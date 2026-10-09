"""Real CGAL 6.2.1 optimization / numerical-geometry family (7.15) production-worker cases.

Usage: python tests/master_optimization_cases.py <cgal-master-worker>
Every transform report is checked by its independent validator (QP certificates in
exact rationals, exact Voronoi-area natural-neighbour coordinates, recomputed VSA
proxies/errors, exhaustive p-center candidates); tampered reports, degenerate
inputs and unsupported parameters must fail closed.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
from fractions import Fraction


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "master" / "optimization"
WORKER = sys.argv[1]
TRANSFORMS = {
    "optimization.quadratic_program": "optimization.validate.quadratic_program",
    "optimization.interpolate": "optimization.validate.interpolation",
    "optimization.approximate_mesh": "optimization.validate.mesh_approximation",
    "optimization.matrix_search": "optimization.validate.matrix_search",
}
COUNTER = [0]


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(name: str, type_: str, unit: str = "mm", path: pathlib.Path | None = None) -> dict:
    path = path or FIXTURES / name
    return {"artifact_id": path.stem, "type": type_, "unit": unit,
            "format": "off" if path.suffix == ".off" else "json",
            "path": str(path.resolve()), "sha256": sha256(path)}


def invoke(scratch: pathlib.Path, operation: str, inputs: list[dict], parameters: dict) -> dict:
    COUNTER[0] += 1
    output = scratch / f"run{COUNTER[0]:03d}"
    output.mkdir()
    request = {"protocol": 1, "request_id": f"optimization-{COUNTER[0]}", "operation": operation,
               "inputs": inputs, "parameters": parameters, "output_dir": str(output.resolve()),
               "kernel": "package_recommended", "limits": {"wall_time_ms": 120000, "memory_mb": 2048}}
    process = subprocess.run([WORKER], input=json.dumps(request) + "\n", text=True, encoding="utf-8",
                             capture_output=True, timeout=300)
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


def run_pair(scratch: pathlib.Path, transform: str, source: dict, parameters: dict) -> tuple[dict, pathlib.Path]:
    validator = TRANSFORMS[transform]
    report_path = ok(invoke(scratch, transform, [source], parameters))
    candidate = artifact("", "OptimizationReport", "none", report_path)
    validation = json.loads(ok(invoke(scratch, validator, [candidate, source], parameters)).read_text("utf-8"))
    assert validation["status"] == "pass" and validation["passed"] is True, validation
    assert validation["validator"] == validator, validation
    assert validation["checks"] and all(validation["checks"].values()), validation
    return json.loads(report_path.read_text("utf-8")), report_path


def tamper(scratch: pathlib.Path, report_path: pathlib.Path, mutate) -> dict:
    report = json.loads(report_path.read_text("utf-8"))
    mutate(report["results"])
    path = scratch / f"tampered{COUNTER[0]}.json"
    path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    return artifact("", "OptimizationReport", "none", path)


def main() -> None:
    manifest = json.loads(subprocess.run([WORKER, "--manifest"], text=True, encoding="utf-8",
                                         capture_output=True, timeout=30, check=True).stdout)
    operations = {operation["id"]: operation for operation in manifest["operations"]}
    for transform, validator in TRANSFORMS.items():
        assert operations[transform]["revision"] == 1, transform
        assert operations[transform]["info"]["validators"] == [validator], transform
        assert operations[validator]["role"] == "validator", validator

    qp = {name: artifact(f"{name}.json", "QuadraticProgram", "none")
          for name in ("lp_optimal", "lp_infeasible", "lp_unbounded", "qp_optimal", "qp_unbounded", "qp_nonconvex")}
    linear_field = artifact("interp_linear_field.json", "InterpolationData2")
    spherical_field = artifact("interp_spherical_field.json", "InterpolationData2")
    line = artifact("line_points.json", "PointSet1")
    cube = artifact("cube_subdivided.off", "TriangleSurfaceMesh")
    with tempfile.TemporaryDirectory(prefix="cgal-optimization-cases-") as directory:
        scratch = pathlib.Path(directory)
        # 7.15.01 QP_solver: optimal / infeasible / unbounded LPs and QPs with certificates.
        lp, lp_path = run_pair(scratch, "optimization.quadratic_program", qp["lp_optimal"], {"solver": "linear"})
        assert lp["results"]["status"] == "optimal", lp
        assert lp["results"]["variable_values"] == ["8/5", "6/5", "8/5"], lp
        assert lp["results"]["objective_value"] == "-14/5", lp
        infeasible, _ = run_pair(scratch, "optimization.quadratic_program", qp["lp_infeasible"], {"solver": "linear"})
        assert infeasible["results"]["status"] == "infeasible", infeasible
        unbounded, _ = run_pair(scratch, "optimization.quadratic_program", qp["lp_unbounded"], {"solver": "linear"})
        assert unbounded["results"]["status"] == "unbounded", unbounded
        quadratic, _ = run_pair(scratch, "optimization.quadratic_program", qp["qp_optimal"], {"solver": "quadratic"})
        assert quadratic["results"]["variable_values"] == ["2", "3"], quadratic
        assert quadratic["results"]["objective_value"] == "8", quadratic
        qp_unbounded, _ = run_pair(scratch, "optimization.quadratic_program", qp["qp_unbounded"],
                                   {"solver": "quadratic"})
        assert qp_unbounded["results"]["status"] == "unbounded", qp_unbounded
        error(invoke(scratch, "optimization.quadratic_program", [qp["qp_nonconvex"]], {"solver": "quadratic"}),
              "NOT_POSITIVE_SEMIDEFINITE", "PRECONDITION_FAILED")
        error(invoke(scratch, "optimization.quadratic_program", [qp["qp_optimal"]], {"solver": "linear"}),
              "NONZERO_QUADRATIC_TERM", "PRECONDITION_FAILED")
        bad = tamper(scratch, lp_path, lambda r: r.__setitem__("objective_value", "-3"))
        error(invoke(scratch, "optimization.validate.quadratic_program", [bad, qp["lp_optimal"]], {"solver": "linear"}),
              "OBJECTIVE_MISMATCH", "VALIDATION_FAILED")
        bad = tamper(scratch, lp_path, lambda r: r["certificate"].__setitem__("values", ["0", "0", "0", "0"]))
        error(invoke(scratch, "optimization.validate.quadratic_program", [bad, qp["lp_optimal"]], {"solver": "linear"}),
              "CERTIFICATE_INVALID", "VALIDATION_FAILED")

        # 7.15.02 Interpolation: exact linear precision and Sibson C1 spherical-quadratic precision.
        linear, linear_path = run_pair(scratch, "optimization.interpolate", linear_field, {"method": "linear"})
        assert [q["value"] for q in linear["results"]["queries"]] == ["51/10", "1", "32/5", "10", "25/4"], linear
        sibson, _ = run_pair(scratch, "optimization.interpolate", spherical_field, {"method": "sibson_c1"})
        expected = [2.062, 0.10555555555555556, 4.502, 5.45, 3.0375]
        values = [float(Fraction(q["value"])) for q in sibson["results"]["queries"]]
        assert all(abs(a - b) < 1e-9 for a, b in zip(values, expected)), values
        linear_on_quadratic, _ = run_pair(scratch, "optimization.interpolate", spherical_field, {"method": "linear"})
        assert [q["value"] for q in linear_on_quadratic["results"]["queries"]][4] == "243/80", linear_on_quadratic
        error(invoke(scratch, "optimization.interpolate", [artifact("interp_query_outside.json", "InterpolationData2")],
                     {"method": "linear"}), "QUERY_OUTSIDE_HULL", "PRECONDITION_FAILED")
        error(invoke(scratch, "optimization.interpolate", [artifact("interp_collinear_sites.json", "InterpolationData2")],
                     {"method": "linear"}), "DEGENERATE_SITES", "PRECONDITION_FAILED")
        bad = tamper(scratch, linear_path, lambda r: r["queries"][0].__setitem__("value", "5"))
        error(invoke(scratch, "optimization.validate.interpolation", [bad, linear_field], {"method": "linear"}),
              "INTERPOLATION_MISMATCH", "VALIDATION_FAILED")

        # 7.15.03 Surface_mesh_approximation: 12 hierarchical proxies fit the cube planes with zero
        # L21 error; 3 incremental proxies cannot (validator recomputes partition, proxies, error).
        fine_parameters = {"max_number_of_proxies": 12, "number_of_iterations": 20, "seeding": "hierarchical"}
        six, six_path = run_pair(scratch, "optimization.approximate_mesh", cube, fine_parameters)
        assert six["results"]["proxy_count"] == 12 and six["results"]["is_manifold"] is True, six
        assert six["results"]["l21_error"]["value"] < 1e-12 and six["results"]["l21_error"]["unit"] == "mm2", six
        three, _ = run_pair(scratch, "optimization.approximate_mesh", cube,
                            {"max_number_of_proxies": 3, "number_of_iterations": 20, "seeding": "incremental"})
        assert three["results"]["proxy_count"] == 3 and three["results"]["l21_error"]["value"] > 1.0, three
        error(invoke(scratch, "optimization.approximate_mesh", [cube],
                     {"max_number_of_proxies": 49, "number_of_iterations": 5, "seeding": "hierarchical"}),
              "TOO_MANY_PROXIES", "PRECONDITION_FAILED")
        bad = tamper(scratch, six_path, lambda r: r["proxies"][0].__setitem__(0, 0.5))
        error(invoke(scratch, "optimization.validate.mesh_approximation", [bad, cube], fine_parameters),
              "PROXY_MISMATCH", "VALIDATION_FAILED")

        # 7.15.04 Matrix_search: interval p-center by sorted_matrix_search.
        three_centers, p3_path = run_pair(scratch, "optimization.matrix_search", line, {"centers": 3})
        assert three_centers["results"]["optimal_diameter"] == "9", three_centers
        four_centers, _ = run_pair(scratch, "optimization.matrix_search", line, {"centers": 4})
        assert four_centers["results"]["optimal_radius"] == "7/2", four_centers
        error(invoke(scratch, "optimization.matrix_search", [line], {"centers": 12}), "TRIVIAL_CENTER_COUNT",
              "PRECONDITION_FAILED")
        bad = tamper(scratch, p3_path, lambda r: (r.__setitem__("optimal_diameter", "8"),
                                                  r.__setitem__("optimal_radius", "4")))
        error(invoke(scratch, "optimization.validate.matrix_search", [bad, line], {"centers": 3}),
              "OPTIMUM_MISMATCH", "VALIDATION_FAILED")
        if "--dump" in sys.argv:
            for name, report in (("lp", lp), ("infeasible", infeasible), ("unbounded", unbounded),
                                 ("qp", quadratic), ("qp_unbounded", qp_unbounded), ("linear", linear),
                                 ("sibson", sibson), ("six", six), ("three", three), ("p3", three_centers)):
                print(name, json.dumps(report["results"])[:600])
    print("PASS master optimization (7.15) worker cases")


if __name__ == "__main__":
    main()
