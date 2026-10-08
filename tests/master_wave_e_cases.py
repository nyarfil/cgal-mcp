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
        tetrahedral_cases(scratch)
        volume_cases(scratch)
        polyhedral_volume_cases(scratch)
        criteria_cases(scratch)
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


# ---------------------------------------------------------------------------
# TetrahedralMesh artifact and its independent validator (foundation for 7.14.03 Mesh_3)
# ---------------------------------------------------------------------------

TET_VALIDATOR = "mesh.validate.tetrahedral_mesh"
TET_TYPE = "TetrahedralMesh"


def tet_fixture(name: str) -> dict:
    return artifact(FIXTURES / name, TET_TYPE)


def load_tet(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text("utf-8"))


def write_tet(scratch: pathlib.Path, vertices, tetrahedra, subdomains=None, raw=None) -> dict:
    COUNTER[0] += 1
    path = scratch / f"tet{COUNTER[0]:03d}.json"
    value = raw if raw is not None else {
        "vertices": vertices, "tetrahedra": tetrahedra,
        "subdomains": subdomains if subdomains is not None else [1] * len(tetrahedra)}
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    return artifact(path, TET_TYPE)


def det3(p):
    a, b, c = ([Fraction(p[i][k]) - Fraction(p[0][k]) for k in range(3)] for i in (1, 2, 3))
    return (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0]))


def tet_reference(vertices, tetrahedra) -> dict:
    """Independent recomputation: exact volume, dihedral extremes, radius-edge maximum."""
    volume = Fraction(0)
    smallest, largest, ratio, largest_radius = 180.0, 0.0, 0.0, 0.0
    for cell in tetrahedra:
        p = [vertices[i] for i in cell]
        volume += det3(p) / 6
        for i, j in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)):
            k, m = [t for t in range(4) if t not in (i, j)]
            axis = [p[j][t] - p[i][t] for t in range(3)]

            def perp(index):
                w = [p[index][t] - p[i][t] for t in range(3)]
                f = sum(w[t] * axis[t] for t in range(3)) / sum(a * a for a in axis)
                return [w[t] - f * axis[t] for t in range(3)]
            u, w = perp(k), perp(m)
            cosine = sum(u[t] * w[t] for t in range(3)) / (math.hypot(*u) * math.hypot(*w))
            angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
            smallest, largest = min(smallest, angle), max(largest, angle)
        # circumradius from the circumcentre linear system (Cramer's rule in floats)
        a, b, c = ([p[i][t] - p[0][t] for t in range(3)] for i in (1, 2, 3))
        rows = [[2 * x for x in v] for v in (a, b, c)]
        rhs = [sum(x * x for x in v) for v in (a, b, c)]

        def det(m):
            return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                    - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                    + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

        def column(index):
            m = [r[:] for r in rows]
            for r in range(3):
                m[r][index] = rhs[r]
            return det(m)
        d = det(rows)
        radius = math.hypot(column(0) / d, column(1) / d, column(2) / d)
        shortest = min(math.dist(p[i], p[j]) for i in range(4) for j in range(i + 1, 4))
        ratio = max(ratio, radius / shortest)
        largest_radius = max(largest_radius, radius)
    return {"volume": float(volume), "min_dihedral": smallest, "max_dihedral": largest,
            "radius_edge": ratio, "max_circumradius": largest_radius}


def tet_validate(scratch, candidate, parameters=None):
    return invoke(scratch, TET_VALIDATOR, [candidate], parameters or {})


def tet_report(result) -> dict:
    _, path = ok(result)
    report = json.loads(path.read_text("utf-8"))
    assert report["status"] == "pass" and report["passed"] is True, report
    assert report["validator"] == TET_VALIDATOR and all(report["checks"].values()), report
    return report


def fix_orientation(vertices, cell):
    cell = list(cell)
    if det3([vertices[i] for i in cell]) < 0:
        cell[2], cell[3] = cell[3], cell[2]
    return cell


def tetrahedral_cases(scratch: pathlib.Path) -> None:
    def near(a, b, tol=1e-9):
        return abs(a - b) <= tol * max(1.0, abs(b))
    # Known-value fixtures: (name, volume, tetrahedron count, vertex count, boundary face count).
    known = [("tet_single.json", Fraction(1, 6), 1, 4, 4),
             ("tet_cube6.json", Fraction(1), 6, 8, 12),
             ("tet_cube5.json", Fraction(1), 5, 8, 12),
             ("tet_octahedron.json", Fraction(4, 3), 8, 7, 8)]
    for name, volume, cells, vertex_count, boundary in known:
        data = load_tet(name)
        reference = tet_reference(data["vertices"], data["tetrahedra"])
        assert reference["volume"] == float(volume), (name, reference)
        report = tet_report(tet_validate(scratch, tet_fixture(name), {"domain_volume": float(volume)}))
        assert report["tetrahedron_count"] == cells and report["vertex_count"] == vertex_count, report
        assert report["boundary_face_count"] == boundary, report
        assert near(report["volume"]["value"], float(volume)), report
        assert report["volume"]["relative_error"] < 1e-12, report
        assert report["boundary_euler_characteristic"] == 2 and report["boundary_genus"] == 0, report
        assert report["euler_characteristic"] == 1, report
        assert near(report["minimum_dihedral_angle_degrees"], reference["min_dihedral"], 1e-7), (name, report, reference)
        assert near(report["maximum_dihedral_angle_degrees"], reference["max_dihedral"], 1e-7), (name, report, reference)
        assert near(report["maximum_radius_edge_ratio"], reference["radius_edge"], 1e-7), (name, report, reference)
        assert "domain_volume" in report["criteria_enforced"], report
    # Single corner tetrahedron: dihedral angles 90 and acos(1/sqrt(3)), radius-edge sqrt(3)/2.
    single = tet_report(tet_validate(scratch, tet_fixture("tet_single.json")))
    assert near(single["minimum_dihedral_angle_degrees"], math.degrees(math.acos(1 / math.sqrt(3))), 1e-9)
    assert near(single["maximum_dihedral_angle_degrees"], 90.0, 1e-9)
    assert near(single["maximum_radius_edge_ratio"], math.sqrt(3) / 2, 1e-9)
    assert single["criteria_enforced"] == [] and "domain_volume_matches" not in single["checks"], single
    # Subdomain bookkeeping.
    two = tet_report(tet_validate(scratch, tet_fixture("tet_cube6_two_subdomains.json"),
                                  {"domain_volume": 1.0}))
    assert two["subdomains"]["1"]["cell_count"] == 3 and two["subdomains"]["2"]["cell_count"] == 3, two
    assert near(two["subdomains"]["1"]["volume"], 0.5) and near(two["subdomains"]["2"]["volume"], 0.5)
    # Optional criteria: enforced when requested, rejected when violated.
    tet_report(tet_validate(scratch, tet_fixture("tet_single.json"),
                            {"minimum_dihedral_angle": 54.0, "maximum_radius_edge_ratio": 0.87,
                             "minimum_tetrahedron_volume": 0.16}))
    for bad, code in (({"minimum_dihedral_angle": 55.0}, "DIHEDRAL_ANGLE_VIOLATED"),
                      ({"maximum_radius_edge_ratio": 0.8}, "RADIUS_EDGE_VIOLATED"),
                      ({"minimum_tetrahedron_volume": 0.17}, "MINIMUM_VOLUME_VIOLATED"),
                      ({"domain_volume": 1.0 / 6.0 * 1.001}, "DOMAIN_VOLUME_MISMATCH")):
        rejected(tet_validate(scratch, tet_fixture("tet_single.json"), bad), code)
    tet_report(tet_validate(scratch, tet_fixture("tet_single.json"),
                            {"domain_volume": 1.0 / 6.0 * 1.001, "volume_relative_tolerance": 0.01}))
    rejected(tet_validate(scratch, tet_fixture("tet_cube6.json"), {"domain_volume": 1.1}),
             "DOMAIN_VOLUME_MISMATCH")

    cube = load_tet("tet_cube6.json")
    cv, ct = cube["vertices"], cube["tetrahedra"]
    octa = load_tet("tet_octahedron.json")
    # Inverted and degenerate cells.
    swapped = [list(t) for t in ct]
    swapped[2][1], swapped[2][2] = swapped[2][2], swapped[2][1]
    rejected(tet_validate(scratch, write_tet(scratch, cv, swapped)), "INVERTED_TETRAHEDRON")
    flat = [list(v) for v in cv]
    flat[7] = [0.5, 0.5, 0.0]  # every tetrahedron through vertex 7 becomes coplanar
    rejected(tet_validate(scratch, write_tet(scratch, flat, ct)), "DEGENERATE_TETRAHEDRON")
    repeated = [list(t) for t in ct]
    repeated[0][3] = repeated[0][0]
    rejected(tet_validate(scratch, write_tet(scratch, cv, repeated)), "DEGENERATE_TETRAHEDRON")
    # Hole: removing one tetrahedron leaves a valid manifold that no longer fills the domain.
    notched = ct[:5]
    tet_report(tet_validate(scratch, write_tet(scratch, cv, notched)))
    rejected(tet_validate(scratch, write_tet(scratch, cv, notched), {"domain_volume": 1.0}),
             "DOMAIN_VOLUME_MISMATCH")
    hole = octa["tetrahedra"][:-1]
    rejected(tet_validate(scratch, write_tet(scratch, octa["vertices"], hole), {"domain_volume": 4 / 3}),
             "DOMAIN_VOLUME_MISMATCH")
    # A detached inner body (cavity wall not face-connected to the outer body) is rejected.
    cavity_vertices = [[0, 0, 0], [4, 0, 0], [0, 4, 0], [0, 0, 4], [1, 1, 1],
                       [2, 1, 1], [1, 2, 1], [1, 1, 2]]
    cavity_cells = [fix_orientation(cavity_vertices, t) for t in
                    ([0, 1, 2, 4], [0, 1, 3, 4], [0, 2, 3, 4], [1, 2, 3, 4], [5, 6, 7, 4])]
    rejected(tet_validate(scratch, write_tet(scratch, cavity_vertices, cavity_cells)), "MULTIPLE_COMPONENTS")
    # T-junction: a large tetrahedron meets two small ones across a face whose edge carries a vertex.
    tj_vertices = [[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 2], [0, 0, -2], [1, 0, 0]]
    tj_cells = [fix_orientation(tj_vertices, t) for t in ([0, 1, 2, 3], [0, 5, 2, 4], [5, 1, 2, 4])]
    rejected(tet_validate(scratch, write_tet(scratch, tj_vertices, tj_cells)), "BOUNDARY_NOT_CLOSED")
    # Duplicate and unused vertices.
    duplicate = [list(v) for v in cv] + [list(cv[0])]
    reroute = [list(t) for t in ct]
    reroute[0] = [8 if i == 0 else i for i in reroute[0]]
    rejected(tet_validate(scratch, write_tet(scratch, duplicate, reroute)), "REPEATED_VERTEX")
    rejected(tet_validate(scratch, write_tet(scratch, cv + [[5, 5, 5]], ct)), "UNUSED_VERTEX")
    # Overlap: a repeated cell, and a cell glued on the same side of a shared face.
    rejected(tet_validate(scratch, write_tet(scratch, cv, ct + [ct[0]])), "NON_MANIFOLD_FACE")
    same_side_vertices = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [0.1, 0.1, 0.1]]
    same_side = [fix_orientation(same_side_vertices, t) for t in ([0, 1, 2, 3], [1, 2, 3, 4])]
    rejected(tet_validate(scratch, write_tet(scratch, same_side_vertices, same_side)),
             "FACE_ORIENTATION_CONFLICT")
    # Cells joined only at a vertex are separate bodies.
    pinch_vertices = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [-1, 0, 0], [0, -1, 0], [0, 0, -1]]
    pinch = [fix_orientation(pinch_vertices, t) for t in ([0, 1, 2, 3], [0, 4, 5, 6])]
    rejected(tet_validate(scratch, write_tet(scratch, pinch_vertices, pinch)), "MULTIPLE_COMPONENTS")
    # Schema and request errors.
    good = {"vertices": cv, "tetrahedra": ct, "subdomains": [1] * 6}
    for bad_raw in (dict(good, subdomains=[1] * 5), dict(good, subdomains=[0] * 6),
                    dict(good, subdomains=[1.5] * 6), dict(good, subdomains=[True] * 6),
                    {key: good[key] for key in ("vertices", "tetrahedra")}, dict(good, extra=1)):
        error(tet_validate(scratch, write_tet(scratch, None, None, raw=bad_raw)), "SCHEMA_MISMATCH",
              "INPUT_ERROR")
    error(tet_validate(scratch, write_tet(scratch, None, None,
                                          raw=dict(good, tetrahedra=[], subdomains=[]))),
          "TETRAHEDRON_LIMIT_EXCEEDED", "RESOURCE_LIMIT")
    error(tet_validate(scratch, write_tet(scratch, None, None,
                                          raw=dict(good, tetrahedra=[[0, 1, 2, 99]] * 6))),
          "INDEX_OUT_OF_RANGE", "INPUT_ERROR")
    error(tet_validate(scratch, dict(tet_fixture("tet_single.json"), unit="inch")), "UNSUPPORTED_UNIT",
          "TYPE_ERROR")
    good_input = tet_fixture("tet_cube6.json")
    error(invoke(scratch, TET_VALIDATOR, [good_input, good_input]), "INPUT_COUNT_MISMATCH", "TYPE_ERROR")
    error(invoke(scratch, TET_VALIDATOR, [artifact(WAVE_C / "planar_points.json", "PointSet2")]),
          "INPUT_TYPE_MISMATCH", "TYPE_ERROR")
    error(tet_validate(scratch, good_input, {"volume_relative_tolerance": 0.01}), "INVALID_PARAMETER",
          "INVALID_REQUEST")
    for bad in ({"domain_volume": -1.0}, {"domain_volume": "1"}, {"minimum_dihedral_angle": 80.0},
                {"maximum_radius_edge_ratio": 0.5}):
        error(tet_validate(scratch, good_input, bad), "INVALID_PARAMETER", "INVALID_REQUEST")
    error(tet_validate(scratch, good_input, {"level_set": "x"}), "UNSUPPORTED_PARAMETER", "INVALID_REQUEST")
    # An artifact whose bytes no longer match its pinned hash is refused.
    assert tet_validate(scratch, dict(good_input, sha256="0" * 64))["status"] == "error"


