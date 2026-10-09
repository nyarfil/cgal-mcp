"""Real CGAL 6.2.1 batch-2 production-worker cases (7.3.05, 7.3.07, 7.5.03, 7.5.04, 7.9.02, 7.9.06,
7.12.04, 7.13.04).

Usage: python tests/master_batch2_cases.py <cgal-master-worker>
Every producer result is checked by its independent CGAL-free validator (exact rational face
normals and triangle/triangle intersections, exact weighted-area tiling, exact minimum balls,
exact polygon boundary chains, brute-force point-set measures); tampered reports/meshes and
degenerate inputs must fail closed.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

import master_query_cases as q

ROOT = q.ROOT
B2 = ROOT / "tests" / "fixtures" / "master" / "batch2"
QUERY = ROOT / "tests" / "fixtures" / "master" / "query"
REPLAY = ROOT / "tests" / "fixtures" / "master" / "replay"


def art(path: pathlib.Path, type_: str, unit: str = "mm") -> dict:
    return q.artifact("", type_, unit, path)


def length(value: float) -> dict:
    return {"value": value, "unit": "mm"}


def pair(scratch, producer, validator, inputs, parameters):
    """Run a producer and its validator; return the producer's first output path and artifact."""
    result = q.invoke(scratch, producer, inputs, parameters)
    path = q.ok(result)
    output = result["outputs"][0]
    candidate = art(path, output["type"], output.get("unit", "none"))
    verdict = json.loads(q.ok(q.invoke(scratch, validator, [candidate] + inputs, parameters)).read_text("utf-8"))
    assert verdict["status"] == "pass" and verdict["passed"] is True, verdict
    assert verdict["validator"] == validator and verdict["checks"] and all(verdict["checks"].values()), verdict
    return path, result


def reject(scratch, operation, inputs, parameters, code, error_class="VALIDATION_FAILED"):
    q.error(q.invoke(scratch, operation, inputs, parameters), code, error_class)


