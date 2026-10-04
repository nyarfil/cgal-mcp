"""Measure synthetic hull workloads; this is not all-family performance acceptance."""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from cgal_mcp.master.runtime import MasterRuntime
from cgal_mcp.master import supervisor

COUNTS = {"small": 1000, "medium": 100000, "large": 1000000}


def write_fixture(path: Path, count: int) -> str:
    rng = random.Random(20261005)
    with path.open("w", encoding="ascii", newline="\n") as stream:
        for x in (0, 1):
            for y in (0, 1):
                for z in (0, 1):
                    stream.write(f"{x} {y} {z}\n")
        for _ in range(count - 8):
            stream.write(" ".join(f"{rng.random():.17g}" for _ in range(3)) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WindowsMemoryMeter:
    """Retain query-only handles so Windows can report each worker's peak RSS."""
    def __init__(self):
        self.handles = []
        self.original = supervisor._assign_windows_job
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        self.kernel.OpenProcess.restype = ctypes.c_void_p
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        self.counters = Counters
        self.psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_uint32]
        self.psapi.GetProcessMemoryInfo.restype = ctypes.c_int

    def assign(self, pid, memory_mb):
        assigned = self.original(pid, memory_mb)
        handle = self.kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            raise OSError(ctypes.get_last_error(), "Cannot measure worker memory")
        self.handles.append(handle)
        return assigned

    def finish(self):
        peaks, commits = [], []
        try:
            for handle in self.handles:
                counters = self.counters()
                counters.cb = ctypes.sizeof(counters)
                if not self.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                    raise OSError(ctypes.get_last_error(), "Cannot read worker peak memory")
                peaks.append(counters.PeakWorkingSetSize)
                commits.append(counters.PeakPagefileUsage)
            assert peaks and all(peaks)
            return {"peak_worker_rss_bytes": max(peaks), "peak_worker_commit_bytes": max(commits),
                    "memory_measurement": "Windows GetProcessMemoryInfo OS peak counters",
                    "measured_processes": len(peaks),
                    "memory_scope": "compute and validator workers; excludes import, host and manifest"}
        finally:
            for handle in self.handles:
                self.kernel.CloseHandle(handle)


async def case(name: str, worker: Path, output: Path):
    count = COUNTS[name]
    with tempfile.TemporaryDirectory(prefix="master-hull-measure-") as directory:
        root = Path(directory)
        fixture = root / "cube-interior.xyz"
        fixture_hash = write_fixture(fixture, count)
        runtime = MasterRuntime(root / "store", worker=worker)
        meter = WindowsMemoryMeter() if os.name == "nt" else None
        started = time.perf_counter()
        try:
            source = runtime.artifact_import(str(fixture), "mm", artifact_type="PointSet3")
            import_seconds = time.perf_counter() - started
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]]})
            async def execute():
                begin = time.perf_counter()
                job = await runtime.execute(plan["plan_id"])
                await asyncio.wait_for(runtime.tasks[job["job_id"]], 300)
                state = runtime.job_status(job["job_id"])
                assert state["state"] == "succeeded" and state["validation_status"] == "passed", state
                return state, time.perf_counter() - begin
            if meter:
                with patch.object(supervisor, "_assign_windows_job", meter.assign):
                    state, execution_seconds = await execute()
                memory = meter.finish()
            else:
                import resource
                state, execution_seconds = await execute()
                rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
                memory = {"peak_child_rss_bytes": int(rss * (1 if sys.platform == "darwin" else 1024)),
                          "memory_measurement": "POSIX getrusage RUSAGE_CHILDREN maximum RSS",
                          "memory_scope": "all child processes in fresh case, including import and manifest"}
            manifest = await runtime.supervisor.manifest("hull.convex_3")
            assert manifest["actual_cgal_version"] == "6.2.1"
            assert manifest["build"]["source_kind"] == "official_release"
            result = {"case": name, "points": count, "status": "pass",
                "import_seconds": import_seconds, "execution_validation_seconds": execution_seconds,
                "input_sha256": fixture_hash, "output_sha256": state["outputs"][0]["sha256"],
                "worker_sha256": manifest["supervisor_executable_sha256"],
                "worker_manifest": manifest, "validation_status": state["validation_status"],
                "operation_result_cache_enabled": False,
                "resource_limit_mode": runtime.supervisor.resource_limit_mode, **memory}
        finally:
            runtime.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes((json.dumps(result, indent=2) + "\n").encode())


