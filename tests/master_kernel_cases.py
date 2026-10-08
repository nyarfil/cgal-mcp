"""Real CGAL 6.2.1 geometry-kernel family (7.1) production-worker cases.

Usage: python tests/master_kernel_cases.py <cgal-master-worker>
Every transform report is checked by its independent GMP-rational validator, and
tampered reports, degenerate inputs and disallowed kernels must fail closed.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "master" / "kernel"
WORKER = sys.argv[1]
ALL_KERNELS = ["simple_cartesian_double", "cartesian_double", "epick", "epeck"]
EXACT_PREDICATE_KERNELS = ["epick", "epeck"]
TRANSFORMS = {
    "kernel.primitives.construct": ("kernel.validate.primitives_report", ALL_KERNELS),
    "kernel.predicates.evaluate": ("kernel.validate.predicates_report", ALL_KERNELS),
    "kernel.intersections.compute": ("kernel.validate.intersections_report", EXACT_PREDICATE_KERNELS),
    "kernel.distance.squared": ("kernel.validate.distances_report", ALL_KERNELS),
}
COUNTER = [0]


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: pathlib.Path, type_: str, unit: str = "mm") -> dict:
    return {"artifact_id": path.stem, "type": type_, "unit": unit, "format": "json",
            "path": str(path.resolve()), "sha256": sha256(path)}


def invoke(scratch: pathlib.Path, operation: str, inputs: list[dict], parameters: dict) -> dict:
    COUNTER[0] += 1
    output = scratch / f"run{COUNTER[0]:03d}"
    output.mkdir()
    request = {"protocol": 1, "request_id": f"kernel-{COUNTER[0]}", "operation": operation,
               "inputs": inputs, "parameters": parameters, "output_dir": str(output.resolve()),
               "kernel": "package_recommended", "limits": {"wall_time_ms": 120000, "memory_mb": 2048}}
    process = subprocess.run([WORKER], input=json.dumps(request) + "\n", text=True, encoding="utf-8",
                             capture_output=True, timeout=120)
    assert process.returncode == 0, process.stderr
    assert process.stderr == "", process.stderr
    lines = process.stdout.splitlines()
    assert len(lines) == 1, process.stdout
    result = json.loads(lines[0])
    assert result["request_id"] == request["request_id"], result
    return result


def ok(result: dict) -> pathlib.Path:
    assert result["status"] == "ok", result
    path = pathlib.Path(result["outputs"][0]["path"])
    assert path.is_file(), result
    return path


def error(result: dict, code: str, error_class: str) -> None:
    assert result["status"] == "error", result
    assert result["error"]["code"] == code, result
    assert result["error"]["class"] == error_class, result


def run_pair(scratch: pathlib.Path, transform: str, source: dict, kernel: str) -> dict:
    validator = TRANSFORMS[transform][0]
    report_path = ok(invoke(scratch, transform, [source], {"kernel": kernel}))
    candidate = artifact(report_path, "KernelReport", "none")
    validation = json.loads(ok(invoke(scratch, validator, [candidate, source], {"kernel": kernel}))
                            .read_text("utf-8"))
    assert validation["status"] == "pass" and validation["passed"] is True, validation
    assert validation["validator"] == validator, validation
    assert validation["checks"] and all(validation["checks"].values()), validation
    return json.loads(report_path.read_text("utf-8"))


def results(report: dict) -> list:
    return [query["result"] for query in report["results"]["queries"]]


def main() -> None:
    manifest = json.loads(subprocess.run([WORKER, "--manifest"], text=True, encoding="utf-8",
                                         capture_output=True, timeout=30, check=True).stdout)
    operations = {operation["id"]: operation for operation in manifest["operations"]}
    for transform, (validator, kernels) in TRANSFORMS.items():
        for operation_id in (transform, validator):
            entry = operations[operation_id]
            assert entry["revision"] == 1 and entry["supported_kernels"] == ["package_recommended"], entry
            assert entry["effective_kernel"] == "selected_by_parameter:kernel", entry
        assert operations[transform]["info"]["validators"] == [validator], transform
        assert operations[transform]["info"]["kernels"] == kernels, transform
        assert operations[transform]["info"]["validator_parameter_bindings"] == {validator: {"kernel": "kernel"}}
        assert operations[validator]["role"] == "validator", validator

    sources = {name: artifact(FIXTURES / f"{name}.json", "KernelQuerySet")
               for name in ("primitives", "predicates", "robustness", "intersections", "distances",
                            "collinear_circumcenter", "unsupported_pair")}
    plan = [("kernel.primitives.construct", "primitives"), ("kernel.predicates.evaluate", "predicates"),
            ("kernel.predicates.evaluate", "robustness"), ("kernel.intersections.compute", "intersections"),
            ("kernel.distance.squared", "distances")]
    with tempfile.TemporaryDirectory(prefix="cgal-kernel-cases-") as directory:
        scratch = pathlib.Path(directory)
        reports: dict[tuple[str, str], dict] = {}
        for transform, name in plan:
            for kernel in TRANSFORMS[transform][1]:
                reports[(name, kernel)] = run_pair(scratch, transform, sources[name], kernel)

        # 7.1.01: the floating-point kernels get the near-degenerate orientation wrong; EPICK/EPECK do not.
        third = "6004799503160661/18014398509481984"
        for kernel in ALL_KERNELS:
            exact = kernel in EXACT_PREDICATE_KERNELS
            expected_third = "1/3" if kernel == "epeck" else third
            assert results(reports[("robustness", kernel)]) == [
                "left_turn" if exact else "right_turn", exact, [expected_third, expected_third]], kernel

        epeck = results(reports[("predicates", "epeck")])
        assert epeck[:6] == ["left_turn", "right_turn", "collinear", "positive", "negative", "coplanar"]
        assert epeck[14:] == [["2", "0"], ["0", "0", "1"], ["4/3", "4/3"], ["1/2", "1/2", "1/2"],
                              ["2", "2"], ["1", "1", "0"], ["1", "1", "1"]]
        primitives = reports[("primitives", "epeck")]["results"]["primitives"]
        assert len(primitives) == 20 and primitives[16]["signed_volume"] == "1/6"
        types = [result["type"] for result in results(reports[("intersections", "epeck")])
                 if isinstance(result, dict)]
        assert {"point", "segment", "line", "plane", "triangle", "polygon", "empty"} <= set(types), types
        assert results(reports[("distances", "epeck")])[11] == "18"

        # Fail-closed preconditions and kernel policy.
        error(invoke(scratch, "kernel.predicates.evaluate", [sources["collinear_circumcenter"]],
                     {"kernel": "epeck"}), "DEGENERATE_CONFIGURATION", "PRECONDITION_FAILED")
        error(invoke(scratch, "kernel.intersections.compute", [sources["unsupported_pair"]],
                     {"kernel": "epeck"}), "UNSUPPORTED_PRIMITIVE_PAIR", "PRECONDITION_FAILED")
        error(invoke(scratch, "kernel.intersections.compute", [sources["intersections"]],
                     {"kernel": "cartesian_double"}), "INVALID_PARAMETER", "INVALID_REQUEST")
        error(invoke(scratch, "kernel.distance.squared", [sources["distances"]], {}),
              "MISSING_PARAMETER", "INVALID_REQUEST")

        # Tampered reports are rejected by the independent validators.
        tampered = [
            ("kernel.validate.primitives_report", "primitives", "epeck", "CONSTRUCTION_MISMATCH"),
            ("kernel.validate.predicates_report", "predicates", "epeck", "CONSTRUCTION_MISMATCH"),
            ("kernel.validate.predicates_report", "robustness", "epick", "PREDICATE_MISMATCH"),
            ("kernel.validate.intersections_report", "intersections", "epeck", "INTERSECTION_MISMATCH"),
            ("kernel.validate.distances_report", "distances", "epeck", "CONSTRUCTION_MISMATCH"),
        ]
        for validator, name, kernel, code in tampered:
            bad = artifact(FIXTURES / f"tampered_{name}_report.json", "KernelReport", "none")
            error(invoke(scratch, validator, [bad, sources[name]], {"kernel": kernel}), code, "VALIDATION_FAILED")

        # A correct report presented under another kernel, or against another source, is rejected.
        epick_report = scratch / "epick_robustness.json"
        epick_report.write_text(json.dumps(reports[("robustness", "epick")]) + "\n", encoding="utf-8")
        candidate = artifact(epick_report, "KernelReport", "none")
        error(invoke(scratch, "kernel.validate.predicates_report", [candidate, sources["robustness"]],
                     {"kernel": "epeck"}), "KERNEL_MISMATCH", "VALIDATION_FAILED")
        error(invoke(scratch, "kernel.validate.predicates_report", [candidate, sources["predicates"]],
                     {"kernel": "epick"}), "SOURCE_MISMATCH", "VALIDATION_FAILED")
        # A double-kernel report that claims the floating-point answer is accepted only as ill-conditioned.
        sc_report = scratch / "sc_robustness.json"
        sc_report.write_text(json.dumps(reports[("robustness", "simple_cartesian_double")]) + "\n",
                             encoding="utf-8")
        validation = json.loads(ok(invoke(
            scratch, "kernel.validate.predicates_report",
            [artifact(sc_report, "KernelReport", "none"), sources["robustness"]],
            {"kernel": "simple_cartesian_double"})).read_text("utf-8"))
        assert validation["ill_conditioned_predicates"] == 2, validation
    print("PASS master geometry kernel (7.1) worker cases")


if __name__ == "__main__":
    main()
