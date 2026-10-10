"""Measure the performance, resource-limit and crash-containment gate of the Master runtime.

Everything runs through the real ``MasterRuntime`` / ``WorkerSupervisor`` and the real
native worker (``build-master/Release/cgal-master-worker.exe``). Four stages:

* ``scale``  - one representative validated operation per original major family
  (7.1-7.15), each at three input scales, with peak worker memory.
* ``limits`` - resource-limit refusals (bounded_input, import size, execution limits,
  invalid configuration, wall-time and memory caps) must fail closed with exact codes.
* ``faults`` - crash containment: injected worker faults (through the test-only
  ``scripts/robustness_fault_proxy.py``; the native worker is not modified), real native
  kill/timeout/memory-cap, hostile requests fed to the real worker, hostile import
  files and a killed host process. Every trial must end in a structured terminal job
  state, publish nothing, leave no running process, leak no staging entry and leave the
  runtime able to serve a correct next call.
* ``persistent`` - opt-in persistent workers (native ``--serve`` session protocol 1) and the
  result cache: faults injected into a REUSED pooled process (proxy and real native kill /
  memory cap) must be contained and the process replaced; all fifteen family
  representatives must reproduce one-shot hashes within one reused process and from cache
  hits; job-count / lifetime / memory-residue / executable-change recycling, idle reaping,
  per-cap pools and cache tamper/stale/re-validation/eviction cases. Speed is informational.

The evidence file separates ``deterministic`` (byte-stable, hash-bound) from ``timings``
(wall clock and peak memory: recorded with a declared tolerance, never gated on speed;
only the declared hard limits gate).
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cgal_mcp.master import supervisor as supervisor_module  # noqa: E402
from cgal_mcp.master.errors import MasterError  # noqa: E402
from cgal_mcp.master.resources import ResourceConfig  # noqa: E402
from cgal_mcp.master.runtime import MasterRuntime  # noqa: E402

def _proxy_command(executable: Path, *arguments: str) -> list[str]:
    """Start the test-only .py proxy with the real interpreter, never the venv launcher.

    ``.venv/Scripts/python.exe`` is a launcher that forks the actual interpreter before the
    supervisor can place it in its Job Object, so the proxy would escape kill-on-close. The
    native worker is a single executable and is unaffected.
    """
    if executable.suffix.lower() == ".py":
        return [getattr(sys, "_base_executable", sys.executable), str(executable), *arguments]
    return [str(executable), *arguments]


supervisor_module._command = _proxy_command
GENERATOR = "master-performance-robustness"
EVIDENCE_PATH = "docs/master/evidence/performance-robustness.json"
PROXY = "scripts/robustness_fault_proxy.py"
DEFAULT_WORKER = "build-master/Release/cgal-master-worker.exe"
BINDING_SOURCES = {
    "generator_sha256": "scripts/measure_master_robustness.py",
    "proxy_sha256": PROXY,
    "operations_sha256": "cgal_mcp/master/operations.json",
    "runtime_sha256": "cgal_mcp/master/runtime.py",
    "supervisor_sha256": "cgal_mcp/master/supervisor.py",
    "resources_sha256": "cgal_mcp/master/resources.py",
    "store_sha256": "cgal_mcp/master/store.py",
    "result_cache_sha256": "cgal_mcp/master/result_cache.py",
}
# The Master plan fixes "crash containment 100%" but no trial count. The count is declared
# here and recorded in the evidence; the evaluator holds the evidence to these floors.
TRIALS_PER_MODE = 20
HOST_KILL_TRIALS = 5
MIN_HOST_KILL_TRIALS = 5
HANDLE_GROWTH_TOLERANCE = 32
MIB = 1024 * 1024
SCALE_LABELS = ("small", "medium", "large")
TIMING_POLICY = {
    "gating": "none on wall-clock or RSS comparisons; only hard declared limits gate "
              "(peak worker RSS below the memory ceiling, wall time below the wall limit)",
    "wall_clock_tolerance": "informational; reruns on the same machine are expected within "
                            "a factor of 3 of the recorded value, a slower machine may exceed it",
    "memory_scope": "peak RSS of every compute and validator worker process of the job "
                    "(Windows GetProcessMemoryInfo); excludes the Python host and parsers",
}


# ---------------------------------------------------------------- fixtures

def _grid(rows: int, cols: int, bump: float, flat_z: bool = False, flip_every: int = 0) -> bytes:
    lines = ["OFF", f"{(rows + 1) * (cols + 1)} {2 * rows * cols} 0"]
    for i in range(rows + 1):
        for j in range(cols + 1):
            z = 0.0 if flat_z else bump * math.sin(i * 0.37) * math.cos(j * 0.23)
            lines.append(f"{j} {i} {z:.9f}")
    for i in range(rows):
        for j in range(cols):
            a = i * (cols + 1) + j
            b, c, d = a + 1, a + cols + 1, a + cols + 2
            flip = flip_every and (i * cols + j) % flip_every == 0
            lines.append(f"3 {a} {d} {b}" if flip else f"3 {a} {b} {d}")
            lines.append(f"3 {a} {d} {c}")
    return ("\n".join(lines) + "\n").encode("ascii")


def _random_xyz(count: int, seed: int, cube: bool = False) -> bytes:
    rng = random.Random(seed)
    rows = []
    if cube:
        rows += [f"{x} {y} {z}" for x in (0, 1) for y in (0, 1) for z in (0, 1)]
    while len(rows) < count:
        rows.append(" ".join(f"{rng.random():.17g}" for _ in range(3)))
    return ("\n".join(rows) + "\n").encode("ascii")


def _sphere_xyz(count: int, radius: float = 10.0) -> bytes:
    golden = math.pi * (3.0 - math.sqrt(5.0))
    rows = []
    for index in range(count):
        z = 1.0 - 2.0 * (index + 0.5) / count
        r = math.sqrt(max(0.0, 1.0 - z * z))
        phi = golden * index
        rows.append(f"{radius * r * math.cos(phi):.12g} {radius * r * math.sin(phi):.12g} {radius * z:.12g}")
    return ("\n".join(rows) + "\n").encode("ascii")


def _kernel_queries(count: int) -> bytes:
    rng = random.Random(20261011)
    primitives = [{"id": f"p{i}", "kind": "Point_2",
                   "points": [[str(rng.randint(-1000, 1000)), str(rng.randint(-1000, 1000))]]}
                  for i in range(count)]
    queries = [{"id": f"d{i}", "query": "squared_distance", "arguments": [f"p{i}", f"p{(i + 1) % count}"]}
               for i in range(count)]
    return json.dumps({"primitives": primitives, "queries": queries}, separators=(",", ":")).encode("ascii")


def _parabola_polygon(count: int) -> bytes:
    m = count - 2
    outer = [[i, i * i] for i in range(m + 1)] + [[0, m * m]]
    return json.dumps({"outer": outer, "holes": []}, separators=(",", ":")).encode("ascii")


def _interpolation(sites_per_side: int, queries: int) -> bytes:
    sites = [{"point": [str(i), str(j)], "value": str(3 * i - j + 2), "gradient": ["3", "-1"]}
             for i in range(sites_per_side) for j in range(sites_per_side)]
    rng = random.Random(20261011)
    span = sites_per_side - 1
    qs = [[f"{rng.randint(1, 7 * span - 1)}/7", f"{rng.randint(1, 7 * span - 1)}/7"] for _ in range(queries)]
    return json.dumps({"sites": sites, "queries": qs}, separators=(",", ":")).encode("ascii")


def _mm(value: float) -> dict:
    return {"value": value, "unit": "mm"}


SQUARE10 = b'{"outer":[[0,0],[10,0],[10,10],[0,10]],"holes":[]}'


def _knn_inputs(count: int) -> list[tuple[bytes, str, str, str]]:
    return [(_random_xyz(count, 11), "xyz", "PointSet3", "mm"),
            (_random_xyz(max(10, count // 100), 12), "xyz", "PointSet3", "mm")]


def _mesh_input(rows: int, cols: int, bump: float = 0.3, soup: bool = False, flat: bool = False):
    kind = "PolygonSoup3" if soup else "TriangleSurfaceMesh"
    return [(_grid(rows, cols, bump, flat, 5 if soup else 0), "off", kind, "mm")]


# family, operation, scale axis, three scale values, builder, parameters builder
FAMILY_CASES: list[dict[str, Any]] = [
    {"family": "7.1", "operation": "kernel.distance.squared", "axis": "query_count",
     "scales": [100, 1000, 10000], "probe": 10001, "inputs": lambda n: [(_kernel_queries(n), "json", "KernelQuerySet", "mm")],
     "parameters": lambda n: {"kernel": "epeck"}},
    {"family": "7.2", "operation": "spatial.knn_3", "axis": "point_count",
     "scales": [1000, 5000, 20000], "probe": 50000, "inputs": _knn_inputs,
     "parameters": lambda n: {"k": 5, "search": "orthogonal"}},
    {"family": "7.3", "operation": "mesh.analysis.measures", "axis": "grid_side_faces",
     "scales": [32, 100, 316], "probe": 317, "inputs": lambda n: _mesh_input(n, n), "parameters": lambda n: {}},
    {"family": "7.4", "operation": "mesh.repair.polygon_soup", "axis": "grid_side_faces",
     "scales": [50, 200, 500], "inputs": lambda n: _mesh_input(n, n, soup=True),
     "parameters": lambda n: {"duplicate_polygon_policy": "keep_one", "require_same_orientation": False}},
    {"family": "7.5", "operation": "mesh.clip.plane", "axis": "grid_cols_x_rows",
     "scales": [[4, 6], [8, 15], [17, 17]], "probe": [18, 18], "inputs": lambda n: _mesh_input(n[0], n[1]),
     "parameters": lambda n: {"normal": [1, 0, 0], "offset": _mm(float(n[1] // 2)), "clip_volume": False}},
    {"family": "7.6", "operation": "mesh.remesh.isotropic", "axis": "grid_side_faces",
     "scales": [10, 30, 60], "probe": 100, "inputs": lambda n: _mesh_input(n, n, flat=True),
     "parameters": lambda n: {"target_edge_length": _mm(1.0), "number_of_iterations": 1,
                              "number_of_relaxation_steps": 1, "max_deviation": _mm(0.5)}},
    {"family": "7.7", "operation": "mesh.simplify.edge_collapse", "axis": "grid_side_faces",
     "scales": [8, 12, 14], "probe": 16, "inputs": lambda n: _mesh_input(n, n),
     "parameters": lambda n: {"stop": {"kind": "face_ratio", "value": 0.5}, "policy": "lindstrom_turk",
                              "max_symmetric_deviation": _mm(1.0),
                              "hausdorff_error_bound": _mm(0.05)}},
    {"family": "7.8", "operation": "mesh.subdivide.loop", "axis": "grid_side_faces",
     "scales": [8, 16, 31], "probe": 32, "inputs": lambda n: _mesh_input(n, n), "parameters": lambda n: {"steps": 1}},
    {"family": "7.9", "operation": "pointset.simplify.grid", "axis": "point_count",
     "scales": [1000, 100000, 1000000],
     "inputs": lambda n: [(_random_xyz(n, 21), "xyz", "PointSet3", "mm")],
     "parameters": lambda n: {"cell_size": _mm(0.05), "min_points_per_cell": 1}},
    {"family": "7.10", "operation": "reconstruction.advancing_front", "axis": "point_count",
     "scales": [300, 3000, 15000], "probe": 20001, "inputs": lambda n: [(_sphere_xyz(n), "xyz", "PointSet3", "mm")],
     "parameters": lambda n: {"radius_ratio_bound": 5, "beta": 0.52, "max_deviation": _mm(2.0)}},
    {"family": "7.11", "operation": "triangulation.delaunay_3", "axis": "point_count",
     "scales": [100, 400, 700], "probe": 1000, "inputs": lambda n: [(_random_xyz(n, 31), "xyz", "PointSet3", "mm")],
     "parameters": lambda n: {}},
    {"family": "7.12", "operation": "polygon.analysis.properties", "axis": "vertex_count",
     "scales": [100, 500, 2000], "probe": 10000,
     "inputs": lambda n: [(_parabola_polygon(n), "json", "PolygonWithHoles2", "mm")],
     "parameters": lambda n: {}},
    {"family": "7.13", "operation": "hull.convex_3", "axis": "point_count",
     "scales": [1000, 100000, 1000000],
     "inputs": lambda n: [(_random_xyz(n, 20261005, cube=True), "xyz", "PointSet3", "mm")],
     "parameters": lambda n: {}},
    {"family": "7.14", "operation": "mesh2.refine.delaunay", "axis": "size_bound_mm",
     "scales": [2.0, 1.0, 0.5], "probe": 0.25, "inputs": lambda n: [(SQUARE10, "json", "PolygonWithHoles2", "mm")],
     "parameters": lambda n: {"aspect_bound": 0.125, "size_bound": _mm(n)}},
    {"family": "7.15", "operation": "optimization.interpolate", "axis": "site_count",
     "scales": [[3, 3], [8, 16], [11, 32]], "probe": [12, 33],
     "inputs": lambda n: [(_interpolation(n[0], n[1]), "json", "InterpolationData2", "mm")],
     "parameters": lambda n: {"method": "linear"}},
]


# ---------------------------------------------------------------- helpers

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def bindings(root: Path = REPO) -> dict[str, str]:
    result = {}
    for key, relative in BINDING_SOURCES.items():
        content = (root / relative).read_bytes().replace(b"\r\n", b"\n")
        result[key] = hashlib.sha256(content).hexdigest()
    return result


class _Win:
    """Minimal Windows process helpers (liveness and host handle count)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None

    @classmethod
    def exited(cls, pid: int) -> bool:
        if cls.k32 is None:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            return False
        k = cls.k32
        k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        k.OpenProcess.restype = ctypes.c_void_p
        k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.WaitForSingleObject.restype = ctypes.c_uint32
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return True
        try:
            return k.WaitForSingleObject(handle, 0) == 0
        finally:
            k.CloseHandle(handle)

    @classmethod
    def handle_count(cls) -> int:
        if cls.k32 is None:
            return len(os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else 0
        k = cls.k32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.GetProcessHandleCount.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        count = ctypes.c_uint32()
        k.GetProcessHandleCount(k.GetCurrentProcess(), ctypes.byref(count))
        return int(count.value)


class SpawnRecorder:
    """Record every worker process the supervisor starts (excluding --manifest probes)."""

    def __init__(self) -> None:
        self.processes: list[Any] = []
        self.on_spawn = None
        self._original = asyncio.create_subprocess_exec

    async def _spawn(self, *arguments, **keywords):
        process = await self._original(*arguments, **keywords)
        if "--manifest" not in arguments:
            self.processes.append(process)
            if self.on_spawn is not None:
                self.on_spawn(process)
        return process

    def __enter__(self):
        self._patch = patch.object(asyncio, "create_subprocess_exec", self._spawn)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()

    def all_exited(self) -> bool:
        return all(p.returncode is not None and _Win.exited(p.pid) for p in self.processes)


def _import_inputs(runtime: MasterRuntime, directory: Path, inputs) -> list[dict]:
    imported = []
    for index, (content, extension, kind, unit) in enumerate(inputs):
        path = directory / f"input{index}.{extension}"
        path.write_bytes(content)
        started = time.perf_counter()
        artifact = runtime.artifact_import(str(path), unit, artifact_type=kind)
        inspection = runtime.artifact_inspect(artifact["artifact_id"])
        imported.append({"artifact_id": artifact["artifact_id"], "type": kind, "unit": unit,
                         "sha256": inspection["sha256"], "size": inspection["size"],
                         "metadata": inspection.get("metadata", {}),
                         "import_seconds": time.perf_counter() - started})
    return imported


def _plan(runtime: MasterRuntime, operation: str, imported: list[dict], parameters: dict) -> dict:
    slots = [spec["slot"] for spec in runtime.registry.get(operation)["io"]["inputs"]]
    step = {"id": "s1", "operation": operation,
            "inputs": {slot: item["artifact_id"] for slot, item in zip(slots, imported)},
            "parameters": parameters}
    return runtime.plan({"steps": [step]})


def _error_of(detail: dict) -> dict:
    error = detail.get("error") or {}
    return {"class": error.get("class"), "code": error.get("code")}


async def _run_plan(runtime: MasterRuntime, plan_id: str, **limits) -> dict:
    job = await runtime.execute(plan_id, **limits)
    task = runtime.tasks[job["job_id"]]
    await asyncio.wait_for(task, 900)
    return runtime.job_status(job["job_id"])


def _meter():
    sys.path.insert(0, str(REPO))
    from scripts.measure_master_hull import WindowsMemoryMeter
    return WindowsMemoryMeter()


# ---------------------------------------------------------------- stage: scale

def _input_record(imported: list[dict]) -> list[dict]:
    return [{"type": i["type"], "unit": i["unit"], "sha256": i["sha256"], "size": i["size"],
             "metadata": {k: v for k, v in i["metadata"].items()
                          if k in ("vertices", "faces", "point_count", "max_face_degree")}}
            for i in imported]


async def _scale_case(case: dict, scale: Any, label: str, worker: Path) -> tuple[dict, dict]:
    with tempfile.TemporaryDirectory(prefix="master-scale-") as directory:
        root = Path(directory)
        runtime = MasterRuntime(root / "store", worker=worker)
        deterministic: dict[str, Any] = {
            "family": case["family"], "operation": case["operation"], "scale": label,
            "axis": case["axis"], "scale_value": scale}
        timing: dict[str, Any] = {}
        try:
            imported: list[dict] = []
            try:
                imported = _import_inputs(runtime, root, case["inputs"](scale))
                plan = _plan(runtime, case["operation"], imported, case["parameters"](scale))
            except MasterError as exc:
                deterministic.update({
                    "status": "refused", "job_state": "refused", "validation_status": "not_run",
                    "error": {"class": exc.failure_class, "code": exc.code}, "inputs": _input_record(imported),
                    "output_types": [], "validators_passed": 0, "worker_processes_started": 0,
                    "worker_processes_all_exited": True,
                    "memory_ceiling_mb": runtime.resources.default_memory_mb,
                    "wall_limit_ms": runtime.resources.default_wall_time_ms})
                return deterministic, timing
            meter = _meter() if os.name == "nt" else None
            began = time.perf_counter()
            with SpawnRecorder() as recorder:
                if meter:
                    with patch.object(supervisor_module, "_assign_windows_job", meter.assign):
                        detail = await _run_plan(runtime, plan["plan_id"])
                    memory = meter.finish()
                else:
                    detail = await _run_plan(runtime, plan["plan_id"])
                    memory = {}
                exited = recorder.all_exited()
                spawned = len(recorder.processes)
            timing = {"import_seconds": round(sum(i["import_seconds"] for i in imported), 3),
                      "execution_validation_seconds": round(time.perf_counter() - began, 3), **memory}
            deterministic.update({
                "status": "pass" if detail["state"] == "succeeded" and detail["validation_status"] == "passed"
                          else "fail",
                "job_state": detail["state"], "validation_status": detail["validation_status"],
                "error": _error_of(detail),
                "inputs": _input_record(imported),
                "output_types": sorted({o["type"] for o in detail.get("outputs", [])}),
                "validators_passed": sum(1 for v in detail.get("validation", [])
                                         if v["report"].get("status") == "pass"),
                "worker_processes_started": spawned, "worker_processes_all_exited": exited,
                "memory_ceiling_mb": runtime.resources.default_memory_mb,
                "wall_limit_ms": runtime._default_wall_time(plan),
            })
            timing["output_sha256"] = [o["sha256"] for o in detail.get("outputs", [])]
        finally:
            runtime.close()
    return deterministic, timing


def run_scale(worker: Path, only: list[str] | None = None) -> tuple[list[dict], list[dict], dict]:
    results, probes, timings = [], [], {}
    for case in FAMILY_CASES:
        if only and case["family"] not in only:
            continue
        for index in range(3):
            deterministic, timing = asyncio.run(_scale_case(case, case["scales"][index], SCALE_LABELS[index], worker))
            results.append(deterministic)
            timings[f"{case['family']}:{case['operation']}:{deterministic['scale']}"] = timing
            print(f"scale {case['family']} {case['operation']} {deterministic['scale']}: "
                  f"{deterministic['status']} {timing.get('execution_validation_seconds')}s "
                  f"rss={timing.get('peak_worker_rss_bytes', 0) // MIB}MiB", flush=True)
        if "probe" in case:
            deterministic, timing = asyncio.run(_scale_case(case, case["probe"], "ceiling_probe", worker))
            probes.append(deterministic)
            timings[f"{case['family']}:{case['operation']}:ceiling_probe"] = timing
            print(f"probe {case['family']} {case['operation']} {case['probe']}: {deterministic['job_state']} "
                  f"{deterministic['error']}", flush=True)
    return results, probes, timings


# ---------------------------------------------------------------- stage: limits

def _refusal(stage: str, exc: MasterError) -> dict:
    return {"stage": stage, "class": exc.failure_class, "code": exc.code}


async def _limit_cases(worker: Path) -> tuple[list[dict], dict]:
    cases: list[dict] = []
    timings: dict[str, Any] = {}

    def record(case_id: str, kind: str, expected: dict, observed: dict, **extra) -> None:
        cases.append({"id": case_id, "kind": kind, "expected": expected, "observed": observed,
                      "passed": observed == expected, **extra})
        print(f"limit {case_id}: {'pass' if observed == expected else 'FAIL ' + canonical(observed)}", flush=True)

    with tempfile.TemporaryDirectory(prefix="master-limits-") as directory:
        root = Path(directory)
        runtime = MasterRuntime(root / "store", worker=worker)
        try:
            with SpawnRecorder() as recorder:
                # bounded_input refusals: faces, vertices, bytes
                for case_id, operation, inputs, params in (
                    ("faces-over-limit", "mesh.clip.plane", _mesh_input(18, 18),
                     {"normal": [1, 0, 0], "offset": _mm(9), "clip_volume": False}),
                    ("vertices-over-limit", "shape.bounding.sphere",
                     [(_random_xyz(33, 5), "xyz", "PointSet3", "mm")], {}),
                    ("bytes-over-limit", "reconstruction.advancing_front",
                     [(_sphere_xyz(480000), "xyz", "PointSet3", "mm")],
                     {"radius_ratio_bound": 5, "beta": 0.52, "max_deviation": _mm(2.0)}),
                ):
                    base = runtime.store.counts()["artifacts"]
                    observed = {"stage": "none"}
                    imported = _import_inputs(runtime, root, inputs)
                    limits = next(c for c in runtime.registry.get(operation)["preconditions"]
                                  if c["id"] == "bounded_input")
                    try:
                        plan = _plan(runtime, operation, imported, params)
                        detail = await _run_plan(runtime, plan["plan_id"])
                        observed = {"stage": "execute", **_error_of(detail)} if detail.get("error") else \
                            {"stage": "none", "state": detail["state"]}
                    except MasterError as exc:
                        observed = _refusal("plan", exc)
                    record(case_id, "bounded_input", {"stage": "plan", "class": "unmet_precondition",
                                                      "code": "unmet_precondition"}, observed,
                           operation=operation, declared_limit={k: v for k, v in limits.items() if k != "id"},
                           published_delta=runtime.store.counts()["artifacts"] - base - len(imported))
                # import size limit
                big = root / "big.xyz"
                with big.open("wb") as stream:
                    stream.truncate(512 * MIB + 1)
                observed = {"stage": "none"}
                try:
                    runtime.artifact_import(str(big), "mm", artifact_type="PointSet3")
                except MasterError as exc:
                    observed = _refusal("import", exc)
                big.unlink()
                record("import-over-512MiB", "import_limit",
                       {"stage": "import", "class": "invalid_input", "code": "import_too_large"}, observed)
                # execution limits
                imported = _import_inputs(runtime, root, [(_random_xyz(200, 7, cube=True), "xyz", "PointSet3", "mm")])
                plan = _plan(runtime, "hull.convex_3", imported, {})
                for case_id, limits in (("wall-zero", {"wall_time_ms": 0}),
                                        ("wall-negative", {"wall_time_ms": -5}),
                                        ("wall-above-max", {"wall_time_ms": 86_400_001}),
                                        ("wall-boolean", {"wall_time_ms": True}),
                                        ("wall-string", {"wall_time_ms": "100"}),
                                        ("memory-below-64MiB", {"memory_mb": 63}),
                                        ("memory-above-ceiling", {"memory_mb": 4097}),
                                        ("memory-boolean", {"memory_mb": True}),
                                        ("memory-float", {"memory_mb": 512.0})):
                    observed = {"stage": "none"}
                    try:
                        await runtime.execute(plan["plan_id"], **limits)
                    except MasterError as exc:
                        observed = _refusal("execute_limits", exc)
                    record(case_id, "execution_limits",
                           {"stage": "execute_limits", "class": "invalid_input", "code": "execution_limits"},
                           observed, limits=limits)
                # invalid host configuration
                for case_id, factory in (
                    ("config-concurrency-zero", lambda: ResourceConfig(concurrency=0)),
                    ("config-memory-below-64", lambda: ResourceConfig(max_memory_mb=63, default_memory_mb=63)),
                    ("config-default-above-ceiling",
                     lambda: ResourceConfig(max_memory_mb=1024, default_memory_mb=2048)),
                    ("config-wall-inverted",
                     lambda: ResourceConfig(default_wall_time_ms=5000, max_wall_time_ms=1000)),
                    ("config-float-memory", lambda: ResourceConfig(max_memory_mb=512.5)),
                ):
                    observed = {"stage": "none"}
                    try:
                        factory()
                    except ValueError:
                        observed = {"stage": "config", "class": "ValueError", "code": "rejected_at_startup"}
                    record(case_id, "configuration",
                           {"stage": "config", "class": "ValueError", "code": "rejected_at_startup"}, observed)
                for case_id, name, value in (("env-memory-text", "CGAL_MASTER_MAX_MEMORY_MB", "lots"),
                                             ("env-concurrency-noncanonical", "CGAL_MASTER_CONCURRENCY", "02"),
                                             ("env-wall-out-of-range", "CGAL_MASTER_DEFAULT_WALL_TIME_MS", "0")):
                    observed = {"stage": "none"}
                    with patch.dict(os.environ, {name: value}):
                        try:
                            ResourceConfig.from_environment()
                        except ValueError:
                            observed = {"stage": "config", "class": "ValueError", "code": "rejected_at_startup"}
                    record(case_id, "configuration",
                           {"stage": "config", "class": "ValueError", "code": "rejected_at_startup"}, observed)
                # real wall-time cap (native process killed) and real memory cap
                big_points = root / "hull-large.xyz"
                big_points.write_bytes(_random_xyz(1000000, 20261005, cube=True))
                artifact = runtime.artifact_import(str(big_points), "mm", artifact_type="PointSet3")
                big_imported = [{"artifact_id": artifact["artifact_id"]}]
                big_plan = _plan(runtime, "hull.convex_3", big_imported, {})
                for trial_kind, limits, expected in (
                    ("wall-cap-native", {"wall_time_ms": 100},
                     {"stage": "execute", "class": "timeout", "code": "worker_timeout"}),
                    ("memory-cap-native", {"memory_mb": 64},
                     {"stage": "execute", "class": "resource_limit", "code": "memory_limit"}),
                ):
                    seen = set()
                    began = time.perf_counter()
                    base_spawn = len(recorder.processes)
                    for _ in range(TRIALS_PER_MODE):
                        detail = await _run_plan(runtime, big_plan["plan_id"], **limits)
                        seen.add(canonical({"stage": "execute", **_error_of(detail)}
                                           if detail["state"] != "succeeded" else {"state": detail["state"]}))
                    spawned = recorder.processes[base_spawn:]
                    record(trial_kind, "native_resource_cap", expected,
                           json.loads(next(iter(seen))) if len(seen) == 1 else {"mixed": sorted(seen)},
                           trials=TRIALS_PER_MODE, limits=limits,
                           processes_all_exited=all(p.returncode is not None and _Win.exited(p.pid)
                                                    for p in spawned),
                           published_delta=0)
                    timings[trial_kind] = {"seconds_per_trial": round((time.perf_counter() - began) / TRIALS_PER_MODE, 3)}
        finally:
            runtime.close()
    return cases, timings


# ---------------------------------------------------------------- stage: faults

# mode -> (expected class, code) or None when the real worker/validator decides (then
# the observed set must still be a structured, terminal, non-publishing failure).
FAULT_MODES: dict[str, dict[str, Any]] = {
    "exit_kill": {"expect": ("worker_crash", "worker_crash")},
    "abort": {"expect": ("worker_crash", "worker_crash")},
    "access_violation": {"expect": ("worker_crash", "worker_crash")},
    "hang": {"expect": ("timeout", "worker_timeout"), "wall_ms": 1000},
    "hang_with_child": {"expect": ("timeout", "worker_timeout"), "wall_ms": 1000, "child": True},
    "hang_partial_output": {"expect": ("timeout", "worker_timeout"), "wall_ms": 1000},
    "empty_stdout": {"expect": ("worker_protocol", "worker_response_malformed")},
    "garbage_stdout": {"expect": ("worker_protocol", "worker_response_malformed")},
    "multi_line_stdout": {"expect": ("worker_protocol", "worker_response_malformed")},
    "oversized_stdout": {"expect": ("worker_protocol", "worker_stdout_limit")},
    "stderr_flood_exit": {"expect": ("worker_crash", "worker_crash")},
    "wrong_request_id": {"expect": ("worker_protocol", "worker_response_identity")},
    "bad_schema": {"expect": ("worker_protocol", "worker_response_schema")},
    "output_path_escape": {"expect": ("worker_protocol", "worker_output_path")},
    "error_response_unknown_class": {"expect": ("worker_error", "x")},
    "truncate_output": {"expect": None},
    "garbage_output": {"expect": None},
    "native_garbage_request": {"expect": None},
    "native_truncated_request": {"expect": None},
    "native_empty_request": {"expect": None},
    "native_wrong_protocol": {"expect": None},
    "native_unknown_operation": {"expect": None},
    "native_missing_input_file": {"expect": None},
    "native_bad_output_dir": {"expect": None},
}

GARBAGE_IMPORTS: list[tuple[str, bytes, str, str]] = [
    ("random-bytes-xyz", bytes(range(256)) * 40, "xyz", "PointSet3"),
    ("nul-bytes-off", b"\x00" * 4096, "off", "TriangleSurfaceMesh"),
    ("truncated-off-header", b"OFF\n99999999 99999999 0\n0 0 0\n", "off", "TriangleSurfaceMesh"),
    ("nan-coordinates-xyz", b"0 0 0\nnan 1 1\n1 inf 1\n1 1 1\n", "xyz", "PointSet3"),
    ("huge-face-count-off", b"OFF\n3 2000000000 0\n0 0 0\n1 0 0\n0 1 0\n", "off", "TriangleSurfaceMesh"),
    ("index-out-of-range-off", b"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 7\n", "off", "TriangleSurfaceMesh"),
    ("deep-json", b"[" * 100000 + b"]" * 100000, "json", "KernelQuerySet"),
    ("binary-ply-lie", b"ply\nformat binary_little_endian 1.0\nelement vertex 1000000000\n"
                       b"property float x\nproperty float y\nproperty float z\nend_header\n\x00\x01", "ply",
     "PointSet3"),
    ("empty-file", b"", "xyz", "PointSet3"),
    ("utf16-text", "0 0 0\n1 1 1\n".encode("utf-16"), "xyz", "PointSet3"),
    ("wrong-type-json", b'{"outer": "nope", "holes": 3}', "json", "PolygonWithHoles2"),
    ("unterminated-json", b'{"primitives": [', "json", "KernelQuerySet"),
]


async def _fault_mode(mode: str, spec: dict, worker: Path, proxy_env: dict) -> tuple[dict, dict]:
    with tempfile.TemporaryDirectory(prefix=f"master-fault-{mode}-") as directory:
        root = Path(directory)
        runtime = MasterRuntime(root / "store", worker=REPO / PROXY)
        pidfile = root / "grandchild.pid"
        os.environ["CGAL_ROBUST_REAL_WORKER"] = str(worker)
        os.environ["CGAL_ROBUST_PIDFILE"] = str(pidfile)
        try:
            imported = _import_inputs(runtime, root, [(_random_xyz(200, 7, cube=True), "xyz", "PointSet3", "mm")])
            plan = _plan(runtime, "hull.convex_3", imported, {})
            os.environ["CGAL_ROBUST_FAULT"] = "none"
            golden_detail = await _run_plan(runtime, plan["plan_id"])
            assert golden_detail["state"] == "succeeded", golden_detail
            golden = [o["sha256"] for o in golden_detail["outputs"]]
            baseline_artifacts = runtime.store.counts()["artifacts"]
            handles_before = _Win.handle_count()
            outcomes: dict[str, int] = {}
            failures: list[str] = []
            seconds = []
            quarantine_before = len(list(runtime.store.quarantine_root.iterdir()))
            for trial in range(TRIALS_PER_MODE):
                pidfile.unlink(missing_ok=True)
                os.environ["CGAL_ROBUST_FAULT"] = mode
                began = time.perf_counter()
                with SpawnRecorder() as recorder:
                    limits = {"wall_time_ms": spec["wall_ms"]} if "wall_ms" in spec else {}
                    detail = await _run_plan(runtime, plan["plan_id"], **limits)
                    seconds.append(time.perf_counter() - began)
                    exited = recorder.all_exited()
                    spawned = len(recorder.processes)
                observed = (detail["state"], *(_error_of(detail).values()))
                key = canonical(list(observed))
                outcomes[key] = outcomes.get(key, 0) + 1
                problems = []
                if detail["state"] not in {"failed", "rejected"} or not all(observed[1:]):
                    problems.append("not a structured terminal failure")
                if spec["expect"] and tuple(observed[1:]) != spec["expect"]:
                    problems.append(f"unexpected error {observed[1:]}")
                if runtime.store.counts()["artifacts"] != baseline_artifacts:
                    problems.append("artifact published by a failed job")
                if detail.get("outputs"):
                    problems.append("failed job exposes outputs")
                if list(runtime.store.staging_root.iterdir()):
                    problems.append("staging entry left behind")
                if not exited or spawned < 1:
                    problems.append("worker process left running or never started")
                if spec.get("child"):
                    if not pidfile.exists() or not _Win.exited(int(pidfile.read_text())):
                        problems.append("grandchild process left running")
                if runtime.tasks:
                    problems.append("runtime still holds a job task")
                os.environ["CGAL_ROBUST_FAULT"] = "none"
                recovery = await _run_plan(runtime, plan["plan_id"])
                if (recovery["state"] != "succeeded" or recovery["validation_status"] != "passed"
                        or [o["sha256"] for o in recovery["outputs"]] != golden):
                    problems.append("next call did not reproduce the golden result")
                runtime.store.counts()
                baseline_artifacts = runtime.store.counts()["artifacts"]
                if problems:
                    failures.append(f"trial {trial}: " + "; ".join(problems))
            quarantine_after = len(list(runtime.store.quarantine_root.iterdir()))
            handle_growth = _Win.handle_count() - handles_before
            deterministic = {
                "mode": mode, "trials": TRIALS_PER_MODE, "contained": TRIALS_PER_MODE - len(failures),
                "failures": failures, "outcomes": dict(sorted(outcomes.items())),
                "expected": list(spec["expect"]) if spec["expect"] else None,
                "quarantined_jobs": quarantine_after - quarantine_before,
                "host_handle_growth_within_tolerance": handle_growth <= HANDLE_GROWTH_TOLERANCE,
            }
            timing = {"mean_trial_seconds": round(sum(seconds) / len(seconds), 3),
                      "host_handle_growth": handle_growth}
        finally:
            os.environ["CGAL_ROBUST_FAULT"] = "none"
            runtime.close()
    print(f"fault {mode}: {deterministic['contained']}/{TRIALS_PER_MODE} contained "
          f"{timing['mean_trial_seconds']}s/trial", flush=True)
    return deterministic, timing


async def _kill_native(worker: Path) -> tuple[dict, dict]:
    """Terminate the REAL native worker from outside while it computes; repeat."""
    with tempfile.TemporaryDirectory(prefix="master-native-kill-") as directory:
        root = Path(directory)
        runtime = MasterRuntime(root / "store", worker=worker)
        try:
            imported = _import_inputs(runtime, root, [(_random_xyz(300000, 20261005, cube=True), "xyz", "PointSet3", "mm")])
            plan = _plan(runtime, "hull.convex_3", imported, {})
            small = _import_inputs(runtime, root, [(_random_xyz(200, 7, cube=True), "xyz", "PointSet3", "mm")])
            small_plan = _plan(runtime, "hull.convex_3", small, {})
            golden = (await _run_plan(runtime, small_plan["plan_id"]))["outputs"][0]["sha256"]
            base = runtime.store.counts()["artifacts"]
            outcomes: dict[str, int] = {}
            failures = []
            for trial in range(TRIALS_PER_MODE):
                with SpawnRecorder() as recorder:
                    loop = asyncio.get_running_loop()
                    recorder.on_spawn = lambda process: loop.call_later(0.15, _terminate, process)
                    detail = await _run_plan(runtime, plan["plan_id"])
                    exited = recorder.all_exited()
                observed = (detail["state"], *(_error_of(detail).values()))
                outcomes[canonical(list(observed))] = outcomes.get(canonical(list(observed)), 0) + 1
                problems = []
                if observed != ("failed", "worker_crash", "worker_crash"):
                    problems.append(f"unexpected outcome {observed}")
                if runtime.store.counts()["artifacts"] != base or list(runtime.store.staging_root.iterdir()):
                    problems.append("publication or staging leak")
                if not exited:
                    problems.append("process left running")
                recovery = await _run_plan(runtime, small_plan["plan_id"])
                if recovery["state"] != "succeeded" or recovery["outputs"][0]["sha256"] != golden:
                    problems.append("next call incorrect")
                base = runtime.store.counts()["artifacts"]
                if problems:
                    failures.append(f"trial {trial}: " + "; ".join(problems))
            deterministic = {"mode": "native_external_kill", "trials": TRIALS_PER_MODE,
                             "contained": TRIALS_PER_MODE - len(failures), "failures": failures,
                             "outcomes": dict(sorted(outcomes.items())),
                             "expected": ["worker_crash", "worker_crash"]}
        finally:
            runtime.close()
    print(f"fault native_external_kill: {deterministic['contained']}/{TRIALS_PER_MODE}", flush=True)
    return deterministic, {}


def _terminate(process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass


async def _garbage_imports(worker: Path) -> tuple[dict, dict]:
    with tempfile.TemporaryDirectory(prefix="master-garbage-") as directory:
        root = Path(directory)
        runtime = MasterRuntime(root / "store", worker=worker)
        try:
            good = _import_inputs(runtime, root, [(_random_xyz(200, 7, cube=True), "xyz", "PointSet3", "mm")])
            plan = _plan(runtime, "hull.convex_3", good, {})
            golden = (await _run_plan(runtime, plan["plan_id"]))["outputs"][0]["sha256"]
            base = runtime.store.counts()["artifacts"]
            rows, failures = [], []
            for name, content, extension, kind in GARBAGE_IMPORTS:
                path = root / f"garbage.{extension}"
                path.write_bytes(content)
                observed = {"result": "accepted"}
                try:
                    runtime.artifact_import(str(path), "mm", artifact_type=kind)
                except MasterError as exc:
                    observed = {"result": "refused", "class": exc.failure_class, "code": exc.code}
                except Exception as exc:  # an unstructured crash would be a containment failure
                    observed = {"result": "unstructured", "exception": type(exc).__name__}
                rows.append({"name": name, **observed})
                if observed["result"] != "refused":
                    failures.append(f"{name}: {observed}")
                if runtime.store.counts()["artifacts"] != base or list(runtime.store.staging_root.iterdir()):
                    failures.append(f"{name}: store or staging changed")
                after = await _run_plan(runtime, plan["plan_id"])
                if after["state"] != "succeeded" or after["outputs"][0]["sha256"] != golden:
                    failures.append(f"{name}: next call incorrect")
                base = runtime.store.counts()["artifacts"]
            # a stored input that is corrupted on disk after import must be caught before the worker runs
            stored = runtime.store.managed_path(good[0]["artifact_id"])
            original = stored.read_bytes()
            os.chmod(stored, 0o666)
            stored.write_bytes(original + b"corrupt\n")
            tampered = await _run_plan(runtime, plan["plan_id"])
            tamper_result = {"state": tampered["state"], **_error_of(tampered)}
            stored.write_bytes(original)
            if tampered["state"] != "failed" or not tamper_result["code"]:
                failures.append(f"tampered store blob: {tamper_result}")
            restored = await _run_plan(runtime, plan["plan_id"])
            if restored["state"] != "succeeded":
                failures.append("restored blob did not run")
            deterministic = {"mode": "garbage_input_files", "trials": len(GARBAGE_IMPORTS) + 1,
                             "contained": len(GARBAGE_IMPORTS) + 1 - len(failures), "failures": failures,
                             "refusals": rows, "tampered_store_blob": tamper_result}
        finally:
            runtime.close()
    print(f"fault garbage_input_files: {deterministic['contained']}/{deterministic['trials']}", flush=True)
    return deterministic, {}


def _host_victim(store: Path, worker: Path, fixture: Path, pidfile: Path) -> None:
    """Child entry point: start a job that hangs in the proxy, publish worker PIDs, wait to be killed."""
    os.environ["CGAL_ROBUST_REAL_WORKER"] = str(worker)
    os.environ["CGAL_ROBUST_FAULT"] = "hang"

    async def go() -> None:
        runtime = MasterRuntime(store, worker=REPO / PROXY)
        artifact = runtime.artifact_import(str(fixture), "mm", artifact_type="PointSet3")
        plan = _plan(runtime, "hull.convex_3", [artifact], {})
        with SpawnRecorder() as recorder:
            recorder.on_spawn = lambda process: pidfile.write_text(f"{process.pid}\n{os.getpid()}\n")
            await runtime.execute(plan["plan_id"])
            await asyncio.sleep(3600)
    asyncio.run(go())


def _host_kill(worker: Path) -> tuple[dict, dict]:
    failures, outcomes = [], {}
    for trial in range(HOST_KILL_TRIALS):
        with tempfile.TemporaryDirectory(prefix="master-host-kill-") as directory:
            root = Path(directory)
            fixture = root / "in.xyz"
            fixture.write_bytes(_random_xyz(200, 7, cube=True))
            pidfile = root / "pids.txt"
            host = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--host-victim",
                                     str(root / "store"), str(worker), str(fixture), str(pidfile)])
            try:
                deadline = time.time() + 60
                while time.time() < deadline and not (pidfile.exists() and len(pidfile.read_text().split()) >= 2):
                    time.sleep(0.05)
                problems = []
                if not pidfile.exists():
                    failures.append(f"trial {trial}: worker never started"); host.kill(); continue
                worker_pid = int(pidfile.read_text().split()[0])
                time.sleep(0.2)
                host.kill(); host.wait(timeout=30)
                limit = time.time() + 10
                while time.time() < limit and not _Win.exited(worker_pid):
                    time.sleep(0.05)
                if not _Win.exited(worker_pid):
                    problems.append("worker survived the death of its host")
                runtime = MasterRuntime(root / "store", worker=worker)
                try:
                    states = [runtime.store.get_job(row) for row in
                              [p.name for p in runtime.store.quarantine_root.iterdir()]] or []
                    jobs = runtime.store._db.execute("SELECT job_id,state,execution_status FROM jobs").fetchall()
                    state = [(r["state"], r["execution_status"]) for r in jobs]
                    outcomes[canonical(state)] = outcomes.get(canonical(state), 0) + 1
                    if state != [("failed", "interrupted")]:
                        problems.append(f"job not recovered as interrupted: {state}")
                    if list(runtime.store.staging_root.iterdir()):
                        problems.append("staging entry survived recovery")
                    good = runtime.artifact_import(str(fixture), "mm", artifact_type="PointSet3")
                    plan = _plan(runtime, "hull.convex_3", [good], {})
                    after = asyncio.run(_run_plan(runtime, plan["plan_id"]))
                    if after["state"] != "succeeded" or after["validation_status"] != "passed":
                        problems.append("new host could not serve a call")
                finally:
                    runtime.close()
                if problems:
                    failures.append(f"trial {trial}: " + "; ".join(problems))
            finally:
                if host.poll() is None:
                    host.kill()
    deterministic = {"mode": "host_process_killed", "trials": HOST_KILL_TRIALS,
                     "contained": HOST_KILL_TRIALS - len(failures), "failures": failures,
                     "outcomes": dict(sorted(outcomes.items()))}
    print(f"fault host_process_killed: {deterministic['contained']}/{HOST_KILL_TRIALS}", flush=True)
    return deterministic, {}