async def cancel_large(worker: Path, output: Path):
    with tempfile.TemporaryDirectory(prefix="master-native-cancel-") as directory:
        root = Path(directory)
        fixture = root / "large.xyz"
        source_hash = write_fixture(fixture, COUNTS["large"])
        runtime = MasterRuntime(root / "store", worker=worker)
        original = asyncio.create_subprocess_exec
        started = asyncio.Event()
        spawned = []
        async def observe(*arguments, **keywords):
            process = await original(*arguments, **keywords)
            if str(arguments[0]) == str(worker) and "--manifest" not in arguments:
                spawned.append(process)
                started.set()
            return process
        try:
            source = runtime.artifact_import(str(fixture), "mm", artifact_type="PointSet3")
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]]})
            with patch.object(asyncio, "create_subprocess_exec", observe):
                job = await runtime.execute(plan["plan_id"])
                await asyncio.wait_for(started.wait(), 30)
                await asyncio.sleep(.05)
                assert spawned[0].returncode is None, "Workload finished before cancellation"
                begin = time.perf_counter()
                await runtime.job_cancel(job["job_id"])
                elapsed = time.perf_counter() - begin
            state = runtime.job_status(job["job_id"])
            assert state["state"] == "cancelled" and not state.get("outputs"), state
            assert spawned[0].returncode is not None, "Cancelled worker still running"
            assert runtime.artifact_inspect(source["artifact_id"])["sha256"] == source_hash
            result = {"case": "cancel_large", "points": COUNTS["large"], "status": "pass",
                "cancel_seconds": elapsed, "cancel_after_native_spawn_seconds": .05,
                "native_worker_running_at_cancel": True, "native_worker_reaped": True,
                "input_preserved": True, "no_output_published": True,
                "input_sha256": source_hash, "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
                "resource_limit_mode": runtime.supervisor.resource_limit_mode}
        finally:
            runtime.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes((json.dumps(result, indent=2) + "\n").encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=[*COUNTS, "cancel_large"])
    args = parser.parse_args()
    if args.case:
        if args.case == "cancel_large":
            asyncio.run(cancel_large(args.worker.resolve(strict=True), args.output))
        else:
            asyncio.run(case(args.case, args.worker.resolve(strict=True), args.output))
        return
    results = []
    with tempfile.TemporaryDirectory(prefix="master-hull-cases-") as directory:
        for name in [*COUNTS, "cancel_large"]:
            report = Path(directory) / f"{name}.json"
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(args.worker.resolve()),
                "--output", str(report), "--case", name], check=True, cwd=REPO, timeout=600)
            measured = json.loads(report.read_text())
            results.append(measured)
            label = "cancel" if name == "cancel_large" else "compute+validate"
            duration = measured.get("cancel_seconds", measured.get("execution_validation_seconds"))
            print(f"{name}: {measured['points']} points, {label} {duration:.3f}s: PASS", flush=True)
    result = {"schema_version": 1, "scope": "synthetic_hull_only", "standalone_accepted": False,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixtures": "fixed random seed 20261005, unit cube corners and interior points",
        "case_isolation": "fresh Python host and transient store per case", "cases": results,
        "limitations": ["one sample per size", "not all-family performance acceptance",
            "cache effect and persistent-worker recovery not implemented or measured",
            "native cancellation checks source preservation and process reap, not every algorithm"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(result, indent=2) + "\n").encode())


if __name__ == "__main__":
    main()
