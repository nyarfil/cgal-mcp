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
from scripts import master_replay_families as replay_families
from scripts.replay_master_capabilities import (
    REPLAY_FAMILIES,
    family_bindings,
    published_output,
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
        self.assertEqual([call.args[1] for call in rerun.call_args_list], list(REPLAY_FAMILIES))
        bound = {requirement_id for family in REPLAY_FAMILIES
                 for requirement_id in family_bindings(family)}
        replay_rows = [row for row in evaluated["requirements"] if row["id"] in bound]
        self.assertEqual(len(replay_rows), 80)
        self.assertTrue(all(row["status"] == "INCOMPLETE" for row in replay_rows))


NOT_REPLAYED = "Evidence has not been reproduced by the acceptance runner for this build"


def family_context(requirement_id: str) -> tuple[dict, dict, dict[str, dict]]:
    family = ".".join(requirement_id.split(".")[1:3])
    report = json.loads(published_output(family).read_text(encoding="utf-8"))
    _wave_report, item, operations = wave_context(requirement_id)
    return report, item, operations


def rehash(exchange: dict) -> None:
    for field in ("request", "response"):
        exchange[f"{field}_sha256"] = _canonical_hash(exchange[field])


GENERIC_BOUND = sorted(requirement_id for family in replay_families.GENERIC_FAMILIES.values()
                       for requirement_id in family["requirements"])


class GenericFamilyReplayTests(unittest.TestCase):
    def test_every_bound_requirement_exercises_every_ledger_symbol(self):
        inventory = json.loads(
            (REPO / "catalog/major_capability_inventory.json").read_text(encoding="utf-8"))
        ledger = {item["id"]: {sub["symbol"] for sub in item["subcapabilities"]}
                  for item in inventory["items"]}
        checked = 0
        for family in replay_families.GENERIC_FAMILIES.values():
            for requirement_id, binding in family["requirements"].items():
                with self.subTest(requirement_id):
                    checked += 1
                    self.assertTrue(ledger[requirement_id])
                    self.assertEqual(sorted(ledger[requirement_id] - set(binding["symbols"])), [])
        self.assertEqual(checked, 74)

    def test_published_family_reports_fail_only_for_missing_replay(self):
        for requirement_id in GENERIC_BOUND:
            with self.subTest(requirement_id):
                report, item, operations = family_context(requirement_id)
                self.assertEqual(_evidence_reasons(report, item, operations, REPO), [NOT_REPLAYED])

    def test_bound_and_unbound_partition_the_family_requirements(self):
        requirements = json.loads((REPO / "catalog/major_requirements.json").read_text(encoding="utf-8"))
        items = {item["id"]: item for family in requirements["families"]
                 for item in family["requirements"]}
        for family_id, family in replay_families.GENERIC_FAMILIES.items():
            ids = {rid for rid in items if rid.startswith(f"major.{family_id}.")}
            self.assertEqual(set(family["requirements"]) | set(family["unbound"]), ids)
            self.assertFalse(set(family["requirements"]) & set(family["unbound"]))
            for requirement_id in family["unbound"]:
                self.assertEqual(items[requirement_id]["evidence"], [])

    def test_family_report_contains_no_repository_host_path(self):
        roots = {str(REPO).lower(), REPO.as_posix().lower()}
        for family in replay_families.GENERIC_FAMILIES:
            report = json.loads(published_output(family).read_text(encoding="utf-8"))
            self.assertFalse(any(any(root in value.lower() for root in roots)
                                 for value in string_values(report)), family)

    def test_unbound_requirement_cannot_borrow_family_evidence(self):
        report, item, operations = family_context("major.7.3.01")
        item = copy.deepcopy(item)
        item["id"] = "major.7.3.99"  # every real 7.3 requirement is bound; use an undeclared id
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Family contract leaves this requirement unbound: major.7.3.99", reasons)

    def test_other_family_report_cannot_establish_requirement(self):
        report, _item, operations = family_context("major.7.3.01")
        _report, item, _operations = family_context("major.7.4.01")
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence family/scope differs from the requirement family", reasons)

    def test_family_without_contract_is_rejected(self):
        report, item, operations = family_context("major.7.3.01")
        item = copy.deepcopy(item)
        item["id"] = "major.7.16.01"
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("No replay family contract declares this requirement: major.7.16.01", reasons)

    def test_missing_family_mandatory_validator_is_rejected(self):
        report, item, operations = family_context("major.7.9.01")
        result = next(r for r in report["operation_results"] if r["validators"])
        result["validators"].pop()
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn(f"Evidence mandatory validator chain is incomplete: {result['case_id']}", reasons)

    def test_rehashed_behaviour_tamper_is_rejected(self):
        report, item, operations = family_context("major.7.3.04")
        result = next(r for r in report["operation_results"]
                      if any(a[0].startswith("metrics.") for a in
                             next(c for c in replay_families.GENERIC_FAMILIES["7.3"]["cases"]
                                  if c["id"] == r["case_id"])["assertions"]))
        case = next(c for c in replay_families.GENERIC_FAMILIES["7.3"]["cases"]
                    if c["id"] == result["case_id"])
        selector = next(a[0] for a in case["assertions"] if a[0].startswith("metrics."))
        target = result["response"]["metrics"]
        keys = selector.split(".")[1:]
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = "tampered"
        rehash(result)
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn(f"Evidence family behaviour assertions fail: {result['case_id']}", reasons)

    def test_validator_parameter_tamper_is_rejected(self):
        report, item, operations = family_context("major.7.4.05")
        result = next(r for r in report["operation_results"] if r["validators"])
        validator = result["validators"][0]
        validator["request"]["parameters"]["tampered"] = True
        rehash(validator)
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence validator exchange is not registry-derived: "
                      f"{result['case_id']}/{validator['operation_id']}", reasons)

    def test_dropped_family_case_is_rejected(self):
        report, item, operations = family_context("major.7.3.04")
        report["operation_results"].pop()
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence family case set differs from the contract", reasons)

    def test_negative_control_tamper_is_rejected(self):
        report, item, operations = family_context("major.7.5.02")
        control_id, proof = next(iter(report["negative_control_proofs"].items()))
        proof["response"]["error"]["class"] = "TAMPERED"
        rehash(proof)
        reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn(f"Evidence family negative control mismatch: {control_id}", reasons)

    def test_contract_change_invalidates_published_family_report(self):
        report, item, operations = family_context("major.7.3.01")
        changed = copy.deepcopy(replay_families.GENERIC_FAMILIES["7.3"])
        changed["cases"][0]["assertions"].pop()
        with mock.patch.dict(replay_families.GENERIC_FAMILIES, {"7.3": changed}):
            reasons = _evidence_reasons(report, item, operations, REPO)
        self.assertIn("Evidence family contract hash mismatch", reasons)

    def test_contract_rejects_bound_requirement_without_cases(self):
        changed = copy.deepcopy(replay_families.GENERIC_FAMILIES["7.4"])
        first = next(iter(changed["requirements"]))
        changed["requirements"][first]["case_ids"] = []
        with self.assertRaises(ValueError):
            replay_families.validate_contract(changed)

    def test_assertion_vocabulary_is_closed(self):
        changed = copy.deepcopy(replay_families.GENERIC_FAMILIES["7.3"])
        changed["cases"][0]["assertions"].append(["metrics.x", "eval", "1"])
        with self.assertRaises(ValueError):
            replay_families.validate_contract(changed)