# ---------------------------------------------------------------------------
# 7.14.03 tetrahedral volume mesh generation (Mesh_3 make_mesh_3) and its independent validator
# ---------------------------------------------------------------------------

VOL_GENERATE = "mesh.volume.generate"
VOL_VALIDATOR = "mesh.validate.volume_mesh"


def vol_params(angle: float, size: float, distance: float, ratio: float, cell: float) -> dict:
    return {"facet_angle": angle, "facet_size": mm(size), "facet_distance": mm(distance),
            "cell_radius_edge_ratio": ratio, "cell_size": mm(cell)}


def volume_facts(mesh: dict) -> dict:
    """Independent Python recomputation of topology and metrics of a TetrahedralMesh."""
    vertices, cells = mesh["vertices"], mesh["tetrahedra"]
    face_use: dict[tuple, list] = {}
    edges = set()
    for cell in cells:
        for slot in ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1)):
            face = tuple(cell[i] for i in slot)
            face_use.setdefault(tuple(sorted(face)), []).append(face)
        for i in range(4):
            for j in range(i + 1, 4):
                edges.add(tuple(sorted((cell[i], cell[j]))))
    assert all(len(uses) <= 2 for uses in face_use.values()), "face shared by more than two cells"
    boundary = [uses[0] for uses in face_use.values() if len(uses) == 1]
    boundary_edges: dict[tuple, int] = {}
    boundary_vertices = set()
    for face in boundary:
        boundary_vertices.update(face)
        for i in range(3):
            key = tuple(sorted((face[i], face[(i + 1) % 3])))
            boundary_edges[key] = boundary_edges.get(key, 0) + 1
    assert all(count == 2 for count in boundary_edges.values()), "boundary is not closed"
    facet_angle, facet_radius, facet_area = 180.0, 0.0, 0.0
    for a, b, c in boundary:
        pa, pb, pc = vertices[a], vertices[b], vertices[c]
        sides = [math.dist(pb, pc), math.dist(pc, pa), math.dist(pa, pb)]
        u = [pb[k] - pa[k] for k in range(3)]
        w = [pc[k] - pa[k] for k in range(3)]
        twice = math.hypot(u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        facet_area += twice / 2
        facet_radius = max(facet_radius, sides[0] * sides[1] * sides[2] / (2 * twice))
        for i in range(3):
            s1, s2 = sides[(i + 1) % 3], sides[(i + 2) % 3]
            cosine = (s1 * s1 + s2 * s2 - sides[i] * sides[i]) / (2 * s1 * s2)
            facet_angle = min(facet_angle, math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    reference = tet_reference(vertices, cells)
    return {"boundary": boundary, "boundary_vertices": boundary_vertices,
            "euler": len(vertices) - len(edges) + len(face_use) - len(cells),
            "boundary_euler": len(boundary_vertices) - len(boundary_edges) + len(boundary),
            "facet_angle": facet_angle, "facet_radius": facet_radius, "facet_area": facet_area, **reference}


def run_volume_pair(scratch, domain, parameters):
    """Generate and validate; return (report, mesh dict, metrics, candidate artifact)."""
    result = invoke(scratch, VOL_GENERATE, [domain], parameters)
    output, path = ok(result)
    assert output["type"] == TET_TYPE and output["format"] == "json" and output["unit"] == "mm", output
    candidate = produced(output, path)
    validation = invoke(scratch, VOL_VALIDATOR, [candidate, domain], parameters)
    _, validation_path = ok(validation)
    report = json.loads(validation_path.read_text("utf-8"))
    assert report["status"] == "pass" and report["passed"] is True, report
    # The count is the base set (14 checks plus 3 domain-specific ones) plus the optional criteria
    # actually requested in this call, so it is exact per call rather than a fixed constant.
    assert report["checks"] and all(report["checks"].values()), report
    assert len(report["checks"]) == 17 + sum(name in report["checks"] for name in OPTIONAL_CHECKS), report
    assert report["validator"] == VOL_VALIDATOR, report
    return report, json.loads(path.read_text("utf-8")), result["metrics"], candidate


def volume_cases(scratch: pathlib.Path) -> None:
    sphere = artifact(FIXTURES / "domain_sphere.json", SURF_DOMAIN)
    sphere_big = artifact(FIXTURES / "domain_sphere_r25.json", SURF_DOMAIN)
    ellipsoid = artifact(FIXTURES / "domain_ellipsoid.json", SURF_DOMAIN)
    torus = artifact(FIXTURES / "domain_torus.json", SURF_DOMAIN)
    sphere_parameters = vol_params(25.0, 0.5, 0.05, 3.0, 0.6)
    regular_volume = 8 / (9 * math.sqrt(3))  # volume of a regular tetrahedron per circumradius cubed

    # --- sphere r = 2: ball with analytic volume 32 pi / 3 and boundary area 16 pi -------------
    report, mesh, metrics, sphere_candidate = run_volume_pair(scratch, sphere, sphere_parameters)
    facts = volume_facts(mesh)
    vertices, cells = mesh["vertices"], mesh["tetrahedra"]
    assert metrics["algorithm"] == "CGAL::make_mesh_3" and metrics["domain_kind"] == "sphere", metrics
    assert metrics["perturbation"] is False and metrics["exudation"] is False, metrics
    assert metrics["vertex_count"] == len(vertices) and metrics["tetrahedron_count"] == len(cells), metrics
    assert metrics["boundary_facet_count"] == len(facts["boundary"]), metrics
    assert set(mesh["subdomains"]) == {1} and len(mesh["subdomains"]) == len(cells), mesh["subdomains"][:3]
    assert facts["euler"] == 1 == report["euler_characteristic"], facts
    assert facts["boundary_euler"] == 2 == report["boundary_euler_characteristic"] and report["genus"] == 0, facts
    exact = 4 / 3 * math.pi * SPHERE_R ** 3
    assert abs(report["volume"]["analytic"] - exact) < 1e-9, report["volume"]
    assert abs(facts["volume"] - report["volume"]["value"]) < 1e-9 * exact, (facts, report["volume"])
    assert abs(facts["volume"] - exact) / exact < 0.08 and facts["volume"] < exact, facts
    assert abs(report["boundary_area"]["analytic"] - 4 * math.pi * 4) < 1e-9, report["boundary_area"]
    assert abs(facts["facet_area"] - 4 * math.pi * 4) / (4 * math.pi * 4) < 0.04, facts
    for index in range(len(vertices)):
        radius = math.sqrt(sum(c * c for c in vertices[index]))
        if index in facts["boundary_vertices"]:
            assert abs(radius - SPHERE_R) < 1e-6, radius
        else:
            assert radius < SPHERE_R - 1e-6, radius
    assert facts["facet_angle"] >= 25.0 and facts["facet_radius"] <= 0.5, facts
    assert facts["max_circumradius"] <= 0.6 + 1e-9 and facts["radius_edge"] <= 3.0 + 1e-9, facts
    assert abs(report["maximum_radius_edge_ratio"] - facts["radius_edge"]) < 1e-6, report
    assert abs(report["minimum_dihedral_angle_degrees"] - facts["min_dihedral"]) < 1e-6, report
    assert len(cells) >= int(0.9 * exact / (regular_volume * 0.6 ** 3)), len(cells)
    assert len(facts["boundary"]) >= math.ceil(4 * math.pi * 4 / (1.3 * 0.25)), len(facts["boundary"])
    assert report["subdomains"]["1"]["cell_count"] == len(cells), report["subdomains"]
    # Deterministic: the same request reproduces the same mesh bytes.
    again = ok(invoke(scratch, VOL_GENERATE, [sphere], sphere_parameters))[1]
    assert sha256(again) == sphere_candidate["sha256"], "Mesh_3 output is not deterministic"

    # --- finer criteria give a finer mesh of the same ball (contrast pair) ----------------------
    report_fine, mesh_fine, _, _ = run_volume_pair(scratch, sphere, vol_params(25.0, 0.3, 0.02, 2.5, 0.3))
    assert len(mesh_fine["tetrahedra"]) > 3 * len(cells), (len(mesh_fine["tetrahedra"]), len(cells))
    assert report_fine["volume"]["relative_error"] < report["volume"]["relative_error"], (report_fine, report)
    assert report_fine["maximum_cell_circumradius"] <= 0.3 + 1e-9, report_fine
    # Another radius gives another ball.
    _, mesh_big, _, _ = run_volume_pair(scratch, sphere_big, sphere_parameters)
    assert abs(volume_facts(mesh_big)["volume"] - 4 / 3 * math.pi * 15.625) / (4 / 3 * math.pi * 15.625) < 0.08

    # --- ellipsoid (3, 2, 1.5): boundary vertices on the algebraic surface, volume 4 pi abc / 3 --
    ellipsoid_parameters = vol_params(25.0, 0.6, 0.04, 3.0, 0.8)
    report_e, mesh_e, _, ellipsoid_candidate = run_volume_pair(scratch, ellipsoid, ellipsoid_parameters)
    facts_e = volume_facts(mesh_e)
    assert facts_e["euler"] == 1 and facts_e["boundary_euler"] == 2 and report_e["genus"] == 0, facts_e
    exact_e = 4 / 3 * math.pi * ELLIPSOID[0] * ELLIPSOID[1] * ELLIPSOID[2]
    assert abs(report_e["volume"]["analytic"] - exact_e) < 1e-9, report_e["volume"]
    assert abs(facts_e["volume"] - exact_e) / exact_e < 0.08 and facts_e["volume"] < exact_e, facts_e
    for index in facts_e["boundary_vertices"]:
        assert surface_distance_python("ellipsoid", mesh_e["vertices"][index]) < 1e-6
    assert facts_e["facet_angle"] >= 25.0 and facts_e["max_circumradius"] <= 0.8 + 1e-9, facts_e

    # --- torus R = 3, r = 1: solid torus, Euler characteristic 0, volume 2 pi^2 R r^2 ---------
    torus_parameters = vol_params(25.0, 0.5, 0.03, 3.0, 0.6)
    report_t, mesh_t, _, torus_candidate = run_volume_pair(scratch, torus, torus_parameters)
    facts_t = volume_facts(mesh_t)
    assert facts_t["euler"] == 0 and facts_t["boundary_euler"] == 0 and report_t["genus"] == 1, facts_t
    exact_t = 2 * math.pi ** 2 * 3 * 1
    assert abs(report_t["volume"]["analytic"] - exact_t) < 1e-9, report_t["volume"]
    assert abs(facts_t["volume"] - exact_t) / exact_t < 0.08 and facts_t["volume"] < exact_t, facts_t
    assert abs(report_t["boundary_area"]["analytic"] - 4 * math.pi ** 2 * 3) < 1e-9
    for index in facts_t["boundary_vertices"]:
        assert surface_distance_python("torus", mesh_t["vertices"][index]) < 1e-6
    assert facts_t["facet_angle"] >= 25.0 and facts_t["max_circumradius"] <= 0.6 + 1e-9, facts_t

    # --- Negative controls: tampered meshes are rejected by the independent validator ---------
    base_cells = [list(c) for c in cells]
    face_count: dict[tuple, int] = {}
    for cell in base_cells:
        for slot in ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1)):
            key = tuple(sorted(cell[i] for i in slot))
            face_count[key] = face_count.get(key, 0) + 1
    boundary_vertex_set = {v for key, n in face_count.items() if n == 1 for v in key}
    interior_cell = next(i for i, c in enumerate(base_cells) if not set(c) & boundary_vertex_set)
    surface_cell = next(i for i, c in enumerate(base_cells) if set(c) & boundary_vertex_set)

    def tamper(vertices_fn=None, cells_fn=None, subdomains_fn=None):
        new_vertices = [list(v) for v in vertices]
        new_cells = [list(c) for c in base_cells]
        new_subdomains = list(mesh["subdomains"])
        if vertices_fn:
            vertices_fn(new_vertices)
        if cells_fn:
            cells_fn(new_cells, new_subdomains)
        if subdomains_fn:
            subdomains_fn(new_subdomains)
        return write_tet(scratch, new_vertices, new_cells, new_subdomains)

    def drop(index):
        def apply(c, s):
            del c[index]
            del s[index]
        return apply

    def flip(c, s):
        c[interior_cell][2], c[interior_cell][3] = c[interior_cell][3], c[interior_cell][2]

    def duplicate(c, s):
        c.append(list(c[interior_cell]))
        s.append(1)

    def scale_all(v):
        for vertex in v:
            vertex[:] = [1.001 * x for x in vertex]

    def push_boundary_vertex(v):
        i = min(facts["boundary_vertices"])
        x, y, z = v[i]
        norm = math.sqrt(x * x + y * y + z * z)
        v[i] = [x * (1 + 0.05 / norm), y * (1 + 0.05 / norm), z * (1 + 0.05 / norm)]

    def relabel(s):
        for i in range(0, len(s), 2):
            s[i] = 2

    good = sphere_parameters
    for candidate, code in (
            (tamper(cells_fn=drop(interior_cell)), "MULTIPLE_BOUNDARY_SURFACES"),
            (tamper(cells_fn=drop(surface_cell)), "VERTEX_OFF_SURFACE"),
            (tamper(cells_fn=flip), "INVERTED_TETRAHEDRON"),
            (tamper(cells_fn=duplicate), "NON_MANIFOLD_FACE"),
            (tamper(vertices_fn=scale_all), "VERTEX_OUTSIDE_DOMAIN"),
            (tamper(vertices_fn=push_boundary_vertex), "VERTEX_OUTSIDE_DOMAIN"),
            (tamper(subdomains_fn=relabel), "SUBDOMAIN_INDEX_INVALID")):
        rejected(invoke(scratch, VOL_VALIDATOR, [candidate, sphere], good), code)
    # Mismatched domain: the sphere mesh against other domains and other meshes against the sphere.
    rejected(invoke(scratch, VOL_VALIDATOR, [sphere_candidate, sphere_big], good), "VERTEX_OFF_SURFACE")
    rejected(invoke(scratch, VOL_VALIDATOR, [sphere_candidate, ellipsoid], good), "VERTEX_OUTSIDE_DOMAIN")
    rejected(invoke(scratch, VOL_VALIDATOR, [sphere_candidate, torus], good), "EULER_CHARACTERISTIC_MISMATCH")
    rejected(invoke(scratch, VOL_VALIDATOR, [torus_candidate, sphere], good), "EULER_CHARACTERISTIC_MISMATCH")
    rejected(invoke(scratch, VOL_VALIDATOR, [ellipsoid_candidate, sphere], ellipsoid_parameters),
             "VERTEX_OUTSIDE_DOMAIN")
    # Criteria stricter than the genuine mesh was built for.
    for stricter, code in ((vol_params(35.0, 0.5, 0.05, 3.0, 0.6), "FACET_ANGLE_VIOLATED"),
                           (vol_params(25.0, 0.3, 0.05, 3.0, 0.6), "FACET_SIZE_VIOLATED"),
                           (vol_params(25.0, 0.5, 0.02, 3.0, 0.6), "FACET_DISTANCE_VIOLATED"),
                           (vol_params(25.0, 0.5, 0.05, 3.0, 0.4), "CELL_SIZE_VIOLATED"),
                           (vol_params(25.0, 0.5, 0.05, 1.5, 0.6), "RADIUS_EDGE_VIOLATED")):
        rejected(invoke(scratch, VOL_VALIDATOR, [sphere_candidate, sphere], stricter), code)
    # A uniformly coarse octahedral mesh (6 vertices on the sphere plus the centre, 8 cells) is a
    # topologically perfect ball whose vertices lie on the surface. It violates the size criteria,
    # and with criteria loose enough to pass them its boundary area is 45 percent short.
    octa_vertices = [[2, 0, 0], [-2, 0, 0], [0, 2, 0], [0, -2, 0], [0, 0, 2], [0, 0, -2], [0, 0, 0]]
    octahedron = write_tet(
        scratch, octa_vertices,
        [fix_orientation(octa_vertices, triangle + [6]) for triangle in
         ([0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4], [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5])])
    rejected(invoke(scratch, VOL_VALIDATOR, [octahedron, sphere], good), "FACET_SIZE_VIOLATED")
    rejected(invoke(scratch, VOL_VALIDATOR, [octahedron, sphere], vol_params(30.0, 5.0, 5.0, 100.0, 50.0)),
             "AREA_MISMATCH")
    error(invoke(scratch, VOL_VALIDATOR, [{**sphere_candidate, "unit": "cm"}, sphere], good),
          "UNIT_MISMATCH", "TYPE_ERROR")
    error(invoke(scratch, VOL_VALIDATOR, [sphere_candidate, sphere], dict(good, cell_size=0.6)),
          "INVALID_PARAMETER", "INVALID_REQUEST")

    # --- Negative controls: the domain set is closed; no expression or unknown kind is accepted --
    for fixture, code in (("domain_expression.json", "UNSUPPORTED_DOMAIN_KIND"),
                          ("domain_unknown_kind.json", "UNSUPPORTED_DOMAIN_KIND"),
                          ("domain_negative_radius.json", "INVALID_DOMAIN"),
                          ("domain_extra_parameter.json", "SCHEMA_MISMATCH"),
                          ("domain_thick_torus.json", "INVALID_DOMAIN"),
                          ("domain_needle_ellipsoid.json", "INVALID_DOMAIN")):
        error(invoke(scratch, VOL_GENERATE, [artifact(FIXTURES / fixture, SURF_DOMAIN)], good), code,
              "INPUT_ERROR")
    for bad in (vol_params(31.0, 0.5, 0.05, 3.0, 0.6), vol_params(0.0, 0.5, 0.05, 3.0, 0.6),
                vol_params(25.0, 0.0, 0.05, 3.0, 0.6), vol_params(25.0, 0.5, 0.0, 3.0, 0.6),
                vol_params(25.0, 0.5, 0.5, 3.0, 0.6),  # 0.5 > 0.1 * smallest curvature radius (2)
                vol_params(25.0, 0.5, 0.05, 1.99, 0.6), vol_params(25.0, 0.5, 0.05, 3.0, 0.0),
                {**good, "facet_angle": "25"}, {**good, "cell_size": 0.6}):
        error(invoke(scratch, VOL_GENERATE, [sphere], bad), "INVALID_PARAMETER", "INVALID_REQUEST")
    error(invoke(scratch, VOL_GENERATE, [sphere], {"facet_angle": 25.0}), "MISSING_PARAMETER",
          "INVALID_REQUEST")
    error(invoke(scratch, VOL_GENERATE, [sphere], dict(good, level_set="x*x+y*y+z*z-4")),
          "UNSUPPORTED_PARAMETER", "INVALID_REQUEST")
    error(invoke(scratch, VOL_GENERATE, [sphere], dict(good, cell_size={"value": 0.6, "unit": "cm"})),
          "UNIT_MISMATCH", "TYPE_ERROR")
    error(invoke(scratch, VOL_GENERATE, [sphere, sphere], good), "INPUT_COUNT_MISMATCH", "TYPE_ERROR")
    error(invoke(scratch, VOL_GENERATE, [artifact(WAVE_C / "polygon_with_hole.json", DOMAIN)], good),
          "INPUT_TYPE_MISMATCH", "TYPE_ERROR")
    error(invoke(scratch, VOL_GENERATE, [sphere], vol_params(25.0, 0.5, 0.05, 3.0, 0.05)),
          "MESH_SIZE_LIMIT_EXCEEDED", "RESOURCE_LIMIT")

