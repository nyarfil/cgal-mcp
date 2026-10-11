"""Client-limit regressions: large-mesh stack, selective hole filling and the hole listing.

Every mesh here is synthesized in the test (no scan data). The tests drive the native worker
through its JSON protocol and are skipped when the Release worker is not built.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
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


def noisy_sphere(latitudes: int, longitudes: int, amplitude: float, seed: int, radius: float = 60.0):
    """UV sphere with seeded radial noise (the synthesized stand-in for a scan with fold-overs)."""
    rnd = random.Random(seed)
    vertices, faces = uv_sphere(latitudes, longitudes)
    out = []
    for index, (x, y, z) in enumerate(vertices):
        r = radius * (1.0 + amplitude * (rnd.random() * 2 - 1)) if 0 < index < len(vertices) - 1 else radius
        out.append((x * r, y * r, z * r))
    return out, faces


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

    # --- simplification self-intersection control (foldover_policy) -------------------
    SIC_FIXTURES = REPO / "tests/fixtures/master/wave_a"

    def sic_params(self, target: int, **extra) -> dict:
        return {"stop": {"kind": "face_count", "value": target}, "policy": "lindstrom_turk",
                "max_symmetric_deviation": {"value": 15.0, "unit": "mm"},
                "hausdorff_error_bound": {"value": 1.0, "unit": "mm"}, **extra}

    def intersection_pairs(self, path: Path, name: str) -> int:
        response = self.run_worker("mesh.analysis.self_intersections", [artifact(path, "input-0")], {}, name)
        self.assertEqual(response["status"], "ok", response)
        report = json.loads(Path(response["outputs"][0]["path"]).read_text(encoding="utf-8"))
        return report["results"]["intersection_pair_count"]

    def test_synthesized_fixtures_match_their_generator(self):
        for name, (amplitude, seed) in {"noisy_sphere_fold.off": (0.1, 1), "noisy_sphere_shortfall.off": (0.06, 2),
                                         "noisy_sphere_unresolved.off": (0.2, 13)}.items():
            vertices, faces = noisy_sphere(12, 16, amplitude, seed)
            regenerated = self.root / name
            write_off(regenerated, vertices, faces)
            self.assertEqual(regenerated.read_bytes(), (self.SIC_FIXTURES / name).read_bytes(), name)

    def test_default_collapse_self_intersects_and_is_unchanged(self):
        source = artifact(self.SIC_FIXTURES / "noisy_sphere_fold.off", "input-0")
        response = self.run_worker("mesh.simplify.edge_collapse", [source], self.sic_params(200), "sic-default")
        self.assertEqual(response["status"], "ok", response)
        self.assertNotIn("retry_attempts", response["metrics"])
        candidate = Path(response["outputs"][0]["path"])
        self.assertEqual(self.intersection_pairs(candidate, "sic-default-pairs"), 3)
        verdict = self.run_worker("mesh.validate.simplification_integrity",
                                  [artifact(candidate, "candidate"), source],
                                  {"preserve_border": True, "constrained_edges": []}, "sic-default-integrity")
        self.assertEqual(verdict["status"], "error")
        self.assertEqual(verdict["error"]["code"], "SELF_INTERSECTION")

    def test_protect_and_retry_yields_an_intersection_free_validated_mesh(self):
        source = artifact(self.SIC_FIXTURES / "noisy_sphere_fold.off", "input-0")
        response = self.run_worker("mesh.simplify.edge_collapse", [source],
                                   self.sic_params(200, foldover_policy="protect_and_retry"), "sic-retry")
        self.assertEqual(response["status"], "ok", response)
        metrics = response["metrics"]
        self.assertEqual((metrics["faces_after"], metrics["retry_attempts"], metrics["final_self_intersecting_pairs"]),
                         (198, 2, 0))
        self.assertEqual([item["intersecting_pairs"] for item in metrics["attempt_log"]], [3, 0])
        candidate = Path(response["outputs"][0]["path"])
        self.assertEqual(self.intersection_pairs(candidate, "sic-retry-pairs"), 0)
        verdict = self.run_worker("mesh.validate.simplification_integrity",
                                  [artifact(candidate, "candidate"), source],
                                  {"preserve_border": True, "constrained_edges": []}, "sic-retry-integrity")
        self.assertEqual(verdict["status"], "ok", verdict)

    def test_unreachable_target_is_refused_with_the_best_achievable_count(self):
        source = artifact(self.SIC_FIXTURES / "noisy_sphere_shortfall.off", "input-0")
        params = self.sic_params(120, foldover_policy="protect_and_retry")
        refused = self.run_worker("mesh.simplify.edge_collapse", [source], params, "sic-short")
        self.assertEqual(refused["status"], "error")
        self.assertEqual(refused["error"]["code"], "TARGET_NOT_REACHABLE_WITHOUT_SELF_INTERSECTION")
        self.assertIn("134 faces", refused["error"]["message"])
        accepted = self.run_worker("mesh.simplify.edge_collapse", [source],
                                   {**params, "accept_target_shortfall": True}, "sic-short-ok")
        self.assertEqual(accepted["status"], "ok", accepted)
        self.assertEqual((accepted["metrics"]["faces_after"], accepted["metrics"]["target_reached"]), (134, False))
        self.assertEqual(self.intersection_pairs(Path(accepted["outputs"][0]["path"]), "sic-short-pairs"), 0)

    def test_exhausted_retry_rounds_publish_nothing(self):
        source = artifact(self.SIC_FIXTURES / "noisy_sphere_unresolved.off", "input-0")
        refused = self.run_worker("mesh.simplify.edge_collapse", [source],
                                  self.sic_params(150, foldover_policy="protect_and_retry",
                                                  max_retry_rounds=1), "sic-unresolved")
        self.assertEqual(refused["status"], "error")
        self.assertEqual(refused["error"]["code"], "SELF_INTERSECTION_UNRESOLVED")
        self.assertEqual(refused.get("outputs", []), [])

    def test_retry_options_require_the_policy(self):
        source = artifact(self.SIC_FIXTURES / "noisy_sphere_fold.off", "input-0")
        for extra, code in (({"max_retry_rounds": 2}, "RETRY_ROUNDS_WITHOUT_POLICY"),
                            ({"accept_target_shortfall": True}, "SHORTFALL_WITHOUT_POLICY"),
                            ({"foldover_policy": "ignore"}, "INVALID_PARAMETER")):
            response = self.run_worker("mesh.simplify.edge_collapse", [source], self.sic_params(200, **extra),
                                       "sic-bad-" + code)
            self.assertEqual(response["error"]["code"], code, response)

    def test_protect_and_retry_on_a_71k_face_noisy_sphere(self):
        vertices, faces = noisy_sphere(188, 190, 0.02, 3, radius=20.0)
        self.assertGreaterEqual(len(faces), 71000)
        mesh = self.root / "noisy_71k.off"
        write_off(mesh, vertices, faces)
        source = artifact(mesh, "input-0")
        plain = self.run_worker("mesh.simplify.edge_collapse", [source], self.sic_params(35600), "sic-71k-plain")
        self.assertGreater(self.intersection_pairs(Path(plain["outputs"][0]["path"]), "sic-71k-plain-pairs"), 0)
        retried = self.run_worker("mesh.simplify.edge_collapse", [source],
                                  self.sic_params(35600, foldover_policy="protect_and_retry"), "sic-71k")
        self.assertEqual(retried["status"], "ok", retried)
        self.assertEqual(retried["metrics"]["faces_after"], 35598)
        candidate = artifact(Path(retried["outputs"][0]["path"]), "candidate")
        verdict = self.run_worker("mesh.validate.simplification_integrity", [candidate, source],
                                  {"preserve_border": True, "constrained_edges": []}, "sic-71k-integrity")
        self.assertEqual(verdict["status"], "ok", verdict)

    def test_registry_and_guide_describe_the_retry_policy(self):
        from cgal_mcp.master.registry import OperationRegistry
        operation = OperationRegistry().operations["mesh.simplify.edge_collapse"]
        for name in ("foldover_policy", "max_retry_rounds", "accept_target_shortfall"):
            self.assertIn(name, operation["parameters"]["properties"])
        self.assertEqual(operation["parameters"]["properties"]["foldover_policy"]["default"], "reject")
        self.assertIn("protect_and_retry", (REPO / "cgal_mcp/master/guide/guide.json").read_text(encoding="utf-8"))


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