async def _lifecycle(worker: Path) -> dict:
    """Default-mode idle footprint: per-call process, no result cache, no idle child."""
    with tempfile.TemporaryDirectory(prefix="master-lifecycle-") as directory:
        root = Path(directory)
        runtime = MasterRuntime(root / "store", worker=worker)
        try:
            imported = _import_inputs(runtime, root, [(_random_xyz(1000, 3, cube=True), "xyz", "PointSet3", "mm")])
            plan = _plan(runtime, "hull.convex_3", imported, {})
            with SpawnRecorder() as recorder:
                first = await _run_plan(runtime, plan["plan_id"])
                first_pids = [p.pid for p in recorder.processes]
                second = await _run_plan(runtime, plan["plan_id"])
                all_pids = [p.pid for p in recorder.processes]
                idle_children = sum(1 for p in recorder.processes if not _Win.exited(p.pid))
            return {
                "operation": "hull.convex_3",
                "processes_first_call": len(first_pids),
                "processes_second_call": len(all_pids) - len(first_pids),
                "second_call_reused_a_process": bool(set(first_pids) & set(all_pids[len(first_pids):])),
                "second_call_executed_worker": len(all_pids) > len(first_pids),
                "result_identical": [o["sha256"] for o in first["outputs"]] == [o["sha256"] for o in second["outputs"]],
                "idle_worker_processes_after_jobs": idle_children,
                "default_mode": "one_shot",
                "persistent_worker_pool": "opt_in (CGAL_MASTER_PERSISTENT_WORKERS=1); see persistent stage",
                "operation_result_cache": "opt_in (CGAL_MASTER_RESULT_CACHE=1); see persistent stage",
            }
        finally:
            runtime.close()