# ---------------------------------------------------------------------------
# 7.14.03 polyhedral domains (Polyhedral_mesh_domain_3 over a closed TriangleSurfaceMesh)
# ---------------------------------------------------------------------------

def poly_source(name: str, unit: str = "mm") -> dict:
    path = FIXTURES / name
    return {"artifact_id": path.stem, "type": SURF_MESH, "unit": unit, "format": "off",
            "path": str(path.resolve()), "sha256": sha256(path)}


def read_off_fixture(name: str):
    lines = (FIXTURES / name).read_text("utf-8").split("\n")
    count, face_count = (int(x) for x in lines[1].split()[:2])
    vertices = [[float(x) for x in line.split()] for line in lines[2:2 + count]]
    faces = [[int(x) for x in line.split()[1:]] for line in lines[2 + count:2 + count + face_count]]
    return vertices, faces


def point_triangle_distance_python(p, a, b, c) -> float:
    """Closest-point distance by exact barycentric clamping (independent of the worker)."""
    def sub(u, v): return [u[k] - v[k] for k in range(3)]
    def dot(u, v): return sum(x * y for x, y in zip(u, v))
    ab, ac, ap = sub(b, a), sub(c, a), sub(p, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0: return math.dist(p, a)
    bp = sub(p, b)
    d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0 and d4 <= d3: return math.dist(p, b)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3)
        return math.dist(p, [a[k] + v * ab[k] for k in range(3)])
    cp = sub(p, c)
    d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0 and d5 <= d6: return math.dist(p, c)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        w = d2 / (d2 - d6)
        return math.dist(p, [a[k] + w * ac[k] for k in range(3)])
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return math.dist(p, [b[k] + w * (c[k] - b[k]) for k in range(3)])
    denominator = 1.0 / (va + vb + vc)
    v, w = vb * denominator, vc * denominator
    return math.dist(p, [a[k] + ab[k] * v + ac[k] * w for k in range(3)])


