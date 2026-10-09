"""Real CGAL 6.2.1 surface reconstruction family (7.10) production-worker cases.

Usage: python tests/master_reconstruction_cases.py <cgal-master-worker>
Every reconstruction is checked by its independent validator (own OFF/PLY/XYZ
parsers and combinatorics, exact GMP rational point-triangle distances, exact
signed volume, exact axis-ray enclosure parity, certified triangle cover
bounds); degenerate inputs, tampered candidates and unsupported parameters
must fail closed. Inputs are fixed analytic samplings (no randomness).
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "master" / "reconstruction"
WORKER = sys.argv[1]
TRANSFORMS = {
    "reconstruction.poisson": "reconstruction.validate.poisson",
    "reconstruction.advancing_front": "reconstruction.validate.interpolating",
    "reconstruction.scale_space": "reconstruction.validate.interpolating",
    "reconstruction.alpha_wrap": "reconstruction.validate.alpha_wrap",
}
FORMATS = {".off": "off", ".xyz": "xyz", ".ply": "ply"}
COUNTER = [0]


def mm(value: float) -> dict:
    return {"value": value, "unit": "mm"}


def artifact(name: str, type_: str, path: pathlib.Path | None = None) -> dict:
    path = path or FIXTURES / name
    return {"artifact_id": path.stem, "type": type_, "unit": "mm", "format": FORMATS[path.suffix],
            "path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def invoke(scratch: pathlib.Path, operation: str, inputs: list[dict], parameters: dict) -> dict:
    COUNTER[0] += 1
    output = scratch / f"run{COUNTER[0]:03d}"
    output.mkdir()
    request = {"protocol": 1, "request_id": f"reconstruction-{COUNTER[0]}", "operation": operation,
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


def run_pair(scratch: pathlib.Path, transform: str, source: dict, parameters: dict) -> tuple[dict, dict]:
    result = invoke(scratch, transform, [source], parameters)
    mesh_path = ok(result)
    candidate = artifact("", "TriangleSurfaceMesh", mesh_path)
    validation = invoke(scratch, TRANSFORMS[transform], [candidate, source], parameters)
    report = json.loads(ok(validation).read_text("utf-8"))
    assert report["status"] == "pass" and report["passed"] is True, report
    assert all(value is True for value in report["checks"].values()), report
    return result["metrics"], report


POISSON_SPHERE = {"sm_angle": 20, "sm_radius": 2, "sm_distance": 0.375, "max_deviation": mm(3.0)}
POISSON_TORUS = {"sm_angle": 20, "sm_radius": 2, "sm_distance": 0.375, "max_deviation": mm(4.0)}
POISSON_TORUS_FINE = {"sm_angle": 20, "sm_radius": 1.5, "sm_distance": 0.25, "max_deviation": mm(4.0)}
AFSR = {"radius_ratio_bound": 5, "beta": 0.52, "max_deviation": mm(2.0)}
SCALE_SPACE = {"iterations": 2, "neighbors": 12, "maximum_facet_length": mm(5.0), "radius_ratio_bound": 5,
               "beta": 0.52, "max_deviation": mm(2.0)}
NOISY_SCALE_SPACE = dict(SCALE_SPACE, iterations=4)
WRAP_SPHERE = {"alpha": mm(3.0), "offset": mm(0.5)}
WRAP_TORUS_FINE = {"alpha": mm(2.5), "offset": mm(0.5)}
WRAP_TORUS_COARSE = {"alpha": mm(15.0), "offset": mm(0.5)}


def main() -> None:
    sphere_dense = artifact("sphere_dense_normals.ply", "PointSet3Normals")
    torus_normals = artifact("torus_normals.ply", "PointSet3Normals")
    sphere = artifact("sphere_points.xyz", "PointSet3")
    torus = artifact("torus_points.xyz", "PointSet3")
    with tempfile.TemporaryDirectory() as directory:
        scratch = pathlib.Path(directory)
        metrics, report = run_pair(scratch, "reconstruction.poisson", sphere_dense, POISSON_SPHERE)
        assert metrics["euler_characteristic"] == 2 and metrics["boundary_edge_count"] == 0, metrics
        assert report["topology"]["genus"] == 0, report
        metrics, report = run_pair(scratch, "reconstruction.poisson", torus_normals, POISSON_TORUS)
        assert metrics["euler_characteristic"] == 0 and report["topology"]["genus"] == 1, report
        fine, _ = run_pair(scratch, "reconstruction.poisson", torus_normals, POISSON_TORUS_FINE)
        for transform, parameters in (("reconstruction.advancing_front", AFSR),
                                      ("reconstruction.scale_space", SCALE_SPACE)):
            metrics, report = run_pair(scratch, transform, sphere, parameters)
            assert metrics["euler_characteristic"] == 2 and metrics["vertex_count"] == 320, metrics
            assert report["closed"] is True and report["unused_source_point_count"] == 0, report
        noisy = artifact("noisy_sphere_points.xyz", "PointSet3")
        plain, _ = run_pair(scratch, "reconstruction.advancing_front", noisy, AFSR)
        smoothed, _ = run_pair(scratch, "reconstruction.scale_space", noisy, NOISY_SCALE_SPACE)
        assert plain["euler_characteristic"] == smoothed["euler_characteristic"] == 2, (plain, smoothed)
        metrics, report = run_pair(scratch, "reconstruction.advancing_front", torus, AFSR)
        assert metrics["euler_characteristic"] == 0 and report["topology"]["genus"] == 1, report
        metrics, report = run_pair(scratch, "reconstruction.alpha_wrap", sphere, WRAP_SPHERE)
        assert metrics["euler_characteristic"] == 2, metrics
        metrics, report = run_pair(scratch, "reconstruction.alpha_wrap", torus, WRAP_TORUS_FINE)
        assert report["topology"]["genus"] == 1, report
        metrics, report = run_pair(scratch, "reconstruction.alpha_wrap", torus, WRAP_TORUS_COARSE)
        assert report["topology"]["genus"] == 0, report

        # Degenerate inputs and unsupported parameters fail closed.
        error(invoke(scratch, "reconstruction.poisson", [artifact("sphere_zero_normal.ply", "PointSet3Normals")],
                     POISSON_SPHERE), "ZERO_NORMAL", "PRECONDITION_FAILED")
        error(invoke(scratch, "reconstruction.advancing_front", [artifact("plane_points.xyz", "PointSet3")], AFSR),
              "DEGENERATE_POINT_SET", "PRECONDITION_FAILED")
        error(invoke(scratch, "reconstruction.alpha_wrap", [torus], {"alpha": mm(0.1), "offset": mm(0.5)}),
              "MESH_SIZE_LIMIT_EXCEEDED", "RESOURCE_LIMIT")
        error(invoke(scratch, "reconstruction.poisson", [sphere], POISSON_SPHERE),
              "INPUT_TYPE_MISMATCH", "TYPE_ERROR")

        # Tampered candidates are rejected by the independent validators.
        tampered = [
            ("reconstruction.validate.poisson", "tampered_poisson_flipped.off", sphere_dense, POISSON_SPHERE,
             "ORIENTATION_NOT_OUTWARD"),
            ("reconstruction.validate.poisson", "tampered_poisson_shrunk.off", sphere_dense, POISSON_SPHERE,
             "SOURCE_TO_SURFACE_BOUND_EXCEEDED"),
            ("reconstruction.validate.interpolating", "tampered_afsr_moved_vertex.off", sphere, AFSR,
             "VERTEX_NOT_SOURCE_POINT"),
            ("reconstruction.validate.interpolating", "tampered_afsr_flipped_face.off", sphere, AFSR,
             "INCONSISTENT_ORIENTATION"),
            ("reconstruction.validate.alpha_wrap", "tampered_wrap_shrunk.off", sphere, WRAP_SPHERE,
             "SOURCE_NOT_ENCLOSED"),
            ("reconstruction.validate.alpha_wrap", "tampered_wrap_grown.off", sphere, WRAP_SPHERE,
             "SURFACE_TO_SOURCE_BOUND_EXCEEDED"),
            ("reconstruction.validate.alpha_wrap", "tampered_wrap_vertex_inside.off", sphere, WRAP_SPHERE,
             "VERTEX_INSIDE_OFFSET_BAND"),
        ]
        for validator, name, source, parameters, code in tampered:
            error(invoke(scratch, validator, [artifact(name, "TriangleSurfaceMesh"), source], parameters),
                  code, "VALIDATION_FAILED")
    print(f"reconstruction cases passed ({COUNTER[0]} worker requests)")


if __name__ == "__main__":
    main()
