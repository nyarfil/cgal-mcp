"""Protect the approved denominator and prevent catalog-only completion claims."""
import copy
import base64
import hashlib
import json
import tempfile
from pathlib import Path
import unittest
from unittest import mock
import scripts.master_acceptance as acceptance_module
from scripts.master_acceptance import (
    REPO,
    WAVE_A_BOUNDED_NORMAL_ANALYTIC_PROOF,
    WAVE_A_BOUNDED_NORMAL_CONTROL,
    WAVE_A_BOUNDED_NORMAL_ERROR_CLASS,
    WAVE_A_BOUNDED_NORMAL_ERROR_CODE,
    WAVE_A_BOUNDED_NORMAL_FILTERED,
    WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256,
    WAVE_A_TRANSFORM,
    WAVE_A_VALIDATORS,
    _bounded_normal_negative_control_reasons,
    _canonical_hash,
    _evidence_reasons,
    evaluate_requirements,
    extract_requirements,
    verify_originals,
)
from scripts.replay_master_capabilities import (
    _approved_output_path,
    _digest,
    _native_binary_format,
    _require_unchanged,
    _requirements_for_replayed_report,
)


def wave_context(requirement_id: str = "major.7.7.01") -> tuple[dict, dict, dict[str, dict]]:
    report = json.loads((REPO / "docs/master/evidence/wave-a-capabilities.json").read_text(encoding="utf-8"))
    requirements = json.loads((REPO / "catalog/major_requirements.json").read_text(encoding="utf-8"))
    item = next(requirement for family in requirements["families"]
                for requirement in family["requirements"] if requirement["id"] == requirement_id)
    operation_data = json.loads((REPO / "cgal_mcp/master/operations.json").read_text(encoding="utf-8"))
    operations = {operation["id"]: operation for operation in operation_data["operations"]}
    return report, item, operations


