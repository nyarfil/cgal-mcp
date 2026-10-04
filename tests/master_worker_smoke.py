"""Protocol-1 smoke test for the generic CGAL Master worker."""

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def invoke(worker: str, request: dict, *, timeout: int = 60):
    process = subprocess.run(
        [worker],
        input=json.dumps(request, separators=(",", ":")) + "\n",
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
    )
    lines = process.stdout.splitlines()
    assert len(lines) == 1, process.stdout
    assert process.stderr == "", process.stderr
    return process, json.loads(lines[0])


def artifact(path: pathlib.Path, artifact_id: str, artifact_type: str, fmt: str):
    return {
        "artifact_id": artifact_id,
        "type": artifact_type,
        "unit": "mm",
        "format": fmt,
        "path": str(path.resolve()),
        "sha256": digest(path),
    }


def request(request_id: str, operation: str, inputs: list[dict], output_dir: pathlib.Path):
    return {
        "protocol": 1,
        "request_id": request_id,
        "operation": operation,
        "inputs": inputs,
        "parameters": {},
        "output_dir": str(output_dir.resolve()),
        "kernel": "exact_constructions",
        "limits": {"wall_time_ms": 60000, "memory_mb": 1024},
    }


worker = sys.argv[1]
manifest_process = subprocess.run(
    [worker, "--manifest"], text=True, encoding="utf-8",
    capture_output=True, timeout=20
)
assert manifest_process.returncode == 0, manifest_process.stderr
assert manifest_process.stderr == "", manifest_process.stderr
manifest = json.loads(manifest_process.stdout)
assert manifest["protocol"] == 1
assert manifest["actual_cgal_version"] == "6.2.1", manifest
assert manifest["build"]["source_kind"] == "official_release", manifest
assert manifest["build"]["source_sha256"] == (
    "b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf"
), manifest
operations = {item["id"]: item for item in manifest["operations"]}
assert operations["hull.convex_3"]["role"] == "transform"
assert operations["hull.validate.convex_enclosure"]["role"] == "validator"

with tempfile.TemporaryDirectory() as folder:
    root = pathlib.Path(folder) / "日本語ステージ"
    root.mkdir()
    points = root / "tetra.xyz"
    points.write_text("0 0 0\n1 0 0\n0 1 0\n0 0 1\n", encoding="ascii")
    hull_stage = root / "hull-stage"
    hull_stage.mkdir()
    hull_request = request(
        "smoke-hull",
        "hull.convex_3",
        [artifact(points, "tetra-points", "PointSet3", "xyz")],
        hull_stage,
    )
    process, hull_result = invoke(worker, hull_request)
    assert process.returncode == 0, hull_result
    assert hull_result["request_id"] == "smoke-hull"
    assert hull_result["status"] == "ok", hull_result
    assert hull_result["diagnostics"] == []
    hull_output = hull_result["outputs"][0]
    assert hull_output["slot"] == "geometry"
    assert hull_output["type"] == "TriangleSurfaceMesh"
    hull_path = pathlib.Path(hull_output["path"])
    assert hull_path.resolve().parent == hull_stage.resolve()
    assert hull_path.name == "geometry.off" and hull_path.is_file()

    validation_stage = root / "validation-stage"
    validation_stage.mkdir()
    validation_request = request(
        "smoke-validation",
        "hull.validate.convex_enclosure",
        [
            artifact(hull_path, "tetra-hull", "TriangleSurfaceMesh", "off"),
            artifact(points, "tetra-points", "PointSet3", "xyz"),
        ],
        validation_stage,
    )
    process, validation_result = invoke(worker, validation_request)
    assert process.returncode == 0, validation_result
    assert validation_result["status"] == "ok", validation_result
    assert validation_result["metrics"]["valid"] is True
    assert validation_result["metrics"]["all_original_points_enclosed"] is True
    report_path = pathlib.Path(validation_result["outputs"][0]["path"])
    assert report_path.resolve().parent == validation_stage.resolve()
    assert json.loads(report_path.read_text(encoding="utf-8"))["valid"] is True

print("Master worker manifest, tetrahedron hull, independent validator: PASS")
