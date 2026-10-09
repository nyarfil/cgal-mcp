"""Real CGAL 6.2.1 batch-5 production-worker cases (7.3.06 distances, 7.3.07 mesh-mesh intersections,
7.12.05 straight skeletons, 7.12.06 offsets).

Usage: python tests/master_batch5_cases.py <cgal-master-worker>
Every producer result is checked by its validator against hand-derived values; tampered candidates and
invalid parameters must fail closed.
"""

from __future__ import annotations

import json
import math
import pathlib
import subprocess
import tempfile

import master_query_cases as q
from master_batch2_cases import art, reject

ROOT = q.ROOT
B5 = ROOT / "tests" / "fixtures" / "master" / "batch5"
BA = ROOT / "tests" / "fixtures" / "master" / "wave_a_boolean"

MM = lambda value: {"value": value, "unit": "mm"}
GRID = {"method": "grid", "grid_spacing": MM(0.5), "include_vertices": True}
RANDOM = {"method": "random_uniform", "random_seed": 7, "points_on_faces": 200, "points_on_edges": 50,
          "include_vertices": True}


def mesh(path):
    return art(path, "TriangleSurfaceMesh")


def report(path):
    return art(path, "GeometryQueryReport", "none")


def pair(scratch, producer, validator, inputs, parameters, validator_inputs=None, validator_parameters=None):
    """Run producer and validator; the validator must pass with every check true."""
    path = q.ok(q.invoke(scratch, producer, inputs, parameters))
    verdict = json.loads(q.ok(q.invoke(scratch, validator, [report(path)] + (validator_inputs or inputs),
                                       parameters if validator_parameters is None else validator_parameters)
                              ).read_text("utf-8"))
    assert verdict["status"] == "pass" and verdict["passed"] is True, verdict
    assert verdict["validator"] == validator and verdict["checks"] and all(verdict["checks"].values()), verdict
    return json.loads(path.read_text("utf-8"))