def run_faults(worker: Path, only: list[str] | None = None) -> tuple[dict, dict]:
    modes, timings = {}, {}
    proxy_env: dict = {}
    for mode, spec in FAULT_MODES.items():
        if only and mode not in only:
            continue
        modes[mode], timings[mode] = asyncio.run(_fault_mode(mode, spec, worker, proxy_env))
    if not only or "native_external_kill" in only:
        modes["native_external_kill"], timings["native_external_kill"] = asyncio.run(_kill_native(worker))
    if not only or "garbage_input_files" in only:
        modes["garbage_input_files"], timings["garbage_input_files"] = asyncio.run(_garbage_imports(worker))
    if not only or "host_process_killed" in only:
        modes["host_process_killed"], timings["host_process_killed"] = _host_kill(worker)
    return modes, timings


# ---------------------------------------------------------------- stage: persistent workers and cache

# Persistent-worker fault modes (session protocol through the test-only proxy, which relays to
# ONE real `--serve` native worker). Expected (class, code) per mode.
PERSISTENT_FAULT_MODES: dict[str, dict[str, Any]] = {
    "exit_kill": {"expect": ("worker_crash", "worker_crash")},
    "abort": {"expect": ("worker_crash", "worker_crash")},
    "access_violation": {"expect": ("worker_crash", "worker_crash")},
    "hang": {"expect": ("timeout", "worker_timeout"), "wall_ms": 1000},
    "hang_with_child": {"expect": ("timeout", "worker_timeout"), "wall_ms": 1000, "child": True},
    "garbage_stdout": {"expect": ("worker_protocol", "worker_response_malformed")},
    "multi_line_stdout": {"expect": ("worker_protocol", "worker_response_identity")},
    "trailing_garbage": {"expect": ("worker_protocol", "worker_response_malformed")},
    "oversized_stdout": {"expect": ("worker_protocol", "worker_stdout_limit")},
    "wrong_request_id": {"expect": ("worker_protocol", "worker_response_identity")},
    "stderr_flood_exit": {"expect": ("worker_crash", "worker_crash")},
}
PERSISTENT_NATIVE_MODES = ("native_external_kill", "native_memory_cap")


