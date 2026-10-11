"""Scalable certified symmetric Hausdorff (validation_mode certified_bvh).

All meshes are synthesized here or are checked-in synthesized fixtures (no scan data). Worker-level tests
drive the native worker through its JSON protocol; runtime tests go through MasterRuntime plan/execute so
the registry precondition (400 faces by default, 2,000,000 only for certified_bvh) and the mandatory
validator chain are exercised. Skipped when the Release worker is not built.
"""
from __future__ import annotations

import asyncio
import json
import math
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_master_client_limits import WORKER, artifact, noisy_sphere, write_off

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests/fixtures/master/batch5"


def mm(value: float) -> dict:
    return {"value": value, "unit": "mm"}


def grid(n: int, lift: float = 0.0):
    vertices = [(i * 1.0, j * 1.0, 0.0) for j in range(n + 1) for i in range(n + 1)]
    faces = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            faces += [(a, a + 1, a + n + 2), (a, a + n + 2, a + n + 1)]
    if lift:
        centre = (n // 2) * (n + 1) + n // 2
        vertices[centre] = (n // 2 * 1.0, n // 2 * 1.0, lift)
    return vertices, faces


@unittest.skipUnless(WORKER.exists(), "native master worker is not built")
class CertifiedHausdorffWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_worker(self, operation: str, inputs: list[dict], parameters: dict) -> dict:
        import subprocess
        type(self).counter += 1
        output = self.root / f"run{self.counter}"
        output.mkdir()
        request = {"protocol": 1, "request_id": output.name, "operation": operation, "inputs": inputs,
                   "parameters": parameters, "output_dir": str(output.resolve()), "kernel": "package_recommended",
                   "limits": {"wall_time_ms": 600000, "memory_mb": 4096}}
        completed = subprocess.run([str(WORKER)], input=json.dumps(request) + "\n", text=True, encoding="utf-8",
                                   capture_output=True, timeout=900)
        self.assertEqual(completed.returncode, 0, completed.stderr[:300])
        return json.loads(completed.stdout.splitlines()[0])

    def report_artifact(self, response: dict) -> dict:
        return artifact(Path(response["outputs"][0]["path"]), "report", "ValidationReport", "json", "none")

    def produce_and_validate(self, reference: Path, candidate: Path, parameters: dict) -> tuple[dict, dict]:
        meshes = [artifact(reference, "reference"), artifact(candidate, "candidate")]
        produced = self.run_worker("mesh.distance.symmetric_hausdorff", meshes, parameters)
        self.assertEqual(produced["status"], "ok", produced)
        validated = self.run_worker("mesh.validate.hausdorff_symmetric_report",
                                    [self.report_artifact(produced), *meshes], parameters)
        report = json.loads(Path(produced["outputs"][0]["path"]).read_text(encoding="utf-8"))
        if validated["status"] != "ok":
            return report, validated
        return report, json.loads(Path(validated["outputs"][0]["path"]).read_text(encoding="utf-8"))

    def test_fixtures_match_their_generator(self):
        for name, lift in (("hausdorff_grid24.off", 0.0), ("hausdorff_grid24_spike.off", 0.5)):
            path = self.root / name
            write_off(path, *grid(24, lift))
            self.assertEqual(path.read_bytes(), (FIXTURES / name).read_bytes())

    def test_spike_is_found_and_certified_against_the_tolerance(self):
        reference, candidate = FIXTURES / "hausdorff_grid24.off", FIXTURES / "hausdorff_grid24_spike.off"
        # At 0.49 mm the CGAL report is indeterminate (0.5 +- 0.01) while the tighter certified bracket fails it.
        for tolerance, verdict, certified in ((0.1, "fail", "fail"), (0.6, "pass", "pass"),
                                              (0.49, "indeterminate", "fail")):
            parameters = {"tolerance": mm(tolerance), "error_bound": mm(0.01), "validation_mode": "certified_bvh"}
            report, validation = self.produce_and_validate(reference, candidate, parameters)
            self.assertEqual(report["verdict"], verdict)
            self.assertEqual(validation["status"], "pass", validation)
            self.assertEqual(validation["validation_mode"], "certified_bvh")
            lower, upper = validation["certified_lower_bound"], validation["certified_upper_bound"]
            self.assertLessEqual(lower, 0.5)
            self.assertGreaterEqual(upper, 0.5)
            self.assertLessEqual(upper - lower, 0.005 + 2 * validation["rounding_margin"])
            self.assertEqual(validation["certified_verdict"], certified)
            self.assertEqual(validation["certified_within_tolerance"], certified == "pass")
            self.assertAlmostEqual(validation["exact_rational_witness_distances"][1], 0.5, places=12)
            self.assertGreater(validation["exhaustive_crosscheck_points"], 2)

    def test_tampered_report_hiding_the_spike_is_rejected(self):
        meshes = [artifact(FIXTURES / "hausdorff_grid24.off", "reference"),
                  artifact(FIXTURES / "hausdorff_grid24_spike.off", "candidate")]
        tampered = artifact(FIXTURES / "tampered_hausdorff_certified_spike_hidden.json", "report",
                            "ValidationReport", "json", "none")
        parameters = {"tolerance": mm(0.1), "error_bound": mm(0.01), "validation_mode": "certified_bvh"}
        rejected = self.run_worker("mesh.validate.hausdorff_symmetric_report", [tampered, *meshes], parameters)
        self.assertEqual(rejected["status"], "error")
        self.assertEqual(rejected["error"]["code"], "DISTANCE_OUT_OF_BRACKET")
        # Without the scalable mode the bruteforce validator keeps its 400-face bound.
        default = self.run_worker("mesh.validate.hausdorff_symmetric_report", [tampered, *meshes],
                                  {"tolerance": mm(0.1), "error_bound": mm(0.01)})
        self.assertEqual(default["error"]["code"], "FACE_LIMIT_EXCEEDED")

    def test_both_tiers_agree_on_a_small_pair(self):
        reference, candidate = self.root / "g12.off", self.root / "g12s.off"
        write_off(reference, *grid(12))
        write_off(candidate, *grid(12, 0.5))
        brackets = {}
        for mode in (None, "certified_bvh"):
            parameters = {"tolerance": mm(0.1), "error_bound": mm(0.01)}
            if mode:
                parameters["validation_mode"] = mode
            report, validation = self.produce_and_validate(reference, candidate, parameters)
            self.assertEqual(validation["status"], "pass", validation)
            self.assertEqual(report["verdict"], "fail")
            brackets[mode] = (validation["recomputed_bracket_lower"], validation["recomputed_bracket_upper"])
            self.assertLessEqual(brackets[mode][0], 0.5 + 1e-9)
            self.assertGreaterEqual(brackets[mode][1], 0.5 - 1e-9)
        self.assertNotIn("validation_mode", self.produce_and_validate(
            reference, candidate, {"tolerance": mm(0.1), "error_bound": mm(0.01)})[1])

    def test_noisy_pair_matches_cgal_within_the_error_bound(self):
        reference, candidate = self.root / "n1.off", self.root / "n2.off"
        write_off(reference, *noisy_sphere(40, 60, 0.002, 5, radius=60.0))
        write_off(candidate, *noisy_sphere(30, 44, 0.002, 6, radius=60.0))
        parameters = {"tolerance": mm(1.0), "error_bound": mm(0.01), "validation_mode": "certified_bvh"}
        report, validation = self.produce_and_validate(reference, candidate, parameters)
        self.assertEqual(validation["status"], "pass", validation)
        cgal = report["results"]["distance"]
        self.assertLessEqual(validation["certified_lower_bound"], cgal + 0.01 + 1e-6)
        self.assertGreaterEqual(validation["certified_upper_bound"], cgal - 0.01 - 1e-6)


@unittest.skipUnless(WORKER.exists(), "native master worker is not built")
class CertifiedHausdorffRuntimeTests(unittest.TestCase):
    def setUp(self):
        from cgal_mcp.master.runtime import MasterRuntime
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MasterRuntime(self.root / "store", worker=WORKER)

    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    def execute(self, plan: dict) -> dict:
        async def scenario():
            queued = await self.runtime.execute(plan["plan_id"], wall_time_ms=900000)
            await self.runtime.tasks[queued["job_id"]]
            return self.runtime.job_status(queued["job_id"])
        return asyncio.run(scenario())

    def test_registry_raises_the_face_bound_only_for_the_certified_mode(self):
        from cgal_mcp.master.errors import PreconditionFailure
        operation = self.runtime.registry.get("mesh.distance.symmetric_hausdorff")
        bound = next(c for c in operation["preconditions"] if c["id"] == "bounded_input")
        self.assertEqual(bound["maximum_faces"], 400)
        self.assertEqual(bound["relaxed_by_parameter"],
                         {"parameter": "validation_mode", "equals": "certified_bvh",
                          "maximum_faces": 2000000, "maximum_bytes": 1073741824})
        reference = self.runtime.artifact_import(str(FIXTURES / "hausdorff_grid24.off"), "mm")
        candidate = self.runtime.artifact_import(str(FIXTURES / "hausdorff_grid24_spike.off"), "mm")
        request = {"operation_id": "mesh.distance.symmetric_hausdorff",
                   "inputs": [reference["artifact_id"], candidate["artifact_id"]],
                   "parameters": {"tolerance": mm(0.1), "error_bound": mm(0.01)}}
        for mode in (None, "bruteforce"):
            if mode:
                request["parameters"]["validation_mode"] = mode
            with self.assertRaisesRegex(PreconditionFailure, "faces<=400"):
                self.runtime.plan(request)
        request["parameters"]["validation_mode"] = "certified_bvh"
        plan = self.runtime.plan(request)
        self.assertEqual(plan["steps"][1]["operation"], "mesh.validate.hausdorff_symmetric_report")
        self.assertEqual(plan["steps"][1]["parameters"]["validation_mode"], "certified_bvh")
        status = self.execute(plan)
        # The spike exceeds the tolerance: the CGAL report says fail, the certified validator confirms the
        # report (it is consistent), and the required verdict=pass check keeps the job from passing.
        self.assertNotEqual(status["state"], "succeeded", status)
        self.assertNotIn("manifest", json.dumps(status.get("error", {})))
        request["parameters"]["tolerance"] = mm(0.6)
        passed = self.execute(self.runtime.plan(request))
        self.assertEqual((passed["state"], passed["validation_status"]), ("succeeded", "passed"), passed)

    def test_71k_scan_sized_simplification_is_validated_end_to_end(self):
        vertices, faces = noisy_sphere(179, 200, 0.0005, 11, radius=60.0)
        self.assertEqual(len(faces), 71200)
        mesh = self.root / "noisy_71k.off"
        write_off(mesh, vertices, faces)
        source = self.runtime.artifact_import(str(mesh), "mm")
        parameters = {"stop": {"kind": "face_count", "value": 35600}, "policy": "lindstrom_turk",
                      "preserve_border": True, "constrained_edges": [], "foldover_policy": "protect_and_retry",
                      "max_symmetric_deviation": mm(0.1), "hausdorff_error_bound": mm(0.01)}
        plain = self.runtime.plan({"operation_id": "mesh.simplify.edge_collapse",
                                   "inputs": [source["artifact_id"]], "parameters": parameters})
        refused = self.execute(plain)
        self.assertNotEqual(refused["state"], "succeeded")
        self.assertIn("faces<=400", json.dumps(refused))
        plan = self.runtime.plan({"operation_id": "mesh.simplify.edge_collapse", "inputs": [source["artifact_id"]],
                                  "parameters": {**parameters, "hausdorff_validation_mode": "certified_bvh"}})
        hausdorff = plan["steps"][-1]
        self.assertEqual(hausdorff["operation"], "mesh.distance.symmetric_hausdorff")
        self.assertEqual(hausdorff["parameters"]["validation_mode"], "certified_bvh")
        started = time.perf_counter()
        status = self.execute(plan)
        elapsed = time.perf_counter() - started
        self.assertEqual((status["state"], status["validation_status"]), ("succeeded", "passed"), status)
        self.assertLess(elapsed, 600)


if __name__ == "__main__":
    unittest.main()
