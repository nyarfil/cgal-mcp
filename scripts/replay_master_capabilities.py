"""Trusted local replay for the six original Wave A major requirements.

The runner invokes one fixed, checked-in Python harness. It never executes a
command supplied by an evidence report. The evaluator independently reruns this
harness for the selected native worker before it can approve the JSON report.
"""
from __future__ import annotations

import argparse
import base64
import copy
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

from scripts.master_acceptance import (
    REPO,
    WAVE_A_REQUIREMENT_CASES,
    _canonical_hash,
    evaluate_requirements,
)

OFFICIAL_SOURCE_SHA256 = "b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf"
CASE_SOURCE = REPO / "tests/master_wave_a_cases.py"
DEFAULT_OUTPUT = REPO / "docs/master/evidence/wave-a-capabilities.json"
WORK_OUTPUT_ROOT = REPO / "work"
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
        "bounded-normal", "bounded-normal-control", "bounded-normal-adversarial",
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
        "bounded-normal-control": {
            "policy": "gh_plane_line", "stop": "edge_ratio",
            "metric": ("bounded_normal_change_enabled", False),
        },
        "bounded-normal-adversarial": {
            "policy": "gh_plane_line", "stop": "edge_ratio",
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


def _build_results(records: dict[str, dict], blobs: dict[str, dict], declared: dict[str, dict],
                   manifest_sha256: str) -> tuple[list[dict], dict[str, object], set[str]]:
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
    normal_control = indexed["bounded-normal-control"]
    normal_filtered = indexed["bounded-normal-adversarial"]
    if (normal_control["input_hashes"] != normal_filtered["input_hashes"] or
            normal_control["response"]["metrics"]["edges_removed"] !=
            normal_filtered["response"]["metrics"]["edges_removed"] or
            normal_control["output_hashes"] == normal_filtered["output_hashes"]):
        raise ValueError("Bounded-normal filter did not change the shared adversarial result")
    normal_filtered["validation"]["checks"]["adversarial_filter_effect"] = {
        "pass": True, "control_case_id": "bounded-normal-control",
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
    return results, reports, used_blobs


def replay(worker: Path) -> dict:
    """Execute and verify the fixed Wave A harness, returning its portable report."""
    if not __debug__ or sys.flags.optimize:
        raise ValueError("Trusted acceptance replay requires Python assertions")
    worker = worker.resolve(strict=True)
    if not worker.is_file():
        raise ValueError("Worker path must name a regular file")
    worker_binary_format = _native_binary_format(worker)
    worker_sha256 = _digest(worker)
    source_sha256 = _source_digest(CASE_SOURCE)
    generator_sha256 = _source_digest(Path(__file__))
    source_bytes_sha256 = _digest(CASE_SOURCE)
    generator_bytes_sha256 = _digest(Path(__file__))
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

    operation_path = REPO / "cgal_mcp/master/operations.json"
    operation_data = _load_json_object(operation_path.read_text(encoding="utf-8"), "operation registry")
    operations = operation_data.get("operations", [])
    if not isinstance(operations, list):
        raise ValueError("Operation registry has no operations list")
    declared, _registered = _operation_index(manifest, operations)
    policy_path = REPO / "cgal_mcp/master/policies.json"
    _verify_policy_catalog(policy_path)
    manifest_sha256 = _canonical_hash(manifest)

    with tempfile.TemporaryDirectory(prefix="master-capability-replay-") as folder:
        trace_path = Path(folder) / "wave-a-trace.jsonl"
        environment = dict(os.environ)
        environment.pop("PYTHONOPTIMIZE", None)
        environment["CGAL_MASTER_ACCEPTANCE_TRACE"] = str(trace_path)
        harness_args = (sys.executable, str(CASE_SOURCE), str(worker))
        process = subprocess.Popen(
            list(harness_args), cwd=REPO, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        try:
            stdout, stderr = process.communicate(timeout=900)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        if process.returncode != 0:
            raise RuntimeError(f"Wave A harness failed ({process.returncode}):\n{stdout}\n{stderr}")
        if stderr or not stdout.rstrip().endswith(": PASS"):
            raise ValueError("Wave A harness did not finish cleanly")
        if not trace_path.is_file():
            raise ValueError("Wave A harness did not produce its requested execution trace")
        records, blobs = _read_verified_trace(trace_path)

    _require_unchanged(worker, worker_sha256, "Worker binary")
    _require_unchanged(CASE_SOURCE, source_bytes_sha256, "Wave A test source")
    _require_unchanged(Path(__file__), generator_bytes_sha256, "Acceptance generator source")
    results, reports, used_blobs = _build_results(records, blobs, declared, manifest_sha256)
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
        "standalone_unmet_gates": [
            "remaining_major_capability_requirements",
            "search_and_retrieval_acceptance",
            "multi_operation_workflow_acceptance",
            "host_compatibility_matrix",
            "performance_resource_and_robustness_acceptance",
        ],
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
            "exit_code": process.returncode,
            "status": "pass",
        }],
        "blobs": blobs,
        "reports": reports,
        "operation_results": results,
        "coverage_note": "Six original 7.7 requirements are replayed through 7 cost/placement policies, "
                         "5 stop predicates, constraint/border cases, bounded distance, bounded normal "
                         "change, Polyhedral Envelope, and both mandatory validators. The immutable "
                         "80-requirement denominator and full standalone acceptance remain incomplete.",
    }
    _require_unchanged(worker, worker_sha256, "Worker binary")
    return report


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


