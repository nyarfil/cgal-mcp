"""Trusted local replay for original major-capability families.

One mechanism replays every family: Wave A simplification (7.7) through its
bespoke harness and contract, and the data-declared families in
``scripts/master_replay_families.py`` through one generic harness.
For each family the runner invokes one fixed, checked-in Python harness. It never executes a
command supplied by an evidence report. The evaluator independently reruns this
harness for the selected native worker before it can approve the JSON report.
"""
from __future__ import annotations

import argparse
import base64
import copy
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

SCRIPT_REPO = Path(__file__).resolve().parents[1]
if str(SCRIPT_REPO) not in sys.path:
    sys.path.insert(0, str(SCRIPT_REPO))

from scripts import master_replay_families as families
from scripts.master_acceptance import (
    REPO,
    WAVE_A_BOUNDED_NORMAL_ANALYTIC_PROOF,
    WAVE_A_BOUNDED_NORMAL_CONTROL,
    WAVE_A_BOUNDED_NORMAL_ERROR_CLASS,
    WAVE_A_BOUNDED_NORMAL_ERROR_CODE,
    WAVE_A_BOUNDED_NORMAL_FILTERED,
    WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256,
    WAVE_A_REQUIREMENT_CASES,
    _canonical_hash,
    evaluate_requirements,
)

OFFICIAL_SOURCE_SHA256 = "b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf"
CASE_SOURCE = REPO / "tests/master_wave_a_cases.py"
DEFAULT_OUTPUT = REPO / "docs/master/evidence/wave-a-capabilities.json"
WORK_OUTPUT_ROOT = REPO / "work"
FAMILY_HARNESS = REPO / families.FAMILY_HARNESS_PATH
FAMILY_CONTRACT_SOURCE = REPO / families.FAMILY_CONTRACT_PATH
WAVE_A_FAMILY = "7.7"
REPLAY_FAMILIES = (WAVE_A_FAMILY, *families.GENERIC_FAMILIES)
# Families whose bound requirements need an optional third-party library compiled into the worker
# (see docs/master/THIRD_PARTY_DEPENDENCIES_JA.md): 7.9.05 needs OpenGR, 7.10.02 needs SCIP.
FAMILY_OPTIONAL_DEPENDENCIES = {"7.9": ("OpenGR",), "7.10": ("SCIP",)}
TRANSFORM = "mesh.simplify.edge_collapse"
INTEGRITY = "mesh.validate.simplification_integrity"
HAUSDORFF = "mesh.distance.symmetric_hausdorff"
REQUIRED_OPERATIONS = (TRANSFORM, INTEGRITY, HAUSDORFF)

