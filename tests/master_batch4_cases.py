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
    print("batch-4 worker cases: PASS")


if __name__ == "__main__":
    main()