def distance_to_off(point, vertices, faces) -> float:
    return min(point_triangle_distance_python(point, vertices[f[0]], vertices[f[1]], vertices[f[2]])
               for f in faces)


def lattice(a, b, c, divisions: int):
    for i in range(divisions + 1):
        for j in range(divisions + 1 - i):
            s, t = i / divisions, j / divisions
            yield [a[k] * (1 - s - t) + b[k] * s + c[k] * t for k in range(3)]


OPTIONAL_CHECKS = ("cell_size_regions_satisfied", "facet_topology_satisfied", "feature_edge_size_satisfied")


def run_poly_pair(scratch, source, parameters):
    result = invoke(scratch, VOL_GENERATE, [source], parameters)
    output, path = ok(result)
    assert output["type"] == TET_TYPE and output["format"] == "json" and output["unit"] == "mm", output
    candidate = produced(output, path)
    validation = invoke(scratch, VOL_VALIDATOR, [candidate, source], parameters)
    _, validation_path = ok(validation)
    report = json.loads(validation_path.read_text("utf-8"))
    assert report["status"] == "pass" and report["passed"] is True, report
    # Base 15 checks (feature mode renames five of them to scoped keys, same count) plus the optional
    # criteria requested in this call.
    assert report["checks"] and all(report["checks"].values()), report
    assert len(report["checks"]) == 15 + sum(name in report["checks"] for name in OPTIONAL_CHECKS), report
    assert report["criteria_scope"]["scoped"] is ("feature_edge_size_satisfied" in report["checks"]), report
    assert report["validator"] == VOL_VALIDATOR and report["domain_kind"] == "polyhedral", report
    return report, json.loads(path.read_text("utf-8")), result["metrics"], candidate


