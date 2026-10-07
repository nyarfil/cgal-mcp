"""Fixed replay harness for data-declared major-capability families.

Usage: master_family_replay_cases.py WORKER FAMILY

Runs every positive case of the family contract in
``scripts/master_replay_families.py`` against the native worker, derives each
mandatory validator request from the operation registry bindings, checks the
validator reports and behavioural assertions, and runs expected-rejection
negative controls. When ``CGAL_MASTER_ACCEPTANCE_TRACE`` is set, every exchange
is appended as a path-free record for the trusted replay runner, which re-checks
everything independently from the trace.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

if not __debug__:
    raise SystemExit("Family replay harness requires Python assertions")

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import master_replay_families as contracts  # noqa: E402

TRACE_PATH = os.environ.get("CGAL_MASTER_ACCEPTANCE_TRACE")


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portable(path: pathlib.Path, expected: str | None) -> tuple[str, dict]:
    content = path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    assert expected is None or actual == expected, (path.name, expected, actual)
    return actual, {"encoding": "base64", "byte_size": len(content),
                    "content": base64.b64encode(content).decode("ascii")}


def trace(request: dict, response: dict) -> tuple[dict, dict, dict[str, bytes]]:
    """Return the portable request/response and blob bytes; append when tracing."""
    blobs: dict[str, dict] = {}
    inputs = []
    for item in request["inputs"]:
        sha256, blob = portable(pathlib.Path(item["path"]), item["sha256"])
        blobs.setdefault(sha256, blob)
        inputs.append({k: v for k, v in item.items() if k != "path"} | {"blob_sha256": sha256})
    outputs = []
    for item in response.get("outputs", []):
        sha256, blob = portable(pathlib.Path(item["path"]), item.get("sha256"))
        blobs.setdefault(sha256, blob)
        outputs.append({k: v for k, v in item.items() if k != "path"} | {"blob_sha256": sha256})
    portable_request = {k: v for k, v in request.items() if k not in {"inputs", "output_dir"}}
    portable_request["inputs"] = inputs
    portable_response = {k: v for k, v in response.items() if k not in {"outputs", "diagnostics"}}
    portable_response["outputs"] = outputs
    if TRACE_PATH is not None:
        record = {
            "schema_version": 1, "case_id": request["request_id"],
            "operation_id": request["operation"],
            "request": portable_request,
            "request_sha256": contracts.canonical_hash(portable_request),
            "response": portable_response,
            "response_sha256": contracts.canonical_hash(portable_response),
            "blobs": blobs,
        }
        with pathlib.Path(TRACE_PATH).open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False) + "\n")
    return portable_request, portable_response, {
        sha: base64.b64decode(blob["content"]) for sha, blob in blobs.items()}


def run(worker: str, request: dict) -> dict:
    process = subprocess.run([worker], input=json.dumps(request) + "\n", text=True,
                             encoding="utf-8", capture_output=True, timeout=120)
    assert process.returncode == 0, (process.returncode, process.stderr)
    assert process.stderr == "", process.stderr
    lines = process.stdout.splitlines()
    assert len(lines) == 1, process.stdout
    response = json.loads(lines[0])
    assert response["protocol"] == 1 and response["request_id"] == request["request_id"], response
    return response


def request(case_id: str, operation: str, inputs: list[dict], parameters: dict,
            output_dir: pathlib.Path) -> dict:
    output_dir.mkdir()
    return {"protocol": 1, "request_id": case_id, "operation": operation, "inputs": inputs,
            "parameters": parameters, "output_dir": str(output_dir.resolve()),
            "kernel": "package_recommended",
            "limits": {"wall_time_ms": 120000, "memory_mb": 2048}}


def fixture_artifact(index: int, item: dict) -> dict:
    path = REPO / contracts.FIXTURE_ROOT / item["fixture"]
    assert digest(path) == item["sha256"], item["fixture"]
    return {"artifact_id": f"input-{index}", "type": item["type"], "unit": item["unit"],
            "format": item["format"], "path": str(path.resolve()), "sha256": item["sha256"]}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: master_family_replay_cases.py WORKER FAMILY")
    worker = str(pathlib.Path(sys.argv[1]).resolve())
    family = contracts.GENERIC_FAMILIES[sys.argv[2]]
    registry = contracts.registry_index(json.loads(
        (REPO / "cgal_mcp/master/operations.json").read_text(encoding="utf-8"))["operations"])
    outputs_by_case: dict[str, list[str]] = {}
    validator_passes = 0
    with tempfile.TemporaryDirectory(prefix="cgal-family-replay-") as directory:
        root = pathlib.Path(directory)
        for case in family["cases"]:
            operation = registry[case["operation"]]
            assert operation["status"] == "VALIDATED", case["operation"]
            inputs = [fixture_artifact(index, item) for index, item in enumerate(case["inputs"])]
            transform_request = request(case["id"], case["operation"], inputs, case["parameters"],
                                        root / case["id"])
            response = run(worker, transform_request)
            assert response["status"] == "ok", (case["id"], response)
            portable_request, portable_response, content = trace(transform_request, response)
            view = contracts.CaseView(operation, portable_request, portable_response, content)
            failures = contracts.assertion_failures(case, view)
            assert not failures, failures
            outputs_by_slot = {item["slot"]: item for item in response["outputs"]}
            inputs_by_slot = {slot["slot"]: item for slot, item in
                              zip(operation["io"]["inputs"], inputs)}
            for validator_id in contracts.mandatory_validators(operation):
                validator = registry[validator_id]
                plan, parameters = contracts.derive_validator_plan(
                    operation, validator, case["parameters"])
                validator_inputs = []
                for position, (kind, slot) in enumerate(plan):
                    if kind == "input":
                        validator_inputs.append(inputs_by_slot[slot])
                    else:
                        produced = outputs_by_slot[slot]
                        path = pathlib.Path(produced["path"])
                        validator_inputs.append({
                            "artifact_id": f"{case['id']}-{slot}-{position}",
                            "type": produced["type"], "unit": produced["unit"],
                            "format": produced["format"], "path": str(path.resolve()),
                            "sha256": digest(path)})
                validator_request = request(f"{case['id']}--{validator_id}", validator_id,
                                            validator_inputs, parameters,
                                            root / f"{case['id']}--{validator_id}")
                validator_response = run(worker, validator_request)
                assert validator_response["status"] == "ok", (case["id"], validator_response)
                trace(validator_request, validator_response)
                reports = [item for item in validator_response["outputs"]
                           if item["slot"] == "validation"]
                assert len(reports) == 1 and len(validator_response["outputs"]) == 1, validator_response
                report = json.loads(pathlib.Path(reports[0]["path"]).read_text(encoding="utf-8"))
                failed = contracts.validator_report_failures(validator, report, case["operation"])
                assert not failed, (case["id"], validator_id, failed)
                validator_passes += 1
            outputs_by_case[case["id"]] = [item["blob_sha256"] for item in portable_response["outputs"]]
        for pair in family["pairs"]:
            first, second = (outputs_by_case[case_id] for case_id in pair["cases"])
            assert (first == second) == (pair["kind"] == "equal_outputs"), pair
        for control in family["negative_controls"]:
            inputs = [fixture_artifact(index, item) for index, item in enumerate(control["inputs"])]
            control_request = request(control["id"], control["operation"], inputs,
                                      control["parameters"], root / control["id"])
            response = run(worker, control_request)
            assert response["status"] == "error", (control["id"], response)
            assert response["error"]["class"] == control["expect_error_class"], response
            assert response.get("outputs", []) == [], response
            trace(control_request, response)
    print(f"Family {family['family']} replay: {len(family['cases'])} cases, "
          f"{validator_passes} mandatory validator passes, "
          f"{len(family['negative_controls'])} negative controls: PASS")


if __name__ == "__main__":
    main()
