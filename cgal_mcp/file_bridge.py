"""Safe OFF/STL file bridge for the validated CGAL runtime.

This module deliberately keeps the caller's source file and CAD document out of
the runtime's mutable workspace.  A result is only written after the runtime
and the bytes that will actually be published have both passed verification.
"""
import argparse
import asyncio
import hashlib
import io
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import trimesh

from cgal_mcp.runtime import MAX_BYTES, Runtime, parse_off, worker_path


MAX_FILE_BYTES = 64 * 1024 * 1024
_SUPPORTED_SUFFIXES = {".off", ".stl"}


class FileBridgeRejected(RuntimeError):
    """The runtime did not accept an artifact for publication."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_limited(path: Path) -> bytes:
    if not path.is_file():
        raise ValueError("Input must be an existing regular file")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Input exceeds 64 MiB limit")
    content = path.read_bytes()
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("Input exceeds 64 MiB limit")
    return content


def _off_tokens(content: str) -> list[str]:
    return " ".join(line.split("#", 1)[0] for line in content.splitlines()).split()


def _off_arrays(content: str) -> tuple[np.ndarray, np.ndarray]:
    """Turn already-validated triangle OFF text into arrays without repair."""
    parse_off(content)
    tokens = _off_tokens(content)
    vertices, faces = int(tokens[1]), int(tokens[2])
    position = 4
    points = np.asarray(
        [[float(tokens[position + 3 * index + axis]) for axis in range(3)]
         for index in range(vertices)],
        dtype=np.float64,
    )
    position += vertices * 3
    triangles = np.asarray(
        [[int(tokens[position + 4 * index + axis]) for axis in range(1, 4)]
         for index in range(faces)],
        dtype=np.int64,
    )
    return points, triangles


def mesh_to_off(vertices: np.ndarray, faces: np.ndarray) -> str:
    """Encode a triangle mesh as validated OFF using round-trip float text."""
    points = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(faces, dtype=np.int64)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 3:
        raise ValueError("Mesh must contain at least three 3D vertices")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or len(triangles) < 1:
        raise ValueError("Mesh must contain triangle faces")
    if not np.isfinite(points).all() or np.any(triangles < 0) or np.any(triangles >= len(points)):
        raise ValueError("Mesh contains invalid coordinates or indices")
    lines = ["OFF", f"{len(points)} {len(triangles)} 0"]
    lines.extend(" ".join(format(float(value), ".17g") for value in point) for point in points)
    lines.extend("3 " + " ".join(str(int(index)) for index in face) for face in triangles)
    content = "\n".join(lines) + "\n"
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Converted OFF exceeds runtime limit")
    parse_off(content)
    return content


def _deduplicate_exact(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Join STL triangle soup only where all coordinate values are identical."""
    points = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(faces, dtype=np.int64)
    if points.ndim != 2 or points.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError("STL must contain a triangle mesh")
    if not np.isfinite(points).all() or np.any(triangles < 0) or np.any(triangles >= len(points)):
        raise ValueError("STL contains invalid coordinates or indices")
    # numpy.unique compares stored floating values; no rounding, welding tolerance,
    # normal repair, or other geometry modification is applied here.
    unique, inverse = np.unique(points, axis=0, return_inverse=True)
    return unique, inverse[triangles]


def stl_to_off(content: bytes) -> str:
    """Decode STL without trimesh processing, then exactly connect its triangle soup."""
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("STL exceeds 64 MiB limit")
    try:
        loaded = trimesh.load(io.BytesIO(content), file_type="stl", process=False)
    except Exception as exc:  # trimesh has format-specific parse errors.
        raise ValueError("Invalid STL input") from exc
    if not isinstance(loaded, trimesh.Trimesh):
        raise ValueError("STL must contain one triangle mesh")
    vertices, faces = _deduplicate_exact(loaded.vertices, loaded.faces)
    return mesh_to_off(vertices, faces)


def _input_off(content: bytes, suffix: str) -> tuple[str, dict[str, Any]]:
    if suffix == ".off":
        try:
            off = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("OFF input must be UTF-8") from exc
        # Keep the caller's exact decoded bytes; parse_off is the authoritative
        # validation and runtime registration preserves those bytes verbatim.
        info = parse_off(off)
        return off, info
    off = stl_to_off(content)
    return off, parse_off(off)


async def _wait_for_job(runtime: Runtime, job: Mapping[str, Any]) -> dict[str, Any]:
    job_id = str(job["job_id"])
    task = runtime.tasks.get(job_id)
    if task is None:
        raise RuntimeError("Runtime did not retain the job task")
    await task
    return runtime.status(job_id)