def _persistent_runtime(store: Path, worker: Path, **policy) -> MasterRuntime:
    from cgal_mcp.master.supervisor import PersistentPolicy
    return MasterRuntime(store, worker=worker, persistent_workers=PersistentPolicy(**policy))


async def _persistent_fault_mode(mode: str, spec: dict, worker: Path) -> tuple[dict, dict]:
    """Warm a pooled worker, fault the REUSED process, then require a replacement and golden output."""
    with tempfile.TemporaryDirectory(prefix=f"master-pfault-{mode}-") as directory:
        root = Path(directory)
        fault_file = root / "fault.txt"
        fault_file.write_text("none", encoding="ascii")
        pidfile = root / "grandchild.pid"
        os.environ["CGAL_ROBUST_REAL_WORKER"] = str(worker)
        os.environ["CGAL_ROBUST_PIDFILE"] = str(pidfile)
        os.environ["CGAL_ROBUST_FAULT_FILE"] = str(fault_file)
        os.environ["CGAL_ROBUST_FAULT"] = "none"
        native = mode in PERSISTENT_NATIVE_MODES
        runtime = _persistent_runtime(root / "store", worker if native else REPO / PROXY)
        all_spawned: list[Any] = []
        failures: list[str] = []
        outcomes: dict[str, int] = {}
        reused_into_fault = replaced_after_fault = 0
        seconds = []
        try:
            small = _import_inputs(runtime, root, [(_random_xyz(200, 7, cube=True), "xyz", "PointSet3", "mm")])
            plan = _plan(runtime, "hull.convex_3", small, {})
            fault_plan = plan
            limits: dict[str, Any] = {"wall_time_ms": spec["wall_ms"]} if "wall_ms" in spec else {}
            if native:
                count = 300000 if mode == "native_external_kill" else 1000000
                big = _import_inputs(runtime, root, [(_random_xyz(count, 20261005, cube=True), "xyz", "PointSet3", "mm")])
                fault_plan = _plan(runtime, "hull.convex_3", big, {})
                if mode == "native_memory_cap":
                    limits = {"memory_mb": 64}
            with SpawnRecorder() as recorder:
                golden_detail = await _run_plan(runtime, plan["plan_id"])
                assert golden_detail["state"] == "succeeded", golden_detail
                golden = [o["sha256"] for o in golden_detail["outputs"]]
                all_spawned.extend(recorder.processes)
            for trial in range(TRIALS_PER_MODE):
                problems = []
                pidfile.unlink(missing_ok=True)
                if native and mode == "native_memory_cap":
                    # warm a pooled worker with the SAME memory cap so the faulted job reuses it
                    await _run_plan(runtime, plan["plan_id"], memory_mb=64)
                base_artifacts = runtime.store.counts()["artifacts"]
                idle_before = {w.process.pid for w in runtime.supervisor._idle}
                began = time.perf_counter()
                with SpawnRecorder() as recorder:
                    if mode == "native_external_kill":
                        loop = asyncio.get_running_loop()

                        def kill_busy() -> None:
                            for busy in list(runtime.supervisor._busy):
                                _terminate(busy.process)
                        loop.call_later(0.15, kill_busy)
                    else:
                        fault_file.write_text(mode if not native else "none", encoding="ascii")
                    detail = await _run_plan(runtime, fault_plan["plan_id"], **limits)
                    fault_file.write_text("none", encoding="ascii")
                    spawned_in_fault = list(recorder.processes)
                seconds.append(time.perf_counter() - began)
                all_spawned.extend(spawned_in_fault)
                observed = (detail["state"], *(_error_of(detail).values()))
                outcomes[canonical(list(observed))] = outcomes.get(canonical(list(observed)), 0) + 1
                if tuple(observed[1:]) != spec["expect"] or detail["state"] not in {"failed", "rejected"}:
                    problems.append(f"unexpected outcome {observed}")
                used = idle_before - {w.process.pid for w in runtime.supervisor._idle}
                if not spawned_in_fault and len(used) == 1:
                    reused_into_fault += 1
                else:
                    problems.append("faulted job did not run on a reused persistent worker")
                if runtime.store.counts()["artifacts"] != base_artifacts or detail.get("outputs"):
                    problems.append("artifact published by a failed job")
                if list(runtime.store.staging_root.iterdir()):
                    problems.append("staging entry left behind")
                if any(not _Win.exited(pid) for pid in used):
                    problems.append("faulted persistent worker still running")
                if spec.get("child") and (not pidfile.exists() or not _Win.exited(int(pidfile.read_text()))):
                    problems.append("grandchild process left running")
                with SpawnRecorder() as recorder:
                    # same cap as the faulted job, so the replacement is observable in that pool
                    recovery = await _run_plan(runtime, plan["plan_id"],
                                               **({"memory_mb": 64} if mode == "native_memory_cap" else {}))
                    respawned = list(recorder.processes)
                all_spawned.extend(respawned)
                if respawned:
                    replaced_after_fault += 1
                else:
                    problems.append("faulted worker was not replaced by a new process")
                if (recovery["state"] != "succeeded" or recovery["validation_status"] != "passed"
                        or [o["sha256"] for o in recovery["outputs"]] != golden):
                    problems.append("next call did not reproduce the golden result")
                if runtime.tasks:
                    problems.append("runtime still holds a job task")
                if problems:
                    failures.append(f"trial {trial}: " + "; ".join(problems))
            pool = runtime.supervisor.pool_status()
            await runtime.supervisor.shutdown()
            leaked = [p.pid for p in all_spawned if not (p.returncode is not None and _Win.exited(p.pid))]
            if leaked:
                failures.append(f"{len(leaked)} worker process(es) alive after pool shutdown")
        finally:
            for key in ("CGAL_ROBUST_FAULT_FILE",):
                os.environ.pop(key, None)
            os.environ["CGAL_ROBUST_FAULT"] = "none"
            runtime.close()
    deterministic = {"mode": mode, "trials": TRIALS_PER_MODE,
                     "contained": TRIALS_PER_MODE - len([f for f in failures if f.startswith("trial")]),
                     "failures": failures, "outcomes": dict(sorted(outcomes.items())),
                     "expected": list(spec["expect"]),
                     "faulted_job_ran_on_reused_worker": reused_into_fault,
                     "replacement_started_after_fault": replaced_after_fault,
                     "recycle_reasons": sorted(pool["recycled"])}
    if failures and deterministic["contained"] == TRIALS_PER_MODE:
        deterministic["contained"] = TRIALS_PER_MODE - 1  # a pool-level leak fails the mode
    print(f"persistent fault {mode}: {deterministic['contained']}/{TRIALS_PER_MODE} contained", flush=True)
    return deterministic, {"mean_trial_seconds": round(sum(seconds) / max(1, len(seconds)), 3)}


