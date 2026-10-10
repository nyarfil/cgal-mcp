"""Generate the tampered batch-9 report fixtures from real worker output.

Usage: python tests/fixtures/master/batch9/generate_tampered_reports.py <cgal-master-worker>
Every tampered report is a genuine producer report with one deliberate defect, so the independent validators
must reject exactly that defect. The parameter sets below must equal the ones scripts/master_replay_families.py
replays (a validator rejects a report whose recorded parameters differ).
"""

from __future__ import annotations

import copy
import json
import math
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
NARROW = {"cone_angle": math.pi / 6, "number_of_rays": 25, "thickness_tolerance": 0.05}
SEGMENT = dict(NARROW, number_of_clusters=2, smoothing_lambda=0.26)
PERIODIC_2 = {"domain_min": [0.0, 0.0], "period": {"value": 1.0, "unit": "mm"}}
PERIODIC_3 = {"domain_min": [0.0, 0.0, 0.0], "period": {"value": 1.0, "unit": "mm"}}
SPHERE = {"center": [0.0, 0.0, 0.0], "radius": {"value": 10.0, "unit": "mm"}}
ARM_FACET = 200  # a side facet of the 1 x 1 arm


def produce(worker: str, scratch: pathlib.Path, operation: str, name: str, type_: str, parameters: dict) -> dict:
    sys.path.insert(0, str(HERE.parents[2]))
    import master_query_cases as q
    from master_batch2_cases import art
    q.WORKER = str(pathlib.Path(worker).resolve())
    folder = scratch / f"run{len(list(scratch.iterdir())):03d}"
    folder.mkdir()
    result = q.invoke(folder, operation, [art(HERE / name, type_)], parameters)
    assert result["status"] == "ok", result
    return json.loads(q.ok(result).read_text("utf-8"))


def save(name: str, report: dict) -> None:
    (HERE / name).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")


def periodic_flip(report: dict, points: list[list[float]]) -> dict:
    """Flip one interior edge of a periodic 2D triangulation: still a triangulation of the torus, not Delaunay."""
    triangles = report["results"]["triangles"]

    def pos(v):
        return (points[v[0]][0] + v[1], points[v[0]][1] + v[2])

    def ccw(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]) > 0

    for i, t1 in enumerate(triangles):
        for k in range(3):
            a, b, c = t1[k], t1[(k + 1) % 3], t1[(k + 2) % 3]
            rel = (a[1] - b[1], a[2] - b[2])
            for j, t2 in enumerate(triangles):
                if j == i:
                    continue
                for m in range(3):
                    b2, a2, d2 = t2[m], t2[(m + 1) % 3], t2[(m + 2) % 3]
                    if b2[0] != b[0] or a2[0] != a[0] or (a2[1] - b2[1], a2[2] - b2[2]) != rel:
                        continue
                    shift = (b[1] - b2[1], b[2] - b2[2])
                    d = [d2[0], d2[1] + shift[0], d2[2] + shift[1]]
                    n1, n2 = [a, d, c], [d, b, c]
                    if ccw(*map(pos, n1)) and ccw(*map(pos, n2)):
                        bad = copy.deepcopy(report)
                        rows = [t for n, t in enumerate(triangles) if n not in (i, j)] + [n1, n2]
                        bad["results"]["triangles"] = rows
                        return bad
    raise AssertionError("no flippable edge")


def sphere_flip(report: dict, points: list[tuple[float, float, float]]) -> dict:
    faces = report["results"]["triangles"]

    def outward(f):
        p, q, r = (points[i] for i in f)
        u = [q[k] - p[k] for k in range(3)]
        v = [r[k] - p[k] for k in range(3)]
        n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        return sum(n[k] * (0.0 - p[k]) for k in range(3)) < 0

    for i, (a, b, c) in enumerate(faces):
        for j, t2 in enumerate(faces):
            if j == i:
                continue
            for m in range(3):
                if t2[m] == b and t2[(m + 1) % 3] == a:
                    d = t2[(m + 2) % 3]
                    n1, n2 = [a, d, c], [d, b, c]
                    if outward(n1) and outward(n2):
                        bad = copy.deepcopy(report)
                        bad["results"]["triangles"] = [f for n, f in enumerate(faces) if n not in (i, j)] + [n1, n2]
                        return bad
    raise AssertionError("no flippable edge")


def main(worker: str) -> None:
    with tempfile.TemporaryDirectory() as raw:
        scratch = pathlib.Path(raw)
        sdf = produce(worker, scratch, "mesh.segment.sdf_values", "body_arm.off", "TriangleSurfaceMesh", NARROW)
        bad = copy.deepcopy(sdf)
        bad["results"]["raw_sdf"][ARM_FACET] *= 4.0  # the 1 mm arm reported as thick as the 4 mm body
        save("tampered_sdf_thick_arm.json", bad)
        bad = copy.deepcopy(sdf)
        bad["results"]["raw_sdf"][0] = -1.0  # a value reported missing on a closed outward mesh
        save("tampered_sdf_missing_value.json", bad)

        seg = produce(worker, scratch, "mesh.segment.sdf", "body_arm.off", "TriangleSurfaceMesh", SEGMENT)
        body_segment = seg["results"]["segment_ids"][0]
        assert seg["results"]["segment_ids"][ARM_FACET] != body_segment
        bad = copy.deepcopy(seg)
        bad["results"]["segment_ids"][ARM_FACET] = body_segment  # an arm facet assigned to the body segment
        save("tampered_segment_wrong_component.json", bad)
        bad = copy.deepcopy(seg)
        bad["results"]["segment_ids"].pop()  # the last facet has no segment
        save("tampered_segment_uncovered_facet.json", bad)
        bad = copy.deepcopy(seg)
        bad["results"]["cluster_ids"][0] = 7  # beyond number_of_clusters = 2
        save("tampered_segment_cluster_out_of_range.json", bad)

        p2 = produce(worker, scratch, "triangulation.periodic_delaunay_2", "periodic_points_2.json", "PointSet2",
                     PERIODIC_2)
        points2 = json.loads((HERE / "periodic_points_2.json").read_text("utf-8"))["points"]
        save("tampered_periodic2_flipped_edge.json", periodic_flip(p2, points2))
        bad = copy.deepcopy(p2)
        del bad["results"]["triangles"][5]  # one triangle missing: the torus is not covered
        save("tampered_periodic2_missing_triangle.json", bad)

        p3 = produce(worker, scratch, "triangulation.periodic_delaunay_3", "periodic_points_3.xyz", "PointSet3",
                     PERIODIC_3)
        bad = copy.deepcopy(p3)
        del bad["results"]["tetrahedra"][7]  # one tetrahedron missing
        save("tampered_periodic3_missing_tetrahedron.json", bad)
        bad = copy.deepcopy(p3)
        tet = bad["results"]["tetrahedra"][11]
        tet[0], tet[1] = tet[1], tet[0]  # negatively oriented
        save("tampered_periodic3_inverted_tetrahedron.json", bad)

        sphere = produce(worker, scratch, "triangulation.delaunay_on_sphere_2", "sphere_points.xyz", "PointSet3", SPHERE)
        points3 = [tuple(float(x) for x in line.split())
                   for line in (HERE / "sphere_points.xyz").read_text("utf-8").splitlines() if line.strip()]
        save("tampered_sphere_flipped_edge.json", sphere_flip(sphere, points3))
        bad = copy.deepcopy(sphere)
        del bad["results"]["triangles"][3]  # a hole in the sphere
        save("tampered_sphere_missing_face.json", bad)


if __name__ == "__main__":
    main(sys.argv[1])
