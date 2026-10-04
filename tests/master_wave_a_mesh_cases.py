"""Direct acceptance cases for the bounded Wave A mesh-analysis worker.

The suite generates synthetic OFF inputs in a temporary directory and runs the
newline-delimited protocol against the independent official-CGAL harness.
"""

from __future__ import annotations

import hashlib
import json
import math
import pathlib
import subprocess
import sys
import tempfile


ANALYSIS_OPS = {
    "mesh.inspect.pmp",
    "mesh.analysis.connected_components",
    "mesh.analysis.normals",
    "mesh.analysis.measures",
    "mesh.analysis.sharp_features",
    "mesh.analysis.self_intersections",
}
VALIDATORS = {
    "mesh.inspect.pmp": "mesh.validate.pmp_inspection_report",
    "mesh.analysis.connected_components":
        "mesh.validate.connected_components_report",
    "mesh.analysis.normals": "mesh.validate.normals_report",
    "mesh.analysis.measures": "mesh.validate.measures_report",
    "mesh.analysis.sharp_features": "mesh.validate.sharp_features_report",
    "mesh.analysis.self_intersections":
        "mesh.validate.self_intersections_report",
}
OPS = ANALYSIS_OPS | set(VALIDATORS.values())


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_off(path: pathlib.Path, points: list[tuple[float, float, float]],
              faces: list[tuple[int, ...]]) -> None:
    lines = ["OFF", f"{len(points)} {len(faces)} 0"]
    lines += [f"{x:.17g} {y:.17g} {z:.17g}" for x, y, z in points]
    lines += [f"{len(face)} " + " ".join(map(str, face)) for face in faces]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def artifact(path: pathlib.Path, unit: str = "mm",
             geometry_type: str = "TriangleSurfaceMesh") -> dict:
    return {"artifact_id": path.stem, "type": geometry_type,
            "unit": unit, "format": "off", "path": str(path.resolve()),
            "sha256": sha256(path)}


def request(operation: str, source: pathlib.Path, output: pathlib.Path,
            parameters: dict | None = None, *, request_id: str,
            unit: str = "mm", kernel: str = "package_recommended",
            source_type: str = "TriangleSurfaceMesh") -> dict:
    return {"protocol": 1, "request_id": request_id, "operation": operation,
            "inputs": [artifact(source, unit, source_type)],
            "parameters": parameters or {},
            "output_dir": str(output.resolve()), "kernel": kernel,
            "limits": {"wall_time_ms": 120_000, "memory_mb": 2048}}


def run(worker: str, value: dict) -> dict:
    process = subprocess.run([worker], input=json.dumps(value) + "\n",
                             text=True, encoding="utf-8", capture_output=True,
                             timeout=120)
    assert process.returncode == 0, (process.returncode, process.stderr)
    assert process.stderr == "", process.stderr
    lines = process.stdout.splitlines()
    assert len(lines) == 1, process.stdout
    result = json.loads(lines[0])
    assert result["protocol"] == 1
    assert result["request_id"] == value.get("request_id", "")
    return result


def invoke(worker: str, root: pathlib.Path, operation: str,
           source: pathlib.Path, *, parameters: dict | None = None,
           case: str, unit: str = "mm",
           source_type: str = "TriangleSurfaceMesh") -> tuple[dict, dict]:
    output = root / f"out-{case}"
    output.mkdir()
    result = run(worker, request(operation, source, output, parameters,
                                 request_id=case, unit=unit,
                                 source_type=source_type))
    assert result["status"] == "ok", result
    assert len(result["outputs"]) == 1
    entry = result["outputs"][0]
    assert entry["slot"] == "analysis"
    assert entry["type"] == "GeometryAnalysisReport"
    assert entry["format"] == "json" and entry["unit"] == "none"
    report_path = pathlib.Path(entry["path"])
    assert report_path.resolve().is_relative_to(output.resolve())
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["source"]["sha256"] == sha256(source)
    assert report["validation"]["passed"] is True
    assert sha256(source) == result["metrics"]["source_sha256"]
    return result, report


