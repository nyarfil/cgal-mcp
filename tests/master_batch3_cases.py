"""Real CGAL 6.2.1 batch-3 production-worker cases (7.5.01, 7.11.03, 7.11.05, 7.12.02, 7.12.03, 7.12.07).

Usage: python tests/master_batch3_cases.py <cgal-master-worker>
Every producer result is checked by its independent CGAL-free validator (exact lifted-point
regularity, exact circumcentres, exact segment splitting and face tracing, exact convolution
membership); tampered reports and degenerate inputs must fail closed.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile

import master_query_cases as q
from master_batch2_cases import art, pair, reject

ROOT = q.ROOT
B3 = ROOT / "tests" / "fixtures" / "master" / "batch3"
QUERY = ROOT / "tests" / "fixtures" / "master" / "query"

PRODUCERS = (
    ("triangulation.regular_2", "triangulation.validate.regular_2"),
    ("triangulation.regular_3", "triangulation.validate.regular_3"),
    ("triangulation.voronoi_dual", "triangulation.validate.voronoi_dual"),
    ("polygon.minkowski_sum", "polygon.validate.minkowski_sum"),
    ("polygon.minkowski_sum_reduced_convolution", "polygon.validate.minkowski_sum"),
    ("arrangement.build", "arrangement.validate.build"),
    ("arrangement.zone", "arrangement.validate.zone"),
    ("arrangement.overlay", "arrangement.validate.overlay"),
    ("mesh.autorefine", "mesh.validate.autorefine"),
)


def main() -> None:
    manifest = json.loads(subprocess.run([q.WORKER, "--manifest"], text=True, encoding="utf-8",
                                         capture_output=True, timeout=30, check=True).stdout)
    operations = {operation["id"]: operation for operation in manifest["operations"]}
    for producer, validator in PRODUCERS:
        assert validator in operations[producer]["info"]["validators"], (producer, validator)
        assert operations[validator]["role"] == "validator", validator
    pts2 = lambda name: art(B3 / name, "PointSet2")
    seg = lambda name: art(B3 / name, "SegmentGraph2")
    poly = lambda name: art(B3 / name, "Polygon2")
    report = lambda name: art(B3 / name, "GeometryQueryReport", "none")
    reg2, reg3 = pts2("reg2_points.json"), art(B3 / "reg3_points.xyz", "PointSet3")
    scatter = pts2("voronoi_scatter.json")
    boxes, cross = seg("arr_boxes.json"), seg("arr_cross.json")
    diagonal = seg("zone_diagonal.json")
    square2, unit, triangle = poly("square_two.json"), poly("square_unit.json"), poly("triangle_a.json")
    u_ring, square3, c_shape = poly("polygon_u.json"), poly("square_three.json"), poly("polygon_c.json")
    zero2, hidden2, heavy2 = [0] * 6, [0, 0, 0, 0, -10, 0], [0, 0, 0, 0, 50, 0]
    zero3, hidden3 = [0] * 10, [0] * 8 + [-10, 0]
    with tempfile.TemporaryDirectory() as raw:
        scratch = pathlib.Path(raw)
        _, result = pair(scratch, "triangulation.regular_2", "triangulation.validate.regular_2", [reg2],
                         {"weights": zero2})
        assert result["metrics"]["hidden_count"] == 0, result
        _, result = pair(scratch, "triangulation.regular_2", "triangulation.validate.regular_2", [reg2],
                         {"weights": hidden2})
        assert result["metrics"]["hidden_count"] == 1, result
        pair(scratch, "triangulation.regular_3", "triangulation.validate.regular_3", [reg3], {"weights": zero3})
        _, result = pair(scratch, "triangulation.regular_3", "triangulation.validate.regular_3", [reg3],
                         {"weights": hidden3})
        assert result["metrics"]["hidden_count"] == 1, result
        pair(scratch, "triangulation.voronoi_dual", "triangulation.validate.voronoi_dual", [scatter], {})
        pair(scratch, "triangulation.voronoi_dual", "triangulation.validate.voronoi_dual",
             [pts2("voronoi_square_center.json")], {})
        for producer in ("polygon.minkowski_sum", "polygon.minkowski_sum_reduced_convolution"):
            _, result = pair(scratch, producer, "polygon.validate.minkowski_sum", [u_ring, square3], {})
            assert result["metrics"]["hole_count"] == 1, result
            pair(scratch, producer, "polygon.validate.minkowski_sum", [square2, triangle], {})
            _, result = pair(scratch, producer, "polygon.validate.minkowski_sum", [c_shape, square2], {})
            assert result["metrics"]["hole_count"] == 0, result
        pair(scratch, "arrangement.build", "arrangement.validate.build", [cross], {})
        _, result = pair(scratch, "arrangement.build", "arrangement.validate.build", [boxes], {})
        assert result["metrics"]["face_count"] == 3, result
        for query in ("zone_horizontal.json", "zone_diagonal.json", "zone_outside.json"):
            pair(scratch, "arrangement.zone", "arrangement.validate.zone", [boxes, seg(query)], {})
        pair(scratch, "arrangement.zone", "arrangement.validate.zone", [cross, diagonal], {})
        pair(scratch, "arrangement.overlay", "arrangement.validate.overlay", [square2, unit], {})
        pair(scratch, "arrangement.overlay", "arrangement.validate.overlay", [square2, triangle], {})
        pair(scratch, "arrangement.overlay", "arrangement.validate.overlay", [u_ring, square3], {})

        # Fail closed: tampered reports.
        for name, validator, inputs, parameters, code in (
            ("tampered_regular2_hidden_report.json", "triangulation.validate.regular_2", [reg2],
             {"weights": zero2}, "HIDDEN_POINT_NOT_DOMINATED"),
            ("tampered_regular2_nonregular_report.json", "triangulation.validate.regular_2", [reg2],
             {"weights": heavy2}, "NOT_REGULAR"),
            ("tampered_regular3_hidden_report.json", "triangulation.validate.regular_3", [reg3],
             {"weights": zero3}, "HIDDEN_POINT_NOT_DOMINATED"),
            ("tampered_regular3_missing_cell_report.json", "triangulation.validate.regular_3", [reg3],
             {"weights": zero3}, "BOUNDARY_FACE_NOT_HULL_FACE"),
            ("tampered_voronoi_edge_report.json", "triangulation.validate.voronoi_dual", [scatter], {},
             "VORONOI_EDGES_MISMATCH"),
            ("tampered_voronoi_vertex_report.json", "triangulation.validate.voronoi_dual", [scatter], {},
             "VORONOI_VERTICES_MISMATCH"),
            ("tampered_minkowski_hole_dropped_report.json", "polygon.validate.minkowski_sum",
             [u_ring, square3], {}, "BOUNDARY_CHAIN_MISMATCH"),
            ("tampered_minkowski_vertex_moved_report.json", "polygon.validate.minkowski_sum",
             [square2, triangle], {}, "BOUNDARY_CHAIN_MISMATCH"),
            ("tampered_arrangement_face_dropped_report.json", "arrangement.validate.build", [boxes], {},
             "ARRANGEMENT_FACES_MISMATCH"),
            ("tampered_arrangement_edge_dropped_report.json", "arrangement.validate.build", [boxes], {},
             "ARRANGEMENT_EDGES_MISMATCH"),
            ("tampered_zone_vertex_dropped_report.json", "arrangement.validate.zone", [boxes, diagonal], {},
             "ZONE_VERTICES_MISMATCH"),
            ("tampered_overlay_label_report.json", "arrangement.validate.overlay", [square2, unit], {},
             "ARRANGEMENT_FACES_MISMATCH"),
        ):
            reject(scratch, validator, [report(name)] + inputs, parameters, code)

        # Fail closed: degenerate inputs.
        reject(scratch, "triangulation.regular_2", [reg2], {"weights": [0, 0, 0]}, "INVALID_PARAMETER",
               "INVALID_REQUEST")
        reject(scratch, "triangulation.regular_2", [pts2("points_duplicate.json")], {"weights": [0] * 4},
               "DUPLICATE_POINT", "PRECONDITION_FAILED")
        reject(scratch, "triangulation.regular_2", [pts2("points_collinear.json")], {"weights": [0] * 4},
               "ALL_COLLINEAR", "PRECONDITION_FAILED")
        reject(scratch, "triangulation.voronoi_dual", [pts2("points_collinear.json")], {}, "ALL_COLLINEAR",
               "PRECONDITION_FAILED")
        reject(scratch, "arrangement.build", [seg("arr_zero_length.json")], {}, "ZERO_LENGTH_SEGMENT",
               "PRECONDITION_FAILED")
        reject(scratch, "arrangement.zone", [boxes, seg("zone_two_segments.json")], {}, "QUERY_NOT_ONE_SEGMENT",
               "PRECONDITION_FAILED")
    print("batch 3 cases passed")


if __name__ == "__main__":
    main()