def _prepare_smalls(runtime: MasterRuntime, root: Path) -> dict[str, str]:
    plans = {}
    for case in FAMILY_CASES:
        tag = f"{case['family']}:{case['operation']}"
        imported = _import_inputs(runtime, _newdir(root / tag.replace(":", "_").replace(".", "_")),
                                  case["inputs"](case["scales"][0]))
        plans[tag] = _plan(runtime, case["operation"], imported, case["parameters"](case["scales"][0]))["plan_id"]
    return plans


async def _run_family_smalls(runtime: MasterRuntime, plans: dict[str, str], tags: list[str]) -> tuple[dict, dict]:
    hashes, seconds = {}, {}
    for tag in tags:
        began = time.perf_counter()
        detail = await _run_plan(runtime, plans[tag])
        seconds[tag] = round(time.perf_counter() - began, 4)
        hashes[tag] = ([o["sha256"] for o in detail["outputs"]]
                       if detail["state"] == "succeeded" and detail["validation_status"] == "passed"
                       else [f"failed:{_error_of(detail)}"])
    return hashes, seconds


async def _persistent_isolation(worker: Path) -> tuple[dict, dict]:
    """All fifteen family representatives (small scale) on the SAME store and input artifacts:
    one-shot twice, then ONE persistent process forward, reversed and forward again, then the
    result cache (miss pass, hit pass). Any difference on a reproducible operation is cross-job
    contamination (persistent) or a wrong cache answer."""
    from cgal_mcp.master.result_cache import ResultCache
    from cgal_mcp.master.supervisor import PersistentPolicy
    with tempfile.TemporaryDirectory(prefix="master-pisol-") as directory:
        root = Path(directory)
        runtime = MasterRuntime(root / "store", worker=worker)
        try:
            plans = _prepare_smalls(runtime, root)
            tags = list(plans)
            first, t_one = await _run_family_smalls(runtime, plans, tags)
            second, _ = await _run_family_smalls(runtime, plans, tags)
            runtime.supervisor.persistent = PersistentPolicy(
                max_jobs_per_worker=100_000, max_lifetime_s=86_400, idle_timeout_s=3_600,
                recycle_private_fraction=1.0)
            with SpawnRecorder() as recorder:
                forward, t_cold = await _run_family_smalls(runtime, plans, tags)
                reverse, _ = await _run_family_smalls(runtime, plans, list(reversed(tags)))
                warm, t_warm = await _run_family_smalls(runtime, plans, tags)
                spawned = len(recorder.processes)
            pool = runtime.supervisor.pool_status()
            await runtime.supervisor.shutdown()
            runtime.supervisor.persistent = None
            runtime.result_cache = ResultCache(root / "cache", registry_revision=runtime.registry.revision)
            miss, t_miss = await _run_family_smalls(runtime, plans, tags)
            hit, t_hit = await _run_family_smalls(runtime, plans, tags)
            cache_status = runtime.result_cache.status()
        finally:
            runtime.close()
    reproducible = sorted(tag for tag in first if first[tag] == second[tag] and not first[tag][0].startswith("failed"))
    mismatches = sorted(tag for tag in reproducible
                        if not (forward[tag] == reverse[tag] == warm[tag] == first[tag]))
    cache_mismatch = sorted(tag for tag in reproducible if not (miss[tag] == hit[tag] == first[tag]))
    deterministic = {
        "operations": len(FAMILY_CASES), "reproducible_one_shot": len(reproducible),
        "non_reproducible_one_shot": sorted(set(first) - set(reproducible)),
        "persistent_processes_started": spawned,
        "persistent_requests_reused": pool["reused"],
        "persistent_mismatches": mismatches,
        "persistent_identical_to_one_shot": not mismatches and len(reproducible) > 0,
        "cache_hits": cache_status["hits"], "cache_misses": cache_status["misses"],
        "cache_mismatches": cache_mismatch,
        "cache_identical_to_one_shot": not cache_mismatch and len(reproducible) > 0,
    }
    speed = {tag: {"one_shot_s": t_one[tag], "persistent_cold_s": t_cold[tag], "persistent_warm_s": t_warm[tag],
                   "cache_miss_s": t_miss[tag], "cache_hit_s": t_hit[tag]} for tag in t_one}
    total = {key: round(sum(row[key] for row in speed.values()), 3) for key in next(iter(speed.values()))}
    print(f"persistent isolation: reproducible={len(reproducible)} mismatches={mismatches} "
          f"cache_mismatch={cache_mismatch} processes={spawned} totals={total}", flush=True)
    return deterministic, {"per_operation": speed, "totals_s": total,
                           "note": "informational; never gated (includes validator time; cache hits "
                                   "still run every mandatory validator live)"}


