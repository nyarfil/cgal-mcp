"""General-position Booleans (mesh.boolean.rounded) and the raised bounds of the exact validators.

The exact Boolean handlers publish only results whose coordinates are binary64 values, so two
spheres already fail. These tests drive the native worker through its JSON protocol (skipped when
no worker is built) and the generic runtime registry. Every mesh is synthesized or a small fixture.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cgal_mcp.master.registry import OperationRegistry

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests/fixtures/master/wave_a_boolean"


def worker_path() -> Path:
    configured = os.environ.get("CGAL_MASTER_WORKER")
    if configured:
        return Path(configured)
    release = REPO / "build-master/Release/cgal-master-worker.exe"
    direct = REPO / ("build-master/cgal-master-worker.exe" if os.name == "nt" else "build-master/cgal-master-worker")
    return release if release.is_file() else direct


WORKER = worker_path()


def artifact(path: Path, artifact_id: str, type_: str = "TriangleSurfaceMesh", format_: str = "off") -> dict:
    # JSON reports carry no length unit.
    return {"artifact_id": artifact_id, "type": type_, "unit": "none" if format_ == "json" else "mm",
            "format": format_,
            "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def read_off(path: Path):
    tokens = path.read_text("utf-8").split()
    assert tokens[0] == "OFF"
    vertex_count, face_count = int(tokens[1]), int(tokens[2])
    values = tokens[4:]
    vertices = [tuple(float(values[3 * i + k]) for k in range(3)) for i in range(vertex_count)]
    faces, cursor = [], 3 * vertex_count
    for _ in range(face_count):
        degree = int(values[cursor])
        faces.append(tuple(int(v) for v in values[cursor + 1:cursor + 1 + degree]))
        cursor += 1 + degree
    return vertices, faces


def write_off(path: Path, vertices, faces) -> None:
    lines = ["OFF", f"{len(vertices)} {len(faces)} 0"]
    lines += [" ".join(repr(float(c)) for c in v) for v in vertices]
    lines += ["3 " + " ".join(str(i) for i in f) for f in faces]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def signed_volume(path: Path) -> float:
    vertices, faces = read_off(path)
    total = 0.0
    for a, b, c in faces:
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = vertices[a], vertices[b], vertices[c]
        total += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
    return total / 6.0


def grid_cube(n: int, shift: float = 0.0):
    """Cube of side n with n x n quads per side, split into triangles; integer coordinates."""
    index, vertices, faces = {}, [], []

    def vid(p):
        if p not in index:
            index[p] = len(vertices)
            vertices.append(p)
        return index[p]

    for axis in range(3):
        for side in (0, 1):
            for i in range(n):
                for j in range(n):
                    def corner(u, v):
                        c = [0, 0, 0]
                        c[axis], c[(axis + 1) % 3], c[(axis + 2) % 3] = side * n, u, v
                        return vid(tuple(c))
                    a, b, c, d = corner(i, j), corner(i + 1, j), corner(i + 1, j + 1), corner(i, j + 1)
                    faces += [(a, b, c), (a, c, d)] if side else [(a, d, c), (a, c, b)]
    return [(x + shift, y + shift, z + shift) for x, y, z in vertices], faces


@unittest.skipUnless(WORKER.is_file(), "native master worker is not built")
class WorkerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def call(self, operation: str, inputs: list[dict], parameters: dict) -> dict:
        type(self).counter += 1
        output = self.root / f"job-{self.counter}"
        output.mkdir()
        request = {"protocol": 1, "request_id": f"rounded-{self.counter}", "operation": operation,
                   "inputs": inputs, "parameters": parameters, "output_dir": str(output.resolve()),
                   "kernel": "package_recommended", "limits": {"wall_time_ms": 300000, "memory_mb": 4096}}
        completed = subprocess.run([str(WORKER)], input=json.dumps(request) + "\n", text=True,
                                   encoding="utf-8", capture_output=True, timeout=600)
        self.assertEqual(completed.returncode, 0, (operation, completed.stderr[:300]))
        return json.loads(completed.stdout.splitlines()[0])

    def ok(self, operation, inputs, parameters) -> dict:
        response = self.call(operation, inputs, parameters)
        self.assertEqual(response["status"], "ok", response.get("error"))
        return response

    def refused(self, operation, inputs, parameters, code: str) -> dict:
        response = self.call(operation, inputs, parameters)
        self.assertEqual(response["status"], "error", response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        return response["error"]


class RoundedBooleanTests(WorkerCase):
    def setUp(self):
        self.a = artifact(FIXTURES / "sphere_general_a.off", "a")
        self.b = artifact(FIXTURES / "sphere_general_b.off", "b")

    def rounded(self, kind: str, a=None, b=None):
        a, b = a or self.a, b or self.b
        produced = self.ok("mesh.boolean.rounded", [a, b], {"operation": kind})
        path = Path(produced["outputs"][0]["path"])
        candidate = artifact(path, "candidate")
        validated = self.ok("mesh.validate.boolean_rounded", [candidate, a, b], {"operation": kind})
        report = json.loads(Path(validated["outputs"][0]["path"]).read_text("utf-8"))
        return produced, candidate, report

    def test_exact_boolean_refuses_general_position_and_names_the_rounded_operation(self):
        for kind in ("union", "intersection", "difference"):
            error = self.refused(f"mesh.boolean.{kind}", [self.a, self.b], {"operation": kind},
                                 "OUTPUT_BINARY64_LOSS")
            self.assertEqual(error["suggested_operations"], ["mesh.boolean.rounded"])

    def test_rounded_results_pass_validation_and_satisfy_inclusion_exclusion(self):
        volumes = {}
        for kind in ("union", "intersection", "difference"):
            produced, candidate, report = self.rounded(kind)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["comparison"], "tolerance")
            for check in ("topology_valid", "self_intersection_free", "element_counts_match_reference",
                          "volume_within_tolerance_of_reference",
                          "candidate_vertices_within_tolerance_of_reference_surface",
                          "reference_vertices_within_tolerance_of_candidate_surface"):
                self.assertIs(report["checks"][check], True, check)
            tolerance = report["checks"]["tolerance"]
            # Largest coordinate is 17.3: the power of two above it is 32, times 2^-40.
            self.assertEqual(tolerance, 32.0 * 2.0 ** -40)
            self.assertLess(report["checks"]["max_candidate_vertex_distance"], tolerance)
            self.assertLess(report["checks"]["max_reference_vertex_distance"], tolerance)
            volumes[kind] = signed_volume(Path(candidate["path"]))
            self.assertGreater(volumes[kind], 0)
        # Independent of CGAL: |A u B| + |A n B| = |A| + |B| and |A - B| = |A| - |A n B|.
        volume_a = signed_volume(FIXTURES / "sphere_general_a.off")
        volume_b = signed_volume(FIXTURES / "sphere_general_b.off")
        self.assertAlmostEqual(volumes["union"] + volumes["intersection"], volume_a + volume_b, delta=1e-8)
        self.assertAlmostEqual(volumes["difference"], volume_a - volumes["intersection"], delta=1e-8)

    def test_validator_rejects_wrong_operation_tampering_and_a_source_as_candidate(self):
        _, candidate, _ = self.rounded("union")
        self.refused("mesh.validate.boolean_rounded", [candidate, self.a, self.b],
                     {"operation": "intersection"}, "BOOLEAN_ROUNDED_COUNT_MISMATCH")
        self.refused("mesh.validate.boolean_rounded", [self.a, self.a, self.b],
                     {"operation": "union"}, "BOOLEAN_ROUNDED_COUNT_MISMATCH")
        vertices, faces = read_off(Path(candidate["path"]))
        for delta in (1e-3, 1e-6, 1e-9):
            moved = list(vertices)
            x, y, z = moved[40]
            moved[40] = (x + delta, y, z)
            path = self.root / f"tampered-{delta}.off"
            write_off(path, moved, faces)
            error = self.call("mesh.validate.boolean_rounded", [artifact(path, "t"), self.a, self.b],
                              {"operation": "union"})
            self.assertEqual(error["status"], "error", delta)
            self.assertEqual(error["error"]["class"], "VALIDATION_FAILED", delta)

    def test_unknown_operation_and_extra_parameters_are_refused(self):
        self.refused("mesh.boolean.rounded", [self.a, self.b], {"operation": "xor"},
                     "BOOLEAN_OPERATION_BINDING_MISMATCH")
        self.refused("mesh.boolean.rounded", [self.a, self.b], {"operation": "union", "tolerance": 1},
                     "BOOLEAN_OPERATION_BINDING_MISMATCH")

    def test_representable_input_gives_the_exact_volume_and_empty_results_stay_empty(self):
        cube_a, overlap = artifact(FIXTURES / "cube_a.off", "a"), artifact(FIXTURES / "cube_overlap.off", "b")
        produced, candidate, report = self.rounded("union", cube_a, overlap)
        self.assertEqual(produced["metrics"]["exact_volume_before_rounding"], "12")
        self.assertEqual(produced["metrics"]["rounded_volume"], "12")
        self.assertEqual(report["checks"]["max_candidate_vertex_distance"], 0.0)
        disjoint = artifact(FIXTURES / "cube_disjoint.off", "b")
        produced, candidate, report = self.rounded("intersection", cube_a, disjoint)
        self.assertEqual(produced["metrics"]["result_status"], "empty")
        self.assertEqual(report["checks"]["result_status"], "empty")

    def test_open_source_is_refused_before_computing(self):
        open_cube = artifact(FIXTURES / "open_cube.off", "a")
        self.refused("mesh.boolean.rounded", [open_cube, self.b], {"operation": "union"}, "MESH_NOT_CLOSED")


class RaisedExactBoundTests(WorkerCase):
    """The exact validators keep their GMP decisions; only the pair selection uses a box hierarchy."""

    def mesh(self, name: str, n: int, shift: float = 0.0) -> dict:
        path = self.root / name
        if not path.exists():
            write_off(path, *grid_cube(n, shift))
        return artifact(path, name)

    def validate(self, validator, produced, inputs, parameters, type_="TriangleSurfaceMesh", format_="off") -> dict:
        candidate = artifact(Path(produced["outputs"][0]["path"]), "candidate", type_, format_)
        response = self.ok(validator, [candidate] + inputs, parameters)
        report = json.loads(Path(response["outputs"][0]["path"]).read_text("utf-8"))
        self.assertEqual(report["status"], "pass")
        return report

    def test_plane_and_intersection_operations_accept_meshes_far_above_the_former_bounds(self):
        n = 24  # 6912 faces: above the former 600 (plane, corefine, features) and 200 (intersection) bounds
        cube, other = self.mesh("grid-a.off", n), self.mesh("grid-b.off", n, 0.5)
        plane = {"normal": [0, 0, 1], "offset": {"value": n / 2 + 0.5, "unit": "mm"}}
        clip = dict(plane, clip_volume=True)
        report = self.validate("mesh.validate.clip", self.ok("mesh.clip.plane", [cube], clip), [cube], clip)
        self.assertGreater(report["cap_triangle_count"], 0)
        self.validate("mesh.validate.split", self.ok("mesh.split.plane", [cube], plane), [cube], plane)
        report = self.validate("mesh.validate.corefine", self.ok("mesh.corefine", [cube, other], {}),
                               [cube, other], {})
        self.assertGreater(report["touching_pair_count"], 0)
        features = {"angle_degrees": 60}
        report = self.validate("mesh.validate.features", self.ok("mesh.features.detect", [cube], features),
                               [cube], features, "GeometryQueryReport", "json")
        self.assertEqual(report["patch_count"], 6)
        overlap = {"overlap_test": True}
        self.validate("mesh.validate.do_intersect",
                      self.ok("mesh.intersections.do_intersect", [cube, other], overlap),
                      [cube, other], overlap, "GeometryQueryReport", "json")
        report = self.validate("mesh.validate.intersection_polylines",
                               self.ok("mesh.intersections.polylines", [cube, other], {}),
                               [cube, other], {}, "GeometryQueryReport", "json")
        self.assertGreater(report["exact_segment_count"], 0)

    def test_validators_still_reject_a_wrong_candidate_on_a_large_mesh(self):
        n = 24
        cube = self.mesh("grid-a.off", n)
        plane = {"normal": [0, 0, 1], "offset": {"value": n / 2 + 0.5, "unit": "mm"}}
        # The uncut cube is not a split result: a triangle crosses the plane.
        self.refused("mesh.validate.split", [cube, cube], plane, "TRIANGLE_STRADDLES_PLANE")
        produced = self.ok("mesh.clip.plane", [cube], dict(plane, clip_volume=True))
        vertices, faces = read_off(Path(produced["outputs"][0]["path"]))
        path = self.root / "clip-missing-face.off"
        write_off(path, vertices, faces[:-1])
        error = self.call("mesh.validate.clip", [artifact(path, "candidate"), cube], dict(plane, clip_volume=True))
        self.assertEqual(error["status"], "error")
        self.assertEqual(error["error"]["class"], "VALIDATION_FAILED")

    def test_the_new_bound_is_enforced(self):
        cube = self.mesh("grid-over.off", 130)  # 202,800 faces
        error = self.refused("mesh.features.detect", [cube], {"angle_degrees": 60}, "FACE_LIMIT_EXCEEDED")
        self.assertIn("limit", error["message"])


@unittest.skipUnless(WORKER.is_file(), "native master worker is not built")
class McpEndToEndTests(unittest.TestCase):
    """Official MCP client -> plan -> mandatory validator -> published artifact."""

    def test_rounded_union_runs_through_the_server_and_the_exact_union_is_refused(self):
        import asyncio
        import sys
        from mcp import Client, StdioServerParameters

        async def scenario(folder: str) -> None:
            connection = StdioServerParameters(
                command=sys.executable, args=["-m", "cgal_mcp.master.server", "stdio"], cwd=str(REPO),
                env={**os.environ, "CGAL_MASTER_DATA": str(Path(folder) / "data"),
                     "CGAL_MASTER_WORKER": str(WORKER.resolve())})
            async with Client(connection) as client:
                async def call(name: str, arguments: dict) -> dict:
                    result = await client.call_tool(name, arguments)
                    self.assertFalse(result.is_error, result)
                    return (result.structured_content if result.structured_content is not None else
                            json.loads("".join(block.text for block in result.content if hasattr(block, "text"))))

                async def run(operation_id: str, inputs: dict, parameters: dict) -> tuple[dict, dict]:
                    plan = await call("cgal_plan", {"request": {
                        "operation_id": operation_id, "inputs": inputs, "parameters": parameters}})
                    queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
                    for _ in range(2400):
                        status = await call("cgal_job_status", {"job_id": queued["job_id"]})
                        if status["state"] not in {"queued", "running"}:
                            return plan, status
                        await asyncio.sleep(0.05)
                    self.fail("job did not finish")

                ids = {}
                for slot, name in (("source_a", "sphere_general_a.off"), ("source_b", "sphere_general_b.off")):
                    imported = await call("cgal_artifact_import", {
                        "path": str(FIXTURES / name), "unit": "mm", "artifact_type": "TriangleSurfaceMesh"})
                    ids[slot] = imported["artifact_id"]
                plan, status = await run("mesh.boolean.rounded", ids, {"operation": "union"})
                self.assertEqual([step["operation"] for step in plan["steps"]],
                                 ["mesh.boolean.rounded", "mesh.validate.boolean_rounded"])
                self.assertEqual(status["state"], "succeeded", status)
                self.assertEqual(status["validation_status"], "passed", status)
                report = status["validation"][0]["report"]
                self.assertEqual(report["comparison"], "tolerance")
                self.assertIs(report["checks"]["volume_within_tolerance_of_reference"], True)
                output = status["outputs"][0]
                self.assertEqual(output["type"], "TriangleSurfaceMesh")
                inspected = await call("cgal_artifact_inspect", {"artifact_id": output["artifact_id"]})
                self.assertEqual(inspected["unit"], "mm")
                _, refused = await run("mesh.boolean.union", ids, {"operation": "union"})
                self.assertEqual(refused["state"], "failed", refused)
                self.assertEqual(refused["error"]["code"], "OUTPUT_BINARY64_LOSS", refused)

        with tempfile.TemporaryDirectory(prefix="master-boolean-rounded-") as folder:
            asyncio.run(scenario(folder))


class RegistryTests(unittest.TestCase):
    def test_rounded_boolean_is_registered_as_implemented_with_its_validator(self):
        registry = OperationRegistry()
        operation = registry.get("mesh.boolean.rounded", executable=True)
        self.assertEqual(operation["status"], "IMPLEMENTED")
        self.assertEqual(operation["validation"]["validators"], ["mesh.validate.boolean_rounded"])
        self.assertIs(operation["validation"]["required"], True)
        validator = registry.get("mesh.validate.boolean_rounded", executable=True)
        self.assertEqual(validator["role"], "validator")
        self.assertEqual(validator["validation"]["validates"], "mesh.boolean.rounded")
        self.assertEqual(operation["evidence"]["review_status"], "self_verified_not_independently_reviewed")

    def test_exact_operation_bounds_match_the_worker_constants(self):
        registry = OperationRegistry()
        for operation_id in ("mesh.features.detect", "mesh.clip.plane", "mesh.split.plane", "mesh.corefine",
                             "mesh.autorefine", "mesh.intersections.do_intersect", "mesh.intersections.polylines"):
            operation = registry.get(operation_id, executable=True)
            bound = next(c for c in operation["preconditions"] if c["id"] == "bounded_input")
            self.assertEqual(bound["maximum_faces"], 200000, operation_id)
            self.assertEqual(operation["worker_manifest"]["info"]["maximum_input_faces"], 200000, operation_id)


if __name__ == "__main__":
    unittest.main()