class SearchGateEvidenceTests(unittest.TestCase):
    """The search gate is decided from verified, replayable retrieval evidence."""

    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(
            (REPO / acceptance_module.SEARCH_EVIDENCE).read_text(encoding="utf-8"))

    def gate(self, evidence=None):
        return acceptance_module.evaluate_search_gate(
            REPO, live=False, evidence=evidence if evidence is not None else copy.deepcopy(self.evidence))

    def test_checked_in_evidence_binds_current_sources_and_stays_honest(self):
        result = self.gate()
        self.assertEqual(result["status"], "unmet")
        self.assertFalse([r for r in result["reasons"] if "bindings differ" in r or "case" in r])
        self.assertEqual(result["measured"]["overall"]["denominator"], 300)
        self.assertIn(acceptance_module.SEARCH_GATE, acceptance_module.WAVE_A_UNMET_STANDALONE_GATES)
        self.assertEqual(len(acceptance_module.WAVE_A_UNMET_STANDALONE_GATES), 4)

    def test_live_search_reproduces_the_recorded_measurement(self):
        result = acceptance_module.evaluate_search_gate(REPO, live=True)
        self.assertTrue(result["live_rerun"])
        self.assertFalse([r for r in result["reasons"] if "fresh run" in r or "bindings" in r])

    def test_recorded_hit_flip_is_rejected(self):
        evidence = copy.deepcopy(self.evidence)
        miss = next(case for case in evidence["cases"] if not case["top3"])
        miss["top3"] = True
        self.assertTrue([r for r in self.gate(evidence)["reasons"] if "inconsistent" in r])

    def test_edited_returned_operations_are_rejected_by_summary(self):
        evidence = copy.deepcopy(self.evidence)
        miss = next(case for case in evidence["cases"] if not case["top3"])
        miss["returned"] = list(miss["expected"][:1])
        miss["top3"] = True
        miss["top1"] = True
        self.assertIn("Search retrieval summary differs from its recorded cases",
                      self.gate(evidence)["reasons"])

    def test_expected_operation_must_match_catalog_binding(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["cases"][0]["expected"] = ["mesh.simplify.edge_collapse"]
        self.assertTrue([r for r in self.gate(evidence)["reasons"] if "catalog binding" in r])

    def test_stale_bindings_are_rejected(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["bindings"]["search_vocabulary_sha256"] = "0" * 64
        self.assertTrue([r for r in self.gate(evidence)["reasons"] if "bindings differ" in r])

    def test_gate_cannot_be_met_without_the_target_and_full_acceptance(self):
        evidence = copy.deepcopy(self.evidence)
        for case in evidence["cases"]:
            case["returned"] = case["expected"][:1]
            case["top1"] = case["top3"] = True
        from scripts import evaluate_master_search as search_eval
        evidence["summary"] = {
            "overall": search_eval._retrieval_summary(evidence["cases"]),
            "development": search_eval._retrieval_summary(
                [c for c in evidence["cases"] if c["split"] == "development"]),
            "held_out": search_eval._retrieval_summary(
                [c for c in evidence["cases"] if c["split"] == "held_out"])}
        retrieval_only = self.gate(evidence)
        self.assertEqual(retrieval_only["status"], "unmet")
        self.assertTrue(retrieval_only["retrieval_target_met"])
        evidence["full_search_acceptance"]["passes_search_acceptance"] = True
        both = self.gate(evidence)
        # Retrieval and typed acceptance alone cannot meet the gate: automatic
        # execution is only sampled and the blind generalization set is below target.
        self.assertEqual(both["status"], "unmet")
        self.assertTrue([r for r in both["reasons"] if "Blind-set top-3" in r])
        self.assertTrue([r for r in both["reasons"] if "Automatic execution" in r])


class WorkflowGateEvidenceTests(unittest.TestCase):
    """The workflow gate is decided from recorded real-runtime workflow evidence."""

    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(
            (REPO / acceptance_module.WORKFLOW_EVIDENCE).read_text(encoding="utf-8"))

    def gate(self, evidence=None):
        return acceptance_module.evaluate_workflow_gate(
            REPO, live=False, evidence=evidence if evidence is not None else copy.deepcopy(self.evidence))

    def test_checked_in_evidence_is_consistent_and_planner_features_are_evidenced(self):
        result = self.gate()
        measured = result["measured"]
        self.assertGreaterEqual(measured["positive_succeeded"], 30)
        self.assertEqual(measured["positive_workflows"], measured["positive_succeeded"])
        self.assertEqual(measured["validator_omissions"], 0)
        self.assertEqual(measured["estimate_problems"], 0)
        self.assertGreaterEqual(measured["validator_rejections"], 1)
        self.assertEqual(result["planner_features"], {
            "fallback_chain": True, "cost_risk_estimate": True,
            "automatic_preprocess_postprocess": True})
        self.assertEqual(result["status"], "met_pending_gate_list_update")
        self.assertEqual(len(result["reasons"]), 1)
        self.assertIn(acceptance_module.WORKFLOW_GATE, acceptance_module.WAVE_A_UNMET_STANDALONE_GATES)

    def test_tampered_estimate_is_detected(self):
        evidence = copy.deepcopy(self.evidence)
        case = next(c for c in evidence["cases"] if c["category"] == "positive")
        case["plan"]["estimate"]["steps"][0]["cost_units"] += 5
        self.assertTrue([r for r in self.gate(evidence)["reasons"] if "estimate problem" in r])

    def test_dropped_or_unrecorded_inserted_step_metadata_is_detected(self):
        evidence = copy.deepcopy(self.evidence)
        case = next(c for c in evidence["cases"] if c["id"].startswith("wf42"))
        for step in case["plan"]["steps"]:
            step.pop("inserted_by", None)
        reasons = self.gate(evidence)["reasons"]
        self.assertTrue([r for r in reasons if "estimate problem" in r or "not evidenced" in r])

    def test_silent_fallback_is_detected(self):
        evidence = copy.deepcopy(self.evidence)
        case = next(c for c in evidence["cases"] if c["id"].startswith("wf44"))
        case["outcome"]["fallback_chain"][0]["error_code"] = None
        self.assertTrue([r for r in self.gate(evidence)["reasons"] if "Fallback chain is inconsistent" in r])
        evidence = copy.deepcopy(self.evidence)
        case = next(c for c in evidence["cases"] if c["id"].startswith("wf44"))
        del case["outcome"]["fallback_chain"]
        self.assertTrue(self.gate(evidence)["reasons"])

    def test_live_rerun_through_the_real_runtime_reproduces_the_evidence(self):
        worker = REPO / "build-master/Release/cgal-master-worker.exe"
        if not worker.is_file():
            self.skipTest("native worker is not built")
        result = acceptance_module.evaluate_workflow_gate(REPO, live=True, worker=worker)
        self.assertTrue(result["measured"]["live_rerun"])
        self.assertFalse([r for r in result["reasons"] if "fresh run" in r or "bindings" in r])

    def test_dropped_validator_is_counted_as_an_omission(self):
        evidence = copy.deepcopy(self.evidence)
        case = next(c for c in evidence["cases"] if c["category"] == "positive")
        victim = next(step for step in case["plan"]["steps"] if step["role"] == "validator")
        case["plan"]["steps"].remove(victim)
        reasons = self.gate(evidence)["reasons"]
        self.assertTrue([r for r in reasons if "Planned validators differ" in r])

    def test_failed_validator_verdict_cannot_pass_a_workflow(self):
        evidence = copy.deepcopy(self.evidence)
        case = next(c for c in evidence["cases"] if c["category"] == "positive")
        case["validators"][0]["status"] = "fail"
        reasons = self.gate(evidence)["reasons"]
        self.assertTrue([r for r in reasons if "Validator did not run to a pass" in r])

    def test_negative_workflow_that_succeeds_or_publishes_is_rejected(self):
        evidence = copy.deepcopy(self.evidence)
        case = next(c for c in evidence["cases"] if c["category"] == "negative")
        case["store_published_delta"] = 1
        reasons = self.gate(evidence)["reasons"]
        self.assertTrue([r for r in reasons if "silently passed or published" in r])

    def test_outcome_must_match_the_declared_expectation(self):
        evidence = copy.deepcopy(self.evidence)
        case = next(c for c in evidence["cases"]
                    if c["outcome"].get("state") == "rejected")
        case["outcome"]["code"] = "SOMETHING_ELSE"
        self.assertTrue([r for r in self.gate(evidence)["reasons"] if "differs from its expectation" in r])

    def test_unit_propagation_tamper_is_detected(self):
        evidence = copy.deepcopy(self.evidence)
        case = next(c for c in evidence["cases"] if c["category"] == "positive"
                    and any(o["unit"] == "cm" for o in c["outputs"]))
        case["outputs"][0]["unit"] = "mm"
        self.assertTrue([r for r in self.gate(evidence)["reasons"] if "Unit propagation" in r])

    def test_tampered_bindings_or_missing_cases_are_rejected(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["bindings"]["planner_sha256"] = "0" * 64
        self.assertTrue([r for r in self.gate(evidence)["reasons"] if "bindings differ" in r])
        evidence = copy.deepcopy(self.evidence)
        evidence["cases"].pop()
        evidence["count"] -= 1
        self.assertIn("Workflow evidence does not cover exactly the declared workflows",
                      self.gate(evidence)["reasons"])

    def test_single_operation_bias_and_count_floor_are_enforced(self):
        spec = json.loads((REPO / acceptance_module.WORKFLOW_SPEC).read_text(encoding="utf-8"))
        evidence = copy.deepcopy(self.evidence)
        keep = [i for i, w in enumerate(spec["workflows"]) if w["category"] == "negative"
                or i < 10]
        spec["workflows"] = [spec["workflows"][i] for i in keep]
        evidence["cases"] = [evidence["cases"][i] for i in keep]
        evidence["count"] = len(keep)
        reasons = acceptance_module.evaluate_workflow_gate(
            REPO, live=False, evidence=evidence, spec=spec)["reasons"]
        self.assertTrue([r for r in reasons if "positive workflows (need 30+)" in r])


class PerformanceGateEvidenceTests(unittest.TestCase):
    """The performance/robustness gate is decided from recorded real-worker evidence."""

    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(
            (REPO / acceptance_module.PERFORMANCE_EVIDENCE).read_text(encoding="utf-8"))

    def gate(self, evidence=None, rehash=True):
        evidence = copy.deepcopy(self.evidence) if evidence is None else evidence
        if rehash:
            evidence["deterministic_sha256"] = acceptance_module._canonical_hash(evidence["deterministic"])
        return acceptance_module.evaluate_performance_gate(REPO, live=False, evidence=evidence)

    def test_checked_in_evidence_is_bound_and_reports_true_status(self):
        result = self.gate(rehash=False)
        self.assertNotEqual(result["status"], "met")
        self.assertFalse([r for r in result["reasons"] if "bindings" in r or "hash" in r or "different native" in r])
        self.assertEqual(len(result["measured"]["families_with_baselines"]), 15)
        containment = result["measured"]["containment"]
        self.assertEqual(containment["contained"], containment["trials"])
        self.assertFalse([r for r in result["reasons"] if "contained" in r and "Fault mode" in r])

    def test_tampered_deterministic_content_is_detected(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["deterministic"]["containment"]["exit_kill"]["contained"] = 0
        result = self.gate(evidence, rehash=False)
        self.assertTrue([r for r in result["reasons"] if "hash does not match" in r])

    def test_uncontained_trial_and_low_trial_count_fail_the_gate(self):
        evidence = copy.deepcopy(self.evidence)
        record = evidence["deterministic"]["containment"]["abort"]
        record["contained"] -= 1
        record["failures"] = ["trial 3: worker process left running or never started"]
        record["trials"] = 5
        reasons = self.gate(evidence)["reasons"]
        self.assertTrue([r for r in reasons if "Fault mode abort contained" in r])
        self.assertTrue([r for r in reasons if "Fault mode abort has 5 trials" in r])

    def test_missing_family_or_fault_kind_fails_the_gate(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["deterministic"]["scale_cases"] = [
            c for c in evidence["deterministic"]["scale_cases"] if c["family"] != "7.9"]
        del evidence["deterministic"]["containment"]["access_violation"]
        reasons = self.gate(evidence)["reasons"]
        self.assertTrue([r for r in reasons if "Family 7.9 lacks" in r])
        self.assertTrue([r for r in reasons if "segfault_like" in r])

    def test_failed_limit_case_and_unmeasured_memory_fail_the_gate(self):
        evidence = copy.deepcopy(self.evidence)
        case = evidence["deterministic"]["limit_cases"][0]
        case["observed"] = {"stage": "none"}
        case["passed"] = False
        first = evidence["deterministic"]["scale_cases"][0]
        evidence["timings"]["scale"][f"{first['family']}:{first['operation']}:{first['scale']}"].pop(
            "peak_worker_rss_bytes", None)
        reasons = self.gate(evidence)["reasons"]
        self.assertTrue([r for r in reasons if f"Resource-limit case {case['id']}" in r])
        self.assertTrue([r for r in reasons if "no measured peak worker memory" in r])

    def test_phase10_work_items_are_never_silently_dropped(self):
        evidence = copy.deepcopy(self.evidence)
        reasons = self.gate(evidence)["reasons"]
        self.assertTrue([r for r in reasons if "Persistent workers are not implemented" in r])
        self.assertTrue([r for r in reasons if "cache and AABB reuse are not implemented" in r])

    def test_fault_proxy_is_selected_only_by_environment_not_protocol_input(self):
        import subprocess, sys, os
        worker = REPO / "build-master/Release/cgal-master-worker.exe"
        if not worker.is_file():
            self.skipTest("native worker is not built")
        env = {**os.environ, "CGAL_ROBUST_REAL_WORKER": str(worker)}
        env.pop("CGAL_ROBUST_FAULT", None)
        request = json.dumps({"protocol": 1, "request_id": "x", "operation": "no.such", "fault": "exit_kill",
                              "CGAL_ROBUST_FAULT": "exit_kill"}).encode() + b"\n"
        done = subprocess.run([sys.executable, str(REPO / "scripts/robustness_fault_proxy.py")],
                              input=request, capture_output=True, env=env, timeout=60)
        self.assertNotEqual(done.returncode, 137)

    def test_live_containment_rerun_including_grandchild_hang(self):
        worker = REPO / "build-master/Release/cgal-master-worker.exe"
        if not worker.is_file():
            self.skipTest("native worker is not built")
        from scripts import measure_master_robustness as rob
        fresh = rob.measure(REPO, worker, stages=("faults",),
                            only_modes=["hang_with_child", "exit_kill"], trials=1, host_kill_trials=0)
        for record in fresh["deterministic"]["containment"].values():
            self.assertEqual(record["contained"], record["trials"], record["failures"])


if __name__ == "__main__":
    unittest.main()
