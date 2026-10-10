"""Evidence-gated Master acceptance; discovery never counts as implementation."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

from scripts import master_replay_families as replay_families
from scripts import package_provenance

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
    # Blind set 3: authored by an independent agent before measurement, measured once (never tuned on).
    blind3_path = root / "docs/master/evidence/search-blind-3.json"
    blind3_set = root / "docs/master/search_blind_set_3.json"
    try:
        blind3 = json.loads(blind3_path.read_text(encoding="utf-8"))
        if blind3.get("blind_set_sha256") != hashlib.sha256(blind3_set.read_bytes()).hexdigest():
            reasons.append("Third blind-set evidence does not match the current third blind set")
        else:
            op3 = blind3["operation_level"]
            probes = blind3.get("out_of_scope_probes", [])
            abstained = sum(not p["returned"] for p in probes)
            false_abstain = sum(not c["returned"] for c in blind3["cases"])
            result["blind_set_3"] = {
                "count": blind3["count"], "top1_percent": op3["top1_pct"], "top3_percent": op3["top3_pct"],
                "by_language_top3_percent": {k: v["op_top3_pct"] for k, v in blind3["by_language"].items()},
                "out_of_scope_abstained": f"{abstained}/{len(probes)}",
                "in_scope_false_abstain": f"{false_abstain}/{blind3['count']}"}
            if op3["top3_pct"] < SEARCH_TARGET_PERCENT:
                reasons.append(f"Third blind-set top-3 {op3['top3_pct']}% is below {SEARCH_TARGET_PERCENT}% "
                               f"(top-1 {op3['top1_pct']}%, {blind3['count']} intents)")
    except (OSError, ValueError, KeyError, UnicodeError):
        reasons.append("Third blind-set generalization evidence is missing")
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
# Phase 6 planner work items. Each feature is listed as an unmet reason unless the recorded
# workflow evidence demonstrates it (re-derived below from the recorded plans and outcomes).
WORKFLOW_PLANNER_FEATURES = {
    "fallback_chain": "Fallback chains are not evidenced for plan-time blocks, runtime failures "
                      "and validator rejections together with exhausted and all-blocked chains",
    "cost_risk_estimate": "Per-plan cost/risk estimates are missing or differ from the registry",
    "automatic_preprocess_postprocess": "Automatic preprocess and postprocess step insertion is "
                                        "not evidenced with recorded, validated inserted steps",
}
WORKFLOW_RULE_OPERATIONS = {"soup_to_triangle_mesh": ("preprocess", "mesh.repair.orient"),
                            "terminal_mesh_inspection": ("postprocess", "mesh.inspect.pmp")}


def _workflow_estimate_problems(plan: dict, registry: dict) -> list[str]:
    """Recompute a plan's cost/risk estimate from registry metadata only."""
    estimate, steps = plan.get("estimate"), plan.get("steps", [])
    if not isinstance(estimate, dict) or len(estimate.get("steps", [])) != len(steps):
        return ["estimate missing or not covering every step"]
    problems, entries = [], estimate["steps"]
    for entry, step in zip(entries, steps):
        operation = registry[step["operation"]]
        bound = next(({k: c[k] for k in ("maximum_faces", "maximum_vertices", "maximum_bytes") if k in c}
                      for c in operation.get("preconditions", []) if c.get("id") == "bounded_input"), {})
        faces = bound.get("maximum_faces")
        tier = ("unbounded" if faces is None else "small" if faces <= 1000
                else "medium" if faces <= 50000 else "large")
        mutating = (step["role"] != "validator"
                    and operation.get("output_contract", {}).get("geometry_mutation") is True)
        units = 1 + sum(1 for c in operation.get("preconditions", []) if "worker_check" in c)
        expected = {"step_id": step["id"], "operation": step["operation"], "role": step["role"],
                    "input_bound": bound, "cost_tier": tier, "cost_units": units,
                    "risk": "mutating_validated" if mutating else "read_only"}
        if entry != expected:
            problems.append(f"estimate entry differs from the registry: {step['id']}")
    expected_totals = {
        "basis": "registry metadata only", "total_cost_units": sum(e["cost_units"] for e in entries),
        "step_count": len(entries),
        "validator_steps": sum(1 for e in entries if e["role"] == "validator"),
        "mutating_steps": sum(1 for e in entries if e["risk"] == "mutating_validated"),
        "highest_risk": ("mutating_validated" if any(e["risk"] == "mutating_validated" for e in entries)
                         else "read_only"),
        "inserted_steps": [step["id"] for step in steps if "inserted_by" in step]}
    if {k: estimate.get(k) for k in expected_totals} != expected_totals:
        problems.append("estimate totals differ from the plan")
    return problems


