"""Real CGAL 6.2.1 Wave E production-worker cases (family 7.14 meshing).

mesh2.refine.delaunay (Mesh_2) and mesh.surface.generate (Surface_mesher make_surface_mesh over a
fixed enumerated set of typed implicit domains) run with their mandatory, independent validators.
Known-value assertions are recomputed in Python from the produced files (exact rational area,
angles and boundary chains for Mesh_2; analytic sphere/ellipsoid/torus area, volume, genus and
point-to-surface distances for surfaces). Negative controls cover tampered candidates, invalid
parameters and invalid (self-intersecting, degenerate, unknown or expression-like) domains.
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
    assert {TRANSFORM, VALIDATOR, SURF_GENERATE, SURF_VALIDATOR} <= operations.keys()
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
        assert coarse_triangles < 231 <= len(mesh_fine["triangles"]),             (coarse_triangles, len(mesh_fine["triangles"]))
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
                (FIXTURES / "hole_far_outside.json", "HOLE_OUTSIDE_DOMAIN"),
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
        surface_cases(scratch)
    print("PASS master Wave E worker cases")


# ---------------------------------------------------------------------------
# 7.14.02 surface mesh generation (Surface_mesher make_surface_mesh)
# ---------------------------------------------------------------------------

SURF_GENERATE = "mesh.surface.generate"
SURF_VALIDATOR = "mesh.validate.surface_mesh"
SURF_DOMAIN = "ImplicitSurfaceDomain"
SURF_MESH = "TriangleSurfaceMesh"

# Analytic references recomputed here, independently of the worker.
SPHERE_R = 2.0
ELLIPSOID = (3.0, 2.0, 1.5)
TORUS = (3.0, 1.0)


def surface_params(angle: float, size: float, distance: float) -> dict:
    return {"angle_bound": angle, "size_bound": mm(size), "distance_bound": mm(distance)}


def read_off(path: pathlib.Path) -> tuple[list[list[float]], list[list[int]]]:
    tokens = path.read_text("utf-8").split()
    assert tokens[0] == "OFF", tokens[:1]
    vertex_count, face_count = int(tokens[1]), int(tokens[2])
    numbers = tokens[4:]
    vertices = [[float(numbers[3 * i + k]) for k in range(3)] for i in range(vertex_count)]
    base = 3 * vertex_count
    faces, position = [], base
    for _ in range(face_count):
        size = int(numbers[position])
        faces.append([int(value) for value in numbers[position + 1:position + 1 + size]])
        position += 1 + size
    assert position == len(numbers), "trailing OFF tokens"
    return vertices, faces


def write_off(scratch: pathlib.Path, vertices, faces) -> dict:
    COUNTER[0] += 1
    path = scratch / f"tampered{COUNTER[0]:03d}.off"
    lines = ["OFF", f"{len(vertices)} {len(faces)} 0"]
    lines += [" ".join(repr(float(c)) for c in v) for v in vertices]
    lines += [" ".join(str(i) for i in [len(f), *f]) for f in faces]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"artifact_id": path.stem, "type": SURF_MESH, "unit": "mm", "format": "off",
            "path": str(path.resolve()), "sha256": sha256(path)}


def surface_distance_python(kind: str, point) -> float:
    x, y, z = point
    if kind == "sphere":
        return abs(math.sqrt(x * x + y * y + z * z) - SPHERE_R)
    if kind == "torus":
        return abs(math.hypot(math.hypot(x, y) - TORUS[0], z) - TORUS[1])
    a, b, c = ELLIPSOID  # algebraic first-order distance (Sampson); exact enough at 1e-6
    f = x * x / (a * a) + y * y / (b * b) + z * z / (c * c) - 1.0
    g = math.sqrt((2 * x / (a * a)) ** 2 + (2 * y / (b * b)) ** 2 + (2 * z / (c * c)) ** 2)
    return abs(f) / g


def mesh_summary(vertices, faces) -> dict:
    """Independent Python recomputation: topology, area, volume, angles, circumradii."""
    edges: dict[tuple[int, int], list[int]] = {}
    area = volume = 0.0
    smallest = 180.0
    largest_circumradius = 0.0
    for a, b, c in faces:
        pa, pb, pc = vertices[a], vertices[b], vertices[c]
        u = [pb[k] - pa[k] for k in range(3)]
        v = [pc[k] - pa[k] for k in range(3)]
        w = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        area += math.sqrt(sum(t * t for t in w)) / 2
        volume += sum(pa[k] * (pb[(k + 1) % 3] * pc[(k + 2) % 3] - pb[(k + 2) % 3] * pc[(k + 1) % 3])
                      for k in range(3)) / 6.0
        lengths = [math.dist(pa, pb), math.dist(pb, pc), math.dist(pc, pa)]
        twice = math.sqrt(sum(t * t for t in w))
        largest_circumradius = max(largest_circumradius, lengths[0] * lengths[1] * lengths[2] / (2 * twice))
        for i, p in enumerate((a, b, c)):
            q, r = (a, b, c)[(i + 1) % 3], (a, b, c)[(i + 2) % 3]
            e1 = [vertices[q][k] - vertices[p][k] for k in range(3)]
            e2 = [vertices[r][k] - vertices[p][k] for k in range(3)]
            cosine = sum(e1[k] * e2[k] for k in range(3)) / (math.hypot(*e1) * math.hypot(*e2))
            smallest = min(smallest, math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
        for i in range(3):
            edges.setdefault(tuple(sorted(((a, b, c)[i], (a, b, c)[(i + 1) % 3]))), []).append(1)
    assert all(len(owners) == 2 for owners in edges.values()), "surface is not closed and manifold"
    return {"area": area, "volume": volume, "euler": len(vertices) - len(edges) + len(faces),
            "min_angle": smallest, "max_circumradius": largest_circumradius}


def run_surface_pair(scratch, domain, parameters):
    """Generate and validate; return (report, mesh dict, metrics, candidate artifact)."""
    result = invoke(scratch, SURF_GENERATE, [domain], parameters)
    output, path = ok(result)
    assert output["type"] == SURF_MESH and output["format"] == "off" and output["unit"] == "mm", output
    candidate = produced(output, path)
    validation = invoke(scratch, SURF_VALIDATOR, [candidate, domain], parameters)
    _, validation_path = ok(validation)
    report = json.loads(validation_path.read_text("utf-8"))
    assert report["status"] == "pass" and report["passed"] is True, report
    assert report["checks"] and all(report["checks"].values()) and len(report["checks"]) == 16, report
    assert report["validator"] == SURF_VALIDATOR, report
    vertices, faces = read_off(path)
    return report, (vertices, faces), result["metrics"], candidate


def surface_cases(scratch: pathlib.Path) -> None:
    sphere = artifact(FIXTURES / "domain_sphere.json", SURF_DOMAIN)
    sphere_big = artifact(FIXTURES / "domain_sphere_r25.json", SURF_DOMAIN)
    ellipsoid = artifact(FIXTURES / "domain_ellipsoid.json", SURF_DOMAIN)
    torus = artifact(FIXTURES / "domain_torus.json", SURF_DOMAIN)
    sphere_parameters = surface_params(25.0, 0.5, 0.05)

    # --- sphere r = 2: closed genus-0 surface with analytic area 16 pi and volume 32 pi / 3 -----
    report, (vertices, faces), metrics, sphere_candidate = run_surface_pair(
        scratch, sphere, sphere_parameters)
    facts = mesh_summary(vertices, faces)
    assert metrics["algorithm"] == "CGAL::make_surface_mesh" and metrics["domain_kind"] == "sphere", metrics
    assert metrics["vertex_count"] == len(vertices) and metrics["facet_count"] == len(faces), metrics
    assert facts["euler"] == 2 == metrics["euler_characteristic"] == report["euler_characteristic"], facts
    assert report["genus"] == 0 and report["domain_kind"] == "sphere", report
    assert max(surface_distance_python("sphere", v) for v in vertices) < 1e-6, "vertex off the sphere"
    assert facts["volume"] > 0, "mesh is not outward oriented"
    assert abs(facts["area"] - 4 * math.pi * SPHERE_R ** 2) / (4 * math.pi * SPHERE_R ** 2) < 0.03, facts
    assert abs(facts["volume"] - 4 / 3 * math.pi * SPHERE_R ** 3) / (4 / 3 * math.pi * SPHERE_R ** 3) < 0.06
    assert abs(report["area"]["analytic"] - 4 * math.pi * 4) < 1e-9, report["area"]
    assert abs(report["volume"]["analytic"] - 4 / 3 * math.pi * 8) < 1e-9, report["volume"]
    assert abs(report["area"]["value"] - facts["area"]) < 1e-9 * facts["area"], report["area"]
    # Criteria hold on the produced mesh, recomputed here: angle >= 25 deg, circumradius <= 0.5.
    assert facts["min_angle"] >= 25.0 and facts["max_circumradius"] <= 0.5, facts
    assert abs(report["minimum_angle_degrees"] - facts["min_angle"]) < 1e-6, report
    # Facets of circumradius <= 0.5 have area <= 1.299 * 0.25, so many facets are needed.
    assert len(faces) >= math.ceil(4 * math.pi * 4 / (1.3 * 0.25)), len(faces)
    assert 3 * len(faces) == 2 * metrics["edge_count"] and len(vertices) == len(faces) // 2 + 2, (len(faces), len(vertices), metrics)
    # Deterministic: the same request reproduces the same mesh bytes (seeded oracle).
    again = ok(invoke(scratch, SURF_GENERATE, [sphere], sphere_parameters))[1]
    assert sha256(again) == sphere_candidate["sha256"], "Surface_mesher output is not deterministic"

    # --- finer criteria give a finer mesh of the same sphere (contrast pair) -------------------
    report_fine, (vertices_fine, faces_fine), _, _ = run_surface_pair(
        scratch, sphere, surface_params(25.0, 0.3, 0.02))
    assert len(faces_fine) > 2 * len(faces), (len(faces_fine), len(faces))
    assert report_fine["area"]["relative_error"] < report["area"]["relative_error"], (report_fine, report)
    assert report_fine["maximum_circumcentre_distance"] <= 0.02 + 1e-5

    # --- ellipsoid (3, 2, 1.5): vertices on the algebraic surface, volume 4 pi abc / 3 ---------
    report_e, (vertices_e, faces_e), _, ellipsoid_candidate = run_surface_pair(
        scratch, ellipsoid, surface_params(25.0, 0.6, 0.04))
    facts_e = mesh_summary(vertices_e, faces_e)
    assert facts_e["euler"] == 2 and report_e["genus"] == 0, facts_e
    assert max(surface_distance_python("ellipsoid", v) for v in vertices_e) < 1e-6
    exact_volume = 4 / 3 * math.pi * ELLIPSOID[0] * ELLIPSOID[1] * ELLIPSOID[2]
    assert abs(report_e["volume"]["analytic"] - exact_volume) < 1e-9 and facts_e["volume"] > 0
    assert abs(facts_e["volume"] - exact_volume) / exact_volume < 0.06, facts_e
    # Knud Thomsen's approximation bounds the ellipsoid area to about 1.1 percent.
    p = 1.6075
    thomsen = 4 * math.pi * (((ELLIPSOID[0] * ELLIPSOID[1]) ** p + (ELLIPSOID[0] * ELLIPSOID[2]) ** p +
                              (ELLIPSOID[1] * ELLIPSOID[2]) ** p) / 3) ** (1 / p)
    assert abs(report_e["area"]["analytic"] - thomsen) / thomsen < 0.012, (report_e["area"], thomsen)
    assert facts_e["min_angle"] >= 25.0 and facts_e["max_circumradius"] <= 0.6, facts_e

    # --- torus R = 3, r = 1: genus 1, area 4 pi^2 R r, volume 2 pi^2 R r^2 -------------------
    report_t, (vertices_t, faces_t), _, torus_candidate = run_surface_pair(
        scratch, torus, surface_params(25.0, 0.5, 0.03))
    facts_t = mesh_summary(vertices_t, faces_t)
    assert facts_t["euler"] == 0 and report_t["genus"] == 1, facts_t
    assert max(surface_distance_python("torus", v) for v in vertices_t) < 1e-6
    assert abs(report_t["area"]["analytic"] - 4 * math.pi ** 2 * 3 * 1) < 1e-9
    assert abs(report_t["volume"]["analytic"] - 2 * math.pi ** 2 * 3 * 1) < 1e-9
    assert abs(facts_t["area"] - 4 * math.pi ** 2 * 3) / (4 * math.pi ** 2 * 3) < 0.03, facts_t
    assert abs(facts_t["volume"] - 2 * math.pi ** 2 * 3) / (2 * math.pi ** 2 * 3) < 0.06, facts_t
    assert facts_t["min_angle"] >= 25.0 and facts_t["max_circumradius"] <= 0.5, facts_t

    # --- Negative controls: tampered candidates are rejected by the independent validator ------
    def tamper(mutate, base=(vertices, faces)):
        changed_vertices = [list(v) for v in base[0]]
        changed_faces = [list(f) for f in base[1]]
        mutate(changed_vertices, changed_faces)
        return write_off(scratch, changed_vertices, changed_faces)

    def drop_face(v, f):
        del f[len(f) // 3]

    def flip_one(v, f):
        f[len(f) // 2][1], f[len(f) // 2][2] = f[len(f) // 2][2], f[len(f) // 2][1]

    def flip_all(v, f):
        for face in f:
            face[1], face[2] = face[2], face[1]

    def duplicate_face(v, f):
        f.append(list(f[0]))

    def push_vertex(v, f):
        x, y, z = v[len(v) // 2]
        norm = math.sqrt(x * x + y * y + z * z)
        v[len(v) // 2] = [x * (1 + 0.05 / norm), y * (1 + 0.05 / norm), z * (1 + 0.05 / norm)]

    def scale_all(v, f):
        for vertex in v:
            vertex[:] = [1.001 * c for c in vertex]

    def repeat_vertex(v, f):
        v[1] = list(v[0])

    def add_unused_vertex(v, f):
        v.append([0.1, 0.2, 0.3])

    good = sphere_parameters
    for mutate, code in ((drop_face, "SURFACE_NOT_CLOSED"), (flip_one, "INCONSISTENT_ORIENTATION"),
                         (flip_all, "ORIENTATION_NOT_OUTWARD"), (duplicate_face, "NON_MANIFOLD_EDGE"),
                         (push_vertex, "VERTEX_OFF_SURFACE"), (scale_all, "VERTEX_OFF_SURFACE"),
                         (repeat_vertex, "REPEATED_VERTEX"), (add_unused_vertex, "UNUSED_VERTEX")):
        rejected(invoke(scratch, SURF_VALIDATOR, [tamper(mutate), sphere], good), code)
    # Mismatched domain: the sphere-r2 mesh against other domains.
    rejected(invoke(scratch, SURF_VALIDATOR, [sphere_candidate, sphere_big], good), "VERTEX_OFF_SURFACE")
    rejected(invoke(scratch, SURF_VALIDATOR, [sphere_candidate, ellipsoid], good), "VERTEX_OFF_SURFACE")
    rejected(invoke(scratch, SURF_VALIDATOR, [sphere_candidate, torus], good),
             "EULER_CHARACTERISTIC_MISMATCH")
    rejected(invoke(scratch, SURF_VALIDATOR, [torus_candidate, sphere], good),
             "EULER_CHARACTERISTIC_MISMATCH")
    rejected(invoke(scratch, SURF_VALIDATOR, [ellipsoid_candidate, sphere], good), "VERTEX_OFF_SURFACE")
    # Criteria stricter than the genuine mesh was built for.
    rejected(invoke(scratch, SURF_VALIDATOR, [sphere_candidate, sphere], surface_params(35.0, 0.5, 0.05)),
             "ANGLE_CRITERION_VIOLATED")
    rejected(invoke(scratch, SURF_VALIDATOR, [sphere_candidate, sphere], surface_params(25.0, 0.2, 0.05)),
             "SIZE_CRITERION_VIOLATED")
    rejected(invoke(scratch, SURF_VALIDATOR, [sphere_candidate, sphere], surface_params(25.0, 0.5, 0.02)),
             "DISTANCE_CRITERION_VIOLATED")
    # A coarse octahedron inscribed in the sphere is a closed, outward, genus-0 manifold with all
    # vertices on the surface and passes every criterion below, but its area is 45 percent short.
    octahedron = write_off(scratch, [[2, 0, 0], [-2, 0, 0], [0, 2, 0], [0, -2, 0], [0, 0, 2], [0, 0, -2]],
                           [[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4],
                            [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]])
    rejected(invoke(scratch, SURF_VALIDATOR, [octahedron, sphere], surface_params(30.0, 5.0, 5.0)),
             "AREA_MISMATCH")
    error(invoke(scratch, SURF_VALIDATOR, [{**sphere_candidate, "unit": "cm"}, sphere], good),
          "UNIT_MISMATCH", "TYPE_ERROR")

    # --- Negative controls: the domain set is closed; no expression or unknown kind is accepted --
    for fixture, code in (("domain_expression.json", "UNSUPPORTED_DOMAIN_KIND"),
                          ("domain_unknown_kind.json", "UNSUPPORTED_DOMAIN_KIND"),
                          ("domain_negative_radius.json", "INVALID_DOMAIN"),
                          ("domain_extra_parameter.json", "SCHEMA_MISMATCH"),
                          ("domain_thick_torus.json", "INVALID_DOMAIN"),
                          ("domain_needle_ellipsoid.json", "INVALID_DOMAIN")):
        error(invoke(scratch, SURF_GENERATE, [artifact(FIXTURES / fixture, SURF_DOMAIN)], good), code,
              "INPUT_ERROR")
    for bad in (surface_params(31.0, 0.5, 0.05), surface_params(0.0, 0.5, 0.05),
                surface_params(25.0, 0.0, 0.05), surface_params(25.0, 0.5, 0.0),
                surface_params(25.0, 0.5, 0.5),  # 0.5 > 0.1 * smallest curvature radius (2)
                {**good, "angle_bound": "25"}, {**good, "size_bound": 0.5}):
        error(invoke(scratch, SURF_GENERATE, [sphere], bad), "INVALID_PARAMETER", "INVALID_REQUEST")
    error(invoke(scratch, SURF_GENERATE, [sphere], {"angle_bound": 25.0}), "MISSING_PARAMETER",
          "INVALID_REQUEST")
    error(invoke(scratch, SURF_GENERATE, [sphere], dict(good, level_set="x*x+y*y+z*z-4")),
          "UNSUPPORTED_PARAMETER", "INVALID_REQUEST")
    error(invoke(scratch, SURF_GENERATE, [sphere],
                 dict(good, size_bound={"value": 0.5, "unit": "cm"})), "UNIT_MISMATCH", "TYPE_ERROR")
    error(invoke(scratch, SURF_GENERATE, [sphere, sphere], good), "INPUT_COUNT_MISMATCH", "TYPE_ERROR")
    error(invoke(scratch, SURF_GENERATE, [artifact(WAVE_C / "polygon_with_hole.json", DOMAIN)], good),
          "INPUT_TYPE_MISMATCH", "TYPE_ERROR")
    error(invoke(scratch, SURF_GENERATE, [sphere], surface_params(25.0, 0.01, 0.0001)),
          "MESH_SIZE_LIMIT_EXCEEDED", "RESOURCE_LIMIT")


def on_boundary(vertex) -> bool:
    x, y = vertex
    return x in (0.0, 10.0) or y in (0.0, 10.0)


if __name__ == "__main__":
    main()
