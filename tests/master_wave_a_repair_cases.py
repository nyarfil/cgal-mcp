"""Direct acceptance suite for the isolated CGAL 6.2.1 mesh-repair harness."""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import math
import subprocess
import sys
import tempfile
import time


FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "master" / "wave_a_repair"
CASES = {
    "mesh.repair.orient": ("mesh.validate.repair_orientation", "tetra_flipped_soup.off", "PolygonSoup3", {}),
    "mesh.repair.stitch_borders": ("mesh.validate.repair_stitch_borders", "duplicated_seam.off", "TriangleSurfaceMesh", {}),
    "mesh.repair.remove_degenerate": ("mesh.validate.repair_remove_degenerate", "degenerate_face.off", "PolygonSoup3", {}),
    "mesh.repair.fill_holes": ("mesh.validate.repair_fill_holes", "open_tetra_hole.off", "TriangleSurfaceMesh", {"max_hole_edges": 3}),
    "mesh.repair.polygon_soup": ("mesh.validate.repair_polygon_soup", "dirty_polygon_soup.off", "PolygonSoup3", {"duplicate_polygon_policy": "keep_one", "require_same_orientation": False}),
    "mesh.repair.manifold_preprocess": ("mesh.validate.repair_manifold_preprocess", "nonmanifold_vertex.off", "TriangleSurfaceMesh", {}),
}


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: pathlib.Path, kind: str, unit: str = "mm") -> dict:
    return {"artifact_id": path.stem, "type": kind, "unit": unit,
            "format": "off", "path": str(path.resolve()), "sha256": digest(path)}


def request(operation: str, inputs: list[dict], parameters: dict,
            output_dir: pathlib.Path, case: str,
            kernel: str = "package_recommended") -> dict:
    return {"protocol": 1, "request_id": case, "operation": operation,
            "inputs": inputs, "parameters": parameters,
            "output_dir": str(output_dir.resolve()), "kernel": kernel,
            "limits": {"wall_time_ms": 120_000, "memory_mb": 2048}}


def run(worker: str, value: dict) -> dict:
    process = subprocess.run([worker], input=json.dumps(value) + "\n", text=True,
                             encoding="utf-8", capture_output=True, timeout=120)
    assert process.returncode == 0, (process.returncode, process.stderr)
    assert process.stderr == "", process.stderr
    lines = process.stdout.splitlines()
    assert len(lines) == 1, process.stdout
    result = json.loads(lines[0])
    assert result["protocol"] == 1 and result["request_id"] == value["request_id"]
    return result


def assert_error(worker: str, value: dict, code: str,
                 error_class: str | None = None) -> dict:
    result = run(worker, value)
    assert result["status"] == "error", result
    assert result["error"]["code"] == code, result
    if error_class:
        assert result["error"]["class"] == error_class, result
    assert result.get("outputs", []) == []
    return result


def copy_fixture(root: pathlib.Path, name: str) -> pathlib.Path:
    destination = root / name
    shutil.copyfile(FIXTURES / name, destination)
    return destination


def invoke(worker: str, root: pathlib.Path, operation: str, source: pathlib.Path,
           source_type: str, parameters: dict, *, case: str,
           unit: str = "mm") -> tuple[dict, pathlib.Path]:
    output = root / (case + "-output")
    output.mkdir()
    value = request(operation, [artifact(source, source_type, unit)], parameters,
                    output, case)
    result = run(worker, value)
    assert result["status"] == "ok", result
    assert len(result["outputs"]) == 1
    entry = result["outputs"][0]
    expected_type = "PolygonSoup3" if operation == "mesh.repair.polygon_soup" else "TriangleSurfaceMesh"
    assert entry["slot"] == "geometry" and entry["type"] == expected_type
    assert entry["unit"] == unit and entry["format"] == "off"
    path = pathlib.Path(entry["path"])
    assert path.resolve().is_relative_to(output.resolve()) and path.is_file()
    assert digest(source) == value["inputs"][0]["sha256"]
    return result, path


def validate(worker: str, root: pathlib.Path, validator: str,
             candidate: pathlib.Path, candidate_type: str,
             source: pathlib.Path, source_type: str, parameters: dict,
             *, case: str, unit: str = "mm") -> dict:
    output = root / (case + "-output")
    output.mkdir()
    value = request(
        validator,
        [artifact(candidate, candidate_type, unit), artifact(source, source_type, unit)],
        parameters, output, case)
    result = run(worker, value)
    assert result["status"] == "ok", result
    entry = result["outputs"][0]
    assert entry["slot"] == "validation" and entry["type"] == "ValidationReport"
    report = json.loads(pathlib.Path(entry["path"]).read_text(encoding="utf-8"))
    required = {"source_identity_matches", "candidate_matches_official_cgal_replay",
                "candidate_unit_matches_source", "repair_invariant_valid",
                "numeric_profile_valid", "source_geometry_preserved_as_required"}
    assert report["schema_version"] == 1 and report["status"] == "pass"
    assert report["passed"] is True and report["validator_id"] == validator
    assert report["parameters"] == parameters
    assert required == report["checks"].keys()
    assert all(report["checks"].values())
    return report