POLICIES = (
    "lindstrom_turk",
    "edge_length_midpoint",
    "gh_plane",
    "gh_triangle",
    "gh_plane_line",
    "gh_probabilistic_plane",
    "gh_probabilistic_triangle",
)
STOP_PREDICATES = ("edge_count", "edge_ratio", "face_count", "face_ratio", "edge_length")
POLICY_CASES = {
    **{f"{TRANSFORM}.cost_placement.{name}": [f"policy-{name}"] for name in POLICIES},
    **{f"{TRANSFORM}.stop_predicate.{name}": (
        [f"stop-{name}", "stop-edge_length-below-minimum"]
        if name == "edge_length" else [f"stop-{name}"]
    ) for name in STOP_PREDICATES},
    f"{TRANSFORM}.wrapper.constraints": ["constraints", "preserve-open-border"],
    f"{TRANSFORM}.wrapper.bounded_distance": [
        "bounded-distance", "filter-control", "bounded-distance-tight",
    ],
    f"{TRANSFORM}.filter.bounded_normal_change": [
        "bounded-normal", "bounded-normal-adversarial",
    ],
    f"{TRANSFORM}.filter.polyhedral_envelope": [
        "polyhedral-envelope", "filter-control", "polyhedral-envelope-tight",
    ],
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_digest(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def _require_unchanged(path: Path, expected_sha256: str, label: str) -> None:
    if _digest(path) != expected_sha256:
        raise ValueError(f"{label} changed during the acceptance replay")


def _native_binary_format(path: Path) -> str:
    magic = path.read_bytes()[:4]
    if magic[:2] == b"MZ":
        return "pe"
    if magic == b"\x7fELF":
        return "elf"
    if magic in {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"}:
        return "mach-o"
    raise ValueError("Acceptance worker must be a native PE, ELF, or Mach-O executable")


def _load_json_object(text: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _contains_path_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(key in {"path", "output_dir"} or _contains_path_key(item)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_path_key(item) for item in value)
    return False


def _verify_blob(digest: str, value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("encoding") != "base64":
        raise ValueError(f"Trace blob {digest} has an unsupported encoding")
    try:
        content = base64.b64decode(value.get("content", ""), validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError(f"Trace blob {digest} is not strict base64") from error
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"Trace blob hash mismatch: {digest}")
    if value.get("byte_size") != len(content):
        raise ValueError(f"Trace blob byte count mismatch: {digest}")
    return {"encoding": "base64", "byte_size": len(content),
            "content": base64.b64encode(content).decode("ascii")}


def _read_verified_trace(path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    records: dict[str, dict] = {}
    blobs: dict[str, dict] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        record = _load_json_object(line, f"trace line {line_number}")
        if record.get("schema_version") != 1 or _contains_path_key(record):
            raise ValueError(f"Trace line {line_number} is not portable schema 1")
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in records:
            raise ValueError(f"Trace has an invalid or duplicate case id: {case_id!r}")
        request = record.get("request")
        response = record.get("response")
        if not isinstance(request, dict) or not isinstance(response, dict):
            raise ValueError(f"Trace case {case_id} has no request/response objects")
        if record.get("request_sha256") != _canonical_hash(request):
            raise ValueError(f"Trace request hash mismatch: {case_id}")
        if record.get("response_sha256") != _canonical_hash(response):
            raise ValueError(f"Trace response hash mismatch: {case_id}")
        if (request.get("request_id") != case_id or response.get("request_id") != case_id or
                request.get("operation") != record.get("operation_id")):
            raise ValueError(f"Trace request/response identity mismatch: {case_id}")
        trace_blobs = record.get("blobs")
        if not isinstance(trace_blobs, dict):
            raise ValueError(f"Trace case {case_id} has no blob map")
        for digest, blob in trace_blobs.items():
            verified = _verify_blob(digest, blob)
            if digest in blobs and blobs[digest] != verified:
                raise ValueError(f"Trace supplied conflicting content for blob: {digest}")
            blobs[digest] = verified
        referenced = [item.get("blob_sha256") for item in request.get("inputs", [])
                      if isinstance(item, dict)]
        referenced += [item.get("blob_sha256") for item in response.get("outputs", [])
                       if isinstance(item, dict)]
        if not referenced or any(digest not in trace_blobs for digest in referenced):
            raise ValueError(f"Trace case {case_id} has an unbound input/output blob")
        records[case_id] = record
    if not records:
        raise ValueError("Wave A harness produced no trace records")
    return records, blobs


def _operation_index(manifest: dict, operations: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    declared = {item.get("id"): item for item in manifest.get("operations", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)}
    registered = {item.get("id", item.get("operation", {}).get("id")): item
                  for item in operations if isinstance(item, dict)}
    for operation_id in REQUIRED_OPERATIONS:
        if operation_id not in declared or operation_id not in registered:
            raise ValueError(f"Required Wave A operation is missing: {operation_id}")
        if registered[operation_id].get("status") != "VALIDATED":
            raise ValueError(f"Required Wave A operation is not VALIDATED: {operation_id}")
        if declared[operation_id].get("revision") != registered[operation_id].get("revision"):
            raise ValueError(f"Worker/registry revision mismatch: {operation_id}")
    info = declared[TRANSFORM].get("info", {})
    if tuple(info.get("policies", [])) != POLICIES:
        raise ValueError("Worker policy manifest differs from the accepted seven-policy set")
    if tuple(info.get("stop_policies", [])) != STOP_PREDICATES:
        raise ValueError("Worker stop manifest differs from the accepted five-predicate set")
    if not {"preserve_border", "constrained_edges", "bounded_distance",
            "bounded_normal_change", "polyhedral_envelope"}.issubset(
                set(info.get("optional_constraints", []))):
        raise ValueError("Worker manifest omits a required Wave A wrapper/filter")
    return declared, registered


def _verify_policy_catalog(path: Path) -> dict[str, dict]:
    catalog = _load_json_object(path.read_text(encoding="utf-8"), "policy catalog")
    policies = catalog.get("policies")
    if not isinstance(policies, list):
        raise ValueError("Policy catalog has no policies list")
    indexed = {item.get("id"): item for item in policies if isinstance(item, dict)}
    validated = {policy_id for policy_id, item in indexed.items()
                 if item.get("operation") == TRANSFORM and item.get("status") == "VALIDATED"}
    if validated != set(POLICY_CASES):
        raise ValueError("Policy catalog differs from the accepted sixteen non-blocked policies")
    blocked = {policy_id for policy_id, item in indexed.items()
               if item.get("operation") == TRANSFORM and item.get("status") == "BLOCKED"}
    if blocked != {f"{TRANSFORM}.filter.fastenvelope"}:
        raise ValueError("Wave A blocked-policy catalog differs from the FastEnvelope baseline")
    return indexed


def _case_expectations() -> dict[str, dict[str, Any]]:
    expected = {
        f"policy-{policy}": {"policy": policy, "stop": "edge_ratio"}
        for policy in POLICIES
    }
    expected.update({
        f"stop-{stop}": {"policy": "lindstrom_turk", "stop": stop}
        for stop in STOP_PREDICATES
    })
    expected.update({
        "stop-edge_length-below-minimum": {
            "policy": "lindstrom_turk", "stop": "edge_length", "expect_removal": False,
        },
        "constraints": {"policy": "gh_plane_line", "stop": "edge_ratio",
                        "metric": ("constrained_edge_count", 1)},
        "preserve-open-border": {"policy": "lindstrom_turk", "stop": "edge_ratio",
                                 "metric": ("constrained_edge_count", 20)},
        "bounded-distance": {"policy": "gh_plane_line", "stop": "edge_ratio",
                             "metric": ("bounded_distance_enabled", True)},
        "bounded-normal": {"policy": "gh_plane_line", "stop": "edge_ratio",
                           "metric": ("bounded_normal_change_enabled", True)},
        "polyhedral-envelope": {"policy": "gh_plane_line", "stop": "edge_ratio",
                                "metric": ("polyhedral_envelope_enabled", True)},
        "filter-control": {"policy": "gh_plane_line", "stop": "edge_ratio"},
        "bounded-distance-tight": {
            "policy": "gh_plane_line", "stop": "edge_ratio", "expect_removal": False,
            "metric": ("bounded_distance_enabled", True),
        },
        "polyhedral-envelope-tight": {
            "policy": "gh_plane_line", "stop": "edge_ratio", "expect_removal": False,
            "metric": ("polyhedral_envelope_enabled", True),
        },
        "bounded-normal-adversarial": {
            "policy": "edge_length_midpoint", "stop": "edge_length",
            "expect_removal": False,
            "metric": ("bounded_normal_change_enabled", True),
        },
    })
    return expected


def _blob_hashes(items: object) -> list[str]:
    if not isinstance(items, list) or not items:
        raise ValueError("Trace exchange is missing input/output descriptors")
    values = [item.get("blob_sha256") for item in items if isinstance(item, dict)]
    if len(values) != len(items) or not all(isinstance(value, str) for value in values):
        raise ValueError("Trace exchange contains an invalid blob reference")
    return values


def _off_minimum_edge_length(digest: str, blobs: dict[str, dict]) -> float:
    try:
        tokens = base64.b64decode(blobs[digest]["content"], validate=True).decode("ascii").split()
        if tokens[0] != "OFF":
            raise ValueError
        vertex_count, face_count = int(tokens[1]), int(tokens[2])
        cursor = 4
        vertices = []
        for _ in range(vertex_count):
            vertices.append(tuple(float(tokens[cursor + axis]) for axis in range(3)))
            cursor += 3
        edges: set[tuple[int, int]] = set()
        for _ in range(face_count):
            size = int(tokens[cursor])
            indices = [int(tokens[cursor + 1 + offset]) for offset in range(size)]
            cursor += size + 1
            for offset, first in enumerate(indices):
                edges.add(tuple(sorted((first, indices[(offset + 1) % size]))))
        if not edges:
            raise ValueError
        return min(math.dist(vertices[first], vertices[second]) for first, second in edges)
    except (KeyError, UnicodeError, ValueError, TypeError, IndexError) as error:
        raise ValueError(f"Cannot measure OFF edge-length boundary for blob {digest}") from error


def _verify_stop_effect(case_id: str, request: dict, response: dict,
                        blobs: dict[str, dict]) -> None:
    if not case_id.startswith("stop-"):
        return
    stop = request["parameters"]["stop"]
    metrics = response["metrics"]
    kind, value = stop["kind"], stop["value"]
    if kind == "edge_count":
        passed = metrics["edges_before"] > value and metrics["edges_after"] <= value
    elif kind == "edge_ratio":
        passed = metrics["edges_after"] / metrics["edges_before"] <= value
    elif kind == "face_count":
        passed = metrics["faces_before"] > value and metrics["faces_after"] <= value
    elif kind == "face_ratio":
        passed = metrics["faces_after"] / metrics["faces_before"] <= value
    elif kind == "edge_length":
        if value.get("unit") != "mm":
            raise ValueError("Wave A edge-length boundary fixture must use millimetres")
        threshold = value["value"]
        input_minimum = _off_minimum_edge_length(_blob_hashes(request["inputs"])[0], blobs)
        if case_id == "stop-edge_length-below-minimum":
            passed = threshold < input_minimum and metrics["edges_removed"] == 0
        else:
            passed = input_minimum < threshold and metrics["edges_removed"] > 0
    else:
        passed = False
    if not passed:
        raise ValueError(f"Stop predicate did not establish its measured boundary: {case_id}")


def _validator_record(record: dict, operation_id: str, revision: int,
                      reports: dict[str, object], blobs: dict[str, dict]) -> dict:
    response = record["response"]
    metrics = response.get("metrics")
    if response.get("status") != "ok" or not isinstance(metrics, dict):
        raise ValueError(f"Validator did not return an OK report: {record['case_id']}")
    if metrics.get("status") != "pass":
        raise ValueError(f"Validator report did not pass: {record['case_id']}")
    if operation_id == HAUSDORFF and metrics.get("verdict") != "pass":
        raise ValueError(f"Hausdorff validator verdict did not pass: {record['case_id']}")
    output_hashes = _blob_hashes(record["response"].get("outputs"))
    if len(output_hashes) != 1:
        raise ValueError(f"Validator must produce exactly one report blob: {record['case_id']}")
    try:
        report_blob = json.loads(base64.b64decode(
            blobs[output_hashes[0]]["content"], validate=True).decode("utf-8"))
    except (KeyError, UnicodeError, ValueError, TypeError) as error:
        raise ValueError(f"Validator report blob is not UTF-8 JSON: {record['case_id']}") from error
    if report_blob != metrics:
        raise ValueError(f"Validator stdout/file reports differ: {record['case_id']}")
    report_sha256 = _canonical_hash(metrics)
    reports[report_sha256] = metrics
    return {
        "operation_id": operation_id,
        "revision": revision,
        "request_sha256": record["request_sha256"],
        "response_sha256": record["response_sha256"],
        "input_hashes": _blob_hashes(record["request"].get("inputs")),
        "output_hashes": output_hashes,
        "report_blob_sha256": output_hashes[0],
        "report_sha256": report_sha256,
        "status": "pass",
    }


def _bounded_normal_fixture_proof(digest: str, blobs: dict[str, dict]) -> dict:
    """Prove the inversion in both decimal-token and parsed-binary64 domains."""
    if digest != WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256:
        raise ValueError("Bounded-normal control did not use the approved fixed fixture")
    try:
        tokens = base64.b64decode(blobs[digest]["content"], validate=True).decode("ascii").split()
        if tokens[:4] != ["OFF", "4", "3", "0"]:
            raise ValueError
        decimal_vertices = [
            tuple(Fraction(tokens[4 + index * 3 + axis]) for axis in range(3))
            for index in range(4)
        ]
        binary64_vertices = [
            tuple(Fraction.from_float(float(tokens[4 + index * 3 + axis])) for axis in range(3))
            for index in range(4)
        ]
        cursor = 16
        faces = []
        for _ in range(3):
            if tokens[cursor] != "3":
                raise ValueError
            faces.append(tuple(int(tokens[cursor + offset]) for offset in range(1, 4)))
            cursor += 4
        if cursor != len(tokens):
            raise ValueError
    except (KeyError, UnicodeError, ValueError, TypeError, IndexError) as error:
        raise ValueError("Bounded-normal fixture is not the approved four-vertex OFF") from error

    edges = {
        tuple(sorted((face[offset], face[(offset + 1) % 3])))
        for face in faces for offset in range(3)
    }

    def squared_distance(vertices: list[tuple[Fraction, ...]], edge: tuple[int, int]) -> Fraction:
        first, second = (vertices[index] for index in edge)
        return sum((first[axis] - second[axis]) ** 2 for axis in range(3))

    decimal_ordered = sorted((squared_distance(decimal_vertices, edge), edge) for edge in edges)
    if (decimal_ordered[0] != (Fraction(17, 10000), (1, 3)) or
            decimal_ordered[1][0] <= Fraction(1, 100)):
        raise ValueError("Bounded-normal fixture does not have the required unique short edge")

    def subtract(first: tuple[Fraction, ...], second: tuple[Fraction, ...]) -> tuple[Fraction, ...]:
        return tuple(first[axis] - second[axis] for axis in range(3))

    def cross(first: tuple[Fraction, ...], second: tuple[Fraction, ...]) -> tuple[Fraction, ...]:
        return (
            first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0],
        )

    p, q, r, s = decimal_vertices
    midpoint = tuple((q[axis] + s[axis]) / 2 for axis in range(3))
    original_normal = cross(subtract(p, q), subtract(r, q))
    collapsed_normal = cross(subtract(p, midpoint), subtract(r, midpoint))
    scalar_product = sum(original_normal[axis] * collapsed_normal[axis] for axis in range(3))
    if (midpoint != (Fraction(0), Fraction(-1, 100), Fraction(1, 200)) or
            original_normal != (Fraction(0), Fraction(0), Fraction(1, 50)) or
            collapsed_normal != (Fraction(0), Fraction(-1, 100), Fraction(-1, 50)) or
            scalar_product != Fraction(-1, 2500)):
        raise ValueError("Bounded-normal fixture no longer proves a strict normal inversion")

    binary_ordered = sorted((squared_distance(binary64_vertices, edge), edge) for edge in edges)
    stop_squared = Fraction.from_float(0.1) ** 2
    p, q, r, s = binary64_vertices
    binary_midpoint = tuple((q[axis] + s[axis]) / 2 for axis in range(3))
    binary_original_normal = cross(subtract(p, q), subtract(r, q))
    binary_collapsed_normal = cross(subtract(p, binary_midpoint), subtract(r, binary_midpoint))
    binary_scalar_product = sum(
        binary_original_normal[axis] * binary_collapsed_normal[axis]
        for axis in range(3)
    )
    if (binary_ordered[0][1] != (1, 3) or
            not binary_ordered[0][0] < stop_squared or
            not binary_ordered[1][0] > stop_squared or
            not binary_scalar_product < Fraction(-3, 10000)):
        raise ValueError("Binary64 worker coordinates no longer prove the bounded-normal effect")
    return copy.deepcopy(WAVE_A_BOUNDED_NORMAL_ANALYTIC_PROOF)


def _build_bounded_normal_negative_control(
    records: dict[str, dict],
    blobs: dict[str, dict],
    declared: dict[str, dict],
    manifest_sha256: str,
    positive_result: dict,
) -> tuple[dict, set[str]]:
    transform = records.get(f"{WAVE_A_BOUNDED_NORMAL_CONTROL}-simplify")
    integrity = records.get(f"{WAVE_A_BOUNDED_NORMAL_CONTROL}-integrity")
    if not isinstance(transform, dict) or not isinstance(integrity, dict):
        raise ValueError("Bounded-normal negative control trace is incomplete")
    if (transform.get("operation_id") != TRANSFORM or
            integrity.get("operation_id") != INTEGRITY):
        raise ValueError("Bounded-normal negative control operation chain is incorrect")

    request = transform["request"]
    response = transform["response"]
    metrics = response.get("metrics", {})
    input_hashes = _blob_hashes(request.get("inputs"))
    output_hashes = _blob_hashes(response.get("outputs"))
    if (response.get("status") != "ok" or input_hashes != [WAVE_A_BOUNDED_NORMAL_FIXTURE_SHA256] or
            len(output_hashes) != 1 or output_hashes[0] == input_hashes[0] or
            metrics.get("policy") != "edge_length_midpoint" or
            metrics.get("stop_policy") != "edge_length" or
            metrics.get("bounded_normal_change_enabled") is not False or
            (metrics.get("edges_before"), metrics.get("edges_removed"), metrics.get("edges_after")) !=
            (6, 3, 3)):
        raise ValueError("Bounded-normal negative control transform assertions failed")

    positive_request = positive_result["request"]
    positive_metrics = positive_result["response"].get("metrics", {})
    control_parameters = copy.deepcopy(request.get("parameters"))
    filtered_parameters = copy.deepcopy(positive_request.get("parameters"))
    if not isinstance(control_parameters, dict) or not isinstance(filtered_parameters, dict):
        raise ValueError("Bounded-normal paired parameters are missing")
    control_flag = control_parameters.pop("bounded_normal_change", None)
    filtered_flag = filtered_parameters.pop("bounded_normal_change", None)
    if (control_flag is not False or filtered_flag is not True or
            control_parameters != filtered_parameters or
            request.get("kernel") != positive_request.get("kernel") or
            input_hashes != positive_result.get("input_hashes") or
            positive_metrics.get("edges_before") != 6 or
            positive_metrics.get("edges_removed") != 0 or
            positive_metrics.get("edges_after") != 6):
        raise ValueError("Bounded-normal control differs from the filtered run beyond the filter flag")
    stop = control_parameters.get("stop")
    if (control_parameters.get("policy") != "edge_length_midpoint" or
            control_parameters.get("preserve_border") is not False or
            stop != {"kind": "edge_length", "value": {"value": 0.1, "unit": "mm"}}):
        raise ValueError("Bounded-normal negative control parameters are not the analytic recipe")

    failure_request = integrity["request"]
    failure_response = integrity["response"]
    failure_inputs = _blob_hashes(failure_request.get("inputs"))
    error = failure_response.get("error")
    if (failure_request.get("parameters") != {"preserve_border": False, "constrained_edges": []} or
            failure_inputs != [output_hashes[0], input_hashes[0]] or
            failure_response.get("status") != "error" or
            failure_response.get("outputs") != [] or
            failure_response.get("metrics") != {} or
            not isinstance(error, dict) or
            error.get("class") != WAVE_A_BOUNDED_NORMAL_ERROR_CLASS or
            error.get("code") != WAVE_A_BOUNDED_NORMAL_ERROR_CODE):
        raise ValueError("Bounded-normal negative candidate was not rejected by the strict validator")

    parameter_proof = {
        "only_changed_parameter": "bounded_normal_change",
        "control_value": False,
        "filtered_value": True,
        "shared_parameters_sha256": _canonical_hash(control_parameters),
    }
    proof = {
        "case_id": WAVE_A_BOUNDED_NORMAL_CONTROL,
        "operation_id": TRANSFORM,
        "revision": declared[TRANSFORM]["revision"],
        "worker_manifest_sha256": manifest_sha256,
        "test_id": "wave-a-worker-cases",
        "paired_positive_case_id": WAVE_A_BOUNDED_NORMAL_FILTERED,
        "request": request,
        "request_sha256": transform["request_sha256"],
        "response": response,
        "response_sha256": transform["response_sha256"],
        "input_hashes": input_hashes,
        "output_hashes": output_hashes,
        "bindings": {
            "source_sha256": input_hashes[0],
            "rejected_candidate_sha256": output_hashes[0],
        },
        "parameter_proof": parameter_proof,
        "analytic_fixture": _bounded_normal_fixture_proof(input_hashes[0], blobs),
        "expected_validator_failure": {
            "operation_id": INTEGRITY,
            "revision": declared[INTEGRITY]["revision"],
            "request": failure_request,
            "request_sha256": integrity["request_sha256"],
            "response": failure_response,
            "response_sha256": integrity["response_sha256"],
            "input_hashes": failure_inputs,
            "output_hashes": [],
            "status": "expected_error",
        },
        "status": "expected_rejection",
    }
    return proof, set(input_hashes + output_hashes + failure_inputs)


def _build_results(records: dict[str, dict], blobs: dict[str, dict], declared: dict[str, dict],
                   manifest_sha256: str) -> tuple[
                       list[dict], dict[str, object], dict[str, dict], set[str]
                   ]:
    results = []
    reports: dict[str, object] = {}
    used_blobs: set[str] = set()
    expected_cases = _case_expectations()
    required_from_contract = set().union(*WAVE_A_REQUIREMENT_CASES.values())
    if set(expected_cases) != required_from_contract:
        raise ValueError("Runner cases differ from the checked acceptance coverage contract")
    for case_id, expectation in expected_cases.items():
        transform = records.get(f"{case_id}-simplify")
        integrity = records.get(f"{case_id}-integrity")
        hausdorff = records.get(f"{case_id}-hausdorff")
        if not all((transform, integrity, hausdorff)):
            raise ValueError(f"Case lacks transform and both mandatory validators: {case_id}")
        if (transform["operation_id"] != TRANSFORM or integrity["operation_id"] != INTEGRITY or
                hausdorff["operation_id"] != HAUSDORFF):
            raise ValueError(f"Case operation chain is incorrect: {case_id}")
        request = transform["request"]
        response = transform["response"]
        parameters = request.get("parameters", {})
        metrics = response.get("metrics", {})
        if response.get("status") != "ok" or not isinstance(metrics, dict):
            raise ValueError(f"Transform did not return OK metrics: {case_id}")
        if (parameters.get("policy") != expectation["policy"] or
                parameters.get("stop", {}).get("kind") != expectation["stop"] or
                metrics.get("policy") != expectation["policy"] or
                metrics.get("stop_policy") != expectation["stop"] or
                not isinstance(metrics.get("edges_removed"), int)):
            raise ValueError(f"Transform assertions failed: {case_id}")
        if expectation.get("expect_removal", True):
            if metrics["edges_removed"] <= 0 or metrics.get("edges_after", 0) >= metrics.get("edges_before", 0):
                raise ValueError(f"Transform did not remove edges: {case_id}")
        elif metrics["edges_removed"] != 0 or metrics.get("edges_after") != metrics.get("edges_before"):
            raise ValueError(f"Tight filter did not reject all collapse candidates: {case_id}")
        if "metric" in expectation:
            name, expected_value = expectation["metric"]
            if metrics.get(name) != expected_value:
                raise ValueError(f"Optional Wave A assertion failed: {case_id}/{name}")
        validator_records = [
            _validator_record(integrity, INTEGRITY, declared[INTEGRITY]["revision"], reports, blobs),
            _validator_record(hausdorff, HAUSDORFF, declared[HAUSDORFF]["revision"], reports, blobs),
        ]
        input_hashes = _blob_hashes(request.get("inputs"))
        output_hashes = _blob_hashes(response.get("outputs"))
        _verify_stop_effect(case_id, request, response, blobs)
        if output_hashes[0] not in validator_records[0]["input_hashes"] or output_hashes[0] not in validator_records[1]["input_hashes"]:
            raise ValueError(f"Validators did not consume the transform output: {case_id}")
        for value in input_hashes + output_hashes:
            used_blobs.add(value)
        for validator in validator_records:
            used_blobs.update(validator["input_hashes"])
            used_blobs.update(validator["output_hashes"])
        results.append({
            "case_id": case_id,
            "operation_id": TRANSFORM,
            "revision": declared[TRANSFORM]["revision"],
            "worker_manifest_sha256": manifest_sha256,
            "test_id": "wave-a-worker-cases",
            "request": request,
            "request_sha256": transform["request_sha256"],
            "response": response,
            "response_sha256": transform["response_sha256"],
            "input_hashes": input_hashes,
            "output_hashes": output_hashes,
            "validators": validator_records,
            "validation": {
                "status": "pass",
                "checks": {
                    "edge_collapse_executed": {"pass": True},
                    "integrity_validator": {"pass": True, "report_sha256": validator_records[0]["report_sha256"]},
                    "hausdorff_validator": {"pass": True, "report_sha256": validator_records[1]["report_sha256"]},
                },
            },
        })
        if case_id.startswith("stop-"):
            results[-1]["validation"]["checks"]["stop_boundary_measured"] = {"pass": True}
    indexed = {result["case_id"]: result for result in results}
    for filtered_case in ("bounded-distance-tight", "polyhedral-envelope-tight"):
        control = indexed["filter-control"]
        filtered = indexed[filtered_case]
        if (control["input_hashes"] != filtered["input_hashes"] or
                control["output_hashes"] == filtered["output_hashes"]):
            raise ValueError(f"Filter did not change the shared control result: {filtered_case}")
        filtered["validation"]["checks"]["adversarial_filter_effect"] = {
            "pass": True, "control_case_id": "filter-control",
        }
    if len(results) != 22 or sum(len(result["validators"]) for result in results) != 44:
        raise ValueError("Wave A positive evidence must remain 22 cases with 44 validator passes")
    normal_filtered = indexed[WAVE_A_BOUNDED_NORMAL_FILTERED]
    normal_proof, normal_used_blobs = _build_bounded_normal_negative_control(
        records, blobs, declared, manifest_sha256, normal_filtered,
    )
    used_blobs.update(normal_used_blobs)
    normal_filtered["validation"]["checks"]["bounded_normal_negative_control"] = {
        "pass": True,
        "negative_control_id": WAVE_A_BOUNDED_NORMAL_CONTROL,
        "rejected_candidate_sha256": normal_proof["bindings"]["rejected_candidate_sha256"],
    }
    edge_length_control = indexed["stop-edge_length-below-minimum"]
    edge_length_active = indexed["stop-edge_length"]
    if (edge_length_control["input_hashes"] != edge_length_active["input_hashes"] or
            edge_length_control["output_hashes"] == edge_length_active["output_hashes"] or
            edge_length_control["response"]["metrics"]["edges_removed"] != 0 or
            edge_length_active["response"]["metrics"]["edges_removed"] <= 0):
        raise ValueError("Edge-length stop threshold did not change the shared control result")
    for result, control_case_id in (
        (edge_length_control, "stop-edge_length"),
        (edge_length_active, "stop-edge_length-below-minimum"),
    ):
        result["validation"]["checks"]["stop_threshold_effect"] = {
            "pass": True, "control_case_id": control_case_id,
        }
    return (
        results,
        reports,
        {WAVE_A_BOUNDED_NORMAL_CONTROL: normal_proof},
        used_blobs,
    )


def _attest_worker(worker: Path) -> dict[str, Any]:
    """Hash and identify the native worker and read its pinned official manifest."""
    if not __debug__ or sys.flags.optimize:
        raise ValueError("Trusted acceptance replay requires Python assertions")
    worker = worker.resolve(strict=True)
    if not worker.is_file():
        raise ValueError("Worker path must name a regular file")
    worker_binary_format = _native_binary_format(worker)
    worker_sha256 = _digest(worker)
    manifest_process = subprocess.run(
        [str(worker), "--manifest"], cwd=REPO, check=True, capture_output=True,
        text=True, encoding="utf-8", timeout=30,
    )
    if manifest_process.stderr:
        raise ValueError("Worker changed or wrote diagnostics while reading its manifest")
    _require_unchanged(worker, worker_sha256, "Worker binary")
    manifest = _load_json_object(manifest_process.stdout, "worker manifest")
    if (manifest.get("protocol") != 1 or manifest.get("worker") != "cgal-master-worker" or
            manifest.get("actual_cgal_version") != "6.2.1" or
            manifest.get("request_model") != "one_json_line_per_process"):
        raise ValueError("Worker protocol/version differs from the Wave A acceptance baseline")
    build = manifest.get("build", {})
    if (build.get("source_kind") != "official_release" or
            build.get("source_sha256") != OFFICIAL_SOURCE_SHA256 or
            build.get("source_attestation") != "configured_pinned_official_archive" or
            build.get("test_stub") is True or not isinstance(build.get("compiler"), dict)):
        raise ValueError("Worker is not bound to the pinned official CGAL 6.2.1 source")
    return {"worker": worker, "worker_sha256": worker_sha256,
            "worker_binary_format": worker_binary_format, "manifest": manifest}


def _load_registry_operations() -> tuple[Path, list[dict]]:
    operation_path = REPO / "cgal_mcp/master/operations.json"
    operation_data = _load_json_object(operation_path.read_text(encoding="utf-8"), "operation registry")
    operations = operation_data.get("operations", [])
    if not isinstance(operations, list):
        raise ValueError("Operation registry has no operations list")
    return operation_path, operations


def _run_traced_harness(harness_args: list[str], label: str) -> tuple[
        str, int, dict[str, dict], dict[str, dict]]:
    """Run one fixed checked-in harness and return its verified portable trace."""
    with tempfile.TemporaryDirectory(prefix="master-capability-replay-") as folder:
        trace_path = Path(folder) / "replay-trace.jsonl"
        environment = dict(os.environ)
        environment.pop("PYTHONOPTIMIZE", None)
        environment["CGAL_MASTER_ACCEPTANCE_TRACE"] = str(trace_path)
        process = subprocess.Popen(
            harness_args, cwd=REPO, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        try:
            stdout, stderr = process.communicate(timeout=900)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        if process.returncode != 0:
            raise RuntimeError(f"{label} harness failed ({process.returncode}):\n{stdout}\n{stderr}")
        if stderr or not stdout.rstrip().endswith(": PASS"):
            raise ValueError(f"{label} harness did not finish cleanly")
        if not trace_path.is_file():
            raise ValueError(f"{label} harness did not produce its requested execution trace")
        records, blobs = _read_verified_trace(trace_path)
    return stdout, process.returncode, records, blobs


def _replay_wave_a(worker: Path) -> dict:
    """Execute and verify the fixed Wave A harness, returning its portable report."""
    attested = _attest_worker(worker)
    worker = attested["worker"]
    worker_sha256 = attested["worker_sha256"]
    worker_binary_format = attested["worker_binary_format"]
    manifest = attested["manifest"]
    source_sha256 = _source_digest(CASE_SOURCE)
    generator_sha256 = _source_digest(Path(__file__))
    source_bytes_sha256 = _digest(CASE_SOURCE)
    generator_bytes_sha256 = _digest(Path(__file__))

    operation_path, operations = _load_registry_operations()
    declared, _registered = _operation_index(manifest, operations)
    policy_path = REPO / "cgal_mcp/master/policies.json"
    _verify_policy_catalog(policy_path)
    manifest_sha256 = _canonical_hash(manifest)

    stdout, returncode, records, blobs = _run_traced_harness(
        [sys.executable, str(CASE_SOURCE), str(worker)], "Wave A",
    )

    _require_unchanged(worker, worker_sha256, "Worker binary")
    _require_unchanged(CASE_SOURCE, source_bytes_sha256, "Wave A test source")
    _require_unchanged(Path(__file__), generator_bytes_sha256, "Acceptance generator source")
    results, reports, negative_control_proofs, used_blobs = _build_results(
        records, blobs, declared, manifest_sha256,
    )
    if not used_blobs.issubset(blobs):
        raise ValueError("A verified result refers to a blob absent from the trace")
    blobs = {digest: blobs[digest] for digest in sorted(used_blobs)}

    report = {
        "schema_version": 1,
        "generator": "master-capability-acceptance",
        "generator_source_path": "scripts/replay_master_capabilities.py",
        "generator_source_sha256": generator_sha256,
        "generator_source_hash_encoding": "utf8-lf",
        "status": "pass",
        "scope": "wave_a_surface_mesh_simplification_only",
        "standalone_accepted": False,
        "standalone_unmet_gates": list(families.STANDALONE_UNMET_GATES),
        "requirements": list(WAVE_A_REQUIREMENT_CASES),
        "requirement_coverage": {
            requirement_id: {"case_ids": sorted(case_ids)}
            for requirement_id, case_ids in WAVE_A_REQUIREMENT_CASES.items()
        },
        "policy_coverage": {
            policy_id: {"case_ids": case_ids}
            for policy_id, case_ids in POLICY_CASES.items()
        },
        "catalog_baseline_sha256": _digest(REPO / "catalog/baseline.json"),
        "operation_registry_sha256": _source_digest(operation_path),
        "operation_registry_hash_encoding": "utf8-lf",
        "policy_catalog_sha256": _source_digest(policy_path),
        "policy_catalog_hash_encoding": "utf8-lf",
        "worker_sha256": worker_sha256,
        "worker_binary_format": worker_binary_format,
        "worker_manifest": manifest,
        "worker_manifest_sha256": manifest_sha256,
        "tests": [{
            "id": "wave-a-worker-cases",
            "source_path": "tests/master_wave_a_cases.py",
            "source_sha256": source_sha256,
            "source_hash_encoding": "utf8-lf",
            "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            "exit_code": returncode,
            "status": "pass",
        }],
        "blobs": blobs,
        "reports": reports,
        "operation_results": results,
        "negative_control_proofs": negative_control_proofs,
        "coverage_note": "Six original 7.7 requirements are replayed through 7 cost/placement policies, "
                         "5 stop predicates, constraint/border cases, bounded distance, bounded normal "
                         "change, Polyhedral Envelope, and both mandatory validators. The immutable "
                         "80-requirement denominator and full standalone acceptance remain incomplete.",
    }
    _require_unchanged(worker, worker_sha256, "Worker binary")
    return report


def _generic_operation_index(manifest: dict, registry: dict[str, dict],
                             operation_ids: set[str]) -> dict[str, dict]:
    declared = {item.get("id"): item for item in manifest.get("operations", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)}
    for operation_id in sorted(operation_ids):
        registered = registry.get(operation_id)
        if operation_id not in declared or registered is None:
            raise ValueError(f"Required family operation is missing: {operation_id}")
        if registered.get("status") != "VALIDATED":
            raise ValueError(f"Required family operation is not VALIDATED: {operation_id}")
        if declared[operation_id].get("revision") != registered.get("revision"):
            raise ValueError(f"Worker/registry revision mismatch: {operation_id}")
    return declared


def _family_operation_ids(family: dict, registry: dict[str, dict]) -> set[str]:
    operation_ids = {case["operation"] for case in family["cases"]}
    operation_ids |= {control["operation"] for control in family["negative_controls"]}
    for case in family["cases"]:
        if case["operation"] not in registry:
            raise ValueError(f"Family case names an unregistered operation: {case['operation']}")
        operation_ids.update(families.mandatory_validators(registry[case["operation"]]))
    return operation_ids


def _expected_request_inputs(items: list[dict], record_inputs: object, label: str) -> list[str]:
    if not isinstance(record_inputs, list) or len(record_inputs) != len(items):
        raise ValueError(f"Traced inputs differ from the family contract: {label}")
    hashes = []
    for declared_input, traced in zip(items, record_inputs):
        if (not isinstance(traced, dict) or traced.get("sha256") != declared_input["sha256"] or
                traced.get("blob_sha256") != declared_input["sha256"] or
                any(traced.get(key) != declared_input[key] for key in ("type", "format", "unit"))):
            raise ValueError(f"Traced input differs from the declared fixture: {label}")
        hashes.append(declared_input["sha256"])
    return hashes


def _build_generic_results(family: dict, records: dict[str, dict], blobs: dict[str, dict],
                           registry: dict[str, dict], declared: dict[str, dict],
                           manifest_sha256: str) -> tuple[
                               list[dict], dict[str, object], dict[str, dict], set[str]]:
    """Independently re-check every traced family exchange against the contract."""
    content = families.blob_bytes(blobs)
    results: list[dict] = []
    reports: dict[str, object] = {}
    used_blobs: set[str] = set()
    expected_records: set[str] = set()
    for case in family["cases"]:
        case_id = case["id"]
        operation = registry[case["operation"]]
        record = records.get(case_id)
        if not isinstance(record, dict) or record.get("operation_id") != case["operation"]:
            raise ValueError(f"Family case trace is missing: {case_id}")
        expected_records.add(case_id)
        request, response = record["request"], record["response"]
        if (request.get("parameters") != case["parameters"] or
                request.get("kernel") != "package_recommended" or
                response.get("status") != "ok"):
            raise ValueError(f"Family transform request/result differs from the contract: {case_id}")
        input_hashes = _expected_request_inputs(case["inputs"], request.get("inputs"), case_id)
        output_hashes = _blob_hashes(response.get("outputs"))
        declared_outputs = {slot["slot"]: slot for slot in operation["io"]["outputs"]}
        output_slots = [item.get("slot") for item in response["outputs"]]
        if (sorted(output_slots) != sorted(declared_outputs) or
                any(item.get("type") != declared_outputs[item.get("slot")]["type"]
                    for item in response["outputs"])):
            raise ValueError(f"Family transform outputs differ from the registry: {case_id}")
        view = families.CaseView(operation, request, response, content)
        failures = families.assertion_failures(case, view)
        if failures:
            raise ValueError("Family behaviour assertions failed: " + "; ".join(failures))
        validator_records = []
        checks: dict[str, dict] = {
            "transform_executed": {"pass": True},
            "behaviour_assertions": {"pass": True, "count": len(case["assertions"])},
        }
        for validator_id in families.mandatory_validators(operation):
            validator = registry[validator_id]
            plan, parameters = families.derive_validator_plan(operation, validator, case["parameters"])
            expected_inputs = [
                (view.inputs if kind == "input" else view.outputs)[slot]["blob_sha256"]
                for kind, slot in plan
            ]
            validator_record = records.get(f"{case_id}--{validator_id}")
            if (not isinstance(validator_record, dict) or
                    validator_record.get("operation_id") != validator_id):
                raise ValueError(f"Mandatory validator trace is missing: {case_id}/{validator_id}")
            expected_records.add(f"{case_id}--{validator_id}")
            validator_request = validator_record["request"]
            validator_response = validator_record["response"]
            if (_blob_hashes(validator_request.get("inputs")) != expected_inputs or
                    validator_request.get("parameters") != parameters or
                    validator_response.get("status") != "ok"):
                raise ValueError("Validator request is not derived from registry bindings: "
                                 f"{case_id}/{validator_id}")
            report_outputs = _blob_hashes(validator_response.get("outputs"))
            if (len(report_outputs) != 1 or
                    validator_response["outputs"][0].get("slot") != "validation" or
                    validator_response["outputs"][0].get("type") != "ValidationReport"):
                raise ValueError(f"Validator must produce exactly one report: {case_id}/{validator_id}")
            try:
                report_value = json.loads(content[report_outputs[0]].decode("utf-8"))
            except (KeyError, UnicodeError, ValueError) as error:
                raise ValueError(f"Validator report is not UTF-8 JSON: {case_id}/{validator_id}") from error
            failed = families.validator_report_failures(validator, report_value, case["operation"])
            if failed:
                raise ValueError(f"Validator report failed {failed}: {case_id}/{validator_id}")
            report_sha256 = _canonical_hash(report_value)
            reports[report_sha256] = report_value
            validator_records.append({
                "operation_id": validator_id,
                "revision": declared[validator_id]["revision"],
                "request": validator_request,
                "request_sha256": validator_record["request_sha256"],
                "response": validator_response,
                "response_sha256": validator_record["response_sha256"],
                "input_hashes": expected_inputs,
                "output_hashes": report_outputs,
                "report_blob_sha256": report_outputs[0],
                "report_sha256": report_sha256,
                "status": "pass",
            })
            checks[f"validator:{validator_id}"] = {"pass": True, "report_sha256": report_sha256}
            used_blobs.update(expected_inputs + report_outputs)
        used_blobs.update(input_hashes + output_hashes)
        results.append({
            "case_id": case_id,
            "operation_id": case["operation"],
            "revision": declared[case["operation"]]["revision"],
            "worker_manifest_sha256": manifest_sha256,
            "test_id": family["test_id"],
            "request": request,
            "request_sha256": record["request_sha256"],
            "response": response,
            "response_sha256": record["response_sha256"],
            "input_hashes": input_hashes,
            "output_hashes": output_hashes,
            "validators": validator_records,
            "validation": {"status": "pass", "checks": checks},
        })
    indexed = {result["case_id"]: result for result in results}
    for pair in family["pairs"]:
        first, second = (indexed[case_id] for case_id in pair["cases"])
        equal = first["output_hashes"] == second["output_hashes"]
        if (first["input_hashes"] != second["input_hashes"] or
                equal != (pair["kind"] == "equal_outputs")):
            raise ValueError(f"Paired-case check failed: {pair}")
        for this, other in ((first, second), (second, first)):
            this["validation"]["checks"][f"pair:{pair['kind']}:{other['case_id']}"] = {"pass": True}
    proofs: dict[str, dict] = {}
    for control in family["negative_controls"]:
        record = records.get(control["id"])
        if not isinstance(record, dict) or record.get("operation_id") != control["operation"]:
            raise ValueError(f"Negative control trace is missing: {control['id']}")
        expected_records.add(control["id"])
        request, response = record["request"], record["response"]
        input_hashes = _expected_request_inputs(control["inputs"], request.get("inputs"), control["id"])
        error = response.get("error")
        if (request.get("parameters") != control["parameters"] or
                response.get("status") != "error" or response.get("outputs") != [] or
                not isinstance(error, dict) or error.get("class") != control["expect_error_class"] or
                ("expect_error_code" in control and error.get("code") != control["expect_error_code"])):
            raise ValueError(f"Negative control was not rejected as declared: {control['id']}")
        used_blobs.update(input_hashes)
        proofs[control["id"]] = {
            "case_id": control["id"],
            "operation_id": control["operation"],
            "revision": declared[control["operation"]]["revision"],
            "worker_manifest_sha256": manifest_sha256,
            "test_id": family["test_id"],
            "request": request,
            "request_sha256": record["request_sha256"],
            "response": response,
            "response_sha256": record["response_sha256"],
            "input_hashes": input_hashes,
            "output_hashes": [],
            "expected_error_class": control["expect_error_class"],
            "status": "expected_rejection",
        }
    if set(records) != expected_records:
        raise ValueError("Family trace contains exchanges outside the declared contract")
    return results, reports, proofs, used_blobs


def _replay_generic_family(worker: Path, family_id: str) -> dict:
    family = families.GENERIC_FAMILIES[family_id]
    families.validate_contract(family)
    attested = _attest_worker(worker)
    worker = attested["worker"]
    manifest = attested["manifest"]
    worker_sha256 = attested["worker_sha256"]
    operation_path, operations = _load_registry_operations()
    registry = families.registry_index(operations)
    declared = _generic_operation_index(manifest, registry, _family_operation_ids(family, registry))
    policy_path = REPO / "cgal_mcp/master/policies.json"
    manifest_sha256 = _canonical_hash(manifest)
    tracked = (FAMILY_HARNESS, Path(__file__), FAMILY_CONTRACT_SOURCE, operation_path)
    before = {path: _digest(path) for path in tracked}
    stdout, returncode, records, blobs = _run_traced_harness(
        [sys.executable, str(FAMILY_HARNESS), str(worker), family_id], f"Family {family_id}",
    )
    _require_unchanged(worker, worker_sha256, "Worker binary")
    for path, value in before.items():
        _require_unchanged(path, value, f"Family replay source {path.name}")
    results, reports, proofs, used_blobs = _build_generic_results(
        family, records, blobs, registry, declared, manifest_sha256,
    )
    if not used_blobs.issubset(blobs):
        raise ValueError("A verified result refers to a blob absent from the trace")
    report = {
        "schema_version": 1,
        "generator": "master-capability-acceptance",
        "generator_source_path": "scripts/replay_master_capabilities.py",
        "generator_source_sha256": _source_digest(Path(__file__)),
        "generator_source_hash_encoding": "utf8-lf",
        "status": "pass",
        "scope": family["scope"],
        "family": family_id,
        "standalone_accepted": False,
        "standalone_unmet_gates": list(families.STANDALONE_UNMET_GATES),
        "binding_rule": families.BINDING_RULE,
        "requirements": list(family["requirements"]),
        "requirement_coverage": families.requirement_coverage(family),
        "unbound_requirements": dict(family["unbound"]),
        "family_contract_sha256": families.contract_digest(family),
        "family_contract_source_path": families.FAMILY_CONTRACT_PATH,
        "family_contract_source_sha256": _source_digest(FAMILY_CONTRACT_SOURCE),
        "family_contract_source_hash_encoding": "utf8-lf",
        "catalog_baseline_sha256": _digest(REPO / "catalog/baseline.json"),
        "operation_registry_sha256": _source_digest(operation_path),
        "operation_registry_hash_encoding": "utf8-lf",
        "policy_catalog_sha256": _source_digest(policy_path),
        "policy_catalog_hash_encoding": "utf8-lf",
        "worker_sha256": worker_sha256,
        "worker_binary_format": attested["worker_binary_format"],
        "worker_manifest": manifest,
        "worker_manifest_sha256": manifest_sha256,
        "tests": [{
            "id": family["test_id"],
            "source_path": families.FAMILY_HARNESS_PATH,
            "source_sha256": _source_digest(FAMILY_HARNESS),
            "source_hash_encoding": "utf8-lf",
            "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            "exit_code": returncode,
            "status": "pass",
        }],
        "blobs": {digest: blobs[digest] for digest in sorted(used_blobs)},
        "reports": reports,
        "operation_results": results,
        "negative_control_proofs": proofs,
        "coverage_note": f"Family {family_id}: {len(family['requirements'])} requirement(s) bound by "
                         f"{len(results)} replayed cases with registry-derived mandatory validators; "
                         f"{len(family['unbound'])} requirement(s) remain unbound with recorded gaps. "
                         "The immutable 80-requirement denominator and full standalone acceptance "
                         "remain incomplete.",
    }
    _require_unchanged(worker, worker_sha256, "Worker binary")
    return report


def worker_optional_dependencies(worker: Path) -> set[str]:
    """Optional libraries the worker was built with, from its manifest (build.optional_dependencies)."""
    try:
        completed = subprocess.run([str(worker), "--manifest"], capture_output=True, text=True,
                                   encoding="utf-8", timeout=60, check=True)
        build = json.loads(completed.stdout).get("build", {})
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise SystemExit(f"Cannot read the worker manifest to check optional dependencies: {error}") from error
    value = build.get("optional_dependencies", "")
    return {item for item in str(value).split(",") if item}


def unavailable_families(selected: list[str], built: set[str]) -> dict[str, list[str]]:
    """Selected families that need an optional library the worker was built without."""
    return {family: sorted(set(FAMILY_OPTIONAL_DEPENDENCIES.get(family, ())) - built)
            for family in selected if set(FAMILY_OPTIONAL_DEPENDENCIES.get(family, ())) - built}


def replay(worker: Path, family: str = WAVE_A_FAMILY) -> dict:
    """Execute and verify one family's fixed harness, returning its portable report."""
    if family == WAVE_A_FAMILY:
        return _replay_wave_a(worker)
    if family in families.GENERIC_FAMILIES:
        return _replay_generic_family(worker, family)
    raise ValueError(f"No replay contract is declared for family {family!r}")


def _load_requirements_and_operations() -> tuple[dict, dict[str, dict]]:
    requirements = _load_json_object(
        (REPO / "catalog/major_requirements.json").read_text(encoding="utf-8"),
        "major requirement catalog",
    )
    operation_data = _load_json_object(
        (REPO / "cgal_mcp/master/operations.json").read_text(encoding="utf-8"),
        "operation registry",
    )
    operations = {item.get("id", item.get("operation", {}).get("id")): item
                  for item in operation_data.get("operations", []) if isinstance(item, dict)}
    return requirements, operations


def published_output(family: str) -> Path:
    if family == WAVE_A_FAMILY:
        return DEFAULT_OUTPUT
    return REPO / families.GENERIC_FAMILIES[family]["evidence_path"]


def family_bindings(family: str) -> dict[str, list[str]]:
    """Requirement id -> operation ids that the family's replay report may establish."""
    if family == WAVE_A_FAMILY:
        return {requirement_id: [TRANSFORM] for requirement_id in WAVE_A_REQUIREMENT_CASES}
    return {requirement_id: list(binding["operation_ids"]) for requirement_id, binding in
            families.GENERIC_FAMILIES[family]["requirements"].items()}


def _requirements_for_replayed_report(requirements: dict, output: Path,
                                      report_sha256: str, family: str = WAVE_A_FAMILY) -> dict:
    """Point only a process-local catalog copy at this freshly replayed report.

    Build-specific worker/compiler hashes make replay reports intentionally vary
    across CI jobs.  The checked catalog remains bound to the published snapshot;
    the receipt from ``replay`` is still required when this copy is evaluated.
    """
    output = output.resolve()
    try:
        relative_output = output.relative_to(REPO.resolve()).as_posix()
    except ValueError as error:
        raise ValueError("Acceptance report output must remain inside the repository") from error
    if (not isinstance(report_sha256, str) or len(report_sha256) != 64 or
            any(character not in "0123456789abcdef" for character in report_sha256)):
        raise ValueError("Fresh acceptance report digest is invalid")
    copied = copy.deepcopy(requirements)
    published = published_output(family)
    published_output_path = published.resolve()
    indexed = {
        item.get("id"): item
        for family_item in copied.get("families", []) if isinstance(family_item, dict)
        for item in family_item.get("requirements", []) if isinstance(item, dict)
    }
    for requirement_id, operation_ids in family_bindings(family).items():
        item = indexed.get(requirement_id)
        if (not isinstance(item, dict) or item.get("operation_ids") != operation_ids or
                not isinstance(item.get("evidence"), list) or len(item["evidence"]) != 1 or
                not isinstance(item["evidence"][0], dict) or
                item["evidence"][0].get("path") != published.relative_to(REPO).as_posix()):
            raise ValueError(f"Checked family {family} catalog binding changed: {requirement_id}")
        if output == published_output_path:
            if item["evidence"][0].get("sha256") != report_sha256:
                raise ValueError(f"Published family {family} evidence hash is stale: {requirement_id}")
        else:
            item["evidence"][0] = {"path": relative_output, "sha256": report_sha256}
    return copied


def _approved_output_path(value: Path, family: str = WAVE_A_FAMILY) -> Path:
    output = value.resolve()
    default = published_output(family).resolve()
    work_root = WORK_OUTPUT_ROOT.resolve()
    if output != default and (not output.is_relative_to(work_root) or output.suffix != ".json"):
        raise ValueError(
            "Acceptance report output must be the published snapshot or a JSON file under work/"
        )
    return output


def _encode_report(report: dict) -> bytes:
    return (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--family", choices=("all", *REPLAY_FAMILIES), default="all")
    parser.add_argument("--output", type=Path,
                        help="report path for a single --family (published snapshot or work/*.json)")
    parser.add_argument("--work-dir", type=Path,
                        help="directory under work/ receiving family-<id>.json for each family")
    parser.add_argument("--skip-unavailable-optional", action="store_true",
                        help="skip families that need an optional library (OpenGR, SCIP) the worker lacks, "
                             "instead of failing; the reported count is then reduced")
    args = parser.parse_args()
    selected = list(REPLAY_FAMILIES) if args.family == "all" else [args.family]
    skipped = unavailable_families(selected, worker_optional_dependencies(args.worker))
    if skipped:
        needs = ", ".join(sorted({library for libraries in skipped.values() for library in libraries}))
        detail = "; ".join(f"family {family} requires {', '.join(libraries)}"
                           for family, libraries in sorted(skipped.items()))
        if not args.skip_unavailable_optional:
            raise SystemExit(
                f"This worker was built without {needs} ({detail}). Rebuild it with the optional libraries "
                "(docs/master/THIRD_PARTY_DEPENDENCIES_JA.md), or pass --skip-unavailable-optional to replay "
                "only the other families; the validated count is then reduced and 80 is not reachable.")
        selected = [family for family in selected if family not in skipped]
        if not selected:
            raise SystemExit(f"Every selected family is unavailable: requires {needs}")
        print(f"WARNING: skipping families that require {needs}: {detail}", file=sys.stderr)
    if args.output is not None and (len(selected) != 1 or args.work_dir is not None):
        raise SystemExit("--output requires one --family and excludes --work-dir")
    try:
        outputs = {}
        for family in selected:
            if args.output is not None:
                candidate = args.output
            elif args.work_dir is not None:
                candidate = args.work_dir / f"family-{family}.json"
            else:
                candidate = published_output(family)
            outputs[family] = _approved_output_path(candidate, family)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    requirements, operations = _load_requirements_and_operations()
    contents: dict[str, bytes] = {}
    reports: dict[str, dict] = {}
    for family in selected:
        reports[family] = replay(args.worker, family)
        contents[family] = _encode_report(reports[family])
        digest = hashlib.sha256(contents[family]).hexdigest()
        # A published snapshot must already have its digest approved in the checked
        # catalog. Fail before touching it when a different platform/build is used.
        if outputs[family] == published_output(family).resolve():
            _requirements_for_replayed_report(requirements, outputs[family], digest, family)
    WORK_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staged_paths: dict[str, Path] = {}
    try:
        replay_requirements = requirements
        for family in selected:
            with tempfile.NamedTemporaryFile(
                prefix=f"family-{family}-acceptance-", suffix=".json", dir=WORK_OUTPUT_ROOT,
                delete=False,
            ) as staged:
                staged.write(contents[family])
                staged.flush()
                os.fsync(staged.fileno())
                staged_paths[family] = Path(staged.name).resolve()
            replay_requirements = _requirements_for_replayed_report(
                replay_requirements, staged_paths[family],
                hashlib.sha256(contents[family]).hexdigest(), family,
            )
        evaluated = evaluate_requirements(
            replay_requirements, operations, REPO,
            replay_worker=args.worker,
        )
        expected_ids = {requirement_id for family in selected for requirement_id in family_bindings(family)}
        family_rows = [row for row in evaluated["requirements"] if row["id"] in expected_ids]
        if (len(family_rows) != len(expected_ids) or
                any(row["status"] != "VALIDATED" for row in family_rows)):
            details = {row["id"]: row["reasons"] for row in family_rows if row["status"] != "VALIDATED"}
            raise SystemExit(
                "Report replay passed, but checked-in catalog bindings are incomplete: " +
                json.dumps(details, ensure_ascii=False)
            )
        for family in selected:
            _require_unchanged(
                args.worker.resolve(strict=True), reports[family]["worker_sha256"], "Worker binary",
            )
            outputs[family].parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_paths.pop(family), outputs[family])
    finally:
        for staging in staged_paths.values():
            if staging.is_file():
                staging.unlink()
    print(json.dumps({
        "status": "pass",
        "families": {
            family: {
                "report": outputs[family].relative_to(REPO).as_posix(),
                "report_sha256": hashlib.sha256(contents[family]).hexdigest(),
                "requirements_validated": len(family_bindings(family)),
            } for family in selected
        },
        "worker_sha256": reports[selected[0]]["worker_sha256"],
        "worker_manifest_sha256": reports[selected[0]]["worker_manifest_sha256"],
        "requirements_validated": len(family_rows),
        "major_requirements_validated": evaluated["validated"],
        "major_requirements_required": evaluated["required"],
        "skipped_families_missing_optional_dependencies": skipped,
        "standalone_accepted": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