async def _verify_export(runtime: Runtime, source_asset: str, exported_asset: str,
                         parameters: Mapping[str, Any]) -> dict[str, Any]:
    plan = runtime.plan_distance(source_asset, exported_asset, {
        "tolerance": parameters["tolerance"],
        "error_bound": parameters["error_bound"],
    })
    status = await _wait_for_job(runtime, runtime.execute(plan["plan_id"]))
    if status.get("state") != "succeeded" or status.get("verification", {}).get("verdict") != "pass":
        raise FileBridgeRejected("Exported file failed independent distance verification")
    return status


def _export_stl(candidate_off: str) -> tuple[bytes, str, dict[str, Any]]:
    vertices, faces = _off_arrays(candidate_off)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False, validate=False)
    exported = mesh.export(file_type="stl")
    if not isinstance(exported, bytes):
        exported = bytes(exported)
    # Binary STL changes the representable coordinate values.  Re-open exactly
    # the bytes that would be published and verify that geometry instead.
    reloaded_off = stl_to_off(exported)
    return exported, reloaded_off, parse_off(reloaded_off)


def _publish_exclusive(path: Path, content: bytes) -> None:
    created = False
    try:
        with path.open("xb") as destination:
            created = True
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise


async def simplify_file(input_path: str | Path, output_path: str | Path, unit: str,
                        parameters: Mapping[str, Any], runtime: Runtime) -> dict[str, Any]:
    """Simplify one OFF/STL file and publish only an independently verified result."""
    source = Path(input_path).expanduser().resolve(strict=True)
    output = Path(output_path).expanduser().resolve(strict=False)
    if source.suffix.lower() not in _SUPPORTED_SUFFIXES or output.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise ValueError("Only .off and .stl input/output files are supported")
    if source == output:
        raise ValueError("Output path must differ from input path")
    if output.exists():
        raise FileExistsError("Output path already exists")
    if not output.parent.is_dir():
        raise ValueError("Output directory does not exist")
    source_bytes = _read_limited(source)
    source_hash = _sha256(source_bytes)
    source_off, source_counts = _input_off(source_bytes, source.suffix.lower())
    registered_source = runtime.register(source_off, unit)
    plan = runtime.plan(registered_source["asset_id"], dict(parameters))
    job_status = await _wait_for_job(runtime, runtime.execute(plan["plan_id"]))
    if job_status.get("state") != "succeeded" or job_status.get("verification", {}).get("verdict") != "pass":
        raise FileBridgeRejected("Simplification did not pass runtime verification")
    artifact = job_status.get("artifact")
    if not isinstance(artifact, dict) or "asset_id" not in artifact:
        raise RuntimeError("Accepted job has no output artifact")
    candidate_off = runtime.artifact(artifact["asset_id"])["off"]
    candidate_counts = parse_off(candidate_off)
    if output.suffix.lower() == ".stl":
        exported_bytes, verification_off, output_counts = _export_stl(candidate_off)
        registered_export = runtime.register(verification_off, unit)
    else:
        exported_bytes = candidate_off.encode("utf-8")
        output_counts = candidate_counts
        registered_export = artifact
    export_status = await _verify_export(
        runtime, registered_source["asset_id"], registered_export["asset_id"], parameters
    )
    # Refuse to publish if another process replaced or changed the original while
    # CGAL was working.  We never write to the caller's source path.
    if _read_limited(source) != source_bytes:
        raise RuntimeError("Input changed during simplification")
    _publish_exclusive(output, exported_bytes)
    return {
        "job": job_status,
        "computation": job_status.get("computation"),
        "verification": job_status.get("verification"),
        "export_verification": export_status.get("verification"),
        "output_path": str(output),
        "source": {
            "file_sha256": source_hash,
            "registered_sha256": registered_source["sha256"],
            "vertices": source_counts["vertices"],
            "faces": source_counts["faces"],
        },
        "output": {
            "file_sha256": _sha256(exported_bytes),
            "registered_sha256": registered_export["sha256"],
            "vertices": output_counts["vertices"],
            "faces": output_counts["faces"],
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simplify an OFF/STL file through CGAL MCP")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--unit", choices=("mm", "cm", "m"), required=True)
    parser.add_argument("--ratio", type=float, required=True)
    parser.add_argument("--tolerance", type=float, required=True)
    parser.add_argument("--error-bound", type=float, required=True)
    parser.add_argument("--envelope", type=float, default=0.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    runtime = Runtime(Path(os.environ.get("CGAL_MCP_DATA", "work/cgal-mcp-data")),
                      worker_path("worker"), worker_path("distance"))
    parameters = {"edge_ratio": args.ratio, "tolerance": args.tolerance,
                  "error_bound": args.error_bound, "envelope": args.envelope}
    try:
        result = asyncio.run(simplify_file(args.input, args.output, args.unit, parameters, runtime))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
