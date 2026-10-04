"""Adversarial and geometry cases for the generic CGAL Master worker."""

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(
    path: pathlib.Path,
    artifact_id: str = "points",
    artifact_type: str = "PointSet3",
    fmt: str = "xyz",
    unit: str = "mm",
):
    return {
        "artifact_id": artifact_id,
        "type": artifact_type,
        "unit": unit,
        "format": fmt,
        "path": str(path.resolve()),
        "sha256": digest(path),
    }


def request(operation: str, inputs: list[dict], output_dir: pathlib.Path, **updates):
    value = {
        "protocol": 1,
        "request_id": "case-request",
        "operation": operation,
        "inputs": inputs,
        "parameters": {},
        "output_dir": str(output_dir.resolve()),
        "kernel": "package_recommended",
        "limits": {"wall_time_ms": 60000, "memory_mb": 1024},
    }
    value.update(updates)
    return value


def run_raw(worker: str, line: str, timeout: int = 60):
    process = subprocess.run(
        [worker], input=line, text=True, encoding="utf-8",
        capture_output=True, timeout=timeout
    )
    lines = process.stdout.splitlines()
    assert len(lines) == 1, process.stdout
    assert process.stderr == "", process.stderr
    return process, json.loads(lines[0])


def run(worker: str, value: dict, timeout: int = 60):
    return run_raw(worker, json.dumps(value, separators=(",", ":")) + "\n", timeout)


def assert_error(worker: str, value: dict, code: str):
    process, result = run(worker, value)
    assert process.returncode == 0, result
    assert result["protocol"] == 1 and result["status"] == "error", result
    assert result["error"]["code"] == code, result
    assert isinstance(result["error"]["recoverable"], bool)
    assert isinstance(result["error"]["suggested_operations"], list)