def main() -> None:
    manifest = json.loads(subprocess.run([q.WORKER, "--manifest"], text=True, encoding="utf-8",
                                         capture_output=True, timeout=30, check=True).stdout)
    operations = {operation["id"]: operation for operation in manifest["operations"]}
    for operation in ("pointset.spacing.average", "pointset.outliers.remove", "shape.bounding.circle",
                      "shape.bounding.sphere", "mesh.features.detect", "mesh.intersections.self",
                      "mesh.clip.plane", "mesh.split.plane", "mesh.corefine", "polygon.boolean"):
        validator = operations[operation]["info"]["validators"][0]
        assert operations[validator]["role"] == "validator", validator
    mesh = lambda path: art(path, "TriangleSurfaceMesh")
    report = lambda name: art(B2 / name, "GeometryQueryReport", "none")
    cube, tetra, bent = mesh(QUERY / "cube12.off"), mesh(QUERY / "tetra.off"), mesh(B2 / "bent_plate.off")
    open_square = mesh(QUERY / "square_open.off")
    with tempfile.TemporaryDirectory() as raw:
        scratch = pathlib.Path(raw)

        # 7.9 point-set processing: hand-derived average spacing 11/15 and the outlier quota rule.
        line = art(B2 / "line10.xyz", "PointSet3")
        path, result = pair(scratch, "pointset.spacing.average", "pointset.validate.average_spacing", [line],
                            {"neighbors": 2})
        assert abs(result["metrics"]["average_spacing"] - 11 / 15) < 1e-12, result
        cluster = art(B2 / "cluster_outlier.xyz", "PointSet3")
        for percent, distance, kept in ((10, 3, 9), (0, 3, 10), (50, 0, 5)):
            _, result = pair(scratch, "pointset.outliers.remove", "pointset.validate.outliers_removed", [cluster],
                             {"neighbors": 3, "threshold_percent": percent, "threshold_distance": length(distance)})
            assert result["metrics"]["output_point_count"] == kept, result
        reject(scratch, "pointset.spacing.average", [line], {"neighbors": 10}, "NEIGHBORHOOD_TOO_LARGE",
               "PRECONDITION_FAILED")
        reject(scratch, "pointset.validate.average_spacing", [report("tampered_spacing_report.json"), line],
               {"neighbors": 2}, "AVERAGE_SPACING_MISMATCH")
        reject(scratch, "pointset.validate.outliers_removed",
               [art(B2 / "tampered_outliers.xyz", "PointSet3"), cluster],
               {"neighbors": 3, "threshold_percent": 10, "threshold_distance": length(3)},
               "REMOVED_POINT_LESS_OUTLYING")

        # 7.13.04 bounding volumes.
        circle = art(B2 / "circle_points.json", "PointSet2")
        _, result = pair(scratch, "shape.bounding.circle", "shape.validate.min_circle", [circle], {})
        assert abs(result["metrics"]["radius"] - 2.5) < 1e-12, result
        pair(scratch, "shape.bounding.circle", "shape.validate.min_circle",
             [art(B2 / "circle_two.json", "PointSet2")], {})
        corners = art(B2 / "cube_corners.xyz", "PointSet3")
        for radius in (0, 0.5):
            _, result = pair(scratch, "shape.bounding.sphere", "shape.validate.min_sphere", [corners],
                             {"radius": length(radius)})
            assert abs(result["metrics"]["radius"] - (3 ** 0.5 + radius)) < 1e-12, result
        reject(scratch, "shape.bounding.sphere", [corners], {"radius": length(-1)}, "INVALID_PARAMETER",
               "INVALID_REQUEST")
        reject(scratch, "shape.validate.min_circle", [report("tampered_circle_report.json"), circle], {},
               "RADIUS_MISMATCH")
        reject(scratch, "shape.validate.min_sphere", [report("tampered_sphere_report.json"), corners],
               {"radius": length(0)}, "RADIUS_MISMATCH")

        # 7.3.05 features and 7.3.07 self-intersections.
        for source, angle, sharp, patches in ((cube, 30, 12, 6), (cube, 100, 0, 1), (bent, 30, 7, 2),
                                              (bent, 60, 6, 1), (open_square, 10, 4, 1)):
            _, result = pair(scratch, "mesh.features.detect", "mesh.validate.features", [source],
                             {"angle_degrees": angle})
            assert (result["metrics"]["sharp_edge_count"], result["metrics"]["patch_count"]) == (sharp, patches), result
        reject(scratch, "mesh.features.detect", [cube], {"angle_degrees": 200}, "INVALID_PARAMETER", "INVALID_REQUEST")
        reject(scratch, "mesh.validate.features", [report("tampered_features_report.json"), bent],
               {"angle_degrees": 30}, "SHARP_EDGES_MISMATCH")
        for source, intersects in ((tetra, False), (cube, False), (mesh(REPLAY / "intersecting_tetrahedra.off"), True)):
            _, result = pair(scratch, "mesh.intersections.self", "mesh.validate.self_intersections", [source], {})
            assert result["metrics"]["does_self_intersect"] is intersects, result
        reject(scratch, "mesh.validate.self_intersections",
               [report("tampered_selfint_report.json"), mesh(REPLAY / "intersecting_tetrahedra.off")], {},
               "INTERSECTING_PAIRS_MISMATCH")

        # 7.5.03 clip and 7.5.04 split / corefine.
        x1 = {"normal": [1, 0, 0], "offset": length(1)}
        diagonal = {"normal": [1, 1, 1], "offset": length(3)}
        for source, plane, volume in ((cube, x1, True), (cube, x1, False), (cube, diagonal, True),
                                      (open_square, x1, True)):
            pair(scratch, "mesh.clip.plane", "mesh.validate.clip", [source], {**plane, "clip_volume": volume})
        for plane in (x1, diagonal):
            pair(scratch, "mesh.split.plane", "mesh.validate.split", [cube], plane)
        pair(scratch, "mesh.corefine", "mesh.validate.corefine", [tetra, mesh(B2 / "tetra_b.off")], {})
        reject(scratch, "mesh.clip.plane", [cube], {"normal": [0, 0, 1], "offset": length(0), "clip_volume": True},
               "COPLANAR_FACE", "PRECONDITION_FAILED")
        reject(scratch, "mesh.clip.plane", [cube], {"normal": [0, 0, 0], "offset": length(1), "clip_volume": True},
               "ZERO_NORMAL", "PRECONDITION_FAILED")
        reject(scratch, "mesh.split.plane", [cube], {"normal": [0, 0, 1], "offset": length(0)},
               "COPLANAR_FACE", "PRECONDITION_FAILED")
        reject(scratch, "mesh.validate.clip", [cube, cube], {**x1, "clip_volume": True}, "VERTEX_ON_REMOVED_SIDE")
        reject(scratch, "mesh.validate.clip", [mesh(B2 / "clip_tampered_strip.off"), open_square],
               {**x1, "clip_volume": False}, "REGION_NOT_COVERED_EXACTLY")
        reject(scratch, "mesh.validate.split", [art(QUERY / "cube12.off", "PolygonSoup3"), cube], x1,
               "TRIANGLE_STRADDLES_PLANE")
        reject(scratch, "mesh.validate.corefine", [tetra, tetra, mesh(B2 / "tetra_b.off")], {},
               "TRIANGLE_CROSSED_BY_OTHER_SURFACE")

        # 7.12.04 polygon Boolean set operations.
        square = art(QUERY / "square4.json", "Polygon2")
        shifted = art(B2 / "square_shift.json", "Polygon2")
        inner = art(B2 / "square_inner.json", "Polygon2")
        far = art(B2 / "square_far.json", "Polygon2")
        hexagon = art(QUERY / "polygon_clockwise.json", "Polygon2")
        for first, second, operation, polygons, holes in (
                (square, shifted, "join", 1, 0), (square, shifted, "intersection", 1, 0),
                (square, shifted, "difference", 1, 0), (square, inner, "difference", 1, 1),
                (square, far, "join", 2, 0), (square, far, "intersection", 0, 0),
                (hexagon, square, "intersection", 1, 0)):
            _, result = pair(scratch, "polygon.boolean", "polygon.validate.boolean", [first, second],
                             {"operation": operation})
            assert (result["metrics"]["polygon_count"], result["metrics"]["hole_count"]) == (polygons, holes), result
        reject(scratch, "polygon.boolean", [art(QUERY / "polygon_bowtie.json", "Polygon2"), square],
               {"operation": "join"}, "POLYGON_NOT_SIMPLE", "PRECONDITION_FAILED")
        reject(scratch, "polygon.validate.boolean", [report("tampered_polygon_report.json"), square, shifted],
               {"operation": "join"}, "BOUNDARY_CHAIN_MISMATCH")
    print("master batch2 cases passed")


if __name__ == "__main__":
    main()
