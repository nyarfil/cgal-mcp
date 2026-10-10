"""Evidence-gated Master acceptance; discovery never counts as implementation."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

from scripts import master_replay_families as replay_families

REPO = Path(__file__).resolve().parents[1]
ORIGINALS = {
    "CGAL_Master_MCP_Design_Spec.md": "44cbb8b0e93abf0216c12f0fd6c9e35b6d04534dff83b9dafe07051625a727fd",
    "CGAL_Master_MCP_Implementation_Plan.md": "4631700c95f72101aef8e417171888f5e52ece7420d2d6f88735e91bfd130183",
}

WAVE_A_REQUIREMENT_CASES = {
    "major.7.7.01": frozenset({
        "policy-lindstrom_turk", "policy-edge_length_midpoint", "policy-gh_plane",
        "policy-gh_triangle", "policy-gh_plane_line", "policy-gh_probabilistic_plane",
        "policy-gh_probabilistic_triangle", "stop-edge_count", "stop-edge_ratio",
        "stop-face_count", "stop-face_ratio", "stop-edge_length", "constraints",
        "preserve-open-border", "bounded-distance", "bounded-normal", "polyhedral-envelope",
        "filter-control", "bounded-distance-tight", "polyhedral-envelope-tight",
        "bounded-normal-adversarial",
        "stop-edge_length-below-minimum",
    }),
    "major.7.7.02": frozenset({
        "policy-lindstrom_turk", "stop-edge_count", "stop-edge_ratio",
        "stop-face_count", "stop-face_ratio", "stop-edge_length",
        "stop-edge_length-below-minimum",
    }),
    "major.7.7.03": frozenset({
        "policy-gh_plane", "policy-gh_triangle", "policy-gh_plane_line",
        "policy-gh_probabilistic_plane", "policy-gh_probabilistic_triangle",
    }),
    "major.7.7.04": frozenset({
        "policy-lindstrom_turk", "policy-edge_length_midpoint", "policy-gh_plane",
        "policy-gh_triangle", "policy-gh_plane_line", "policy-gh_probabilistic_plane",
        "policy-gh_probabilistic_triangle", "constraints", "preserve-open-border",
        "bounded-distance", "filter-control", "bounded-distance-tight",
    }),
    "major.7.7.05": frozenset({
        "polyhedral-envelope", "filter-control", "polyhedral-envelope-tight",
    }),
    "major.7.7.06": frozenset({
        "bounded-normal", "bounded-normal-adversarial",
    }),
}
WAVE_A_TRANSFORM = "mesh.simplify.edge_collapse"
WAVE_A_VALIDATORS = (
    "mesh.validate.simplification_integrity",
    "mesh.distance.symmetric_hausdorff",
)
WAVE_A_POLICY_CASES = {
    **{f"{WAVE_A_TRANSFORM}.cost_placement.{name}": frozenset({f"policy-{name}"}) for name in (
        "lindstrom_turk", "edge_length_midpoint", "gh_plane", "gh_triangle", "gh_plane_line",
        "gh_probabilistic_plane", "gh_probabilistic_triangle",
    )},
    **{f"{WAVE_A_TRANSFORM}.stop_predicate.{name}": frozenset(
        {f"stop-{name}", "stop-edge_length-below-minimum"}
        if name == "edge_length" else {f"stop-{name}"}
    ) for name in (
        "edge_count", "edge_ratio", "face_count", "face_ratio", "edge_length",
    )},
    f"{WAVE_A_TRANSFORM}.wrapper.constraints": frozenset({"constraints", "preserve-open-border"}),
    f"{WAVE_A_TRANSFORM}.wrapper.bounded_distance": frozenset({
        "bounded-distance", "filter-control", "bounded-distance-tight",
    }),
    f"{WAVE_A_TRANSFORM}.filter.bounded_normal_change": frozenset({
        "bounded-normal", "bounded-normal-adversarial",
    }),
    f"{WAVE_A_TRANSFORM}.filter.polyhedral_envelope": frozenset({
        "polyhedral-envelope", "filter-control", "polyhedral-envelope-tight",
    }),
}
WAVE_A_BOUNDED_NORMAL_CONTROL = "bounded-normal-control"
WAVE_A_BOUNDED_NORMAL_FILTERED = "bounded-normal-adversarial"
WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256 = (
    "02fa9498ee15d604a00a79a6e903d82618afa3e65ed5e1c3118864a5a61e1f04"
)
WAVE_A_BOUNDED_NORMAL_ERROR_CLASS = "VALIDATION_FAILED"
WAVE_A_BOUNDED_NORMAL_ERROR_CODE = "OPEN_SURFACE_WINDING_CHANGED"
WAVE_A_BOUNDED_NORMAL_ANALYTIC_PROOF = {
    "source_sha256": WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256,
    "decimal_token_domain": {
        "unique_short_edge": [1, 3],
        "short_edge_squared": {
            "numerator": 17, "denominator": 10000, "unit": "mm^2",
        },
        "next_edge_squared_greater_than": {
            "numerator": 1, "denominator": 100, "unit": "mm^2",
        },
        "collapse_midpoint": ["0", "-1/100", "1/200"],
        "original_normal": ["0", "0", "1/50"],
        "collapsed_normal": ["0", "-1/100", "-1/50"],
        "normal_scalar_product": {"numerator": -1, "denominator": 2500},
    },
    "binary64_storage_domain": {
        "conversion": "exact rational of IEEE-754 binary64 parsed coordinates",
        "unique_short_edge": [1, 3],
        "short_edge_squared_less_than_stop_squared": True,
        "next_edge_squared_greater_than_stop_squared": True,
        "normal_scalar_product_sign": "negative",
        "normal_scalar_product_less_than": {"numerator": -3, "denominator": 10000},
    },
}
WAVE_A_UNMET_STANDALONE_GATES = {
    "search_and_retrieval_acceptance",
    "multi_operation_workflow_acceptance",
    "host_compatibility_matrix",
    "performance_resource_and_robustness_acceptance",
}


def verify_originals(root: Path = REPO) -> dict:
    checks = {}
    for name, expected in ORIGINALS.items():
        path = root / "docs" / "master" / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        checks[name] = {"sha256": actual, "matches_original": actual == expected}
    if not all(item["matches_original"] for item in checks.values()):
        raise ValueError("Original Master document bytes changed")
    return checks


def extract_requirements(root: Path = REPO) -> dict:
    verify_originals(root)
    path = root / "docs/master/CGAL_Master_MCP_Implementation_Plan.md"
    families = []
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^## (7\.(\d+)) (.+)$", line)
        if heading:
            number = int(heading[2])
            if not 1 <= number <= 15:
                raise ValueError("Unexpected major-family number")
            current = {"id": heading[1], "title": heading[3], "requirements": []}
            families.append(current)
        elif line.startswith("#") and not line.startswith("###"):
            current = None
        elif current is not None and line.startswith("- "):
            n = len(current["requirements"]) + 1
            current["requirements"].append({
                "id": f"major.{current['id']}.{n:02d}",
                "description": line[2:],
                "required": True,
                "operation_ids": [],
                "evidence": [],
            })
    if [f["id"] for f in families] != [f"7.{n}" for n in range(1, 16)]:
        raise ValueError("All fifteen original major families must be retained")
    if any(not f["requirements"] for f in families):
        raise ValueError("Empty family cannot establish complete coverage")
    return {
        "schema_version": 1,
        "source": "docs/master/CGAL_Master_MCP_Implementation_Plan.md",
        "source_sha256": ORIGINALS[path.name],
        "acceptance_policy": "all_listed_major_requirements_validated",
        "catalog_target_percent": 100,
        "major_requirements_target_percent": 100,
        "families": families,
    }


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _source_digest(path: Path, encoding: object) -> str | None:
    content = path.read_bytes()
    if encoding == "utf8-lf":
        content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    elif encoding is not None:
        return None
    return hashlib.sha256(content).hexdigest()


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _string_members(value: object) -> set[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return set(value)


def _verified_blobs(report: dict) -> tuple[set[str], list[str]]:
    verified: set[str] = set()
    reasons = []
    blobs = report.get("blobs")
    if not isinstance(blobs, dict) or not blobs:
        return verified, ["Evidence has no portable fixture/output blobs"]
    for digest, value in blobs.items():
        if not _valid_digest(digest) or not isinstance(value, dict) or value.get("encoding") != "base64":
            reasons.append("Evidence contains an invalid portable blob record")
            continue
        try:
            content = base64.b64decode(value.get("content", ""), validate=True)
        except (ValueError, TypeError):
            reasons.append(f"Evidence blob is not strict base64: {digest}")
            continue
        if (hashlib.sha256(content).hexdigest() != digest or
                value.get("byte_size") != len(content)):
            reasons.append(f"Evidence blob hash/size mismatch: {digest}")
            continue
        verified.add(digest)
    return verified, reasons


def _verified_reports(report: dict) -> tuple[set[str], list[str]]:
    verified: set[str] = set()
    reasons = []
    reports = report.get("reports")
    if not isinstance(reports, dict) or not reports:
        return verified, ["Evidence has no validator reports"]
    for digest, value in reports.items():
        if not _valid_digest(digest) or digest != _canonical_hash(value):
            reasons.append(f"Evidence validator report hash mismatch: {digest}")
            continue
        verified.add(digest)
    return verified, reasons


def _hash_bound_exchange(value: dict, label: str) -> list[str]:
    reasons = []
    for field in ("request", "response"):
        content = value.get(field)
        if not isinstance(content, dict) or value.get(f"{field}_sha256") != _canonical_hash(content):
            reasons.append(f"Evidence {label} {field} hash mismatch")
    return reasons


def _exchange_blob_hashes(value: object, field: str) -> list[str] | None:
    if not isinstance(value, dict):
        return None
    items = value.get(field)
    if not isinstance(items, list) or not items or not all(isinstance(item, dict) for item in items):
        return None
    hashes = [item.get("blob_sha256") for item in items]
    if not all(_valid_digest(digest) for digest in hashes):
        return None
    return hashes


def _bounded_normal_negative_control_reasons(
    report: dict,
    indexed_results: dict[str, dict],
    operations: dict[str, dict],
    declared: dict[str, dict],
    tests: dict[str, dict],
    blob_hashes: set[str],
    manifest_digest: str | None,
) -> list[str]:
    """Validate the replayed rejection proof without treating it as a good output."""
    reasons: list[str] = []
    proofs = report.get("negative_control_proofs")
    if (not isinstance(proofs, dict) or
            set(proofs) != {WAVE_A_BOUNDED_NORMAL_CONTROL} or
            not isinstance(proofs.get(WAVE_A_BOUNDED_NORMAL_CONTROL), dict)):
        return ["Evidence bounded-normal negative control proof is missing"]
    proof = proofs[WAVE_A_BOUNDED_NORMAL_CONTROL]
    positive = indexed_results.get(WAVE_A_BOUNDED_NORMAL_FILTERED)
    transform = operations.get(WAVE_A_TRANSFORM, {})
    transform_handler = declared.get(WAVE_A_TRANSFORM, {})
    integrity_id = WAVE_A_VALIDATORS[0]
    integrity = operations.get(integrity_id, {})
    integrity_handler = declared.get(integrity_id, {})

    if (proof.get("case_id") != WAVE_A_BOUNDED_NORMAL_CONTROL or
            WAVE_A_BOUNDED_NORMAL_CONTROL in indexed_results):
        reasons.append("Evidence negative control was counted as a positive geometry case")
    if (proof.get("operation_id") != WAVE_A_TRANSFORM or
            proof.get("revision") != transform.get("revision") or
            transform_handler.get("revision") != transform.get("revision") or
            proof.get("worker_manifest_sha256") != manifest_digest or
            proof.get("test_id") not in tests or
            proof.get("status") != "expected_rejection" or
            proof.get("paired_positive_case_id") != WAVE_A_BOUNDED_NORMAL_FILTERED):
        reasons.append("Evidence bounded-normal negative control build/test binding mismatch")
    reasons.extend(_hash_bound_exchange(proof, "bounded-normal negative control"))

    input_hashes = proof.get("input_hashes")
    output_hashes = proof.get("output_hashes")
    if (input_hashes != [WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256] or
            not isinstance(output_hashes, list) or len(output_hashes) != 1 or
            output_hashes[0] == WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256 or
            not all(_valid_digest(value) and value in blob_hashes
                    for value in input_hashes + output_hashes)):
        reasons.append("Evidence bounded-normal negative control artifact hashes are invalid")
        candidate_sha256 = None
    else:
        candidate_sha256 = output_hashes[0]
    if (proof.get("input_hashes") != _exchange_blob_hashes(proof.get("request"), "inputs") or
            proof.get("output_hashes") != _exchange_blob_hashes(proof.get("response"), "outputs")):
        reasons.append("Evidence bounded-normal negative control exchange binding mismatch")
    bindings = proof.get("bindings")
    if bindings != {
        "source_sha256": WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256,
        "rejected_candidate_sha256": candidate_sha256,
    }:
        reasons.append("Evidence bounded-normal negative control artifact binding mismatch")

    request = proof.get("request")
    response = proof.get("response")
    parameters = request.get("parameters") if isinstance(request, dict) else None
    metrics = response.get("metrics") if isinstance(response, dict) else None
    if (not isinstance(request, dict) or not isinstance(response, dict) or
            not isinstance(parameters, dict) or request.get("operation") != WAVE_A_TRANSFORM or
            response.get("status") != "ok" or not isinstance(metrics, dict) or
            parameters.get("policy") != "edge_length_midpoint" or
            parameters.get("stop") != {
                "kind": "edge_length", "value": {"value": 0.1, "unit": "mm"},
            } or parameters.get("preserve_border") is not False or
            parameters.get("bounded_normal_change") is not False or
            metrics.get("policy") != "edge_length_midpoint" or
            metrics.get("stop_policy") != "edge_length" or
            metrics.get("bounded_normal_change_enabled") is not False or
            (metrics.get("edges_before"), metrics.get("edges_removed"), metrics.get("edges_after")) !=
            (6, 3, 3)):
        reasons.append("Evidence bounded-normal negative control transform semantics mismatch")

    if proof.get("analytic_fixture") != WAVE_A_BOUNDED_NORMAL_ANALYTIC_PROOF:
        reasons.append("Evidence bounded-normal analytic fixture proof mismatch")

    if isinstance(parameters, dict):
        shared_parameters = dict(parameters)
        control_value = shared_parameters.pop("bounded_normal_change", None)
    else:
        shared_parameters = {}
        control_value = None
    positive_request = positive.get("request") if isinstance(positive, dict) else None
    positive_response = positive.get("response") if isinstance(positive, dict) else None
    positive_parameters = (dict(positive_request.get("parameters", {}))
                           if isinstance(positive_request, dict) else {})
    filtered_value = positive_parameters.pop("bounded_normal_change", None)
    parameter_proof = proof.get("parameter_proof")
    if (control_value is not False or filtered_value is not True or
            shared_parameters != positive_parameters or
            not isinstance(positive_request, dict) or
            not isinstance(positive, dict) or
            proof.get("input_hashes") != positive.get("input_hashes") or
            request.get("kernel") != positive_request.get("kernel") or
            parameter_proof != {
                "only_changed_parameter": "bounded_normal_change",
                "control_value": False,
                "filtered_value": True,
                "shared_parameters_sha256": _canonical_hash(shared_parameters),
            }):
        reasons.append("Evidence bounded-normal parameter proof mismatch")
    positive_metrics = (positive_response.get("metrics", {})
                        if isinstance(positive_response, dict) else {})
    positive_check = (positive.get("validation", {}).get("checks", {}).get(
        "bounded_normal_negative_control") if isinstance(positive, dict) else None)
    if (positive_metrics.get("bounded_normal_change_enabled") is not True or
            (positive_metrics.get("edges_before"), positive_metrics.get("edges_removed"),
             positive_metrics.get("edges_after")) != (6, 0, 6) or
            positive_check != {
                "pass": True,
                "negative_control_id": WAVE_A_BOUNDED_NORMAL_CONTROL,
                "rejected_candidate_sha256": candidate_sha256,
            }):
        reasons.append("Evidence bounded-normal filtered positive result is not bound to the rejection proof")

    failure = proof.get("expected_validator_failure")
    if not isinstance(failure, dict):
        reasons.append("Evidence bounded-normal expected validator failure is missing")
        return reasons
    reasons.extend(_hash_bound_exchange(failure, "bounded-normal expected validator failure"))
    failure_request = failure.get("request")
    failure_response = failure.get("response")
    failure_inputs = failure.get("input_hashes")
    failure_error = (failure_response.get("error")
                     if isinstance(failure_response, dict) else None)
    if (failure.get("operation_id") != integrity_id or
            failure.get("revision") != integrity.get("revision") or
            integrity_handler.get("revision") != integrity.get("revision") or
            failure.get("status") != "expected_error" or
            failure.get("output_hashes") != [] or
            failure_inputs != [candidate_sha256, WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256] or
            not all(_valid_digest(value) and value in blob_hashes
                    for value in failure_inputs if value is not None) or
            not isinstance(failure_request, dict) or
            failure_request.get("operation") != integrity_id or
            failure_request.get("parameters") != {
                "preserve_border": False, "constrained_edges": [],
            } or failure_inputs != _exchange_blob_hashes(failure_request, "inputs") or
            not isinstance(failure_response, dict) or
            failure_response.get("status") != "error" or
            failure_response.get("outputs") != [] or
            failure_response.get("metrics") != {} or
            not isinstance(failure_error, dict) or
            failure_error.get("class") != WAVE_A_BOUNDED_NORMAL_ERROR_CLASS or
            failure_error.get("code") != WAVE_A_BOUNDED_NORMAL_ERROR_CODE):
        reasons.append("Evidence bounded-normal strict validator rejection mismatch")
    if candidate_sha256 is not None and any(
        candidate_sha256 in result.get("output_hashes", [])
        for result in indexed_results.values() if isinstance(result, dict)
    ):
        reasons.append("Evidence rejected bounded-normal candidate was published as positive geometry")
    return reasons


def _generic_family_reasons(report: dict, item: dict, operations: dict[str, dict],
                            declared: dict[str, dict], tests: dict[str, dict],
                            blob_hashes: set[str], report_hashes: set[str], root: Path) -> list[str]:
    """Check a data-declared family report against its checked-in contract."""
    requirement_id = item.get("id", "")
    family_id = ".".join(requirement_id.split(".")[1:3]) if requirement_id.count(".") >= 3 else ""
    family = replay_families.GENERIC_FAMILIES.get(family_id)
    if family is None:
        return [f"No replay family contract declares this requirement: {requirement_id}"]
    reasons: list[str] = []
    binding = family["requirements"].get(requirement_id)
    if binding is None:
        reasons.append(f"Family contract leaves this requirement unbound: {requirement_id}")
    elif item.get("operation_ids") != binding["operation_ids"]:
        reasons.append(f"Requirement operation binding differs from the family contract: {requirement_id}")
    if report.get("family") != family_id or report.get("scope") != family["scope"]:
        reasons.append("Evidence family/scope differs from the requirement family")
    if report.get("family_contract_sha256") != replay_families.contract_digest(family):
        reasons.append("Evidence family contract hash mismatch")
    contract_path = root / replay_families.FAMILY_CONTRACT_PATH
    if (report.get("family_contract_source_path") != replay_families.FAMILY_CONTRACT_PATH or
            not contract_path.is_file() or
            report.get("family_contract_source_sha256") != _source_digest(
                contract_path, report.get("family_contract_source_hash_encoding"))):
        reasons.append("Evidence family contract source mismatch")
    if (report.get("requirements") != list(family["requirements"]) or
            report.get("requirement_coverage") != replay_families.requirement_coverage(family) or
            report.get("unbound_requirements") != family["unbound"] or
            report.get("binding_rule") != replay_families.BINDING_RULE):
        reasons.append("Evidence family requirement coverage differs from the contract")
    if _string_members(report.get("standalone_unmet_gates")) != WAVE_A_UNMET_STANDALONE_GATES:
        reasons.append("Evidence omits unmet standalone acceptance gates")
    test = tests.get(family["test_id"])
    if not isinstance(test, dict) or test.get("source_path") != replay_families.FAMILY_HARNESS_PATH:
        reasons.append("Evidence family harness test record is missing")
    try:
        content = replay_families.blob_bytes(
            {digest: report["blobs"][digest] for digest in blob_hashes})
    except (KeyError, ValueError, TypeError):
        return reasons + ["Evidence family blobs cannot be decoded"]
    results = [result for result in report.get("operation_results", []) if isinstance(result, dict)]
    indexed = {result.get("case_id"): result for result in results}
    expected_cases = {case["id"]: case for case in family["cases"]}
    if len(indexed) != len(results) or set(indexed) != set(expected_cases):
        reasons.append("Evidence family case set differs from the contract")
    for case_id, case in expected_cases.items():
        result = indexed.get(case_id)
        operation = operations.get(case["operation"])
        if not isinstance(result, dict) or not isinstance(operation, dict):
            reasons.append(f"Evidence has no covered family case: {case_id}")
            continue
        request, response = result.get("request"), result.get("response")
        if (result.get("operation_id") != case["operation"] or
                result.get("test_id") != family["test_id"] or
                not isinstance(request, dict) or not isinstance(response, dict) or
                request.get("parameters") != case["parameters"] or
                response.get("status") != "ok" or
                result.get("input_hashes") != [entry["sha256"] for entry in case["inputs"]]):
            reasons.append(f"Evidence family case differs from the contract: {case_id}")
            continue
        try:
            view = replay_families.CaseView(operation, request, response, content)
            failures = replay_families.assertion_failures(case, view)
            validator_ids = replay_families.mandatory_validators(operation)
        except (KeyError, ValueError, TypeError) as error:
            reasons.append(f"Evidence family case cannot be re-checked: {case_id}: {error}")
            continue
        if failures:
            reasons.append(f"Evidence family behaviour assertions fail: {case_id}")
        validators = result.get("validators")
        if (not isinstance(validators, list) or
                [entry.get("operation_id") for entry in validators if isinstance(entry, dict)] != validator_ids or
                len(validators) != len(validator_ids)):
            reasons.append(f"Evidence mandatory validator chain is incomplete: {case_id}")
            continue
        for validator_id, entry in zip(validator_ids, validators):
            validator = operations.get(validator_id, {})
            try:
                plan, parameters = replay_families.derive_validator_plan(
                    operation, validator, case["parameters"])
                expected_inputs = [(view.inputs if kind == "input" else view.outputs)[slot]["blob_sha256"]
                                   for kind, slot in plan]
            except (KeyError, ValueError, TypeError):
                reasons.append(f"Evidence validator binding cannot be derived: {case_id}/{validator_id}")
                continue
            reasons.extend(_hash_bound_exchange(entry, f"validator {case_id}/{validator_id}"))
            validator_request = entry.get("request") if isinstance(entry.get("request"), dict) else {}
            if (entry.get("status") != "pass" or
                    entry.get("revision") != validator.get("revision") or
                    declared.get(validator_id, {}).get("revision") != validator.get("revision") or
                    entry.get("input_hashes") != expected_inputs or
                    _exchange_blob_hashes(validator_request, "inputs") != expected_inputs or
                    validator_request.get("operation") != validator_id or
                    validator_request.get("parameters") != parameters or
                    entry.get("output_hashes") != _exchange_blob_hashes(entry.get("response"), "outputs") or
                    entry.get("output_hashes") != [entry.get("report_blob_sha256")]):
                reasons.append(f"Evidence validator exchange is not registry-derived: {case_id}/{validator_id}")
                continue
            report_value = report.get("reports", {}).get(entry.get("report_sha256"))
            try:
                report_blob = json.loads(content[entry["report_blob_sha256"]].decode("utf-8"))
            except (KeyError, UnicodeError, ValueError, TypeError):
                report_blob = None
            if (entry.get("report_sha256") not in report_hashes or report_blob != report_value or
                    replay_families.validator_report_failures(validator, report_blob, case["operation"])):
                reasons.append(f"Evidence validator report missing/failed: {case_id}/{validator_id}")
    for pair in family["pairs"]:
        first, second = (indexed.get(case_id, {}) for case_id in pair["cases"])
        equal = first.get("output_hashes") == second.get("output_hashes")
        if (first.get("input_hashes") != second.get("input_hashes") or
                equal != (pair["kind"] == "equal_outputs")):
            reasons.append(f"Evidence paired-case check fails: {pair['cases']}")
    proofs = report.get("negative_control_proofs")
    expected_controls = {control["id"]: control for control in family["negative_controls"]}
    if not isinstance(proofs, dict) or set(proofs) != set(expected_controls):
        reasons.append("Evidence family negative controls differ from the contract")
    else:
        for control_id, control in expected_controls.items():
            proof = proofs[control_id]
            response = proof.get("response") if isinstance(proof, dict) else None
            request = proof.get("request") if isinstance(proof, dict) else None
            if (not isinstance(proof, dict) or not isinstance(response, dict) or
                    not isinstance(request, dict) or
                    proof.get("status") != "expected_rejection" or
                    proof.get("operation_id") != control["operation"] or
                    request.get("operation") != control["operation"] or
                    request.get("parameters") != control["parameters"] or
                    proof.get("input_hashes") != [entry["sha256"] for entry in control["inputs"]] or
                    proof.get("input_hashes") != _exchange_blob_hashes(request, "inputs") or
                    proof.get("output_hashes") != [] or response.get("outputs") != [] or
                    response.get("status") != "error" or
                    not isinstance(response.get("error"), dict) or
                    response["error"].get("class") != control["expect_error_class"] or
                    ("expect_error_code" in control and
                     response["error"].get("code") != control["expect_error_code"]) or
                    control_id in indexed):
                reasons.append(f"Evidence family negative control mismatch: {control_id}")
                continue
            reasons.extend(_hash_bound_exchange(proof, f"negative control {control_id}"))
    return reasons


def _evidence_reasons(report: dict, item: dict, operations: dict[str, dict], root: Path,
                      replayed_report: dict | None = None) -> list[str]:
    """Tie evidence to a baseline, actual handler build, fixtures and executable tests."""
    reasons = []
    approved = isinstance(replayed_report, dict) and replayed_report == report
    if not approved:
        reasons.append("Evidence has not been reproduced by the acceptance runner for this build")
    if report.get("schema_version") != 1 or report.get("generator") != "master-capability-acceptance":
        reasons.append("Unknown acceptance evidence schema/generator")
    if report.get("status") != "pass" or item["id"] not in report.get("requirements", []):
        reasons.append("Evidence does not establish this requirement")
    if report.get("standalone_accepted") is not False:
        reasons.append("Capability evidence must not claim full standalone acceptance")
    baseline_path = root / "catalog/baseline.json"
    if not baseline_path.is_file() or report.get("catalog_baseline_sha256") != hashlib.sha256(baseline_path.read_bytes()).hexdigest():
        reasons.append("Evidence catalog baseline mismatch")
    for field, encoding_field, relative in (
        ("operation_registry_sha256", "operation_registry_hash_encoding", "cgal_mcp/master/operations.json"),
        ("policy_catalog_sha256", "policy_catalog_hash_encoding", "cgal_mcp/master/policies.json"),
    ):
        path = root / relative
        if (not path.is_file() or
                report.get(field) != _source_digest(path, report.get(encoding_field))):
            reasons.append(f"Evidence checked source mismatch: {relative}")
    generator_path = (root / str(report.get("generator_source_path", ""))).resolve()
    if (not generator_path.is_relative_to((root / "scripts").resolve()) or
            not generator_path.is_file() or
            report.get("generator_source_sha256") != _source_digest(
                generator_path, report.get("generator_source_hash_encoding"))):
        reasons.append("Evidence generator source mismatch")
    if not _valid_digest(report.get("worker_sha256")):
        reasons.append("Evidence worker executable hash is missing")
    if report.get("worker_binary_format") not in {"pe", "elf", "mach-o"}:
        reasons.append("Evidence worker is not identified as a native executable")
    manifest = report.get("worker_manifest")
    manifest_digest = None
    declared = {}
    if not isinstance(manifest, dict) or manifest.get("protocol") != 1:
        reasons.append("Evidence has no actual worker manifest")
    else:
        manifest_digest = _canonical_hash(manifest)
        build = manifest.get("build", {})
        if (manifest.get("actual_cgal_version") != "6.2.1" or
                manifest.get("worker") != "cgal-master-worker" or
                manifest.get("request_model") != "one_json_line_per_process" or
                build.get("source_kind") != "official_release" or
                build.get("source_sha256") != "b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf" or
                build.get("source_attestation") != "configured_pinned_official_archive" or
                build.get("test_stub") is True or not isinstance(build.get("compiler"), dict)):
            reasons.append("Evidence worker differs from the official CGAL baseline")
        declared = {o.get("id"): o for o in manifest.get("operations", []) if isinstance(o, dict)}
        if report.get("worker_manifest_sha256") != manifest_digest:
            reasons.append("Evidence worker manifest hash mismatch")
    tests = {}
    for case in report.get("tests", []):
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            reasons.append("Evidence has an invalid test record")
            continue
        path = (root / str(case.get("source_path", ""))).resolve()
        if (not path.is_relative_to((root / "tests").resolve()) or not path.is_file() or
                _source_digest(path, case.get("source_hash_encoding")) != case.get("source_sha256") or
                case.get("status") != "pass" or case.get("exit_code") != 0):
            reasons.append("Evidence test source/result mismatch")
            continue
        tests[case["id"]] = case
    blob_hashes, blob_reasons = _verified_blobs(report)
    report_hashes, report_reasons = _verified_reports(report)
    reasons.extend(blob_reasons)
    reasons.extend(report_reasons)
    results = report.get("operation_results", [])
    for operation_id in item.get("operation_ids", []):
        operation = operations.get(operation_id, {})
        handler = declared.get(operation_id, {})
        if handler.get("revision") != operation.get("revision"):
            reasons.append(f"Evidence handler revision mismatch: {operation_id}")
        matches = [r for r in results if isinstance(r, dict) and r.get("operation_id") == operation_id]
        if not matches:
            reasons.append(f"Evidence has no execution result: {operation_id}")
        for result in matches:
            if (result.get("revision") != operation.get("revision") or
                    result.get("worker_manifest_sha256") != manifest_digest or
                    result.get("test_id") not in tests):
                reasons.append(f"Evidence execution/build/test mismatch: {operation_id}")
            reasons.extend(_hash_bound_exchange(result, f"execution {result.get('case_id', operation_id)}"))
            for field in ("input_hashes", "output_hashes"):
                values = result.get(field)
                if (not isinstance(values, list) or not values or
                        not all(_valid_digest(v) and v in blob_hashes for v in values)):
                    reasons.append(f"Evidence fixture/artifact hash missing: {operation_id}")
            if (result.get("input_hashes") != _exchange_blob_hashes(result.get("request"), "inputs") or
                    result.get("output_hashes") != _exchange_blob_hashes(result.get("response"), "outputs")):
                reasons.append(f"Evidence fixture/artifact exchange binding mismatch: {operation_id}")
            validation = result.get("validation")
            if (not isinstance(validation, dict) or validation.get("status") != "pass" or
                    not isinstance(validation.get("checks"), dict) or not validation["checks"] or
                    not all(c.get("pass") is True for c in validation["checks"].values() if isinstance(c, dict)) or
                    not all(isinstance(c, dict) for c in validation["checks"].values())):
                reasons.append(f"Evidence validation checks missing/failed: {operation_id}")
    if item.get("id") in WAVE_A_REQUIREMENT_CASES:
        expected_cases = WAVE_A_REQUIREMENT_CASES[item["id"]]
        coverage_map = report.get("requirement_coverage")
        coverage = coverage_map.get(item["id"], {}) if isinstance(coverage_map, dict) else {}
        actual_cases = coverage.get("case_ids") if isinstance(coverage, dict) else None
        if (item.get("operation_ids") != [WAVE_A_TRANSFORM] or
                _string_members(actual_cases) != expected_cases or
                len(actual_cases) != len(expected_cases)):
            reasons.append(f"Evidence case coverage is incomplete: {item['id']}")
        if _string_members(report.get("requirements")) != set(WAVE_A_REQUIREMENT_CASES):
            reasons.append("Evidence Wave A requirement set is partial")
        if _string_members(report.get("standalone_unmet_gates")) != WAVE_A_UNMET_STANDALONE_GATES:
            reasons.append("Evidence omits unmet standalone acceptance gates")
        policy_coverage = report.get("policy_coverage")
        if not isinstance(policy_coverage, dict) or set(policy_coverage) != set(WAVE_A_POLICY_CASES):
            reasons.append("Evidence non-blocked policy coverage is incomplete")
        else:
            for policy_id, expected_policy_cases in WAVE_A_POLICY_CASES.items():
                value = policy_coverage.get(policy_id)
                case_ids = value.get("case_ids") if isinstance(value, dict) else None
                if (_string_members(case_ids) != expected_policy_cases or
                        len(case_ids) != len(expected_policy_cases)):
                    reasons.append(f"Evidence policy case coverage is incomplete: {policy_id}")
        indexed = {result.get("case_id"): result for result in results if isinstance(result, dict)}
        if len(indexed) != len([result for result in results if isinstance(result, dict)]):
            reasons.append("Evidence contains duplicate execution case ids")
        all_positive_cases = set().union(*WAVE_A_REQUIREMENT_CASES.values())
        if set(indexed) != all_positive_cases or len(indexed) != 22:
            reasons.append("Evidence positive Wave A case set differs from the 22-case contract")
        for case_id in sorted(all_positive_cases):
            result = indexed.get(case_id)
            if not isinstance(result, dict) or result.get("operation_id") != WAVE_A_TRANSFORM:
                reasons.append(f"Evidence has no covered execution case: {case_id}")
                continue
            validators = result.get("validators")
            if (not isinstance(validators, list) or
                    [validator.get("operation_id") for validator in validators if isinstance(validator, dict)] != list(WAVE_A_VALIDATORS) or
                    len(validators) != len(WAVE_A_VALIDATORS)):
                reasons.append(f"Evidence mandatory validator chain is incomplete: {case_id}")
                continue
            transform_outputs = result.get("output_hashes", [])
            if not isinstance(transform_outputs, list):
                transform_outputs = []
            for validator in validators:
                validator_id = validator.get("operation_id")
                operation = operations.get(validator_id, {})
                handler = declared.get(validator_id, {})
                if (validator.get("status") != "pass" or
                        validator.get("revision") != operation.get("revision") or
                        handler.get("revision") != operation.get("revision")):
                    reasons.append(f"Evidence validator revision/result mismatch: {case_id}/{validator_id}")
                for field in ("input_hashes", "output_hashes"):
                    values = validator.get(field)
                    if (not isinstance(values, list) or not values or
                            not all(_valid_digest(value) and value in blob_hashes for value in values)):
                        reasons.append(f"Evidence validator artifact hash missing: {case_id}/{validator_id}")
                validator_inputs = validator.get("input_hashes")
                if (not isinstance(validator_inputs, list) or
                        not set(transform_outputs).intersection(validator_inputs)):
                    reasons.append(f"Evidence validator did not consume transform output: {case_id}/{validator_id}")
                if validator.get("report_sha256") not in report_hashes:
                    reasons.append(f"Evidence validator report missing: {case_id}/{validator_id}")
                report_blob_sha256 = validator.get("report_blob_sha256")
                if report_blob_sha256 not in blob_hashes:
                    reasons.append(f"Evidence validator report blob missing: {case_id}/{validator_id}")
                else:
                    try:
                        report_blob = json.loads(base64.b64decode(
                            report["blobs"][report_blob_sha256]["content"], validate=True).decode("utf-8"))
                    except (KeyError, UnicodeError, ValueError, TypeError):
                        report_blob = None
                    if report_blob != report.get("reports", {}).get(validator.get("report_sha256")):
                        reasons.append(f"Evidence validator stdout/file report mismatch: {case_id}/{validator_id}")
                if (not _valid_digest(validator.get("request_sha256")) or
                        not _valid_digest(validator.get("response_sha256"))):
                    reasons.append(f"Evidence validator exchange hash missing: {case_id}/{validator_id}")
        reasons.extend(_bounded_normal_negative_control_reasons(
            report, indexed, operations, declared, tests, blob_hashes, manifest_digest,
        ))
    else:
        reasons.extend(_generic_family_reasons(
            report, item, operations, declared, tests, blob_hashes, report_hashes, root,
        ))
    return reasons


def _rerun_replayed_evidence(replay_worker: Path | None, root: Path) -> dict[str, dict]:
    """Re-execute the fixed harness and index its exact regenerated report.

    Offline JSON evaluation supplies no worker and remains incomplete. The trusted
    CLI supplies a native worker path; callers cannot substitute report data or a
    command. Arbitrary mutation by already-trusted Python code is outside this data
    evidence boundary.
    """
    verified: dict[str, dict] = {}
    if replay_worker is None or root.resolve() != REPO.resolve():
        return verified
    # Lazy import avoids a module cycle: the replay module imports this evaluator.
    from scripts.replay_master_capabilities import REPLAY_FAMILIES
    from scripts.replay_master_capabilities import replay as rerun_approved_harness
    for family in REPLAY_FAMILIES:
        try:
            fresh_report = rerun_approved_harness(Path(replay_worker), family)
            content = (json.dumps(
                fresh_report, ensure_ascii=False, indent=2, allow_nan=False,
            ) + "\n").encode("utf-8")
        except Exception:
            continue
        verified[hashlib.sha256(content).hexdigest()] = fresh_report
    return verified


def evaluate_requirements(requirements: dict, operations: dict[str, dict], root: Path = REPO,
                          *, replay_worker: Path | None = None) -> dict:
    """A requirement needs all declared adapters and nonempty valid evidence files."""
    fresh = extract_requirements(root)
    expected = {r["id"]: r["description"] for f in fresh["families"] for r in f["requirements"]}
    actual = [r for f in requirements.get("families", []) for r in f.get("requirements", [])]
    if len(actual) != len(expected) or {r.get("id"): r.get("description") for r in actual} != expected:
        raise ValueError("Acceptance denominator differs from the original major requirements")
    rerun_reports = _rerun_replayed_evidence(replay_worker, root)
    rows = []
    for item in actual:
        reasons = []
        if item.get("required") is not True:
            reasons.append("Required capability was disabled")
        ids = item.get("operation_ids", [])
        if not ids:
            reasons.append("No complete operation binding")
        for operation_id in ids:
            operation = operations.get(operation_id)
            if operation is None or operation.get("status") != "VALIDATED":
                reasons.append(f"Operation not validated: {operation_id}")
        evidence = item.get("evidence", [])
        if not evidence:
            reasons.append("No acceptance evidence")
        for record in evidence:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                reasons.append("Invalid evidence record")
                continue
            path = (root / record["path"]).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                reasons.append("Missing or unmanaged evidence")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if record.get("sha256") != digest:
                reasons.append("Evidence hash mismatch")
                continue
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                reasons.append("Evidence is not a machine-readable report")
                continue
            if not isinstance(report, dict):
                reasons.append("Evidence report must be an object")
                continue
            reasons.extend(_evidence_reasons(report, item, operations, root,
                           rerun_reports.get(digest)))
        rows.append({"id": item["id"], "description": item["description"],
                     "status": "VALIDATED" if not reasons else "INCOMPLETE", "reasons": reasons})
    validated = sum(row["status"] == "VALIDATED" for row in rows)
    return {"required": len(rows), "validated": validated,
            "percent": 100 * validated / len(rows) if rows else 0,
            "complete": bool(rows) and validated == len(rows), "requirements": rows}


SEARCH_GATE = "search_and_retrieval_acceptance"
SEARCH_EVIDENCE = "docs/master/evidence/search-retrieval.json"
SEARCH_TARGET_PERCENT = 95.0


def evaluate_search_gate(root: Path = REPO, *, live: bool = True,
                         evidence: dict | None = None) -> dict:
    """Verify the retrieval evidence and decide the search gate honestly.

    The gate is met only when (1) the evidence bindings match the current
    corpus, requirement bindings, registry, vocabulary and generator; (2) every
    recorded case matches the catalog binding and, when ``live``, a fresh run of
    the production search; (3) top-3 recall over all 300 intents is at least 95%
    and (4) the full search acceptance (typed recall, documentation discovery,
    126 package smoke, 4 planner gates, goal routing) passes.
    """
    reasons: list[str] = []
    result: dict = {"gate": SEARCH_GATE, "status": "unmet", "evidence": SEARCH_EVIDENCE,
                    "target_percent": SEARCH_TARGET_PERCENT, "reasons": reasons}
    path = root / SEARCH_EVIDENCE
    if evidence is None:
        if not path.is_file():
            reasons.append("Search retrieval evidence is missing")
            return result
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            reasons.append("Search retrieval evidence is not machine readable")
            return result
    if not isinstance(evidence, dict) or evidence.get("generator") != "master-search-retrieval-evidence":
        reasons.append("Search retrieval evidence has the wrong generator")
        return result
    from scripts import evaluate_master_search as search_eval
    bindings = evidence.get("bindings")
    expected_bindings = {key: hashlib.sha256((root / rel).read_bytes()).hexdigest()
                         for key, rel in search_eval.RETRIEVAL_BINDING_SOURCES.items()}
    if bindings != expected_bindings:
        reasons.append("Search retrieval evidence bindings differ from the current corpus, "
                       "requirement bindings, registry, vocabulary or generator")
    try:
        corpus = json.loads((root / search_eval.RETRIEVAL_BINDING_SOURCES["corpus_sha256"]
                             ).read_text(encoding="utf-8"))
        requirements = json.loads((root / "catalog/major_requirements.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        reasons.append("Search corpus or requirement bindings are unreadable")
        return result
    bound = {item["id"]: sorted(item["operation_ids"])
             for family in requirements["families"] for item in family["requirements"]}
    intents = corpus.get("intents", [])
    cases = evidence.get("cases")
    if not isinstance(cases, list) or len(cases) != len(intents) or len(intents) != 300:
        reasons.append("Search retrieval evidence does not cover all 300 intents")
        return result
    fresh = None
    if live and root.resolve() == REPO.resolve():
        import tempfile
        from cgal_mcp.master.runtime import MasterRuntime
        with tempfile.TemporaryDirectory(prefix="master-search-gate-") as name:
            runtime = MasterRuntime(Path(name) / "store", require_memory_limit=False)
            try:
                fresh = search_eval.measure_catalog_bound_retrieval(
                    intents, requirements, runtime=runtime)
            finally:
                runtime.close()
    recomputed = []
    for index, (intent, case) in enumerate(zip(intents, cases)):
        requirement = intent["requirement_ids"][0]
        if (not isinstance(case, dict) or case.get("id") != intent["id"] or
                case.get("requirement") != requirement or
                case.get("expected") != bound.get(requirement) or
                case.get("split") != search_eval.retrieval_split(requirement)):
            reasons.append(f"Search retrieval case does not match the catalog binding: {intent['id']}")
            continue
        returned = case.get("returned")
        if not isinstance(returned, list) or len(returned) > 3 or not all(
                isinstance(x, str) for x in returned):
            reasons.append(f"Search retrieval case has invalid results: {intent['id']}")
            continue
        top1 = bool(returned and returned[0] in case["expected"])
        top3 = bool(set(case["expected"]) & set(returned))
        if case.get("top1") is not top1 or case.get("top3") is not top3:
            reasons.append(f"Search retrieval case hit flags are inconsistent: {intent['id']}")
        if fresh is not None and fresh[index] != case:
            reasons.append(f"Search retrieval case differs from a fresh run: {intent['id']}")
        recomputed.append({**case, "top1": top1, "top3": top3})
    summary = {
        "overall": search_eval._retrieval_summary(recomputed),
        "development": search_eval._retrieval_summary([c for c in recomputed if c["split"] == "development"]),
        "held_out": search_eval._retrieval_summary([c for c in recomputed if c["split"] == "held_out"]),
    }
    if evidence.get("summary") != summary:
        reasons.append("Search retrieval summary differs from its recorded cases")
    result["measured"] = summary
    result["live_rerun"] = fresh is not None
    result["retrieval_target_met"] = summary["overall"]["top3_percent"] >= SEARCH_TARGET_PERCENT
    if not result["retrieval_target_met"]:
        reasons.append(
            f"Top-3 retrieval {summary['overall']['top3_percent']}% is below {SEARCH_TARGET_PERCENT}% "
            f"(top-1 {summary['overall']['top1_percent']}%)")
    full = evidence.get("full_search_acceptance")
    if not isinstance(full, dict) or full.get("passes_search_acceptance") is not True:
        reasons.append("Full search acceptance (typed recall, documentation discovery, package smoke, "
                       "planner gates, goal routing) is not passing")
        if isinstance(full, dict):
            goal = full.get("goal_routing", {}).get("documentation_only", {})
            result["goal_routing_unmeasured_input_model"] = goal.get("unmeasured_input_model")
    if full is not None and full.get("execute_calls") != 0:
        reasons.append("Search evidence must not claim execution measurements")
    sample = full.get("execute_after_search_sample") if isinstance(full, dict) else None
    if not isinstance(sample, dict):
        reasons.append("Automatic execution after search is unmeasured")
    else:
        result["execute_after_search_sample"] = {k: sample.get(k) for k in ("sample_size", "succeeded")}
        reasons.append(
            f"Automatic execution is measured on a {sample.get('sample_size')}-intent sample only "
            f"({sample.get('succeeded')} succeeded); the other intents are not executed")
    blind_path = root / "docs/master/evidence/search-blind.json"
    blind_set = root / "docs/master/search_blind_set.json"
    try:
        blind = json.loads(blind_path.read_text(encoding="utf-8"))
        if blind.get("blind_set_sha256") != hashlib.sha256(blind_set.read_bytes()).hexdigest():
            reasons.append("Blind-set evidence does not match the current blind set")
        else:
            op = blind["operation_level"]
            result["blind_set"] = {"count": blind["count"], "top1_percent": op["top1_pct"],
                                   "top3_percent": op["top3_pct"]}
            if op["top3_pct"] < SEARCH_TARGET_PERCENT:
                reasons.append(f"Blind-set top-3 {op['top3_pct']}% is below {SEARCH_TARGET_PERCENT}% "
                               f"(top-1 {op['top1_pct']}%, {blind['count']} intents)")
    except (OSError, ValueError, KeyError, UnicodeError):
        reasons.append("Blind-set generalization evidence is missing")
    blind2_path = root / "docs/master/evidence/search-blind-2.json"
    blind2_set = root / "docs/master/search_blind_set_2.json"
    try:
        blind2 = json.loads(blind2_path.read_text(encoding="utf-8"))
        if blind2.get("blind_set_sha256") != hashlib.sha256(blind2_set.read_bytes()).hexdigest():
            reasons.append("Second blind-set evidence does not match the current second blind set")
        else:
            op2 = blind2["operation_level"]
            result["blind_set_2"] = {"count": blind2["count"], "top1_percent": op2["top1_pct"],
                                     "top3_percent": op2["top3_pct"]}
            if op2["top3_pct"] < SEARCH_TARGET_PERCENT:
                reasons.append(f"Second blind-set top-3 {op2['top3_pct']}% is below {SEARCH_TARGET_PERCENT}% "
                               f"(top-1 {op2['top1_pct']}%, {blind2['count']} intents)")
    except (OSError, ValueError, KeyError, UnicodeError):
        reasons.append("Second blind-set generalization evidence is missing")
    if not reasons:
        result["status"] = "met"
        if SEARCH_GATE in WAVE_A_UNMET_STANDALONE_GATES:
            result["status"] = "met_pending_gate_list_update"
            reasons.append("Evidence supports the gate but the unmet standalone gate list still names it")
    return result


WORKFLOW_GATE = "multi_operation_workflow_acceptance"
WORKFLOW_EVIDENCE = "docs/master/evidence/workflows.json"
WORKFLOW_SPEC = "docs/master/workflows.json"
WORKFLOW_MIN_POSITIVE = 30
WORKFLOW_MAX_OPERATION_SHARE = 0.35
WORKFLOW_MIN_DISTINCT_OPERATIONS = 12
# Phase 6 work items the planner does not implement; each is listed as an unmet reason until
# the planner/runtime gains the feature and this table is updated together with evidence for it.
WORKFLOW_UNIMPLEMENTED_PLANNER_FEATURES = {
    "fallback_chain": "The planner and runtime have no fallback chain: a failed step never "
                      "retries an alternative registered operation",
    "cost_risk_estimate": "Plans carry no cost/risk estimate (only default wall-time budgets)",
    "automatic_preprocess_postprocess": "Preprocess/postprocess steps (repair, triangulate, "
                                        "conversion) are never inserted automatically; "
                                        "every DAG is declared explicitly",
}


def evaluate_workflow_gate(root: Path = REPO, *, live: bool = True,
                           evidence: dict | None = None, spec: dict | None = None,
                           worker: Path | None = None) -> dict:
    """Verify multi-operation workflow evidence and decide the workflow gate honestly.

    Every verdict is re-derived from the recorded cases and the current registry: the
    declared DAGs and fixtures must equal the checked-in spec, every recorded outcome must
    equal the spec expectation, each succeeded workflow must run all registry-mandated
    validators to a pass, artifact/unit propagation must be consistent, failed workflows
    must publish nothing, and (when ``live``) a fresh run through the real runtime and
    worker must reproduce the recorded cases exactly.
    """
    reasons: list[str] = []
    result: dict = {"gate": WORKFLOW_GATE, "status": "unmet", "evidence": WORKFLOW_EVIDENCE,
                    "reasons": reasons}
    path = root / WORKFLOW_EVIDENCE
    try:
        if evidence is None:
            evidence = json.loads(path.read_text(encoding="utf-8"))
        if spec is None:
            spec = json.loads((root / WORKFLOW_SPEC).read_text(encoding="utf-8"))
        operation_data = json.loads((root / "cgal_mcp/master/operations.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        reasons.append("Workflow evidence, spec or registry is missing or unreadable")
        return result
    if isinstance(operation_data, dict):
        operation_data = operation_data.get("operations", [])
    registry = {item["id"]: item for item in operation_data}
    if not isinstance(evidence, dict) or evidence.get("generator") != "master-workflow-evidence":
        reasons.append("Workflow evidence has the wrong generator")
        return result
    from scripts import run_master_workflows as runner
    if evidence.get("bindings") != runner.bindings(root):
        reasons.append("Workflow evidence bindings differ from the current spec, registry, "
                       "policies, planner, runtime or runner")
    for name, fixture in spec.get("fixtures", {}).items():
        try:
            actual = hashlib.sha256((root / fixture["path"]).read_bytes()).hexdigest()
        except OSError:
            actual = None
        if actual != fixture["sha256"]:
            reasons.append(f"Workflow fixture {name} does not match its declared hash")
    cases = evidence.get("cases")
    workflows = spec.get("workflows", [])
    if (not isinstance(cases, list) or evidence.get("count") != len(cases)
            or [c.get("id") for c in cases] != [w["id"] for w in workflows]):
        reasons.append("Workflow evidence does not cover exactly the declared workflows")
        return result
    fresh = None
    if live and root.resolve() == REPO.resolve():
        worker = worker or root / "build-master/Release/cgal-master-worker.exe"
        if worker.is_file():
            fresh = runner.measure(root, worker)["cases"]
        else:
            reasons.append("Native worker is unavailable for the live workflow rerun")
    positives = negatives = 0
    operation_counts: dict[str, int] = {}
    primary_operations: set[str] = set()
    families: set[str] = set()
    joins = fanouts = unit_cases = omissions = 0
    negative_kinds: dict[str, int] = {}
    for index, (workflow, case) in enumerate(zip(workflows, cases)):
        label = workflow["id"]
        declared = [{"id": step["id"], "operation": step["operation"],
                     "inputs": dict(sorted(step["inputs"].items()))} for step in workflow["steps"]]
        if (case.get("declared_dag") != declared or case.get("expect") != workflow["expect"]
                or case.get("category") != workflow["category"]
                or case.get("families") != workflow["families"]
                or case.get("fixtures") != {name: {key: spec["fixtures"][name][key]
                                                   for key in ("sha256", "type", "unit")}
                                            for name in workflow.get("fixtures", [])}):
            reasons.append(f"Workflow record differs from its declaration: {label}")
            continue
        if fresh is not None and fresh[index] != case:
            reasons.append(f"Workflow record differs from a fresh run through the runtime: {label}")
        outcome = case.get("outcome", {})
        expect = workflow["expect"]
        if any(outcome.get(key) != value for key, value in expect.items()):
            reasons.append(f"Workflow outcome differs from its expectation: {label}")
            continue
        validators = case.get("validators", [])
        plan_steps = case.get("plan", {}).get("steps", [])
        if plan_steps:
            steps_by_id = {step["id"]: step for step in plan_steps}
            for step in plan_steps:
                if step["role"] == "validator":
                    continue
                required = registry[step["operation"]]["validation"]["validators"]
                planned = [v["operation"] for v in plan_steps
                           if v["role"] == "validator" and v["validates"] == step["id"]]
                if sorted(planned) != sorted(required):
                    omissions += 1
                    reasons.append(f"Planned validators differ from the registry for {label}:{step['id']}")
            for step in plan_steps:
                for slot, binding in step["inputs"].items():
                    if "step" in binding:
                        producer = steps_by_id.get(binding["step"])
                        if producer is None or step["input_types"][slot] not in producer["output_types"]:
                            reasons.append(f"Workflow DAG edge is not type-consistent: {label}:{step['id']}.{slot}")
        if workflow["category"] == "positive":
            positives += 1
            if outcome.get("state") != "succeeded":
                reasons.append(f"Positive workflow did not succeed: {label}")
                continue
            transforms = [s for s in plan_steps if s["role"] != "validator"]
            operations = [s["operation"] for s in transforms]
            if len(set(operations)) < 2:
                reasons.append(f"Positive workflow is a single operation: {label}")
            for operation in set(operations):
                operation_counts[operation] = operation_counts.get(operation, 0) + 1
            primary_operations.update(operations)
            families.update(workflow["families"])
            consumers: dict[str, int] = {}
            for step in transforms:
                stepped = [b["step"] for b in step["inputs"].values() if "step" in b]
                if len(stepped) >= 2:
                    joins += 1
                for source in set(stepped):
                    consumers[source] = consumers.get(source, 0) + 1
            fanouts += sum(1 for count in consumers.values() if count >= 2)
            executed = {v["step_id"]: v for v in validators}
            for step in plan_steps:
                if step["role"] == "validator" and (
                        step["id"] not in executed or executed[step["id"]]["status"] != "pass"):
                    omissions += 1
                    reasons.append(f"Validator did not run to a pass: {label}:{step['id']}")
            fixture_units = {spec["fixtures"][name]["unit"] for name in workflow.get("fixtures", [])}
            unit_set = {b for s in plan_steps for b in s["input_units"].values() if b != "none"}
            output_units = {o["unit"] for o in case.get("outputs", []) if o["unit"] != "none"}
            if len(fixture_units) != 1 or unit_set != fixture_units or not output_units <= fixture_units:
                reasons.append(f"Unit propagation is inconsistent: {label}")
            elif fixture_units != {"mm"}:
                unit_cases += 1
            expected_outputs = sum(len(registry[s["operation"]]["io"]["outputs"]) for s in transforms)
            if len(case.get("outputs", [])) != expected_outputs or case["store_published_delta"] != expected_outputs:
                reasons.append(f"Published outputs differ from the plan: {label}")
        else:
            negatives += 1
            if outcome.get("state") == "succeeded" or case.get("store_published_delta") != 0:
                reasons.append(f"Negative workflow silently passed or published artifacts: {label}")
            for tag in workflow["families"]:
                if tag in {"bad_input", "validator", "resource_limit", "typing", "units", "dag", "registry"}:
                    negative_kinds[tag] = negative_kinds.get(tag, 0) + 1
    result["measured"] = {
        "positive_workflows": positives, "negative_workflows": negatives,
        "positive_succeeded": sum(1 for w, c in zip(workflows, cases)
                                  if w["category"] == "positive" and c["outcome"].get("state") == "succeeded"),
        "distinct_primary_operations": len(primary_operations), "families": sorted(families),
        "join_steps": joins, "fanout_steps": fanouts, "non_mm_unit_workflows": unit_cases,
        "validator_omissions": omissions, "negative_kinds": negative_kinds,
        "validator_rejections": sum(1 for c in cases if c["outcome"].get("state") == "rejected"),
        "live_rerun": fresh is not None,
    }
    share = (max(operation_counts.values()) / positives) if positives and operation_counts else 1.0
    result["measured"]["max_operation_share"] = round(share, 4)
    if positives < WORKFLOW_MIN_POSITIVE:
        reasons.append(f"Only {positives} positive workflows (need {WORKFLOW_MIN_POSITIVE}+)")
    if share > WORKFLOW_MAX_OPERATION_SHARE:
        reasons.append(f"Single-operation bias: one operation appears in {share:.0%} of workflows")
    if len(primary_operations) < WORKFLOW_MIN_DISTINCT_OPERATIONS:
        reasons.append(f"Only {len(primary_operations)} distinct primary operations are exercised")
    if joins < 1 or fanouts < 1:
        reasons.append("DAG branching (fan-out) and join are not both evidenced")
    if unit_cases < 1:
        reasons.append("Non-millimetre unit propagation is not evidenced")
    for kind in ("bad_input", "validator", "resource_limit"):
        if not negative_kinds.get(kind):
            reasons.append(f"No negative workflow covers {kind}")
    if not result["measured"]["validator_rejections"]:
        reasons.append("No workflow demonstrates a validator rejection failing the workflow")
    if omissions:
        reasons.append(f"Validator omission count is {omissions} (must be 0)")
    result["planner_features"] = {name: False for name in WORKFLOW_UNIMPLEMENTED_PLANNER_FEATURES}
    reasons.extend(WORKFLOW_UNIMPLEMENTED_PLANNER_FEATURES.values())
    if not reasons:
        result["status"] = "met"
        if WORKFLOW_GATE in WAVE_A_UNMET_STANDALONE_GATES:
            result["status"] = "met_pending_gate_list_update"
            reasons.append("Evidence supports the gate but the unmet standalone gate list still names it")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-requirements", action="store_true")
    parser.add_argument("--originals-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    originals = verify_originals()
    target = REPO / "catalog/major_requirements.json"
    if args.refresh_requirements:
        if target.exists():
            raise SystemExit("Refusing to overwrite existing operation/evidence bindings")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(extract_requirements(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"original_documents": originals, "standalone_accepted": False}
    if not args.originals_only:
        requirements = json.loads(target.read_text(encoding="utf-8"))
        operation_path = REPO / "cgal_mcp/master/operations.json"
        operation_data = json.loads(operation_path.read_text(encoding="utf-8")) if operation_path.exists() else []
        if isinstance(operation_data, dict):
            operation_data = operation_data.get("operations", [])
        operations = {o.get("id", o.get("operation", {}).get("id")): o for o in operation_data}
        report["major_capabilities"] = evaluate_requirements(requirements, operations)
        report["standalone_gates"] = {SEARCH_GATE: evaluate_search_gate(REPO),
                                      WORKFLOW_GATE: evaluate_workflow_gate(REPO)}
        report["standalone_acceptance_reason"] = "Additional package, routing, workflow, host and robustness gates required"
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content)


if __name__ == "__main__":
    main()