def polyhedral_volume_cases(scratch: pathlib.Path) -> None:
    cube_parameters = vol_params(25.0, 0.25, 0.02, 3.0, 0.3)
    fine_parameters = vol_params(25.0, 0.15, 0.01, 2.5, 0.15)
    prism_parameters = vol_params(25.0, 0.4, 0.03, 3.0, 0.5)
    box_parameters = vol_params(25.0, 0.5, 0.04, 3.0, 0.6)
    cube = poly_source("poly_cube.off")
    cube_vertices, cube_faces = read_off_fixture("poly_cube.off")

    # --- unit cube: volume 1, Euler characteristic 1, vertices on the six planes ----------------
    report, mesh, metrics, cube_candidate = run_poly_pair(scratch, cube, cube_parameters)
    facts = volume_facts(mesh)
    vertices, cells = mesh["vertices"], mesh["tetrahedra"]
    assert metrics["algorithm"] == "CGAL::make_mesh_3" and metrics["domain"] == "CGAL::Polyhedral_mesh_domain_3", metrics
    assert metrics["domain_kind"] == "polyhedral" and metrics["feature_protection"] is False, metrics
    assert metrics["perturbation"] is False and metrics["exudation"] is False, metrics
    assert metrics["source_face_count"] == 12 and metrics["source_vertex_count"] == 8, metrics
    assert abs(metrics["source_volume"] - 1.0) < 1e-12 and abs(metrics["source_area"] - 6.0) < 1e-12, metrics
    assert metrics["vertex_count"] == len(vertices) and metrics["tetrahedron_count"] == len(cells), metrics
    assert metrics["boundary_facet_count"] == len(facts["boundary"]), metrics
    assert set(mesh["subdomains"]) == {1}, mesh["subdomains"][:3]
    assert facts["euler"] == 1 == report["euler_characteristic"], facts
    assert facts["boundary_euler"] == 2 == report["boundary_euler_characteristic"] and report["genus"] == 0, facts
    assert abs(report["volume"]["source"] - 1.0) < 1e-12, report["volume"]
    assert abs(facts["volume"] - report["volume"]["value"]) < 1e-9, (facts, report["volume"])
    # Vertices lie in the closed cube; boundary vertices on a face plane, interior vertices strictly inside.
    for index, vertex in enumerate(vertices):
        assert all(-1e-9 <= c <= 1 + 1e-9 for c in vertex), vertex
        on_plane = any(min(abs(c), abs(c - 1)) < 1e-9 for c in vertex)
        assert on_plane == (index in facts["boundary_vertices"]), (index, vertex)
    # Corner and edge cutting can only remove volume: 0.9 <= V <= 1 for this mesh.
    assert 0.95 <= facts["volume"] <= 1.0 + 1e-9, facts["volume"]
    assert facts["facet_angle"] >= 25.0 and facts["facet_radius"] <= 0.25 + 1e-9, facts
    assert facts["max_circumradius"] <= 0.3 + 1e-9 and facts["radius_edge"] <= 3.0 + 1e-9, facts
    assert abs(report["maximum_radius_edge_ratio"] - facts["radius_edge"]) < 1e-6, report
    assert report["boundary_area"]["source"] == 6.0 or abs(report["boundary_area"]["source"] - 6.0) < 1e-12, report
    assert 0.8 * 6.0 <= facts["facet_area"] <= 6.0 + 1e-6, facts["facet_area"]
    # Two-sided sampled Hausdorff recomputed here by brute force.
    forward = reverse = 0.0
    for face in facts["boundary"]:
        for point in lattice(vertices[face[0]], vertices[face[1]], vertices[face[2]], 4):
            forward = max(forward, distance_to_off(point, cube_vertices, cube_faces))
    for f in cube_faces:
        for point in lattice(cube_vertices[f[0]], cube_vertices[f[1]], cube_vertices[f[2]], 8):
            reverse = min(max(reverse, min(point_triangle_distance_python(
                point, vertices[b[0]], vertices[b[1]], vertices[b[2]]) for b in facts["boundary"])), 10.0)
    assert forward <= 0.25 + 1e-9 and reverse <= 0.5 + 1e-9, (forward, reverse)
    assert abs(report["forward_hausdorff_sampled"] - forward) < 0.25 * 0.25 / 4, (report, forward)
    # Deterministic: the same request reproduces the same mesh bytes.
    again = ok(invoke(scratch, VOL_GENERATE, [cube], cube_parameters))[1]
    assert sha256(again) == cube_candidate["sha256"], "Mesh_3 polyhedral output is not deterministic"

    # --- finer criteria give a finer mesh of the same cube (contrast pair) ----------------------
    fine_report, fine_mesh, _, _ = run_poly_pair(scratch, cube, fine_parameters)
    assert len(fine_mesh["tetrahedra"]) > 2.5 * len(cells), (len(fine_mesh["tetrahedra"]), len(cells))
    assert fine_report["maximum_cell_circumradius"] <= 0.15 + 1e-9, fine_report
    assert fine_report["volume"]["relative_error"] <= report["volume"]["relative_error"] + 1e-9, (fine_report, report)

    # --- L-shaped prism (non-convex, reflex edge): volume 3 -------------------------------------
    l_source = poly_source("poly_l_prism.off")
    l_vertices, l_faces = read_off_fixture("poly_l_prism.off")
    l_report, l_mesh, l_metrics, l_candidate = run_poly_pair(scratch, l_source, prism_parameters)
    l_facts = volume_facts(l_mesh)
    assert abs(l_metrics["source_volume"] - 3.0) < 1e-12 and abs(l_metrics["source_area"] - 14.0) < 1e-12, l_metrics
    assert l_facts["euler"] == 1 and l_facts["boundary_euler"] == 2, l_facts
    assert 0.95 * 3.0 <= l_facts["volume"] <= 3.0 + 1e-9, l_facts["volume"]
    for index in l_facts["boundary_vertices"]:
        assert distance_to_off(l_mesh["vertices"][index], l_vertices, l_faces) < 1e-9
    for index, vertex in enumerate(l_mesh["vertices"]):
        if index in l_facts["boundary_vertices"]:
            continue
        x, y, z = vertex
        assert 0 < z < 1 and 0 < x < 2 and 0 < y < 2 and not (x > 1 and y > 1), vertex  # strictly inside the L
    assert l_facts["facet_angle"] >= 25.0 and l_facts["facet_radius"] <= 0.4 + 1e-9, l_facts
    assert l_facts["max_circumradius"] <= 0.5 + 1e-9 and l_facts["radius_edge"] <= 3.0 + 1e-9, l_facts

    # --- staircase prism (three reflex edges): volume 6 ----------------------------------------
    stair_source = poly_source("poly_stair_prism.off")
    stair_vertices, stair_faces = read_off_fixture("poly_stair_prism.off")
    stair_report, stair_mesh, stair_metrics, _ = run_poly_pair(scratch, stair_source, prism_parameters)
    stair_facts = volume_facts(stair_mesh)
    assert abs(stair_metrics["source_volume"] - 6.0) < 1e-12, stair_metrics
    assert stair_facts["euler"] == 1 and stair_facts["boundary_euler"] == 2, stair_facts
    assert 0.95 * 6.0 <= stair_facts["volume"] <= 6.0 + 1e-9, stair_facts["volume"]
    for index in stair_facts["boundary_vertices"]:
        assert distance_to_off(stair_mesh["vertices"][index], stair_vertices, stair_faces) < 1e-9

    # --- tilted box 1 x 2 x 3: volume 6, vertices on the six tilted planes ----------------------
    box_source = poly_source("poly_tilted_box.off")
    box_vertices, box_faces = read_off_fixture("poly_tilted_box.off")
    box_report, box_mesh, box_metrics, _ = run_poly_pair(scratch, box_source, box_parameters)
    box_facts = volume_facts(box_mesh)
    assert abs(box_metrics["source_volume"] - 6.0) < 1e-9 and abs(box_metrics["source_area"] - 22.0) < 1e-9, box_metrics
    assert box_facts["euler"] == 1 and box_facts["boundary_euler"] == 2, box_facts
    assert 0.95 * 6.0 <= box_facts["volume"] <= 6.0 + 1e-9, box_facts["volume"]
    origin = box_vertices[0]
    axes = [[box_vertices[i][k] - origin[k] for k in range(3)] for i in (1, 3, 4)]
    lengths = [math.sqrt(sum(c * c for c in axis)) for axis in axes]
    assert [round(x, 9) for x in lengths] == [1.0, 2.0, 3.0], lengths
    for index, vertex in enumerate(box_mesh["vertices"]):
        local = [sum((vertex[k] - origin[k]) * axes[i][k] for k in range(3)) / lengths[i] for i in range(3)]
        assert all(-1e-9 <= local[i] <= lengths[i] + 1e-9 for i in range(3)), local
        on_plane = any(min(abs(local[i]), abs(local[i] - lengths[i])) < 1e-9 for i in range(3))
        assert on_plane == (index in box_facts["boundary_vertices"]), (index, local)

    # --- Negative controls: tampered meshes are rejected by the independent validator ---------
    base_cells = [list(c) for c in cells]
    face_count: dict[tuple, int] = {}
    for cell in base_cells:
        for slot in ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1)):
            key = tuple(sorted(cell[i] for i in slot))
            face_count[key] = face_count.get(key, 0) + 1
    boundary_vertex_set = {v for key, n in face_count.items() if n == 1 for v in key}

    def fully_interior(cell) -> bool:
        return all(face_count[tuple(sorted(cell[i] for i in slot))] == 2
                   for slot in ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1)))
    interior_cell = next(i for i, c in enumerate(base_cells) if fully_interior(c))
    surface_cell = next(i for i, c in enumerate(base_cells) if set(c) & boundary_vertex_set)

    def tamper(vertices_fn=None, cells_fn=None, subdomains_fn=None):
        new_vertices = [list(v) for v in vertices]
        new_cells = [list(c) for c in base_cells]
        new_subdomains = list(mesh["subdomains"])
        if vertices_fn:
            vertices_fn(new_vertices)
        if cells_fn:
            cells_fn(new_cells, new_subdomains)
        if subdomains_fn:
            subdomains_fn(new_subdomains)
        return write_tet(scratch, new_vertices, new_cells, new_subdomains)

    def drop(index):
        def apply(c, s):
            del c[index]
            del s[index]
        return apply

    def flip(c, s):
        c[interior_cell][2], c[interior_cell][3] = c[interior_cell][3], c[interior_cell][2]

    def duplicate(c, s):
        c.append(list(c[interior_cell]))
        s.append(1)

    def shift_all(v):
        for vertex in v:
            vertex[0] += 0.05

    def scale_all(v):
        for vertex in v:
            vertex[:] = [1.02 * x for x in vertex]

    def bump_boundary_vertex(v):
        i = min(facts["boundary_vertices"])
        v[i][0] += -0.08 if v[i][0] < 0.5 else 0.08

    def relabel(s):
        for i in range(0, len(s), 2):
            s[i] = 2

    good = cube_parameters
    for candidate, code in (
            (tamper(cells_fn=drop(interior_cell)), "BOUNDARY_NOT_CLOSED"),
            (tamper(cells_fn=drop(surface_cell)), "FACET_DISTANCE_VIOLATED"),
            (tamper(cells_fn=flip), "INVERTED_TETRAHEDRON"),
            (tamper(cells_fn=duplicate), "NON_MANIFOLD_FACE"),
            (tamper(vertices_fn=shift_all), "VERTEX_OFF_SURFACE"),
            (tamper(vertices_fn=scale_all), "VERTEX_OFF_SURFACE"),
            (tamper(vertices_fn=bump_boundary_vertex), "VERTEX_OFF_SURFACE"),
            (tamper(subdomains_fn=relabel), "SUBDOMAIN_INDEX_INVALID")):
        rejected(invoke(scratch, VOL_VALIDATOR, [candidate, cube], good), code)
    # A mesh of one polyhedron against another.
    rejected(invoke(scratch, VOL_VALIDATOR, [cube_candidate, l_source], good), "VERTEX_OFF_SURFACE")
    rejected(invoke(scratch, VOL_VALIDATOR, [cube_candidate, box_source], good), "VERTEX_OFF_SURFACE")
    rejected(invoke(scratch, VOL_VALIDATOR, [cube_candidate, stair_source], good), "VERTEX_OFF_SURFACE")
    rejected(invoke(scratch, VOL_VALIDATOR, [l_candidate, cube], prism_parameters), "VERTEX_OFF_SURFACE")
    rejected(invoke(scratch, VOL_VALIDATOR, [l_candidate, stair_source], prism_parameters), "VERTEX_OFF_SURFACE")
    # The sub-box [0,1] x [0,2] x [0,1] of the L-prism has all 8 vertices on the prism surface but
    # fills only part of it: its boundary facets are not the prism's.
    sub_vertices = [[v[0], 2 * v[1], v[2]] for v in [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0],
                                                      [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]]]
    sub_box = write_tet(scratch, sub_vertices,
                        [[0, 1, 3, 7], [0, 1, 7, 5], [0, 2, 7, 3], [0, 2, 6, 7], [0, 4, 5, 7], [0, 4, 7, 6]])
    rejected(invoke(scratch, VOL_VALIDATOR, [sub_box, l_source], prism_parameters), "ORIENTATION_NOT_OUTWARD")
    # Criteria stricter than the genuine mesh was built for.
    for stricter, code in ((vol_params(35.0, 0.25, 0.02, 3.0, 0.3), "FACET_ANGLE_VIOLATED"),
                           (vol_params(25.0, 0.15, 0.02, 3.0, 0.3), "FACET_SIZE_VIOLATED"),
                           (vol_params(25.0, 0.25, 0.005, 3.0, 0.3), "FACET_DISTANCE_VIOLATED"),
                           (vol_params(25.0, 0.25, 0.02, 3.0, 0.2), "CELL_SIZE_VIOLATED"),
                           (vol_params(25.0, 0.25, 0.02, 1.5, 0.3), "RADIUS_EDGE_VIOLATED")):
        rejected(invoke(scratch, VOL_VALIDATOR, [cube_candidate, cube], stricter), code)
    # The six-tetrahedron cube mesh is a perfect tiling of the cube: the validator accepts it under
    # loose criteria (it does not depend on the generator) and rejects it as too coarse otherwise.
    cube6 = artifact(FIXTURES / "tet_cube6.json", TET_TYPE)
    loose = vol_params(30.0, 5.0, 5.0, 100.0, 50.0)
    loose_report = ok(invoke(scratch, VOL_VALIDATOR, [cube6, cube], loose))[1]
    loose_data = json.loads(loose_report.read_text("utf-8"))
    assert loose_data["status"] == "pass" and abs(loose_data["volume"]["value"] - 1.0) < 1e-12, loose_data
    assert loose_data["forward_hausdorff_sampled"] < 1e-9 and loose_data["reverse_hausdorff_sampled"] < 1e-9, loose_data
    rejected(invoke(scratch, VOL_VALIDATOR, [cube6, cube], good), "FACET_SIZE_VIOLATED")
    # Invalid sources are rejected by the validator as well as by the generator.
    for name, source_code, producer_code in (
            ("poly_cube_open.off", "SOURCE_MESH_NOT_CLOSED", "MESH_NOT_CLOSED"),
            ("poly_cube_inverted.off", "SOURCE_INWARD_ORIENTED_INPUT", "INWARD_ORIENTED_INPUT"),
            ("poly_cube_inconsistent.off", "SOURCE_INCONSISTENT_ORIENTATION", "INCONSISTENT_ORIENTATION"),
            ("poly_cube_self_intersecting.off", "SOURCE_SELF_INTERSECTING_INPUT", "SELF_INTERSECTING_INPUT"),
            ("poly_two_cubes.off", "SOURCE_MULTIPLE_COMPONENTS", "MULTIPLE_COMPONENTS"),
            ("poly_cube_nonmanifold.off", "SOURCE_NON_MANIFOLD_INPUT", "NON_MANIFOLD_INPUT")):
        bad_source = poly_source(name)
        error(invoke(scratch, VOL_GENERATE, [bad_source], good), producer_code, "PRECONDITION_FAILED")
        rejected(invoke(scratch, VOL_VALIDATOR, [cube_candidate, bad_source], good), source_code)
    # Parameter and type errors.
    for bad in (vol_params(31.0, 0.25, 0.02, 3.0, 0.3), vol_params(0.0, 0.25, 0.02, 3.0, 0.3),
                vol_params(25.0, 0.0, 0.02, 3.0, 0.3), vol_params(25.0, 0.25, 0.0, 3.0, 0.3),
                vol_params(25.0, 0.25, 0.02, 1.99, 0.3), vol_params(25.0, 0.25, 0.02, 3.0, 0.0),
                {**good, "facet_angle": "25"}):
        error(invoke(scratch, VOL_GENERATE, [cube], bad), "INVALID_PARAMETER", "INVALID_REQUEST")
    error(invoke(scratch, VOL_GENERATE, [cube], dict(good, features="sharp")), "UNSUPPORTED_PARAMETER",
          "INVALID_REQUEST")
    error(invoke(scratch, VOL_GENERATE, [poly_source("poly_cube.off", "cm")], good), "UNIT_MISMATCH", "TYPE_ERROR")
    error(invoke(scratch, VOL_GENERATE, [{**cube, "format": "json"}], good), "INPUT_FORMAT_MISMATCH", "TYPE_ERROR")
    error(invoke(scratch, VOL_GENERATE, [cube], vol_params(25.0, 0.25, 0.0001, 3.0, 0.3)),
          "MESH_SIZE_LIMIT_EXCEEDED", "RESOURCE_LIMIT")
    error(invoke(scratch, VOL_GENERATE, [cube], vol_params(25.0, 0.25, 0.02, 3.0, 0.01)),
          "MESH_SIZE_LIMIT_EXCEEDED", "RESOURCE_LIMIT")
    error(invoke(scratch, VOL_VALIDATOR, [cube_candidate, poly_source("poly_cube.off", "cm")], good),
          "UNIT_MISMATCH", "TYPE_ERROR")


