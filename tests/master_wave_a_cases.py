"""Wave A policy, validator, typed-unit, and adversarial worker cases.

This suite intentionally names and executes every public CGAL 6.2.1 policy
exposed by the Wave A adapter. VALIDATED status requires this suite to pass
against the official-release build.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import pathlib
import subprocess
import sys
import tempfile

if not __debug__:
    raise SystemExit("Wave A acceptance harness requires Python assertions")


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


TRACE_PATH = os.environ.get("CGAL_MASTER_ACCEPTANCE_TRACE")


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def portable_blob(path: pathlib.Path, expected_sha256: str | None = None) -> tuple[str, dict]:
    """Capture only synthetic fixture/output bytes for trusted local replay."""
    content = path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None:
        assert actual == expected_sha256, (path.name, expected_sha256, actual)
    return actual, {
        "encoding": "base64",
        "byte_size": len(content),
        "content": base64.b64encode(content).decode("ascii"),
    }


def trace_exchange(request_value: dict, response_value: dict) -> None:
    """Append a path-free request/response trace when the approved runner asks.

    The ordinary Wave A harness remains unchanged when the environment variable is
    absent.  The trusted runner independently decodes and hashes every captured
    synthetic blob before it can issue in-memory replay evidence.
    """
    if TRACE_PATH is None:
        return
    blobs: dict[str, dict] = {}
    portable_inputs = []
    for item in request_value["inputs"]:
        sha256, blob = portable_blob(pathlib.Path(item["path"]), item["sha256"])
        blobs.setdefault(sha256, blob)
        portable_inputs.append({key: value for key, value in item.items() if key != "path"} |
                               {"blob_sha256": sha256})
    portable_request = {
        key: value for key, value in request_value.items()
        if key not in {"inputs", "output_dir"}
    }
    portable_request["inputs"] = portable_inputs

    portable_outputs = []
    for item in response_value.get("outputs", []):
        path = pathlib.Path(item["path"])
        sha256, blob = portable_blob(path, item.get("sha256"))
        blobs.setdefault(sha256, blob)
        portable_outputs.append({key: value for key, value in item.items() if key != "path"} |
                                {"blob_sha256": sha256})
    portable_response = {
        key: value for key, value in response_value.items()
        if key not in {"outputs", "diagnostics"}
    }
    portable_response["outputs"] = portable_outputs
    record = {
        "schema_version": 1,
        "case_id": request_value["request_id"],
        "operation_id": request_value["operation"],
        "request": portable_request,
        "request_sha256": canonical_hash(portable_request),
        "response": portable_response,
        "response_sha256": canonical_hash(portable_response),
        "blobs": blobs,
    }
    with pathlib.Path(TRACE_PATH).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False) + "\n")


def artifact(path: pathlib.Path, artifact_id: str, unit: str = "mm") -> dict:
    return {
        "artifact_id": artifact_id,
        "type": "TriangleSurfaceMesh",
        "unit": unit,
        "format": "off",
        "path": str(path.resolve()),
        "sha256": digest(path),
    }


def typed_length(value: float, unit: str = "mm") -> dict:
    return {"value": value, "unit": unit}


def request(
    operation: str,
    inputs: list[dict],
    output_dir: pathlib.Path,
    parameters: dict,
    *,
    request_id: str,
    kernel: str = "package_recommended",
) -> dict:
    return {
        "protocol": 1,
        "request_id": request_id,
        "operation": operation,
        "inputs": inputs,
        "parameters": parameters,
        "output_dir": str(output_dir.resolve()),
        "kernel": kernel,
        "limits": {"wall_time_ms": 120000, "memory_mb": 2048},
    }


def run(worker: str, value: dict, timeout: int = 120) -> dict:
    process = subprocess.run(
        [worker],
        input=json.dumps(value, separators=(",", ":")) + "\n",
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
    )
    lines = process.stdout.splitlines()
    assert process.returncode == 0, (process.returncode, process.stdout, process.stderr)
    assert len(lines) == 1, process.stdout
    assert process.stderr == "", process.stderr
    result = json.loads(lines[0])
    assert result["protocol"] == 1
    assert result["request_id"] == value["request_id"]
    trace_exchange(value, result)
    return result


def assert_error(worker: str, value: dict, code: str) -> None:
    result = run(worker, value)
    assert result["status"] == "error", result
    assert result["error"]["code"] == code, result


def write_off(path: pathlib.Path, vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]]) -> None:
    lines = ["OFF", f"{len(vertices)} {len(faces)} 0"]
    lines.extend(f"{x:.17g} {y:.17g} {z:.17g}" for x, y, z in vertices)
    lines.extend(f"3 {a} {b} {c}" for a, b, c in faces)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def sphere_fixture(subdivisions: int = 2) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices = [
        (1.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -1.0),
    ]
    # Consistent outward winding for an octahedron.
    faces = [
        (0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
        (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5),
    ]
    for _ in range(subdivisions):
        midpoint_cache: dict[tuple[int, int], int] = {}

        def midpoint(first: int, second: int) -> int:
            key = tuple(sorted((first, second)))
            if key in midpoint_cache:
                return midpoint_cache[key]
            a = vertices[first]
            b = vertices[second]
            value = tuple((a[i] + b[i]) * 0.5 for i in range(3))
            length = math.sqrt(sum(component * component for component in value))
            normalized = tuple(component / length for component in value)
            index = len(vertices)
            vertices.append(normalized)
            midpoint_cache[key] = index
            return index

        refined: list[tuple[int, int, int]] = []
        for a, b, c in faces:
            ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
            refined.extend([(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)])
        faces = refined
    return vertices, faces


def grid_fixture(size: int = 6) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices = [(float(x), float(y), 0.0) for y in range(size) for x in range(size)]
    faces: list[tuple[int, int, int]] = []
    for y in range(size - 1):
        for x in range(size - 1):
            a = y * size + x
            b = a + 1
            c = a + size
            d = c + 1
            faces.extend([(a, b, d), (a, d, c)])
    return vertices, faces


def torus_fixture(major_steps: int = 12, minor_steps: int = 8) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices = []
    major_radius, minor_radius = 2.0, 0.6
    for i in range(major_steps):
        u = 2.0 * math.pi * i / major_steps
        for j in range(minor_steps):
            v = 2.0 * math.pi * j / minor_steps
            radius = major_radius + minor_radius * math.cos(v)
            vertices.append((radius * math.cos(u), radius * math.sin(u), minor_radius * math.sin(v)))
    faces: list[tuple[int, int, int]] = []
    for i in range(major_steps):
        for j in range(minor_steps):
            a = i * minor_steps + j
            b = ((i + 1) % major_steps) * minor_steps + j
            c = i * minor_steps + (j + 1) % minor_steps
            d = ((i + 1) % major_steps) * minor_steps + (j + 1) % minor_steps
            faces.extend([(a, b, d), (a, d, c)])
    return vertices, faces


def two_tetrahedra_fixture(reverse_second: bool = False) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    tetra_vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    tetra_faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    vertices = tetra_vertices + [(x + 3.0, y, z) for x, y, z in tetra_vertices]
    second = [(a + 4, b + 4, c + 4) for a, b, c in tetra_faces]
    if reverse_second:
        second = [(a, c, b) for a, b, c in second]
    return vertices, tetra_faces + second


def tetrahedral_cavity_fixture() -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    outer = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0), (0.0, 0.0, 4.0)]
    inner = [(0.5, 0.5, 0.5), (1.0, 0.5, 0.5), (0.5, 1.0, 0.5), (0.5, 0.5, 1.0)]
    outward = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    inward = [(a + 4, c + 4, b + 4) for a, b, c in outward]
    return outer + inner, outward + inward


def base_parameters(policy: str, stop: dict | None = None) -> dict:
    return {
        "policy": policy,
        "stop": stop or {"kind": "edge_ratio", "value": 0.85},
        "preserve_border": True,
        "bounded_normal_change": False,
        "max_symmetric_deviation": typed_length(2.0),
        "hausdorff_error_bound": typed_length(0.01),
    }


def stage(root: pathlib.Path, name: str) -> pathlib.Path:
    directory = root / name
    directory.mkdir()
    return directory


def validate_candidate(
    worker: str,
    root: pathlib.Path,
    name: str,
    candidate: pathlib.Path,
    source: pathlib.Path,
    integrity_parameters: dict | None = None,
    expected_protected_edges: int | None = None,
) -> None:
    integrity = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [artifact(candidate, f"{name}-candidate"), artifact(source, f"{name}-source")],
            stage(root, f"{name}-integrity"),
            integrity_parameters or {"preserve_border": True},
            request_id=f"{name}-integrity",
        ),
    )
    assert integrity["status"] == "ok", integrity
    assert integrity["metrics"]["status"] == "pass", integrity
    assert integrity["metrics"]["component_topology_preserved"] is True, integrity
    if expected_protected_edges is not None:
        assert integrity["metrics"]["protected_edge_count"] == expected_protected_edges, integrity

    hausdorff = run(
        worker,
        request(
            "mesh.distance.symmetric_hausdorff",
            [artifact(source, f"{name}-reference"), artifact(candidate, f"{name}-hausdorff-candidate")],
            stage(root, f"{name}-hausdorff"),
            {"tolerance": typed_length(2.0), "error_bound": typed_length(0.01)},
            request_id=f"{name}-hausdorff",
        ),
    )
    assert hausdorff["status"] == "ok", hausdorff
    assert hausdorff["metrics"]["status"] == "pass", hausdorff


def simplify_fixture(
    worker: str,
    root: pathlib.Path,
    source: pathlib.Path,
    name: str,
    parameters: dict,
    integrity_parameters: dict | None = None,
    expected_protected_edges: int | None = None,
    expect_removal: bool = True,
) -> dict:
    result = run(
        worker,
        request(
            "mesh.simplify.edge_collapse",
            [artifact(source, f"{name}-input")],
            stage(root, f"{name}-simplify"),
            parameters,
            request_id=f"{name}-simplify",
        ),
    )
    assert result["status"] == "ok", result
    assert result["outputs"][0]["slot"] == "geometry", result
    if expect_removal:
        assert result["metrics"]["edges_removed"] > 0, result
        assert result["metrics"]["edges_after"] < result["metrics"]["edges_before"], result
    else:
        assert result["metrics"]["edges_removed"] == 0, result
        assert result["metrics"]["edges_after"] == result["metrics"]["edges_before"], result
    output = pathlib.Path(result["outputs"][0]["path"])
    assert output.is_file(), result
    validate_candidate(
        worker,
        root,
        name,
        output,
        source,
        integrity_parameters,
        expected_protected_edges,
    )
    return result


worker = sys.argv[1]
manifest_process = subprocess.run(
    [worker, "--manifest"],
    text=True,
    encoding="utf-8",
    capture_output=True,
    timeout=20,
)
assert manifest_process.returncode == 0, manifest_process.stderr
assert manifest_process.stderr == "", manifest_process.stderr
manifest = json.loads(manifest_process.stdout)
manifest_operations = {item["id"]: item for item in manifest["operations"]}
for operation_id in (
    "mesh.simplify.edge_collapse",
    "mesh.validate.simplification_integrity",
    "mesh.distance.symmetric_hausdorff",
):
    operation_manifest = manifest_operations[operation_id]
    assert operation_manifest["supported_kernels"] == ["package_recommended"]
    assert operation_manifest["effective_kernel"] == (
        "CGAL::Exact_predicates_inexact_constructions_kernel"
    )
    assert operation_manifest["dependencies"], operation_manifest
    assert operation_manifest["info"], operation_manifest
assert manifest_operations["mesh.simplify.edge_collapse"]["info"]["policies"] == [
    "lindstrom_turk",
    "edge_length_midpoint",
    "gh_plane",
    "gh_triangle",
    "gh_plane_line",
    "gh_probabilistic_plane",
    "gh_probabilistic_triangle",
]
with tempfile.TemporaryDirectory() as folder:
    root = pathlib.Path(folder)
    vertices, faces = sphere_fixture()
    source = root / "sphere.off"
    write_off(source, vertices, faces)

    # Every public cost/placement policy exposed by the adapter has its own
    # transform + integrity + Hausdorff fixture.
    policies = [
        "lindstrom_turk",
        "edge_length_midpoint",
        "gh_plane",
        "gh_triangle",
        "gh_plane_line",
        "gh_probabilistic_plane",
        "gh_probabilistic_triangle",
    ]
    for policy in policies:
        result = simplify_fixture(
            worker, root, source, f"policy-{policy}", base_parameters(policy)
        )
        assert result["metrics"]["policy"] == policy, result

    # Every public stop predicate exposed by the adapter has its own fixture.
    edge_count = len({tuple(sorted((face[i], face[(i + 1) % 3]))) for face in faces for i in range(3)})
    stop_fixtures = {
        "edge_count": {"kind": "edge_count", "value": int(edge_count * 0.9)},
        "edge_ratio": {"kind": "edge_ratio", "value": 0.9},
        "face_count": {"kind": "face_count", "value": int(len(faces) * 0.9)},
        "face_ratio": {"kind": "face_ratio", "value": 0.9},
        "edge_length": {"kind": "edge_length", "value": typed_length(0.45)},
    }
    stop_results = {}
    for stop_name, stop_value in stop_fixtures.items():
        result = simplify_fixture(
            worker,
            root,
            source,
            f"stop-{stop_name}",
            base_parameters("lindstrom_turk", stop_value),
        )
        assert result["metrics"]["stop_policy"] == stop_name, result
        stop_results[stop_name] = result

    # Edge-length stopping is a candidate-cost boundary rather than a final
    # mesh minimum-edge guarantee.  On the identical sphere, a threshold below
    # every input edge must stop immediately, while 0.45 mm performs collapses.
    edge_length_below_minimum = simplify_fixture(
        worker,
        root,
        source,
        "stop-edge_length-below-minimum",
        base_parameters(
            "lindstrom_turk",
            {"kind": "edge_length", "value": typed_length(0.2)},
        ),
        expect_removal=False,
    )
    assert stop_results["edge_length"]["metrics"]["edges_removed"] > 0
    assert edge_length_below_minimum["metrics"]["edges_removed"] == 0

    # Constraint and optional wrapper/filter branches are independently named.
    protected_edge = [faces[0][0], faces[0][1]]
    constraint_parameters = base_parameters("gh_plane_line") | {
        "preserve_border": False,
        "constrained_edges": [protected_edge],
    }
    constrained = simplify_fixture(
        worker,
        root,
        source,
        "constraints",
        constraint_parameters,
        {"preserve_border": False, "constrained_edges": [protected_edge]},
    )
    assert constrained["metrics"]["constrained_edge_count"] == 1, constrained

    # A 6x6 open grid has exactly 20 boundary segments. The fixture must both
    # collapse interior edges and preserve every original boundary segment.
    grid_vertices, grid_faces = grid_fixture(6)
    grid = root / "open-grid.off"
    write_off(grid, grid_vertices, grid_faces)
    border_preserved = simplify_fixture(
        worker,
        root,
        grid,
        "preserve-open-border",
        base_parameters(
            "lindstrom_turk", {"kind": "edge_ratio", "value": 0.7}
        ),
        {"preserve_border": True},
        expected_protected_edges=20,
    )
    assert border_preserved["metrics"]["constrained_edge_count"] == 20, border_preserved

    bounded = simplify_fixture(
        worker,
        root,
        source,
        "bounded-distance",
        base_parameters("gh_plane_line") | {"bounded_distance": typed_length(0.25)},
    )
    assert bounded["metrics"]["bounded_distance_enabled"] is True, bounded

    normal = simplify_fixture(
        worker,
        root,
        source,
        "bounded-normal",
        base_parameters("gh_plane_line") | {"bounded_normal_change": True},
    )
    assert normal["metrics"]["bounded_normal_change_enabled"] is True, normal

    envelope = simplify_fixture(
        worker,
        root,
        source,
        "polyhedral-envelope",
        base_parameters("gh_plane_line") | {"polyhedral_envelope": typed_length(0.25)},
    )
    assert envelope["metrics"]["polyhedral_envelope_enabled"] is True, envelope

    # Tight placement/filter thresholds must demonstrably change behavior, not
    # merely echo an enabled flag.  The shared aggressive control removes most
    # edges; bounded distance and Polyhedral Envelope independently reject every
    # proposed collapse at a 1e-6 mm bound.
    filter_control = simplify_fixture(
        worker,
        root,
        source,
        "filter-control",
        base_parameters("gh_plane_line", {"kind": "edge_ratio", "value": 0.1}),
    )
    bounded_tight = simplify_fixture(
        worker,
        root,
        source,
        "bounded-distance-tight",
        base_parameters("gh_plane_line", {"kind": "edge_ratio", "value": 0.1}) |
        {"bounded_distance": typed_length(1e-6)},
        expect_removal=False,
    )
    envelope_tight = simplify_fixture(
        worker,
        root,
        source,
        "polyhedral-envelope-tight",
        base_parameters("gh_plane_line", {"kind": "edge_ratio", "value": 0.1}) |
        {"polyhedral_envelope": typed_length(1e-6)},
        expect_removal=False,
    )
    assert digest(pathlib.Path(filter_control["outputs"][0]["path"])) != digest(
        pathlib.Path(bounded_tight["outputs"][0]["path"])
    )
    assert digest(pathlib.Path(filter_control["outputs"][0]["path"])) != digest(
        pathlib.Path(envelope_tight["outputs"][0]["path"])
    )

    # A torus gives bounded-normal-change a nontrivial adversarial surface. The
    # moderate 0.2 ratio retains more geometry than the earlier aggressive control;
    # the filter selects a different valid result after the same number of collapses.
    # Identical outputs would prove only parameter echoing.
    guard_vertices, guard_faces = torus_fixture()
    normal_guard = root / "normal-guard-torus.off"
    write_off(normal_guard, guard_vertices, guard_faces)
    normal_control = run(
        worker,
        request(
            "mesh.simplify.edge_collapse",
            [artifact(normal_guard, "bounded-normal-control-input")],
            stage(root, "bounded-normal-control-simplify"),
            base_parameters("gh_triangle", {"kind": "edge_ratio", "value": 0.2}),
            request_id="bounded-normal-control-simplify",
        ),
    )
    assert normal_control["status"] == "ok", normal_control
    assert normal_control["metrics"]["edges_removed"] > 0, normal_control
    normal_control_output = pathlib.Path(normal_control["outputs"][0]["path"])
    validate_candidate(worker, root, "bounded-normal-control", normal_control_output, normal_guard)
    normal_adversarial = simplify_fixture(
        worker,
        root,
        normal_guard,
        "bounded-normal-adversarial",
        base_parameters("gh_triangle", {"kind": "edge_ratio", "value": 0.2}) |
        {"bounded_normal_change": True},
    )
    assert normal_control["metrics"]["edges_removed"] == normal_adversarial["metrics"]["edges_removed"]
    assert digest(normal_control_output) != digest(
        pathlib.Path(normal_adversarial["outputs"][0]["path"])
    )

    # Identical meshes deterministically exercise pass and indeterminate bounds.
    hausdorff_pass = run(
        worker,
        request(
            "mesh.distance.symmetric_hausdorff",
            [artifact(source, "pass-reference"), artifact(source, "pass-candidate")],
            stage(root, "hausdorff-pass"),
            {"tolerance": typed_length(0.02), "error_bound": typed_length(0.01)},
            request_id="hausdorff-pass",
        ),
    )
    assert hausdorff_pass["metrics"]["verdict"] == "pass", hausdorff_pass

    hausdorff_indeterminate = run(
        worker,
        request(
            "mesh.distance.symmetric_hausdorff",
            [artifact(source, "indeterminate-reference"), artifact(source, "indeterminate-candidate")],
            stage(root, "hausdorff-indeterminate"),
            {"tolerance": typed_length(0.005), "error_bound": typed_length(0.01)},
            request_id="hausdorff-indeterminate",
        ),
    )
    assert hausdorff_indeterminate["metrics"]["status"] == "fail", hausdorff_indeterminate
    assert hausdorff_indeterminate["metrics"]["verdict"] == "indeterminate", hausdorff_indeterminate

    shifted = root / "shifted.off"
    write_off(shifted, [(x + 10.0, y, z) for x, y, z in vertices], faces)
    hausdorff_fail = run(
        worker,
        request(
            "mesh.distance.symmetric_hausdorff",
            [artifact(source, "fail-reference"), artifact(shifted, "fail-candidate")],
            stage(root, "hausdorff-fail"),
            {"tolerance": typed_length(1.0), "error_bound": typed_length(0.01)},
            request_id="hausdorff-fail",
        ),
    )
    assert hausdorff_fail["metrics"]["status"] == "fail", hausdorff_fail
    assert hausdorff_fail["metrics"]["verdict"] == "fail", hausdorff_fail

    # Removing one face keeps a readable triangle mesh but must fail topology.
    open_candidate = root / "open.off"
    write_off(open_candidate, vertices, faces[:-1])
    integrity_failure = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [artifact(open_candidate, "open-candidate"), artifact(source, "closed-source")],
            stage(root, "integrity-failure"),
            {"preserve_border": True},
            request_id="integrity-failure",
        ),
    )
    assert integrity_failure["status"] == "error", integrity_failure
    assert integrity_failure["error"]["code"] in {"CLOSEDNESS_CHANGED", "BORDER_COUNT_CHANGED"}, integrity_failure

    # Two open triangles sharing only one vertex form two umbrellas at that
    # vertex. Unlike a closed pinched solid, CGAL's two-manifold OFF reader
    # accepts this minimal graph so the validator branch is exercised.
    non_manifold_vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, -1.0, 0.0),
    ]
    first_tetra_faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    non_manifold = root / "non-manifold-vertex.off"
    write_off(non_manifold, non_manifold_vertices, [(0, 1, 2), (0, 3, 4)])
    non_manifold_failure = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [artifact(non_manifold, "non-manifold-candidate"), artifact(source, "non-manifold-source")],
            stage(root, "non-manifold-failure"),
            {"preserve_border": False},
            request_id="non-manifold-failure",
        ),
    )
    assert non_manifold_failure["status"] == "error", non_manifold_failure
    assert non_manifold_failure["error"]["code"] == "NON_MANIFOLD_VERTEX", non_manifold_failure

    # Disconnected triangle faces crossing in their interiors must reach the
    # Master validator's self-intersection rejection branch.
    crossing = root / "crossing-triangles.off"
    write_off(
        crossing,
        [
            (-1.0, -1.0, 0.0),
            (1.0, -1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, -1.0),
            (0.0, 0.5, 1.0),
            (0.0, -0.5, 1.0),
        ],
        [(0, 1, 2), (3, 4, 5)],
    )
    self_intersection_failure = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [artifact(crossing, "crossing-candidate"), artifact(source, "crossing-source")],
            stage(root, "self-intersection-failure"),
            {"preserve_border": False},
            request_id="self-intersection-failure",
        ),
    )
    assert self_intersection_failure["status"] == "error", self_intersection_failure
    assert self_intersection_failure["error"]["code"] == "SELF_INTERSECTION", self_intersection_failure

    # Removing one otherwise healthy connected component must be rejected
    # independently of topology and distance checks.
    two_component_vertices, two_component_faces = two_tetrahedra_fixture(False)
    two_component_source = root / "two-component-source.off"
    one_component_candidate = root / "one-component-candidate.off"
    write_off(two_component_source, two_component_vertices, two_component_faces)
    write_off(one_component_candidate, two_component_vertices[:4], first_tetra_faces)
    component_failure = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [
                artifact(one_component_candidate, "one-component-candidate"),
                artifact(two_component_source, "two-component-source"),
            ],
            stage(root, "component-count-failure"),
            {"preserve_border": False},
            request_id="component-count-failure",
        ),
    )
    assert component_failure["status"] == "error", component_failure
    assert component_failure["error"]["code"] == "COMPONENT_COUNT_CHANGED", component_failure

    # A nested inward shell is a legal cavity boundary. The validator must
    # preserve that orientation contract rather than forcing every component
    # outward.
    cavity_vertices, cavity_faces = tetrahedral_cavity_fixture()
    cavity = root / "tetrahedral-cavity.off"
    write_off(cavity, cavity_vertices, cavity_faces)
    cavity_validation = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [artifact(cavity, "cavity-candidate"), artifact(cavity, "cavity-source")],
            stage(root, "cavity-validation"),
            {"preserve_border": False},
            request_id="cavity-validation",
        ),
    )
    assert cavity_validation["status"] == "ok", cavity_validation
    assert cavity_validation["metrics"]["bounds_volume"] is True, cavity_validation
    cavity_orientations = {
        item["orientation"]
        for item in cavity_validation["metrics"]["candidate_component_topology"]
    }
    assert cavity_orientations == {"outward", "inward"}, cavity_validation
    cavity_nesting_levels = {
        item["nesting_level"]
        for item in cavity_validation["metrics"]["candidate_component_topology"]
    }
    assert cavity_nesting_levels == {0, 1}, cavity_validation

    # Closed-component volume/orientation checks must be invariant across the
    # full finite coordinate scale, rather than underflowing or overflowing a
    # binary64 volume accumulator.
    for scale_name, coordinate_scale in (("tiny", 1e-200), ("huge", 1e200)):
        scaled_tetra = root / f"{scale_name}-closed-tetra.off"
        scaled_vertices = [
            (0.0, 0.0, 0.0),
            (coordinate_scale, 0.0, 0.0),
            (0.0, coordinate_scale, 0.0),
            (0.0, 0.0, coordinate_scale),
        ]
        write_off(scaled_tetra, scaled_vertices, first_tetra_faces)
        scaled_identity = run(
            worker,
            request(
                "mesh.validate.simplification_integrity",
                [
                    artifact(scaled_tetra, f"{scale_name}-closed-candidate"),
                    artifact(scaled_tetra, f"{scale_name}-closed-source"),
                ],
                stage(root, f"{scale_name}-closed-identity"),
                {"preserve_border": False},
                request_id=f"{scale_name}-closed-identity",
            ),
        )
        assert scaled_identity["status"] == "ok", scaled_identity
        assert scaled_identity["metrics"]["component_topology_preserved"] is True

    # Reversing every shell preserves the unordered {outward, inward} set and
    # identical geometry, but swaps orientation across containment levels.
    # The outer shell must remain outward and the cavity shell inward.
    reversed_cavity = root / "tetrahedral-cavity-all-reversed.off"
    write_off(
        reversed_cavity,
        cavity_vertices,
        [(face[0], face[2], face[1]) for face in cavity_faces],
    )
    reversed_cavity_failure = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [
                artifact(reversed_cavity, "reversed-cavity-candidate"),
                artifact(cavity, "reversed-cavity-source"),
            ],
            stage(root, "reversed-cavity-failure"),
            {"preserve_border": False},
            request_id="reversed-cavity-failure",
        ),
    )
    assert reversed_cavity_failure["status"] == "error", reversed_cavity_failure
    assert (
        reversed_cavity_failure["error"]["code"]
        == "CANDIDATE_INVALID_NESTED_ORIENTATION"
    ), reversed_cavity_failure

    # An open component must not disable containment/orientation checks for
    # the closed subset of a mixed mesh.
    mixed_vertices = cavity_vertices + [
        (10.0, 0.0, 0.0),
        (11.0, 0.0, 0.0),
        (10.0, 1.0, 0.0),
    ]
    open_face = (len(cavity_vertices), len(cavity_vertices) + 1, len(cavity_vertices) + 2)
    mixed_source = root / "mixed-cavity-and-open-source.off"
    mixed_reversed = root / "mixed-cavity-and-open-reversed.off"
    write_off(mixed_source, mixed_vertices, cavity_faces + [open_face])
    write_off(
        mixed_reversed,
        mixed_vertices,
        [(face[0], face[2], face[1]) for face in cavity_faces] + [open_face],
    )
    mixed_orientation_failure = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [
                artifact(mixed_reversed, "mixed-reversed-candidate"),
                artifact(mixed_source, "mixed-valid-source"),
            ],
            stage(root, "mixed-orientation-failure"),
            {"preserve_border": True},
            request_id="mixed-orientation-failure",
        ),
    )
    assert mixed_orientation_failure["status"] == "error", mixed_orientation_failure
    assert (
        mixed_orientation_failure["error"]["code"]
        == "CANDIDATE_INVALID_NESTED_ORIENTATION"
    ), mixed_orientation_failure

    # Open topology alone has no inside/outside predicate. Compare candidate
    # and source normals so a whole-surface winding reversal cannot pass.
    open_square_vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
    ]
    open_square_faces = [(0, 1, 2), (0, 2, 3)]
    open_square = root / "open-square.off"
    reversed_open_square = root / "open-square-reversed.off"
    write_off(open_square, open_square_vertices, open_square_faces)
    write_off(
        reversed_open_square,
        open_square_vertices,
        [(face[0], face[2], face[1]) for face in open_square_faces],
    )
    open_winding_failure = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [
                artifact(reversed_open_square, "reversed-open-candidate"),
                artifact(open_square, "open-source"),
            ],
            stage(root, "open-winding-failure"),
            {"preserve_border": True},
            request_id="open-winding-failure",
        ),
    )
    assert open_winding_failure["status"] == "error", open_winding_failure
    assert (
        open_winding_failure["error"]["code"]
        == "OPEN_SURFACE_WINDING_CHANGED"
    ), open_winding_failure

    # Normal comparison must avoid both cross-product overflow and dot-product
    # underflow while retaining the winding sign.
    huge_open = root / "huge-open-triangle.off"
    huge_open_reversed = root / "huge-open-triangle-reversed.off"
    huge_vertices = [(0.0, 0.0, 0.0), (1e308, 0.0, 0.0), (0.0, 1e308, 0.0)]
    write_off(huge_open, huge_vertices, [(0, 1, 2)])
    write_off(huge_open_reversed, huge_vertices, [(0, 2, 1)])
    huge_winding_failure = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [
                artifact(huge_open_reversed, "huge-reversed-candidate"),
                artifact(huge_open, "huge-open-source"),
            ],
            stage(root, "huge-open-winding-failure"),
            {"preserve_border": True},
            request_id="huge-open-winding-failure",
        ),
    )
    assert huge_winding_failure["status"] == "error", huge_winding_failure
    assert (
        huge_winding_failure["error"]["code"]
        == "OPEN_SURFACE_WINDING_CHANGED"
    ), huge_winding_failure

    tiny_open = root / "tiny-open-triangle.off"
    tiny_vertices = [(0.0, 0.0, 0.0), (1e-200, 0.0, 0.0), (0.0, 1e-200, 0.0)]
    write_off(tiny_open, tiny_vertices, [(0, 1, 2)])
    tiny_winding_identity = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [
                artifact(tiny_open, "tiny-open-candidate"),
                artifact(tiny_open, "tiny-open-source"),
            ],
            stage(root, "tiny-open-winding-identity"),
            {"preserve_border": True},
            request_id="tiny-open-winding-identity",
        ),
    )
    assert tiny_winding_identity["status"] == "ok", tiny_winding_identity
    assert tiny_winding_identity["metrics"]["open_surface_winding_preserved"] is True

    translated_open = root / "translated-open-triangle.off"
    translated_open_reversed = root / "translated-open-triangle-reversed.off"
    translated_vertices = [
        (1e200, 0.0, 0.0),
        (1e200, 1.0, 0.0),
        (1e200, 0.0, 1.0),
    ]
    write_off(translated_open, translated_vertices, [(0, 1, 2)])
    write_off(translated_open_reversed, translated_vertices, [(0, 2, 1)])
    translated_identity = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [
                artifact(translated_open, "translated-open-candidate"),
                artifact(translated_open, "translated-open-source"),
            ],
            stage(root, "translated-open-identity"),
            {"preserve_border": True},
            request_id="translated-open-identity",
        ),
    )
    assert translated_identity["status"] == "ok", translated_identity
    translated_reversal = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [
                artifact(translated_open_reversed, "translated-reversed-candidate"),
                artifact(translated_open, "translated-reversal-source"),
            ],
            stage(root, "translated-open-reversal"),
            {"preserve_border": True},
            request_id="translated-open-reversal",
        ),
    )
    assert translated_reversal["status"] == "error", translated_reversal
    assert (
        translated_reversal["error"]["code"]
        == "OPEN_SURFACE_WINDING_CHANGED"
    ), translated_reversal

    # Component count, border count, and closedness are identical for a sphere
    # and torus; Euler characteristic must reject the genus change.
    torus_vertices, torus_faces = torus_fixture()
    torus = root / "torus.off"
    write_off(torus, torus_vertices, torus_faces)
    topology_failure = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [artifact(torus, "torus-candidate"), artifact(source, "sphere-source")],
            stage(root, "topology-failure"),
            {"preserve_border": False},
            request_id="topology-failure",
        ),
    )
    assert topology_failure["status"] == "error", topology_failure
    assert topology_failure["error"]["code"] == "COMPONENT_TOPOLOGY_CHANGED", topology_failure

    # Hausdorff is orientation-insensitive. Two outward tetrahedra versus the
    # same geometry with one reversed component must pass Hausdorff but fail
    # the integrity orientation/volume contract.
    two_tetra_vertices, two_tetra_faces = two_tetrahedra_fixture(False)
    _, reversed_tetra_faces = two_tetrahedra_fixture(True)
    two_tetra_source = root / "two-tetra-source.off"
    two_tetra_reversed = root / "two-tetra-reversed.off"
    write_off(two_tetra_source, two_tetra_vertices, two_tetra_faces)
    write_off(two_tetra_reversed, two_tetra_vertices, reversed_tetra_faces)
    orientation_hausdorff = run(
        worker,
        request(
            "mesh.distance.symmetric_hausdorff",
            [
                artifact(two_tetra_source, "orientation-reference"),
                artifact(two_tetra_reversed, "orientation-candidate"),
            ],
            stage(root, "orientation-hausdorff"),
            {"tolerance": typed_length(0.02), "error_bound": typed_length(0.01)},
            request_id="orientation-hausdorff",
        ),
    )
    assert orientation_hausdorff["metrics"]["verdict"] == "pass", orientation_hausdorff
    orientation_failure = run(
        worker,
        request(
            "mesh.validate.simplification_integrity",
            [
                artifact(two_tetra_reversed, "reversed-candidate"),
                artifact(two_tetra_source, "outward-source"),
            ],
            stage(root, "orientation-failure"),
            {"preserve_border": False},
            request_id="orientation-failure",
        ),
    )
    assert orientation_failure["status"] == "error", orientation_failure
    assert orientation_failure["error"]["code"] in {
        "CANDIDATE_INVALID_NESTED_ORIENTATION",
        "COMPONENT_TOPOLOGY_CHANGED",
        "CANDIDATE_DOES_NOT_BOUND_VOLUME",
    }, orientation_failure

    bad_policy = base_parameters("does_not_exist")
    assert_error(
        worker,
        request(
            "mesh.simplify.edge_collapse",
            [artifact(source, "bad-policy")],
            stage(root, "bad-policy"),
            bad_policy,
            request_id="bad-policy",
        ),
        "UNKNOWN_SIMPLIFICATION_POLICY",
    )
    assert_error(
        worker,
        request(
            "mesh.simplify.edge_collapse",
            [artifact(source, "bad-kernel")],
            stage(root, "bad-kernel"),
            base_parameters("lindstrom_turk"),
            request_id="bad-kernel",
            kernel="exact_constructions",
        ),
        "UNSUPPORTED_KERNEL",
    )
    assert_error(
        worker,
        request(
            "mesh.simplify.edge_collapse",
            [artifact(source, "bad-unit")],
            stage(root, "bad-unit"),
            base_parameters("lindstrom_turk") | {"bounded_distance": typed_length(1.0, "inch")},
            request_id="bad-unit",
        ),
        "UNSUPPORTED_UNIT",
    )
    assert_error(
        worker,
        request(
            "mesh.simplify.edge_collapse",
            [artifact(source, "bad-constraint")],
            stage(root, "bad-constraint"),
            base_parameters("lindstrom_turk") | {"constrained_edges": [[0, 999999]]},
            request_id="bad-constraint",
        ),
        "INVALID_CONSTRAINT_EDGE",
    )

    # Each typed length parameter must reject a finite source number whose
    # unit conversion overflows binary64 (1e308 m -> mm).
    overflow = typed_length(1e308, "m")
    simplify_overflow_cases = {
        "stop-edge-length": {"stop": {"kind": "edge_length", "value": overflow}},
        "max-deviation": {"max_symmetric_deviation": overflow},
        "hausdorff-bound": {"hausdorff_error_bound": overflow},
        "bounded-distance": {"bounded_distance": overflow},
        "polyhedral-envelope": {"polyhedral_envelope": overflow},
    }
    for overflow_name, update in simplify_overflow_cases.items():
        parameters = base_parameters("lindstrom_turk") | update
        assert_error(
            worker,
            request(
                "mesh.simplify.edge_collapse",
                [artifact(source, f"overflow-{overflow_name}")],
                stage(root, f"overflow-{overflow_name}"),
                parameters,
                request_id=f"overflow-{overflow_name}",
            ),
            "INVALID_TYPED_LENGTH",
        )
    for parameter_name in ("tolerance", "error_bound"):
        parameters = {
            "tolerance": typed_length(1.0),
            "error_bound": typed_length(0.01),
        }
        parameters[parameter_name] = overflow
        assert_error(
            worker,
            request(
                "mesh.distance.symmetric_hausdorff",
                [
                    artifact(source, f"overflow-{parameter_name}-reference"),
                    artifact(source, f"overflow-{parameter_name}-candidate"),
                ],
                stage(root, f"overflow-{parameter_name}"),
                parameters,
                request_id=f"overflow-{parameter_name}",
            ),
            "INVALID_TYPED_LENGTH",
        )

    # Positive lengths must also remain positive after conversion. The
    # smallest binary64 subnormal in mm underflows to zero in metre geometry.
    underflow = typed_length(5e-324, "mm")
    simplify_underflow_cases = {
        "stop-edge-length": {"stop": {"kind": "edge_length", "value": underflow}},
        "hausdorff-bound": {"hausdorff_error_bound": underflow},
        "bounded-distance": {"bounded_distance": underflow},
        "polyhedral-envelope": {"polyhedral_envelope": underflow},
    }
    for underflow_name, update in simplify_underflow_cases.items():
        parameters = base_parameters("lindstrom_turk") | update
        assert_error(
            worker,
            request(
                "mesh.simplify.edge_collapse",
                [artifact(source, f"underflow-{underflow_name}", unit="m")],
                stage(root, f"underflow-{underflow_name}"),
                parameters,
                request_id=f"underflow-{underflow_name}",
            ),
            "INVALID_TYPED_LENGTH",
        )
    assert_error(
        worker,
        request(
            "mesh.distance.symmetric_hausdorff",
            [
                artifact(source, "underflow-error-reference", unit="m"),
                artifact(source, "underflow-error-candidate", unit="m"),
            ],
            stage(root, "underflow-error-bound"),
            {"tolerance": typed_length(1.0, "m"), "error_bound": underflow},
            request_id="underflow-error-bound",
        ),
        "INVALID_TYPED_LENGTH",
    )

print(
    "Wave A: 7 cost/placement policies, 5 stop predicates, constraints, "
    "bounded distance, bounded normal change, Polyhedral Envelope, open-border "
    "preservation, topology/orientation rejection, Hausdorff pass/fail/indeterminate, "
    "unit overflow/underflow, kernels, and invalid inputs: PASS"
)