def string_values(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from string_values(item)


def bounded_normal_proof_context() -> tuple[dict, dict, dict, dict, dict, set[str], str]:
    """Minimal internally consistent structure for negative-proof tamper tests."""
    candidate = "c" * 64
    positive_output = "d" * 64
    manifest_digest = "e" * 64
    shared = {
        "policy": "edge_length_midpoint",
        "stop": {"kind": "edge_length", "value": {"value": 0.1, "unit": "mm"}},
        "preserve_border": False,
        "constrained_edges": [],
        "max_symmetric_deviation": {"value": 2.0, "unit": "mm"},
        "hausdorff_error_bound": {"value": 0.01, "unit": "mm"},
    }

    def artifact(digest: str) -> dict:
        return {"blob_sha256": digest}

    control_request = {
        "operation": WAVE_A_TRANSFORM,
        "request_id": f"{WAVE_A_BOUNDED_NORMAL_CONTROL}-simplify",
        "inputs": [artifact(WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256)],
        "parameters": shared | {"bounded_normal_change": False},
        "kernel": "package_recommended",
    }
    control_response = {
        "request_id": control_request["request_id"],
        "status": "ok",
        "outputs": [artifact(candidate)],
        "metrics": {
            "policy": "edge_length_midpoint",
            "stop_policy": "edge_length",
            "bounded_normal_change_enabled": False,
            "edges_before": 6,
            "edges_removed": 3,
            "edges_after": 3,
        },
    }
    failure_request = {
        "operation": WAVE_A_VALIDATORS[0],
        "request_id": f"{WAVE_A_BOUNDED_NORMAL_CONTROL}-integrity",
        "inputs": [artifact(candidate), artifact(WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256)],
        "parameters": {"preserve_border": False, "constrained_edges": []},
    }
    failure_response = {
        "request_id": failure_request["request_id"],
        "status": "error",
        "outputs": [],
        "metrics": {},
        "error": {
            "class": WAVE_A_BOUNDED_NORMAL_ERROR_CLASS,
            "code": WAVE_A_BOUNDED_NORMAL_ERROR_CODE,
        },
    }
    proof = {
        "case_id": WAVE_A_BOUNDED_NORMAL_CONTROL,
        "operation_id": WAVE_A_TRANSFORM,
        "revision": 1,
        "worker_manifest_sha256": manifest_digest,
        "test_id": "wave-a-worker-cases",
        "paired_positive_case_id": WAVE_A_BOUNDED_NORMAL_FILTERED,
        "request": control_request,
        "request_sha256": _canonical_hash(control_request),
        "response": control_response,
        "response_sha256": _canonical_hash(control_response),
        "input_hashes": [WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256],
        "output_hashes": [candidate],
        "bindings": {
            "source_sha256": WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256,
            "rejected_candidate_sha256": candidate,
        },
        "parameter_proof": {
            "only_changed_parameter": "bounded_normal_change",
            "control_value": False,
            "filtered_value": True,
            "shared_parameters_sha256": _canonical_hash(shared),
        },
        "analytic_fixture": copy.deepcopy(WAVE_A_BOUNDED_NORMAL_ANALYTIC_PROOF),
        "expected_validator_failure": {
            "operation_id": WAVE_A_VALIDATORS[0],
            "revision": 1,
            "request": failure_request,
            "request_sha256": _canonical_hash(failure_request),
            "response": failure_response,
            "response_sha256": _canonical_hash(failure_response),
            "input_hashes": [candidate, WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256],
            "output_hashes": [],
            "status": "expected_error",
        },
        "status": "expected_rejection",
    }
    positive_request = {
        "operation": WAVE_A_TRANSFORM,
        "inputs": [artifact(WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256)],
        "parameters": shared | {"bounded_normal_change": True},
        "kernel": "package_recommended",
    }
    positive = {
        "case_id": WAVE_A_BOUNDED_NORMAL_FILTERED,
        "input_hashes": [WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256],
        "output_hashes": [positive_output],
        "request": positive_request,
        "response": {"status": "ok", "metrics": {
            "bounded_normal_change_enabled": True,
            "edges_before": 6,
            "edges_removed": 0,
            "edges_after": 6,
        }},
        "validation": {"checks": {"bounded_normal_negative_control": {
            "pass": True,
            "negative_control_id": WAVE_A_BOUNDED_NORMAL_CONTROL,
            "rejected_candidate_sha256": candidate,
        }}},
    }
    report = {"negative_control_proofs": {WAVE_A_BOUNDED_NORMAL_CONTROL: proof}}
    indexed = {WAVE_A_BOUNDED_NORMAL_FILTERED: positive}
    operations = {WAVE_A_TRANSFORM: {"revision": 1}, WAVE_A_VALIDATORS[0]: {"revision": 1}}
    declared = copy.deepcopy(operations)
    tests = {"wave-a-worker-cases": {}}
    blobs = {WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256, candidate, positive_output}
    return report, indexed, operations, declared, tests, blobs, manifest_digest


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
        self.assertIn("Evidence has not been reproduced by the acceptance runner for this build", reasons)

    def test_no_report_hash_only_issuer_api_exists(self):
        self.assertFalse(hasattr(acceptance_module, "ReplayedEvidence"))
        self.assertFalse(hasattr(acceptance_module, "_approve_replayed_report"))

    def test_wave_a_report_without_process_local_replay_is_incomplete(self):
        report, item, operations = wave_context()
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence has not been reproduced by the acceptance runner for this build", reasons)

    def test_wave_a_report_contains_no_repository_host_path(self):
        report, _item, _operations = wave_context()
        roots = {str(REPO).lower(), REPO.as_posix().lower()}
        self.assertFalse(any(any(root in value.lower() for root in roots)
                             for value in string_values(report)))

    def test_malformed_fabricated_wave_a_coverage_is_rejected_without_execution(self):
        report, item, operations = wave_context()
        report["requirement_coverage"] = []
        report["policy_coverage"] = []
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn(f"Evidence case coverage is incomplete: {item['id']}", reasons)
        self.assertIn("Evidence non-blocked policy coverage is incomplete", reasons)

    def test_partial_wave_a_case_coverage_is_rejected(self):
        report, item, operations = wave_context()
        report["requirement_coverage"][item["id"]]["case_ids"].pop()
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn(f"Evidence case coverage is incomplete: {item['id']}", reasons)

    def test_partial_nonblocked_policy_coverage_is_rejected(self):
        report, item, operations = wave_context()
        report["policy_coverage"].pop(next(iter(report["policy_coverage"])))
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence non-blocked policy coverage is incomplete", reasons)

    def test_missing_mandatory_validator_is_rejected(self):
        report, item, operations = wave_context("major.7.7.05")
        result = next(result for result in report["operation_results"]
                      if result["case_id"] == "polyhedral-envelope")
        result["validators"].pop()
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence mandatory validator chain is incomplete: polyhedral-envelope", reasons)

    def test_modified_test_source_binding_is_rejected(self):
        report, item, operations = wave_context("major.7.7.06")
        report["tests"][0]["source_sha256"] = "0" * 64
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence test source/result mismatch", reasons)

    def test_wrong_worker_manifest_is_rejected(self):
        report, item, operations = wave_context("major.7.7.05")
        report["worker_manifest"]["actual_cgal_version"] = "0.0.0"
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence worker differs from the official CGAL baseline", reasons)
        self.assertIn("Evidence worker manifest hash mismatch", reasons)

    def test_test_stub_cannot_claim_official_cgal_capability(self):
        report, item, operations = wave_context("major.7.7.05")
        report["worker_manifest"]["build"]["test_stub"] = True
        report["worker_manifest_sha256"] = _canonical_hash(report["worker_manifest"])
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence worker differs from the official CGAL baseline", reasons)

    def test_wrong_handler_revision_is_rejected(self):
        report, item, operations = wave_context("major.7.7.05")
        result = next(result for result in report["operation_results"]
                      if result["case_id"] == "polyhedral-envelope")
        result["revision"] += 1
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence execution/build/test mismatch: mesh.simplify.edge_collapse", reasons)

    def test_unknown_fixture_hash_is_rejected(self):
        report, item, operations = wave_context("major.7.7.05")
        result = next(result for result in report["operation_results"]
                      if result["case_id"] == "polyhedral-envelope")
        result["input_hashes"][0] = "a" * 64
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence fixture/artifact hash missing: mesh.simplify.edge_collapse", reasons)

    def test_fixture_blob_content_hash_mismatch_is_rejected(self):
        report, item, operations = wave_context("major.7.7.05")
        result = next(result for result in report["operation_results"]
                      if result["case_id"] == "polyhedral-envelope")
        digest = result["input_hashes"][0]
        report["blobs"][digest]["content"] = base64.b64encode(b"fabricated").decode("ascii")
        report["blobs"][digest]["byte_size"] = len(b"fabricated")
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn(f"Evidence blob hash/size mismatch: {digest}", reasons)

    def test_unknown_output_hash_is_rejected(self):
        report, item, operations = wave_context("major.7.7.06")
        result = next(result for result in report["operation_results"]
                      if result["case_id"] == "bounded-normal")
        result["output_hashes"][0] = "b" * 64
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence fixture/artifact hash missing: mesh.simplify.edge_collapse", reasons)

    def test_modified_validator_report_is_rejected(self):
        report, item, operations = wave_context("major.7.7.06")
        digest = next(iter(report["reports"]))
        report["reports"][digest]["status"] = "fail"
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn(f"Evidence validator report hash mismatch: {digest}", reasons)

    def test_bounded_normal_negative_control_contract_is_internally_consistent(self):
        context = bounded_normal_proof_context()
        self.assertEqual(_bounded_normal_negative_control_reasons(*context), [])

    def test_bounded_normal_negative_control_artifact_tamper_is_rejected(self):
        context = bounded_normal_proof_context()
        proof = context[0]["negative_control_proofs"][WAVE_A_BOUNDED_NORMAL_CONTROL]
        proof["bindings"]["rejected_candidate_sha256"] = "f" * 64
        reasons = _bounded_normal_negative_control_reasons(*context)
        self.assertIn(
            "Evidence bounded-normal negative control artifact binding mismatch", reasons,
        )

    def test_bounded_normal_negative_control_wrong_error_is_rejected(self):
        context = bounded_normal_proof_context()
        failure = context[0]["negative_control_proofs"][
            WAVE_A_BOUNDED_NORMAL_CONTROL
        ]["expected_validator_failure"]
        failure["response"]["error"]["code"] = "SELF_INTERSECTION"
        failure["response_sha256"] = _canonical_hash(failure["response"])
        reasons = _bounded_normal_negative_control_reasons(*context)
        self.assertIn(
            "Evidence bounded-normal strict validator rejection mismatch", reasons,
        )

    def test_bounded_normal_negative_control_missing_parameter_proof_is_rejected(self):
        context = bounded_normal_proof_context()
        del context[0]["negative_control_proofs"][
            WAVE_A_BOUNDED_NORMAL_CONTROL
        ]["parameter_proof"]
        reasons = _bounded_normal_negative_control_reasons(*context)
        self.assertIn("Evidence bounded-normal parameter proof mismatch", reasons)

    def test_worker_hash_change_during_replay_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = Path(folder) / "worker.bin"
            worker.write_bytes(b"MZfirst")
            expected = _digest(worker)
            worker.write_bytes(b"MZsecond")
            with self.assertRaisesRegex(ValueError, "Worker binary changed"):
                _require_unchanged(worker, expected, "Worker binary")

    def test_python_test_stub_is_not_a_native_acceptance_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = Path(folder) / "worker.py"
            worker.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "native"):
                _native_binary_format(worker)

    def test_fresh_build_report_uses_only_a_process_local_catalog_copy(self):
        requirements = json.loads(
            (REPO / "catalog/major_requirements.json").read_text(encoding="utf-8")
        )
        before = copy.deepcopy(requirements)
        output = REPO / "work/fresh-wave-a-ci.json"
        copied = _requirements_for_replayed_report(requirements, output, "a" * 64)
        self.assertEqual(requirements, before)
        original_items = {
            item["id"]: item for family in requirements["families"]
            for item in family["requirements"]
        }
        copied_items = {
            item["id"]: item for family in copied["families"]
            for item in family["requirements"]
        }
        changed = {
            requirement_id for requirement_id in original_items
            if original_items[requirement_id] != copied_items[requirement_id]
        }
        self.assertEqual(changed, {f"major.7.7.{number:02d}" for number in range(1, 7)})
        for requirement_id in changed:
            self.assertEqual(copied_items[requirement_id]["operation_ids"],
                             ["mesh.simplify.edge_collapse"])
            self.assertEqual(copied_items[requirement_id]["evidence"], [{
                "path": "work/fresh-wave-a-ci.json", "sha256": "a" * 64,
            }])

    def test_fresh_report_output_cannot_overwrite_catalog_or_escape_work(self):
        self.assertEqual(
            _approved_output_path(REPO / "work/fresh-wave-a-ci.json"),
            (REPO / "work/fresh-wave-a-ci.json").resolve(),
        )
        with self.assertRaisesRegex(ValueError, "published snapshot"):
            _approved_output_path(REPO / "catalog/major_requirements.json")
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "published snapshot"):
                _approved_output_path(Path(folder) / "wave-a.json")

    def test_published_report_requires_the_checked_catalog_digest(self):
        requirements = json.loads(
            (REPO / "catalog/major_requirements.json").read_text(encoding="utf-8")
        )
        with self.assertRaisesRegex(ValueError, "evidence hash is stale"):
            _requirements_for_replayed_report(requirements, REPO /
                                              "docs/master/evidence/wave-a-capabilities.json",
                                              "f" * 64)

    def test_replay_worker_forces_an_actual_evaluator_rerun(self):
        _report, _item, operations = wave_context()
        requirements = json.loads(
            (REPO / "catalog/major_requirements.json").read_text(encoding="utf-8")
        )
        with mock.patch(
            "scripts.replay_master_capabilities.replay",
            side_effect=RuntimeError("proof that evaluator attempted the approved replay"),
        ) as rerun:
            evaluated = evaluate_requirements(
                requirements, operations, REPO,
                replay_worker=REPO / "build-master/Release/cgal-master-worker.exe",
            )
        rerun.assert_called_once()
        wave_rows = [
            row for row in evaluated["requirements"]
            if row["id"].startswith("major.7.7.")
        ]
        self.assertEqual(len(wave_rows), 6)
        self.assertTrue(all(row["status"] == "INCOMPLETE" for row in wave_rows))


if __name__ == "__main__":
    unittest.main()
