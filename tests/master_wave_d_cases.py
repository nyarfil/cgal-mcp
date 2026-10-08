"""Real CGAL 6.2.1 Wave D production-worker cases (family 7.6 meshing/remeshing).

Every transform runs with its mandatory, independent validator. Negative controls
cover tampered candidates, invalid parameters and invalid (non-manifold,
non-triangulated) inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "master" / "wave_d"
QUAD_CUBE = ROOT / "tests" / "fixtures" / "master" / "replay" / "quad_cube.off"
CUBE = ROOT / "tests" / "fixtures" / "master" / "wave_a_boolean" / "cube_a.off"
NONMANIFOLD = ROOT / "tests" / "fixtures" / "master" / "wave_a_repair" / "nonmanifold_vertex.off"
WORKER = sys.argv[1]

TRANSFORMS = {
    "mesh.triangulate.faces": ["mesh.validate.triangulated_faces"],
    "mesh.refine.local": ["mesh.validate.refinement"],
    "mesh.remesh.isotropic": ["mesh.validate.isotropic_remesh"],
    "mesh.remesh.split_long_edges": ["mesh.validate.split_long_edges"],
    "mesh.smooth.tangential_relaxation": ["mesh.validate.tangential_relaxation"],
    "mesh.smooth.shape": ["mesh.validate.shape_smoothing"],
    "mesh.remesh.adaptive": ["mesh.validate.adaptive_remesh"],
}
VALIDATORS = {validator for values in TRANSFORMS.values() for validator in values}
TSM = "TriangleSurfaceMesh"


def mm(value: float) -> dict:
    return {"value": value, "unit": "mm"}


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path: pathlib.Path, type_: str, unit: str = "mm") -> dict:
    return {"artifact_id": path.stem, "type": type_, "unit": unit, "format": "off",
            "path": str(path.resolve()), "sha256": sha256(path)}


COUNTER = [0]


def invoke(scratch: pathlib.Path, operation: str, inputs: list[dict],
           parameters: dict | None = None) -> dict:
    COUNTER[0] += 1
    output = scratch / f"run{COUNTER[0]:03d}"
    output.mkdir()
    request = {"protocol": 1, "request_id": f"wave-d-{COUNTER[0]}", "operation": operation,
               "inputs": inputs, "parameters": parameters or {},
               "output_dir": str(output.resolve()), "kernel": "package_recommended",
               "limits": {"wall_time_ms": 120000, "memory_mb": 2048}}
    process = subprocess.run([WORKER], input=json.dumps(request) + "\n", text=True,
                             encoding="utf-8", capture_output=True, timeout=300)
    assert process.returncode == 0, process.stderr
    assert process.stderr == "", process.stderr
    lines = process.stdout.splitlines()
    assert len(lines) == 1, process.stdout
    result = json.loads(lines[0])
    assert result["request_id"] == request["request_id"], result
    return result


def ok(result: dict) -> tuple[dict, pathlib.Path]:
    assert result["status"] == "ok", result
    output = result["outputs"][0]
    path = pathlib.Path(output["path"])
    assert path.is_file(), result
    return output, path


def error(result: dict, code: str, error_class: str | None = None) -> None:
    assert result["status"] == "error", result
    assert result["error"]["code"] == code, result
    if error_class is not None:
        assert result["error"]["class"] == error_class, result


def rejected(result: dict, check: str) -> None:
    """Validator rejected the candidate and names the failed check."""
    assert result["status"] == "error", result
    assert result["error"]["class"] == "VALIDATION_FAILED", result
    assert result["error"]["code"].endswith("_FAILED"), result
    head = result["error"]["message"].split("|", 1)[0]
    assert check in head.split(), (check, result["error"]["message"][:400])


def read_off(path: pathlib.Path) -> tuple[list[list[float]], list[list[int]]]:
    tokens = path.read_text("ascii").split()
    assert tokens[0] == "OFF"
    nv, nf = int(tokens[1]), int(tokens[2])
    position = 4
    vertices = []
    for _ in range(nv):
        vertices.append([float(value) for value in tokens[position:position + 3]])
        position += 3
    faces = []
    for _ in range(nf):
        degree = int(tokens[position])
        faces.append([int(value) for value in tokens[position + 1:position + 1 + degree]])
        position += 1 + degree
    return vertices, faces


def write_off(path: pathlib.Path, vertices, faces) -> None:
    lines = ["OFF", f"{len(vertices)} {len(faces)} 0"]
    lines += [" ".join(repr(float(c)) for c in vertex) for vertex in vertices]
    lines += [" ".join(str(i) for i in [len(face), *face]) for face in faces]
    path.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def tampered(scratch: pathlib.Path, source: pathlib.Path, mutate) -> dict:
    vertices, faces = read_off(source)
    mutate(vertices, faces)
    COUNTER[0] += 1
    path = scratch / f"tampered{COUNTER[0]:03d}.off"
    write_off(path, vertices, faces)
    return artifact(path, TSM)


def produced(output: dict, path: pathlib.Path) -> dict:
    return {"artifact_id": path.stem, "type": output["type"], "unit": output["unit"],
            "format": output["format"], "path": str(path.resolve()), "sha256": sha256(path)}


def run_pair(scratch, transform, source, parameters, validator, validator_parameters):
    """Run a transform and its mandatory validator; return (report, candidate path, metrics)."""
    result = invoke(scratch, transform, [source], parameters)
    output, path = ok(result)
    assert output["type"] == TSM, output
    validation = invoke(scratch, validator, [produced(output, path), source], validator_parameters)
    _, validation_path = ok(validation)
    report = json.loads(validation_path.read_text("utf-8"))
    assert report["status"] == "pass" and report["passed"] is True, report
    assert report["checks"] and all(report["checks"].values()), report
    return report, path, result["metrics"]


def edge_lengths(path: pathlib.Path) -> list[float]:
    vertices, faces = read_off(path)
    edges = {tuple(sorted((face[i], face[(i + 1) % len(face)])))
             for face in faces for i in range(len(face))}
    return [math.dist(vertices[a], vertices[b]) for a, b in edges]


def main() -> None:
    manifest = json.loads(subprocess.run([WORKER, "--manifest"], text=True, encoding="utf-8",
                                         capture_output=True, timeout=30, check=True).stdout)
    assert manifest["actual_cgal_version"] == "6.2.1", manifest.get("actual_cgal_version")
    operations = {operation["id"]: operation for operation in manifest["operations"]}
    assert set(TRANSFORMS) | VALIDATORS <= operations.keys()
    for operation_id in set(TRANSFORMS) | VALIDATORS:
        entry = operations[operation_id]
        assert entry["revision"] == 1, entry
        assert entry["supported_kernels"] == ["package_recommended"], entry
        assert entry["effective_kernel"] == \
            "CGAL::Exact_predicates_inexact_constructions_kernel", entry
    for transform, validators in TRANSFORMS.items():
        assert operations[transform]["info"]["validators"] == validators, transform
        assert operations[transform]["role"] == "transform", transform
    for validator in VALIDATORS:
        assert operations[validator]["role"] == "validator", validator

    l_prism = artifact(FIXTURES / "l_prism.off", "PolygonSoup3")
    l_hexagon = artifact(FIXTURES / "l_hexagon.off", "PolygonSoup3")
    quad_cube = artifact(QUAD_CUBE, "PolygonSoup3")
    hexadecagon = artifact(FIXTURES / "hexadecagon_fan.off", TSM)
    square_fan = artifact(FIXTURES / "square_fan.off", TSM)
    square2 = artifact(FIXTURES / "square_two_triangles.off", TSM)
    grid3 = artifact(FIXTURES / "grid3_displaced.off", TSM)
    grid5 = artifact(FIXTURES / "grid5_bump.off", TSM)
    sphere = artifact(FIXTURES / "icosphere2.off", TSM)
    noisy = artifact(FIXTURES / "icosphere2_noisy.off", TSM)
    ellipsoid = artifact(FIXTURES / "ellipsoid_3_1_1.off", TSM)
    cube = artifact(CUBE, TSM)
    nonmanifold = artifact(NONMANIFOLD, TSM)

    with tempfile.TemporaryDirectory(prefix="cgal-master-wave-d-") as temporary:
        scratch = pathlib.Path(temporary)

        # --- 7.6.01 triangulation (triangulate_faces / triangulate_face) -------
        tri_paths = {}
        for method in ("triangulate_faces", "triangulate_face"):
            report, path, metrics = run_pair(scratch, "mesh.triangulate.faces", l_prism,
                                             {"method": method},
                                             "mesh.validate.triangulated_faces", {})
            candidate = report["candidate"]
            assert candidate["face_count"] == 20 and candidate["vertex_count"] == 12, candidate
            assert abs(candidate["area"] - 14.0) < 1e-9, candidate
            assert abs(candidate["signed_volume"] - 3.0) < 1e-9, candidate
            assert candidate["closed"] and candidate["euler_characteristic"] == 2, candidate
            tri_paths[method] = path
            report, _, _ = run_pair(scratch, "mesh.triangulate.faces", l_hexagon,
                                    {"method": method}, "mesh.validate.triangulated_faces", {})
            assert report["candidate"]["face_count"] == 4, report
            assert abs(report["candidate"]["area"] - 3.0) < 1e-12, report
        report, _, _ = run_pair(scratch, "mesh.triangulate.faces", quad_cube,
                                {"method": "triangulate_faces"},
                                "mesh.validate.triangulated_faces", {})
        assert report["candidate"]["face_count"] == 12, report
        assert abs(report["candidate"]["signed_volume"] - 1.0) < 1e-12, report
        prism_tris = tri_paths["triangulate_faces"]
        # Tampered: drop a triangle, flip a triangle, move a vertex off the face.
        rejected(invoke(scratch, "mesh.validate.triangulated_faces",
                        [tampered(scratch, prism_tris, lambda v, f: f.pop()), l_prism]),
                 "triangle_count_per_face_is_degree_minus_two")
        rejected(invoke(scratch, "mesh.validate.triangulated_faces",
                        [tampered(scratch, prism_tris, lambda v, f: f[0].reverse()), l_prism]),
                 "triangles_consistently_oriented_with_face")
        rejected(invoke(scratch, "mesh.validate.triangulated_faces",
                        [tampered(scratch, prism_tris,
                                  lambda v, f: v[0].__setitem__(2, -0.25)), l_prism]),
                 "vertices_identical_to_source")
        error(invoke(scratch, "mesh.triangulate.faces", [l_prism], {"method": "ear_clip"}),
              "INVALID_PARAMETER", "INVALID_REQUEST")

        # --- 7.6.02 refinement (refine) ----------------------------------------
        report, refined, metrics = run_pair(
            scratch, "mesh.refine.local", hexadecagon,
            {"density_control_factor": math.sqrt(2), "max_deviation": mm(0.01)},
            "mesh.validate.refinement", {"max_deviation": mm(0.01)})
        assert metrics["inserted_vertices"] == 13 and metrics["new_faces"] == 26, metrics
        candidate = report["candidate"]
        assert candidate["vertex_count"] == 29 and candidate["face_count"] == 40, candidate
        assert abs(candidate["area"] - 32 * math.sin(math.pi / 8)) < 1e-9, candidate
        report3, _, metrics3 = run_pair(
            scratch, "mesh.refine.local", hexadecagon,
            {"density_control_factor": 3.0, "max_deviation": mm(0.01)},
            "mesh.validate.refinement", {"max_deviation": mm(0.01)})
        assert metrics3["inserted_vertices"] > metrics["inserted_vertices"], metrics3
        rejected(invoke(scratch, "mesh.validate.refinement",
                        [tampered(scratch, refined, lambda v, f: v[20].__setitem__(2, 0.5)),
                         hexadecagon], {"max_deviation": mm(0.01)}),
                 "hausdorff_within_max_deviation")
        rejected(invoke(scratch, "mesh.validate.refinement",
                        [tampered(scratch, refined, lambda v, f: v[3].__setitem__(0, v[3][0] * 0.9)),
                         hexadecagon], {"max_deviation": mm(0.01)}),
                 "source_vertices_preserved")
        error(invoke(scratch, "mesh.refine.local", [hexadecagon],
                     {"density_control_factor": 0.0, "max_deviation": mm(0.01)}),
              "INVALID_PARAMETER", "INVALID_REQUEST")

        # --- 7.6.03 isotropic remeshing ----------------------------------------
        report, iso_square, _ = run_pair(
            scratch, "mesh.remesh.isotropic", square_fan,
            {"target_edge_length": mm(0.5), "number_of_iterations": 3,
             "number_of_relaxation_steps": 1, "max_deviation": mm(0.01)},
            "mesh.validate.isotropic_remesh",
            {"target_edge_length": mm(0.5), "max_deviation": mm(0.01)})
        candidate = report["candidate"]
        assert abs(candidate["area"] - 16.0) < 1e-9 and candidate["boundary_loop_count"] == 1
        assert 0.8 * 0.5 <= candidate["mean_edge_length"] <= 4 / 3 * 0.5, candidate
        report, iso_sphere, _ = run_pair(
            scratch, "mesh.remesh.isotropic", sphere,
            {"target_edge_length": mm(0.2), "number_of_iterations": 3,
             "number_of_relaxation_steps": 1, "max_deviation": mm(0.05)},
            "mesh.validate.isotropic_remesh",
            {"target_edge_length": mm(0.2), "max_deviation": mm(0.05)})
        assert report["candidate"]["closed"] and report["candidate"]["euler_characteristic"] == 2
        assert report["candidate"]["face_count"] > 320, report
        run_pair(scratch, "mesh.remesh.isotropic", cube,
                 {"target_edge_length": mm(0.5), "number_of_iterations": 3,
                  "number_of_relaxation_steps": 1, "max_deviation": mm(0.6)},
                 "mesh.validate.isotropic_remesh",
                 {"target_edge_length": mm(0.5), "max_deviation": mm(0.6)})
        # The unremeshed source does not satisfy the target band.
        rejected(invoke(scratch, "mesh.validate.isotropic_remesh", [square_fan, square_fan],
                        {"target_edge_length": mm(0.5), "max_deviation": mm(0.01)}),
                 "edge_lengths_within_target_band")
        rejected(invoke(scratch, "mesh.validate.isotropic_remesh",
                        [tampered(scratch, iso_sphere,
                                  lambda v, f: [p.__setitem__(k, p[k] * 1.1)
                                                for p in v for k in range(3)]), sphere],
                        {"target_edge_length": mm(0.2), "max_deviation": mm(0.05)}),
                 "hausdorff_within_max_deviation")
        rejected(invoke(scratch, "mesh.validate.isotropic_remesh",
                        [tampered(scratch, iso_sphere, lambda v, f: [face.reverse() for face in f]),
                         sphere], {"target_edge_length": mm(0.2), "max_deviation": mm(0.05)}),
                 "orientation_preserved")
        error(invoke(scratch, "mesh.remesh.isotropic", [square_fan],
                     {"target_edge_length": mm(-0.5), "number_of_iterations": 3,
                      "number_of_relaxation_steps": 1, "max_deviation": mm(0.01)}),
              "INVALID_PARAMETER", "INVALID_REQUEST")
        error(invoke(scratch, "mesh.remesh.isotropic", [square_fan],
                     {"target_edge_length": mm(0.5), "number_of_iterations": 0,
                      "number_of_relaxation_steps": 1, "max_deviation": mm(0.01)}),
              "INVALID_PARAMETER", "INVALID_REQUEST")
        result = invoke(scratch, "mesh.remesh.isotropic", [nonmanifold],
                        {"target_edge_length": mm(0.5), "number_of_iterations": 1,
                         "number_of_relaxation_steps": 1, "max_deviation": mm(0.1)})
        assert result["status"] == "error", result
        assert result["error"]["class"] == "PRECONDITION_FAILED", result
        assert result["error"]["code"] in {"NON_MANIFOLD_INPUT", "NON_MANIFOLD_VERTEX"}, result
        error(invoke(scratch, "mesh.remesh.isotropic", [artifact(QUAD_CUBE, TSM)],
                     {"target_edge_length": mm(0.5), "number_of_iterations": 1,
                      "number_of_relaxation_steps": 1, "max_deviation": mm(0.1)}),
              "MESH_NOT_TRIANGULATED", "PRECONDITION_FAILED")

        # --- split_long_edges ----------------------------------------------------
        report, split, _ = run_pair(scratch, "mesh.remesh.split_long_edges", square2,
                                    {"max_length": mm(1.0)}, "mesh.validate.split_long_edges",
                                    {"max_length": mm(1.0)})
        candidate = report["candidate"]
        assert (candidate["vertex_count"], candidate["face_count"]) == (23, 28), candidate
        assert report["longest_subdivided_piece"] <= 1.0 + 1e-12, report
        assert abs(candidate["area"] - 16.0) < 1e-12, candidate
        rejected(invoke(scratch, "mesh.validate.split_long_edges", [square2, square2],
                        {"max_length": mm(1.0)}), "subdivided_pieces_within_max_length")
        rejected(invoke(scratch, "mesh.validate.split_long_edges",
                        [tampered(scratch, split, lambda v, f: v[10].__setitem__(2, 0.3)), square2],
                        {"max_length": mm(1.0)}), "new_vertices_on_source_edges")
        error(invoke(scratch, "mesh.remesh.split_long_edges", [square2], {"max_length": mm(0)}),
              "INVALID_PARAMETER", "INVALID_REQUEST")

        # --- 7.6.04 tangential relaxation / smooth_shape ------------------------
        report, relaxed, _ = run_pair(scratch, "mesh.smooth.tangential_relaxation", grid3,
                                      {"number_of_iterations": 1, "max_deviation": mm(0.01)},
                                      "mesh.validate.tangential_relaxation",
                                      {"max_deviation": mm(0.01)})
        vertices, _ = read_off(relaxed)
        assert all(abs(a - b) < 1e-9 for a, b in zip(vertices[4], (1.0, 1.0, 0.0))), vertices[4]
        assert abs(report["candidate"]["min_angle_degrees"] - 45.0) < 1e-9, report
        rejected(invoke(scratch, "mesh.validate.tangential_relaxation",
                        [tampered(scratch, relaxed, lambda v, f: v[0].__setitem__(0, -0.2)), grid3],
                        {"max_deviation": mm(0.01)}), "boundary_vertices_fixed")
        rejected(invoke(scratch, "mesh.validate.tangential_relaxation",
                        [tampered(scratch, relaxed, lambda v, f: v[4].__setitem__(2, 0.5)), grid3],
                        {"max_deviation": mm(0.01)}), "hausdorff_within_max_deviation")

        report, smoothed, _ = run_pair(
            scratch, "mesh.smooth.shape", grid5,
            {"time_step": 0.01, "number_of_iterations": 1, "preserve_volume": False,
             "max_deviation": mm(1.0)},
            "mesh.validate.shape_smoothing", {"max_deviation": mm(1.0), "preserve_volume": False})
        rough = report["umbrella_roughness"]
        assert rough["candidate"] < rough["source"], rough
        report, smooth_sphere, _ = run_pair(
            scratch, "mesh.smooth.shape", noisy,
            {"time_step": 0.01, "number_of_iterations": 1, "preserve_volume": True,
             "max_deviation": mm(0.2)},
            "mesh.validate.shape_smoothing", {"max_deviation": mm(0.2), "preserve_volume": True})
        assert abs(report["candidate"]["signed_volume"] - report["source"]["signed_volume"]) \
            <= 1e-9 * abs(report["source"]["signed_volume"]), report
        rejected(invoke(scratch, "mesh.validate.shape_smoothing", [grid5, grid5],
                        {"max_deviation": mm(1.0), "preserve_volume": False}), "roughness_reduced")
        rejected(invoke(scratch, "mesh.validate.shape_smoothing",
                        [tampered(scratch, smooth_sphere,
                                  lambda v, f: [p.__setitem__(k, p[k] * 1.01)
                                                for p in v for k in range(3)]), noisy],
                        {"max_deviation": mm(0.2), "preserve_volume": True}), "volume_preserved")
        rejected(invoke(scratch, "mesh.validate.shape_smoothing",
                        [tampered(scratch, smoothed, lambda v, f: v[0].__setitem__(2, 0.1)), grid5],
                        {"max_deviation": mm(1.0), "preserve_volume": False}),
                 "boundary_vertices_fixed")
        error(invoke(scratch, "mesh.smooth.shape", [grid5],
                     {"time_step": 0.01, "number_of_iterations": 1, "preserve_volume": True,
                      "max_deviation": mm(1.0)}),
              "VOLUME_REQUIRES_CLOSED_MESH", "PRECONDITION_FAILED")
        error(invoke(scratch, "mesh.smooth.shape", [grid5],
                     {"time_step": -1.0, "number_of_iterations": 1, "preserve_volume": False,
                      "max_deviation": mm(1.0)}),
              "INVALID_PARAMETER", "INVALID_REQUEST")

        # --- 7.6.05 adaptive remeshing (Adaptive_sizing_field) -------------------
        adaptive = {}
        for mode in ("isotropic_remeshing", "split_long_edges"):
            params = {"tolerance": mm(0.005), "min_edge_length": mm(0.1),
                      "max_edge_length": mm(0.6), "mode": mode, "number_of_iterations": 3,
                      "max_deviation": mm(0.05)}
            report, path, _ = run_pair(
                scratch, "mesh.remesh.adaptive", ellipsoid, params, "mesh.validate.adaptive_remesh",
                {key: params[key] for key in ("tolerance", "min_edge_length", "max_edge_length",
                                              "mode", "max_deviation")})
            follow = report["sizing_follow"]
            assert not follow["correlation_required"] or follow["log_correlation"] >= 0.5, follow
            assert follow["edge_over_target_p95"] <= (2.25 if mode == "split_long_edges" else 1.75), follow
            adaptive[mode] = path
        # Adaptivity: curvature-driven sizing yields a wider edge-length spread than a
        # uniform remesh of the same input at a comparable mean length.
        lengths = edge_lengths(adaptive["isotropic_remeshing"])
        mean = sum(lengths) / len(lengths)
        _, uniform, _ = run_pair(
            scratch, "mesh.remesh.isotropic", ellipsoid,
            {"target_edge_length": mm(mean), "number_of_iterations": 3,
             "number_of_relaxation_steps": 3, "max_deviation": mm(0.1)},
            "mesh.validate.isotropic_remesh",
            {"target_edge_length": mm(mean), "max_deviation": mm(0.1)})
        uniform_lengths = edge_lengths(uniform)
        spread = max(lengths) / min(lengths)
        uniform_spread = max(uniform_lengths) / min(uniform_lengths)
        assert spread > uniform_spread, (spread, uniform_spread)
        adaptive_params = {"tolerance": mm(0.005), "min_edge_length": mm(0.1), "max_edge_length": mm(0.6),
                           "mode": "isotropic_remeshing", "max_deviation": mm(0.05)}
        # Negative controls on the strongly curved oblate spheroid (field contrast > 1.5):
        # uniform remeshes are valid isotropic remeshes but ignore curvature.
        oblate = artifact(FIXTURES / "oblate_spheroid.off", TSM)
        oblate_params = {"tolerance": mm(0.01), "min_edge_length": mm(0.1),
                         "max_edge_length": mm(0.8), "mode": "isotropic_remeshing",
                         "max_deviation": mm(0.05)}
        for target in (0.1, 0.3):
            _, uniform_oblate, _ = run_pair(
                scratch, "mesh.remesh.isotropic", oblate,
                {"target_edge_length": mm(target), "number_of_iterations": 3,
                 "number_of_relaxation_steps": 3, "max_deviation": mm(0.3)},
                "mesh.validate.isotropic_remesh",
                {"target_edge_length": mm(target), "max_deviation": mm(0.3)})
            rejected(invoke(scratch, "mesh.validate.adaptive_remesh", [tampered(scratch, uniform_oblate, lambda v, f: None), oblate],
                            oblate_params), "edges_follow_curvature_sizing")
        genuine_report, genuine_oblate, _ = run_pair(
            scratch, "mesh.remesh.adaptive", oblate,
            dict(oblate_params, number_of_iterations=3),
            "mesh.validate.adaptive_remesh", oblate_params)
        assert genuine_report["sizing_follow"]["correlation_required"], genuine_report
        rejected(invoke(scratch, "mesh.validate.adaptive_remesh",
                        [tampered(scratch, genuine_oblate, lambda v, f: None), oblate],
                        dict(oblate_params, tolerance=mm(0.0001))), "edges_follow_curvature_sizing")
        rejected(invoke(scratch, "mesh.validate.adaptive_remesh",
                        [tampered(scratch, adaptive["isotropic_remeshing"],
                                  lambda v, f: v[0].__setitem__(0, v[0][0] + 0.5)), ellipsoid],
                        adaptive_params), "hausdorff_within_max_deviation")
        rejected(invoke(scratch, "mesh.validate.adaptive_remesh",
                        [tampered(scratch, adaptive["split_long_edges"],
                                  lambda v, f: v[200].__setitem__(1, v[200][1] + 0.01)), ellipsoid],
                        dict(adaptive_params, mode="split_long_edges")),
                 "new_vertices_on_source_edges")
        error(invoke(scratch, "mesh.remesh.adaptive", [ellipsoid],
                     {"tolerance": mm(0.005), "min_edge_length": mm(0.6),
                      "max_edge_length": mm(0.1), "mode": "isotropic_remeshing",
                      "number_of_iterations": 3, "max_deviation": mm(0.05)}),
              "INVALID_PARAMETER", "INVALID_REQUEST")
        error(invoke(scratch, "mesh.remesh.adaptive", [ellipsoid],
                     {"tolerance": mm(0.005), "min_edge_length": mm(0.1),
                      "max_edge_length": mm(0.6), "mode": "loop_subdivision",
                      "number_of_iterations": 3, "max_deviation": mm(0.05)}),
              "INVALID_PARAMETER", "INVALID_REQUEST")
        # Validators reject candidates with a different unit than the source.
        error(invoke(scratch, "mesh.validate.isotropic_remesh",
                     [artifact(pathlib.Path(iso_square), TSM, unit="cm"), square_fan],
                     {"target_edge_length": mm(0.5), "max_deviation": mm(0.01)}),
              "UNIT_MISMATCH", "TYPE_ERROR")
    print("PASS master Wave D worker cases")


if __name__ == "__main__":
    main()