# ---------------------------------------------------------------------------
# 7.14.04 typed Mesh_criteria_3 criteria, each recomputed independently from the output
# ---------------------------------------------------------------------------

def cell_circumspheres(mesh: dict) -> list:
    """(centre, radius) of every tetrahedron by Cramer's rule, independent of the worker."""
    result = []
    vertices = mesh["vertices"]
    for cell in mesh["tetrahedra"]:
        p = [vertices[i] for i in cell]
        rows = [[2 * (p[k][c] - p[0][c]) for c in range(3)] for k in (1, 2, 3)]
        rhs = [sum((p[k][c] - p[0][c]) ** 2 for c in range(3)) for k in (1, 2, 3)]

        def det3(m):
            return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                    - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                    + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
        d = det3(rows)
        offset = []
        for column in range(3):
            m = [row[:] for row in rows]
            for r in range(3):
                m[r][column] = rhs[r]
            offset.append(det3(m) / d)
        result.append(([p[0][c] + offset[c] for c in range(3)], math.hypot(*offset)))
    return result


def in_box(point, low, high) -> bool:
    return all(low[c] <= point[c] <= high[c] for c in range(3))


def region(low, high, size: float) -> dict:
    return {"box_min": {axis: mm(low[i]) for i, axis in enumerate("xyz")},
            "box_max": {axis: mm(high[i]) for i, axis in enumerate("xyz")}, "cell_size": mm(size)}


