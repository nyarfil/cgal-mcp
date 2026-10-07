"""Real CGAL 6.2.1 Wave B production-worker cases."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "master" / "wave_b"
WORKER = sys.argv[1]


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: pathlib.Path, type_: str, format_: str, id_: str, unit: str = "mm") -> dict:
    return {
        "artifact_id": id_, "type": type_, "unit": unit, "format": format_,
        "path": str(path.resolve()), "sha256": sha256(path),
    }


def invoke(operation: str, inputs: list[dict], output: pathlib.Path, parameters: dict,
           request_id: str, kernel: str = "package_recommended") -> dict:
    output.mkdir()
    request = {
        "protocol": 1, "request_id": request_id, "operation": operation,
        "inputs": inputs, "parameters": parameters, "output_dir": str(output.resolve()),
        "kernel": kernel, "limits": {"wall_time_ms": 120000, "memory_mb": 2048},
    }
    process = subprocess.run([WORKER], input=json.dumps(request) + "\n", text=True,
                             encoding="utf-8", capture_output=True, timeout=120)
    assert process.returncode == 0, process.stderr
    assert process.stderr == "", process.stderr
    lines = process.stdout.splitlines()
    assert len(lines) == 1, process.stdout
    result = json.loads(lines[0])
    assert result["request_id"] == request_id, result
    return result


def result_path(result: dict) -> pathlib.Path:
    assert result["status"] == "ok", result
    value = pathlib.Path(result["outputs"][0]["path"])
    assert value.is_file(), result
    return value


def expect_error(*args, code: str, error_class: str | None = None, **kwargs) -> None:
    result = invoke(*args, **kwargs)
    assert result["status"] == "error", result
    assert result["error"]["code"] == code, result
    if error_class is not None:
        assert result["error"]["class"] == error_class, result


def write_xyz(path: pathlib.Path, points: list[tuple[float, float, float]]) -> None:
    path.write_text(
        "".join(f"{x:.17g} {y:.17g} {z:.17g}\n" for x, y, z in points),
        encoding="ascii",
    )


def replace_first_ply_vertex(
    source: pathlib.Path,
    destination: pathlib.Path,
    transform,
) -> None:
    lines = source.read_text(encoding="ascii").splitlines()
    first = lines.index("end_header") + 1
    values = [float(value) for value in lines[first].split()]
    lines[first] = " ".join(f"{value:.17g}" for value in transform(values))
    destination.write_text("\n".join(lines) + "\n", encoding="ascii")


def transform_ply_vertices(
    source: pathlib.Path,
    destination: pathlib.Path,
    transform,
) -> None:
    lines = source.read_text(encoding="ascii").splitlines()
    first = lines.index("end_header") + 1
    for index in range(first, len(lines)):
        values = [float(value) for value in lines[index].split()]
        lines[index] = " ".join(f"{value:.17g}" for value in transform(values))
    destination.write_text("\n".join(lines) + "\n", encoding="ascii")


def read_ply_normals(path: pathlib.Path) -> list[tuple[float, float, float]]:
    lines = path.read_text(encoding="ascii").splitlines()
    first = lines.index("end_header") + 1
    return [tuple(float(value) for value in line.split()[3:6]) for line in lines[first:]]


manifest_process = subprocess.run(
    [WORKER, "--manifest"], text=True, encoding="utf-8", capture_output=True, timeout=30
)
assert manifest_process.returncode == 0, manifest_process.stderr
assert manifest_process.stderr == "", manifest_process.stderr
manifest = json.loads(manifest_process.stdout)
manifest_operations = {operation["id"]: operation for operation in manifest["operations"]}
expected_operations = {
    "pointset.remove_outliers",
    "pointset.simplify.grid",
    "pointset.simplify.random",
    "pointset.simplify.hierarchy",
    "pointset.smooth.jet",
    "pointset.normals.estimate",
    "pointset.normals.orient_mst",
    "pointset.validate.basic",
    "pointset.validate.subset",
    "pointset.validate.smoothed",
    "pointset.validate.normals_estimated",
    "pointset.validate.normals_oriented",
}
assert expected_operations <= manifest_operations.keys(), manifest_operations.keys()
for operation_id in expected_operations:
    operation = manifest_operations[operation_id]
    assert operation["revision"] == 1, operation
    assert operation["supported_kernels"] == ["package_recommended"], operation
    assert operation["effective_kernel"] == "CGAL::Exact_predicates_inexact_constructions_kernel", operation
    assert operation["dependencies"] == ["Point_set_processing_3", "Eigen3"], operation

expected_bindings = {
    "pointset.remove_outliers": {
        "pointset.validate.subset": {
            "neighbors": "neighbors", "threshold_percent": "threshold_percent",
            "threshold_distance": "threshold_distance",
        }
    },
    "pointset.simplify.grid": {
        "pointset.validate.subset": {
            "cell_size": "cell_size", "min_points_per_cell": "min_points_per_cell",
        }
    },
    "pointset.simplify.random": {
        "pointset.validate.subset": {
            "removed_percentage": "removed_percentage", "seed": "seed",
        }
    },
    "pointset.simplify.hierarchy": {
        "pointset.validate.subset": {
            "cluster_size": "cluster_size", "maximum_variation": "maximum_variation",
        }
    },
    "pointset.smooth.jet": {
        "pointset.validate.smoothed": {
            "neighbors": "neighbors", "degree_fitting": "degree_fitting",
            "degree_monge": "degree_monge",
        }
    },
    "pointset.normals.estimate": {
        "pointset.validate.normals_estimated": {
            "method": "method", "neighbors": "neighbors",
            "degree_fitting": "degree_fitting",
        }
    },
    "pointset.normals.orient_mst": {
        "pointset.validate.normals_oriented": {
            "neighbors": "neighbors", "drop_unoriented": "drop_unoriented",
        }
    },
}
for operation_id, bindings in expected_bindings.items():
    assert manifest_operations[operation_id]["info"]["validator_parameter_bindings"] == bindings
assert "normal_vectors_unit" in manifest_operations["pointset.validate.basic"]["info"]["checks"]
assert "cgal_reference_match" in manifest_operations["pointset.validate.subset"]["info"]["checks"]


with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    source = FIXTURES / "noisy_plane_with_outlier.xyz"
    source_digest = sha256(source)
    points = artifact(source, "PointSet3", "xyz", "source")

    # Mandatory PointSet validator accepts finite rank-2 input and writes a report.
    validation = invoke("pointset.validate.basic", [points], root / "validate-source", {}, "validate-source")
    assert validation["status"] == "ok", validation
    assert validation["metrics"]["affine_rank"] == 3, validation
    assert validation["metrics"]["normal_vectors_unit"] is None, validation

    outliers = invoke("pointset.remove_outliers", [points], root / "outliers", {
        "neighbors": 8, "threshold_percent": 10.0,
        "threshold_distance": {"value": 3.0, "unit": "mm"},
    }, "outliers")
    outlier_path = result_path(outliers)
    assert outliers["metrics"]["removed_point_count"] >= 1, outliers
    assert outliers["metrics"]["output_point_count"] < outliers["metrics"]["input_point_count"], outliers
    outlier_contract = invoke(
        "pointset.validate.subset",
        [artifact(outlier_path, "PointSet3", "xyz", "outlier-candidate"), points],
        root / "validate-outlier-contract", {
            "neighbors": 8, "threshold_percent": 10.0,
            "threshold_distance": {"value": 3.0, "unit": "mm"},
        }, "validate-outlier-contract",
    )
    assert outlier_contract["metrics"]["candidate_is_source_multiset_subset"] is True

    grid = invoke("pointset.simplify.grid", [points], root / "grid", {
        "cell_size": {"value": 1.5, "unit": "mm"}, "min_points_per_cell": 1,
    }, "grid")
    assert grid["metrics"]["output_point_count"] < 26, grid
    grid_path = result_path(grid)
    grid_contract = invoke(
        "pointset.validate.subset",
        [artifact(grid_path, "PointSet3", "xyz", "grid-candidate"), points],
        root / "validate-grid-contract", {
            "cell_size": {"value": 1.5, "unit": "mm"},
            "min_points_per_cell": 1,
        }, "validate-grid-contract",
    )
    assert grid_contract["metrics"]["point_count_not_increased"] is True
    centimeter_grid = invoke("pointset.simplify.grid", [artifact(source, "PointSet3", "xyz", "source-cm", "cm")], root / "grid-cm", {
        "cell_size": {"value": 15.0, "unit": "mm"}, "min_points_per_cell": 1,
    }, "grid-cm")
    assert centimeter_grid["metrics"]["cell_size"] == {"value": 1.5, "unit": "cm"}, centimeter_grid
    assert centimeter_grid["outputs"][0]["unit"] == "cm", centimeter_grid

    random_one = invoke("pointset.simplify.random", [points], root / "random-one", {
        "removed_percentage": 50.0, "seed": 12345,
    }, "random-one")
    random_two = invoke("pointset.simplify.random", [points], root / "random-two", {
        "removed_percentage": 50.0, "seed": 12345,
    }, "random-two")
    assert sha256(result_path(random_one)) == sha256(result_path(random_two)), (random_one, random_two)
    random_one_path = result_path(random_one)
    assert random_one["metrics"]["deterministic"] is True, random_one
    random_three = invoke("pointset.simplify.random", [points], root / "random-three", {
        "removed_percentage": 50.0, "seed": 99999,
    }, "random-three")
    assert sha256(result_path(random_one)) != sha256(result_path(random_three)), (random_one, random_three)
    random_contract = invoke(
        "pointset.validate.subset",
        [artifact(random_one_path, "PointSet3", "xyz", "random-candidate"), points],
        root / "validate-random-contract", {
            "removed_percentage": 50.0, "seed": 12345,
        },
        "validate-random-contract",
    )
    assert random_contract["metrics"]["candidate_is_source_multiset_subset"] is True
    assert random_contract["metrics"]["random_sample_count_matches"] is True

    hierarchy = invoke("pointset.simplify.hierarchy", [points], root / "hierarchy", {
        "cluster_size": 4, "maximum_variation": 0.2,
    }, "hierarchy")
    assert hierarchy["metrics"]["output_point_count"] <= 26, hierarchy
    hierarchy_path = result_path(hierarchy)
    hierarchy_contract = invoke(
        "pointset.validate.subset",
        [artifact(hierarchy_path, "PointSet3", "xyz", "hierarchy-candidate"), points],
        root / "validate-hierarchy-contract", {
            "cluster_size": 4, "maximum_variation": 0.2,
        }, "validate-hierarchy-contract",
    )
    assert hierarchy_contract["metrics"]["candidate_is_source_multiset_subset"] is True

    smoothed = invoke("pointset.smooth.jet", [points], root / "smooth", {
        "neighbors": 8, "degree_fitting": 2, "degree_monge": 2,
    }, "smooth")
    assert smoothed["metrics"]["coordinates_modified"] is True, smoothed
    smoothed_path = result_path(smoothed)
    assert sha256(smoothed_path) != source_digest, smoothed
    smooth_contract = invoke(
        "pointset.validate.smoothed",
        [artifact(smoothed_path, "PointSet3", "xyz", "smooth-candidate"), points],
        root / "validate-smooth-contract",
        {"neighbors": 8, "degree_fitting": 2, "degree_monge": 2},
        "validate-smooth-contract",
    )
    assert smooth_contract["metrics"]["point_count_preserved"] is True
    assert smooth_contract["metrics"]["cgal_reference_match"] is True

    # PCA and jet normal estimation produce ASCII PLY x/y/z/nx/ny/nz.
    pca = invoke("pointset.normals.estimate", [artifact(outlier_path, "PointSet3", "xyz", "outlier-clean")], root / "pca", {
        "method": "pca", "neighbors": 8,
    }, "pca")
    pca_path = result_path(pca)
    assert pca["outputs"][0]["type"] == "PointSet3Normals", pca
    assert pca_path.read_text(encoding="ascii").splitlines()[0:2] == ["ply", "format ascii 1.0"]
    pca_contract = invoke(
        "pointset.validate.normals_estimated",
        [artifact(pca_path, "PointSet3Normals", "ply", "pca-candidate"),
         artifact(outlier_path, "PointSet3", "xyz", "pca-source")],
        root / "validate-pca-contract", {"method": "pca", "neighbors": 8},
        "validate-pca-contract",
    )
    assert pca_contract["metrics"]["point_positions_preserved"] is True

    jet = invoke("pointset.normals.estimate", [artifact(outlier_path, "PointSet3", "xyz", "outlier-clean-jet")], root / "jet", {
        "method": "jet", "neighbors": 8, "degree_fitting": 2,
    }, "jet")
    jet_path = result_path(jet)
    jet_contract = invoke(
        "pointset.validate.normals_estimated",
        [artifact(jet_path, "PointSet3Normals", "ply", "jet-candidate"),
         artifact(outlier_path, "PointSet3", "xyz", "jet-source")],
        root / "validate-jet-contract",
        {"method": "jet", "neighbors": 8, "degree_fitting": 2},
        "validate-jet-contract",
    )
    assert jet_contract["metrics"]["point_positions_preserved"] is True

    normals_validation = invoke("pointset.validate.basic", [artifact(jet_path, "PointSet3Normals", "ply", "jet-normals")], root / "validate-normals", {}, "validate-normals")
    assert normals_validation["metrics"]["normal_vectors_nonzero"] is True, normals_validation
    assert normals_validation["metrics"]["normal_vectors_unit"] is True, normals_validation

    # MST works on a fixture with deliberately alternating valid normals.
    alternating = FIXTURES / "plane_normals_alternating.ply"
    oriented = invoke("pointset.normals.orient_mst", [artifact(alternating, "PointSet3Normals", "ply", "alternating")], root / "orient", {
        "neighbors": 4, "drop_unoriented": False,
    }, "orient")
    assert oriented["metrics"]["unoriented_point_count"] == 0, oriented
    oriented_path = result_path(oriented)
    orient_contract = invoke(
        "pointset.validate.normals_oriented",
        [artifact(oriented_path, "PointSet3Normals", "ply", "oriented-candidate"),
         artifact(alternating, "PointSet3Normals", "ply", "oriented-source")],
        root / "validate-orient-contract",
        {"neighbors": 4, "drop_unoriented": False},
        "validate-orient-contract",
    )
    assert orient_contract["metrics"]["positions_and_normals_preserved_up_to_sign"] is True

    # Every transform result has enough structure to pass the independent point-set validator.
    for index, path in enumerate((outlier_path, grid_path, random_one_path, hierarchy_path, smoothed_path)):
        check = invoke("pointset.validate.basic", [artifact(path, "PointSet3", "xyz", f"check-{index}")], root / f"check-{index}", {}, f"check-{index}")
        assert check["metrics"]["status"] == "pass", check
    for index, path in enumerate((pca_path, jet_path, oriented_path)):
        check = invoke("pointset.validate.basic", [artifact(path, "PointSet3Normals", "ply", f"normal-check-{index}")], root / f"normal-check-{index}", {}, f"normal-check-{index}")
        assert check["metrics"]["status"] == "pass", check

    # XYZ parsing matches the parent inspector's UTF-8 BOM and inline-comment
    # behavior.
    commented = root / "commented.xyz"
    commented.write_bytes(
        b"\xef\xbb\xbf0 0 0 # origin\n1 0 0\n0 1 0 # plane\n"
    )
    commented_check = invoke(
        "pointset.validate.basic",
        [artifact(commented, "PointSet3", "xyz", "commented")],
        root / "commented-check", {}, "commented-check",
    )
    assert commented_check["metrics"]["affine_rank"] == 2

    # Specific validators reject artifacts that a structure-only check would
    # accept.
    foreign = root / "foreign-subset.xyz"
    write_xyz(foreign, [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 99.0)])
    expect_error(
        "pointset.validate.subset",
        [artifact(foreign, "PointSet3", "xyz", "foreign-candidate"), points],
        root / "foreign-subset-check", {}, "foreign-subset-check",
        code="POINT_NOT_FROM_SOURCE", error_class="VALIDATION_FAILED",
    )
    expect_error(
        "pointset.validate.smoothed",
        [artifact(grid_path, "PointSet3", "xyz", "short-smooth-candidate"), points],
        root / "short-smooth-check",
        {"neighbors": 8, "degree_fitting": 2, "degree_monge": 2},
        "short-smooth-check",
        code="POINT_COUNT_CHANGED", error_class="VALIDATION_FAILED",
    )
    expect_error(
        "pointset.validate.smoothed",
        [points, points], root / "unchanged-smooth-check",
        {"neighbors": 8, "degree_fitting": 2, "degree_monge": 2},
        "unchanged-smooth-check", code="SMOOTHING_REFERENCE_MISMATCH",
        error_class="VALIDATION_FAILED",
    )
    expect_error(
        "pointset.validate.subset", [points, points],
        root / "random-noop-check", {"removed_percentage": 50.0, "seed": 12345},
        "random-noop-check", code="UNEXPECTED_RANDOM_SAMPLE_COUNT",
        error_class="VALIDATION_FAILED",
    )

    moved_pca = root / "moved-pca.ply"
    replace_first_ply_vertex(
        pca_path, moved_pca,
        lambda values: [values[0] + 0.25, *values[1:]],
    )
    expect_error(
        "pointset.validate.normals_estimated",
        [artifact(moved_pca, "PointSet3Normals", "ply", "moved-normal-candidate"),
         artifact(outlier_path, "PointSet3", "xyz", "moved-normal-source")],
        root / "moved-normal-check", {"method": "pca", "neighbors": 8},
        "moved-normal-check",
        code="POINT_POSITION_CHANGED", error_class="VALIDATION_FAILED",
    )

    tangent_pca = root / "tangent-pca.ply"
    transform_ply_vertices(
        pca_path, tangent_pca,
        lambda values: [*values[:3], 1.0, 0.0, 0.0],
    )
    expect_error(
        "pointset.validate.normals_estimated",
        [artifact(tangent_pca, "PointSet3Normals", "ply", "tangent-pca"),
         artifact(outlier_path, "PointSet3", "xyz", "tangent-source")],
        root / "tangent-normal-check", {"method": "pca", "neighbors": 8},
        "tangent-normal-check", code="ESTIMATED_NORMAL_REFERENCE_MISMATCH",
        error_class="VALIDATION_FAILED",
    )

    tiny_pca = root / "tiny-pca.ply"
    transform_ply_vertices(
        pca_path, tiny_pca,
        lambda values: [*values[:3], 5e-324, 0.0, 0.0],
    )
    expect_error(
        "pointset.validate.normals_estimated",
        [artifact(tiny_pca, "PointSet3Normals", "ply", "tiny-pca"),
         artifact(outlier_path, "PointSet3", "xyz", "tiny-source")],
        root / "tiny-normal-check", {"method": "pca", "neighbors": 8},
        "tiny-normal-check", code="NON_UNIT_NORMAL",
        error_class="VALIDATION_FAILED",
    )

    # A representable binary64 subnormal is valid numeric syntax on every
    # platform.  The dedicated geometry validator must reject its magnitude,
    # rather than a locale/runtime-dependent stod range exception rejecting PLY.
    for index, token in enumerate((
        "+4.9406564584124654e-324", "-4.9406564584124654e-324",
        "2.2250738585072014e-308",
    )):
        candidate = root / f"finite-small-normal-{index}.ply"
        lines = pca_path.read_text(encoding="ascii").splitlines()
        first = lines.index("end_header") + 1
        fields = lines[first].split()
        fields[3:] = [token, "0", "0"]
        lines[first] = " ".join(fields)
        candidate.write_text("\n".join(lines) + "\n", encoding="ascii")
        expect_error(
            "pointset.validate.normals_estimated",
            [artifact(candidate, "PointSet3Normals", "ply", f"small-normal-{index}"),
             artifact(outlier_path, "PointSet3", "xyz", f"small-source-{index}")],
            root / f"finite-small-normal-check-{index}", {"method": "pca", "neighbors": 8},
            f"finite-small-normal-check-{index}", code="NON_UNIT_NORMAL",
            error_class="VALIDATION_FAILED",
        )

    # Values outside binary64 and non-decimal tokens fail before calculation;
    # an underflowing token must not silently become a zero normal component.
    for index, token in enumerate(("1e-400", "1e400", "+-1", "0x1p0", "nan")):
        candidate = root / f"invalid-numeric-normal-{index}.ply"
        lines = pca_path.read_text(encoding="ascii").splitlines()
        first = lines.index("end_header") + 1
        fields = lines[first].split()
        fields[3] = token
        lines[first] = " ".join(fields)
        candidate.write_text("\n".join(lines) + "\n", encoding="ascii")
        expect_error(
            "pointset.validate.normals_estimated",
            [artifact(candidate, "PointSet3Normals", "ply", f"invalid-normal-{index}"),
             artifact(outlier_path, "PointSet3", "xyz", f"invalid-source-{index}")],
            root / f"invalid-numeric-normal-check-{index}", {"method": "pca", "neighbors": 8},
            f"invalid-numeric-normal-check-{index}", code="MALFORMED_PLY",
            error_class="INVALID_INPUT",
        )

    changed_oriented = root / "changed-oriented.ply"
    def change_normal_magnitude(values: list[float]) -> list[float]:
        for index in range(3, 6):
            if values[index] != 0:
                values[index] *= 2
                break
        return values
    replace_first_ply_vertex(oriented_path, changed_oriented, change_normal_magnitude)
    expect_error(
        "pointset.validate.normals_oriented",
        [artifact(changed_oriented, "PointSet3Normals", "ply", "changed-oriented-candidate"),
         artifact(alternating, "PointSet3Normals", "ply", "changed-oriented-source")],
        root / "changed-oriented-check",
        {"neighbors": 4, "drop_unoriented": False},
        "changed-oriented-check", code="NON_UNIT_NORMAL",
        error_class="VALIDATION_FAILED",
    )
    expect_error(
        "pointset.validate.normals_oriented",
        [artifact(alternating, "PointSet3Normals", "ply", "unchanged-oriented"),
         artifact(alternating, "PointSet3Normals", "ply", "unchanged-source")],
        root / "unchanged-oriented-check",
        {"neighbors": 4, "drop_unoriented": False},
        "unchanged-oriented-check", code="MST_ORIENTATION_REFERENCE_MISMATCH",
        error_class="VALIDATION_FAILED",
    )

    nonunit_normals = root / "nonunit-normals.ply"
    transform_ply_vertices(
        alternating, nonunit_normals,
        lambda values: [*values[:3], *(component * 2.0 for component in values[3:6])],
    )
    expect_error(
        "pointset.normals.orient_mst",
        [artifact(nonunit_normals, "PointSet3Normals", "ply", "nonunit-normals")],
        root / "nonunit-orient", {"neighbors": 4, "drop_unoriented": False},
        "nonunit-orient", code="NON_UNIT_NORMAL_INPUT",
        error_class="PRECONDITION_FAILED",
    )

    duplicate_neighborhood = root / "duplicate-neighborhood.xyz"
    write_xyz(
        duplicate_neighborhood,
        [(0.0, 0.0, 0.0)] * 20
        + [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
    )
    duplicate_points = artifact(
        duplicate_neighborhood, "PointSet3", "xyz", "duplicate-neighborhood"
    )
    expect_error(
        "pointset.smooth.jet", [duplicate_points], root / "duplicate-smooth",
        {"neighbors": 4, "degree_fitting": 2, "degree_monge": 2},
        "duplicate-smooth", code="LOCAL_NEIGHBORHOOD_RANK_LT_2",
        error_class="PRECONDITION_FAILED",
    )
    expect_error(
        "pointset.normals.estimate", [duplicate_points], root / "duplicate-estimate",
        {"method": "pca", "neighbors": 4}, "duplicate-estimate",
        code="LOCAL_NEIGHBORHOOD_RANK_LT_2", error_class="PRECONDITION_FAILED",
    )

    for label, scale in (("huge", 1e308), ("tiny", 1e-200)):
        unsafe_scale = root / f"{label}-scale.xyz"
        write_xyz(
            unsafe_scale,
            [(x * scale, y * scale, 0.0) for x in (-1.0, 0.0, 1.0)
             for y in (-1.0, 0.0, 1.0)],
        )
        unsafe_points = artifact(
            unsafe_scale, "PointSet3", "xyz", f"{label}-scale"
        )
        expect_error(
            "pointset.simplify.hierarchy", [unsafe_points],
            root / f"{label}-hierarchy",
            {"cluster_size": 2, "maximum_variation": 0.1},
            f"{label}-hierarchy", code="UNSUPPORTED_NUMERIC_SCALE",
            error_class="PRECONDITION_FAILED",
        )
        expect_error(
            "pointset.smooth.jet", [unsafe_points], root / f"{label}-smooth",
            {"neighbors": 4, "degree_fitting": 2, "degree_monge": 2},
            f"{label}-smooth", code="UNSUPPORTED_NUMERIC_SCALE",
            error_class="PRECONDITION_FAILED",
        )

    for translated_offset in (1e10, 1e12, 1e50):
        label = f"translated-unsafe-{translated_offset:.0e}".replace("+", "")
        translated_unsafe = root / f"{label}.xyz"
        write_xyz(
            translated_unsafe,
            [(translated_offset, float(y), float(z))
             for y in range(3) for z in range(3)],
        )
        translated_unsafe_points = artifact(
            translated_unsafe, "PointSet3", "xyz", label
        )
        for method, parameters in (
            ("pca", {"method": "pca", "neighbors": 8}),
            ("jet", {"method": "jet", "neighbors": 8, "degree_fitting": 2}),
        ):
            expect_error(
                "pointset.normals.estimate", [translated_unsafe_points],
                root / f"{label}-{method}", parameters,
                f"{label}-{method}", code="UNSUPPORTED_NUMERIC_SCALE",
                error_class="PRECONDITION_FAILED",
            )
        expect_error(
            "pointset.smooth.jet", [translated_unsafe_points],
            root / f"{label}-smooth",
            {"neighbors": 8, "degree_fitting": 2, "degree_monge": 2},
            f"{label}-smooth", code="UNSUPPORTED_NUMERIC_SCALE",
            error_class="PRECONDITION_FAILED",
        )

    translated_safe = root / "translated-safe-plane.xyz"
    write_xyz(
        translated_safe,
        [(1e6, float(y), float(z)) for y in range(3) for z in range(3)],
    )
    translated_safe_points = artifact(
        translated_safe, "PointSet3", "xyz", "translated-safe"
    )
    for method, parameters in (
        ("pca", {"method": "pca", "neighbors": 8}),
        ("jet", {"method": "jet", "neighbors": 8, "degree_fitting": 2}),
    ):
        translated_normals = invoke(
            "pointset.normals.estimate", [translated_safe_points],
            root / f"translated-safe-{method}", parameters,
            f"translated-safe-{method}",
        )
        for nx, ny, nz in read_ply_normals(result_path(translated_normals)):
            assert abs(nx) >= 1.0 - 1e-6, translated_normals
            assert (ny * ny + nz * nz) ** 0.5 <= 1e-6, translated_normals
    translated_smooth = invoke(
        "pointset.smooth.jet", [translated_safe_points],
        root / "translated-safe-smooth",
        {"neighbors": 8, "degree_fitting": 2, "degree_monge": 2},
        "translated-safe-smooth",
    )
    translated_smooth_path = result_path(translated_smooth)
    translated_smooth_check = invoke(
        "pointset.validate.smoothed",
        [artifact(translated_smooth_path, "PointSet3", "xyz", "translated-smooth"),
         translated_safe_points], root / "translated-safe-smooth-check",
        {"neighbors": 8, "degree_fitting": 2, "degree_monge": 2},
        "translated-safe-smooth-check",
    )
    assert translated_smooth_check["metrics"]["cgal_reference_match"] is True

    expect_error("pointset.simplify.grid", [points], root / "length-overflow", {
        "cell_size": {"value": 1e308, "unit": "m"}, "min_points_per_cell": 1,
    }, "length-overflow", code="INVALID_TYPED_LENGTH", error_class="INVALID_INPUT")
    expect_error("pointset.simplify.grid", [points], root / "cell-ratio-overflow", {
        "cell_size": {"value": 5e-324, "unit": "mm"},
        "min_points_per_cell": 1,
    }, "cell-ratio-overflow", code="UNSUPPORTED_NUMERIC_SCALE",
        error_class="PRECONDITION_FAILED")
    expect_error(
        "pointset.simplify.grid",
        [artifact(source, "PointSet3", "xyz", "source-metres", "m")],
        root / "length-underflow", {
            "cell_size": {"value": 5e-324, "unit": "mm"},
            "min_points_per_cell": 1,
        }, "length-underflow", code="INVALID_TYPED_LENGTH",
        error_class="INVALID_INPUT",
    )
    expect_error("pointset.simplify.random", [points], root / "seed-overflow", {
        "removed_percentage": 50.0, "seed": 2**32,
    }, "seed-overflow", code="INVALID_PARAMETER", error_class="INVALID_INPUT")
    expect_error("pointset.smooth.jet", [points], root / "bad-degree-order", {
        "neighbors": 8, "degree_fitting": 1, "degree_monge": 2,
    }, "bad-degree-order", code="MONGE_DEGREE_EXCEEDS_FITTING",
        error_class="PRECONDITION_FAILED")

    malformed_ply = root / "malformed-property.ply"
    malformed_ply.write_text(
        "ply\nformat ascii 1.0\nelement vertex 3\nproperty banana x\n"
        "property double y\nproperty double z\nproperty double nx\n"
        "property double ny\nproperty double nz\nend_header\n"
        "0 0 0 0 0 1\n1 0 0 0 0 1\n0 1 0 0 0 1\n",
        encoding="ascii",
    )
    expect_error(
        "pointset.validate.basic",
        [artifact(malformed_ply, "PointSet3Normals", "ply", "malformed-ply")],
        root / "malformed-ply-check", {}, "malformed-ply-check",
        code="MALFORMED_PLY", error_class="INVALID_INPUT",
    )

    expect_error("pointset.simplify.random", [points], root / "bad-kernel", {
        "removed_percentage": 50.0, "seed": 1,
    }, "bad-kernel", kernel="exact_constructions", code="UNSUPPORTED_KERNEL",
        error_class="UNSUPPORTED_ADAPTER")
    expect_error("pointset.smooth.jet", [points], root / "bad-neighbors", {
        "neighbors": 1, "degree_fitting": 2, "degree_monge": 2,
    }, "bad-neighbors", code="INVALID_PARAMETER", error_class="INVALID_INPUT")
    bad_digest = dict(points)
    bad_digest["sha256"] = "0" * 64
    expect_error("pointset.simplify.grid", [bad_digest], root / "bad-digest", {
        "cell_size": {"value": 1.0, "unit": "mm"}, "min_points_per_cell": 1,
    }, "bad-digest", code="DIGEST_MISMATCH", error_class="INVALID_INPUT")
    assert sha256(source) == source_digest, "worker mutated the source artifact"

print(
    "Wave B production worker: 7 transforms, deterministic CGAL reference validators, "
    "unit/local-surface normal contracts, typed units, strict I/O, numeric fail-closed, "
    "digest and taxonomy cases: PASS"
)