async def _persistent_lifecycle(worker: Path) -> dict:
    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="master-plife-") as directory:
        root = Path(directory)
        copy_dir = _newdir(root / "worker-copy")
        for item in worker.parent.iterdir():  # the binary with its runtime DLLs
            if item.is_file() and (item == worker or item.suffix.lower() == ".dll"):
                shutil.copyfile(item, copy_dir / item.name)
        exe = copy_dir / worker.name

        async def golden_and(runtime: MasterRuntime, action) -> tuple[bool, dict, list]:
            imported = _import_inputs(runtime, _newdir(root / uuid_dir()), [(_random_xyz(200, 7, cube=True), "xyz", "PointSet3", "mm")])
            plan = _plan(runtime, "hull.convex_3", imported, {})
            with SpawnRecorder() as recorder:
                first = await _run_plan(runtime, plan["plan_id"])
                await action()
                second = await _run_plan(runtime, plan["plan_id"])
                processes = list(recorder.processes)
            ok = (first["state"] == second["state"] == "succeeded"
                  and [o["sha256"] for o in first["outputs"]] == [o["sha256"] for o in second["outputs"]])
            return ok, runtime.supervisor.pool_status(), processes

        async def nothing() -> None:
            return None

        cases = {
            "job_count": ({"max_jobs_per_worker": 2}, nothing, "job_count"),
            "lifetime": ({"max_lifetime_s": 0.5}, lambda: asyncio.sleep(0.8), "lifetime"),
            "memory_residue": ({"recycle_private_fraction": 0.0001}, nothing, "memory_residue"),
        }
        for name, (policy, action, reason) in cases.items():
            runtime = _persistent_runtime(root / f"s-{name}", worker, **policy)
            try:
                ok, pool, processes = await golden_and(runtime, action)
                await runtime.supervisor.shutdown()
                results[name] = {"results_identical": ok, "recycled_for_reason": pool["recycled"].get(reason, 0) > 0,
                                 "processes_started": len(processes),
                                 "all_exited_after_shutdown": all(p.returncode is not None and _Win.exited(p.pid)
                                                                  for p in processes)}
            finally:
                runtime.close()
        # idle reaping: no worker process may remain once the idle timeout elapsed
        runtime = _persistent_runtime(root / "s-idle", worker, idle_timeout_s=1.0)
        try:
            ok, pool, processes = await golden_and(runtime, nothing)
            idle_after_job = pool["idle_workers"]
            await asyncio.sleep(2.5)
            results["idle_reap"] = {"results_identical": ok, "idle_workers_after_job": idle_after_job,
                                    "idle_workers_after_timeout": runtime.supervisor.pool_status()["idle_workers"],
                                    "processes_alive_after_timeout": sum(1 for p in processes if not _Win.exited(p.pid)),
                                    "recycled_for_reason": runtime.supervisor.pool_status()["recycled"].get("idle_timeout", 0) > 0}
        finally:
            runtime.close()
        # executable change: a changed worker binary is never reused
        runtime = _persistent_runtime(root / "s-exe", exe)

        async def change_exe() -> None:
            # upgrade the Windows way: a running image can be renamed, not rewritten; the new
            # binary carries one extra PE overlay byte (still runs, digest differs)
            previous = exe.with_name("previous-" + exe.name)
            exe.rename(previous)
            exe.write_bytes(previous.read_bytes())
            with open(exe, "ab") as handle:
                handle.write(b"\0")  # PE overlay byte: still runs, digest differs
        try:
            ok, pool, processes = await golden_and(runtime, change_exe)
            await runtime.supervisor.shutdown()
            results["executable_change"] = {"results_identical": ok,
                                            "recycled_for_reason": pool["recycled"].get("executable_changed", 0) > 0,
                                            "processes_started": len(processes)}
        finally:
            runtime.close()
        # per-job memory caps: pooled processes are keyed by cap and never shared across caps
        runtime = _persistent_runtime(root / "s-caps", worker)
        try:
            imported = _import_inputs(runtime, _newdir(root / uuid_dir()), [(_random_xyz(200, 7, cube=True), "xyz", "PointSet3", "mm")])
            plan = _plan(runtime, "hull.convex_3", imported, {})
            with SpawnRecorder() as recorder:
                a = await _run_plan(runtime, plan["plan_id"], memory_mb=256)
                b = await _run_plan(runtime, plan["plan_id"], memory_mb=512)
                c = await _run_plan(runtime, plan["plan_id"], memory_mb=256)
                processes = list(recorder.processes)
            caps = sorted(w.memory_mb for w in runtime.supervisor._idle)
            await runtime.supervisor.shutdown()
            results["per_cap_pools"] = {"all_succeeded": all(x["state"] == "succeeded" for x in (a, b, c)),
                                        "processes_started": len(processes), "idle_caps_mb": caps}
        finally:
            runtime.close()
    print(f"persistent lifecycle: {results}", flush=True)
    return results