def distance_cases(operations) -> None:
    for producer, validator in (("mesh.distance.sample_points", "mesh.validate.distance_samples"),
                                ("mesh.distance.max_to_mesh", "mesh.validate.max_distance_to_mesh"),
                                ("mesh.distance.hausdorff_approximate", "mesh.validate.hausdorff_report"),
                                ("mesh.distance.hausdorff_approximate_symmetric", "mesh.validate.hausdorff_report"),
                                ("mesh.distance.max_to_points", "mesh.validate.max_distance_to_points"),
                                ("mesh.distance.hausdorff_bounded", "mesh.validate.hausdorff_report")):
        assert validator in operations[producer]["info"]["validators"], producer
        assert operations[validator]["role"] == "validator"
    cube = mesh(BA / "cube_a.off")
    shifted = mesh(B5 / "cube_shift_x.off")  # cube translated by (+1, 0, 0)
    scaled = mesh(B5 / "cube_scaled2.off")   # cube scaled by 2 about the origin: [0,4]^3
    points = art(B5 / "dist_points.xyz", "PointSet3")
    error = MM(0.01)
    tolerance = 1e-9
    with tempfile.TemporaryDirectory() as raw:
        scratch = pathlib.Path(raw)
        # sample_triangle_mesh: every vertex of the 8-vertex cube is sampled first.
        for sampling in (GRID, RANDOM):
            result = pair(scratch, "mesh.distance.sample_points", "mesh.validate.distance_samples", [cube],
                          {"sampling": sampling})
            samples = result["results"]["points"]
            assert samples[:8] == [list(map(float, row.split())) for row in
                                   (BA / "cube_a.off").read_text().split("\n")[2:10]], samples[:8]
            if sampling is RANDOM:
                assert len(samples) == 8 + 200 + 50, len(samples)
        # max_distance_to_triangle_mesh: (1,1,3) is 1 above the face z=2 -> 1; (5,0,0) is 3 from x=2 -> 3.
        result = pair(scratch, "mesh.distance.max_to_mesh", "mesh.validate.max_distance_to_mesh", [points, cube], {})
        assert abs(result["results"]["distance"] - 3.0) < tolerance, result
        # Hausdorff distances: cube vs cube+1 in x is 1; cube vs the doubled cube is 2 one way, 2*sqrt(3) back.
        for other, expected in ((shifted, 1.0), (scaled, 2.0)):
            for producer, parameters in (("mesh.distance.hausdorff_approximate", {"sampling": GRID}),
                                         ("mesh.distance.hausdorff_approximate", {"sampling": RANDOM}),
                                         ("mesh.distance.hausdorff_bounded", {"error_bound": error})):
                result = pair(scratch, producer, "mesh.validate.hausdorff_report", [cube, other], parameters)
                assert abs(result["results"]["distance"] - expected) <= (0.01 if "bounded" in producer else tolerance), result
        result = pair(scratch, "mesh.distance.hausdorff_approximate", "mesh.validate.hausdorff_report", [scaled, cube],
                      {"sampling": GRID})
        assert abs(result["results"]["distance"] - 2 * math.sqrt(3)) < 1e-6, result
        result = pair(scratch, "mesh.distance.hausdorff_approximate_symmetric", "mesh.validate.hausdorff_report",
                      [cube, scaled], {"sampling": GRID})
        assert abs(result["results"]["distance"] - 2 * math.sqrt(3)) < 1e-6, result
        result = pair(scratch, "mesh.distance.hausdorff_bounded", "mesh.validate.hausdorff_report", [scaled, cube],
                      {"error_bound": error})
        assert abs(result["results"]["distance"] - 2 * math.sqrt(3)) <= 0.01, result
        # approximate_max_distance_to_point_set: the cube vertex (0,0,0) is sqrt(4+4+4)... exact value brackets.
        result = pair(scratch, "mesh.distance.max_to_points", "mesh.validate.max_distance_to_points", [cube, points],
                      {"precision": MM(0.01)})
        assert 3.3 < result["results"]["distance"] < 3.4, result
        # Tampered reports and invalid input fail closed.
        for name, validator, inputs, parameters, code in (
                ("tampered_samples_off_surface.json", "mesh.validate.distance_samples", [cube], {"sampling": GRID},
                 "SAMPLE_OFF_SURFACE"),
                ("tampered_samples_vertex_dropped.json", "mesh.validate.distance_samples", [cube], {"sampling": GRID},
                 "VERTICES_MISSING"),
                ("tampered_max_to_mesh_low.json", "mesh.validate.max_distance_to_mesh", [points, cube], {},
                 "DISTANCE_MISMATCH"),
                ("tampered_max_to_points_low.json", "mesh.validate.max_distance_to_points", [cube, points],
                 {"precision": MM(0.01)}, "DISTANCE_OUT_OF_BRACKET"),
                ("tampered_hausdorff_above_exact.json", "mesh.validate.hausdorff_report", [cube, scaled],
                 {"sampling": GRID}, "DISTANCE_ABOVE_EXACT"),
                ("tampered_hausdorff_below_vertex.json", "mesh.validate.hausdorff_report", [cube, scaled],
                 {"sampling": GRID}, "DISTANCE_BELOW_VERTEX_BOUND"),
                ("tampered_hausdorff_bounded_low.json", "mesh.validate.hausdorff_report", [cube, scaled],
                 {"error_bound": error}, "DISTANCE_OUT_OF_BRACKET")):
            reject(scratch, validator, [report(B5 / name)] + inputs, parameters, code)
        reject(scratch, "mesh.distance.hausdorff_bounded", [cube, scaled], {"error_bound": MM(0)}, "INVALID_PARAMETER",
               "INVALID_REQUEST")
        reject(scratch, "mesh.distance.hausdorff_approximate", [cube, scaled],
               {"sampling": {**GRID, "unexpected": 1}}, "INVALID_PARAMETER", "INVALID_REQUEST")
        reject(scratch, "mesh.distance.hausdorff_approximate", [cube, scaled],
               {"sampling": {"method": "grid", "grid_spacing": MM(0.5)}}, "INVALID_PARAMETER", "INVALID_REQUEST")
        reject(scratch, "mesh.distance.sample_points", [cube],
               {"sampling": {**RANDOM, "random_seed": -1}}, "INVALID_PARAMETER", "INVALID_REQUEST")