def _workflow_inserted_problems(plan: dict, rules: dict) -> list[str]:
    problems, steps = [], {step["id"]: step for step in plan.get("steps", [])}
    for step in plan.get("steps", []):
        meta = step.get("inserted_by")
        if meta is None:
            continue
        rule = WORKFLOW_RULE_OPERATIONS.get(meta.get("rule"))
        target = steps.get(meta.get("for_step"))
        if (rule is None or rule[0] != meta.get("phase") or not rules.get(rule[0])
                or step["operation"] != rule[1] or target is None or not meta.get("reason")):
            problems.append(f"inserted step is not a recorded rule application: {step['id']}")
        elif rule[0] == "preprocess":
            if target["inputs"].get(meta["for_slot"], {}).get("step") != step["id"]:
                problems.append(f"preprocess step is not wired into its consumer: {step['id']}")
        elif not any(b.get("step") == target["id"] for b in step["inputs"].values()):
            problems.append(f"postprocess step does not consume its producer: {step['id']}")
    return problems


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
    joins = fanouts = unit_cases = omissions = estimate_problems = 0
    inserted_phases: set[str] = set()
    succeeded_inserted: set[str] = set()
    fallback_kinds: set[str] = set()
    negative_kinds: dict[str, int] = {}
    for index, (workflow, case) in enumerate(zip(workflows, cases)):
        label = workflow["id"]
        declared = [{"id": step["id"], "operation": step["operation"],
                     "inputs": dict(sorted(step["inputs"].items()))} for step in workflow["steps"]]
        alternatives_dag = [[{"id": step["id"], "operation": step["operation"],
                              "inputs": dict(sorted(step["inputs"].items()))}
                             for step in alternative["steps"]]
                            for alternative in workflow.get("alternatives", [])]
        if (case.get("alternatives_dag", []) != alternatives_dag
                or case.get("rules", {}) != workflow.get("rules", {})
                or case.get("declared_dag") != declared or case.get("expect") != workflow["expect"]
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
        plan_records = ([case["plan"]] + case.get("fallback_plans", [])) if "plan" in case else []
        chain = outcome.get("fallback_chain", [])
        served_index = outcome.get("served_by_index") if chain else 0
        served = (plan_records[served_index]
                  if plan_records and served_index is not None and served_index < len(plan_records)
                  else {})
        plan_steps = served.get("steps", [])
        for record in plan_records:
            for problem in _workflow_estimate_problems(record, registry):
                estimate_problems += 1
                reasons.append(f"Plan estimate problem for {label}: {problem}")
            for problem in _workflow_inserted_problems(record, workflow.get("rules", {})):
                reasons.append(f"Plan rule problem for {label}: {problem}")
            for step in record["steps"]:
                if "inserted_by" in step:
                    inserted_phases.add(step["inserted_by"].get("phase"))
                    if outcome.get("state") == "succeeded" and record is served:
                        succeeded_inserted.add(step["inserted_by"].get("phase"))
            steps_by_id = {step["id"]: step for step in record["steps"]}
            for step in record["steps"]:
                if step["role"] == "validator":
                    continue
                required = registry[step["operation"]]["validation"]["validators"]
                planned = [v["operation"] for v in record["steps"]
                           if v["role"] == "validator" and v["validates"] == step["id"]]
                if sorted(planned) != sorted(required):
                    omissions += 1
                    reasons.append(f"Planned validators differ from the registry for {label}:{step['id']}")
            for step in record["steps"]:
                for slot, binding in step["inputs"].items():
                    if "step" in binding:
                        producer = steps_by_id.get(binding["step"])
                        if producer is None or step["input_types"][slot] not in producer["output_types"]:
                            reasons.append(f"Workflow DAG edge is not type-consistent: {label}:{step['id']}.{slot}")
        if "alternatives" in workflow:
            attempts = case.get("plan_attempts", [])
            planned_count = sum(1 for a in attempts if a["status"] == "planned")
            blocked = [a for a in attempts if a["status"] == "blocked"]
            if ("plan" in case and (len(attempts) != 1 + len(workflow["alternatives"])
                                    or planned_count != len(plan_records))
                    or any(not a.get("class") or not a.get("code") for a in blocked)):
                reasons.append(f"Fallback plan attempts are not fully recorded: {label}")
            if chain:
                states = [e["state"] for e in chain]
                if (len(chain) > planned_count or [e["index"] for e in chain] != list(range(len(chain)))
                        or any(e["state"] not in {"failed", "rejected"} or not e["error_code"]
                               for e in chain[:-1])
                        or states[-1] != outcome.get("state")
                        or served_index != (len(chain) - 1 if states[-1] == "succeeded" else None)):
                    reasons.append(f"Fallback chain is inconsistent or silent: {label}")
                elif states[-1] == "succeeded":
                    fallback_kinds.add({"failed": "runtime_failure",
                                        "rejected": "validator_rejection"}[states[0]])
                elif workflow["category"] == "negative" and len(chain) > 1:
                    fallback_kinds.add("exhausted")
            elif outcome.get("state") == "succeeded" and blocked:
                fallback_kinds.add("plan_block")
            elif outcome.get("state") == "refused" and not planned_count:
                fallback_kinds.add("all_blocked")
        elif chain or case.get("plan_attempts") or case.get("fallback_plans"):
            reasons.append(f"Fallback records appear without declared alternatives: {label}")
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
            if "alternatives" in workflow:
                # A fallback chain declares fixtures for every candidate; judge the served plan only.
                used = {(binding["artifact_sha256"], step["input_units"][slot])
                        for step in plan_steps for slot, binding in step["inputs"].items()
                        if "artifact_sha256" in binding}
                fixture_units = {spec["fixtures"][name]["unit"] for name in workflow.get("fixtures", [])
                                 if (spec["fixtures"][name]["sha256"], spec["fixtures"][name]["unit"]) in used}
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
    estimates_ok = (bool(cases) and not estimate_problems
                    and all("estimate" in c["plan"] for c in cases if "plan" in c))
    features = {
        "fallback_chain": fallback_kinds >= {"plan_block", "runtime_failure", "validator_rejection",
                                             "exhausted", "all_blocked"},
        "cost_risk_estimate": estimates_ok,
        "automatic_preprocess_postprocess": succeeded_inserted >= {"preprocess", "postprocess"},
    }
    result["planner_features"] = features
    result["measured"]["fallback_kinds"] = sorted(fallback_kinds)
    result["measured"]["inserted_rule_phases"] = sorted(inserted_phases)
    result["measured"]["estimate_problems"] = estimate_problems
    for name, ok in features.items():
        if not ok:
            reasons.append(WORKFLOW_PLANNER_FEATURES[name])
    if not reasons:
        result["status"] = "met"
        if WORKFLOW_GATE in WAVE_A_UNMET_STANDALONE_GATES:
            result["status"] = "met_pending_gate_list_update"
            reasons.append("Evidence supports the gate but the unmet standalone gate list still names it")
    return result


PERFORMANCE_GATE = "performance_resource_and_robustness_acceptance"
PERFORMANCE_EVIDENCE = "docs/master/evidence/performance-robustness.json"
PERFORMANCE_MIN_TRIALS_PER_MODE = 20
PERFORMANCE_MIN_HOST_KILL_TRIALS = 5
PERFORMANCE_MIN_GARBAGE_CASES = 12
PERFORMANCE_REQUIRED_FAULT_KINDS = {
    "kill": {"exit_kill", "native_external_kill"},
    "abort": {"abort"},
    "segfault_like": {"access_violation"},
    "hang_past_timeout": {"hang", "hang_with_child", "hang_partial_output"},
    "malformed_output": {"garbage_stdout", "empty_stdout", "multi_line_stdout", "wrong_request_id",
                         "bad_schema", "output_path_escape", "truncate_output", "garbage_output"},
    "oversized_output": {"oversized_stdout", "stderr_flood_exit"},
    "garbage_input": {"garbage_input_files", "native_garbage_request", "native_truncated_request",
                      "native_empty_request", "native_wrong_protocol", "native_missing_input_file"},
    "host_death": {"host_process_killed"},
}
PERFORMANCE_LIVE_MODES = ["exit_kill", "access_violation", "oversized_stdout",
                          "native_garbage_request", "garbage_input_files"]
PERFORMANCE_REQUIRED_LIMIT_KINDS = {"bounded_input": 3, "import_limit": 1, "execution_limits": 9,
                                    "configuration": 8, "native_resource_cap": 2}


def row_axis_is_size_bound(rows: list[dict]) -> bool:
    """Workload scaled by an output-size parameter on an identical input (mesh size bound)."""
    return all(row.get("axis") == "size_bound_mm" for row in rows) and len(
        {tuple(i["sha256"] for i in row["inputs"]) for row in rows}) == 1


def evaluate_performance_gate(root: Path = REPO, *, live: bool = True,
                              evidence: dict | None = None, worker: Path | None = None) -> dict:
    """Decide the performance/resource/robustness gate from recorded real-worker evidence.

    Re-derived from the evidence and the current registry: all fifteen families measured at
    three increasing input scales within the registry bounds and the declared memory/wall
    ceilings, every resource-limit refusal exact, crash containment 100% over at least the
    declared trial floor for every fault kind, and the Phase 10 work items still named as
    reasons while the lifecycle evidence shows them absent. Timings are never gated on speed.
    """
    reasons: list[str] = []
    result: dict = {"gate": PERFORMANCE_GATE, "status": "unmet", "evidence": PERFORMANCE_EVIDENCE,
                    "reasons": reasons}
    try:
        if evidence is None:
            evidence = json.loads((root / PERFORMANCE_EVIDENCE).read_text(encoding="utf-8"))
        operation_data = json.loads((root / "cgal_mcp/master/operations.json").read_text(encoding="utf-8"))
        requirements = json.loads((root / "catalog/major_requirements.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        reasons.append("Performance evidence, registry or requirements are missing or unreadable")
        return result
    if isinstance(operation_data, dict):
        operation_data = operation_data.get("operations", [])
    registry = {item["id"]: item for item in operation_data}
    if not isinstance(evidence, dict) or evidence.get("generator") != "master-performance-robustness":
        reasons.append("Performance evidence has the wrong generator")
        return result
    from scripts import measure_master_robustness as rob
    if evidence.get("bindings") != rob.bindings(root):
        reasons.append("Performance evidence bindings differ from the current generator, fault proxy, "
                       "registry, runtime, supervisor, resources or store")
    worker_path = worker or root / rob.DEFAULT_WORKER
    if worker_path.is_file() and evidence.get("worker_sha256") != hashlib.sha256(worker_path.read_bytes()).hexdigest():
        reasons.append("Performance evidence was measured on a different native worker binary")
    deterministic = evidence.get("deterministic")
    if not isinstance(deterministic, dict) or evidence.get("deterministic_sha256") != _canonical_hash(deterministic):
        reasons.append("Deterministic evidence hash does not match its content")
        return result
    timings = evidence.get("timings", {})
    declared = evidence.get("declared", {})
    memory_ceiling = declared.get("memory_ceiling_mb")
    wall_limit = declared.get("wall_limit_ms")
    if declared.get("trials_per_fault_mode", 0) < PERFORMANCE_MIN_TRIALS_PER_MODE:
        reasons.append("Declared trial count per fault mode is below the evaluator floor")

    # (1) per-family scale baselines
    cases = deterministic.get("scale_cases", [])
    family_ops = {f["id"]: {op for r in f["requirements"] for op in r["operation_ids"]}
                  for f in requirements["families"]}
    by_family: dict[str, list[dict]] = {}
    for case in cases:
        by_family.setdefault(case.get("family"), []).append(case)
    measured_families = []
    for family in sorted(family_ops, key=lambda value: int(value.split(".")[1])):
        rows = by_family.get(family, [])
        if len(rows) < 3 or len(rows) % 3:
            reasons.append(f"Family {family} lacks small/medium/large performance baselines")
            continue
        for operation in sorted({row["operation"] for row in rows}):
            ops = [row for row in rows if row["operation"] == operation]
            if [row["scale"] for row in ops] != ["small", "medium", "large"]:
                reasons.append(f"Family {family} {operation} does not have exactly small/medium/large scales")
                continue
            definition = registry.get(operation)
            if (definition is None or definition.get("status") != "VALIDATED"
                    or operation not in family_ops[family]):
                reasons.append(f"Family {family} representative {operation} is not a VALIDATED "
                               "operation of the family")
                continue
            bounds = next((c for c in definition["preconditions"] if c.get("id") == "bounded_input"), {})
            validators = len(definition["validation"]["validators"])
            sizes = []
            for row in ops:
                label = f"{family} {operation} {row['scale']}"
                if (row["status"] != "pass" or row["job_state"] != "succeeded"
                        or row["validation_status"] != "passed"):
                    reasons.append(f"Scale case {label} did not succeed and validate: "
                                   f"{row['job_state']} {row['error'].get('code')} "
                                   f"(worker processes started: {row['worker_processes_started']})")
                if row["validators_passed"] != validators:
                    reasons.append(f"Scale case {label} ran {row['validators_passed']} of "
                                   f"{validators} mandatory validators")
                if not row["worker_processes_all_exited"]:
                    reasons.append(f"Scale case {label} left a worker process running")
                if row["memory_ceiling_mb"] != memory_ceiling or row["wall_limit_ms"] > wall_limit:
                    reasons.append(f"Scale case {label} used a different resource ceiling")
                for item in row["inputs"]:
                    meta = item["metadata"]
                    for key, maximum, actual in (
                            ("size", bounds.get("maximum_bytes"), item["size"]),
                            ("vertices", bounds.get("maximum_vertices"),
                             meta.get("vertices", meta.get("point_count"))),
                            ("faces", bounds.get("maximum_faces"), meta.get("faces"))):
                        if maximum is not None and actual is not None and actual > maximum:
                            reasons.append(f"Scale case {label} exceeds the declared {key} bound")
                sizes.append(sum(item["size"] for item in row["inputs"]))
                timing = timings.get("scale", {}).get(f"{family}:{operation}:{row['scale']}", {})
                peak = timing.get("peak_worker_rss_bytes")
                if not isinstance(peak, int) or peak <= 0:
                    reasons.append(f"Scale case {label} has no measured peak worker memory")
                elif peak > memory_ceiling * 1024 * 1024:
                    reasons.append(f"Scale case {label} peak worker memory exceeds the ceiling")
                seconds = timing.get("execution_validation_seconds")
                if not isinstance(seconds, (int, float)) or seconds * 1000 > wall_limit:
                    reasons.append(f"Scale case {label} has no wall time within the declared limit")
            values = [row["scale_value"] for row in ops]
            if row_axis_is_size_bound(ops):
                increasing = values[0] > values[1] > values[2]  # smaller mesh size bound = more work
            else:
                increasing = sizes[0] < sizes[1] < sizes[2]
            if not increasing:
                reasons.append(f"Family {family} {operation} scales do not increase")
        measured_families.append(family)
    probes = deterministic.get("ceiling_probes", [])
    for probe in probes:
        if probe["error"].get("class") == "worker_crash" or not probe["worker_processes_all_exited"]:
            reasons.append(
                f"Native crash inside declared bounds: {probe['operation']} at scale "
                f"{probe['scale_value']} (error {probe['error'].get('code')}, "
                f"{probe['worker_processes_started']} worker process(es) started); the crash is "
                "contained but the operation does not run within its declared bounds")
    result["measured"] = {
        "families_with_baselines": measured_families,
        "scale_cases": len(cases),
        "ceiling_probes": [{"operation": p["operation"], "scale_value": p["scale_value"],
                            "state": p["job_state"], "error": p["error"]} for p in probes],
    }

    # (2) resource-limit refusals
    limits = deterministic.get("limit_cases", [])
    kinds: dict[str, int] = {}
    for case in limits:
        ok = case["passed"] and case["observed"] == case["expected"]
        kinds[case["kind"]] = kinds.get(case["kind"], 0) + (1 if ok else 0)
        if not ok:
            reasons.append(f"Resource-limit case {case['id']} did not fail closed with the expected code")
        if case.get("published_delta", 0) != 0 or case.get("processes_all_exited") is False:
            reasons.append(f"Resource-limit case {case['id']} published an artifact or left a process")
        if case["kind"] == "native_resource_cap" and case.get("trials", 0) < PERFORMANCE_MIN_TRIALS_PER_MODE:
            reasons.append(f"Resource-limit case {case['id']} has too few trials")
    for kind, minimum in PERFORMANCE_REQUIRED_LIMIT_KINDS.items():
        if kinds.get(kind, 0) < minimum:
            reasons.append(f"Resource-limit coverage for {kind} is {kinds.get(kind, 0)} of {minimum}")
    result["measured"]["limit_cases"] = {"total": len(limits), "passed_by_kind": dict(sorted(kinds.items()))}

    # (3) crash containment
    modes = deterministic.get("containment", {})
    total_trials = total_contained = 0
    for kind, names in PERFORMANCE_REQUIRED_FAULT_KINDS.items():
        missing = sorted(names - set(modes))
        if missing:
            reasons.append(f"Fault kind {kind} lacks evidence for: {', '.join(missing)}")
    for name, record in sorted(modes.items()):
        floor = (PERFORMANCE_MIN_HOST_KILL_TRIALS if name == "host_process_killed"
                 else PERFORMANCE_MIN_GARBAGE_CASES if name == "garbage_input_files"
                 else PERFORMANCE_MIN_TRIALS_PER_MODE)
        total_trials += record["trials"]
        total_contained += record["contained"]
        if record["trials"] < floor:
            reasons.append(f"Fault mode {name} has {record['trials']} trials (need {floor}+)")
        if record["contained"] != record["trials"] or record["failures"]:
            reasons.append(f"Fault mode {name} contained {record['contained']} of {record['trials']} "
                           f"trials: {(record['failures'] or ['unspecified'])[0]}")
        if record.get("host_handle_growth_within_tolerance") is False:
            reasons.append(f"Fault mode {name} leaked host handles beyond the declared tolerance")
        expected = record.get("expected")
        if expected:
            for outcome in record.get("outcomes", {}):
                if json.loads(outcome)[1:] != expected:
                    reasons.append(f"Fault mode {name} produced an unexpected classification {outcome}")
    result["measured"]["containment"] = {
        "modes": len(modes), "trials": total_trials, "contained": total_contained,
        "contained_percent": round(100.0 * total_contained / total_trials, 4) if total_trials else 0.0}

    # (4) lifecycle and Phase 10 work items
    life = deterministic.get("lifecycle", {})
    if life.get("idle_worker_processes_after_jobs") != 0:
        reasons.append("Idle runtime retains worker processes")
    if not life.get("persistent_worker_pool") and life.get("second_call_executed_worker"):
        reasons.append("Persistent workers are not implemented (each call starts a fresh worker process), "
                       "so persistent-worker crash recovery and resource reclamation are unevidenced")
    if not life.get("operation_result_cache") and life.get("second_call_executed_worker"):
        reasons.append("Artifact/result cache and AABB reuse are not implemented, so their effect on "
                       "performance is unmeasured")
    result["measured"]["lifecycle"] = life

    if live:
        try:
            fresh = rob.measure(root, worker_path if worker_path.is_file() else None, stages=("faults",),
                                only_modes=PERFORMANCE_LIVE_MODES, trials=2, host_kill_trials=0)
        except Exception as exc:  # a live rerun that cannot execute is a reason, never a pass
            reasons.append(f"Live rerun of sampled fault modes could not execute: {type(exc).__name__}")
            fresh = None
        if fresh is not None:
            result["measured"]["live_rerun"] = PERFORMANCE_LIVE_MODES
            for name, record in fresh["deterministic"]["containment"].items():
                recorded = modes.get(name, {})
                if record["contained"] != record["trials"]:
                    reasons.append(f"Live rerun of fault mode {name} was not fully contained")
                if "refusals" in record:
                    if record["refusals"] != recorded.get("refusals"):
                        reasons.append("Live rerun of garbage input refusals differs from the evidence")
                elif set(record["outcomes"]) != set(recorded.get("outcomes", {})):
                    reasons.append(f"Live rerun of fault mode {name} produced different outcomes "
                                   "than the evidence")
    if not reasons:
        result["status"] = "met"
        if PERFORMANCE_GATE in WAVE_A_UNMET_STANDALONE_GATES:
            result["status"] = "met_pending_gate_list_update"
            reasons.append("Evidence supports the gate but the unmet standalone gate list still names it")
    return result


PACKAGE_GATE = "package_harvest_provenance"
PACKAGE_EVIDENCE = "catalog/packages.json"


def evaluate_package_harvest_gate(root: Path = REPO, *, source_root: Path | None = None) -> dict:
    """Machine-check the package-wide harvest: status, reason, license and provenance per package.

    Met only when every package has a vocabulary status with a reason code, validated counts match
    the operations catalog, every license is finally classified from official sources, provenance
    hashes are present, every operation license derives from its package record, and no package
    or operation is left for human license review. Review items keep the gate unmet.
    """
    reasons: list[str] = []
    result: dict = {"gate": PACKAGE_GATE, "status": "unmet", "evidence": PACKAGE_EVIDENCE,
                    "reasons": reasons}
    try:
        inventory = json.loads((root / "catalog/major_capability_inventory.json").read_text(encoding="utf-8"))
        operations = package_provenance.load_operations(root / "cgal_mcp/master/operations.json")
        measured = package_provenance.check_catalog(
            root / "catalog", operations=operations,
            policy=package_provenance.load_policy(root / "catalog/package_status_policy.json"),
            inventory=inventory, evidence_dir=root / "docs/master/evidence",
            source_root=source_root, repo=root)
        bundled_ok = all((root / "catalog" / name).read_bytes()
                         == (root / "cgal_mcp/master/catalog" / name).read_bytes()
                         for name in ("baseline.json", "packages.json", "docs_index.jsonl"))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        reasons.append(f"Package harvest evidence is unreadable: {type(exc).__name__}: {exc}")
        return result
    reasons.extend(measured.pop("blocking_reasons"))
    if not bundled_ok:
        reasons.append("Bundled catalog snapshot differs from the canonical catalog")
    review = measured["human_review"]
    result["measured"] = {**measured, "inventory_items": len(inventory["items"]),
                          "bundled_catalog_matches": bundled_ok,
                          "license_provenance_notice": package_provenance.NOTICE,
                          "source_tree_rehashed": source_root is not None}
    if not reasons and (review["packages"] or review["operations"]):
        reasons.append(f"{len(review['packages'])} package(s) and {len(review['operations'])} operation(s) "
                       "need human license review; licenses are provenance data, not legal advice")
    if not reasons:
        result["status"] = "met"
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
                                      WORKFLOW_GATE: evaluate_workflow_gate(REPO),
                                      PERFORMANCE_GATE: evaluate_performance_gate(REPO),
                                      PACKAGE_GATE: evaluate_package_harvest_gate(REPO)}
        report["standalone_acceptance_reason"] = "Additional package, routing, workflow, host and robustness gates required"
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content)


if __name__ == "__main__":
    main()
