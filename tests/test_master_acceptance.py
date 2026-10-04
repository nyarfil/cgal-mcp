"""Protect the approved denominator and prevent catalog-only completion claims."""
import copy
import hashlib
import tempfile
from pathlib import Path
import unittest
from scripts.master_acceptance import REPO, _canonical_hash, _evidence_reasons, evaluate_requirements, extract_requirements, verify_originals


class AcceptanceContractTests(unittest.TestCase):
    def test_original_document_bytes_preserved(self):
        self.assertTrue(all(c["matches_original"] for c in verify_originals().values()))

    def test_all_original_families_and_requirements_retained(self):
        manifest = extract_requirements()
        self.assertEqual(len(manifest["families"]), 15)
        self.assertGreater(sum(len(f["requirements"]) for f in manifest["families"]), 70)
        self.assertTrue(all(r["required"] for f in manifest["families"] for r in f["requirements"]))

    def test_catalog_only_is_not_implementation(self):
        report = evaluate_requirements(extract_requirements(), {})
        self.assertFalse(report["complete"])
        self.assertEqual(report["validated"], 0)

    def test_removing_requirement_cannot_improve_coverage(self):
        manifest = extract_requirements()
        manifest["families"][0]["requirements"].pop()
        with self.assertRaisesRegex(ValueError, "denominator"):
            evaluate_requirements(manifest, {})

    def test_declared_validated_handler_without_evidence_is_incomplete(self):
        manifest = copy.deepcopy(extract_requirements())
        item = manifest["families"][0]["requirements"][0]
        item["operation_ids"] = ["pretend.operation"]
        report = evaluate_requirements(manifest, {"pretend.operation": {"status": "VALIDATED"}})
        self.assertEqual(report["validated"], 0)

    def test_self_declared_pass_cannot_establish_acceptance(self):
        item = extract_requirements()["families"][0]["requirements"][0]
        item["operation_ids"] = ["pretend.operation"]
        with tempfile.TemporaryDirectory() as folder:
            reasons = _evidence_reasons(
                {"status": "pass", "requirements": [item["id"]]}, item,
                {"pretend.operation": {"status": "VALIDATED", "revision": 1}}, Path(folder))
        self.assertTrue(any("manifest" in reason for reason in reasons))
        self.assertTrue(any("execution" in reason for reason in reasons))
        self.assertTrue(any("baseline" in reason for reason in reasons))

    def test_fully_populated_report_without_actual_replay_is_incomplete(self):
        """Even internally consistent hashes and declared passes are not executions."""
        item = copy.deepcopy(extract_requirements()["families"][0]["requirements"][0])
        item["operation_ids"] = ["pretend.operation"]
        test_path = REPO / "tests/test_master_acceptance.py"
        manifest = {"protocol": 1, "actual_cgal_version": "6.2.1",
                    "build": {"source_kind": "official_release",
                              "source_sha256": "b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf"},
                    "operations": [{"id": "pretend.operation", "revision": 1}]}
        report = {"schema_version": 1, "generator": "master-capability-acceptance",
                  "status": "pass", "requirements": [item["id"]],
                  "catalog_baseline_sha256": hashlib.sha256((REPO / "catalog/baseline.json").read_bytes()).hexdigest(),
                  "worker_manifest": manifest, "worker_manifest_sha256": _canonical_hash(manifest),
                  "tests": [{"id": "pretend.test", "source_path": "tests/test_master_acceptance.py",
                             "source_sha256": hashlib.sha256(test_path.read_bytes()).hexdigest(), "status": "pass"}],
                  "operation_results": [{"operation_id": "pretend.operation", "revision": 1,
                      "worker_manifest_sha256": _canonical_hash(manifest), "test_id": "pretend.test",
                      "input_hashes": ["a" * 64], "output_hashes": ["b" * 64],
                      "validation": {"status": "pass", "checks": {"invented": {"pass": True}}}}]}
        reasons = _evidence_reasons(report, item, {"pretend.operation": {"revision": 1}}, REPO)
        self.assertEqual(reasons, ["Evidence has not been reproduced by the acceptance runner for this build"])


if __name__ == "__main__":
    unittest.main()
