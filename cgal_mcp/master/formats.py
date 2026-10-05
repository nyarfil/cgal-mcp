"""Bounded syntax readers and separate, non-repairing geometry observations."""

from __future__ import annotations

import json
import math
import re
import struct
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from .errors import InvalidInput


_ASCII_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


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
        if any(_ASCII_NUMBER.fullmatch(field) is None for field in fields):
            raise InvalidInput("xyz_syntax", f"XYZ line {line_number} has a non-number")
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
            coordinate_tokens = tuple(tokens[position:position + 3])
            point = tuple(float(value) for value in coordinate_tokens)
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
    edge_directions: dict[tuple[int, int], list[int]] = {}
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
            if cross == (0.0, 0.0, 0.0) or not _finite(list(cross)):
                # The native worker parses OFF coordinates as binary64 before
                # constructing its exact kernel.  Re-evaluate ambiguous cross
                # products as exact rationals of those same binary64 values so
                # importer typing and worker geometry agree at every scale.
                exact = [[Fraction.from_float(value) for value in points[index]]
                         for index in face]
                exact_u = [exact[1][i] - exact[0][i] for i in range(3)]
                exact_v = [exact[2][i] - exact[0][i] for i in range(3)]
                exact_cross = (
                    exact_u[1] * exact_v[2] - exact_u[2] * exact_v[1],
                    exact_u[2] * exact_v[0] - exact_u[0] * exact_v[2],
                    exact_u[0] * exact_v[1] - exact_u[1] * exact_v[0])
                if exact_cross == (0, 0, 0):
                    degenerate_faces += 1
        for first, second in zip(face, face[1:] + face[:1]):
            edge = tuple(sorted((first, second)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
            edge_directions.setdefault(edge, []).append(
                1 if (first, second) == edge else -1)
    triangular = all(len(face) == 3 for face in faces)
    manifold_edges = all(count <= 2 for count in edge_counts.values())
    orientation_consistent = all(
        len(directions) == 1 or sorted(directions) == [-1, 1]
        for directions in edge_directions.values())
    clean_triangle_mesh = (triangular and manifold_edges and orientation_consistent
                           and not duplicate_faces and not degenerate_faces)
    geometry_type = "TriangleSurfaceMesh" if clean_triangle_mesh else "PolygonSoup3"
    return Inspection(geometry_type, "off", {
        "finite": True, "triangulated": triangular, "manifold_edges": manifold_edges,
        "closed": bool(edge_counts) and all(count == 2 for count in edge_counts.values()),
        "self_intersections": "unknown", "oriented": "unknown",
        "indices_valid": True, "surface_mesh_constructible": clean_triangle_mesh,
    }, {"vertices": vertex_count, "faces": face_count, "edges": len(edge_counts),
        "bounds": _bounds(points), "duplicate_faces": duplicate_faces,
        "degenerate_faces": degenerate_faces,
        "max_face_degree": max((len(face) for face in faces), default=0)})


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


def parse_pointset_normals_ply(content: bytes) -> Inspection:
    """Parse the strict ASCII PLY interchange used by PointSet3Normals.

    This intentionally accepts vertex data only.  Faces and other elements
    would change the artifact's meaning and therefore cannot be hidden behind
    the PointSet3Normals type.
    """
    try:
        lines = content.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise InvalidInput("ply_header", "PointSet3Normals PLY must be ASCII") from exc
    if len(lines) < 4 or lines[0] != "ply" or lines[1] != "format ascii 1.0":
        raise InvalidInput("ply_format", "PointSet3Normals requires ASCII PLY 1.0")

    scalar_types = {"char", "uchar", "short", "ushort", "int", "uint",
                    "int8", "uint8", "int16", "uint16", "int32", "uint32",
                    "float", "double", "float32", "float64"}
    vertex_count: int | None = None
    properties: list[str] = []
    header_end: int | None = None
    for index, line in enumerate(lines[2:], 2):
        fields = line.split()
        if fields == ["end_header"]:
            header_end = index
            break
        if not fields or fields[0] in {"comment", "obj_info"}:
            continue
        if fields[:2] == ["element", "vertex"] and len(fields) == 3:
            if vertex_count is not None:
                raise InvalidInput("ply_element", "PLY must contain one vertex element")
            try:
                vertex_count = int(fields[2])
            except ValueError as exc:
                raise InvalidInput("ply_element", "PLY vertex count is invalid") from exc
            if vertex_count <= 0 or vertex_count > 10_000_000:
                raise InvalidInput("ply_element", "PLY vertex count is outside the supported range")
            continue
        if fields[:1] == ["element"]:
            raise InvalidInput("ply_element", "PointSet3Normals does not accept faces or other elements")
        if fields[:1] == ["property"]:
            if vertex_count is None or len(fields) != 3 or fields[1] not in scalar_types:
                raise InvalidInput("ply_properties", "PointSet3Normals requires scalar vertex properties")
            if fields[2] in properties:
                raise InvalidInput("ply_properties", "PLY vertex property names must be unique")
            properties.append(fields[2])
            continue
        raise InvalidInput("ply_header", "PointSet3Normals PLY contains an unsupported header line")
    if header_end is None or vertex_count is None:
        raise InvalidInput("ply_header", "PLY end_header or vertex element is missing")
    required = ("x", "y", "z", "nx", "ny", "nz")
    if any(name not in properties for name in required):
        raise InvalidInput("ply_properties", "PLY vertices require x, y, z, nx, ny and nz")

    body = lines[header_end + 1:]
    if len(body) < vertex_count:
        raise InvalidInput("ply_truncated", "PLY ended before all vertices")
    if any(line.strip() for line in body[vertex_count:]):
        raise InvalidInput("ply_trailing", "PointSet3Normals PLY contains trailing data")
    positions = {name: properties.index(name) for name in required}
    points: list[tuple[float, float, float]] = []
    normals_nonzero = True
    normals_unit = True
    for offset, line in enumerate(body[:vertex_count], 1):
        fields = line.split()
        if len(fields) != len(properties):
            raise InvalidInput("ply_vertex", f"PLY vertex {offset} property count is invalid")
        if any(_ASCII_NUMBER.fullmatch(field) is None for field in fields):
            raise InvalidInput("ply_vertex", f"PLY vertex {offset} has a non-number")
        try:
            values = [float(field) for field in fields]
        except ValueError as exc:
            raise InvalidInput("ply_vertex", f"PLY vertex {offset} has a non-number") from exc
        if not _finite(values):
            raise InvalidInput("nonfinite_coordinate", f"PLY vertex {offset} is non-finite")
        point = tuple(values[positions[name]] for name in ("x", "y", "z"))
        normal = tuple(values[positions[name]] for name in ("nx", "ny", "nz"))
        points.append(point)  # type: ignore[arg-type]
        normals_nonzero = normals_nonzero and normal != (0.0, 0.0, 0.0)
        normals_unit = normals_unit and math.isclose(math.hypot(*normal), 1.0,
                                                     rel_tol=1e-6, abs_tol=1e-6)
    return Inspection("PointSet3Normals", "ply",
                      {"finite": True, "normals_nonzero": normals_nonzero,
                       "normals_unit": normals_unit},
                      {"point_count": vertex_count, "bounds": _bounds(points),
                       "encoding": "ascii", "vertex_properties": properties,
                       "normals_present": True})


def parse_json_geometry(content: bytes, requested_type: str | None) -> Inspection:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON number: {value}")
    try:
        value = json.loads(content, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InvalidInput("json_syntax", "Invalid UTF-8 JSON geometry") from exc
    def require_finite(item: Any) -> None:
        if isinstance(item, float) and not math.isfinite(item):
            raise InvalidInput("json_nonfinite", "JSON report contains a non-finite number")
        if isinstance(item, list):
            for child in item:
                require_finite(child)
        elif isinstance(item, dict):
            for child in item.values():
                require_finite(child)
    require_finite(value)
    if requested_type == "ValidationReport":
        if not isinstance(value, dict) or value.get("status") not in {"pass", "fail"}:
            raise InvalidInput("validation_report", "ValidationReport status must be pass or fail")
        return Inspection("ValidationReport", "json", {"valid": value["status"] == "pass"}, value)
    if requested_type == "GeometryAnalysisReport":
        required = {"schema_version", "analysis_kind", "source", "mesh_summary",
                    "results", "validation"}
        if not isinstance(value, dict) or not required.issubset(value):
            raise InvalidInput("analysis_report", "GeometryAnalysisReport lacks required v1 fields")
        producer_validators = {
            "pmp_inspection": "mesh.producer_check.pmp_inspection",
            "connected_components": "mesh.producer_check.connected_components",
            "normals": "mesh.producer_check.normals",
            "measures": "mesh.producer_check.measures",
            "sharp_features": "mesh.producer_check.sharp_features",
            "self_intersections": "mesh.producer_check.self_intersections",
            "aabb_closest_point": "spatial.producer_check.aabb_closest_point",
            "aabb_segment_candidates": "spatial.producer_check.aabb_segment_candidates",
        }
        if (value["schema_version"] != 1
                or value["analysis_kind"] not in producer_validators):
            raise InvalidInput("analysis_report", "GeometryAnalysisReport version/kind is invalid")
        source = value["source"]
        source_required = {"artifact_id", "type", "format", "unit", "sha256"}
        if (not isinstance(source, dict) or set(source) != source_required
                or not isinstance(source["artifact_id"], str) or not source["artifact_id"]
                or source["type"] not in {"TriangleSurfaceMesh", "PolygonSoup3"}
                or (source["type"] == "PolygonSoup3"
                    and value["analysis_kind"] != "pmp_inspection")
                or source["format"] != "off"
                or source["unit"] not in {"mm", "cm", "m"}
                or not isinstance(source["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) is None):
            raise InvalidInput("analysis_report", "GeometryAnalysisReport source identity is invalid")
        summary = value["mesh_summary"]
        summary_required = {"raw_vertex_count", "raw_face_count", "finite_coordinates",
                            "indices_valid", "triangulated", "surface_mesh_constructible"}
        if (not isinstance(summary, dict) or not summary_required.issubset(summary)
                or any(type(summary[name]) is not int or summary[name] < 0
                       for name in ("raw_vertex_count", "raw_face_count"))
                or any(type(summary[name]) is not bool for name in
                       ("finite_coordinates", "indices_valid", "triangulated",
                        "surface_mesh_constructible"))):
            raise InvalidInput("analysis_report", "GeometryAnalysisReport mesh summary is invalid")
        if not isinstance(value["results"], dict):
            raise InvalidInput("analysis_report", "GeometryAnalysisReport results must be an object")
        results = value["results"]
        required_results = {
            "pmp_inspection": {"count_unit", "parse_issues", "polygon_mesh_valid", "closed",
                               "degenerate_face_count", "non_manifold_vertex_count",
                               "isolated_vertex_count"},
            "connected_components": {"component_count", "count_unit", "components"},
            "normals": {"face_normals", "vertex_normals", "corner_normals",
                        "corner_normal_mode", "count_unit", "degenerate_face_count",
                        "zero_face_normal_count", "zero_vertex_normal_count"},
            "measures": {"surface_area", "signed_volume", "absolute_volume",
                         "volume_centroid"},
            "sharp_features": {"angle", "count_unit", "features"},
            "self_intersections": {"available", "count_unit"},
            "aabb_closest_point": {
                "closest_point", "squared_distance", "distance",
                "closest_face_index", "primitive_count",
                "distance_acceleration",
            },
            "aabb_segment_candidates": {
                "intersects", "intersection_count", "face_indices",
                "primitive_count", "constructs_intersection_geometry",
            },
        }
        missing_results = required_results[value["analysis_kind"]] - results.keys()
        if missing_results:
            raise InvalidInput("analysis_report", "GeometryAnalysisReport results lack: "
                               + ", ".join(sorted(missing_results)))
        if "count_unit" in results and results["count_unit"] != "count":
            raise InvalidInput("analysis_report", "GeometryAnalysisReport count unit is invalid")
        if value["analysis_kind"] == "self_intersections" and results["available"] is True:
            required_available = {"does_self_intersect", "intersection_pair_count",
                                  "pair_limit", "pairs"}
            if required_available - results.keys():
                raise InvalidInput("analysis_report",
                                   "Available self-intersection results are incomplete")
        def validate_availability(item: Any) -> None:
            if isinstance(item, list):
                for child in item:
                    validate_availability(child)
            elif isinstance(item, dict):
                if "available" in item:
                    if type(item["available"]) is not bool:
                        raise InvalidInput("analysis_report", "Result availability must be boolean")
                    if item["available"] is False and (
                            not isinstance(item.get("reason"), str) or not item["reason"]):
                        raise InvalidInput("analysis_report", "Unavailable result requires a reason")
                for child in item.values():
                    validate_availability(child)
        validate_availability(value["results"])
        validation = value["validation"]
        if (not isinstance(validation, dict)
                or not {"validator_id", "authoritative", "passed", "checks"}.issubset(validation)
                or validation["validator_id"] !=
                   producer_validators[value["analysis_kind"]]
                or validation["authoritative"] is not False
                or validation["passed"] is not True
                or not (isinstance(validation["checks"], dict)
                        or (isinstance(validation["checks"], list)
                            and all(isinstance(item, str) for item in validation["checks"])))):
            raise InvalidInput("analysis_report", "GeometryAnalysisReport validation summary is invalid")
        metadata = {"schema_version": 1, "analysis_kind": value["analysis_kind"],
                    "source_sha256": source["sha256"], "source_unit": source["unit"],
                    "raw_vertex_count": summary["raw_vertex_count"],
                    "raw_face_count": summary["raw_face_count"],
                    "result_keys": sorted(value["results"]),
                    "inline_validation_claimed": validation["passed"]}
        return Inspection("GeometryAnalysisReport", "json",
                          {"schema_valid": True, "source_identity_present": True}, metadata)
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
    elif format_name == "ply" and requested_type == "PointSet3Normals":
        inspection = parse_pointset_normals_ply(content)
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
