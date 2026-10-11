"""Client-limit regressions: large-mesh stack, selective hole filling and the hole listing.

Every mesh here is synthesized in the test (no scan data). The tests drive the native worker
through its JSON protocol and are skipped when the Release worker is not built.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKER = REPO / "build-master/Release/cgal-master-worker.exe"
FIXTURES = REPO / "tests/fixtures/master/wave_a_repair"


def uv_sphere(latitudes: int, longitudes: int) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices = [(0.0, 0.0, 1.0)]
    for i in range(1, latitudes):
        theta = math.pi * i / latitudes
        for j in range(longitudes):
            phi = 2.0 * math.pi * j / longitudes
            vertices.append((math.sin(theta) * math.cos(phi), math.sin(theta) * math.sin(phi), math.cos(theta)))
    vertices.append((0.0, 0.0, -1.0))
    south = len(vertices) - 1

    def ring(i: int, j: int) -> int:
        return 1 + (i - 1) * longitudes + (j % longitudes)

    faces = [(0, ring(1, j), ring(1, j + 1)) for j in range(longitudes)]
    for i in range(1, latitudes - 1):
        for j in range(longitudes):
            a, b, c, d = ring(i, j), ring(i, j + 1), ring(i + 1, j + 1), ring(i + 1, j)
            faces += [(a, d, c), (a, c, b)]
    faces += [(south, ring(latitudes - 1, j + 1), ring(latitudes - 1, j)) for j in range(longitudes)]
    return vertices, faces


def write_off(path: Path, vertices, faces) -> None:
    lines = ["OFF", f"{len(vertices)} {len(faces)} 0"]
    lines += [f"{x:.9f} {y:.9f} {z:.9f}" for x, y, z in vertices]
    lines += [f"3 {a} {b} {c}" for a, b, c in faces]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def artifact(path: Path, artifact_id: str, type_: str = "TriangleSurfaceMesh",
             format_: str = "off", unit: str = "mm") -> dict:
    return {"artifact_id": artifact_id, "type": type_, "unit": unit, "format": format_,
            "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@unittest.skipUnless(WORKER.exists(), "native master worker is not built")
class ClientLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_worker(self, operation: str, inputs: list[dict], parameters: dict, name: str) -> dict:
        output = self.root / name
        output.mkdir(parents=True, exist_ok=True)
        request = {"protocol": 1, "request_id": name, "operation": operation, "inputs": inputs,
                   "parameters": parameters, "output_dir": str(output.resolve()),
                   "kernel": "package_recommended",
                   "limits": {"wall_time_ms": 300000, "memory_mb": 4096}}
        completed = subprocess.run([str(WORKER)], input=json.dumps(request) + "\n", text=True,
                                   encoding="utf-8", capture_output=True, timeout=600)
        self.assertEqual(completed.returncode, 0, (operation, completed.returncode, completed.stderr[:300]))
        return json.loads(completed.stdout.splitlines()[0])

    def test_integrity_validator_survives_a_large_closed_mesh(self):
        # The volume-component recursion inside CGAL overflowed the default 1 MiB Windows stack
        # (0xC00000FD) from roughly 10k faces; the worker links with a larger stack.
        vertices, faces = uv_sphere(100, 200)
        self.assertGreaterEqual(len(faces), 20000)
        mesh = self.root / "closed_large.off"
        write_off(mesh, vertices, faces)
        response = self.run_worker("mesh.validate.simplification_integrity",
                                   [artifact(mesh, "candidate"), artifact(mesh, "source")],
                                   {"preserve_border": True}, "integrity-large")
        self.assertEqual(response["status"], "ok", response)
        self.assertEqual(response["metrics"]["status"], "pass", response)

    def hole_mesh(self) -> Path:
        return FIXTURES / "dome_three_holes.off"

    def test_boundary_cycles_lists_stable_ids_sizes_and_order(self):
        response = self.run_worker("mesh.analysis.boundary_cycles", [artifact(self.hole_mesh(), "input-0")],
                                   {}, "cycles")
        self.assertEqual(response["status"], "ok", response)
        report = json.loads(Path(response["outputs"][0]["path"]).read_text(encoding="utf-8"))
        results = report["results"]
        self.assertEqual([h["hole_id"] for h in results["holes"]], [0, 4, 49])
        self.assertEqual([h["edge_count"] for h in results["holes"]], [3, 3, 12])
        self.assertEqual(results["order_by_boundary_length_desc"], [49, 4, 0])
        self.assertAlmostEqual(results["holes"][2]["patch_area_estimate"], 0.75, places=9)
        self.assertAlmostEqual(results["holes"][2]["boundary_length"], 12 * math.sin(math.pi / 12), places=9)
        self.assertEqual(results["area_unit"], "mm^2")

    def test_selective_fill_leaves_unselected_holes_open(self):
        mesh = artifact(self.hole_mesh(), "input-0")
        response = self.run_worker("mesh.repair.fill_holes", [mesh], {"max_hole_edges": 20, "hole_ids": [49]},
                                   "fill-by-id")
        self.assertEqual(response["status"], "ok", response)
        self.assertEqual(response["metrics"]["filled_hole_ids"], [49])
        self.assertEqual(response["metrics"]["skipped_hole_ids"], [0, 4])
        candidate = Path(response["outputs"][0]["path"])
        cycles = self.run_worker("mesh.analysis.boundary_cycles", [artifact(candidate, "input-0")], {}, "cycles-after")
        report = json.loads(Path(cycles["outputs"][0]["path"]).read_text(encoding="utf-8"))
        self.assertEqual([h["hole_id"] for h in report["results"]["holes"]], [0, 4])

    def test_default_fill_is_unchanged_and_fills_every_eligible_hole(self):
        response = self.run_worker("mesh.repair.fill_holes", [artifact(self.hole_mesh(), "input-0")],
                                   {"max_hole_edges": 20}, "fill-default")
        self.assertEqual(response["status"], "ok", response)
        self.assertEqual(response["metrics"]["filled_hole_count"], 3)
        self.assertNotIn("filled_hole_ids", response["metrics"])

    def test_stale_ids_and_ambiguous_selection_are_refused(self):
        mesh = artifact(self.hole_mesh(), "input-0")
        stale = self.run_worker("mesh.repair.fill_holes", [mesh], {"max_hole_edges": 20, "hole_ids": [7]}, "stale")
        self.assertEqual(stale["status"], "error")
        self.assertEqual(stale["error"]["code"], "HOLE_ID_NOT_FOUND")
        both = self.run_worker("mesh.repair.fill_holes", [mesh],
                               {"max_hole_edges": 20, "hole_ids": [49],
                                "max_hole_perimeter": {"value": 5.0, "unit": "mm"}}, "both")
        self.assertEqual(both["error"]["code"], "HOLE_SELECTION_CONFLICT")

    def test_validator_rejects_a_candidate_that_filled_an_unselected_hole(self):
        response = self.run_worker(
            "mesh.validate.repair_fill_holes",
            [artifact(FIXTURES / "dome_three_holes_all_filled.off", "candidate"), artifact(self.hole_mesh(), "source")],
            {"max_hole_edges": 20, "hole_ids": [49]}, "overfilled")
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error"]["code"], "REPAIR_VALIDATION_FAILED")


class RegistryGuideTests(unittest.TestCase):
    def test_registry_and_guide_carry_the_list_first_rule(self):
        from cgal_mcp.master.registry import OperationRegistry
        registry = OperationRegistry()
        cycles = registry.operations["mesh.analysis.boundary_cycles"]
        fill = registry.operations["mesh.repair.fill_holes"]
        for operation in (cycles, fill):
            self.assertIn("list first, ask the user, then fill by ids", operation["summary"])
        for name in ("hole_ids", "max_hole_perimeter", "max_hole_area"):
            self.assertIn(name, fill["parameters"]["properties"])
        guide = (REPO / "cgal_mcp/master/guide/guide.json").read_text(encoding="utf-8")
        self.assertIn("list first, ask the user, then fill by ids", guide)


if __name__ == "__main__":
    unittest.main()
