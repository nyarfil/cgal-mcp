"""Real CGAL 6.2.1 Wave C production-worker cases (2D, triangulation, spatial)."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "master" / "wave_c"
CUBE = ROOT / "tests" / "fixtures" / "master" / "wave_a_boolean" / "cube_a.off"
SKEW = ROOT / "tests" / "fixtures" / "master" / "wave_a_boolean" / "skew_tetra.off"
WORKER = sys.argv[1]

TRANSFORMS = {
    "hull.convex_2": ["hull.validate.convex_enclosure_2"],
    "polygon.analysis.properties": ["polygon.validate.properties_report"],
    "polygon.query.containment": ["polygon.validate.containment_report"],
    "triangulation.delaunay_2": ["triangulation.validate.delaunay_2"],
    "triangulation.constrained_2": ["triangulation.validate.constrained_2"],
    "triangulation.delaunay_3": ["triangulation.validate.delaunay_3"],
    "spatial.knn_3": ["spatial.validate.knn_report"],
    "spatial.range_search_3": ["spatial.validate.range_report"],
    "spatial.bbox_2": ["spatial.validate.bbox_report"],
    "spatial.bbox_3": ["spatial.validate.bbox_report"],
    "spatial.aabb.closest_points": ["spatial.validate.closest_points_report"],
    "spatial.aabb.ray_first_hits": ["spatial.validate.ray_hits_report"],
}
VALIDATORS = {validator for values in TRANSFORMS.values() for validator in values}


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: pathlib.Path, type_: str, format_: str | None = None, unit: str = "mm") -> dict:
    if format_ is None:
        format_ = {".json": "json", ".xyz": "xyz", ".off": "off"}[path.suffix]
    return {"artifact_id": path.stem, "type": type_, "unit": unit, "format": format_,
            "path": str(path.resolve()), "sha256": sha256(path)}


COUNTER = [0]


def invoke(scratch: pathlib.Path, operation: str, inputs: list[dict],
           parameters: dict | None = None) -> dict:
    COUNTER[0] += 1
    output = scratch / f"run{COUNTER[0]:03d}"
    output.mkdir()
    request = {"protocol": 1, "request_id": f"wave-c-{COUNTER[0]}", "operation": operation,
               "inputs": inputs, "parameters": parameters or {},
               "output_dir": str(output.resolve()), "kernel": "package_recommended",
               "limits": {"wall_time_ms": 120000, "memory_mb": 2048}}
    process = subprocess.run([WORKER], input=json.dumps(request) + "\n", text=True,
                             encoding="utf-8", capture_output=True, timeout=120)
    assert process.returncode == 0, process.stderr
    assert process.stderr == "", process.stderr
    lines = process.stdout.splitlines()
    assert len(lines) == 1, process.stdout
    result = json.loads(lines[0])
    assert result["request_id"] == request["request_id"], result
    return result


def ok(result: dict) -> tuple[dict, pathlib.Path]:
    assert result["status"] == "ok", result
    output = result["outputs"][0]
    path = pathlib.Path(output["path"])
    assert path.is_file(), result
    return output, path


def error(result: dict, code: str, error_class: str | None = None) -> None:
    assert result["status"] == "error", result
    assert result["error"]["code"] == code, result
    if error_class is not None:
        assert result["error"]["class"] == error_class, result


def produced(output: dict, path: pathlib.Path) -> dict:
    return {"artifact_id": path.stem, "type": output["type"], "unit": output["unit"],
            "format": output["format"], "path": str(path.resolve()), "sha256": sha256(path)}


def tampered(scratch: pathlib.Path, source: pathlib.Path, mutate) -> dict:
    value = json.loads(source.read_text("utf-8"))
    mutate(value)
    COUNTER[0] += 1
    path = scratch / f"tampered{COUNTER[0]:03d}.json"
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return path


def run_pair(scratch, transform, inputs, parameters, validator, validator_inputs,
             validator_parameters=None):
    """Run a transform and its mandatory validator; return (report json, artifact, metrics)."""
    output, path = ok(invoke(scratch, transform, inputs, parameters))
    candidate = produced(output, path)
    validation = invoke(scratch, validator, [candidate, *validator_inputs],
                        validator_parameters if validator_parameters is not None else parameters)
    _, validation_path = ok(validation)
    report = json.loads(validation_path.read_text("utf-8"))
    assert report["status"] == "pass" and report["passed"] is True, report
    assert all(report["checks"].values()), report
    return json.loads(path.read_text("utf-8")), candidate, path


def main() -> None:
    manifest = json.loads(subprocess.run([WORKER, "--manifest"], text=True, encoding="utf-8",
                                         capture_output=True, timeout=30, check=True).stdout)
    operations = {operation["id"]: operation for operation in manifest["operations"]}
    assert set(TRANSFORMS) | VALIDATORS <= operations.keys()
    for operation_id in set(TRANSFORMS) | VALIDATORS:
        entry = operations[operation_id]
        assert entry["revision"] == 1, entry
        assert entry["supported_kernels"] == ["package_recommended"], entry
        assert entry["effective_kernel"] == \
            "CGAL::Exact_predicates_inexact_constructions_kernel", entry
    for transform, validators in TRANSFORMS.items():
        assert operations[transform]["info"]["validators"] == validators, transform

    points2 = artifact(FIXTURES / "planar_points.json", "PointSet2")
    collinear = artifact(FIXTURES / "collinear_points.json", "PointSet2")
    holed = artifact(FIXTURES / "polygon_with_hole.json", "PolygonWithHoles2")
    l_shape = artifact(FIXTURES / "polygon_l_shape.json", "PolygonWithHoles2")
    bowtie = artifact(FIXTURES / "polygon_bowtie.json", "PolygonWithHoles2")
    queries2 = artifact(FIXTURES / "containment_queries.json", "PointSet2")
    graph = artifact(FIXTURES / "constraint_graph.json", "SegmentGraph2")
    crossing = artifact(FIXTURES / "constraint_crossing.json", "SegmentGraph2")
    cloud = artifact(FIXTURES / "cloud_points.xyz", "PointSet3")
    flat = artifact(FIXTURES / "flat_points.xyz", "PointSet3")
    queries3 = artifact(FIXTURES / "query_points.xyz", "PointSet3")
    mesh_queries = artifact(FIXTURES / "mesh_queries.xyz", "PointSet3")
    cube = artifact(CUBE, "TriangleSurfaceMesh")
    skew = artifact(SKEW, "TriangleSurfaceMesh")
    rays = artifact(FIXTURES / "cube_rays.json", "RayBatch3")

    with tempfile.TemporaryDirectory(prefix="cgal-master-wave-c-") as temporary:
        scratch = pathlib.Path(temporary)

        # --- 2D convex hull ---------------------------------------------------
        hull, hull_artifact, hull_path = run_pair(
            scratch, "hull.convex_2", [points2], {}, "hull.validate.convex_enclosure_2", [points2])
        assert hull["points"] == [[0, 0], [3, 0], [3, 3], [0, 3]], hull
        for mutate, code in (
            (lambda v: v["points"].reverse(), "HULL_NOT_STRICTLY_CONVEX_CCW"),
            (lambda v: v["points"].pop(), None),
            (lambda v: v["points"].insert(1, [1.5, 0]), "HULL_NOT_STRICTLY_CONVEX_CCW"),
            (lambda v: v["points"].__setitem__(2, [3.5, 3]), "HULL_VERTEX_NOT_IN_SOURCE"),
        ):
            bad = artifact(tampered(scratch, hull_path, mutate), "Polygon2")
            failed = invoke(scratch, "hull.validate.convex_enclosure_2", [bad, points2])
            assert failed["status"] == "error", failed
            assert failed["error"]["class"] == "VALIDATION_FAILED", failed
            if code is not None:
                assert failed["error"]["code"] == code, failed
        error(invoke(scratch, "hull.convex_2", [collinear]), "AFFINE_RANK_LT_2")
        error(invoke(scratch, "hull.convex_2", [graph]), "INPUT_TYPE_MISMATCH", "TYPE_ERROR")

        # --- polygon properties ------------------------------------------------
        properties, _, properties_path = run_pair(
            scratch, "polygon.analysis.properties", [holed], {},
            "polygon.validate.properties_report", [holed])
        results = properties["results"]
        assert results["valid_polygon_with_holes"] is True, results
        assert results["area"]["exact"] == "91", results
        assert [ring["orientation"] for ring in results["rings"]] == \
            ["counterclockwise", "clockwise"], results
        l_report, _, _ = run_pair(scratch, "polygon.analysis.properties", [l_shape], {},
                                  "polygon.validate.properties_report", [l_shape])
        assert l_report["results"]["rings"][0]["convex"] is False, l_report
        assert l_report["results"]["area"]["exact"] == "7", l_report
        bow_report, _, _ = run_pair(scratch, "polygon.analysis.properties", [bowtie], {},
                                    "polygon.validate.properties_report", [bowtie])
        assert bow_report["results"]["valid_polygon_with_holes"] is False, bow_report
        assert bow_report["results"]["rings"][0]["simple"] is False, bow_report
        bad = artifact(tampered(scratch, properties_path,
                                lambda v: v["results"]["rings"][0].__setitem__("convex", False)),
                       "Polygon2AnalysisReport", unit="none")
        failed = invoke(scratch, "polygon.validate.properties_report", [bad, holed])
        assert failed["status"] == "error" and failed["error"]["class"] == "VALIDATION_FAILED", failed

        # --- polygon containment --------------------------------------------
        containment, _, containment_path = run_pair(
            scratch, "polygon.query.containment", [holed, queries2], {},
            "polygon.validate.containment_report", [holed, queries2])
        locations = [entry["location"] for entry in containment["results"]]
        assert locations == ["inside", "outside", "boundary", "boundary", "outside", "boundary",
                             "boundary", "inside"], locations
        bad = artifact(tampered(scratch, containment_path,
                                lambda v: v["results"][1].__setitem__("location", "inside")),
                       "Polygon2AnalysisReport", unit="none")
        failed = invoke(scratch, "polygon.validate.containment_report", [bad, holed, queries2])
        assert failed["status"] == "error" and failed["error"]["class"] == "VALIDATION_FAILED", failed
        error(invoke(scratch, "polygon.query.containment", [bowtie, queries2]),
              "INVALID_POLYGON_WITH_HOLES", "PRECONDITION_FAILED")

        # --- Delaunay 2 --------------------------------------------------------
        dt2, _, dt2_path = run_pair(scratch, "triangulation.delaunay_2", [points2], {},
                                    "triangulation.validate.delaunay_2", [points2])
        assert len(dt2["vertices"]) == 20 and dt2["constrained_edges"] == [], dt2
        def flip_first_interior(value):
            value["triangles"][0] = list(reversed(value["triangles"][0]))
        for mutate in (flip_first_interior, lambda v: v["triangles"].pop(),
                       lambda v: v["vertices"].__setitem__(0, [0, -1e-9])):
            bad = artifact(tampered(scratch, dt2_path, mutate), "Triangulation2")
            failed = invoke(scratch, "triangulation.validate.delaunay_2", [bad, points2])
            assert failed["status"] == "error" and \
                failed["error"]["class"] == "VALIDATION_FAILED", failed
        error(invoke(scratch, "triangulation.delaunay_2", [collinear]), "AFFINE_RANK_LT_2")

        # --- constrained triangulations ---------------------------------------
        cdt, _, _ = run_pair(scratch, "triangulation.constrained_2", [graph], {"delaunay": True},
                             "triangulation.validate.constrained_2", [graph])
        assert len(cdt["constrained_edges"]) == 3, cdt
        ct, _, ct_path = run_pair(scratch, "triangulation.constrained_2", [graph],
                                  {"delaunay": False}, "triangulation.validate.constrained_2",
                                  [graph])
        assert len(ct["constrained_edges"]) == 3, ct
        bad = artifact(tampered(scratch, ct_path, lambda v: v["constrained_edges"].pop()),
                       "Triangulation2")
        failed = invoke(scratch, "triangulation.validate.constrained_2", [bad, graph],
                        {"delaunay": False})
        assert failed["status"] == "error" and failed["error"]["class"] == "VALIDATION_FAILED", failed
        # A constraint that is not a Delaunay edge must be kept by the CDT.
        edges = {tuple(sorted((t[i], t[(i + 1) % 3]))) for t in cdt["triangles"] for i in range(3)}
        assert (4, 5) in edges, sorted(edges)
        error(invoke(scratch, "triangulation.constrained_2", [crossing], {"delaunay": True}),
              "CONSTRAINTS_INTERSECT", "PRECONDITION_FAILED")
        error(invoke(scratch, "triangulation.constrained_2", [graph], {}),
              "MISSING_PARAMETER")

        # --- Delaunay 3 --------------------------------------------------------
        dt3, _, dt3_path = run_pair(scratch, "triangulation.delaunay_3", [cloud], {},
                                    "triangulation.validate.delaunay_3", [cloud])
        assert len(dt3["vertices"]) == 168 and len(dt3["tetrahedra"]) > 168, len(dt3["tetrahedra"])
        for mutate in (lambda v: v["tetrahedra"].pop(),
                       lambda v: v["tetrahedra"][0].__setitem__(0, v["tetrahedra"][0][1]) or
                       v["tetrahedra"][0].__setitem__(1, v["tetrahedra"][0][0])):
            bad = artifact(tampered(scratch, dt3_path, mutate), "Triangulation3")
            failed = invoke(scratch, "triangulation.validate.delaunay_3", [bad, cloud])
            assert failed["status"] == "error" and \
                failed["error"]["class"] == "VALIDATION_FAILED", failed
        error(invoke(scratch, "triangulation.delaunay_3", [flat]), "AFFINE_RANK_LT_3")

        # --- k nearest neighbors ---------------------------------------------
        for search in ("orthogonal", "general"):
            knn, _, knn_path = run_pair(scratch, "spatial.knn_3", [cloud, queries3],
                                        {"k": 5, "search": search}, "spatial.validate.knn_report",
                                        [cloud, queries3])
            assert len(knn["results"]) == 6, knn
            assert knn["results"][1]["neighbors"][0]["index"] == \
                cloud_index(FIXTURES / "cloud_points.xyz", (1, 1, 1)), knn["results"][1]
            assert knn["results"][1]["neighbors"][0]["distance"] == 0, knn["results"][1]
        def swap_far(value):
            value["results"][0]["neighbors"][-1]["index"] = farthest_index(
                FIXTURES / "cloud_points.xyz", (0, 0, 0))
        bad = artifact(tampered(scratch, knn_path, swap_far), "SpatialQueryReport", unit="none")
        error(invoke(scratch, "spatial.validate.knn_report", [bad, cloud, queries3],
                     {"k": 5, "search": "general"}), "DISTANCE_MISMATCH", "VALIDATION_FAILED")
        error(invoke(scratch, "spatial.validate.knn_report", [knn_artifact(knn_path), cloud,
                                                              queries3],
                     {"k": 4, "search": "general"}), "REPORT_PARAMETER_MISMATCH")
        error(invoke(scratch, "spatial.knn_3", [cloud, queries3], {"k": 0, "search": "general"}),
              "INVALID_PARAMETER")

        # --- radius search -----------------------------------------------------
        radius = {"radius": {"value": 0.5, "unit": "mm"}}
        ranged, _, range_path = run_pair(scratch, "spatial.range_search_3", [cloud, queries3],
                                         radius, "spatial.validate.range_report",
                                         [cloud, queries3])
        assert ranged["summary"]["total_matches"] > 0, ranged
        exact = run_pair(scratch, "spatial.range_search_3", [cloud, queries3],
                         {"radius": {"value": 2 * 3 ** 0.5, "unit": "mm"}},
                         "spatial.validate.range_report", [cloud, queries3])[0]
        bad = artifact(tampered(scratch, range_path, lambda v: v["results"][0]["neighbors"].pop()),
                       "SpatialQueryReport", unit="none")
        error(invoke(scratch, "spatial.validate.range_report", [bad, cloud, queries3], radius),
              "RANGE_SET_MISMATCH", "VALIDATION_FAILED")
        error(invoke(scratch, "spatial.range_search_3", [cloud, queries3],
                     {"radius": {"value": 0.5, "unit": "cm"}}), "UNIT_MISMATCH", "TYPE_ERROR")
        assert exact["summary"]["total_matches"] >= 168, exact["summary"]

        # --- bounding boxes ------------------------------------------------------
        box2, _, box2_path = run_pair(scratch, "spatial.bbox_2", [points2], {},
                                      "spatial.validate.bbox_report", [points2])
        assert box2["results"] == {"dimension": 2, "min": [0, 0], "max": [3, 3]}, box2
        box3, _, _ = run_pair(scratch, "spatial.bbox_3", [cube], {},
                              "spatial.validate.bbox_report", [cube])
        assert box3["results"] == {"dimension": 3, "min": [0, 0, 0], "max": [2, 2, 2]}, box3
        run_pair(scratch, "spatial.bbox_3", [cloud], {}, "spatial.validate.bbox_report", [cloud])
        empty3 = scratch / "empty3.xyz"
        empty3.write_bytes(b"")
        error(invoke(scratch, "spatial.bbox_3", [artifact(empty3, "PointSet3")]),
              "EMPTY_POINT_SET", "PRECONDITION_FAILED")
        # Oversized convex shell: a valid closed convex outward mesh enclosing the points, but
        # whose vertices are not source points, must be rejected.
        inner = artifact(FIXTURES / "hull_inner_points.xyz", "PointSet3")
        oversized = invoke(scratch, "hull.validate.convex_enclosure", [cube, inner])
        error(oversized, "HULL_VERTEX_NOT_IN_SOURCE", "VALIDATION_FAILED")
        bad = artifact(tampered(scratch, box2_path,
                                lambda v: v["results"]["max"].__setitem__(0, 3.5)),
                       "SpatialQueryReport", unit="none")
        error(invoke(scratch, "spatial.validate.bbox_report", [bad, points2]),
              "BBOX_MISMATCH", "VALIDATION_FAILED")
        error(invoke(scratch, "spatial.validate.bbox_report", [knn_artifact(box2_path), cube]),
              "REPORT_SOURCE_MISMATCH", "VALIDATION_FAILED")

        # --- AABB closest points ------------------------------------------------
        closest, _, closest_path = run_pair(
            scratch, "spatial.aabb.closest_points", [cube, mesh_queries], {},
            "spatial.validate.closest_points_report", [cube, mesh_queries])
        distances = [entry["distance"] for entry in closest["results"]]
        assert abs(distances[0] - 1) < 1e-12 and abs(distances[1] - 1) < 1e-12, distances
        assert abs(distances[2] - 2) < 1e-12, distances
        run_pair(scratch, "spatial.aabb.closest_points", [skew, mesh_queries], {},
                 "spatial.validate.closest_points_report", [skew, mesh_queries])
        bad = artifact(tampered(scratch, closest_path,
                                lambda v: v["results"][0].__setitem__("distance", 1.5)),
                       "SpatialQueryReport", unit="none")
        error(invoke(scratch, "spatial.validate.closest_points_report", [bad, cube, mesh_queries]),
              "NOT_CLOSEST_POINT", "VALIDATION_FAILED")

        # --- AABB ray first hits ---------------------------------------------
        hits, _, hits_path = run_pair(scratch, "spatial.aabb.ray_first_hits", [cube, rays], {},
                                      "spatial.validate.ray_hits_report", [cube, rays])
        status = [entry["hit"] for entry in hits["results"]]
        assert status == [True, False, True, True, True, True], status
        assert abs(hits["results"][0]["distance"] - 1) < 1e-12, hits["results"][0]
        assert abs(hits["results"][2]["distance"] - (1 + 0.09 + 0.04) ** 0.5) < 1e-12
        assert abs(hits["results"][3]["distance"] - 1) < 1e-12, hits["results"][3]
        assert abs(hits["results"][4]["distance"] - 3 ** 0.5) < 1e-12, hits["results"][4]
        bad = artifact(tampered(scratch, hits_path,
                                lambda v: v["results"][1].update({"hit": True, "face_index": 0,
                                                                  "point": [0, 0, 0],
                                                                  "distance": 1})),
                       "SpatialQueryReport", unit="none")
        error(invoke(scratch, "spatial.validate.ray_hits_report", [bad, cube, rays]),
              "HIT_STATUS_MISMATCH", "VALIDATION_FAILED")
        bad = artifact(tampered(scratch, hits_path,
                                lambda v: v["results"][5].update({"face_index": 0,
                                                                  "point": [0.5, 0.5, 0],
                                                                  "distance": 3})),
                       "SpatialQueryReport", unit="none")
        error(invoke(scratch, "spatial.validate.ray_hits_report", [bad, cube, rays]),
              "NOT_FIRST_HIT", "VALIDATION_FAILED")
        error(invoke(scratch, "spatial.aabb.ray_first_hits",
                     [cube, artifact(FIXTURES / "cube_rays.json", "RayBatch3", unit="cm")]),
              "UNIT_MISMATCH", "TYPE_ERROR")
    print("PASS master Wave C worker cases")


def read_xyz(path: pathlib.Path) -> list[tuple[float, float, float]]:
    return [tuple(float(value) for value in line.split())
            for line in path.read_text("ascii").splitlines() if line.strip()]


def cloud_index(path: pathlib.Path, point) -> int:
    return read_xyz(path).index(tuple(float(value) for value in point))


def farthest_index(path: pathlib.Path, query) -> int:
    points = read_xyz(path)
    return max(range(len(points)),
               key=lambda i: sum((a - b) ** 2 for a, b in zip(points[i], query)))


def knn_artifact(path: pathlib.Path) -> dict:
    return artifact(path, "SpatialQueryReport", "json", unit="none")


if __name__ == "__main__":
    main()