def assert_error(worker: str, value: dict, code: str,
                 error_class: str | None = None) -> None:
    result = run(worker, value)
    assert result["status"] == "error", result
    assert result["error"]["code"] == code, result
    if error_class:
        assert result["error"]["class"] == error_class, result


def validate(worker: str, root: pathlib.Path, operation: str,
             analysis_result: dict, source: pathlib.Path, *, case: str,
             parameters: dict | None = None, unit: str = "mm",
             source_type: str = "TriangleSurfaceMesh") -> dict:
    output = root / f"out-{case}"
    output.mkdir()
    report_path = pathlib.Path(analysis_result["outputs"][0]["path"])
    candidate = {"artifact_id": case + "-candidate",
                 "type": "GeometryAnalysisReport", "unit": "none",
                 "format": "json", "path": str(report_path.resolve()),
                 "sha256": sha256(report_path)}
    value = {"protocol": 1, "request_id": case,
             "operation": VALIDATORS[operation],
             "inputs": [candidate, artifact(source, unit, source_type)],
             "parameters": parameters or {},
             "output_dir": str(output.resolve()),
             "kernel": "package_recommended",
             "limits": {"wall_time_ms": 120_000, "memory_mb": 2048}}
    result = run(worker, value)
    assert result["status"] == "ok", result
    entry = result["outputs"][0]
    assert entry["slot"] == "validation"
    assert entry["type"] == "ValidationReport"
    report = json.loads(pathlib.Path(entry["path"]).read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["passed"] is True
    required = {"schema_valid", "source_identity_matches",
                 "analysis_kind_matches", "dimension_units_valid",
                 "result_semantics_valid", "producer_diagnostic_matches",
                 "official_cgal_reference_match"}
    assert required <= report["checks"].keys()
    assert all(report["checks"][name] is True for name in required)
    return result


def tetra(scale: float = 1.0, offset: float = 0.0):
    p = [(offset, offset, offset), (offset + scale, offset, offset),
         (offset, offset + scale, offset), (offset, offset, offset + scale)]
    f = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]
    return p, f


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: master_wave_a_mesh_cases.py WORKER")
    worker = str(pathlib.Path(sys.argv[1]).resolve())
    manifest_process = subprocess.run([worker, "--manifest"], text=True,
                                      encoding="utf-8", capture_output=True,
                                      timeout=30)
    assert manifest_process.returncode == 0 and manifest_process.stderr == ""
    manifest = json.loads(manifest_process.stdout)
    assert manifest["protocol"] == 1
    assert manifest["actual_cgal_version"] == "6.2.1"
    assert manifest["build"]["source_kind"] == "official_release"
    manifest_operations = {item["id"]: item for item in manifest["operations"]}
    assert OPS <= manifest_operations.keys()
    for item in (manifest_operations[operation] for operation in OPS):
        if item["role"] == "analysis":
            expected = (["TriangleSurfaceMesh", "PolygonSoup3"]
                        if item["id"] == "mesh.inspect.pmp"
                        else ["TriangleSurfaceMesh"])
            assert item["input_types"] == expected
            assert item["output_type"] == "GeometryAnalysisReport"
            assert item["info"]["geometry_mutation"] is False
            assert item["info"]["validators"] == \
                [VALIDATORS[item["id"]]]
            assert item["info"]["max_report_bytes"] == 16 * 1024 * 1024
        else:
            assert item["role"] == "validator"
            expected = (["GeometryAnalysisReport", "TriangleSurfaceMesh",
                         "PolygonSoup3"]
                        if item["id"] ==
                        "mesh.validate.pmp_inspection_report"
                        else ["GeometryAnalysisReport", "TriangleSurfaceMesh"])
            assert item["input_types"] == expected
            assert item["output_type"] == "ValidationReport"
    approximate_output_ops = {
        "mesh.analysis.normals", "mesh.analysis.measures",
        "mesh.analysis.sharp_features", "mesh.validate.normals_report",
        "mesh.validate.measures_report",
        "mesh.validate.sharp_features_report",
    }
    for operation in approximate_output_ops:
        assert manifest_operations[operation]["supported_kernels"] == \
            ["package_recommended"]

    with tempfile.TemporaryDirectory(prefix="cgal-wave-a-mesh-") as temporary:
        root = pathlib.Path(temporary)
        tetra_path = root / "tetra.off"
        points, faces = tetra()
        write_off(tetra_path, points, faces)
        tetra_digest = sha256(tetra_path)

        inspection_result, inspection = invoke(
            worker, root, "mesh.inspect.pmp", tetra_path,
            case="inspect-tetra")
        assert inspection["results"]["polygon_mesh_valid"] is True
        assert inspection["results"]["closed"] is True
        assert inspection["results"]["degenerate_face_count"] == 0
        validate(worker, root, "mesh.inspect.pmp", inspection_result,
                 tetra_path, case="validate-inspect-tetra")
        exact_inspect_out = root / "out-inspect-exact"
        exact_inspect_out.mkdir()
        exact_inspect = request("mesh.inspect.pmp", tetra_path,
                                exact_inspect_out, request_id="inspect-exact",
                                kernel="exact_constructions")
        assert run(worker, exact_inspect)["status"] == "ok"

        normals_result, normals = invoke(
            worker, root, "mesh.analysis.normals", tetra_path,
            case="normals-tetra")
        assert len(normals["results"]["face_normals"]) == 4
        assert len(normals["results"]["vertex_normals"]) == 4
        assert len(normals["results"]["corner_normals"]) == 12
        assert all(item["normal"]["is_unit"] for item in
                   normals["results"]["face_normals"])
        # Analytic fixture: the base face points exactly along negative z.
        assert normals["results"]["face_normals"][0]["normal"]["value"] == \
            [0.0, 0.0, -1.0]
        validate(worker, root, "mesh.analysis.normals", normals_result,
                 tetra_path, case="validate-normals-tetra")
        exact_normals_out = root / "out-normals-exact"
        exact_normals_out.mkdir()
        exact_normals = request("mesh.analysis.normals", tetra_path,
                                exact_normals_out, request_id="normals-exact",
                                kernel="exact_constructions")
        assert_error(worker, exact_normals,
                     "OUTPUT_PRECISION_PROFILE_UNSUPPORTED", "UNSUPPORTED")

        measures_result, measures = invoke(
            worker, root, "mesh.analysis.measures", tetra_path,
            case="measures-tetra", unit="cm")
        values = measures["results"]
        assert values["surface_area"]["unit"] == "cm^2"
        assert values["signed_volume"]["unit"] == "cm^3"
        assert math.isclose(values["signed_volume"]["value"], 1 / 6,
                            rel_tol=1e-12)
        assert values["volume_centroid"]["value"] == [0.25, 0.25, 0.25]
        validate(worker, root, "mesh.analysis.measures", measures_result,
                 tetra_path, case="validate-measures-tetra", unit="cm")

        inward = root / "inward.off"
        write_off(inward, points, [tuple(reversed(face)) for face in faces])
        _, inward_measures = invoke(worker, root, "mesh.analysis.measures",
                                    inward, case="measures-inward")
        assert inward_measures["results"]["signed_volume"]["available"] is False
        assert inward_measures["results"]["signed_volume"]["reason"] == \
            "NONPOSITIVE_ORIENTATION"

        open_path = root / "open.off"
        write_off(open_path, [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                  [(0, 1, 2), (0, 2, 3)])
        _, open_measures = invoke(worker, root, "mesh.analysis.measures",
                                  open_path, case="measures-open")
        assert open_measures["results"]["surface_area"]["value"] == 1
        assert open_measures["results"]["signed_volume"]["reason"] == \
            "MESH_NOT_CLOSED"

        coincident_shells = root / "coincident-shells.off"
        write_off(coincident_shells, points + points,
                  faces + [tuple(index + 4 for index in face)
                           for face in faces])
        coincident_si_result, coincident_si = invoke(
            worker, root, "mesh.analysis.self_intersections",
            coincident_shells, case="si-coincident-shells")
        assert coincident_si["results"]["does_self_intersect"] is True
        assert coincident_si["results"]["intersection_pair_count"] > 0
        validate(worker, root, "mesh.analysis.self_intersections",
                 coincident_si_result, coincident_shells,
                 case="validate-si-coincident-shells")
        coincident_measures_result, coincident_measures = invoke(
            worker, root, "mesh.analysis.measures", coincident_shells,
            case="measures-coincident-shells")
        coincident_results = coincident_measures["results"]
        assert coincident_results["surface_area"]["available"] is True
        for field in ("signed_volume", "absolute_volume", "volume_centroid"):
            assert coincident_results[field]["available"] is False
            assert coincident_results[field]["reason"] == \
                "SELF_INTERSECTING_MESH"
        validate(worker, root, "mesh.analysis.measures",
                 coincident_measures_result, coincident_shells,
                 case="validate-measures-coincident-shells")

        forged_measures_path = root / "forged-coincident-measures.json"
        forged_measures = json.loads(pathlib.Path(
            coincident_measures_result["outputs"][0]["path"]
        ).read_text(encoding="utf-8"))
        forged_measures["results"]["signed_volume"] = {
            "available": True, "value": 1 / 3, "unit": "mm^3"}
        forged_measures_path.write_text(json.dumps(forged_measures) + "\n",
                                        encoding="utf-8")
        forged_out = root / "out-validate-forged-coincident-measures"
        forged_out.mkdir()
        assert_error(worker, {
            "protocol": 1,
            "request_id": "validate-forged-coincident-measures",
            "operation": "mesh.validate.measures_report",
            "inputs": [
                {"artifact_id": "forged-coincident-measures",
                 "type": "GeometryAnalysisReport", "unit": "none",
                 "format": "json", "path": str(forged_measures_path.resolve()),
                 "sha256": sha256(forged_measures_path)},
                artifact(coincident_shells),
            ],
            "parameters": {}, "output_dir": str(forged_out.resolve()),
            "kernel": "package_recommended",
            "limits": {"wall_time_ms": 120_000, "memory_mb": 2048},
        }, "REPORT_SEMANTICS_MISMATCH", "VALIDATION_FAILED")

        multi_path = root / "multi.off"
        second_points, second_faces = tetra(offset=3)
        write_off(multi_path, points + second_points,
                  faces + [tuple(index + 4 for index in face)
                           for face in second_faces])
        components_result, components = invoke(worker, root,
                               "mesh.analysis.connected_components",
                               multi_path, case="components-two")
        assert components["results"]["component_count"] == 2
        assert sorted(c["face_count"] for c in
                      components["results"]["components"]) == [4, 4]
        validate(worker, root, "mesh.analysis.connected_components",
                 components_result, multi_path,
                 case="validate-components-two")

        sharp_result, sharp_deg = invoke(worker, root, "mesh.analysis.sharp_features",
                              tetra_path, parameters={"angle": {"value": 60,
                                                                "unit": "deg"}},
                              case="sharp-deg")
        _, sharp_rad = invoke(worker, root, "mesh.analysis.sharp_features",
                              tetra_path,
                              parameters={"angle": {"value": math.pi / 3,
                                                     "unit": "rad"}},
                              case="sharp-rad")
        assert sharp_deg["results"]["features"]["edges"] == \
            sharp_rad["results"]["features"]["edges"]
        validate(worker, root, "mesh.analysis.sharp_features", sharp_result,
                 tetra_path, case="validate-sharp-deg",
                 parameters={"angle": {"value": 60, "unit": "deg"}})

        crossing = root / "crossing.off"
        write_off(crossing,
                  [(-1, -1, 0), (1, -1, 0), (0, 1, 0),
                   (0, -0.5, -1), (0, -0.5, 1), (0, 0.5, 0)],
                  [(0, 1, 2), (3, 4, 5)])
        intersections_result, intersections = invoke(worker, root,
                                  "mesh.analysis.self_intersections", crossing,
                                  case="self-crossing")
        assert intersections["results"]["does_self_intersect"] is True
        assert intersections["results"]["intersection_pair_count"] == 1
        validate(worker, root, "mesh.analysis.self_intersections",
                 intersections_result, crossing,
                 case="validate-self-crossing")

        invalid = root / "invalid-graph.off"
        write_off(invalid, [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0)],
                  [(0, 1, 2), (0, 1, 3)])
        _, invalid_report = invoke(worker, root, "mesh.inspect.pmp", invalid,
                                   case="inspect-invalid")
        assert invalid_report["mesh_summary"]["surface_mesh_constructible"] is False
        error_out = root / "out-invalid-components"
        error_out.mkdir()
        assert_error(worker, request("mesh.analysis.connected_components", invalid,
                                     error_out, request_id="invalid-components"),
                     "MESH_GRAPH_NOT_CONSTRUCTIBLE", "PRECONDITION_FAILED")

        nonmanifold = root / "nonmanifold-vertex.off"
        write_off(nonmanifold,
                  [(0, 0, 0), (1, 0, 0), (0, 1, 0),
                   (-1, 0, 0), (0, -1, 0)],
                  [(0, 1, 2), (0, 3, 4)])
        _, nonmanifold_inspection = invoke(worker, root, "mesh.inspect.pmp",
                                           nonmanifold,
                                           case="inspect-nonmanifold")
        assert nonmanifold_inspection["results"][
            "non_manifold_vertex_count"] == 1

        degenerate = root / "degenerate.off"
        write_off(degenerate, [(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1, 2)])
        _, degenerate_inspect = invoke(worker, root, "mesh.inspect.pmp",
                                      degenerate, case="inspect-degenerate")
        assert degenerate_inspect["results"]["degenerate_face_count"] == 1
        _, degenerate_normals = invoke(worker, root, "mesh.analysis.normals",
                                       degenerate, case="normals-degenerate")
        assert degenerate_normals["results"]["degenerate_face_count"] == 1
        assert degenerate_normals["results"]["zero_face_normal_count"] == 1
        _, degenerate_sharp = invoke(worker, root,
                                     "mesh.analysis.sharp_features", degenerate,
                                     parameters={"angle": {"value": 45,
                                                           "unit": "deg"}},
                                     case="sharp-degenerate")
        assert degenerate_sharp["results"]["features"]["available"] is False
        _, degenerate_si = invoke(worker, root,
                                  "mesh.analysis.self_intersections", degenerate,
                                  case="si-degenerate")
        assert degenerate_si["results"]["reason"] == "DEGENERATE_FACES"

        tiny = root / "tiny.off"
        tiny_points, tiny_faces = tetra(scale=1e-200)
        write_off(tiny, tiny_points, tiny_faces)
        _, tiny_measure = invoke(worker, root, "mesh.analysis.measures", tiny,
                                 case="measures-tiny")
        assert tiny_measure["results"]["surface_area"]["available"] is False
        assert tiny_measure["results"]["signed_volume"]["available"] is False
        _, tiny_normals = invoke(worker, root, "mesh.analysis.normals", tiny,
                                 case="normals-tiny")
        assert all(item["normal"]["is_unit"] for item in
                   tiny_normals["results"]["face_normals"])

        huge = root / "huge.off"
        huge_points, huge_faces = tetra(scale=1e200)
        write_off(huge, huge_points, huge_faces)
        _, huge_measure = invoke(worker, root, "mesh.analysis.measures", huge,
                                 case="measures-huge")
        assert huge_measure["results"]["surface_area"]["available"] is False
        assert huge_measure["results"]["signed_volume"]["available"] is False
        _, huge_normals = invoke(worker, root, "mesh.analysis.normals", huge,
                                 case="normals-huge")
        assert all(item["normal"]["is_unit"] for item in
                   huge_normals["results"]["face_normals"])

        translated = root / "translated.off"
        translated_points, translated_faces = tetra(scale=1e90, offset=1e100)
        write_off(translated, translated_points, translated_faces)
        _, translated_measure = invoke(worker, root, "mesh.analysis.measures",
                                       translated, case="measures-translated")
        assert translated_measure["results"]["surface_area"]["available"] is True
        assert translated_measure["results"]["signed_volume"]["available"] is True
        _, translated_normals = invoke(worker, root, "mesh.analysis.normals",
                                       translated, case="normals-translated")
        assert all(item["normal"]["is_unit"] for item in
                   translated_normals["results"]["face_normals"])

        tampered_path = root / "tampered-normals.json"
        original_normals = json.loads(pathlib.Path(
            normals_result["outputs"][0]["path"]).read_text(encoding="utf-8"))
        tampered = json.loads(json.dumps(original_normals))
        tampered["results"]["face_normals"][0]["normal"]["value"] = [1, 0, 0]
        tampered_path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
        tampered_out = root / "out-validate-tampered"
        tampered_out.mkdir()
        tampered_request = {
            "protocol": 1, "request_id": "validate-tampered",
            "operation": "mesh.validate.normals_report",
            "inputs": [
                {"artifact_id": "tampered", "type": "GeometryAnalysisReport",
                 "unit": "none", "format": "json",
                 "path": str(tampered_path.resolve()),
                 "sha256": sha256(tampered_path)},
                artifact(tetra_path),
            ],
            "parameters": {}, "output_dir": str(tampered_out.resolve()),
            "kernel": "package_recommended",
            "limits": {"wall_time_ms": 120_000, "memory_mb": 2048},
        }
        assert_error(worker, tampered_request, "REPORT_SEMANTICS_MISMATCH",
                     "VALIDATION_FAILED")

        def reject_report(value: dict, name: str, code: str) -> None:
            report_path = root / f"{name}.json"
            report_path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            output = root / f"out-{name}"
            output.mkdir()
            check = json.loads(json.dumps(tampered_request))
            check["request_id"] = name
            check["output_dir"] = str(output.resolve())
            check["inputs"][0] = {
                "artifact_id": name, "type": "GeometryAnalysisReport",
                "unit": "none", "format": "json",
                "path": str(report_path.resolve()), "sha256": sha256(report_path)}
            assert_error(worker, check, code, "VALIDATION_FAILED")

        missing_validation = json.loads(json.dumps(original_normals))
        del missing_validation["validation"]
        reject_report(missing_validation, "missing-producer-validation",
                      "REPORT_SCHEMA_MISMATCH")

        altered_validation = json.loads(json.dumps(original_normals))
        altered_validation["validation"].update(
            {"validator_id": "attacker", "authoritative": True,
             "passed": False})
        reject_report(altered_validation, "altered-producer-validation",
                      "REPORT_PRODUCER_DIAGNOSTIC_MISMATCH")

        extra_claim = json.loads(json.dumps(original_normals))
        extra_claim["untrusted_claim"] = True
        reject_report(extra_claim, "extra-top-level-claim",
                      "REPORT_SCHEMA_MISMATCH")

        sparse_results = json.loads(json.dumps(original_normals))
        del sparse_results["results"]["face_normals"]
        reject_report(sparse_results, "sparse-normal-results",
                      "REPORT_DIMENSION_MISMATCH")

        wide_schema_version = json.loads(json.dumps(original_normals))
        wide_schema_version["schema_version"] = 2**64 - 1
        reject_report(wide_schema_version, "wide-schema-version",
                      "REPORT_SCHEMA_MISMATCH")

        oversized = root / "oversized-report.json"
        oversized.write_bytes(b" " * (16 * 1024 * 1024 + 1))
        oversized_out = root / "out-validate-oversized"
        oversized_out.mkdir()
        oversized_request = dict(tampered_request)
        oversized_request["request_id"] = "validate-oversized"
        oversized_request["output_dir"] = str(oversized_out.resolve())
        oversized_request["inputs"] = [
            {"artifact_id": "oversized", "type": "GeometryAnalysisReport",
             "unit": "none", "format": "json",
             "path": str(oversized.resolve()), "sha256": sha256(oversized)},
            artifact(tetra_path),
        ]
        assert_error(worker, oversized_request, "REPORT_SIZE_LIMIT_EXCEEDED",
                     "RESOURCE_LIMIT")

        polygon = root / "polygon.off"
        write_off(polygon, [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                  [(0, 1, 2, 3)])
        _, polygon_inspection = invoke(worker, root, "mesh.inspect.pmp", polygon,
                                       case="inspect-polygon")
        assert polygon_inspection["mesh_summary"]["triangulated"] is False
        polygon_out = root / "out-polygon-components"
        polygon_out.mkdir()
        assert_error(worker, request("mesh.analysis.connected_components",
                                     polygon, polygon_out,
                                     request_id="polygon-components"),
                     "MESH_NOT_TRIANGULATED", "PRECONDITION_FAILED")

        soup_result, soup_inspection = invoke(
            worker, root, "mesh.inspect.pmp", polygon,
            case="inspect-polygon-soup", source_type="PolygonSoup3")
        assert soup_inspection["source"]["type"] == "PolygonSoup3"
        assert soup_inspection["mesh_summary"]["triangulated"] is False
        validate(worker, root, "mesh.inspect.pmp", soup_result, polygon,
                 case="validate-inspect-polygon-soup",
                 source_type="PolygonSoup3")
        soup_components_out = root / "out-soup-components"
        soup_components_out.mkdir()
        assert_error(worker, request(
            "mesh.analysis.connected_components", polygon,
            soup_components_out, request_id="soup-components",
            source_type="PolygonSoup3"),
            "INPUT_TYPE_OR_FORMAT_MISMATCH", "INVALID_INPUT")

        nonfinite = root / "nonfinite.off"
        nonfinite.write_text("OFF\n3 1 0\nnan 0 0\n1 0 0\n0 1 0\n3 0 1 2\n",
                             encoding="ascii")
        _, nonfinite_inspection = invoke(worker, root, "mesh.inspect.pmp",
                                         nonfinite, case="inspect-nonfinite")
        assert nonfinite_inspection["mesh_summary"]["finite_coordinates"] is False
        assert "NONFINITE_COORDINATE" in \
            nonfinite_inspection["results"]["parse_issues"]

        assert sha256(tetra_path) == tetra_digest  # analysis is immutable

        bad_angle_out = root / "out-bad-angle"
        bad_angle_out.mkdir()
        assert_error(worker, request("mesh.analysis.sharp_features", tetra_path,
                                     bad_angle_out,
                                     {"angle": {"value": 1, "unit": "grad"}},
                                     request_id="bad-angle"),
                     "INVALID_TYPED_ANGLE", "INVALID_INPUT")
        bad_kernel_out = root / "out-bad-kernel"
        bad_kernel_out.mkdir()
        bad_kernel = request("mesh.inspect.pmp", tetra_path, bad_kernel_out,
                             request_id="bad-kernel")
        bad_kernel["kernel"] = "fast_inexact"
        assert_error(worker, bad_kernel, "UNSUPPORTED_KERNEL",
                     "UNSUPPORTED")
        bad_digest_out = root / "out-bad-digest"
        bad_digest_out.mkdir()
        bad_digest = request("mesh.inspect.pmp", tetra_path, bad_digest_out,
                             request_id="bad-digest")
        bad_digest["inputs"][0]["sha256"] = "0" * 64
        assert_error(worker, bad_digest, "DIGEST_MISMATCH", "INVALID_INPUT")
        bad_type_out = root / "out-bad-type"
        bad_type_out.mkdir()
        bad_type = request("mesh.inspect.pmp", tetra_path, bad_type_out,
                           request_id="bad-type")
        bad_type["inputs"][0]["type"] = "PointSet3"
        assert_error(worker, bad_type, "INPUT_TYPE_OR_FORMAT_MISMATCH",
                     "INVALID_INPUT")
        unknown_out = root / "out-unknown"
        unknown_out.mkdir()
        assert_error(worker, request("mesh.analysis.unknown", tetra_path,
                                     unknown_out, request_id="unknown"),
                     "UNKNOWN_OPERATION", "UNSUPPORTED")
        malformed = run(worker, {"request_id": "malformed", "protocol": 1})
        assert malformed["status"] == "error"

    print("master Wave A mesh cases: PASS")


if __name__ == "__main__":
    main()
