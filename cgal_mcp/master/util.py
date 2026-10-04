from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, BinaryIO


ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
UNITS = {"mm", "cm", "m"}
ANGLE_UNITS = {"deg", "rad"}
UNIT_SCALE_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


def valid_artifact_unit(artifact_type: str | None, unit: str) -> bool:
    return unit == "none" if artifact_type in {"ValidationReport", "GeometryAnalysisReport"} else unit in UNITS


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def digest_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def copy_hash_bounded(source: BinaryIO, destination: BinaryIO, maximum: int,
                      chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = source.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise ValueError(f"Input exceeds {maximum} byte limit")
        digest.update(chunk)
        destination.write(chunk)
    return digest.hexdigest(), total


def within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def normalize_quantities(value: Any, input_unit: str) -> Any:
    """Normalize explicit length/angle quantities without guessing bare numbers."""
    if isinstance(value, list):
        return [normalize_quantities(item, input_unit) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) >= {"value", "unit"}:
        if (not isinstance(value["value"], (int, float)) or isinstance(value["value"], bool)
                or not math.isfinite(float(value["value"]))):
            raise ValueError("Quantity value must be a finite number")
        unit = value["unit"]
        number = float(value["value"])
        if unit in UNITS:
            if input_unit not in UNITS:
                raise ValueError("Length quantity requires an input length unit")
            normalized = number * UNIT_SCALE_MM[unit] / UNIT_SCALE_MM[input_unit]
            return {"value": normalized, "unit": input_unit,
                    "source_value": number, "source_unit": unit}
        if unit in ANGLE_UNITS:
            return {"value": math.radians(number) if unit == "deg" else number,
                    "unit": "rad", "source_value": number, "source_unit": unit}
        raise ValueError(f"Unsupported quantity unit: {unit}")
    return {key: normalize_quantities(item, input_unit) for key, item in value.items()}


def atomic_write_exclusive(path: Path, content: bytes) -> None:
    path.parent.resolve(strict=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
