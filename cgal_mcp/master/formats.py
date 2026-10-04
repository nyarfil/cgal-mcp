"""Bounded syntax readers and separate, non-repairing geometry observations."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import InvalidInput


@dataclass(frozen=True)
class Inspection:
    geometry_type: str
    format: str
    properties: dict[str, Any]
    metadata: dict[str, Any]


def _finite(values: list[float]) -> bool:
    return all(math.isfinite(value) for value in values)


def _bounds(points: list[tuple[float, ...]]) -> list[list[float]] | None:
    if not points:
        return None
    return [[min(point[axis] for point in points), max(point[axis] for point in points)]
            for axis in range(len(points[0]))]


def parse_xyz(content: bytes) -> Inspection:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidInput("xyz_encoding", "XYZ must be UTF-8 text") from exc
    points: list[tuple[float, float, float]] = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 3:
            raise InvalidInput("xyz_syntax", f"XYZ line {line_number} must have three coordinates")
        try:
            point = tuple(float(field) for field in fields)
        except ValueError as exc:
            raise InvalidInput("xyz_syntax", f"XYZ line {line_number} has a non-number") from exc
        if not _finite(list(point)):
            raise InvalidInput("nonfinite_coordinate", f"XYZ line {line_number} is non-finite")
        points.append(point)  # type: ignore[arg-type]
    if not points:
        raise InvalidInput("empty_geometry", "XYZ contains no points")
    return Inspection("PointSet3", "xyz",
                      {"finite": True, "bounds_known": True},
                      {"point_count": len(points), "bounds": _bounds(points)})


def _tokens(text: str) -> list[str]:
    return " ".join(line.split("#", 1)[0] for line in text.splitlines()).split()


def parse_off(content: bytes) -> Inspection:
    try:
        tokens = _tokens(content.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise InvalidInput("off_encoding", "OFF must be UTF-8 text") from exc
    if len(tokens) < 4 or tokens[0] != "OFF":
        raise InvalidInput("off_header", "Expected ASCII OFF header")
    try:
        vertex_count, face_count, edge_hint = (int(value) for value in tokens[1:4])
    except ValueError as exc:
        raise InvalidInput("off_counts", "Invalid OFF counts") from exc
    if vertex_count < 0 or face_count < 0 or edge_hint < 0:
        raise InvalidInput("off_counts", "OFF counts must be non-negative")
    position = 4
    points: list[tuple[float, float, float]] = []
    try:
        for _ in range(vertex_count):
            point = tuple(float(value) for value in tokens[position:position + 3])
            if len(point) != 3:
                raise ValueError
            position += 3
            if not _finite(list(point)):
                raise InvalidInput("nonfinite_coordinate", "OFF contains a non-finite vertex")
            points.append(point)  # type: ignore[arg-type]
        faces: list[list[int]] = []
        for _ in range(face_count):
            size = int(tokens[position]); position += 1
            if size < 3:
                raise InvalidInput("off_face", "OFF face has fewer than three vertices")
            indices = [int(value) for value in tokens[position:position + size]]
            if len(indices) != size:
                raise ValueError
            position += size
            if any(index < 0 or index >= vertex_count for index in indices):
                raise InvalidInput("off_index", "OFF face index is out of range")
            faces.append(indices)
    except (IndexError, ValueError) as exc:
        raise InvalidInput("off_truncated", "OFF data is malformed or truncated") from exc
    if position != len(tokens):
        raise InvalidInput("off_trailing", "OFF contains unexpected trailing tokens")

    edge_counts: dict[tuple[int, int], int] = {}
    duplicate_faces = 0
    seen_faces: set[tuple[int, ...]] = set()
    degenerate_faces = 0
    for face in faces:
        key = tuple(sorted(face))
        duplicate_faces += key in seen_faces
        seen_faces.add(key)
        if len(set(face)) != len(face):
            degenerate_faces += 1
        if len(face) == 3:
            a, b, c = (points[index] for index in face)
            u = tuple(b[i] - a[i] for i in range(3))
            v = tuple(c[i] - a[i] for i in range(3))
            cross = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
                     u[0] * v[1] - u[1] * v[0])
            if cross == (0.0, 0.0, 0.0):
                degenerate_faces += 1
        for first, second in zip(face, face[1:] + face[:1]):
            edge = tuple(sorted((first, second)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    triangular = all(len(face) == 3 for face in faces)
    manifold_edges = all(count <= 2 for count in edge_counts.values())
    clean_triangle_mesh = triangular and manifold_edges and not duplicate_faces and not degenerate_faces
    geometry_type = "TriangleSurfaceMesh" if clean_triangle_mesh else "PolygonSoup3"
    return Inspection(geometry_type, "off", {
        "finite": True, "triangulated": triangular, "manifold_edges": manifold_edges,
        "closed": bool(edge_counts) and all(count == 2 for count in edge_counts.values()),
        "self_intersections": "unknown", "oriented": "unknown",
    }, {"vertices": vertex_count, "faces": face_count, "edges": len(edge_counts),
        "bounds": _bounds(points), "duplicate_faces": duplicate_faces,
        "degenerate_faces": degenerate_faces})


def parse_obj(content: bytes) -> Inspection:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidInput("obj_encoding", "OBJ must be UTF-8 text") from exc
    points: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        fields = raw.strip().split()
        if not fields or fields[0].startswith("#"):
            continue
        if fields[0] == "v":
            if len(fields) < 4:
                raise InvalidInput("obj_vertex", f"OBJ line {number} has an invalid vertex")
            try:
                point = tuple(float(value) for value in fields[1:4])
            except ValueError as exc:
                raise InvalidInput("obj_vertex", f"OBJ line {number} has an invalid vertex") from exc
            if not _finite(list(point)):
                raise InvalidInput("nonfinite_coordinate", "OBJ contains a non-finite vertex")
            points.append(point)  # type: ignore[arg-type]
        elif fields[0] == "f":
            if len(fields) < 4:
                raise InvalidInput("obj_face", f"OBJ line {number} has an invalid face")
            indices: list[int] = []
            for field in fields[1:]:
                try:
                    raw_index = int(field.split("/", 1)[0])
                except ValueError as exc:
                    raise InvalidInput("obj_face", f"OBJ line {number} has an invalid index") from exc
                index = raw_index - 1 if raw_index > 0 else len(points) + raw_index
                if index < 0 or index >= len(points):
                    raise InvalidInput("obj_index", f"OBJ line {number} index is out of range")
                indices.append(index)
            faces.append(indices)
    if not points or not faces:
        raise InvalidInput("empty_geometry", "OBJ must contain vertices and faces")
    triangular = all(len(face) == 3 for face in faces)
    return Inspection("PolygonSoup3", "obj", {
        "finite": True, "triangulated": triangular, "manifold_edges": "unknown",
        "closed": "unknown", "self_intersections": "unknown", "oriented": "unknown",
    }, {"vertices": len(points), "faces": len(faces), "bounds": _bounds(points)})


def parse_stl(content: bytes) -> Inspection:
    triangle_count: int
    if len(content) >= 84:
        triangle_count = struct.unpack_from("<I", content, 80)[0]
        expected = 84 + triangle_count * 50
        if expected == len(content):
            points: list[tuple[float, float, float]] = []
            for index in range(triangle_count):
                values = struct.unpack_from("<12f", content, 84 + index * 50)
                coordinates = list(values[3:12])
                if not _finite(coordinates):
                    raise InvalidInput("nonfinite_coordinate", "STL contains non-finite coordinates")
                points.extend(tuple(coordinates[offset:offset + 3]) for offset in (0, 3, 6))
            return Inspection("PolygonSoup3", "stl", {
                "finite": True, "triangulated": True, "manifold_edges": "unknown",
                "closed": "unknown", "self_intersections": "unknown", "oriented": "unknown",
            }, {"vertices_with_duplicates": len(points), "faces": triangle_count,
                "bounds": _bounds(points), "encoding": "binary"})
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise InvalidInput("stl_syntax", "Invalid binary or ASCII STL") from exc
    points = []
    for raw in text.splitlines():
        fields = raw.strip().split()
        if fields[:1] == ["vertex"] and len(fields) == 4:
            try:
                point = tuple(float(value) for value in fields[1:])
            except ValueError as exc:
                raise InvalidInput("stl_syntax", "Invalid ASCII STL vertex") from exc
            if not _finite(list(point)):
                raise InvalidInput("nonfinite_coordinate", "STL contains non-finite coordinates")
            points.append(point)  # type: ignore[arg-type]
    if not points or len(points) % 3:
        raise InvalidInput("stl_syntax", "Invalid ASCII STL triangles")
    return Inspection("PolygonSoup3", "stl", {
        "finite": True, "triangulated": True, "manifold_edges": "unknown",
        "closed": "unknown", "self_intersections": "unknown", "oriented": "unknown",
    }, {"vertices_with_duplicates": len(points), "faces": len(points) // 3,
        "bounds": _bounds(points), "encoding": "ascii"})


def parse_ply(content: bytes) -> Inspection:
    marker = b"end_header\n"
    offset = content.find(marker)
    marker_size = len(marker)
    if offset < 0:
        marker = b"end_header\r\n"
        offset = content.find(marker)
        marker_size = len(marker)
    if offset < 0:
        raise InvalidInput("ply_header", "PLY end_header was not found")
    try:
        header = content[:offset].decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise InvalidInput("ply_header", "PLY header must be ASCII") from exc
    if not header or header[0].strip() != "ply":
        raise InvalidInput("ply_header", "Expected PLY header")
    format_line = next((line for line in header if line.startswith("format ")), "")
    if format_line != "format ascii 1.0":
        raise InvalidInput("ply_format", "Foundation importer supports ASCII PLY 1.0")
    vertex_count = face_count = 0
    vertex_properties: list[str] = []
    element = ""
    for line in header:
        fields = line.split()
        if fields[:2] == ["element", "vertex"]:
            vertex_count = int(fields[2]); element = "vertex"
        elif fields[:2] == ["element", "face"]:
            face_count = int(fields[2]); element = "face"
        elif fields[:1] == ["element"]:
            element = fields[1]
        elif fields[:1] == ["property"] and element == "vertex":
            vertex_properties.append(fields[-1])
    if not all(axis in vertex_properties for axis in ("x", "y", "z")):
        raise InvalidInput("ply_properties", "PLY vertices require x, y and z")
    lines = content[offset + marker_size:].decode("ascii").splitlines()
    if len(lines) < vertex_count + face_count:
        raise InvalidInput("ply_truncated", "PLY body is truncated")
    indices = [vertex_properties.index(axis) for axis in ("x", "y", "z")]
    points: list[tuple[float, float, float]] = []
    for line in lines[:vertex_count]:
        fields = line.split()
        try:
            point = tuple(float(fields[index]) for index in indices)
        except (ValueError, IndexError) as exc:
            raise InvalidInput("ply_vertex", "Invalid PLY vertex") from exc
        if not _finite(list(point)):
            raise InvalidInput("nonfinite_coordinate", "PLY contains non-finite coordinates")
        points.append(point)  # type: ignore[arg-type]
    triangular = True
    for line in lines[vertex_count:vertex_count + face_count]:
        fields = line.split()
        try:
            count = int(fields[0]); face = [int(value) for value in fields[1:1 + count]]
        except (ValueError, IndexError) as exc:
            raise InvalidInput("ply_face", "Invalid PLY face") from exc
        if len(face) != count or any(index < 0 or index >= vertex_count for index in face):
            raise InvalidInput("ply_face", "Invalid PLY face indices")
        triangular = triangular and count == 3
    return Inspection("PolygonSoup3", "ply", {
        "finite": True, "triangulated": triangular, "manifold_edges": "unknown",
        "closed": "unknown", "self_intersections": "unknown", "oriented": "unknown",
    }, {"vertices": vertex_count, "faces": face_count, "bounds": _bounds(points),
        "encoding": "ascii"})


def parse_json_geometry(content: bytes, requested_type: str | None) -> Inspection:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidInput("json_syntax", "Invalid UTF-8 JSON geometry") from exc
    if requested_type == "ValidationReport":
        if not isinstance(value, dict) or value.get("status") not in {"pass", "fail"}:
            raise InvalidInput("validation_report", "ValidationReport status must be pass or fail")
        return Inspection("ValidationReport", "json", {"valid": value["status"] == "pass"}, value)
    points_value = value.get("points") if isinstance(value, dict) else value
    if not isinstance(points_value, list) or len(points_value) < 3:
        raise InvalidInput("polygon2_syntax", "Polygon2 JSON requires at least three points")
    points: list[tuple[float, float]] = []
    for item in points_value:
        if not isinstance(item, list) or len(item) != 2 or not all(isinstance(x, (int, float)) for x in item):
            raise InvalidInput("polygon2_syntax", "Each Polygon2 point must contain two numbers")
        point = (float(item[0]), float(item[1]))
        if not _finite(list(point)):
            raise InvalidInput("nonfinite_coordinate", "Polygon2 contains non-finite coordinates")
        points.append(point)
    return Inspection("Polygon2", "json", {"finite": True, "simple": "unknown"},
                      {"point_count": len(points), "bounds": _bounds(points)})


PARSERS = {"xyz": parse_xyz, "off": parse_off, "obj": parse_obj,
           "stl": parse_stl, "ply": parse_ply}


def inspect_bytes(content: bytes, format_name: str, requested_type: str | None = None) -> Inspection:
    format_name = format_name.lower().lstrip(".")
    if format_name == "json":
        inspection = parse_json_geometry(content, requested_type)
    elif format_name in PARSERS:
        inspection = PARSERS[format_name](content)
    else:
        raise InvalidInput("unsupported_format", f"Unsupported geometry format: {format_name}")
    if requested_type and requested_type != inspection.geometry_type:
        raise InvalidInput("type_mismatch", f"Expected {requested_type}, parsed {inspection.geometry_type}")
    return inspection


def format_from_path(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix not in {*PARSERS, "json"}:
        raise InvalidInput("unsupported_format", f"Unsupported geometry extension: {path.suffix}")
    return suffix
