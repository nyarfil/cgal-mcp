"""Direct CGAL 6.2.1 acceptance cases for Spatial Query family 7.2."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

OPS = {
    "spatial.aabb.closest_point": "spatial.validate.aabb_closest_point",
    "spatial.kdtree.range": "spatial.validate.kdtree_range",
    "spatial.nearest_neighbors": "spatial.validate.nearest_neighbors",
    "spatial.intersection_candidates": "spatial.validate.intersection_candidates",
    "spatial.bounding_box": "spatial.validate.bounding_box",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_xyz(path: Path) -> None:
    path.write_text(
        "0 0 0\n1 0 0\n0 2 0\n0 0 3\n2 2 2\n",
        encoding="ascii",
    )


def write_tetra(path: Path) -> None:
    path.write_text(
        """OFF
4 4 0
0 0 0
1 0 0
0 1 0
0 0 1
3 0 2 1
3 0 1 3
3 1 2 3
3 2 0 3
""",
        encoding="ascii",
    )


def write_degenerate(path: Path) -> None:
    path.write_text(
        """OFF
3 1 0
0 0 0
1 0 0
2 0 0
3 0 1 2
""",
        encoding="ascii",
    )


def artifact(path: Path, kind: str, unit: str = "mm") -> dict:
    return {
        "artifact_id": path.stem,
        "type": kind,
        "unit": unit,
        "format": "off" if kind == "TriangleSurfaceMesh" else "xyz",
        "path": str(path.resolve()),
        "sha256": sha256(path),
    }


def run(worker: str, request: dict) -> dict:
    process = subprocess.run(
        [worker],
        input=json.dumps(request, separators=(",", ":")) + "\n",
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=120,
    )
    assert process.returncode == 0, (process.returncode, process.stderr)
    assert process.stderr == "", process.stderr
    lines = process.stdout.splitlines()
    assert len(lines) == 1, process.stdout
    result = json.loads(lines[0])
    assert result["protocol"] == 1
    assert result["request_id"] == request["request_id"]
    return result


def request(operation: str, inputs: list[dict], parameters: dict,
            output_dir: Path, request_id: str,
            kernel: str = "package_recommended") -> dict:
    return {
        "protocol": 1,
        "request_id": request_id,
        "operation": operation,
        "inputs": inputs,
        "parameters": parameters,
        "output_dir": str(output_dir.resolve()),
        "kernel": kernel,
        "limits": {"wall_time_ms": 120_000, "memory_mb": 2048},
    }


def invoke(worker: str, root: Path, operation: str, source: dict,
           parameters: dict, case: str,
           kernel: str = "package_recommended") -> tuple[dict, Path, dict]:
    out = root / ("out-" + case)
    out.mkdir()
    result = run(worker, request(operation, [source], parameters, out, case, kernel))
    assert result["status"] == "ok", result
    assert len(result["outputs"]) == 1
    entry = result["outputs"][0]
    assert entry["slot"] == "analysis"
    assert entry["type"] == "GeometryAnalysisReport"
    assert entry["format"] == "json" and entry["unit"] == "none"
    report_path = Path(entry["path"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["source"]["sha256"] == source["sha256"]
    assert report["validation"]["passed"] is True
    assert all(report["validation"]["checks"].values())
    return result, report_path, report


def validate(worker: str, root: Path, operation: str, source: dict,
             parameters: dict, report_path: Path, case: str,
             kernel: str = "package_recommended") -> dict:
    candidate = {
        "artifact_id": case + "-candidate",
        "type": "GeometryAnalysisReport",
        "unit": "none",
        "format": "json",
        "path": str(report_path.resolve()),
        "sha256": sha256(report_path),
    }
    out = root / ("out-validate-" + case)
    out.mkdir()
    result = run(
        worker,
        request(OPS[operation], [candidate, source], parameters,
                out, "validate-" + case, kernel),
    )
    assert result["status"] == "ok", result
    report = json.loads(Path(result["outputs"][0]["path"]).read_text(encoding="utf-8"))
    assert report["status"] == "pass" and report["passed"] is True
    assert report["validator_id"] == OPS[operation]
    assert all(report["checks"].values())
    return report


def expect_error(worker: str, value: dict, code: str) -> dict:
    result = run(worker, value)
    assert result["status"] == "error", result
    assert result["error"]["code"] == code, result
    assert result["outputs"] == []
    return result


def main(worker: str) -> None:
    manifest_process = subprocess.run(
        [worker, "--manifest"], text=True, encoding="utf-8",
        capture_output=True, timeout=30, check=True)
    assert manifest_process.stderr == ""
    manifest = json.loads(manifest_process.stdout)
    assert manifest["actual_cgal_version"] == "6.2.1"
    operations = {item["id"]: item for item in manifest["operations"]}
    expected = set(OPS) | set(OPS.values())
    assert expected <= set(operations)
    for op, validator in OPS.items():
        assert operations[op]["info"]["validators"] == [validator]
        assert operations[validator]["info"]["validates"] == op
    for op in ("spatial.kdtree.range", "spatial.nearest_neighbors"):
        assert operations[op]["supported_kernels"] == ["package_recommended"]
        assert operations[op]["effective_kernel"] == (
            "CGAL::Exact_predicates_inexact_constructions_kernel")
    for op in ("spatial.aabb.closest_point",
               "spatial.intersection_candidates",
               "spatial.bounding_box"):
        assert operations[op]["effective_kernel"] == (
            "CGAL::Exact_predicates_exact_constructions_kernel")

    with tempfile.TemporaryDirectory(prefix="cgal-spatial-") as folder:
        root = Path(folder)
        points = root / "points.xyz"
        mesh = root / "tetra.off"
        write_xyz(points)
        write_tetra(mesh)
        point_source = artifact(points, "PointSet3")
        mesh_source = artifact(mesh, "TriangleSurfaceMesh")
        point_hash = sha256(points)
        mesh_hash = sha256(mesh)

        closest_params = {
            "query_point": {"value": [2, 0, 0], "unit": "mm"}}
        _, closest_path, closest = invoke(
            worker, root, "spatial.aabb.closest_point", mesh_source,
            closest_params, "aabb-closest", kernel="exact_constructions")
        cp = closest["results"]["closest_point"]
        assert cp["value"] == [1.0, 0.0, 0.0], cp
        assert cp["exact"] == ["1", "0", "0"], cp
        assert closest["results"]["squared_distance"]["exact"] == "1"
        assert 0 <= closest["results"]["primitive_index"] < 4
        validate(worker, root, "spatial.aabb.closest_point", mesh_source,
                 closest_params, closest_path, "aabb-closest",
                 kernel="exact_constructions")

        range_params = {
            "center": {"value": [0, 0, 0], "unit": "mm"},
            "radius": {"value": 1.01, "unit": "mm"},
            "epsilon": {"value": 0, "unit": "mm"},
            "max_results": 100,
        }
        _, range_path, ranged = invoke(
            worker, root, "spatial.kdtree.range", point_source,
            range_params, "kd-range")
        assert ranged["results"]["match_count"] == 2, ranged
        assert ranged["results"]["listed_count"] == 2
        assert ranged["results"]["truncated"] is False
        assert [item["value"] for item in ranged["results"]["points"]] == [
            [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
        validate(worker, root, "spatial.kdtree.range", point_source,
                 range_params, range_path, "kd-range")

        nearest_params = {
            "query_point": {"value": [0, 0, 0], "unit": "mm"},
            "k": 2,
            "epsilon": 0,
        }
        _, nearest_path, nearest = invoke(
            worker, root, "spatial.nearest_neighbors", point_source,
            nearest_params, "nearest")
        neighbors = nearest["results"]["neighbors"]
        assert len(neighbors) == 2
        assert neighbors[0]["point"]["value"] == [0.0, 0.0, 0.0]
        assert neighbors[1]["point"]["value"] == [1.0, 0.0, 0.0]
        assert math.isclose(neighbors[0]["distance"]["value"], 0.0)
        assert math.isclose(neighbors[1]["distance"]["value"], 1.0)
        validate(worker, root, "spatial.nearest_neighbors", point_source,
                 nearest_params, nearest_path, "nearest")

        intersection_params = {
            "segment_start": {"value": [-1, 0.2, 0.2], "unit": "mm"},
            "segment_end": {"value": [2, 0.2, 0.2], "unit": "mm"},
            "max_candidates": 100,
        }
        _, intersections_path, intersections = invoke(
            worker, root, "spatial.intersection_candidates", mesh_source,
            intersection_params, "intersection", kernel="exact_constructions")
        values = intersections["results"]
        assert values["does_intersect"] is True
        assert values["candidate_count"] >= 1
        assert values["primitive_indices"] == sorted(set(values["primitive_indices"]))
        assert all(0 <= index < 4 for index in values["primitive_indices"])
        validate(worker, root, "spatial.intersection_candidates", mesh_source,
                 intersection_params, intersections_path, "intersection",
                 kernel="exact_constructions")

        _, bbox_path, bbox = invoke(
            worker, root, "spatial.bounding_box", point_source, {},
            "bbox", kernel="exact_constructions")
        assert bbox["results"]["minimum"]["value"] == [0.0, 0.0, 0.0]
        assert bbox["results"]["maximum"]["value"] == [2.0, 2.0, 3.0]
        assert bbox["results"]["extent"]["value"] == [2.0, 2.0, 3.0]
        validate(worker, root, "spatial.bounding_box", point_source, {},
                 bbox_path, "bbox", kernel="exact_constructions")

        # Exact requests must not silently downgrade the EPICK Kd-tree path.
        out = root / "out-kd-exact"
        out.mkdir()
        exact_kd = request("spatial.nearest_neighbors", [point_source],
                           nearest_params, out, "kd-exact",
                           kernel="exact_constructions")
        expect_error(worker, exact_kd, "OUTPUT_PRECISION_PROFILE_UNSUPPORTED")

        # CGAL explicitly warns that degenerate AABB primitives are unsafe.
        degenerate = root / "degenerate.off"
        write_degenerate(degenerate)
        deg_source = artifact(degenerate, "TriangleSurfaceMesh")
        out = root / "out-degenerate"
        out.mkdir()
        bad_aabb = request(
            "spatial.aabb.closest_point", [deg_source], closest_params,
            out, "degenerate-aabb")
        expect_error(worker, bad_aabb, "AABB_DEGENERATE_PRIMITIVE")

        out = root / "out-zero-segment"
        out.mkdir()
        zero_segment = {
            "segment_start": {"value": [0, 0, 0], "unit": "mm"},
            "segment_end": {"value": [0, 0, 0], "unit": "mm"},
        }
        expect_error(
            worker,
            request("spatial.intersection_candidates", [mesh_source],
                    zero_segment, out, "zero-segment"),
            "DEGENERATE_SEGMENT_QUERY",
        )

        out = root / "out-k-too-large"
        out.mkdir()
        too_many = dict(nearest_params)
        too_many["k"] = 6
        expect_error(
            worker,
            request("spatial.nearest_neighbors", [point_source], too_many,
                    out, "k-too-large"),
            "INVALID_K",
        )

        # A syntactically valid forged analysis must fail the independent replay.
        forged = root / "forged.json"
        forged_report = json.loads(closest_path.read_text(encoding="utf-8"))
        forged_report["results"]["primitive_index"] = 3
        forged.write_text(json.dumps(forged_report) + "\n", encoding="utf-8")
        candidate = {
            "artifact_id": "forged", "type": "GeometryAnalysisReport",
            "unit": "none", "format": "json", "path": str(forged.resolve()),
            "sha256": sha256(forged),
        }
        out = root / "out-forged"
        out.mkdir()
        forged_result = run(
            worker,
            request(OPS["spatial.aabb.closest_point"],
                    [candidate, mesh_source], closest_params,
                    out, "forged-validate", kernel="exact_constructions"),
        )
        assert forged_result["status"] == "error", forged_result
        assert forged_result["error"]["code"] == "REPORT_SEMANTICS_MISMATCH"

        assert sha256(points) == point_hash
        assert sha256(mesh) == mesh_hash

    print("Spatial Query 7.2 native worker: 5 analyses + 5 validators: PASS")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: master_wave_c_spatial_cases.py WORKER")
    main(str(Path(sys.argv[1]).resolve()))
