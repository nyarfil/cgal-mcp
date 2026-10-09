"""Real CGAL 6.2.1 batch-4 production-worker cases (7.4.04 hole filling with refinement and fairing).

Usage: python tests/master_batch4_cases.py <cgal-master-worker>
Every producer result is checked by its validator; tampered candidates and invalid parameters must
fail closed.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile

import master_query_cases as q
from master_batch2_cases import art, reject

ROOT = q.ROOT
B4 = ROOT / "tests" / "fixtures" / "master" / "batch4"

FAIR = ("mesh.repair.fill_holes_refine_fair", "mesh.validate.repair_fill_holes_refine_fair")


def repair_pair(scratch, producer, validator, source, parameters):
    result = q.invoke(scratch, producer, [source], parameters)
    path = q.ok(result)
    candidate = art(path, "TriangleSurfaceMesh")
    verdict = json.loads(q.ok(q.invoke(scratch, validator, [candidate, source], parameters)).read_text("utf-8"))
    assert verdict["status"] == "pass" and verdict["passed"] is True, verdict
    assert verdict["validator_id"] == validator and verdict["checks"] and all(verdict["checks"].values()), verdict
    return path, result


def shortest_path_cases(operations) -> None:
    assert "mesh.validate.shortest_path" in operations["mesh.path.shortest"]["info"]["validators"]
    cube = art(B4 / "cube_geodesic.off", "TriangleSurfaceMesh")
    lshape = art(B4 / "lshape.off", "TriangleSurfaceMesh")
    cases = ((cube, {"sources": [{"vertex": 0}], "targets": [{"vertex": 6}, {"vertex": 2}, {"vertex": 1}]},
              [4.47213595499958, 2.8284271247461903, 2.0]),
             (lshape, {"sources": [{"vertex": 6}], "targets": [{"vertex": 3}, {"vertex": 2}]},
              [2.414213562373095, 2.8284271247461903]))
    with tempfile.TemporaryDirectory() as raw:
        scratch = pathlib.Path(raw)
        for mesh, parameters, expected in cases:
            result = q.invoke(scratch, "mesh.path.shortest", [mesh], parameters)
            path = q.ok(result)
            rows = json.loads(path.read_text("utf-8"))["results"]["targets"]
            for row, value in zip(rows, expected):
                assert abs(row["distance"] - value) < 1e-9, rows
            candidate = art(path, "GeometryQueryReport", "none")
            verdict = json.loads(q.ok(q.invoke(scratch, "mesh.validate.shortest_path", [candidate, mesh],
                                               parameters)).read_text("utf-8"))
            assert verdict["passed"] is True and all(verdict["checks"].values()), verdict
        for name, code in (("tampered_sp_distance_short.json", "DISTANCE_MISMATCH"),
                           ("tampered_sp_path_off_surface.json", "PATH_LEAVES_SURFACE")):
            reject(scratch, "mesh.validate.shortest_path", [art(B4 / name, "GeometryQueryReport", "none"), cube],
                   cases[0][1] | {"targets": [{"vertex": 6}, {"vertex": 2}]}, code)
        reject(scratch, "mesh.path.shortest", [cube], {"sources": [{"vertex": 99}], "targets": [{"vertex": 1}]},
               "INVALID_PARAMETER", "INVALID_REQUEST")


def main() -> None:
    manifest = json.loads(subprocess.run([q.WORKER, "--manifest"], text=True, encoding="utf-8",
                                         capture_output=True, timeout=30, check=True).stdout)
    operations = {operation["id"]: operation for operation in manifest["operations"]}
    assert FAIR[1] in operations[FAIR[0]]["info"]["validators"]
    assert operations[FAIR[1]]["role"] == "validator"
    dome = art(B4 / "dome_hole12.off", "TriangleSurfaceMesh")
    with tempfile.TemporaryDirectory() as raw:
        scratch = pathlib.Path(raw)
        for factor, continuity, vertices in ((1.0, 0, 0), (1.41, 1, 1), (2.5, 2, 7)):
            _, result = repair_pair(scratch, *FAIR, dome, {"max_hole_edges": 20, "density_control_factor": factor,
                                                           "fairing_continuity": continuity})
            assert result["metrics"]["added_vertex_count"] == vertices, result
            assert result["metrics"]["candidate"]["mesh"]["closed"] is True, result
        parameters = {"max_hole_edges": 20, "density_control_factor": 1.41, "fairing_continuity": 1}
        reject(scratch, FAIR[1], [art(B4 / "tampered_fair_vertex_moved.off", "TriangleSurfaceMesh"), dome],
               parameters, "REPAIR_VALIDATION_FAILED")
        reject(scratch, FAIR[1], [dome, dome], parameters, "REPAIR_VALIDATION_FAILED")
        reject(scratch, FAIR[0], [dome], {**parameters, "max_hole_edges": 8}, "NO_ELIGIBLE_HOLES",
               "PRECONDITION_FAILED")
        reject(scratch, FAIR[0], [dome], {**parameters, "density_control_factor": 0.5},
               "INVALID_DENSITY_CONTROL_FACTOR", "INVALID_INPUT")
        reject(scratch, FAIR[0], [dome], {**parameters, "fairing_continuity": 3},
               "INVALID_FAIRING_CONTINUITY", "INVALID_INPUT")
    shortest_path_cases(operations)
    print("batch-4 worker cases: PASS")


if __name__ == "__main__":
    main()