def _newdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def uuid_dir() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


TAMPER_OFF = b"OFF\n4 4 0\n0 0 0\n0.01 0 0\n0 0.01 0\n0 0 0.01\n3 0 2 1\n3 0 1 3\n3 0 3 2\n3 1 2 3\n"


async def _cache_cases(worker: Path) -> dict:
    """Result cache: hit/miss, tamper -> miss, stale registry/worker -> miss, re-signed bad
    candidate -> live validator rejects, eviction bound, failed jobs never stored."""
    import hmac as _hmac
    from cgal_mcp.master.result_cache import ResultCache
    from cgal_mcp.master.util import canonical_json as _cj
    rows: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="master-cache-") as directory:
        root = Path(directory)
        runtime = MasterRuntime(root / "store", worker=worker, result_cache=True)
        cache = runtime.result_cache
        try:
            imported = _import_inputs(runtime, root, [(_random_xyz(500, 11, cube=True), "xyz", "PointSet3", "mm")])
            plan = _plan(runtime, "hull.convex_3", imported, {})
            validators = len(runtime.registry.get("hull.convex_3")["validation"]["validators"])

            async def run() -> tuple[dict, int]:
                with SpawnRecorder() as recorder:
                    detail = await _run_plan(runtime, plan["plan_id"])
                    return detail, len(recorder.processes)

            first, spawned_first = await run()
            golden = [o["sha256"] for o in first["outputs"]]
            second, spawned_second = await run()
            rows["miss_then_hit"] = {
                "first_state": first["state"], "second_state": second["state"],
                "identical_outputs": [o["sha256"] for o in second["outputs"]] == golden,
                "first_processes": spawned_first, "second_processes": spawned_second,
                "transform_skipped_validators_live": spawned_second == validators and spawned_first == validators + 1,
                "second_validation_status": second["validation_status"],
                "hits": cache.stats["hits"], "stores": cache.stats["stores"]}
            entry = next(cache.entries.glob("*.json"))
            key = entry.stem

            def resign(mutator) -> None:
                data = json.loads(entry.read_text(encoding="utf-8"))
                mutator(data["body"])
                data["mac"] = _hmac.new(cache._secret, _cj(data["body"]), hashlib.sha256).hexdigest()
                entry.write_text(json.dumps(data), encoding="utf-8")

            def check_miss(name: str, counter: str, before: int, detail: dict, processes: int) -> None:
                rows[name] = {"state": detail["state"], "counter_incremented": cache.stats[counter] > before,
                              "identical_outputs": [o["sha256"] for o in detail["outputs"]] == golden,
                              "transform_executed": processes == validators + 1}

            # tampered entry body (MAC no longer matches) -> miss
            data = json.loads(entry.read_text(encoding="utf-8"))
            data["body"]["metrics"] = {"forged": True}
            entry.write_text(json.dumps(data), encoding="utf-8")
            before = cache.stats["rejected_tampered"]
            detail, processes = await run()
            check_miss("tampered_entry", "rejected_tampered", before, detail, processes)
            # tampered blob bytes -> miss
            body = json.loads(entry.read_text(encoding="utf-8"))["body"]
            blob = cache.blobs / body["outputs"][0]["sha256"]
            blob.write_bytes(blob.read_bytes() + b"# tampered\n")
            before = cache.stats["rejected_tampered"]
            detail, processes = await run()
            check_miss("tampered_blob", "rejected_tampered", before, detail, processes)
            # stale worker digest -> miss (entry dropped)
            resign(lambda b: b.__setitem__("worker_sha256", "0" * 64))
            before = cache.stats["rejected_stale"]
            detail, processes = await run()
            check_miss("stale_worker", "rejected_stale", before, detail, processes)
            # stale registry revision -> pruned at startup / miss
            resign(lambda b: b.__setitem__("registry_revision", "f" * 64))
            before_entries = cache.usage()[0]
            other = ResultCache(cache.root, registry_revision=runtime.registry.revision)
            rows["stale_registry"] = {"entries_before": before_entries, "entries_after_reopen": other.usage()[0],
                                      "rejected_stale": other.stats["rejected_stale"]}
            detail, processes = await run()
            rows["stale_registry"]["next_run_transform_executed"] = processes == validators + 1
            rows["stale_registry"]["identical_outputs"] = [o["sha256"] for o in detail["outputs"]] == golden
            # a correctly signed but WRONG cached candidate is caught by the live validator
            entry = next(cache.entries.glob("*.json"))
            bad_digest = hashlib.sha256(TAMPER_OFF).hexdigest()
            (cache.blobs / bad_digest).write_bytes(TAMPER_OFF)

            def plant(b: dict) -> None:
                b["outputs"][0]["sha256"] = bad_digest
                b["outputs"][0]["size"] = len(TAMPER_OFF)
            resign(plant)
            artifacts_before = runtime.store.counts()["artifacts"]
            stores_before = cache.stats["stores"]
            detail, processes = await run()
            rows["resigned_bad_candidate"] = {
                "state": detail["state"], "validation_status": detail["validation_status"],
                "published": runtime.store.counts()["artifacts"] - artifacts_before,
                "outputs": len(detail.get("outputs", [])), "stored_after_failure": cache.stats["stores"] - stores_before}
            cache.clear()
            # eviction bound
            small = ResultCache(root / "bounded", registry_revision="r", max_entries=2)
            runtime.result_cache = small
            for seed in (1, 2, 3):
                extra = _import_inputs(runtime, _newdir(root / f"ev{seed}"),
                                       [(_random_xyz(100, seed, cube=True), "xyz", "PointSet3", "mm")])
                await _run_plan(runtime, _plan(runtime, "hull.convex_3", extra, {})["plan_id"])
            rows["eviction"] = {"max_entries": 2, "entries": small.usage()[0], "evicted": small.stats["evicted"]}
        finally:
            runtime.close()
    ok = (rows["miss_then_hit"]["transform_skipped_validators_live"] and rows["miss_then_hit"]["identical_outputs"]
          and rows["miss_then_hit"]["second_validation_status"] == "passed"
          and all(rows[n]["counter_incremented"] and rows[n]["identical_outputs"] and rows[n]["transform_executed"]
                  for n in ("tampered_entry", "tampered_blob", "stale_worker"))
          and rows["stale_registry"]["entries_after_reopen"] == 0 and rows["stale_registry"]["next_run_transform_executed"]
          and rows["resigned_bad_candidate"]["state"] in {"rejected", "failed"}
          and rows["resigned_bad_candidate"]["published"] == 0 and rows["resigned_bad_candidate"]["outputs"] == 0
          and rows["resigned_bad_candidate"]["stored_after_failure"] == 0
          and rows["eviction"]["entries"] <= 2 and rows["eviction"]["evicted"] >= 1)
    rows["all_passed"] = bool(ok)
    print(f"cache cases: {rows}", flush=True)
    return rows