def write_off(path: pathlib.Path, points: list[tuple[float, float, float]],
              faces: list[tuple[int, int, int]]) -> None:
    lines = ["OFF", f"{len(points)} {len(faces)} 0"]
    lines += [f"{x:.17g} {y:.17g} {z:.17g}" for x, y, z in points]
    lines += ["3 " + " ".join(map(str, face)) for face in faces]
    path.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: master_wave_a_repair_cases.py WORKER")
    worker = str(pathlib.Path(sys.argv[1]).resolve())
    manifest_run = subprocess.run([worker, "--manifest"], text=True,
                                  encoding="utf-8", capture_output=True, timeout=30)
    assert manifest_run.returncode == 0 and manifest_run.stderr == ""
    manifest = json.loads(manifest_run.stdout)
    assert manifest["actual_cgal_version"] == "6.2.1"
    assert manifest["build"]["source_kind"] == "official_release"
    expected_ids = set(CASES) | {value[0] for value in CASES.values()}
    assert len(expected_ids) == 12, sorted(expected_ids)
    declared = {item["id"]: item for item in manifest["operations"]}
    assert expected_ids <= declared.keys(), (
        "worker lacks repair operations (stale binary?): %s" % sorted(expected_ids - declared.keys()))
    operations = {key: declared[key] for key in sorted(expected_ids)}
    for item in operations.values():
        assert item["revision"] == 1
        assert item["supported_kernels"] == ["package_recommended"]
        assert item["effective_kernel"] == "CGAL::Exact_predicates_inexact_constructions_kernel"
        assert item["info"]["license_evidence"]["sha256"] == \
            "efb290ee3ef3d8b7675896bc037f1c9359f583543ca9e38bcb425fe34a8995db"

    with tempfile.TemporaryDirectory(prefix="cgal-repair-") as directory:
        root = pathlib.Path(directory)
        results: dict[str, tuple[pathlib.Path, pathlib.Path, str, dict]] = {}
        for index, (operation, (validator, fixture, source_type, parameters)) in enumerate(CASES.items()):
            source = root / f"{index}-{fixture}"
            source.write_bytes((FIXTURES / fixture).read_bytes())
            unit = ("mm", "cm", "m")[index % 3]
            transform, candidate = invoke(worker, root, operation, source, source_type,
                                          parameters, case=f"repair-{index}", unit=unit)
            candidate_type = transform["outputs"][0]["type"]
            validate(worker, root, validator, candidate, candidate_type, source,
                     source_type, parameters, case=f"validate-{index}", unit=unit)
            results[operation] = (source, candidate, source_type, parameters)

        assert results["mesh.repair.orient"][0].read_bytes() != results["mesh.repair.orient"][1].read_bytes()
        assert results["mesh.repair.stitch_borders"][0].read_bytes() != results["mesh.repair.stitch_borders"][1].read_bytes()

        # Candidate tamper must fail official replay and never produce validation output.
        source, candidate, source_type, parameters = results["mesh.repair.fill_holes"]
        tampered = root / "tampered-hole.off"
        text = candidate.read_text(encoding="ascii")
        tampered.write_text(text.replace("0 0 0", "0.125 0 0", 1), encoding="ascii", newline="\n")
        output = root / "tamper-output"; output.mkdir()
        value = request(CASES["mesh.repair.fill_holes"][0],
                        [artifact(tampered, "TriangleSurfaceMesh"), artifact(source, source_type)],
                        parameters, output, "tamper")
        assert_error(worker, value, "REPAIR_VALIDATION_FAILED", "VALIDATION_FAILED")

        # Exact-construction requests are rejected at the operation boundary.
        source = copy_fixture(root, "tetra_outward.off")
        output = root / "kernel-output"; output.mkdir()
        value = request("mesh.repair.stitch_borders",
                        [artifact(source, "TriangleSurfaceMesh")], {}, output,
                        "bad-kernel", kernel="exact_constructions")
        assert_error(worker, value, "OUTPUT_PRECISION_PROFILE_UNSUPPORTED", "UNSUPPORTED_ADAPTER")

        # Digest and malformed index checks are fail-closed.
        output = root / "digest-output"; output.mkdir()
        bad = artifact(source, "TriangleSurfaceMesh"); bad["sha256"] = "0" * 64
        assert_error(worker, request("mesh.repair.stitch_borders", [bad], {}, output,
                                     "bad-digest"), "DIGEST_MISMATCH", "INVALID_INPUT")
        invalid = copy_fixture(root, "invalid_index.off")
        output = root / "invalid-output"; output.mkdir()
        assert_error(worker, request("mesh.repair.orient",
                                     [artifact(invalid, "PolygonSoup3")], {}, output,
                                     "invalid-index"), "OFF_INDEX_OUT_OF_RANGE", "INVALID_INPUT")

        # Numeric scale/translation bounds are enforced before CGAL dispatch.
        extreme = root / "extreme.off"
        write_off(extreme, [(1e50, 0, 0), (1e50, 1, 0), (1e50, 0, 1)], [(0, 1, 2)])
        output = root / "scale-output"; output.mkdir()
        assert_error(worker, request("mesh.repair.orient",
                                     [artifact(extreme, "PolygonSoup3")], {}, output,
                                     "bad-scale"), "UNSUPPORTED_NUMERIC_SCALE", "PRECONDITION_FAILED")

        # Parameter bindings are strict and the triangular hole limit is deterministic.
        source = copy_fixture(root, "open_tetra_hole.off")
        output = root / "parameter-output"; output.mkdir()
        assert_error(worker, request("mesh.repair.fill_holes",
                                     [artifact(source, "TriangleSurfaceMesh")],
                                     {"max_hole_edges": 2}, output, "bad-limit"),
                     "INVALID_MAX_HOLE_EDGES", "INVALID_INPUT")

        # Regression: repeated-index-only polygons must fail fast instead of
        # hanging inside orient_polygon_soup.
        repeated = root / "repeated-index.off"
        write_off(repeated, [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, 1)])
        output = root / "repeated-output"; output.mkdir()
        started = time.monotonic()
        assert_error(worker, request("mesh.repair.orient",
                                     [artifact(repeated, "PolygonSoup3")], {}, output,
                                     "repeated-index"),
                     "COMBINATORIALLY_DEGENERATE_FACE", "PRECONDITION_FAILED")
        assert time.monotonic() - started < 10

        # Regression: hole triangulation must stay bounded for a large non-planar
        # hole (the cubic fallback is disabled); success or a typed failure only.
        count = 600
        rim = [(math.cos(2 * math.pi * i / count), math.sin(2 * math.pi * i / count),
                0.4 * math.sin(7 * 2 * math.pi * i / count)) for i in range(count)]
        big = root / "big-hole.off"
        write_off(big, [(0.0, 0.0, 1.0)] + rim,
                  [(0, 1 + i, 1 + (i + 1) % count) for i in range(count)])
        output = root / "big-hole-output"; output.mkdir()
        started = time.monotonic()
        result = run(worker, request("mesh.repair.fill_holes",
                                     [artifact(big, "TriangleSurfaceMesh")],
                                     {"max_hole_edges": count}, output, "big-hole"))
        assert time.monotonic() - started < 30
        assert result["status"] == "ok" or result["error"]["code"] == "HOLE_TRIANGULATION_FAILED", result

        # Larger holes than the schema bound are rejected before CGAL dispatch.
        output = root / "huge-hole-output"; output.mkdir()
        assert_error(worker, request("mesh.repair.fill_holes",
                                     [artifact(big, "TriangleSurfaceMesh")],
                                     {"max_hole_edges": 4000}, output, "huge-hole"),
                     "INVALID_MAX_HOLE_EDGES", "INVALID_INPUT")

        # Regression: validators accept correct CGAL output that is not a subset
        # of source triangles (edge flips) or keeps collinear/opposite duplicates.
        flat = root / "flat-cap.off"
        write_off(flat, [(0, 0, 0), (1, 0, 0), (2, 0, 0), (1, 1, 1)],
                  [(0, 1, 2), (0, 3, 1), (1, 3, 2), (0, 2, 3)])
        output = root / "flat-output"; output.mkdir()
        flat_result = run(worker, request("mesh.repair.remove_degenerate",
                                          [artifact(flat, "PolygonSoup3")], {}, output, "flat-cap"))
        if flat_result["status"] == "ok":
            candidate = pathlib.Path(flat_result["outputs"][0]["path"])
            validate(worker, root, "mesh.validate.repair_remove_degenerate", candidate,
                     "TriangleSurfaceMesh", flat, "PolygonSoup3", {}, case="flat-validate")
        else:
            assert flat_result["error"]["code"] in {"REPAIR_WOULD_EMPTY_MESH", "DEGENERATE_REPAIR_INCOMPLETE"}, flat_result
        mixed = root / "mixed-duplicates.off"
        write_off(mixed, [(0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 0, 0), (3, 0, 0)],
                  [(0, 1, 2), (0, 2, 1), (0, 1, 2), (1, 3, 4)])
        parameters = {"duplicate_polygon_policy": "keep_one", "require_same_orientation": True}
        mixed_result, mixed_candidate = invoke(worker, root, "mesh.repair.polygon_soup", mixed,
                                               "PolygonSoup3", parameters, case="mixed")
        validate(worker, root, "mesh.validate.repair_polygon_soup", mixed_candidate,
                 "PolygonSoup3", mixed, "PolygonSoup3", parameters, case="mixed-validate")

    print("Wave A repair: 6 transforms, 6 dedicated replay validators, defects, tamper, units, kernels, numeric bounds: PASS")


if __name__ == "__main__":
    main()
