"""Direct acceptance cases for CGAL Master Spatial AABB closest-point queries."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile


ANALYSIS = "spatial.aabb.closest_point"
VALIDATOR = "spatial.validate.aabb_closest_point"
SEGMENT_ANALYSIS = "spatial.aabb.segment_candidates"
SEGMENT_VALIDATOR = "spatial.validate.aabb_segment_candidates"
ROOT = pathlib.Path(__file__).resolve().parents[1]


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_off(path: pathlib.Path, points: list[tuple[float, float, float]],
              faces: list[tuple[int, int, int]]) -> None:
    lines = ["OFF", f"{len(points)} {len(faces)} 0"]
    lines += [f"{x:.17g} {y:.17g} {z:.17g}" for x, y, z in points]
    lines += ["3 " + " ".join(map(str, face)) for face in faces]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def artifact(path: pathlib.Path, artifact_id: str, *, unit: str = "cm",
             geometry_type: str = "TriangleSurfaceMesh",
             fmt: str = "off") -> dict:
    return {
        "artifact_id": artifact_id,
        "type": geometry_type,
        "unit": unit,
        "format": fmt,
        "path": str(path.resolve()),
        "sha256": sha256(path),
    }


def request(operation: str, inputs: list[dict], output: pathlib.Path,
            query: dict, request_id: str,
            *, kernel: str = "package_recommended") -> dict:
    return {
        "protocol": 1,
        "request_id": request_id,
        "operation": operation,
        "inputs": inputs,
        "parameters": {"query": query},
        "output_dir": str(output.resolve()),
        "kernel": kernel,
        "limits": {"wall_time_ms": 120_000, "memory_mb": 2048},
    }


def segment_request(operation: str, inputs: list[dict], output: pathlib.Path,
                    source: dict, target: dict, request_id: str,
                    *, kernel: str = "package_recommended") -> dict:
    return {
        "protocol": 1,
        "request_id": request_id,
        "operation": operation,
        "inputs": inputs,
        "parameters": {"source": source, "target": target},
        "output_dir": str(output.resolve()),
        "kernel": kernel,
        "limits": {"wall_time_ms": 120_000, "memory_mb": 2048},
    }


def run(worker: str, value: dict) -> dict:
    process = subprocess.run(
        [worker], input=json.dumps(value) + "\n",
        text=True, encoding="utf-8", capture_output=True, timeout=120,
    )
    assert process.returncode == 0, (process.returncode, process.stderr)
    assert process.stderr == "", process.stderr
    lines = process.stdout.splitlines()
    assert len(lines) == 1, process.stdout
    result = json.loads(lines[0])
    assert result["protocol"] == 1
    assert result["request_id"] == value.get("request_id", "")
    return result


def expect_error(worker: str, value: dict, code: str,
                 error_class: str | None = None) -> dict:
    result = run(worker, value)
    assert result["status"] == "error", result
    assert result["error"]["code"] == code, result
    if error_class is not None:
        assert result["error"]["class"] == error_class, result
    assert result["outputs"] == [], result
    return result


def main(worker: str) -> None:
    manifest_process = subprocess.run(
        [worker, "--manifest"], text=True, encoding="utf-8",
        capture_output=True, timeout=30,
    )
    assert manifest_process.returncode == 0, manifest_process.stderr
    assert manifest_process.stderr == ""
    manifest = json.loads(manifest_process.stdout)
    operations = {item["id"]: item for item in manifest["operations"]}
    assert {ANALYSIS, VALIDATOR, SEGMENT_ANALYSIS, SEGMENT_VALIDATOR} <= \
        set(operations), operations.keys()

    analysis_manifest = operations[ANALYSIS]
    assert analysis_manifest["role"] == "analysis"
    assert analysis_manifest["input_types"] == ["TriangleSurfaceMesh"]
    assert analysis_manifest["output_type"] == "GeometryAnalysisReport"
    assert analysis_manifest["supported_kernels"] == ["package_recommended"]
    assert analysis_manifest["effective_kernel"] == (
        "CGAL::Exact_predicates_inexact_constructions_kernel")
    assert analysis_manifest["dependencies"] == ["AABB_tree", "Surface_mesh"]
    assert analysis_manifest["info"]["distance_acceleration"] == (
        "AABB_tree::accelerate_distance_queries")
    assert analysis_manifest["info"]["degenerate_primitive_policy"] == "reject"
    assert analysis_manifest["info"]["validators"] == [VALIDATOR]

    validator_manifest = operations[VALIDATOR]
    assert validator_manifest["role"] == "validator"
    assert validator_manifest["input_types"] == [
        "GeometryAnalysisReport", "TriangleSurfaceMesh"]
    assert validator_manifest["info"]["validates"] == ANALYSIS

    catalog = json.loads(
        (ROOT / "catalog" / "operations_spatial.json").read_text(encoding="utf-8"))
    catalog_operations = {item["id"]: item for item in catalog["operations"]}
    assert {ANALYSIS, VALIDATOR, SEGMENT_ANALYSIS, SEGMENT_VALIDATOR} == \
        set(catalog_operations)
    assert {item["status"] for item in catalog["operations"]} <= {
        "IMPLEMENTED", "VALIDATED"}
    assert catalog_operations[ANALYSIS]["major_requirements"] == [
        "major.7.2.01"]

    with tempfile.TemporaryDirectory(prefix="cgal-spatial-aabb-") as folder:
        root = pathlib.Path(folder)
        mesh = root / "square.off"
        write_off(
            mesh,
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
            [(0, 1, 2), (0, 2, 3)],
        )
        source = artifact(mesh, "square", unit="cm")
        query = {"value": [7.5, 2.5, 20.0], "unit": "mm"}

        analysis_dir = root / "analysis"
        analysis_dir.mkdir()
        result = run(worker, request(
            ANALYSIS, [source], analysis_dir, query, "aabb-distance"))
        assert result["status"] == "ok", result
        assert result["metrics"]["analysis_kind"] == "aabb_closest_point"
        assert result["metrics"]["primitive_count"] == 2
        assert result["metrics"]["distance_acceleration"] is True

        output = result["outputs"][0]
        assert (output["slot"], output["type"], output["format"], output["unit"]) == (
            "analysis", "GeometryAnalysisReport", "json", "none")
        report_path = pathlib.Path(output["path"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["analysis_kind"] == "aabb_closest_point"
        assert report["source"]["sha256"] == sha256(mesh)
        assert report["query"] == {"value": [0.75, 0.25, 2.0], "unit": "cm"}
        assert report["results"]["closest_point"] == {
            "value": [0.75, 0.25, 0.0], "unit": "cm"}
        assert report["results"]["distance"] == {"value": 2.0, "unit": "cm"}
        assert report["results"]["squared_distance"] == {
            "value": 4.0, "unit": "cm^2"}
        assert report["results"]["closest_face_index"] == 0
        assert report["results"]["primitive_count"] == 2
        assert report["results"]["distance_acceleration"] is True

        validate_dir = root / "validate"
        validate_dir.mkdir()
        candidate = artifact(
            report_path, "aabb-report", unit="none",
            geometry_type="GeometryAnalysisReport", fmt="json")
        validation = run(worker, request(
            VALIDATOR, [candidate, source], validate_dir, query, "aabb-validate"))
        assert validation["status"] == "ok", validation
        validation_report = json.loads(
            pathlib.Path(validation["outputs"][0]["path"]).read_text(encoding="utf-8"))
        assert validation_report["status"] == "pass"
        assert validation_report["passed"] is True
        assert validation_report["validator_id"] == VALIDATOR
        assert validation_report["validates"] == ANALYSIS
        assert all(validation_report["checks"].values())

        surface_dir = root / "surface"
        surface_dir.mkdir()
        surface_query = {"value": [0.75, 0.25, 0.0], "unit": "cm"}
        surface_result = run(worker, request(
            ANALYSIS, [source], surface_dir, surface_query, "aabb-surface"))
        surface_report = json.loads(
            pathlib.Path(surface_result["outputs"][0]["path"]).read_text())
        assert surface_report["results"]["distance"]["value"] == 0.0
        assert surface_report["results"]["squared_distance"]["value"] == 0.0

        forged = json.loads(report_path.read_text(encoding="utf-8"))
        forged["results"]["distance"]["value"] = 3.0
        forged_path = root / "forged.json"
        forged_path.write_text(json.dumps(forged) + "\n", encoding="utf-8")
        forged_dir = root / "forged-validate"
        forged_dir.mkdir()
        forged_candidate = artifact(
            forged_path, "forged", unit="none",
            geometry_type="GeometryAnalysisReport", fmt="json")
        rejected = expect_error(
            worker,
            request(VALIDATOR, [forged_candidate, source], forged_dir, query,
                    "aabb-forged"),
            "AABB_REPORT_MISMATCH", "VALIDATION_FAILED")
        assert list(forged_dir.iterdir()) == [], rejected

        exact_dir = root / "exact"
        exact_dir.mkdir()
        exact = expect_error(
            worker,
            request(ANALYSIS, [source], exact_dir, query, "aabb-exact",
                    kernel="exact_constructions"),
            "UNSUPPORTED_KERNEL", "UNSUPPORTED")
        assert list(exact_dir.iterdir()) == [], exact

        invalid_dir = root / "invalid-query"
        invalid_dir.mkdir()
        invalid = request(
            ANALYSIS, [source], invalid_dir,
            {"value": [1.0, 2.0, 3.0]}, "aabb-invalid-query")
        invalid["parameters"] = {"query": {"value": [1.0, 2.0, 3.0]}}
        expect_error(worker, invalid, "INVALID_AABB_QUERY", "INVALID_INPUT")
        assert list(invalid_dir.iterdir()) == []


        segment_manifest = operations[SEGMENT_ANALYSIS]
        assert segment_manifest["role"] == "analysis"
        assert segment_manifest["input_types"] == ["TriangleSurfaceMesh"]
        assert segment_manifest["output_type"] == "GeometryAnalysisReport"
        assert segment_manifest["supported_kernels"] == ["package_recommended"]
        assert segment_manifest["dependencies"] == ["AABB_tree", "Surface_mesh"]
        assert segment_manifest["info"]["constructs_intersection_geometry"] is False
        assert segment_manifest["info"]["validators"] == [SEGMENT_VALIDATOR]
        assert operations[SEGMENT_VALIDATOR]["info"]["validates"] == SEGMENT_ANALYSIS

        segment_source = {"value": [7.5, 2.5, -10.0], "unit": "mm"}
        segment_target = {"value": [7.5, 2.5, 10.0], "unit": "mm"}
        segment_dir = root / "segment"
        segment_dir.mkdir()
        segment_result = run(worker, segment_request(
            SEGMENT_ANALYSIS, [source], segment_dir,
            segment_source, segment_target, "aabb-segment"))
        assert segment_result["status"] == "ok", segment_result
        segment_path = pathlib.Path(segment_result["outputs"][0]["path"])
        segment_report = json.loads(segment_path.read_text(encoding="utf-8"))
        assert segment_report["analysis_kind"] == "aabb_segment_candidates"
        assert segment_report["query"] == {
            "source": {"value": [0.75, 0.25, -1.0], "unit": "cm"},
            "target": {"value": [0.75, 0.25, 1.0], "unit": "cm"},
        }
        assert segment_report["results"]["intersects"] is True
        assert segment_report["results"]["intersection_count"] == 1
        assert segment_report["results"]["face_indices"] == [0]
        assert segment_report["results"]["constructs_intersection_geometry"] is False

        segment_validate_dir = root / "segment-validate"
        segment_validate_dir.mkdir()
        segment_candidate = artifact(
            segment_path, "segment-report", unit="none",
            geometry_type="GeometryAnalysisReport", fmt="json")
        segment_validation = run(worker, segment_request(
            SEGMENT_VALIDATOR, [segment_candidate, source],
            segment_validate_dir, segment_source, segment_target,
            "aabb-segment-validate"))
        assert segment_validation["status"] == "ok", segment_validation
        segment_validation_report = json.loads(pathlib.Path(
            segment_validation["outputs"][0]["path"]).read_text(encoding="utf-8"))
        assert segment_validation_report["passed"] is True
        assert all(segment_validation_report["checks"].values())

        miss_dir = root / "segment-miss"
        miss_dir.mkdir()
        miss_result = run(worker, segment_request(
            SEGMENT_ANALYSIS, [source], miss_dir,
            {"value": [20, 20, -10], "unit": "mm"},
            {"value": [20, 20, 10], "unit": "mm"},
            "aabb-segment-miss"))
        miss_report = json.loads(pathlib.Path(
            miss_result["outputs"][0]["path"]).read_text(encoding="utf-8"))
        assert miss_report["results"]["intersects"] is False
        assert miss_report["results"]["intersection_count"] == 0
        assert miss_report["results"]["face_indices"] == []

        forged_segment = json.loads(segment_path.read_text(encoding="utf-8"))
        forged_segment["results"]["face_indices"] = [1]
        forged_segment_path = root / "forged-segment.json"
        forged_segment_path.write_text(
            json.dumps(forged_segment) + "\n", encoding="utf-8")
        forged_segment_dir = root / "forged-segment-validate"
        forged_segment_dir.mkdir()
        expect_error(
            worker,
            segment_request(
                SEGMENT_VALIDATOR,
                [artifact(forged_segment_path, "forged-segment", unit="none",
                          geometry_type="GeometryAnalysisReport", fmt="json"),
                 source],
                forged_segment_dir, segment_source, segment_target,
                "aabb-forged-segment"),
            "AABB_SEGMENT_REPORT_MISMATCH", "VALIDATION_FAILED")
        assert list(forged_segment_dir.iterdir()) == []

        zero_dir = root / "segment-zero"
        zero_dir.mkdir()
        expect_error(
            worker,
            segment_request(
                SEGMENT_ANALYSIS, [source], zero_dir,
                {"value": [1, 1, 1], "unit": "cm"},
                {"value": [1, 1, 1], "unit": "cm"},
                "aabb-zero-segment"),
            "ZERO_LENGTH_SEGMENT", "PRECONDITION_FAILED")
        assert list(zero_dir.iterdir()) == []

        degenerate = root / "degenerate.off"
        write_off(
            degenerate,
            [(0, 0, 0), (1, 0, 0), (2, 0, 0)],
            [(0, 1, 2)],
        )
        degenerate_dir = root / "degenerate"
        degenerate_dir.mkdir()
        expect_error(
            worker,
            request(
                ANALYSIS, [artifact(degenerate, "degenerate", unit="cm")],
                degenerate_dir, {"value": [0, 0, 1], "unit": "cm"},
                "aabb-degenerate"),
            "DEGENERATE_AABB_PRIMITIVE", "PRECONDITION_FAILED")
        assert list(degenerate_dir.iterdir()) == []

    print("CGAL Master Spatial AABB closest-point + segment candidates + validators: PASS")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: master_spatial_aabb_cases.py WORKER")
    main(str(pathlib.Path(sys.argv[1]).resolve()))
