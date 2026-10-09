"""Real CGAL 6.2.1 batch-6 production-worker cases (7.9.05 OpenGR registration, 7.10.01 Poisson with boundary,
7.10.02 polygonal and kinetic surface reconstruction).

Usage: python tests/master_batch6_cases.py <cgal-master-worker>
Every producer result is checked by its independent validator against hand-derived values; tampered candidates
and invalid parameters must fail closed. Registration and PolyFit need the optional OpenGR / SCIP libraries and
are skipped (with a message) when the worker was built without them.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile

import master_query_cases as q
from master_batch2_cases import art, reject

ROOT = q.ROOT
B6 = ROOT / "tests" / "fixtures" / "master" / "batch6"
RC = ROOT / "tests" / "fixtures" / "master" / "reconstruction"

MM = lambda value: {"value": value, "unit": "mm"}
REG = {"number_of_samples": 200, "accuracy": MM(0.1), "overlap": 0.7, "maximum_running_time": 30,
       "max_rms": MM(0.05), "inlier_distance": MM(0.1), "min_inlier_fraction": 0.9}
REG_BOUNDS = {key: REG[key] for key in ("max_rms", "inlier_distance", "min_inlier_fraction")}
POLYFIT = {"sphere_radius": MM(2.0), "maximum_distance": MM(0.2), "maximum_angle": 10.0, "minimum_region_size": 20,
           "fitting": 0.43, "coverage": 0.27, "complexity": 0.3, "max_deviation": MM(0.5), "planarity_tolerance": MM(1e-6)}
KINETIC = {"k_neighbors": 12, "maximum_distance": MM(0.2), "maximum_angle": 10.0, "minimum_region_size": 20,
           "angle_tolerance": 5.0, "maximum_offset": MM(0.5), "regularize_parallelism": True,
           "regularize_orthogonality": True, "regularize_coplanarity": True, "regularize_axis_symmetry": False,
           "partition_depth": 2, "lambda": 0.5, "max_deviation": MM(0.5), "planarity_tolerance": MM(1e-6)}
SOUP_BOUNDS = {"max_deviation": MM(0.5), "planarity_tolerance": MM(1e-6)}
POISSON_DELAUNAY = {"sm_angle": 20, "sm_radius": 2, "sm_distance": 0.375, "max_deviation": MM(3.0),
                    "max_circumradius": MM(6.0), "min_coverage": 0.5}


def points(path):
    return art(path, "PointSet3")


def normals(path):
    item = art(path, "PointSet3Normals")
    item["format"] = "ply"
    return item


def report(path):
    return art(path, "GeometryQueryReport", "none")


def validated(scratch, validator, inputs, parameters):
    verdict = json.loads(q.ok(q.invoke(scratch, validator, inputs, parameters)).read_text("utf-8"))
    assert verdict["status"] == "pass" and verdict["passed"] is True, verdict
    assert verdict["validator"] == validator and verdict["checks"] and all(verdict["checks"].values()), verdict
    return verdict


def registration_cases(operations) -> None:
    if not operations["pointset.registration.register"]["info"].get("optional_dependency_built"):
        print("OpenGR not built: registration cases skipped")
        return
    reference, moving = points(B6 / "reg_reference.xyz"), points(B6 / "reg_moving.xyz")
    with tempfile.TemporaryDirectory() as raw:
        scratch = pathlib.Path(raw)
        first = q.ok(q.invoke(scratch, "pointset.registration.compute_transformation", [reference, moving], REG))
        again = q.ok(q.invoke(scratch, "pointset.registration.compute_transformation", [reference, moving], REG))
        one, two = json.loads(first.read_text("utf-8")), json.loads(again.read_text("utf-8"))
        assert one["results"]["transformation_row_major_3x4"] == two["results"]["transformation_row_major_3x4"], "not stable"
        expected = [0.8, 0.6, 0.0, 0.0, -0.36, 0.48, 0.8, 0.9, 0.48, -0.64, 0.6, -2.45]
        assert all(abs(a - b) < 1e-9 for a, b in zip(one["results"]["transformation_row_major_3x4"], expected)), one
        validated(scratch, "pointset.validate.registration_transformation", [report(first), reference, moving], REG_BOUNDS)
        registered = q.ok(q.invoke(scratch, "pointset.registration.register", [reference, moving], REG))
        validated(scratch, "pointset.validate.registered_points", [points(registered), reference, moving], REG_BOUNDS)
        noisy = points(B6 / "reg_moving_noisy.xyz")
        noisy_report = q.ok(q.invoke(scratch, "pointset.registration.compute_transformation", [reference, noisy],
                                     {**REG, "max_rms": MM(0.1)}))
        validated(scratch, "pointset.validate.registration_transformation", [report(noisy_report), reference, noisy],
                  {**REG_BOUNDS, "max_rms": MM(0.1)})
        reject(scratch, "pointset.validate.registration_transformation",
               [report(B6 / "tampered_registration_translation.json"), reference, moving], REG_BOUNDS,
               "RESIDUAL_RMS_EXCEEDED")
        reject(scratch, "pointset.validate.registered_points",
               [points(B6 / "tampered_registered_point_moved.xyz"), reference, moving], REG_BOUNDS,
               "NOT_A_RIGID_IMAGE")
        reject(scratch, "pointset.registration.compute_transformation", [reference, points(B6 / "reg_flat.xyz")], REG,
               "DEGENERATE_POINT_SET", "PRECONDITION_FAILED")
        reject(scratch, "pointset.registration.compute_transformation", [reference, moving],
               {**REG, "overlap": 1.5}, "INVALID_PARAMETER", "INVALID_REQUEST")
        reject(scratch, "pointset.registration.compute_transformation", [reference, moving],
               {key: REG[key] for key in REG if key != "overlap"}, "MISSING_PARAMETER", "INVALID_REQUEST")


def soup_cases(operations) -> None:
    box = normals(B6 / "box_normals.ply")
    lprism = normals(B6 / "lprism_normals.ply")
    with tempfile.TemporaryDirectory() as raw:
        scratch = pathlib.Path(raw)
        runs = [("reconstruction.kinetic_surface", KINETIC, box, 6, 8, 480.0),
                ("reconstruction.kinetic_surface", KINETIC, lprism, None, None, 336.0)]
        if operations["reconstruction.polygonal_surface"]["info"].get("optional_dependency_built"):
            runs += [("reconstruction.polygonal_surface", POLYFIT, box, 6, 8, 480.0),
                     ("reconstruction.polygonal_surface", POLYFIT, lprism, 14, 16, 336.0)]
        else:
            print("SCIP not built: polygonal surface cases skipped")
        for operation, parameters, source, faces, vertices, volume in runs:
            result = q.invoke(scratch, operation, [source], parameters)
            path = q.ok(result)
            if faces is not None:
                assert result["metrics"]["face_count"] == faces and result["metrics"]["vertex_count"] == vertices, result["metrics"]
            candidate = art(path, "PolygonSoup3")
            verdict = validated(scratch, "reconstruction.validate.polygonal_surface", [candidate, source], SOUP_BOUNDS)
            assert verdict["euler_characteristic"] == 2 and abs(verdict["signed_volume"] - volume) < 1e-6, verdict
        soup = lambda name: art(B6 / name, "PolygonSoup3")
        valid = validated(scratch, "reconstruction.validate.polygonal_surface", [soup("box_soup.off"), box], SOUP_BOUNDS)
        assert valid["face_count"] == 6 and valid["vertex_count"] == 8 and valid["edge_count"] == 12, valid
        for name, code in (("tampered_box_nonplanar.off", "FACE_NOT_PLANAR"),
                           ("tampered_box_face_flipped.off", "EDGE_NOT_MANIFOLD_OR_INCONSISTENT"),
                           ("tampered_box_inward.off", "NOT_OUTWARD_ORIENTED"),
                           ("tampered_box_open.off", "SURFACE_NOT_CLOSED"),
                           ("tampered_box_shrunk.off", "SOURCE_TO_SURFACE_BOUND_EXCEEDED")):
            reject(scratch, "reconstruction.validate.polygonal_surface", [soup(name), box], SOUP_BOUNDS, code)
        reject(scratch, "reconstruction.kinetic_surface", [normals(RC / "sphere_zero_normal.ply")], KINETIC,
               "ZERO_NORMAL", "PRECONDITION_FAILED")
        reject(scratch, "reconstruction.kinetic_surface", [box], {**KINETIC, "partition_depth": 7},
               "INVALID_PARAMETER", "INVALID_REQUEST")
        reject(scratch, "reconstruction.kinetic_surface", [box], {**KINETIC, "lambda": 1.0},
               "INVALID_PARAMETER", "INVALID_REQUEST")


def poisson_cases() -> None:
    with tempfile.TemporaryDirectory() as raw:
        scratch = pathlib.Path(raw)
        for name, deviation in (("sphere_dense_normals.ply", 3.0), ("torus_normals.ply", 4.0)):
            source = normals(RC / name)
            parameters = {**POISSON_DELAUNAY, "max_deviation": MM(deviation)}
            result = q.invoke(scratch, "reconstruction.poisson_delaunay", [source], parameters)
            path = q.ok(result)
            assert result["metrics"]["algorithm"] == "CGAL::poisson_surface_reconstruction_delaunay", result["metrics"]
            assert result["metrics"]["boundary_edge_count"] > 0, "expected the disclosed manifold-with-boundary holes"
            candidate = art(path, "TriangleSurfaceMesh")
            verdict = validated(scratch, "reconstruction.validate.poisson_boundary", [candidate, source],
                                {key: parameters[key] for key in ("max_deviation", "max_circumradius", "min_coverage")})
            assert verdict["closed"] is False and verdict["closedness_claimed"] is False, verdict
            assert verdict["boundary_edge_count"] == result["metrics"]["boundary_edge_count"], verdict
        sphere = normals(RC / "sphere_dense_normals.ply")
        bounds = {key: POISSON_DELAUNAY[key] for key in ("max_deviation", "max_circumradius", "min_coverage")}
        reject(scratch, "reconstruction.validate.poisson_boundary",
               [art(RC / "tampered_poisson_flipped.off", "TriangleSurfaceMesh"), sphere], bounds, "ORIENTATION_NOT_OUTWARD")
        reject(scratch, "reconstruction.validate.poisson_boundary",
               [art(RC / "tampered_poisson_shrunk.off", "TriangleSurfaceMesh"), sphere], bounds,
               "SOURCE_COVERAGE_BELOW_MINIMUM")
        reject(scratch, "reconstruction.poisson_delaunay", [normals(RC / "sphere_zero_normal.ply")], POISSON_DELAUNAY,
               "ZERO_NORMAL", "PRECONDITION_FAILED")
        reject(scratch, "reconstruction.poisson_delaunay", [sphere],
               {key: POISSON_DELAUNAY[key] for key in POISSON_DELAUNAY if key != "min_coverage"},
               "MISSING_PARAMETER", "INVALID_REQUEST")
        reject(scratch, "reconstruction.validate.poisson_boundary",
               [art(RC / "tampered_poisson_flipped.off", "TriangleSurfaceMesh"), sphere],
               {**bounds, "max_circumradius": MM(0.0)}, "INVALID_PARAMETER", "INVALID_REQUEST")


def main() -> None:
    manifest = json.loads(subprocess.run([q.WORKER, "--manifest"], text=True, encoding="utf-8",
                                         capture_output=True, timeout=30, check=True).stdout)
    operations = {operation["id"]: operation for operation in manifest["operations"]}
    for producer in ("pointset.registration.compute_transformation", "pointset.registration.register",
                     "reconstruction.polygonal_surface", "reconstruction.kinetic_surface",
                     "reconstruction.poisson_delaunay"):
        for validator in operations[producer]["info"]["validators"]:
            assert operations[validator]["role"] == "validator", validator
    registration_cases(operations)
    soup_cases(operations)
    poisson_cases()
    print("batch-6 worker cases: PASS")


if __name__ == "__main__":
    main()
