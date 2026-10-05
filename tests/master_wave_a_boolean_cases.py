"""Direct native acceptance cases for formal Wave A PMP Boolean handlers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import pathlib
import subprocess
import sys
import tempfile

from cgal_mcp.master.formats import parse_json_geometry, parse_off


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "master" / "wave_a_boolean"


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: pathlib.Path, artifact_id: str, unit: str = "mm") -> dict:
    return {
        "artifact_id": artifact_id,
        "type": "TriangleSurfaceMesh",
        "unit": unit,
        "format": "off",
        "path": str(path.resolve()),
        "sha256": sha256(path),
    }


def request(operation: str, inputs: list[dict], output: pathlib.Path,
            kind: str, request_id: str, *, kernel: str = "package_recommended") -> dict:
    return {
        "protocol": 1,
        "request_id": request_id,
        "operation": operation,
        "inputs": inputs,
        "parameters": {"operation": kind},
        "output_dir": str(output.resolve()),
        "kernel": kernel,
        "limits": {"wall_time_ms": 120_000, "memory_mb": 4096},
    }


def run(worker: str, value: dict) -> dict:
    process = subprocess.run(
        [worker], input=json.dumps(value) + "\n", text=True, encoding="utf-8",
        capture_output=True, timeout=120,
    )
    assert process.returncode == 0, (process.returncode, process.stderr)
    assert process.stderr == "", process.stderr
    lines = process.stdout.splitlines()
    assert len(lines) == 1, process.stdout
    result = json.loads(lines[0])
    assert result["protocol"] == 1
    assert result["request_id"] == value.get("request_id", "")
    return result


def read_off(path: pathlib.Path) -> tuple[list[tuple[float, float, float]],
                                           list[tuple[int, int, int]]]:
    tokens: list[str] = []
    for raw in path.read_text(encoding="ascii").splitlines():
        tokens.extend(raw.split("#", 1)[0].split())
    assert tokens[0] == "OFF"
    vertex_count, face_count = map(int, tokens[1:3])
    cursor = 4
    points = []
    for _ in range(vertex_count):
        points.append(tuple(map(float, tokens[cursor:cursor + 3])))
        cursor += 3
    faces = []
    for _ in range(face_count):
        assert tokens[cursor] == "3"
        faces.append(tuple(map(int, tokens[cursor + 1:cursor + 4])))
        cursor += 4
    assert cursor == len(tokens)
    return points, faces


def signed_volume(path: pathlib.Path) -> float:
    points, faces = read_off(path)
    volume = 0.0
    for i, j, k in faces:
        a, b, c = points[i], points[j], points[k]
        volume += (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        ) / 6.0
    return volume


def invoke_transform(worker: str, root: pathlib.Path, kind: str,
                     source_a: pathlib.Path, source_b: pathlib.Path,
                     case: str) -> tuple[dict, pathlib.Path]:
    output = root / f"{case}-{kind}"
    output.mkdir()
    result = run(
        worker,
        request(
            f"mesh.boolean.{kind}",
            [artifact(source_a, f"{case}-a"), artifact(source_b, f"{case}-b")],
            output, kind, f"{case}-{kind}",
        ),
    )
    assert result["status"] == "ok", result
    assert len(result["outputs"]) == 1
    entry = result["outputs"][0]
    assert (entry["slot"], entry["type"], entry["format"], entry["unit"]) == (
        "geometry", "TriangleSurfaceMesh", "off", "mm")
    candidate = pathlib.Path(entry["path"])
    assert candidate.resolve().is_relative_to(output.resolve())
    assert candidate.exists()
    return result, candidate


def invoke_validator(worker: str, root: pathlib.Path, kind: str,
                     candidate: pathlib.Path, source_a: pathlib.Path,
                     source_b: pathlib.Path, case: str) -> dict:
    output = root / f"{case}-{kind}-validate"
    output.mkdir()
    result = run(
        worker,
        request(
            f"mesh.validate.boolean_{kind}",
            [artifact(candidate, f"{case}-candidate"),
             artifact(source_a, f"{case}-a"),
             artifact(source_b, f"{case}-b")],
            output, kind, f"{case}-{kind}-validate",
        ),
    )
    assert result["status"] == "ok", result
    assert result["metrics"]["passed"] is True
    report_path = pathlib.Path(result["outputs"][0]["path"])
    report = json.loads(report_path.read_text())
    assert report["schema_version"] == 1 and report["status"] == "pass"
    inspection = parse_json_geometry(report_path.read_bytes(), "ValidationReport")
    assert inspection.geometry_type == "ValidationReport"
    assert report["passed"] is True
    assert report["operation"] == kind
    assert report["checks"]["operation_parameter_bound"] is True
    assert report["checks"]["exact_volume_matches_reference"] is True
    assert report["checks"]["mutual_exact_difference_empty"] is True
    assert report["checks"]["operation_classification_matches"] is True
    assert report["bindings"]["candidate_sha256"] == sha256(candidate)
    return result


def expect_error(worker: str, root: pathlib.Path, operation: str,
                 inputs: list[dict], kind: str, case: str,
                 codes: set[str], error_class: str | None = None) -> dict:
    output = root / case
    output.mkdir()
    result = run(worker, request(operation, inputs, output, kind, case))
    assert result["status"] == "error", result
    assert result["error"]["code"] in codes, result
    if error_class is not None:
        assert result["error"]["class"] == error_class, result
    assert result["outputs"] == []
    assert list(output.iterdir()) == [], (result, list(output.iterdir()))
    return result


def translated_candidate(source: pathlib.Path, destination: pathlib.Path) -> None:
    points, faces = read_off(source)
    lines = ["OFF", f"{len(points)} {len(faces)} 0"]
    lines.extend(f"{x + 10:.17g} {y:.17g} {z:.17g}" for x, y, z in points)
    lines.extend("3 " + " ".join(map(str, face)) for face in faces)
    destination.write_text("\n".join(lines) + "\n", encoding="ascii")


def main(worker: str) -> None:
    manifest_process = subprocess.run(
        [worker, "--manifest"], text=True, encoding="utf-8",
        capture_output=True, timeout=30,
    )
    assert manifest_process.returncode == 0, manifest_process.stderr
    assert manifest_process.stderr == ""
    manifest = json.loads(manifest_process.stdout)
    operations = {item["id"]: item for item in manifest["operations"]}
    expected = {
        "mesh.boolean.union", "mesh.boolean.intersection",
        "mesh.boolean.difference", "mesh.validate.boolean_union",
        "mesh.validate.boolean_intersection", "mesh.validate.boolean_difference",
    }
    # Master MCP is intentionally extensible; Boolean acceptance must not pin\n    # the global operation count as new validated capability slices are added.\n    assert expected <= set(operations), operations.keys()\n    for item in (operations[operation] for operation in expected):
        assert item["revision"] == 1
        assert item["supported_kernels"] == [
            "exact_constructions", "package_recommended"]
        assert item["effective_kernel"] == (
            "CGAL::Exact_predicates_exact_constructions_kernel")
        assert item["dependencies"] == [
            "Polygon_mesh_processing", "Surface_mesh", "AABB_tree"]
    for kind in ("union", "intersection", "difference"):
        info = operations[f"mesh.boolean.{kind}"]["info"]
        assert info["validator_parameter_bindings"] == {
            f"mesh.validate.boolean_{kind}": {"operation": "operation"}}
        assert info["precision_contract"]["internal_kernel"] == "EPECK"
        assert info["precision_contract"]["unrepresentable_policy"].startswith(
            "NUMERIC_FAILURE/OUTPUT_BINARY64_LOSS")
        validator = operations[f"mesh.validate.boolean_{kind}"]["info"]
        assert validator["precision_contract"] == {
            "internal_kernel": "EPECK",
            "input_coordinate_storage": (
                "IEEE-754 binary64 converted to exact binary-rational coordinates"),
            "reference_comparison": (
                "exact EPECK Boolean replay, exact signed volume, and mutual "
                "exact set difference"),
            "report_numeric_storage": (
                "booleans and exact rational strings; no approximate tolerance"),
        }
        assert validator["required_report_checks"] == {
            "schema_version": 1,
            "schema": "ValidationReport/v1",
            "status": "pass",
            "validator_id": f"mesh.validate.boolean_{kind}",
            "validates": f"mesh.boolean.{kind}",
            "passed": True,
            "operation": kind,
            "bindings.operation_parameter": kind,
            "checks.topology_valid": True,
            "checks.closed_or_canonical_empty": True,
            "checks.volume_boundary_orientation_valid": True,
            "checks.self_intersection_free": True,
            "checks.operation_parameter_bound": True,
            "checks.result_status_matches_reference": True,
            "checks.exact_volume_matches_reference": True,
            "checks.mutual_exact_difference_empty": True,
            "checks.operation_classification_matches": True,
        }

    catalog = json.loads(
        (ROOT / "catalog" / "operations_wave_a_boolean.json").read_text(encoding="utf-8"))
    assert len(catalog["operations"]) == 6
    if catalog["catalog_revision"] == "wave-a-boolean-validated-1":
        assert {item["status"] for item in catalog["operations"]} == {"VALIDATED"}
        assert all(item["evidence"]["review_status"] == "independent_review_pass"
                   and item["evidence"]["independent_review"]["status"] == "pass"
                   and item["evidence"]["independent_review"]["high"] == 0
                   and item["evidence"]["independent_review"]["medium"] == 0
                   for item in catalog["operations"])
    else:
        assert catalog["catalog_revision"] == "wave-a-boolean-implemented-2"
        assert {item["status"] for item in catalog["operations"]} == {"IMPLEMENTED"}
        assert all(item["evidence"]["review_status"] == "pending_independent_review"
                   for item in catalog["operations"])
    catalog_operations = {item["id"]: item for item in catalog["operations"]}
    for operation in expected:
        item = catalog_operations[operation]
        assert item["evidence"]["build"] == (
            "build-master/Release/cgal-master-worker.exe")
        assert item["worker_manifest"] == {
            "require_dependencies": True,
            "effective_kernel": operations[operation]["effective_kernel"],
            "info": operations[operation]["info"],
        }
        if operation.startswith("mesh.validate."):
            checks = operations[operation]["info"]["required_report_checks"]
            assert item["validation"]["required_report_checks"] == checks
            assert item["runtime_report_contract"][
                "required_report_checks"] == checks

    a = FIXTURES / "cube_a.off"
    source_digest = sha256(a)
    scenarios = [
        ("overlap", FIXTURES / "cube_overlap.off",
         {"union": ("volume", 12.0), "intersection": ("volume", 4.0),
          "difference": ("volume", 4.0)}),
        ("disjoint", FIXTURES / "cube_disjoint.off",
         {"union": ("volume", 16.0), "intersection": ("empty", 0.0),
          "difference": ("volume", 8.0)}),
        ("contained", FIXTURES / "cube_contained.off",
         {"union": ("volume", 8.0), "intersection": ("volume", 1.0),
          "difference": ("volume", 7.0)}),
        ("identical", FIXTURES / "cube_identical.off",
         {"union": ("volume", 8.0), "intersection": ("volume", 8.0),
          "difference": ("empty", 0.0)}),
        ("face-touch", FIXTURES / "cube_face_touch.off",
         {"union": ("volume", 16.0), "intersection": ("empty", 0.0),
          "difference": ("volume", 8.0)}),
        ("partial-coplanar", FIXTURES / "cube_partial_coplanar_touch.off",
         {"union": ("volume", 10.0), "intersection": ("empty", 0.0),
          "difference": ("volume", 8.0)}),
    ]
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        successful: dict[tuple[str, str], pathlib.Path] = {}
        for label, other, expectations in scenarios:
            for kind, (status, volume) in expectations.items():
                result, candidate = invoke_transform(
                    worker, root, kind, a, other, label)
                assert result["metrics"]["result_status"] == status, result
                assert math.isclose(signed_volume(candidate), volume,
                                    rel_tol=0, abs_tol=1e-12), result
                if status == "empty":
                    points, faces = read_off(candidate)
                    assert points == [] and faces == []
                    assert parse_off(candidate.read_bytes()).geometry_type == (
                        "TriangleSurfaceMesh")
                    assert result["metrics"]["empty_reason"]
                invoke_validator(worker, root, kind, candidate, a, other, label)
                successful[(label, kind)] = candidate

        # A point contact is an explicit zero-volume intersection.
        for label, other in (
            ("point-touch", FIXTURES / "cube_point_touch.off"),
        ):
            result, candidate = invoke_transform(
                worker, root, "intersection", a, other, label)
            assert result["metrics"]["result_status"] == "empty", result
            assert result["metrics"]["empty_reason"] == "lower_dimensional_contact"
            invoke_validator(worker, root, "intersection", candidate, a, other,
                             label)

        # A point-touch union is not a manifold volume and must not be published.
        expect_error(
            worker, root, "mesh.boolean.union",
            [artifact(a, "point-a"),
             artifact(FIXTURES / "cube_point_touch.off", "point-b")],
            "union", "point-touch-union",
            {"BOOLEAN_RESULT_NOT_MANIFOLD", "NON_MANIFOLD_VERTEX",
             "SELF_INTERSECTION"}, "PRECONDITION_FAILED",
        )

        # Candidate tampering remains a valid closed mesh but fails set semantics.
        tampered = root / "tampered-union.off"
        translated_candidate(successful[("overlap", "union")], tampered)
        expect_error(
            worker, root, "mesh.validate.boolean_union",
            [artifact(tampered, "tampered"), artifact(a, "tamper-a"),
             artifact(FIXTURES / "cube_overlap.off", "tamper-b")],
            "union", "tampered-validator", {"BOOLEAN_SET_SEMANTICS_MISMATCH"},
        )

        open_candidate = expect_error(
            worker, root, "mesh.validate.boolean_union",
            [artifact(FIXTURES / "open_cube.off", "open-candidate"),
             artifact(a, "open-source-a"),
             artifact(FIXTURES / "cube_overlap.off", "open-source-b")],
            "union", "open-candidate-validator",
            {"BOOLEAN_CANDIDATE_MESH_NOT_CLOSED"},
        )
        assert open_candidate["error"]["class"] == "VALIDATION_FAILED"

        # Exact operation binding is mandatory on both transform and validator.
        output = root / "binding-mismatch"
        output.mkdir()
        bad = request(
            "mesh.boolean.union",
            [artifact(a, "binding-a"),
             artifact(FIXTURES / "cube_overlap.off", "binding-b")],
            output, "intersection", "binding-mismatch",
        )
        mismatch = run(worker, bad)
        assert mismatch["error"]["code"] == "BOOLEAN_OPERATION_BINDING_MISMATCH"
        assert mismatch["error"]["class"] == "INVALID_INPUT"
        assert list(output.iterdir()) == []

        invalid_cases = [
            ("open", FIXTURES / "open_cube.off", {"MESH_NOT_CLOSED"}),
            ("degenerate", FIXTURES / "degenerate_tetra.off",
             {"DEGENERATE_FACE", "MESH_DOES_NOT_BOUND_VOLUME",
              "SELF_INTERSECTION"}),
            ("nonmanifold", FIXTURES / "nonmanifold_vertex.off",
             {"INVALID_POLYGON_MESH", "NON_MANIFOLD_VERTEX",
              "SELF_INTERSECTION"}),
            ("inward", FIXTURES / "inward_cube.off",
             {"MESH_NOT_OUTWARD_ORIENTED", "MESH_DOES_NOT_BOUND_VOLUME"}),
            ("extreme-scale", FIXTURES / "extreme_scale_cube.off",
             {"UNSUPPORTED_NUMERIC_SCALE"}),
            ("extreme-translation", FIXTURES / "extreme_translation_cube.off",
             {"UNSUPPORTED_NUMERIC_SCALE"}),
        ]
        for label, source, codes in invalid_cases:
            expect_error(
                worker, root, "mesh.boolean.union",
                [artifact(source, f"{label}-a"),
                 artifact(FIXTURES / "cube_disjoint.off", f"{label}-b")],
                "union", f"invalid-{label}", codes,
                "PRECONDITION_FAILED",
            )

        # Two-source unit equality is checked before CGAL dispatch.
        expect_error(
            worker, root, "mesh.boolean.union",
            [artifact(a, "unit-a", "mm"),
             artifact(FIXTURES / "cube_overlap.off", "unit-b", "m")],
            "union", "unit-mismatch", {"UNIT_MISMATCH"}, "INVALID_INPUT",
        )

        exact_output = root / "exact-kernel"
        exact_output.mkdir()
        exact_result = run(worker, request(
            "mesh.boolean.union",
            [artifact(a, "exact-a"),
             artifact(FIXTURES / "cube_disjoint.off", "exact-b")],
            exact_output, "union", "exact-kernel",
            kernel="exact_constructions",
        ))
        assert exact_result["status"] == "ok", exact_result
        assert exact_result["metrics"]["effective_kernel"] == (
            "CGAL::Exact_predicates_exact_constructions_kernel")

        bad_kernel_output = root / "bad-kernel"
        bad_kernel_output.mkdir()
        bad_kernel = run(worker, request(
            "mesh.boolean.union",
            [artifact(a, "bad-kernel-a"),
             artifact(FIXTURES / "cube_disjoint.off", "bad-kernel-b")],
            bad_kernel_output, "union", "bad-kernel", kernel="inexact_fast",
        ))
        assert bad_kernel["status"] == "error"
        assert bad_kernel["error"]["code"] == "UNSUPPORTED_KERNEL"
        # The shared protocol parser rejects unknown policy names before
        # operation dispatch using the established formal-worker taxonomy.
        assert bad_kernel["error"]["class"] == "UNSUPPORTED"
        assert list(bad_kernel_output.iterdir()) == []

        # Rational EPECK intersections that binary64 OFF cannot preserve fail closed.
        expect_error(
            worker, root, "mesh.boolean.intersection",
            [artifact(FIXTURES / "skew_tetra.off", "fraction-a"),
             artifact(FIXTURES / "fraction_cut_cube.off", "fraction-b")],
            "intersection", "binary64-loss",
            {"OUTPUT_BINARY64_LOSS"}, "NUMERIC_FAILURE",
        )

        # Formal worker output publication uses the global IO failure class.
        occupied_output = successful[("overlap", "union")].parent
        occupied = run(worker, request(
            "mesh.boolean.union",
            [artifact(a, "occupied-a"),
             artifact(FIXTURES / "cube_overlap.off", "occupied-b")],
            occupied_output, "union", "occupied-output"))
        assert occupied["status"] == "error", occupied
        assert occupied["error"]["class"] == "IO_FAILURE", occupied
        assert occupied["error"]["code"] == "OUTPUT_EXISTS", occupied

        assert sha256(a) == source_digest, "Boolean worker mutated source A"

    print(
        "Wave A PMP Boolean: 3 transforms, 3 separate exact-binding validators, "
        "overlap/disjoint/contained/identical/contact, invalid topology, numeric "
        "limits, binary64 fail-closed, immutability: PASS"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: master_wave_a_boolean_cases.py WORKER")
    main(sys.argv[1])