def _requirements_for_replayed_report(requirements: dict, output: Path,
                                      report_sha256: str) -> dict:
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
    published_output = DEFAULT_OUTPUT.resolve()
    indexed = {
        item.get("id"): item
        for family in copied.get("families", []) if isinstance(family, dict)
        for item in family.get("requirements", []) if isinstance(item, dict)
    }
    for requirement_id in WAVE_A_REQUIREMENT_CASES:
        item = indexed.get(requirement_id)
        if (not isinstance(item, dict) or item.get("operation_ids") != [TRANSFORM] or
                not isinstance(item.get("evidence"), list) or len(item["evidence"]) != 1 or
                not isinstance(item["evidence"][0], dict) or
                item["evidence"][0].get("path") != DEFAULT_OUTPUT.relative_to(REPO).as_posix()):
            raise ValueError(f"Checked Wave A catalog binding changed: {requirement_id}")
        if output == published_output:
            if item["evidence"][0].get("sha256") != report_sha256:
                raise ValueError(f"Published Wave A evidence hash is stale: {requirement_id}")
        else:
            item["evidence"][0] = {"path": relative_output, "sha256": report_sha256}
    return copied


def _approved_output_path(value: Path) -> Path:
    output = value.resolve()
    default = DEFAULT_OUTPUT.resolve()
    work_root = WORK_OUTPUT_ROOT.resolve()
    if output != default and (not output.is_relative_to(work_root) or output.suffix != ".json"):
        raise ValueError(
            "Acceptance report output must be the published snapshot or a JSON file under work/"
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        output = _approved_output_path(args.output)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    report = replay(args.worker)
    content = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    report_digest = hashlib.sha256(content).hexdigest()
    requirements, operations = _load_requirements_and_operations()
    # A published snapshot must already have its digest approved in the checked
    # catalog. Fail before touching it when a different platform/build is used.
    if output == DEFAULT_OUTPUT.resolve():
        _requirements_for_replayed_report(requirements, output, report_digest)
    WORK_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="wave-a-acceptance-", suffix=".json", dir=WORK_OUTPUT_ROOT,
            delete=False,
        ) as staged:
            staged.write(content)
            staged.flush()
            os.fsync(staged.fileno())
            staging = Path(staged.name).resolve()
        replay_requirements = _requirements_for_replayed_report(
            requirements, staging, report_digest,
        )
        evaluated = evaluate_requirements(
            replay_requirements, operations, REPO,
            replay_worker=args.worker,
        )
        wave_rows = [
            row for row in evaluated["requirements"]
            if row["id"] in WAVE_A_REQUIREMENT_CASES
        ]
        if (len(wave_rows) != len(WAVE_A_REQUIREMENT_CASES) or
                any(row["status"] != "VALIDATED" for row in wave_rows)):
            details = {row["id"]: row["reasons"] for row in wave_rows}
            raise SystemExit(
                "Report replay passed, but checked-in catalog bindings are incomplete: " +
                json.dumps(details, ensure_ascii=False)
            )
        _require_unchanged(
            args.worker.resolve(strict=True), report["worker_sha256"], "Worker binary",
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, output)
        staging = None
    finally:
        if staging is not None and staging.is_file():
            staging.unlink()
    print(json.dumps({
        "status": "pass",
        "report": output.relative_to(REPO).as_posix(),
        "report_sha256": report_digest,
        "worker_sha256": report["worker_sha256"],
        "worker_manifest_sha256": report["worker_manifest_sha256"],
        "requirements_validated": len(wave_rows),
        "major_requirements_validated": evaluated["validated"],
        "major_requirements_required": evaluated["required"],
        "standalone_accepted": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