def cube_feature_chains(mesh: dict) -> list:
    """For each of the 12 unit-cube edges, the sorted mesh vertices on it and whether consecutive
    ones are joined by a tetrahedron edge (all recomputed from the raw mesh)."""
    vertices = mesh["vertices"]
    edges = set()
    for cell in mesh["tetrahedra"]:
        for i in range(4):
            for j in range(i + 1, 4):
                edges.add((min(cell[i], cell[j]), max(cell[i], cell[j])))
    chains = []
    for axis in range(3):
        others = [c for c in range(3) if c != axis]
        for a in (0.0, 1.0):
            for b in (0.0, 1.0):
                on_line = sorted((vertices[i][axis], i) for i in range(len(vertices))
                                 if abs(vertices[i][others[0]] - a) < 1e-9 and abs(vertices[i][others[1]] - b) < 1e-9)
                joined = all((min(u[1], w[1]), max(u[1], w[1])) in edges for u, w in zip(on_line, on_line[1:]))
                gaps = [w[0] - u[0] for u, w in zip(on_line, on_line[1:])]
                chains.append({"count": len(on_line), "joined": joined, "gaps": gaps,
                               "ends": (on_line[0][0], on_line[-1][0])})
    return chains


def criteria_cases(scratch: pathlib.Path) -> None:
    sphere = artifact(FIXTURES / "domain_sphere.json", SURF_DOMAIN)
    base = vol_params(25.0, 0.5, 0.05, 3.0, 0.6)

    # --- every Mesh_criteria_3 criterion has a measurable effect, recomputed from the output -----
    base_report, base_mesh, _, base_candidate = run_volume_pair(scratch, sphere, base)
    base_facts = volume_facts(base_mesh)
    base_spheres = cell_circumspheres(base_mesh)
    variants = (("cell_size", vol_params(25.0, 0.5, 0.05, 3.0, 0.4)),
                ("facet_size", vol_params(25.0, 0.3, 0.05, 3.0, 0.6)),
                ("facet_distance", vol_params(25.0, 0.5, 0.02, 3.0, 0.6)),
                ("cell_radius_edge_ratio", vol_params(25.0, 0.5, 0.05, 2.0, 0.6)),
                ("facet_angle", {**base, "facet_angle": 30.0}))
    for name, parameters in variants:
        report, mesh, _, _ = run_volume_pair(scratch, sphere, parameters)
        facts = volume_facts(mesh)
        spheres = cell_circumspheres(mesh)
        if name == "cell_size":
            assert max(r for _, r in spheres) <= 0.4 + 1e-9 < max(r for _, r in base_spheres), name
            assert len(mesh["tetrahedra"]) > 1.5 * len(base_mesh["tetrahedra"]), name
        elif name == "facet_size":
            assert facts["facet_radius"] <= 0.3 + 1e-9 and len(facts["boundary"]) > 1.5 * len(base_facts["boundary"])
        elif name == "facet_distance":
            assert len(facts["boundary"]) > len(base_facts["boundary"]), name
            assert report["maximum_facet_circumcentre_distance"] <= 0.02 + 1e-9, report
        elif name == "cell_radius_edge_ratio":
            assert facts["radius_edge"] <= 2.0 + 1e-9, facts
            assert report["maximum_radius_edge_ratio"] <= 2.0 + 1e-9, report
        elif name == "facet_angle":
            assert facts["facet_angle"] >= 30.0 - 1e-9, facts
            assert report["minimum_facet_angle_degrees"] >= 30.0 - 1e-6, report
    # Each criterion tightened alone makes the genuine baseline mesh fail with its own code.
    for parameters, code in ((vol_params(25.0, 0.5, 0.05, 3.0, 0.4), "CELL_SIZE_VIOLATED"),
                             (vol_params(25.0, 0.3, 0.05, 3.0, 0.6), "FACET_SIZE_VIOLATED"),
                             (vol_params(25.0, 0.5, 0.02, 3.0, 0.6), "FACET_DISTANCE_VIOLATED"),
                             (vol_params(25.0, 0.5, 0.05, 1.5, 0.6), "RADIUS_EDGE_VIOLATED"),
                             ({**base, "facet_angle": 35.0}, "FACET_ANGLE_VIOLATED")):
        rejected(invoke(scratch, VOL_VALIDATOR, [base_candidate, sphere], parameters), code)

    # --- cell_size_regions: a sizing field restricted to enumerated boxes ------------------------
    low, high = [0.0, 0.0, 0.0], [2.5, 2.5, 2.5]
    regional = {**base, "cell_size_regions": [region(low, high, 0.3)]}
    reg_report, reg_mesh, reg_metrics, reg_candidate = run_volume_pair(scratch, sphere, regional)
    assert reg_metrics["cell_size_region_count"] == 1 and reg_report["checks"]["cell_size_regions_satisfied"] is True
    inside = [(c, r) for c, r in cell_circumspheres(reg_mesh) if in_box(c, low, high)]
    outside = [(c, r) for c, r in cell_circumspheres(reg_mesh) if not in_box(c, low, high)]
    base_inside = [r for c, r in base_spheres if in_box(c, low, high)]
    assert inside and outside and max(r for _, r in inside) <= 0.3 + 1e-9, (len(inside), len(outside))
    assert max(base_inside) > 0.3 + 1e-6, "the box must actually constrain the baseline"
    assert len(reg_mesh["tetrahedra"]) > 1.3 * len(base_mesh["tetrahedra"]), "regional refinement adds cells"
    assert max(r for _, r in outside) > 0.3, "outside the box the global bound still applies"
    assert max(r for _, r in outside) <= 0.6 + 1e-9
    assert reg_report["optional_criteria"]["cell_size_regions"][0]["cells_with_circumcentre_inside"] == len(inside), reg_report
    assert ok(invoke(scratch, VOL_GENERATE, [sphere], regional))[1].read_bytes() == \
        pathlib.Path(reg_candidate["path"]).read_bytes(), "regional mesh must be deterministic"
    # The unrefined mesh violates the regional bound; the regional mesh meets the global one too.
    rejected(invoke(scratch, VOL_VALIDATOR, [base_candidate, sphere], regional), "CELL_SIZE_REGION_VIOLATED")
    ok(invoke(scratch, VOL_VALIDATOR, [reg_candidate, sphere], base))
    two = {**base, "cell_size_regions": [region(low, high, 0.3), region([-2.5, -2.5, -2.5], [0.0, 0.0, 0.0], 0.45)]}
    two_report, two_mesh, _, _ = run_volume_pair(scratch, sphere, two)
    for centre, radius in cell_circumspheres(two_mesh):
        bound = min([0.6] + ([0.3] if in_box(centre, low, high) else []) +
                    ([0.45] if in_box(centre, [-2.5] * 3, [0.0] * 3) else []))
        assert radius <= bound + 1e-9, (centre, radius, bound)
    # Typed-schema errors, from the generator and from the validator.
    good_region = region(low, high, 0.3)
    for bad, code, kind in (
            ([], "INVALID_PARAMETER", "INVALID_REQUEST"),
            ("box", "INVALID_PARAMETER", "INVALID_REQUEST"),
            ([good_region] * 5, "INVALID_PARAMETER", "INVALID_REQUEST"),
            ([{**good_region, "color": "red"}], "INVALID_PARAMETER", "INVALID_REQUEST"),
            ([{"box_min": good_region["box_min"], "cell_size": mm(0.3)}], "INVALID_PARAMETER", "INVALID_REQUEST"),
            ([region(high, low, 0.3)], "INVALID_PARAMETER", "INVALID_REQUEST"),
            ([region(low, high, 0.6)], "INVALID_PARAMETER", "INVALID_REQUEST"),
            ([region(low, high, 0.9)], "INVALID_PARAMETER", "INVALID_REQUEST"),
            ([region(low, high, -0.3)], "INVALID_PARAMETER", "INVALID_REQUEST"),
            ([{**good_region, "cell_size": "0.3"}], "INVALID_PARAMETER", "INVALID_REQUEST"),
            ([{**good_region, "cell_size": {"value": 0.3, "unit": "cm"}}], "UNIT_MISMATCH", "TYPE_ERROR"),
            ([{**good_region, "box_max": {"x": mm(2.5), "y": mm(2.5)}}], "INVALID_PARAMETER", "INVALID_REQUEST"),
            ([region([5.0, 5.0, 5.0], [6.0, 6.0, 6.0], 0.3)], "REGION_OUTSIDE_DOMAIN", "INVALID_REQUEST")):
        error(invoke(scratch, VOL_GENERATE, [sphere], {**base, "cell_size_regions": bad}), code, kind)
        error(invoke(scratch, VOL_VALIDATOR, [base_candidate, sphere], {**base, "cell_size_regions": bad}), code, kind)

    # --- facet_topology and unsupported combinations --------------------------------------------
    for topology in ("FACET_VERTICES_ON_SURFACE", "FACET_VERTICES_ON_SAME_SURFACE_PATCH"):
        topo_report, _, topo_metrics, _ = run_volume_pair(scratch, sphere, {**base, "facet_topology": topology})
        assert topo_metrics["facet_topology"] == topology and topo_report["checks"]["facet_topology_satisfied"] is True
    for bad in ("FACET_VERTICES_ON_SURFACE ", "facet_vertices_on_surface", 3, None):
        error(invoke(scratch, VOL_GENERATE, [sphere], {**base, "facet_topology": bad}), "INVALID_PARAMETER",
              "INVALID_REQUEST")
    error(invoke(scratch, VOL_GENERATE, [sphere], {**base, "edge_size": mm(0.3)}), "CRITERION_NOT_APPLICABLE",
          "INVALID_REQUEST")
    error(invoke(scratch, VOL_VALIDATOR, [base_candidate, sphere], {**base, "edge_size": mm(0.3)}),
          "CRITERION_NOT_APPLICABLE", "INVALID_REQUEST")
    error(invoke(scratch, VOL_GENERATE, [sphere], {**base, "mystery_criterion": 1}), "UNSUPPORTED_PARAMETER",
          "INVALID_REQUEST")

    # --- edge_size: sharp-edge (1D feature) protection on a polyhedral domain ----------------------
    cube = poly_source("poly_cube.off")
    cube_parameters = vol_params(25.0, 0.25, 0.02, 3.0, 0.3)
    chain_counts = {}
    loose_candidate = None
    for edge in (0.5, 0.25):
        parameters = {**cube_parameters, "edge_size": mm(edge)}
        result = invoke(scratch, VOL_GENERATE, [cube], parameters)
        output, path = ok(result)
        candidate = produced(output, path)
        assert result["metrics"]["feature_protection"] is True and result["metrics"]["edge_size"] == edge, result["metrics"]
        assert result["metrics"]["domain"] == "CGAL::Polyhedral_mesh_domain_with_features_3", result["metrics"]
        report = json.loads(ok(invoke(scratch, VOL_VALIDATOR, [candidate, cube], parameters))[1].read_text("utf-8"))
        assert report["status"] == "pass" and report["checks"]["feature_edge_size_satisfied"] is True, report
        # Feature mode reports the facet/cell criteria under scoped keys, never as full passes.
        scope = report["criteria_scope"]
        assert scope["scoped"] is True and scope["facets"]["excluded"] > 0, report
        assert scope["facets"]["checked"] + scope["facets"]["excluded"] == scope["facets"]["total"], report
        assert scope["cells"]["checked"] + scope["cells"]["excluded"] == scope["cells"]["total"], report
        assert scope["facets"]["checked"] >= scope["minimum_checked_share"] * scope["facets"]["total"], report
        assert scope["cells"]["checked"] >= scope["minimum_checked_share"] * scope["cells"]["total"], report
        assert "facet_angle_criterion_satisfied_on_unprotected_facets_only" in report["checks"], report
        assert "cell_size_criterion_satisfied_on_unprotected_cells_only" in report["checks"], report
        assert "facet_angle_criterion_satisfied" not in report["checks"], report
        assert "cell_radius_edge_criterion_satisfied" not in report["checks"], report
        mesh = json.loads(path.read_text("utf-8"))
        chains = cube_feature_chains(mesh)
        assert len(chains) == 12 and all(c["joined"] for c in chains), chains
        assert all(c["ends"] == (0.0, 1.0) for c in chains), chains
        assert max(max(c["gaps"]) for c in chains) <= edge + 1e-9, chains
        assert any(max(c["gaps"]) > edge / 2 for c in chains), "the bound is actually active"
        chain_counts[edge] = sum(c["count"] for c in chains)
        features = report["optional_criteria"]["feature_edges"]
        assert features["sharp_source_edges"] == 12 and features["longest_segment"] <= edge + 1e-9, report
        assert features["mesh_edge_segments"] == sum(len(c["gaps"]) for c in chains), (features, chains)
        # Volume is exact: the cube corners and edges are preserved.
        assert abs(report["volume"]["value"] - 1.0) < 1e-9, report["volume"]
        if edge == 0.5:
            loose_candidate = candidate
            # A mesh built for 0.5 is rejected under 0.25.
            rejected(invoke(scratch, VOL_VALIDATOR, [candidate, cube], {**cube_parameters, "edge_size": mm(0.25)}),
                     "EDGE_SIZE_VIOLATED")
    assert chain_counts[0.25] > chain_counts[0.5] > 12, chain_counts
    # A mesh without feature protection is rejected whenever edge_size is requested.
    plain_report, plain_mesh, plain_metrics, plain_candidate = run_poly_pair(scratch, cube, cube_parameters)
    assert plain_metrics["feature_protection"] is False
    rejected(invoke(scratch, VOL_VALIDATOR, [plain_candidate, cube], {**cube_parameters, "edge_size": mm(0.5)}),
             "FEATURE_EDGE_NOT_PROTECTED")
    # The facet-criteria exclusion of feature facets applies only when edge_size is requested: the
    # same feature-protected mesh is judged by all facets (and fails the facet angle) without it.
    rejected(invoke(scratch, VOL_VALIDATOR, [loose_candidate, cube], cube_parameters), "FACET_ANGLE_VIOLATED")
    # Fail closed: a fabricated candidate with only the eight cube corners (five tetrahedra) has every
    # boundary facet touching a protected sharp edge, so the scoped facet criteria would check nothing.
    corners = [[float(i & 1), float((i >> 1) & 1), float((i >> 2) & 1)] for i in range(8)]
    corner_cells = [[1, 2, 4, 7], [0, 1, 2, 4], [3, 1, 2, 7], [5, 1, 4, 7], [6, 2, 4, 7]]
    corner_cells = [c if det3([corners[i] for i in c]) > 0 else [c[0], c[1], c[3], c[2]] for c in corner_cells]
    corner_candidate = write_tet(scratch, corners, corner_cells)
    rejected(invoke(scratch, VOL_VALIDATOR, [corner_candidate, cube], {**cube_parameters, "edge_size": mm(1.5)}),
             "CRITERIA_SCOPE_EMPTY")
    # Cell regions work on polyhedral domains too.
    poly_regional = {**cube_parameters, "cell_size_regions": [region([0.0, 0.0, 0.0], [0.5, 1.0, 1.0], 0.15)]}
    result = invoke(scratch, VOL_GENERATE, [cube], poly_regional)
    output, path = ok(result)
    poly_candidate = produced(output, path)
    poly_mesh = json.loads(path.read_text("utf-8"))
    report = json.loads(ok(invoke(scratch, VOL_VALIDATOR, [poly_candidate, cube], poly_regional))[1].read_text("utf-8"))
    assert report["checks"]["cell_size_regions_satisfied"] is True, report
    half = [(c, r) for c, r in cell_circumspheres(poly_mesh) if in_box(c, [0, 0, 0], [0.5, 1, 1])]
    assert half and max(r for _, r in half) <= 0.15 + 1e-9, len(half)
    assert len(poly_mesh["tetrahedra"]) > 1.3 * len(plain_mesh["tetrahedra"])
    rejected(invoke(scratch, VOL_VALIDATOR, [plain_candidate, cube], poly_regional), "CELL_SIZE_REGION_VIOLATED")
    # edge_size needs sharp edges: a smooth polyhedral sphere has none.
    ico = poly_source("poly_icosphere.off")
    error(invoke(scratch, VOL_GENERATE, [ico], {**vol_params(25.0, 0.3, 0.03, 3.0, 0.5), "edge_size": mm(0.3)}),
          "CRITERION_NOT_APPLICABLE", "INVALID_REQUEST")
    for bad in (mm(0.0), mm(-0.1), 0.25):
        error(invoke(scratch, VOL_GENERATE, [cube], {**cube_parameters, "edge_size": bad}), "INVALID_PARAMETER",
              "INVALID_REQUEST")
    error(invoke(scratch, VOL_GENERATE, [cube], {**cube_parameters, "edge_size": {"value": 0.25, "unit": "cm"}}),
          "UNIT_MISMATCH", "TYPE_ERROR")
    error(invoke(scratch, VOL_GENERATE, [cube], {**cube_parameters, "edge_size": mm(0.001)}),
          "MESH_SIZE_LIMIT_EXCEEDED", "RESOURCE_LIMIT")
    error(invoke(scratch, VOL_GENERATE, [cube], {
        **cube_parameters, "edge_size": mm(0.25), "facet_topology": "FACET_VERTICES_ON_SAME_SURFACE_PATCH"}),
        "CRITERION_NOT_APPLICABLE", "INVALID_REQUEST")


def on_boundary(vertex) -> bool:
    x, y = vertex
    return x in (0.0, 10.0) or y in (0.0, 10.0)


if __name__ == "__main__":
    main()