worker = sys.argv[1]
with tempfile.TemporaryDirectory() as folder:
    root = pathlib.Path(folder)
    cube = root / "cube.xyz"
    cube.write_text(
        "\n".join(
            [
                "0 0 0",
                "1 0 0",
                "0 1 0",
                "1 1 0",
                "0 0 1",
                "1 0 1",
                "0 1 1",
                "1 1 1",
                "0.5 0.5 0.5",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    cube_stage = root / "cube-stage"
    cube_stage.mkdir()
    process, cube_result = run(
        worker, request("hull.convex_3", [artifact(cube)], cube_stage)
    )
    assert process.returncode == 0 and cube_result["status"] == "ok", cube_result
    assert cube_result["metrics"]["input_point_count"] == 9
    assert cube_result["metrics"]["hull_vertex_count"] == 8
    hull = pathlib.Path(cube_result["outputs"][0]["path"])

    validate_stage = root / "validate-stage"
    validate_stage.mkdir()
    process, validation = run(
        worker,
        request(
            "hull.validate.convex_enclosure",
            [
                artifact(hull, "cube-hull", "TriangleSurfaceMesh", "off"),
                artifact(cube, "cube-points"),
            ],
            validate_stage,
        ),
    )
    assert process.returncode == 0 and validation["status"] == "ok", validation
    assert validation["metrics"]["inside_point_count"] == 1, validation
    assert validation["metrics"]["boundary_point_count"] == 8, validation

    empty = root / "empty.xyz"
    empty.write_bytes(b"")
    empty_stage = root / "empty-stage"
    empty_stage.mkdir()
    process, empty_result = run(
        worker,
        request(
            "hull.validate.convex_enclosure",
            [
                artifact(hull, "cube-hull", "TriangleSurfaceMesh", "off"),
                artifact(empty, "empty-points"),
            ],
            empty_stage,
        ),
    )
    assert process.returncode == 0, empty_result
    assert empty_result["status"] == "error", empty_result
    assert empty_result["error"]["code"] == "EMPTY_POINT_SET"

    outside = root / "outside.xyz"
    outside.write_text(cube.read_text(encoding="ascii") + "2 2 2\n", encoding="ascii")
    outside_stage = root / "outside-stage"
    outside_stage.mkdir()
    process, outside_result = run(
        worker,
        request(
            "hull.validate.convex_enclosure",
            [
                artifact(hull, "cube-hull", "TriangleSurfaceMesh", "off"),
                artifact(outside, "outside-points"),
            ],
            outside_stage,
        ),
    )
    assert process.returncode == 0, outside_result
    assert outside_result["status"] == "error", outside_result
    assert outside_result["error"]["code"] == "POINT_OUTSIDE_HULL"

    process, overwrite_result = run(
        worker, request("hull.convex_3", [artifact(cube)], cube_stage)
    )
    assert process.returncode == 0, overwrite_result
    assert overwrite_result["status"] == "error", overwrite_result
    assert overwrite_result["error"]["code"] == "OUTPUT_EXISTS"

    unit_stage = root / "unit-stage"
    unit_stage.mkdir()
    assert_error(
        worker,
        request(
            "hull.convex_3",
            [artifact(cube, unit="bananas")],
            unit_stage,
        ),
        "UNSUPPORTED_UNIT",
    )

    extreme = root / "extreme.xyz"
    extreme.write_text(
        "0 0 0\n1e200 0 0\n0 1e200 0\n0 0 1e200\n", encoding="ascii"
    )
    extreme_stage = root / "extreme-stage"
    extreme_stage.mkdir()
    process, extreme_result = run(
        worker, request("hull.convex_3", [artifact(extreme)], extreme_stage)
    )
    assert process.returncode == 0 and extreme_result["status"] == "ok", extreme_result
    volume = extreme_result["metrics"]["volume"]
    assert isinstance(volume["exact"], str) and volume["exact"], volume
    assert volume["unit"] == "mm^3"
    assert "approximate" not in volume, volume

    colon_stage = root / "colon-stage"
    colon_stage.mkdir()
    process, colon_result = run(
        worker,
        request(
            "hull.convex_3",
            [artifact(cube)],
            colon_stage,
            request_id="case:1",
        ),
    )
    assert process.returncode == 0 and colon_result["status"] == "ok", colon_result
    assert pathlib.Path(colon_result["outputs"][0]["path"]).is_file()

    wrong_type_stage = root / "wrong-type-stage"
    wrong_type_stage.mkdir()
    assert_error(
        worker,
        request(
            "hull.convex_3",
            [artifact(cube, artifact_type="TriangleSurfaceMesh")],
            wrong_type_stage,
        ),
        "INPUT_TYPE_MISMATCH",
    )

    unknown_stage = root / "unknown-stage"
    unknown_stage.mkdir()
    assert_error(
        worker,
        request("mesh.magic", [artifact(cube)], unknown_stage),
        "UNKNOWN_OPERATION",
    )

    coplanar = root / "coplanar.xyz"
    coplanar.write_text("0 0 0\n1 0 0\n0 1 0\n1 1 0\n", encoding="ascii")
    coplanar_stage = root / "coplanar-stage"
    coplanar_stage.mkdir()
    process, coplanar_result = run(
        worker,
        request("hull.convex_3", [artifact(coplanar)], coplanar_stage),
    )
    assert process.returncode == 0, coplanar_result
    assert coplanar_result["error"]["class"] == "PRECONDITION_FAILED"
    assert coplanar_result["error"]["code"] == "AFFINE_RANK_LT_3"

    insufficient = root / "insufficient.xyz"
    insufficient.write_text("0 0 0\n1 0 0\n0 1 0\n", encoding="ascii")
    insufficient_stage = root / "insufficient-stage"
    insufficient_stage.mkdir()
    process, insufficient_result = run(
        worker,
        request("hull.convex_3", [artifact(insufficient)], insufficient_stage),
    )
    assert process.returncode == 0, insufficient_result
    assert insufficient_result["status"] == "error", insufficient_result
    assert insufficient_result["error"]["class"] == "PRECONDITION_FAILED"
    assert insufficient_result["error"]["code"] == "INSUFFICIENT_POINTS"

    nonfinite = root / "nonfinite.xyz"
    nonfinite.write_text("0 0 0\n1 0 0\n0 1 0\n0 0 NaN\n", encoding="ascii")
    nonfinite_stage = root / "nonfinite-stage"
    nonfinite_stage.mkdir()
    assert_error(
        worker,
        request("hull.convex_3", [artifact(nonfinite)], nonfinite_stage),
        "NONFINITE_OR_INVALID_COORDINATE",
    )

    digest_stage = root / "digest-stage"
    digest_stage.mkdir()
    bad_digest = artifact(cube)
    bad_digest["sha256"] = "0" * 64
    assert_error(
        worker,
        request("hull.convex_3", [bad_digest], digest_stage),
        "DIGEST_MISMATCH",
    )

    kernel_stage = root / "kernel-stage"
    kernel_stage.mkdir()
    assert_error(
        worker,
        request(
            "hull.convex_3",
            [artifact(cube)],
            kernel_stage,
            kernel="fast_inexact",
        ),
        "UNSUPPORTED_KERNEL",
    )

    malicious_stage = root / "malicious-stage"
    malicious_stage.mkdir()
    assert_error(
        worker,
        request(
            "hull.convex_3",
            [artifact(cube)],
            malicious_stage,
            request_id="../escape",
        ),
        "INVALID_IDENTIFIER",
    )
    relative_input = artifact(cube)
    relative_input["path"] = "../cube.xyz"
    assert_error(
        worker,
        request("hull.convex_3", [relative_input], malicious_stage),
        "INPUT_PATH_NOT_ABSOLUTE",
    )
    relative_output = request("hull.convex_3", [artifact(cube)], malicious_stage)
    relative_output["output_dir"] = "../outside"
    assert_error(worker, relative_output, "OUTPUT_PATH_NOT_ABSOLUTE")
    assert not (root / "escape").exists()

    malformed_process, malformed = run_raw(worker, "{not-json}\n")
    assert malformed_process.returncode == 0
    assert malformed["status"] == "error"
    assert malformed["error"]["code"] == "MALFORMED_JSON", malformed

print(
    "Master worker cube/interior, enclosure failure, typed rank failures, finite "
    "parsing, digest, kernel, unit, large exact metric, overwrite, Unicode, "
    "colon identifier, and path rejection: PASS"
)
