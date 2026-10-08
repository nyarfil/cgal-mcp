"""Real CGAL 6.2.1 Wave E production-worker cases (family 7.14 Mesh_2).

mesh2.refine.delaunay runs with its mandatory, independent validator. Known-value
assertions are recomputed in Python from the produced JSON (exact rational area,
angles, boundary chains). Negative controls cover tampered candidates, invalid
parameters and invalid (self-intersecting, degenerate) domains.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import pathlib
import subprocess
import sys
import tempfile
from fractions import Fraction


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "master" / "wave_e"
WAVE_C = ROOT / "tests" / "fixtures" / "master" / "wave_c"
WORKER = sys.argv[1]

TRANSFORM = "mesh2.refine.delaunay"
VALIDATOR = "mesh.validate.delaunay_refinement_2"
DOMAIN = "PolygonWithHoles2"
TRI = "Triangulation2"
ASPECT = 0.125
MIN_ANGLE = math.degrees(math.asin(math.sqrt(ASPECT)))


def mm(value: float) -> dict:
    return {"value": value, "unit": "mm"}


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: pathlib.Path, type_: str, unit: str = "mm") -> dict:
    return {"artifact_id": path.stem, "type": type_, "unit": unit, "format": "json",
            "path": str(path.resolve()), "sha256": sha256(path)}


COUNTER = [0]


def invoke(scratch: pathlib.Path, operation: str, inputs: list[dict],
           parameters: dict | None = None) -> dict:
    COUNTER[0] += 1
    output = scratch / f"run{COUNTER[0]:03d}"
    output.mkdir()
    request = {"protocol": 1, "request_id": f"wave-e-{COUNTER[0]}", "operation": operation,
               "inputs": inputs, "parameters": parameters or {},
               "output_dir": str(output.resolve()), "kernel": "package_recommended",
               "limits": {"wall_time_ms": 120000, "memory_mb": 2048}}
    process = subprocess.run([WORKER], input=json.dumps(request) + "\n", text=True,
                             encoding="utf-8", capture_output=True, timeout=300)
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


def rejected(result: dict, code: str) -> None:
    """Validator rejected the candidate and names the failed check."""
    error(result, code, "VALIDATION_FAILED")


def produced(output: dict, path: pathlib.Path) -> dict:
    return {"artifact_id": path.stem, "type": output["type"], "unit": output["unit"],
            "format": output["format"], "path": str(path.resolve()), "sha256": sha256(path)}


def params(size: float, aspect: float = ASPECT) -> dict:
    return {"aspect_bound": aspect, "size_bound": mm(size)}


def run_pair(scratch, source, parameters):
    """Run the transform and its mandatory validator; return (report, mesh, metrics, artifact)."""
    result = invoke(scratch, TRANSFORM, [source], parameters)
    output, path = ok(result)
    assert output["type"] == TRI and output["unit"] == "mm", output
    candidate = produced(output, path)
    validation = invoke(scratch, VALIDATOR, [candidate, source], parameters)
    _, validation_path = ok(validation)
    report = json.loads(validation_path.read_text("utf-8"))
    assert report["status"] == "pass" and report["passed"] is True, report
    assert report["checks"] and all(report["checks"].values()), report
    assert report["validator"] == VALIDATOR, report
    return report, json.loads(path.read_text("utf-8")), result["metrics"], candidate


def tampered(scratch: pathlib.Path, mesh: dict, mutate) -> dict:
    changed = copy.deepcopy(mesh)
    mutate(changed)
    COUNTER[0] += 1
    path = scratch / f"tampered{COUNTER[0]:03d}.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    return artifact(path, TRI)


def mesh_facts(mesh: dict) -> dict:
    """Independent Python recomputation of the facts asserted below."""
    vertices = [(Fraction(x), Fraction(y)) for x, y in mesh["vertices"]]
    twice = Fraction(0)
    smallest = 90.0
    longest = 0.0
    edges: dict[tuple[int, int], int] = {}
    for a, b, c in mesh["triangles"]:
        (ax, ay), (bx, by), (cx, cy) = vertices[a], vertices[b], vertices[c]
        signed = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        assert signed > 0, "triangle not counterclockwise"
        twice += signed
        points = [(float(x), float(y)) for x, y in (vertices[a], vertices[b], vertices[c])]
        for i in range(3):
            p, q, r = points[i], points[(i + 1) % 3], points[(i + 2) % 3]
            u = (q[0] - p[0], q[1] - p[1])
            v = (r[0] - p[0], r[1] - p[1])
            angle = math.degrees(math.acos(max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) /
                                                          (math.hypot(*u) * math.hypot(*v))))))
            smallest = min(smallest, angle)
            longest = max(longest, math.dist(p, q))
        for i in range(3):
            key = tuple(sorted((int((a, b, c)[i]), int((a, b, c)[(i + 1) % 3]))))
            edges[key] = edges.get(key, 0) + 1
    assert max(edges.values()) <= 2, "edge used by more than two triangles"
    boundary = {key for key, count in edges.items() if count == 1}
    return {"area": twice / 2, "min_angle": smallest, "max_edge": longest,
            "edges": len(edges), "boundary": boundary,
            "vertices": {(float(x), float(y)) for x, y in vertices}}


def in_circle(a, b, c, d) -> Fraction:
    """Sign-correct in-circle determinant of d against the circle through a, b, c."""
    rows = []
    for point in (a, b, c):
        dx, dy = Fraction(point[0]) - Fraction(d[0]), Fraction(point[1]) - Fraction(d[1])
        rows.append((dx, dy, dx * dx + dy * dy))
    (a1, a2, a3), (b1, b2, b3), (c1, c2, c3) = rows
    return a1 * (b2 * c3 - b3 * c2) - a2 * (b1 * c3 - b3 * c1) + a3 * (b1 * c2 - b2 * c1)


def main() -> None:
    manifest = json.loads(subprocess.run([WORKER, "--manifest"], text=True, encoding="utf-8",
                                         capture_output=True, timeout=30, check=True).stdout)
    assert manifest["actual_cgal_version"] == "6.2.1", manifest.get("actual_cgal_version")
    operations = {operation["id"]: operation for operation in manifest["operations"]}
    assert {TRANSFORM, VALIDATOR} <= operations.keys()
    for operation_id in (TRANSFORM, VALIDATOR):
        entry = operations[operation_id]
        assert entry["revision"] == 1, entry
        assert entry["supported_kernels"] == ["package_recommended"], entry
        assert entry["effective_kernel"] == \
            "CGAL::Exact_predicates_inexact_constructions_kernel", entry
    assert operations[TRANSFORM]["role"] == "transform"
    assert operations[TRANSFORM]["info"]["validators"] == [VALIDATOR]
    assert operations[VALIDATOR]["role"] == "validator"

    square = artifact(FIXTURES / "square10.json", DOMAIN)
    holed = artifact(WAVE_C / "polygon_with_hole.json", DOMAIN)
    lshape = artifact(WAVE_C / "polygon_l_shape.json", DOMAIN)
    two_holes = artifact(FIXTURES / "two_holes.json", DOMAIN)

    with tempfile.TemporaryDirectory(prefix="cgal-master-wave-e-") as temporary:
        scratch = pathlib.Path(temporary)

        # --- 10 x 10 square: area 100, corners kept, boundary split ----------------
        report, mesh, metrics, candidate = run_pair(scratch, square, params(2.0))
        facts = mesh_facts(mesh)
        assert report["area"]["exact"] == "100" and facts["area"] == 100, report
        assert metrics["algorithm"] == "CGAL::refine_Delaunay_mesh_2", metrics
        assert metrics["input_vertex_count"] == 4 and metrics["ring_count"] == 1, metrics
        assert metrics["vertex_count"] == metrics["input_vertex_count"] + metrics["steiner_vertex_count"]
        assert {(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)} <= facts["vertices"]
        # Each triangle has edges <= 2, so it covers at most sqrt(3)/4 * 4 area units.
        assert len(mesh["triangles"]) >= math.ceil(100 / math.sqrt(3.0)), len(mesh["triangles"])
        assert facts["max_edge"] <= 2.0 + 1e-12 and facts["max_edge"] == report["maximum_edge_length"]
        assert facts["min_angle"] >= MIN_ANGLE - 1e-9, facts["min_angle"]
        assert abs(facts["min_angle"] - report["minimum_angle_degrees"]) < 1e-6
        # Euler relation for a disc: T = 2V - B - 2, with B boundary edges.
        boundary = len(facts["boundary"])
        assert len(mesh["triangles"]) == 2 * len(mesh["vertices"]) - boundary - 2, (boundary,)
        assert boundary == len(mesh["constrained_edges"]) == report["boundary_edge_count"]
        # Every side of length 10 is cut into pieces of length <= 2 (at least 5 pieces).
        assert boundary >= 20, boundary
        assert all(on_boundary(mesh["vertices"][i]) and on_boundary(mesh["vertices"][j])
                   for i, j in mesh["constrained_edges"])
        assert report["boundary_maximum_deviation"] == 0.0 and report["relative_area_error"] == 0.0
        coarse_triangles = len(mesh["triangles"])

        # --- finer size bound gives a strictly finer mesh of the same domain --------
        report_fine, mesh_fine, _, _ = run_pair(scratch, square, params(1.0))
        assert report_fine["area"]["exact"] == "100"
        assert len(mesh_fine["triangles"]) > coarse_triangles
        assert mesh_facts(mesh_fine)["max_edge"] <= 1.0 + 1e-12

        # --- a tighter angle bound than the defaults still holds (0.0625, ~14.5 deg) --
        report_loose, mesh_loose, _, _ = run_pair(scratch, square, params(2.0, 0.0625))
        assert report_loose["area"]["exact"] == "100"
        assert mesh_facts(mesh_loose)["min_angle"] >= math.degrees(math.asin(0.25)) - 1e-9

        # --- 10 x 10 square with a 3 x 3 hole: area 91, two boundary loops ---------
        report_hole, mesh_hole, metrics_hole, hole_candidate = run_pair(scratch, holed, params(2.0))
        facts_hole = mesh_facts(mesh_hole)
        assert report_hole["area"]["exact"] == "91" and facts_hole["area"] == 91, report_hole
        assert report_hole["hole_count"] == 1 and metrics_hole["ring_count"] == 2
        assert metrics_hole["input_vertex_count"] == 8
        boundary_hole = len(facts_hole["boundary"])
        assert len(mesh_hole["triangles"]) == 2 * len(mesh_hole["vertices"]) - boundary_hole, boundary_hole
        assert not any(3 < x < 6 and 3 < y < 6 for x, y in facts_hole["vertices"]), \
            "a vertex lies inside the hole"
        assert {(3.0, 3.0), (3.0, 6.0), (6.0, 6.0), (6.0, 3.0)} <= facts_hole["vertices"]

        # --- L-shape: area 7, reflex corner (1,1) preserved ------------------------
        report_l, mesh_l, _, l_candidate = run_pair(scratch, lshape, params(2.0))
        assert report_l["area"]["exact"] == "7" and mesh_facts(mesh_l)["area"] == 7
        assert (1.0, 1.0) in mesh_facts(mesh_l)["vertices"]

        # --- two disjoint holes: area 100 - 4 - 4 ----------------------------------
        report_two, mesh_two, _, _ = run_pair(scratch, two_holes, params(2.0))
        assert report_two["area"]["exact"] == "92" and report_two["hole_count"] == 2
        assert mesh_facts(mesh_two)["area"] == 92

        # --- Negative controls: tampered candidates are rejected by the validator --
        def drop_triangle(m):
            """Remove an interior triangle (no constrained edge), leaving a hole in the mesh."""
            constrained = {tuple(e) for e in m["constrained_edges"]}
            for number, t in enumerate(m["triangles"]):
                if not any(tuple(sorted((t[k], t[(k + 1) % 3]))) in constrained for k in range(3)):
                    del m["triangles"][number]
                    return
            raise AssertionError("no interior triangle")

        def flip_triangle(m):
            t = m["triangles"][len(m["triangles"]) // 2]
            t[1], t[2] = t[2], t[1]

        def duplicate_triangle(m):
            m["triangles"].append(list(m["triangles"][0]))

        def drop_constraint(m):
            m["constrained_edges"].pop()

        def shift_boundary_vertex(m):
            """Move a non-corner boundary vertex off its side (no longer on the segment)."""
            corners = {(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)}
            index = next(i for i, v in enumerate(m["vertices"])
                         if on_boundary(v) and tuple(v) not in corners)
            m["vertices"][index][0] += 0.01 if m["vertices"][index][0] in (0.0, 10.0) else 0.0
            m["vertices"][index][1] += 0.01 if m["vertices"][index][1] in (0.0, 10.0) else 0.0

        def shift_corner(m):
            index = m["vertices"].index([0.0, 0.0])
            m["vertices"][index] = [0.5, 0.5]

        def flip_interior_edge(m):
            """Flip a shared diagonal: valid triangulation, but no longer Delaunay."""
            constrained = {tuple(e) for e in m["constrained_edges"]}
            owners: dict[tuple[int, int], list[int]] = {}
            for number, t in enumerate(m["triangles"]):
                for k in range(3):
                    owners.setdefault(tuple(sorted((t[k], t[(k + 1) % 3]))), []).append(number)
            vertices = m["vertices"]
            for edge, pair in sorted(owners.items()):
                if len(pair) != 2 or edge in constrained:
                    continue
                first, second = (m["triangles"][number] for number in pair)
                p = next(v for v in first if v not in edge)
                q = next(v for v in second if v not in edge)
                a, b = edge
                if in_circle(vertices[p], vertices[a], vertices[b], vertices[q]) == 0:
                    continue  # cocircular quad: both diagonals are Delaunay
                new = [[p, q, a], [p, b, q]]
                for t in new:
                    (ax, ay), (bx, by), (cx, cy) = (vertices[i] for i in t)
                    if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) <= 0:
                        t[1], t[2] = t[2], t[1]
                (ax, ay), (bx, by), (cx, cy) = (vertices[i] for i in new[0])
                if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) <= 0:
                    continue
                m["triangles"][pair[0]], m["triangles"][pair[1]] = new
                return
            raise AssertionError("no flippable edge")

        good = params(2.0)
        rejected(invoke(scratch, VALIDATOR, [tampered(scratch, mesh, drop_triangle), square], good),
                 "EULER_CHARACTERISTIC_MISMATCH")
        rejected(invoke(scratch, VALIDATOR, [tampered(scratch, mesh, flip_triangle), square], good),
                 "TRIANGLE_NOT_CCW")
        rejected(invoke(scratch, VALIDATOR, [tampered(scratch, mesh, duplicate_triangle), square], good),
                 "NON_MANIFOLD_EDGE")
        rejected(invoke(scratch, VALIDATOR, [tampered(scratch, mesh, drop_constraint), square], good),
                 "CONSTRAINT_NOT_PRESERVED")
        rejected(invoke(scratch, VALIDATOR, [tampered(scratch, mesh, shift_boundary_vertex), square], good),
                 "CONSTRAINT_NOT_PRESERVED")
        rejected(invoke(scratch, VALIDATOR, [tampered(scratch, mesh, shift_corner), square], good),
                 "DOMAIN_VERTEX_MISSING")
        # Flipped diagonal: angles stay legal for a very loose bound, but the empty-circle test fails.
        flipped = tampered(scratch, mesh_hole, flip_interior_edge)
        rejected(invoke(scratch, VALIDATOR, [flipped, holed], params(50.0, 0.001)),
                 "NOT_LOCALLY_DELAUNAY")
        # The same mesh without the flip passes the identical (loose) criteria.
        ok(invoke(scratch, VALIDATOR, [hole_candidate, holed], params(50.0, 0.001)))
        # The genuine mesh violates stricter criteria than it was built for.
        rejected(invoke(scratch, VALIDATOR, [candidate, square], params(0.5)),
                 "SIZE_CRITERION_VIOLATED")
        rejected(invoke(scratch, VALIDATOR, [candidate, square], params(2.0, 0.6)),
                 "SHAPE_CRITERION_VIOLATED")
        # A mesh of the plain square does not cover the holed domain or the L-shape.
        rejected(invoke(scratch, VALIDATOR, [candidate, holed], good), "EULER_CHARACTERISTIC_MISMATCH")
        rejected(invoke(scratch, VALIDATOR, [hole_candidate, square], good), "EULER_CHARACTERISTIC_MISMATCH")
        rejected(invoke(scratch, VALIDATOR, [l_candidate, square], good), "DOMAIN_VERTEX_MISSING")
        # Unit mismatch between candidate and source.
        error(invoke(scratch, VALIDATOR, [{**candidate, "unit": "cm"}, square], good),
              "UNIT_MISMATCH", "TYPE_ERROR")

        # --- Negative controls: invalid domains and parameters are rejected --------
        for fixture, code in (
                (WAVE_C / "polygon_bowtie.json", "SELF_INTERSECTING_DOMAIN"),
                (FIXTURES / "hole_outside.json", "SELF_INTERSECTING_DOMAIN"),
                (FIXTURES / "hole_touching.json", "SELF_INTERSECTING_DOMAIN"),
                (FIXTURES / "holes_overlapping.json", "SELF_INTERSECTING_DOMAIN"),
                (FIXTURES / "hole_nested.json", "NESTED_HOLE"),
                (FIXTURES / "fold_back.json", "SELF_INTERSECTING_DOMAIN")):
            error(invoke(scratch, TRANSFORM, [artifact(fixture, DOMAIN)], good), code,
                  "PRECONDITION_FAILED")
        for bad in ({"aspect_bound": 0.5, "size_bound": mm(2.0)},
                    {"aspect_bound": 0.0, "size_bound": mm(2.0)},
                    {"aspect_bound": "0.125", "size_bound": mm(2.0)},
                    {"aspect_bound": ASPECT, "size_bound": mm(0.0)},
                    {"aspect_bound": ASPECT, "size_bound": 2.0}):
            error(invoke(scratch, TRANSFORM, [square], bad), "INVALID_PARAMETER", "INVALID_REQUEST")
        error(invoke(scratch, TRANSFORM, [square], {"aspect_bound": ASPECT}),
              "MISSING_PARAMETER", "INVALID_REQUEST")
        error(invoke(scratch, TRANSFORM, [square], dict(good, extra=1)),
              "UNSUPPORTED_PARAMETER", "INVALID_REQUEST")
        error(invoke(scratch, TRANSFORM, [square],
                     {"aspect_bound": ASPECT, "size_bound": {"value": 2.0, "unit": "cm"}}),
              "UNIT_MISMATCH", "TYPE_ERROR")
        error(invoke(scratch, TRANSFORM, [square, square], good), "INPUT_COUNT_MISMATCH", "TYPE_ERROR")
        error(invoke(scratch, TRANSFORM, [artifact(WAVE_C / "planar_points.json", "PointSet2")], good),
              "INPUT_TYPE_MISMATCH", "TYPE_ERROR")
        # A size bound that would need too many triangles is refused up front.
        error(invoke(scratch, TRANSFORM, [square], params(0.01)),
              "MESH_SIZE_LIMIT_EXCEEDED", "RESOURCE_LIMIT")
    print("PASS master Wave E worker cases")


def on_boundary(vertex) -> bool:
    x, y = vertex
    return x in (0.0, 10.0) or y in (0.0, 10.0)


if __name__ == "__main__":
    main()
