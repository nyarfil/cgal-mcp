"""Real CGAL 6.2.1 query / mesh-processing additions (7.2.04, 7.3.02, 7.3.08, 7.5.05, 7.8.06, 7.13.05)
production-worker cases.

Usage: python tests/master_query_cases.py <cgal-master-worker>
Every producer report or mesh is checked by its independent validator (exact rational
barycentric weights, brute-force ray/triangle predicates, union-find components, exact
closest points, exact triangle/plane sections, textbook subdivision masks); tampered
reports, degenerate inputs and unsupported parameters must fail closed.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "master" / "query"
WORKER = sys.argv[1] if len(sys.argv) > 1 else ""
COUNTER = [0]


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(name: str, type_: str, unit: str = "mm", path: pathlib.Path | None = None) -> dict:
    path = path or FIXTURES / name
    fmt = {".off": "off", ".xyz": "xyz"}.get(path.suffix, "json")
    return {"artifact_id": path.stem, "type": type_, "unit": unit, "format": fmt,
            "path": str(path.resolve()), "sha256": sha256(path)}


def invoke(scratch: pathlib.Path, operation: str, inputs: list[dict], parameters: dict) -> dict:
    COUNTER[0] += 1
    output = scratch / f"run{COUNTER[0]:03d}"
    output.mkdir()
    request = {"protocol": 1, "request_id": f"query-{COUNTER[0]}", "operation": operation,
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


def validate(scratch: pathlib.Path, validator: str, candidate: dict, sources: list[dict], parameters: dict) -> dict:
    result = invoke(scratch, validator, [candidate] + sources, parameters)
    return result


def run_pair(scratch, transform, validator, inputs, parameters, mesh_output=None):
    """Runs a producer, then its validator. Returns (output path, candidate artifact)."""
    path = ok(invoke(scratch, transform, inputs, parameters))
    if mesh_output:
        candidate = artifact("", mesh_output, "mm", path)
    else:
        candidate = artifact("", "GeometryQueryReport" if not transform.startswith("spatial") else "SpatialQueryReport",
                             "none", path)
    verdict = json.loads(ok(invoke(scratch, validator, [candidate] + inputs, parameters)).read_text("utf-8"))
    assert verdict["status"] == "pass" and verdict["passed"] is True, verdict
    assert verdict["validator"] == validator, verdict
    assert verdict["checks"] and all(verdict["checks"].values()), verdict
    return path, candidate


def tamper(scratch, report_path, kind, mutate):
    report = json.loads(report_path.read_text("utf-8"))
    mutate(report["results"])
    path = scratch / f"tampered{COUNTER[0]}.json"
    path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    return artifact("", kind, "none", path)


def tamper_mesh(scratch, mesh_path, type_, mutate_vertex_line):
    lines = mesh_path.read_text("utf-8").splitlines()
    lines[3] = mutate_vertex_line(lines[3])
    path = scratch / f"tampered{COUNTER[0]}.off"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return artifact("", type_, "mm", path)


def shift_x(line: str) -> str:
    parts = line.split()
    return " ".join([repr(float(parts[0]) + 0.01)] + parts[1:])


def vcount(path: pathlib.Path) -> tuple[int, int]:
    header = path.read_text("utf-8").split("\n")[1].split()
    return int(header[0]), int(header[1])


def main() -> None:
    manifest = json.loads(subprocess.run([WORKER, "--manifest"], text=True, encoding="utf-8",
                                         capture_output=True, timeout=30, check=True).stdout)
    operations = {operation["id"]: operation for operation in manifest["operations"]}
    pairs = {
        "shape.barycentric": "shape.validate.barycentric",
        "spatial.aabb.intersections": "spatial.validate.aabb_intersections",
        "mesh.components.label": "mesh.validate.components_label",
        "mesh.components.component": "mesh.validate.components_component",
        "mesh.components.keep_largest": "mesh.validate.components_keep_largest",
        "mesh.location.locate": "mesh.validate.location",
        "mesh.slice.compute": "mesh.validate.slice",
        "mesh.subdivide.catmull_clark": "mesh.validate.catmull_clark",
        "mesh.subdivide.loop": "mesh.validate.loop",
    }
    for transform, validator in pairs.items():
        assert operations[transform]["revision"] == 1, transform
        assert operations[transform]["info"]["validators"] == [validator], transform
        assert operations[validator]["role"] == "validator", validator

    cube = artifact("cube12.off", "TriangleSurfaceMesh")
    tetra = artifact("tetra.off", "TriangleSurfaceMesh")
    three = artifact("three_components.off", "TriangleSurfaceMesh")
    open_square = artifact("square_open.off", "TriangleSurfaceMesh")
    quad_box = artifact("quad_box.off", "PolygonSoup3")
    hexagon = artifact("hexagon.json", "Polygon2")
    polygon_l = artifact("polygon_l.json", "Polygon2")
    queries = artifact("bary_queries.json", "PointSet2")
    queries_l = artifact("bary_queries_l.json", "PointSet2")
    with tempfile.TemporaryDirectory(prefix="cgal-query-cases-") as directory:
        scratch = pathlib.Path(directory)

        # 7.13.05 Barycentric_coordinates_2: Wachspress / discrete harmonic / mean value.
        report = {}
        for method in ("wachspress", "discrete_harmonic", "mean_value"):
            path, candidate = run_pair(scratch, "shape.barycentric", pairs["shape.barycentric"],
                                       [hexagon, queries], {"method": method})
            data = json.loads(path.read_text("utf-8"))
            assert len(data["results"]) == 5, data
            for entry in data["results"]:
                assert abs(sum(entry["coordinates"]) - 1) < 1e-12, entry
                assert all(c > 0 for c in entry["coordinates"]), entry
            report[method] = (path, candidate)
            # The hexagon is point-symmetric about the origin, so the central weights are too.
            centre = data["results"][0]["coordinates"]
            assert all(abs(centre[i] - centre[i + 3]) < 1e-12 for i in range(3)), centre
        run_pair(scratch, "shape.barycentric", pairs["shape.barycentric"], [polygon_l, queries_l],
                 {"method": "mean_value"})
        bad = tamper(scratch, report["wachspress"][0], "GeometryQueryReport",
                     lambda r: r[1]["coordinates"].__setitem__(0, r[1]["coordinates"][0] + 1e-3))
        error(invoke(scratch, pairs["shape.barycentric"], [bad, hexagon, queries], {"method": "wachspress"}),
              "COORDINATE_MISMATCH", "VALIDATION_FAILED")
        error(invoke(scratch, pairs["shape.barycentric"], [report["wachspress"][1], hexagon, queries],
                     {"method": "discrete_harmonic"}), "PARAMETER_MISMATCH", "VALIDATION_FAILED")
        error(invoke(scratch, "shape.barycentric", [artifact("polygon_clockwise.json", "Polygon2"), queries],
                     {"method": "wachspress"}), "POLYGON_NOT_COUNTERCLOCKWISE", "PRECONDITION_FAILED")
        error(invoke(scratch, "shape.barycentric", [artifact("polygon_bowtie.json", "Polygon2"), queries],
                     {"method": "mean_value"}), "POLYGON_NOT_SIMPLE", "PRECONDITION_FAILED")
        error(invoke(scratch, "shape.barycentric", [polygon_l, queries_l], {"method": "wachspress"}),
              "POLYGON_NOT_STRICTLY_CONVEX", "PRECONDITION_FAILED")
        error(invoke(scratch, "shape.barycentric", [hexagon, artifact("bary_query_outside.json", "PointSet2")],
                     {"method": "wachspress"}), "QUERY_NOT_STRICTLY_INSIDE", "PRECONDITION_FAILED")
        error(invoke(scratch, "shape.barycentric", [hexagon, artifact("bary_query_boundary.json", "PointSet2")],
                     {"method": "wachspress"}), "QUERY_NOT_STRICTLY_INSIDE", "PRECONDITION_FAILED")

        # 7.2.04 AABB_tree intersection candidates (do_intersect / any / all intersected primitives).
        rays = artifact("rays.json", "RayBatch3")
        path, candidate = run_pair(scratch, "spatial.aabb.intersections", pairs["spatial.aabb.intersections"],
                                   [cube, rays], {})
        data = json.loads(path.read_text("utf-8"))["results"]
        flags = [entry["do_intersect"] for entry in data]
        assert flags == [True, False, True, True, True, True, True], flags
        assert data[1]["any_face"] is None and data[1]["faces"] == [], data[1]
        assert all(entry["faces"] == sorted(set(entry["faces"])) for entry in data)
        bad = tamper(scratch, path, "SpatialQueryReport", lambda r: r[1].__setitem__("do_intersect", True))
        error(invoke(scratch, pairs["spatial.aabb.intersections"], [bad, cube, rays], {}),
              "DO_INTERSECT_MISMATCH", "VALIDATION_FAILED")
        bad = tamper(scratch, path, "SpatialQueryReport", lambda r: r[0]["faces"].pop())
        error(invoke(scratch, pairs["spatial.aabb.intersections"], [bad, cube, rays], {}),
              "INTERSECTED_PRIMITIVES_MISMATCH", "VALIDATION_FAILED")
        error(invoke(scratch, pairs["spatial.aabb.intersections"], [candidate, tetra, rays], {}),
              "SOURCE_MISMATCH", "VALIDATION_FAILED")

        # 7.3.02 Polygon_mesh_processing connected components.
        path, candidate = run_pair(scratch, "mesh.components.label", pairs["mesh.components.label"], [three], {})
        data = json.loads(path.read_text("utf-8"))["results"]
        assert data["component_count"] == 3 and sorted(data["component_sizes"]) == [1, 4, 4], data
        bad = tamper(scratch, path, "GeometryQueryReport",
                     lambda r: r["face_labels"].__setitem__(0, r["face_labels"][4]))
        error(invoke(scratch, pairs["mesh.components.label"], [bad, three], {}),
              "PARTITION_MISMATCH", "VALIDATION_FAILED")
        bad = tamper(scratch, path, "GeometryQueryReport", lambda r: r.__setitem__("component_count", 2))
        error(invoke(scratch, pairs["mesh.components.label"], [bad, three], {}),
              "COMPONENT_COUNT_MISMATCH", "VALIDATION_FAILED")
        comp_path, comp = run_pair(scratch, "mesh.components.component", pairs["mesh.components.component"],
                                   [three], {"face": 4}, "TriangleSurfaceMesh")
        assert vcount(comp_path) == (4, 4), vcount(comp_path)
        error(invoke(scratch, pairs["mesh.components.component"], [comp, three], {"face": 0}),
              "FACE_SET_MISMATCH", "VALIDATION_FAILED")
        keep_path, keep = run_pair(scratch, "mesh.components.keep_largest", pairs["mesh.components.keep_largest"],
                                   [three], {"count": 2}, "TriangleSurfaceMesh")
        assert vcount(keep_path) == (8, 8), vcount(keep_path)
        error(invoke(scratch, pairs["mesh.components.keep_largest"], [comp, three], {"count": 2}),
              "FACE_SET_MISMATCH", "VALIDATION_FAILED")
        error(invoke(scratch, "mesh.components.keep_largest", [three], {"count": 1}),
              "AMBIGUOUS_COMPONENT_TIE", "PRECONDITION_FAILED")
        error(invoke(scratch, "mesh.components.component", [three], {"face": 9}), "INVALID_PARAMETER", "INVALID_REQUEST")

        # 7.3.08 Polygon_mesh_processing locate (face + barycentric coordinates).
        points = artifact("locate_queries.xyz", "PointSet3")
        for strategy in ("locate", "locate_with_AABB_tree"):
            path, candidate = run_pair(scratch, "mesh.location.locate", pairs["mesh.location.locate"],
                                       [cube, points], {"strategy": strategy})
        data = json.loads(path.read_text("utf-8"))["results"]
        assert data[0]["squared_distance"] == "9", data[0]
        bad = tamper(scratch, path, "GeometryQueryReport", lambda r: r[0].__setitem__("squared_distance", "8"))
        error(invoke(scratch, pairs["mesh.location.locate"], [bad, cube, points], {"strategy": "locate_with_AABB_tree"}),
              "DISTANCE_MISMATCH", "VALIDATION_FAILED")
        bad = tamper(scratch, path, "GeometryQueryReport", lambda r: r[0].__setitem__("face", (r[0]["face"] + 5) % 12))
        failure = invoke(scratch, pairs["mesh.location.locate"], [bad, cube, points], {"strategy": "locate_with_AABB_tree"})
        assert failure["status"] == "error" and failure["error"]["class"] == "VALIDATION_FAILED", failure

        # 7.5.05 Polygon_mesh_slicer.
        plane = {"normal": [0, 0, 1], "offset": {"value": 1, "unit": "mm"}}
        path, candidate = run_pair(scratch, "mesh.slice.compute", pairs["mesh.slice.compute"], [cube], plane)
        data = json.loads(path.read_text("utf-8"))["results"]
        assert data["polylines"] and all(line["closed"] for line in data["polylines"]), data
        diagonal = {"normal": [1, 1, 1], "offset": {"value": 3, "unit": "mm"}}
        run_pair(scratch, "mesh.slice.compute", pairs["mesh.slice.compute"], [cube], diagonal)
        run_pair(scratch, "mesh.slice.compute", pairs["mesh.slice.compute"], [open_square],
                 {"normal": [1, 0, 0], "offset": {"value": 1, "unit": "mm"}})
        bad = tamper(scratch, path, "GeometryQueryReport", lambda r: r["polylines"].pop())
        error(invoke(scratch, pairs["mesh.slice.compute"], [bad, cube], plane), "SECTION_NOT_COVERED", "VALIDATION_FAILED")
        bad = tamper(scratch, path, "GeometryQueryReport",
                     lambda r: r["polylines"][0]["points"][0].__setitem__(2, "3/2"))
        failure = invoke(scratch, pairs["mesh.slice.compute"], [bad, cube], plane)
        assert failure["status"] == "error" and failure["error"]["class"] == "VALIDATION_FAILED", failure
        error(invoke(scratch, pairs["mesh.slice.compute"], [candidate, cube],
                     {"normal": [0, 0, 1], "offset": {"value": 0.5, "unit": "mm"}}), "PARAMETER_MISMATCH", "VALIDATION_FAILED")
        error(invoke(scratch, "mesh.slice.compute", [cube], {"normal": [0, 0, 1], "offset": {"value": 0, "unit": "mm"}}),
              "COPLANAR_FACE", "PRECONDITION_FAILED")
        error(invoke(scratch, "mesh.slice.compute", [cube], {"normal": [0, 0, 0], "offset": {"value": 1, "unit": "mm"}}),
              "ZERO_NORMAL", "PRECONDITION_FAILED")

        # 7.8.06 Subdivision_method_3: Loop and Catmull-Clark (closed and open meshes).
        for steps in (1, 2):
            loop_path, loop = run_pair(scratch, "mesh.subdivide.loop", pairs["mesh.subdivide.loop"], [tetra],
                                       {"steps": steps}, "TriangleSurfaceMesh")
            assert vcount(loop_path)[1] == 4 * 4 ** steps, vcount(loop_path)
        run_pair(scratch, "mesh.subdivide.loop", pairs["mesh.subdivide.loop"], [open_square], {"steps": 2},
                 "TriangleSurfaceMesh")
        cc_path, cc = run_pair(scratch, "mesh.subdivide.catmull_clark", pairs["mesh.subdivide.catmull_clark"],
                               [quad_box], {"steps": 1}, "PolygonSoup3")
        assert vcount(cc_path)[1] == 24, vcount(cc_path)
        run_pair(scratch, "mesh.subdivide.catmull_clark", pairs["mesh.subdivide.catmull_clark"], [quad_box],
                 {"steps": 2}, "PolygonSoup3")
        run_pair(scratch, "mesh.subdivide.catmull_clark", pairs["mesh.subdivide.catmull_clark"], [tetra],
                 {"steps": 1}, "PolygonSoup3")
        error(invoke(scratch, pairs["mesh.subdivide.loop"], [loop, tetra], {"steps": 1}),
              "COUNT_MISMATCH", "VALIDATION_FAILED")
        moved = tamper_mesh(scratch, loop_path, "TriangleSurfaceMesh", shift_x)
        error(invoke(scratch, pairs["mesh.subdivide.loop"], [moved, tetra], {"steps": 2}),
              "FACE_NOT_MATCHED", "VALIDATION_FAILED")
        moved = tamper_mesh(scratch, cc_path, "PolygonSoup3", shift_x)
        error(invoke(scratch, pairs["mesh.subdivide.catmull_clark"], [moved, quad_box], {"steps": 1}),
              "FACE_NOT_MATCHED", "VALIDATION_FAILED")
        failure = invoke(scratch, "mesh.subdivide.loop", [quad_box], {"steps": 1})
        assert failure["status"] == "error", failure
        error(invoke(scratch, "mesh.subdivide.loop", [tetra], {"steps": 9}), "INVALID_PARAMETER", "INVALID_REQUEST")
    print("master query cases passed")


if __name__ == "__main__":
    main()