def intersection_cases(operations) -> None:
    assert "mesh.validate.do_intersect" in operations["mesh.intersections.do_intersect"]["info"]["validators"]
    assert "mesh.validate.intersection_polylines" in operations["mesh.intersections.polylines"]["info"]["validators"]
    cube = mesh(BA / "cube_a.off")
    shifted = mesh(B5 / "cube_shift.off")
    far = mesh(B5 / "cube_far.off")
    contained = mesh(BA / "cube_contained.off")
    with tempfile.TemporaryDirectory() as raw:
        scratch = pathlib.Path(raw)
        for other, overlap, expected in ((shifted, False, True), (far, False, False), (contained, False, False),
                                         (contained, True, True), (far, True, False)):
            result = pair(scratch, "mesh.intersections.do_intersect", "mesh.validate.do_intersect", [cube, other],
                          {"overlap_test": overlap})
            assert result["results"]["intersect"] is expected, (overlap, result)
        result = pair(scratch, "mesh.intersections.polylines", "mesh.validate.intersection_polylines", [cube, shifted], {})
        lines = result["results"]["polylines"]
        assert len(lines) == 1 and lines[0]["points"][0] == lines[0]["points"][-1], lines
        # Hand-derived closed loop with corners (1,2,2) (1,2,1/4) (2,2,1/4) (2,1/2,1/4) (2,1/2,2) (1,1/2,2):
        # perimeter 8.5, computed from the exact rational polyline points.
        def number(text):
            top, _, bottom = text.partition("/")
            return float(top) / float(bottom or 1)
        points = [[number(c) for c in point] for point in lines[0]["points"]]
        perimeter = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        assert abs(perimeter - 8.5) < 1e-12, perimeter
        for name, validator, parameters, code in (
                ("tampered_poly_point_off_surface.json", "mesh.validate.intersection_polylines", {},
                 "POINT_NOT_ON_BOTH_MESHES"),
                ("tampered_poly_segment_dropped.json", "mesh.validate.intersection_polylines", {}, "INTERSECTION_MISSING"),
                ("tampered_poly_chord_shortcut.json", "mesh.validate.intersection_polylines", {},
                 "SEGMENT_NOT_ON_INTERSECTION"),
                ("tampered_do_intersect_flipped.json", "mesh.validate.do_intersect", {"overlap_test": False},
                 "INTERSECTION_MISMATCH")):
            reject(scratch, validator, [report(B5 / name), cube, shifted], parameters, code)
        reject(scratch, "mesh.intersections.polylines", [cube, mesh(BA / "cube_partial_coplanar_touch.off")], {},
               "COPLANAR_TRIANGLES", "PRECONDITION_FAILED")
        reject(scratch, "mesh.intersections.do_intersect", [cube, mesh(BA / "open_cube.off")], {"overlap_test": True},
               "MESH_NOT_CLOSED", "PRECONDITION_FAILED")
        reject(scratch, "mesh.intersections.do_intersect", [cube, shifted], {"overlap_test": "yes"},
               "INVALID_PARAMETER", "INVALID_REQUEST")
        reject(scratch, "mesh.intersections.do_intersect", [cube, shifted], {}, "MISSING_PARAMETER", "INVALID_REQUEST")


def main() -> None:
    manifest = json.loads(subprocess.run([q.WORKER, "--manifest"], text=True, encoding="utf-8",
                                         capture_output=True, timeout=30, check=True).stdout)
    operations = {operation["id"]: operation for operation in manifest["operations"]}
    distance_cases(operations)
    intersection_cases(operations)
    try:
        import master_batch5_skeleton as skeleton
    except ImportError:
        skeleton = None
    if skeleton is not None:
        skeleton.skeleton_cases(operations)
    print("batch-5 worker cases: PASS")


if __name__ == "__main__":
    main()