def run_persistent(worker: Path, only: list[str] | None = None) -> tuple[dict, dict]:
    deterministic: dict[str, Any] = {"containment": {}}
    timings: dict[str, Any] = {"containment": {}}
    for mode, spec in list(PERSISTENT_FAULT_MODES.items()) + [
            ("native_external_kill", {"expect": ("worker_crash", "worker_crash")}),
            ("native_memory_cap", {"expect": ("resource_limit", "memory_limit")})]:
        if only and mode not in only:
            continue
        deterministic["containment"][mode], timings["containment"][mode] = asyncio.run(
            _persistent_fault_mode(mode, spec, worker))
    if not only:
        deterministic["isolation"], timings["speed"] = asyncio.run(_persistent_isolation(worker))
        deterministic["lifecycle"] = asyncio.run(_persistent_lifecycle(worker))
        deterministic["cache"] = asyncio.run(_cache_cases(worker))
    from cgal_mcp.master.supervisor import PersistentPolicy
    deterministic["default_policy"] = PersistentPolicy().as_dict()
    return deterministic, timings


# ---------------------------------------------------------------- evidence

def measure(root: Path = REPO, worker: Path | None = None,
            stages: tuple[str, ...] = ("scale", "limits", "faults", "persistent"),
            only_families: list[str] | None = None, only_modes: list[str] | None = None,
            trials: int | None = None, host_kill_trials: int | None = None) -> dict:
    global TRIALS_PER_MODE, HOST_KILL_TRIALS
    if trials is not None:
        TRIALS_PER_MODE = trials
    if host_kill_trials is not None:
        HOST_KILL_TRIALS = host_kill_trials
    worker = (worker or root / DEFAULT_WORKER).resolve(strict=True)
    deterministic: dict[str, Any] = {}
    timings: dict[str, Any] = {}
    if "scale" in stages:
        deterministic["scale_cases"], deterministic["ceiling_probes"], timings["scale"] = run_scale(worker, only_families)
    if "limits" in stages:
        deterministic["limit_cases"], timings["limits"] = asyncio.run(_limit_cases(worker))
    if "faults" in stages:
        deterministic["containment"], timings["containment"] = run_faults(worker, only_modes)
        deterministic["lifecycle"] = asyncio.run(_lifecycle(worker))
    if "persistent" in stages:
        deterministic["persistent"], timings["persistent"] = run_persistent(
            worker, only_modes if only_modes and "faults" not in stages else None)
    return {
        "schema_version": 1, "generator": GENERATOR, "scope": "all_fifteen_major_families",
        "standalone_accepted": False,
        "bindings": bindings(root), "worker_sha256": sha256_file(worker),
        "platform": {"os": sys.platform, "python": sys.version.split()[0]},
        "declared": {"trials_per_fault_mode": TRIALS_PER_MODE, "host_kill_trials": HOST_KILL_TRIALS,
                     "memory_ceiling_mb": ResourceConfig().default_memory_mb,
                     "wall_limit_ms": ResourceConfig().default_wall_time_ms,
                     "handle_growth_tolerance": HANDLE_GROWTH_TOLERANCE,
                     "trial_count_source": "declared here; the Master plan states crash containment 100% "
                                           "without a trial count",
                     "fault_injection": "scripts/robustness_fault_proxy.py (test-only proxy; the native "
                                        "worker binary and the registry are unchanged)"},
        "deterministic": deterministic,
        "deterministic_sha256": canonical_sha(deterministic),
        "timing_policy": TIMING_POLICY,
        "timings": timings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stage", action="append", choices=["scale", "limits", "faults", "persistent"])
    parser.add_argument("--family", action="append")
    parser.add_argument("--mode", action="append")
    parser.add_argument("--trials", type=int)
    parser.add_argument("--host-kill-trials", type=int)
    parser.add_argument("--host-victim", nargs=4, metavar=("STORE", "WORKER", "FIXTURE", "PIDFILE"))
    args = parser.parse_args()
    if args.host_victim:
        store, worker, fixture, pidfile = (Path(item) for item in args.host_victim)
        _host_victim(store, worker, fixture, pidfile)
        return
    evidence = measure(REPO, args.worker, tuple(args.stage or ("scale", "limits", "faults", "persistent")),
                       args.family, args.mode, args.trials, args.host_kill_trials)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=1, sort_keys=True) + "\n",
                               encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
