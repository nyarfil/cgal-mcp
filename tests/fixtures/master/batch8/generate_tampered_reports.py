"""Generate the tampered batch-8 report fixtures from real worker output.

Usage: python tests/fixtures/master/batch8/generate_tampered_reports.py <cgal-master-worker>
Every tampered report is a genuine producer report with one deliberate defect, so the independent validators
must reject exactly that defect. The parameter sets below must equal the ones scripts/master_replay_families.py
replays (a validator rejects a report whose recorded parameters differ).
"""

from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ACD_L = {"maximum_number_of_convex_volumes": 2, "maximum_number_of_voxels": 10000, "maximum_depth": 6,
         "volume_error": 0.01, "refitting": True, "split_at_concavity": True}
MCF_TUBE = {"quality_speed_tradeoff": 0.1, "medially_centered_speed_tradeoff": 0.2, "is_medially_centered": True,
            "max_iterations": 500}
MCF_TORUS = dict(MCF_TUBE, quality_speed_tradeoff=1.0)
ARAP_A = {"lambda": 1000.0, "iterations": 50, "maximum_distortion": 1.25}
ARAP_TIGHT = {"lambda": 0.0, "iterations": 1, "maximum_distortion": 1.5}


def produce(worker: str, scratch: pathlib.Path, operation: str, mesh: str, parameters: dict) -> dict:
    sys.path.insert(0, str(HERE.parents[2]))
    import master_query_cases as q
    from master_batch2_cases import art
    q.WORKER = str(pathlib.Path(worker).resolve())
    folder = scratch / f"run{len(list(scratch.iterdir())):03d}"
    folder.mkdir()
    result = q.invoke(folder, operation, [art(HERE / mesh, "TriangleSurfaceMesh")], parameters)
    assert result["status"] == "ok", result
    return json.loads(q.ok(result).read_text("utf-8"))


def save(name: str, report: dict) -> None:
    (HERE / name).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")


def main(worker: str) -> None:
    with tempfile.TemporaryDirectory() as raw:
        scratch = pathlib.Path(raw)
        acd = produce(worker, scratch, "mesh.decompose.approx_convex", "l_prism.off", ACD_L)
        bad = copy.deepcopy(acd)
        part = bad["results"]["parts"][0]
        count = len(part["vertices"])
        centroid = [sum(v[k] for v in part["vertices"]) / count for k in range(3)]
        part["vertices"][0] = centroid  # a dent: the part is no longer convex
        save("tampered_acd_nonconvex.json", bad)
        bad = copy.deepcopy(acd)
        del bad["results"]["parts"][1]  # a part is missing: the input is not covered
        save("tampered_acd_missing_part.json", bad)

        tube = produce(worker, scratch, "mesh.skeletonize.mean_curvature_flow", "tube.off", MCF_TUBE)
        bad = copy.deepcopy(tube)
        bad["results"]["vertices"][3]["point"] = [100.0, 0.0, 0.0]
        save("tampered_skeleton_outside.json", bad)
        bad = copy.deepcopy(tube)
        edges = bad["results"]["edges"]
        del edges[len(edges) // 2]  # splits the path in two
        save("tampered_skeleton_split.json", bad)
        bad = copy.deepcopy(tube)
        vertex_count = len(bad["results"]["vertices"])
        existing = {tuple(e) for e in bad["results"]["edges"]}
        for a in range(vertex_count):
            for b in range(a + 1, vertex_count):
                if (a, b) not in existing and not bad.get("_added"):
                    # connect two vertices that are two steps apart on the path: a spurious cycle
                    if (a, a + 1) in existing and (a + 1, b) in existing and b == a + 2:
                        bad["results"]["edges"].append([a, b])
                        bad["_added"] = True
        del bad["_added"]
        bad["results"]["edges"].sort()
        save("tampered_skeleton_extra_cycle.json", bad)

        torus = produce(worker, scratch, "mesh.skeletonize.mean_curvature_flow", "torus.off", MCF_TORUS)
        save("genuine_skeleton_torus_defaults.json", produce(
            worker, scratch, "mesh.skeletonize.mean_curvature", "torus.off", {}))  # collapses through the surface
        bad = copy.deepcopy(torus)
        del bad["results"]["edges"][0]  # the loop is cut open: no cycle left for the genus-1 torus
        save("tampered_skeleton_open_loop.json", bad)

        dcm = produce(worker, scratch, "mesh.parameterize.discrete_conformal_map", "disc_bump.off", {})
        uv = dcm["results"]["uv"]
        bad = copy.deepcopy(dcm)
        # swap two neighbouring interior vertices (grid vertices 40 and 41): flips triangles around them
        bad["results"]["uv"][40], bad["results"]["uv"][41] = uv[41], uv[40]
        save("tampered_param_flipped.json", bad)
        bad = copy.deepcopy(dcm)
        bad["results"]["uv"][40] = [uv[40][0] + 0.002, uv[40][1] - 0.002]  # no flip, but not harmonic
        save("tampered_param_nonharmonic.json", bad)

        arap = produce(worker, scratch, "mesh.parameterize", "disc_bump.off", ARAP_A)
        save("genuine_param_arap_tight_bound.json", produce(
            worker, scratch, "mesh.parameterize", "disc_bump.off", ARAP_TIGHT))  # genuine but above the bound
        bad = copy.deepcopy(arap)
        bad["results"]["uv"] = [[3.0 * u, v] for u, v in bad["results"]["uv"]]  # anisotropic stretch
        save("tampered_param_stretched.json", bad)


if __name__ == "__main__":
    main(sys.argv[1])
