"""Data-declared replay case sets for original major-capability families.

One replay mechanism (``scripts/replay_master_capabilities.py``) executes every
family. Each family below declares, as data only:

* the requirements it binds, with the validated operations and the inventory
  subcapability symbols each bound requirement is held to;
* the requirements it deliberately leaves unbound, with the precise gap;
* positive cases (fixture, operation, parameters, behavioural assertions);
* paired-case checks and expected-rejection negative controls.

Mandatory validators are never listed here: they are derived from the
operation registry (``validation.validators`` and ``validation.bindings``) so a
case cannot skip or substitute a validator. Assertions use a closed vocabulary
of selectors/measures implemented below; no case can name code to execute.

Wave A simplification (7.7) keeps its bespoke contract in
``scripts/master_acceptance.py`` and is registered as a family by the replay
runner.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
from typing import Any

FIXTURE_ROOT = "tests/fixtures/master"
FAMILY_HARNESS_PATH = "tests/master_family_replay_cases.py"
FAMILY_CONTRACT_PATH = "scripts/master_replay_families.py"
STANDALONE_UNMET_GATES = (
    "remaining_major_capability_requirements",
    "search_and_retrieval_acceptance",
    "multi_operation_workflow_acceptance",
    "host_compatibility_matrix",
    "performance_resource_and_robustness_acceptance",
)
BINDING_RULE = (
    "A requirement is bound only when replayed cases exercise every enumerated "
    "variant in its original description and every subcapability symbol listed for "
    "it in catalog/major_capability_inventory.json, each through a VALIDATED "
    "operation whose registry-mandated validators pass."
)

TETRA = {"fixture": "wave_a_repair/tetra_outward.off",
         "sha256": "9713f92b295f8c4769d2cb8a1ea793ffff044e0689b1a760556daca497ff8c70"}
OPEN_TETRA = {"fixture": "wave_a_repair/open_tetra_hole.off",
              "sha256": "efb1b639be9862e629614ec53e3dabf3b2f8c6829746f0598755f1e5ae82cbd3"}
QUAD_CUBE = {"fixture": "replay/quad_cube.off",
             "sha256": "3eb508791f4ae9b98a6435b01e7e7d336283ff3b683c1158a0a46ef612049720"}
INTERSECTING = {"fixture": "replay/intersecting_tetrahedra.off",
                "sha256": "088c0fb78e5c559dfa809c899cb0b4a51be6034fe1bfe3cd380e652963203287"}
CUBE_A = {"fixture": "wave_a_boolean/cube_a.off",
          "sha256": "727bedd5d13712e7506e15aeb1ea35b5da660bf2143bf28e8f257b0aa7eb2164"}
CUBE_OVERLAP = {"fixture": "wave_a_boolean/cube_overlap.off",
                "sha256": "76773013b165e44ba4f7668144a74ea31cb43fc61bd102d3d368f16ca4adc7c9"}
CUBE_CONTAINED = {"fixture": "wave_a_boolean/cube_contained.off",
                  "sha256": "857398dc1af0ff7c938c08c2ebdb7e00352f73a571d6f6fbaa3ad4913c01a5fa"}
CUBE_DISJOINT = {"fixture": "wave_a_boolean/cube_disjoint.off",
                 "sha256": "6663ab0ca3e8b2cbf6965eb22f29b84ef47fa2114a180283720d73cebda9fdce"}
OPEN_CUBE = {"fixture": "wave_a_boolean/open_cube.off",
             "sha256": "8d4361aaa4b58509192dd35df2ddc7f0a735f84339825532f2c0ba22be0bc242"}
INWARD_CUBE = {"fixture": "wave_a_boolean/inward_cube.off",
               "sha256": "b61488ba67892f3859b0f6180b096182c626149e7ba435215286cb2c2dba62ea"}
FLIPPED_SOUP = {"fixture": "wave_a_repair/tetra_flipped_soup.off",
                "sha256": "c363f3006ae2317b0dd94ee94fcdf31d2307588ea8d267e9dd2266b17413eed3"}
SEAM = {"fixture": "wave_a_repair/duplicated_seam.off",
        "sha256": "38ac49cb0fbd26449c1da56a4c40ce87a48480cc2b0a724f2c49af1c774e8eb1"}
DEGENERATE_FACE = {"fixture": "wave_a_repair/degenerate_face.off",
                   "sha256": "3976347b4e7744f4de6d41c7475eeda7198e5973dd6cbc881e0fb9c7b9c603f3"}
ZERO_EDGE = {"fixture": "replay/zero_length_edge_soup.off",
             "sha256": "c2006933f1f2dfc036143728701adf7b7422b28e7acbafe44fe6e110db37ae25"}
DIRTY_SOUP = {"fixture": "wave_a_repair/dirty_polygon_soup.off",
              "sha256": "9f246dfd058ef36fe5bf0a3371513dbbfa130f36ae42ace4850362ecea155211"}
DUPLICATE_FACES = {"fixture": "wave_a_repair/duplicate_faces.off",
                   "sha256": "7491fcba50478cd654dd8f291379ddfae26e5f14532b17d51367ca8bad16b1ea"}
NONMANIFOLD = {"fixture": "wave_a_repair/nonmanifold_vertex.off",
               "sha256": "699a11b36d882ee67a5e7efd90eb1149aed8431d8719c5bccadc6a6cb7cea409"}
PLANE = {"fixture": "replay/noisy_plane_without_outlier.xyz",
         "sha256": "57913bba9ace858b3c8925f7abf7b5c2009dea1faca0a204eeba477edd0653be"}
NOISY_PLANE = {"fixture": "wave_b/noisy_plane_with_outlier.xyz",
               "sha256": "5ce0758c1f9d9c0d59c80b567982ccf93f8c5df7f75cb6dc4f85430f75adc452"}
ALTERNATING = {"fixture": "wave_b/plane_normals_alternating.ply",
               "sha256": "19a42b0881ce6a9d437026a0858302da91602a2296c5cd93149056d44670691e"}


def _mesh(fixture: dict, type_: str = "TriangleSurfaceMesh") -> dict:
    return {**fixture, "type": type_, "format": "off", "unit": "mm"}


def _points(fixture: dict, type_: str = "PointSet3", format_: str = "xyz") -> dict:
    return {**fixture, "type": type_, "format": format_, "unit": "mm"}


def _case(case_id: str, operation: str, inputs: list[dict], parameters: dict,
          assertions: list[list]) -> dict:
    return {"id": case_id, "operation": operation, "inputs": inputs,
            "parameters": parameters, "assertions": assertions}


SQRT3_HALF = math.sqrt(3.0) / 2.0

SQRT3_INV = 1.0 / math.sqrt(3.0)
# Hand-derived from the cube_a.off geometry (0..2 axis-aligned cube, outward winding):
# per-face outward axis normals in file order, and vertex normals along the corner diagonals.
CUBE_FACE_NORMALS = [
    [0.0, 0.0, -1.0],
    [0.0, 0.0, -1.0],
    [0.0, 0.0, 1.0],
    [0.0, 0.0, 1.0],
    [0.0, -1.0, 0.0],
    [0.0, -1.0, 0.0],
    [1.0, 0.0, 0.0],
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 1.0, 0.0],
    [-1.0, 0.0, 0.0],
    [-1.0, 0.0, 0.0],
]
CUBE_VERTEX_NORMALS = [[c * SQRT3_INV for c in corner] for corner in [
    [-1.0, -1.0, -1.0],
    [1.0, -1.0, -1.0],
    [1.0, 1.0, -1.0],
    [-1.0, 1.0, -1.0],
    [-1.0, -1.0, 1.0],
    [1.0, -1.0, 1.0],
    [1.0, 1.0, 1.0],
    [-1.0, 1.0, 1.0],
]]
INWARD_FACE_NORMALS = [[-c if c else 0.0 for c in normal] for normal in CUBE_FACE_NORMALS]
INWARD_VERTEX_NORMALS = [[-c if c else 0.0 for c in normal] for normal in CUBE_VERTEX_NORMALS]

FAMILY_7_3 = {
    "family": "7.3",
    "scope": "family_7_3_polygon_mesh_processing_core_partial",
    "evidence_path": "docs/master/evidence/family-7.3-capabilities.json",
    "test_id": "family-7.3-replay-cases",
    "requirements": {
        "major.7.3.01": {
            "operation_ids": ["mesh.inspect.pmp", "mesh.analysis.self_intersections"],
            "symbols": ["does_self_intersect", "is_closed", "is_triangle_mesh"],
            "case_ids": ["inspect-closed-tetra", "inspect-open-tetra", "inspect-quad-cube",
                         "self-intersection-free-tetra", "self-intersecting-tetrahedra"],
        },
        "major.7.3.03": {
            "operation_ids": ["mesh.analysis.normals"],
            "symbols": ["compute_face_normals", "compute_vertex_normals", "compute_normals"],
            "symbol_notes": "CGAL 6.2.1 compute_normal.h compute_normals() calls "
                            "compute_face_normals() and compute_vertex_normals(); counts and the "
                            "exact per-face/per-vertex values on the axis-aligned cube (and the "
                            "negated values on its inward-wound twin) are asserted by the replay "
                            "harness against hand-derived constants. The mandatory validator "
                            "re-runs the same worker code and is a consistency check only, not "
                            "an independent oracle.",
            "case_ids": ["normals-tetra", "normals-cube", "normals-inward-cube"],
        },
        "major.7.3.04": {
            "operation_ids": ["mesh.analysis.measures"],
            "symbols": ["area", "volume", "centroid"],
            "case_ids": ["measures-tetra", "measures-cube"],
        },
    },
    "unbound": {
        "major.7.3.02": "mesh.analysis.connected_components labels/counts components only; "
                        "connected_component (single-component extraction) and "
                        "keep_largest_connected_components are not exposed.",
        "major.7.3.05": "mesh.analysis.sharp_features exposes detect_sharp_edges only; "
                        "sharp_edges_segmentation is not exposed.",
        "major.7.3.06": "Only bounded_error_symmetric_Hausdorff_distance is executable, as the "
                        "simplification validator; sample_triangle_mesh, max_distance_to_triangle_mesh, "
                        "approximate/one-sided Hausdorff and approximate_max_distance_to_point_set "
                        "are not exposed.",
        "major.7.3.07": "Self-intersection (self_intersections, does_self_intersect) is replayed, but "
                        "intersections between two meshes (do_intersect/surface_intersection) are not "
                        "an executable operation.",
        "major.7.3.08": "No validated location operation (locate, locate_with_AABB_tree).",
    },
    "cases": [
        _case("inspect-closed-tetra", "mesh.inspect.pmp", [_mesh(TETRA)], {}, [
            ["output:analysis:json:mesh_summary.closed", "==", True],
            ["output:analysis:json:mesh_summary.triangulated", "==", True],
            ["output:analysis:json:results.polygon_mesh_valid", "==", True],
        ]),
        _case("inspect-open-tetra", "mesh.inspect.pmp", [_mesh(OPEN_TETRA)], {}, [
            ["output:analysis:json:mesh_summary.closed", "==", False],
            ["output:analysis:json:mesh_summary.triangulated", "==", True],
            ["input:mesh:measure:off.boundary_edge_count", "==", 3],
        ]),
        _case("inspect-quad-cube", "mesh.inspect.pmp", [_mesh(QUAD_CUBE, "PolygonSoup3")], {}, [
            ["output:analysis:json:mesh_summary.closed", "==", True],
            ["output:analysis:json:mesh_summary.triangulated", "==", False],
            ["input:mesh:measure:off.max_face_degree", "==", 4],
        ]),
        _case("self-intersection-free-tetra", "mesh.analysis.self_intersections",
              [_mesh(TETRA)], {}, [
            ["output:analysis:json:results.does_self_intersect", "==", False],
            ["output:analysis:json:results.intersection_pair_count", "==", 0],
        ]),
        _case("self-intersecting-tetrahedra", "mesh.analysis.self_intersections",
              [_mesh(INTERSECTING)], {}, [
            ["output:analysis:json:results.does_self_intersect", "==", True],
            ["output:analysis:json:results.intersection_pair_count", ">", 0],
            ["output:analysis:json:mesh_summary.closed", "==", True],
        ]),
        _case("normals-tetra", "mesh.analysis.normals", [_mesh(TETRA)], {}, [
            ["metrics.face_normal_count", "==", 4],
            ["metrics.vertex_normal_count", "==", 4],
            ["metrics.zero_face_normal_count", "==", 0],
            ["metrics.zero_vertex_normal_count", "==", 0],
        ]),
        _case("normals-cube", "mesh.analysis.normals", [_mesh(CUBE_A)], {}, [
            ["metrics.face_normal_count", "==", 12],
            ["metrics.vertex_normal_count", "==", 8],
            ["metrics.zero_face_normal_count", "==", 0],
            ["metrics.zero_vertex_normal_count", "==", 0],
            ["output:analysis:json:results.face_normals[*].normal.value", "approx",
             [CUBE_FACE_NORMALS, 1e-9]],
            ["output:analysis:json:results.vertex_normals[*].normal.value", "approx",
             [CUBE_VERTEX_NORMALS, 1e-9]],
            ["input:mesh:measure:off.signed_volume", "approx", [8.0, 1e-12]],
        ]),
        # Orientation negative control: the same cube with inward winding must report the
        # exactly negated normals, so flipped or sign-wrong normals cannot satisfy both cases.
        _case("normals-inward-cube", "mesh.analysis.normals", [_mesh(INWARD_CUBE)], {}, [
            ["input:mesh:measure:off.signed_volume", "approx", [-8.0, 1e-12]],
            ["output:analysis:json:results.face_normals[*].normal.value", "approx",
             [INWARD_FACE_NORMALS, 1e-9]],
            ["output:analysis:json:results.vertex_normals[*].normal.value", "approx",
             [INWARD_VERTEX_NORMALS, 1e-9]],
        ]),
        _case("measures-tetra", "mesh.analysis.measures", [_mesh(TETRA)], {}, [
            ["output:analysis:json:results.surface_area.value", "approx", [1.5 + SQRT3_HALF, 1e-12]],
            ["output:analysis:json:results.surface_area.unit", "==", "mm^2"],
            ["output:analysis:json:results.signed_volume.value", "approx", [1.0 / 6.0, 1e-12]],
            ["output:analysis:json:results.signed_volume.unit", "==", "mm^3"],
            ["output:analysis:json:results.volume_centroid.value", "approx", [[0.25, 0.25, 0.25], 1e-12]],
            ["input:mesh:measure:off.signed_volume", "approx", [1.0 / 6.0, 1e-12]],
        ]),
        _case("measures-cube", "mesh.analysis.measures", [_mesh(CUBE_A)], {}, [
            ["output:analysis:json:results.surface_area.value", "approx", [24.0, 1e-12]],
            ["output:analysis:json:results.signed_volume.value", "approx", [8.0, 1e-12]],
            ["output:analysis:json:results.volume_centroid.value", "approx", [[1.0, 1.0, 1.0], 1e-12]],
            ["output:analysis:json:results.volume_centroid.unit", "==", "mm"],
        ]),
    ],
    "pairs": [],
    "negative_controls": [],
}

_REPAIR_UNCHANGED_UNIT = ["output:geometry:sha256", "!=", {"path": "input:source:sha256"}]

FAMILY_7_4 = {
    "family": "7.4",
    "scope": "family_7_4_mesh_repair_partial",
    "evidence_path": "docs/master/evidence/family-7.4-capabilities.json",
    "test_id": "family-7.4-replay-cases",
    "requirements": {
        "major.7.4.01": {
            "operation_ids": ["mesh.repair.orient"],
            "symbols": ["orient_to_bound_a_volume", "orient_polygon_soup"],
            "case_ids": ["orient-flipped-soup", "orient-inward-cube"],
        },
        "major.7.4.02": {
            "operation_ids": ["mesh.repair.stitch_borders"],
            "symbols": ["stitch_borders"],
            "case_ids": ["stitch-duplicated-seam"],
        },
        "major.7.4.03": {
            "operation_ids": ["mesh.repair.remove_degenerate"],
            "symbols": ["remove_degenerate_faces", "remove_degenerate_edges"],
            "case_ids": ["degenerate-collinear-face", "degenerate-zero-length-edge"],
        },
        "major.7.4.05": {
            "operation_ids": ["mesh.repair.polygon_soup"],
            "symbols": ["repair_polygon_soup"],
            "case_ids": ["soup-dirty-keep-one", "soup-duplicates-keep-one",
                         "soup-duplicates-erase-all"],
        },
        "major.7.4.06": {
            "operation_ids": ["mesh.repair.manifold_preprocess"],
            "symbols": ["duplicate_non_manifold_vertices", "non_manifold_vertices"],
            "symbol_notes": "CGAL 6.2.1 manifoldness.h duplicate_non_manifold_vertices() collects "
                            "cones through non_manifold_vertices(); the case asserts one repaired "
                            "non-manifold group and a manifold closed candidate.",
            "case_ids": ["manifold-pinched-vertex"],
        },
    },
    "unbound": {
        "major.7.4.04": "mesh.repair.fill_holes calls triangulate_hole only; "
                        "triangulate_refine_and_fair_hole (refinement/fairing) is not exposed.",
    },
    "cases": [
        _case("orient-flipped-soup", "mesh.repair.orient", [_mesh(FLIPPED_SOUP, "PolygonSoup3")], {}, [
            ["metrics.orientation_changed", "==", True],
            ["metrics.candidate.mesh.closed", "==", True],
            ["metrics.candidate.mesh.outward_oriented", "==", True],
            ["metrics.source.polygon_mesh_constructible", "==", False],
            ["output:geometry:measure:off.signed_volume", "approx", [1.0 / 6.0, 1e-12]],
            _REPAIR_UNCHANGED_UNIT,
        ]),
        _case("orient-inward-cube", "mesh.repair.orient", [_mesh(INWARD_CUBE, "PolygonSoup3")], {}, [
            ["metrics.orientation_changed", "==", True],
            ["metrics.source.mesh.outward_oriented", "==", False],
            ["metrics.candidate.mesh.outward_oriented", "==", True],
            ["input:source:measure:off.signed_volume", "approx", [-8.0, 1e-12]],
            ["output:geometry:measure:off.signed_volume", "approx", [8.0, 1e-12]],
        ]),
        _case("stitch-duplicated-seam", "mesh.repair.stitch_borders", [_mesh(SEAM)], {}, [
            ["metrics.stitched_pair_count", ">=", 1],
            ["input:source:measure:off.vertex_count", "==", 6],
            ["output:geometry:measure:off.vertex_count", "==", 4],
            ["output:geometry:measure:off.boundary_edge_count", "==", 4],
            ["input:source:measure:off.boundary_edge_count", "==", 6],
        ]),
        _case("degenerate-collinear-face", "mesh.repair.remove_degenerate",
              [_mesh(DEGENERATE_FACE, "PolygonSoup3")], {}, [
            ["metrics.source.degenerate_face_count", "==", 1],
            ["metrics.candidate.degenerate_face_count", "==", 0],
            ["metrics.remove_degenerate_faces_complete", "==", True],
            ["metrics.remove_degenerate_edges_complete", "==", True],
            ["output:geometry:measure:off.face_count", "==", 4],
        ]),
        _case("degenerate-zero-length-edge", "mesh.repair.remove_degenerate",
              [_mesh(ZERO_EDGE, "PolygonSoup3")], {}, [
            ["input:source:measure:off.min_edge_length", "==", 0.0],
            ["metrics.source.degenerate_face_count", "==", 2],
            ["metrics.source.duplicate_point_count", "==", 1],
            ["metrics.candidate.degenerate_face_count", "==", 0],
            ["metrics.candidate.mesh.closed", "==", True],
            ["metrics.remove_degenerate_edges_complete", "==", True],
            ["output:geometry:measure:off.min_edge_length", ">", 0.0],
            ["output:geometry:measure:off.vertex_count", "==", 4],
            ["output:geometry:measure:off.signed_volume", "approx", [1.0 / 6.0, 1e-12]],
        ]),
        _case("soup-dirty-keep-one", "mesh.repair.polygon_soup",
              [_mesh(DIRTY_SOUP, "PolygonSoup3")],
              {"duplicate_polygon_policy": "keep_one", "require_same_orientation": False}, [
            ["metrics.source.duplicate_point_count", ">", 0],
            ["metrics.source.degenerate_face_count", ">", 0],
            ["metrics.candidate.duplicate_point_count", "==", 0],
            ["metrics.candidate.degenerate_face_count", "==", 0],
            ["metrics.candidate.duplicate_face_count", "==", 0],
            ["metrics.candidate.unused_point_count", "==", 0],
        ]),
        _case("soup-duplicates-keep-one", "mesh.repair.polygon_soup",
              [_mesh(DUPLICATE_FACES, "PolygonSoup3")],
              {"duplicate_polygon_policy": "keep_one", "require_same_orientation": False}, [
            ["metrics.source.face_count", "==", 3],
            ["metrics.candidate.duplicate_face_count", "==", 0],
            ["metrics.candidate.face_count", "==", 2],
        ]),
        _case("soup-duplicates-erase-all", "mesh.repair.polygon_soup",
              [_mesh(DUPLICATE_FACES, "PolygonSoup3")],
              {"duplicate_polygon_policy": "erase_all", "require_same_orientation": False}, [
            ["metrics.candidate.duplicate_face_count", "==", 0],
            ["metrics.candidate.face_count", "==", 1],
        ]),
        _case("manifold-pinched-vertex", "mesh.repair.manifold_preprocess", [_mesh(NONMANIFOLD)], {}, [
            ["metrics.source.polygon_mesh_constructible", "==", False],
            ["metrics.repaired_vertex_group_count", "==", 1],
            ["metrics.candidate.mesh.closed", "==", True],
            ["metrics.candidate.mesh.non_manifold_vertex_count", "==", 0],
            ["metrics.duplicated_vertex_count", "==", 1],
            ["input:source:measure:off.vertex_count", "==", 7],
            ["output:geometry:measure:off.vertex_count", "==", 8],
        ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["soup-duplicates-keep-one", "soup-duplicates-erase-all"]},
    ],
    "negative_controls": [],
}

FAMILY_7_5 = {
    "family": "7.5",
    "scope": "family_7_5_boolean_operations_partial",
    "evidence_path": "docs/master/evidence/family-7.5-capabilities.json",
    "test_id": "family-7.5-replay-cases",
    "requirements": {
        "major.7.5.02": {
            "operation_ids": ["mesh.boolean.union", "mesh.boolean.intersection",
                              "mesh.boolean.difference"],
            "symbols": ["corefine_and_compute_union", "corefine_and_compute_intersection",
                        "corefine_and_compute_difference"],
            "case_ids": ["union-overlap", "intersection-overlap", "difference-overlap",
                         "union-disjoint", "intersection-contained", "difference-contained"],
        },
    },
    "unbound": {
        "major.7.5.01": "corefine and autorefine are used only inside the three Boolean "
                        "operations; standalone corefinement output is not an operation.",
        "major.7.5.03": "No validated clip operation.",
        "major.7.5.04": "No validated split operation.",
        "major.7.5.05": "No validated Polygon_mesh_slicer operation.",
    },
    "cases": [
        _case("union-overlap", "mesh.boolean.union",
              [_mesh(CUBE_A), _mesh(CUBE_OVERLAP)], {"operation": "union"}, [
            ["metrics.exact_volume", "==", "12"], ["metrics.result_status", "==", "volume"],
            ["output:geometry:measure:off.signed_volume", "approx", [12.0, 1e-9]],
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
        ]),
        _case("intersection-overlap", "mesh.boolean.intersection",
              [_mesh(CUBE_A), _mesh(CUBE_OVERLAP)], {"operation": "intersection"}, [
            ["metrics.exact_volume", "==", "4"], ["metrics.result_status", "==", "volume"],
            ["output:geometry:measure:off.signed_volume", "approx", [4.0, 1e-9]],
        ]),
        _case("difference-overlap", "mesh.boolean.difference",
              [_mesh(CUBE_A), _mesh(CUBE_OVERLAP)], {"operation": "difference"}, [
            ["metrics.exact_volume", "==", "4"], ["metrics.result_status", "==", "volume"],
            ["output:geometry:measure:off.signed_volume", "approx", [4.0, 1e-9]],
        ]),
        _case("union-disjoint", "mesh.boolean.union",
              [_mesh(CUBE_A), _mesh(CUBE_DISJOINT)], {"operation": "union"}, [
            ["metrics.exact_volume", "==", "16"],
            ["output:geometry:measure:off.signed_volume", "approx", [16.0, 1e-9]],
        ]),
        _case("intersection-contained", "mesh.boolean.intersection",
              [_mesh(CUBE_A), _mesh(CUBE_CONTAINED)], {"operation": "intersection"}, [
            ["metrics.exact_volume", "==", "1"],
            ["output:geometry:measure:off.signed_volume", "approx", [1.0, 1e-9]],
        ]),
        _case("difference-contained", "mesh.boolean.difference",
              [_mesh(CUBE_A), _mesh(CUBE_CONTAINED)], {"operation": "difference"}, [
            ["metrics.exact_volume", "==", "7"],
            ["output:geometry:measure:off.signed_volume", "approx", [7.0, 1e-9]],
        ]),
    ],
    "pairs": [],
    "negative_controls": [
        {"id": "union-open-input-rejected", "operation": "mesh.boolean.union",
         "inputs": [_mesh(OPEN_CUBE), _mesh(CUBE_OVERLAP)], "parameters": {"operation": "union"},
         "expect_error_class": "PRECONDITION_FAILED"},
    ],
}

FAMILY_7_9 = {
    "family": "7.9",
    "scope": "family_7_9_point_set_processing_partial",
    "evidence_path": "docs/master/evidence/family-7.9-capabilities.json",
    "test_id": "family-7.9-replay-cases",
    "requirements": {
        "major.7.9.01": {
            "operation_ids": ["pointset.normals.estimate", "pointset.normals.orient_mst"],
            "symbols": ["jet_estimate_normals", "pca_estimate_normals"],
            "case_ids": ["normals-pca-plane", "normals-jet-plane", "normals-orient-mst"],
        },
        "major.7.9.04": {
            "operation_ids": ["pointset.simplify.grid", "pointset.simplify.random",
                              "pointset.simplify.hierarchy"],
            "symbols": ["grid_simplify_point_set", "random_simplify_point_set"],
            "case_ids": ["simplify-grid", "simplify-random-seed-a", "simplify-random-seed-a-repeat",
                         "simplify-random-seed-b", "simplify-hierarchy"],
        },
    },
    "unbound": {
        "major.7.9.02": "pointset.remove_outliers is replayable, but compute_average_spacing is "
                        "not exposed (the threshold distance must be supplied explicitly).",
        "major.7.9.03": "pointset.smooth.jet exposes jet_smooth_point_set only; "
                        "bilateral_smooth_point_set is not exposed.",
        "major.7.9.05": "No validated registration operation (register_point_sets, "
                        "compute_registration_transformation).",
        "major.7.9.06": "compute_average_spacing is not exposed; remove_outliers alone does not "
                        "cover the listed reconstruction-preprocessing subcapabilities.",
    },
    "cases": [
        _case("normals-pca-plane", "pointset.normals.estimate", [_points(PLANE)],
              {"method": "pca", "neighbors": 8}, [
            ["metrics.method", "==", "pca"],
            ["output:points:measure:points.count", "==", 25],
            ["output:points:measure:points.min_abs_normal_z", ">", 0.99],
        ]),
        _case("normals-jet-plane", "pointset.normals.estimate", [_points(PLANE)],
              {"method": "jet", "neighbors": 8, "degree_fitting": 2}, [
            ["metrics.method", "==", "jet"],
            ["output:points:measure:points.count", "==", 25],
            ["output:points:measure:points.min_abs_normal_z", ">", 0.99],
        ]),
        _case("normals-orient-mst", "pointset.normals.orient_mst",
              [_points(ALTERNATING, "PointSet3Normals", "ply")],
              {"neighbors": 4, "drop_unoriented": False}, [
            ["metrics.unoriented_point_count", "==", 0],
            ["input:points:measure:points.normal_z_sign_consistent", "==", False],
            ["output:points:measure:points.normal_z_sign_consistent", "==", True],
            ["output:points:measure:points.count", "==", 9],
        ]),
        _case("simplify-grid", "pointset.simplify.grid", [_points(NOISY_PLANE)],
              {"cell_size": {"value": 1.5, "unit": "mm"}, "min_points_per_cell": 1}, [
            ["input:points:measure:points.count", "==", 26],
            ["output:points:measure:points.count", "<", {"path": "input:points:measure:points.count"}],
            ["output:points:measure:points.count", ">", 0],
        ]),
        _case("simplify-random-seed-a", "pointset.simplify.random", [_points(NOISY_PLANE)],
              {"removed_percentage": 50.0, "seed": 12345}, [
            ["output:points:measure:points.count", "==", 13],
        ]),
        _case("simplify-random-seed-a-repeat", "pointset.simplify.random", [_points(NOISY_PLANE)],
              {"removed_percentage": 50.0, "seed": 12345}, [
            ["output:points:measure:points.count", "==", 13],
        ]),
        _case("simplify-random-seed-b", "pointset.simplify.random", [_points(NOISY_PLANE)],
              {"removed_percentage": 50.0, "seed": 99999}, [
            ["output:points:measure:points.count", "==", 13],
        ]),
        _case("simplify-hierarchy", "pointset.simplify.hierarchy", [_points(NOISY_PLANE)],
              {"cluster_size": 4, "maximum_variation": 0.2}, [
            ["output:points:measure:points.count", "<", {"path": "input:points:measure:points.count"}],
            ["output:points:measure:points.count", ">", 0],
        ]),
    ],
    "pairs": [
        {"kind": "equal_outputs", "cases": ["simplify-random-seed-a", "simplify-random-seed-a-repeat"]},
        {"kind": "different_outputs", "cases": ["simplify-random-seed-a", "simplify-random-seed-b"]},
        {"kind": "different_outputs", "cases": ["normals-pca-plane", "normals-jet-plane"]},
    ],
    "negative_controls": [],
}

# ---- Wave C families (fixtures under tests/fixtures/master/wave_c) ----------
PLANAR = {"fixture": "wave_c/planar_points.json", "sha256": "2edb3017cdb0e39e041a75284cf208f42b847c91ad938fab0eaafcfca219fbae"}
COLLINEAR = {"fixture": "wave_c/collinear_points.json", "sha256": "087f7019a38d090185c7819a8218e88b0d5be18c4636bf558534818186ae14f5"}
POLYGON_HOLE = {"fixture": "wave_c/polygon_with_hole.json", "sha256": "b88fd8eeacddaa021697227ce5caa3a2fe22bd026592f9676a97bf17963d7959"}
POLYGON_L = {"fixture": "wave_c/polygon_l_shape.json", "sha256": "dec71795a9fc825548732ea647003420ad0b4fd1419443f4440308bdbe7f4b4d"}
POLYGON_BOWTIE = {"fixture": "wave_c/polygon_bowtie.json", "sha256": "44351418b0b2c4af582cf01a32eda634860b502b0026459e767f0924ba4cc71f"}
CONTAINMENT_QUERIES = {"fixture": "wave_c/containment_queries.json",
                       "sha256": "d01fce2f49091c170b8a6da5b10c44a374dc9f89d4e6ac9647e88c167fced48b"}
CONSTRAINT_GRAPH = {"fixture": "wave_c/constraint_graph.json", "sha256": "ddfd2a733ff2bddc32857ba5cf1ed8d5ebed2cf6c89ea63ae9fd7b92256c49fb"}
CONSTRAINT_CROSSING = {"fixture": "wave_c/constraint_crossing.json",
                       "sha256": "2b9d0ae7e96b5b1bc6702ae78f6cfac0bf825ac57cc768dc1d876144fc942059"}
CLOUD = {"fixture": "wave_c/cloud_points.xyz", "sha256": "6eefbc923c71e53120312cdbdd30e283ae07850e5fb650ecb958f16b7c1e0dae"}
QUERY_POINTS = {"fixture": "wave_c/query_points.xyz", "sha256": "49d0b7c67d716f111f324a49918d9561d46e5b2d3bf03ec1c934c071f5ee1070"}
MESH_QUERIES = {"fixture": "wave_c/mesh_queries.xyz", "sha256": "6c4bc044e35ca94f3c9dd5f91cea6282a85aaf3818420222dbc8c8b819925277"}
CUBE_RAYS = {"fixture": "wave_c/cube_rays.json", "sha256": "1c9d3a1e32f7100ac8ce54f14a2b27016543ab2f52d7f8d98444c69c8dd5d523"}
CUBE_WITH_INTERIOR = {"fixture": "cube_with_interior.xyz", "sha256": "299fc3e1e6363388d7fa80fcc86a297dde4740fd59f7d2fc628bdb0d27ae7a39"}


def _json_input(fixture: dict, type_: str, unit: str = "mm") -> dict:
    return {**fixture, "type": type_, "format": "json", "unit": unit}


SQRT2 = math.sqrt(2.0)
SQRT3 = math.sqrt(3.0)

FAMILY_7_13 = {
    "family": "7.13",
    "scope": "family_7_13_hulls_partial",
    "evidence_path": "docs/master/evidence/family-7.13-capabilities.json",
    "test_id": "family-7.13-replay-cases",
    "requirements": {
        "major.7.13.01": {
            "operation_ids": ["hull.convex_2", "hull.convex_3"],
            "symbols": ["convex_hull_2", "convex_hull_3"],
            "symbol_notes": "The 2D case is a 21-point set with interior points whose hull is the "
                            "hand-derived 3x3 square (area 9); the 3D case is the cube corners plus "
                            "the centre, whose hull is the cube of volume 8 with 8 vertices and 12 "
                            "triangles. Each hull is also checked by its independent enclosure "
                            "validator.",
            "case_ids": ["hull2-grid", "hull3-cube"],
        },
    },
    "unbound": {
        "major.7.13.02": "No alpha shape operation (Alpha_shape_2, Alpha_shape_3).",
        "major.7.13.03": "No alpha wrapping operation (alpha_wrap_3).",
        "major.7.13.04": "No bounding-volume operation (Min_sphere_of_spheres_d, Min_circle_2); "
                         "spatial.bbox_2/3 are axis-aligned boxes only.",
        "major.7.13.05": "No barycentric coordinate operation (mean_value_coordinates_2, "
                         "wachspress_coordinates_2).",
    },
    "cases": [
        _case("hull2-grid", "hull.convex_2", [_json_input(PLANAR, "PointSet2")], {}, [
            ["output:polygon:json:points", "==", [[0.0, 0.0], [3.0, 0.0], [3.0, 3.0], [0.0, 3.0]]],
            ["metrics.hull_vertex_count", "==", 4],
            ["metrics.input_point_count", "==", 21],
            ["metrics.orientation", "==", "counterclockwise"],
            ["metrics.area.exact", "==", "9"],
            ["metrics.algorithm", "==", "CGAL::convex_hull_2"],
        ]),
        _case("hull3-cube", "hull.convex_3", [_points(CUBE_WITH_INTERIOR)], {}, [
            ["input:points:measure:points.count", "==", 9],
            ["output:geometry:measure:off.vertex_count", "==", 8],
            ["output:geometry:measure:off.face_count", "==", 12],
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.signed_volume", "approx", [8.0, 1e-12]],
        ]),
    ],
    "pairs": [],
    "negative_controls": [
        {"id": "hull2-collinear-rejected", "operation": "hull.convex_2",
         "inputs": [_json_input(COLLINEAR, "PointSet2")], "parameters": {},
         "expect_error_class": "PRECONDITION_FAILED"},
    ],
}

FAMILY_7_11 = {
    "family": "7.11",
    "scope": "family_7_11_triangulations_partial",
    "evidence_path": "docs/master/evidence/family-7.11-capabilities.json",
    "test_id": "family-7.11-replay-cases",
    "requirements": {
        "major.7.11.01": {
            "operation_ids": ["triangulation.delaunay_2", "triangulation.delaunay_3"],
            "symbols": ["Delaunay_triangulation_2", "Delaunay_triangulation_3"],
            "symbol_notes": "dt2-grid: 20 distinct vertices (one duplicate input merged) with 13 hull "
                            "vertices give 2n-2-h = 25 triangles by Euler's relation; dt3-cube: every "
                            "Delaunay tetrahedron of the cube corners plus centre contains the centre, "
                            "giving 12 tetrahedra. The dt3-cloud tetrahedron count is a regression pin "
                            "checked by the exact independent validator, not a hand-derived value.",
            "case_ids": ["dt2-grid", "dt3-cube", "dt3-cloud"],
        },
        "major.7.11.02": {
            "operation_ids": ["triangulation.constrained_2"],
            "symbols": ["Constrained_Delaunay_triangulation_2", "Constrained_triangulation_2"],
            "symbol_notes": "delaunay=true runs Constrained_Delaunay_triangulation_2 and delaunay=false "
                            "runs Constrained_triangulation_2 (asserted through the reported algorithm); "
                            "both preserve the three input constraints.",
            "case_ids": ["cdt-delaunay", "ct-plain"],
        },
    },
    "unbound": {
        "major.7.11.03": "No Regular_triangulation_2/3 operation.",
        "major.7.11.04": "No periodic or on-sphere triangulation operation.",
        "major.7.11.05": "No Voronoi_diagram_2 / Voronoi dual operation.",
    },
    "cases": [
        _case("dt2-grid", "triangulation.delaunay_2", [_json_input(PLANAR, "PointSet2")], {}, [
            ["metrics.algorithm", "==", "CGAL::Delaunay_triangulation_2"],
            ["metrics.input_point_count", "==", 21],
            ["metrics.duplicate_points_merged", "==", 1],
            ["metrics.vertex_count", "==", 20],
            ["metrics.triangle_count", "==", 25],
            ["output:triangulation:json:constrained_edges", "==", []],
        ]),
        _case("dt3-cube", "triangulation.delaunay_3", [_points(CUBE_WITH_INTERIOR)], {}, [
            ["metrics.algorithm", "==", "CGAL::Delaunay_triangulation_3"],
            ["metrics.vertex_count", "==", 9],
            ["metrics.tetrahedron_count", "==", 12],
        ]),
        _case("dt3-cloud", "triangulation.delaunay_3", [_points(CLOUD)], {}, [
            ["metrics.algorithm", "==", "CGAL::Delaunay_triangulation_3"],
            ["metrics.input_point_count", "==", 168],
            ["metrics.vertex_count", "==", 168],
        ]),
        _case("cdt-delaunay", "triangulation.constrained_2",
              [_json_input(CONSTRAINT_GRAPH, "SegmentGraph2")], {"delaunay": True}, [
            ["metrics.algorithm", "==", "CGAL::Constrained_Delaunay_triangulation_2"],
            ["metrics.vertex_count", "==", 10],
            ["output:triangulation:json:constrained_edges", "==", [[0, 6], [3, 7], [4, 5]]],
        ]),
        _case("ct-plain", "triangulation.constrained_2",
              [_json_input(CONSTRAINT_GRAPH, "SegmentGraph2")], {"delaunay": False}, [
            ["metrics.algorithm", "==", "CGAL::Constrained_triangulation_2"],
            ["metrics.vertex_count", "==", 10],
            ["output:triangulation:json:constrained_edges", "==", [[0, 6], [3, 7], [4, 5]]],
        ]),
    ],
    "pairs": [],
    "negative_controls": [
        {"id": "dt2-collinear-rejected", "operation": "triangulation.delaunay_2",
         "inputs": [_json_input(COLLINEAR, "PointSet2")], "parameters": {},
         "expect_error_class": "PRECONDITION_FAILED"},
        {"id": "cdt-crossing-constraints-rejected", "operation": "triangulation.constrained_2",
         "inputs": [_json_input(CONSTRAINT_CROSSING, "SegmentGraph2")], "parameters": {"delaunay": True},
         "expect_error_class": "PRECONDITION_FAILED"},
    ],
}

FAMILY_7_12 = {
    "family": "7.12",
    "scope": "family_7_12_polygons_partial",
    "evidence_path": "docs/master/evidence/family-7.12-capabilities.json",
    "test_id": "family-7.12-replay-cases",
    "requirements": {
        "major.7.12.01": {
            "operation_ids": ["polygon.analysis.properties", "polygon.query.containment"],
            "symbols": ["Polygon_2", "Polygon_with_holes_2", "is_simple"],
            "symbol_notes": "Replayed 2D polygon operations are ring orientation, simplicity "
                            "(Polygon_2::is_simple), convexity, exact area and centroid, bounding box, "
                            "polygon-with-holes validity and exact point location, asserted against "
                            "hand-derived values (100-9=91, centroid 919/182, L-shape 7 and 19/14). "
                            "Boolean, offset, skeleton and Minkowski operations are separate "
                            "requirements and stay unbound.",
            "case_ids": ["polygon-with-hole", "polygon-l-shape", "polygon-bowtie", "containment-with-hole"],
        },
    },
    "unbound": {
        "major.7.12.02": "No Arrangement_2 operation.",
        "major.7.12.03": "No overlay operation.",
        "major.7.12.04": "No Polygon_set_2 Boolean operation.",
        "major.7.12.05": "No straight-skeleton operation.",
        "major.7.12.06": "No skeleton-offset operation.",
        "major.7.12.07": "No Minkowski sum operation.",
    },
    "cases": [
        _case("polygon-with-hole", "polygon.analysis.properties",
              [_json_input(POLYGON_HOLE, "PolygonWithHoles2")], {}, [
            ["output:analysis:json:results.valid_polygon_with_holes", "==", True],
            ["output:analysis:json:results.hole_count", "==", 1],
            ["output:analysis:json:results.area.exact", "==", "91"],
            ["output:analysis:json:results.centroid.exact", "==", ["919/182", "919/182"]],
            ["output:analysis:json:results.bbox.min", "approx", [[0.0, 0.0], 1e-12]],
            ["output:analysis:json:results.bbox.max", "approx", [[10.0, 10.0], 1e-12]],
            ["output:analysis:json:results.rings[*].role", "==", ["outer", "hole"]],
            ["output:analysis:json:results.rings[*].orientation", "==", ["counterclockwise", "clockwise"]],
            ["output:analysis:json:results.rings[*].simple", "==", [True, True]],
            ["output:analysis:json:results.rings[*].convex", "==", [True, True]],
            ["output:analysis:json:results.rings[*].signed_area.exact", "==", ["100", "-9"]],
        ]),
        _case("polygon-l-shape", "polygon.analysis.properties",
              [_json_input(POLYGON_L, "PolygonWithHoles2")], {}, [
            ["output:analysis:json:results.valid_polygon_with_holes", "==", True],
            ["output:analysis:json:results.area.exact", "==", "7"],
            ["output:analysis:json:results.centroid.exact", "==", ["19/14", "19/14"]],
            ["output:analysis:json:results.rings[*].simple", "==", [True]],
            ["output:analysis:json:results.rings[*].convex", "==", [False]],
            ["output:analysis:json:results.rings[*].orientation", "==", ["counterclockwise"]],
        ]),
        _case("polygon-bowtie", "polygon.analysis.properties",
              [_json_input(POLYGON_BOWTIE, "PolygonWithHoles2")], {}, [
            ["output:analysis:json:results.valid_polygon_with_holes", "==", False],
            ["output:analysis:json:results.rings[*].simple", "==", [False]],
        ]),
        _case("containment-with-hole", "polygon.query.containment",
              [_json_input(POLYGON_HOLE, "PolygonWithHoles2"),
               _json_input(CONTAINMENT_QUERIES, "PointSet2")], {}, [
            ["output:analysis:json:results[*].location", "==",
             ["inside", "outside", "boundary", "boundary", "outside", "boundary", "boundary", "inside"]],
            ["output:analysis:json:summary.inside", "==", 2],
            ["output:analysis:json:summary.outside", "==", 2],
            ["output:analysis:json:summary.boundary", "==", 4],
        ]),
    ],
    "pairs": [],
    "negative_controls": [
        {"id": "containment-bowtie-rejected", "operation": "polygon.query.containment",
         "inputs": [_json_input(POLYGON_BOWTIE, "PolygonWithHoles2"),
                    _json_input(CONTAINMENT_QUERIES, "PointSet2")], "parameters": {},
         "expect_error_class": "PRECONDITION_FAILED"},
    ],
}

# Query 1 coincides with cloud point 167 (1,1,1); query 5 is (3,3,3), 2*sqrt(3) away from it.
_KNN_COMMON = [
    ["metrics.tree", "==", "CGAL::Kd_tree"],
    ["metrics.query_count", "==", 6],
    ["output:analysis:json:results.1.neighbors.0.index", "==", 167],
    ["output:analysis:json:results.1.neighbors.0.distance", "==", 0.0],
    ["output:analysis:json:results.5.neighbors.0.index", "==", 167],
    ["output:analysis:json:results.5.neighbors.0.distance", "approx", [2.0 * SQRT3, 1e-12]],
]

FAMILY_7_2 = {
    "family": "7.2",
    "scope": "family_7_2_spatial_queries_partial",
    "evidence_path": "docs/master/evidence/family-7.2-capabilities.json",
    "test_id": "family-7.2-replay-cases",
    "requirements": {
        "major.7.2.01": {
            "operation_ids": ["spatial.aabb.closest_points", "spatial.aabb.ray_first_hits"],
            "symbols": ["AABB_tree", "AABB_traits", "AABB_face_graph_triangle_primitive"],
            "symbol_notes": "The worker uses AABB_tree with AABB_face_graph_triangle_primitive and the "
                            "AABB_traits_3 traits class (the CGAL 6.x name of the inventory's "
                            "AABB_traits). Closest-point distances and ray hits on the axis-aligned "
                            "cube are hand-derived; closest points are asserted only where the nearest "
                            "face is unique. Intersection-candidate queries are 7.2.04.",
            "case_ids": ["aabb-closest-cube", "aabb-rays-cube"],
        },
        "major.7.2.02": {
            "operation_ids": ["spatial.knn_3", "spatial.range_search_3"],
            "symbols": ["Kd_tree", "Search_traits_3"],
            "symbol_notes": "Both operations build a CGAL::Kd_tree over Search_traits_3 (through "
                            "Search_traits_adapter). Radius search is replayed with radius 0 (exactly "
                            "the coincident point 167) and radius 0.5 (total confirmed by the exact "
                            "brute-force validator; queries 2 and 5 are empty because their nearest "
                            "neighbours are 1.60 and 3.46 away).",
            "case_ids": ["knn-orthogonal", "knn-general", "range-zero-radius", "range-half-radius"],
        },
        "major.7.2.03": {
            "operation_ids": ["spatial.knn_3"],
            "symbols": ["K_neighbor_search", "Orthogonal_k_neighbor_search"],
            "case_ids": ["knn-orthogonal", "knn-general", "knn-nearest-single"],
        },
        "major.7.2.05": {
            "operation_ids": ["spatial.bbox_2", "spatial.bbox_3"],
            "symbols": ["Bbox_2", "Bbox_3", "bbox_2", "bbox_3"],
            "symbol_notes": "Boxes of a planar point set, a triangle mesh and a 3D point set are "
                            "asserted against hand-derived extrema.",
            "case_ids": ["bbox-planar", "bbox-cube-mesh", "bbox-point-set"],
        },
    },
    "unbound": {
        "major.7.2.04": "No intersection-candidate operation (do_intersect, any_intersected_primitive, "
                        "all_intersected_primitives); only AABB first-hit ray queries are exposed.",
    },
    "cases": [
        _case("aabb-closest-cube", "spatial.aabb.closest_points",
              [_mesh(CUBE_A), _points(MESH_QUERIES)], {}, [
            ["metrics.algorithm", "==", "CGAL::AABB_tree::closest_point_and_primitive"],
            ["metrics.face_count", "==", 12],
            ["metrics.query_count", "==", 6],
            ["output:analysis:json:results[*].distance", "approx",
             [[1.0, 1.0, 2.0, SQRT3 / 2.0, 0.25, SQRT2], 1e-12]],
            ["output:analysis:json:results.1.point", "approx", [[2.0, 1.0, 1.0], 1e-12]],
            ["output:analysis:json:results.2.point", "approx", [[1.0, 1.0, 0.0], 1e-12]],
            ["output:analysis:json:results.3.point", "approx", [[2.0, 2.0, 2.0], 1e-12]],
            ["output:analysis:json:results.4.point", "approx", [[1.0, 0.5, 0.0], 1e-12]],
            ["output:analysis:json:results.5.point", "approx", [[0.0, 2.0, 1.0], 1e-12]],
        ]),
        _case("aabb-rays-cube", "spatial.aabb.ray_first_hits",
              [_mesh(CUBE_A), _json_input(CUBE_RAYS, "RayBatch3")], {}, [
            ["metrics.algorithm", "==", "CGAL::AABB_tree::first_intersection"],
            ["metrics.ray_count", "==", 6],
            ["metrics.hit_count", "==", 5],
            ["output:analysis:json:results[*].hit", "==", [True, False, True, True, True, True]],
            ["output:analysis:json:results.0.distance", "approx", [1.0, 1e-12]],
            ["output:analysis:json:results.0.point", "approx", [[1.0, 1.0, 0.0], 1e-12]],
            ["output:analysis:json:results.2.distance", "approx", [math.sqrt(1.13), 1e-12]],
            ["output:analysis:json:results.2.point", "approx", [[2.0, 1.3, 1.2], 1e-12]],
            ["output:analysis:json:results.3.distance", "approx", [1.0, 1e-12]],
            ["output:analysis:json:results.3.point", "approx", [[0.0, 0.5, 0.0], 1e-12]],
            ["output:analysis:json:results.4.distance", "approx", [SQRT3, 1e-12]],
            ["output:analysis:json:results.4.point", "approx", [[0.0, 0.0, 0.0], 1e-12]],
            ["output:analysis:json:results.5.distance", "approx", [1.0, 1e-12]],
            ["output:analysis:json:results.5.point", "approx", [[0.5, 0.5, 2.0], 1e-12]],
        ]),
        _case("knn-orthogonal", "spatial.knn_3", [_points(CLOUD), _points(QUERY_POINTS)],
              {"k": 5, "search": "orthogonal"}, [
            ["metrics.algorithm", "==", "CGAL::Orthogonal_k_neighbor_search"],
            ["metrics.k", "==", 5],
            *_KNN_COMMON,
        ]),
        _case("knn-general", "spatial.knn_3", [_points(CLOUD), _points(QUERY_POINTS)],
              {"k": 5, "search": "general"}, [
            ["metrics.algorithm", "==", "CGAL::K_neighbor_search"],
            ["metrics.k", "==", 5],
            *_KNN_COMMON,
        ]),
        _case("knn-nearest-single", "spatial.knn_3", [_points(CLOUD), _points(QUERY_POINTS)],
              {"k": 1, "search": "orthogonal"}, [
            ["metrics.k", "==", 1],
            ["output:analysis:json:results.1.neighbors.0.index", "==", 167],
            ["output:analysis:json:results.5.neighbors.0.index", "==", 167],
        ]),
        _case("range-zero-radius", "spatial.range_search_3", [_points(CLOUD), _points(QUERY_POINTS)],
              {"radius": {"value": 0.0, "unit": "mm"}}, [
            ["output:analysis:json:results.1.neighbors.0.index", "==", 167],
            ["output:analysis:json:results.1.neighbors.0.distance", "==", 0.0],
            ["output:analysis:json:results.0.neighbors", "==", []],
        ]),
        _case("range-half-radius", "spatial.range_search_3", [_points(CLOUD), _points(QUERY_POINTS)],
              {"radius": {"value": 0.5, "unit": "mm"}}, [
            ["output:analysis:json:results.2.neighbors", "==", []],
            ["output:analysis:json:results.5.neighbors", "==", []],
        ]),
        _case("bbox-planar", "spatial.bbox_2", [_json_input(PLANAR, "PointSet2")], {}, [
            ["output:analysis:json:results.dimension", "==", 2],
            ["output:analysis:json:results.min", "approx", [[0.0, 0.0], 1e-12]],
            ["output:analysis:json:results.max", "approx", [[3.0, 3.0], 1e-12]],
            ["output:analysis:json:summary.point_count", "==", 21],
        ]),
        _case("bbox-cube-mesh", "spatial.bbox_3", [_mesh(CUBE_A)], {}, [
            ["output:analysis:json:source.geometry_type", "==", "TriangleSurfaceMesh"],
            ["output:analysis:json:results.dimension", "==", 3],
            ["output:analysis:json:results.min", "approx", [[0.0, 0.0, 0.0], 1e-12]],
            ["output:analysis:json:results.max", "approx", [[2.0, 2.0, 2.0], 1e-12]],
        ]),
        _case("bbox-point-set", "spatial.bbox_3", [_points(QUERY_POINTS)], {}, [
            ["output:analysis:json:source.geometry_type", "==", "PointSet3"],
            ["output:analysis:json:results.min", "approx", [[-0.3, -0.5, -0.9], 1e-12]],
            ["output:analysis:json:results.max", "approx", [[3.0, 3.0, 3.0], 1e-12]],
            ["output:analysis:json:summary.point_count", "==", 6],
        ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["range-zero-radius", "range-half-radius"]},
        {"kind": "different_outputs", "cases": ["knn-orthogonal", "knn-nearest-single"]},
    ],
    "negative_controls": [
        {"id": "knn-zero-k-rejected", "operation": "spatial.knn_3",
         "inputs": [_points(CLOUD), _points(QUERY_POINTS)],
         "parameters": {"k": 0, "search": "general"}, "expect_error_class": "INVALID_REQUEST"},
        {"id": "range-unit-mismatch-rejected", "operation": "spatial.range_search_3",
         "inputs": [_points(CLOUD), _points(QUERY_POINTS)],
         "parameters": {"radius": {"value": 0.5, "unit": "cm"}}, "expect_error_class": "TYPE_ERROR"},
        {"id": "rays-unit-mismatch-rejected", "operation": "spatial.aabb.ray_first_hits",
         "inputs": [_mesh(CUBE_A), {**_json_input(CUBE_RAYS, "RayBatch3"), "unit": "cm"}],
         "parameters": {}, "expect_error_class": "TYPE_ERROR"},
        {"id": "bbox2-rejects-3d-points", "operation": "spatial.bbox_2",
         "inputs": [_points(CLOUD)], "parameters": {}, "expect_error_class": "TYPE_ERROR"},
    ],
}

GENERIC_FAMILIES: dict[str, dict] = {
    family["family"]: family for family in (FAMILY_7_2, FAMILY_7_3, FAMILY_7_4, FAMILY_7_5, FAMILY_7_9, FAMILY_7_11,
                   FAMILY_7_12, FAMILY_7_13)
}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def contract_digest(family: dict) -> str:
    return canonical_hash(family)


def requirement_coverage(family: dict) -> dict[str, dict]:
    return {
        requirement_id: {
            "case_ids": sorted(binding["case_ids"]),
            "operation_ids": list(binding["operation_ids"]),
            "symbols": list(binding["symbols"]),
        }
        for requirement_id, binding in family["requirements"].items()
    }


def validate_contract(family: dict) -> None:
    """Static self-consistency of one family contract (no execution)."""
    case_ids = [case["id"] for case in family["cases"]]
    negative_ids = [case["id"] for case in family["negative_controls"]]
    if len(set(case_ids + negative_ids)) != len(case_ids) + len(negative_ids):
        raise ValueError(f"Family {family['family']} has duplicate case ids")
    covered: set[str] = set()
    prefix = f"major.{family['family']}."
    for requirement_id, binding in family["requirements"].items():
        if not requirement_id.startswith(prefix) or requirement_id in family["unbound"]:
            raise ValueError(f"Invalid family requirement binding: {requirement_id}")
        if not binding["case_ids"] or not binding["operation_ids"] or not binding["symbols"]:
            raise ValueError(f"Empty family requirement binding: {requirement_id}")
        for case_id in binding["case_ids"]:
            if case_id not in case_ids:
                raise ValueError(f"Requirement names an unknown case: {requirement_id}/{case_id}")
            operation = next(case["operation"] for case in family["cases"] if case["id"] == case_id)
            if operation not in binding["operation_ids"]:
                raise ValueError(f"Case operation is outside the bound operations: {case_id}")
        operations_used = {case["operation"] for case in family["cases"]
                           if case["id"] in binding["case_ids"]}
        if operations_used != set(binding["operation_ids"]):
            raise ValueError(f"Bound operation lacks a replay case: {requirement_id}")
        covered.update(binding["case_ids"])
    for pair in family["pairs"]:
        if (pair["kind"] not in {"equal_outputs", "different_outputs"} or len(pair["cases"]) != 2 or
                not set(pair["cases"]) <= set(case_ids)):
            raise ValueError(f"Invalid pair check in family {family['family']}")
    if covered != set(case_ids):
        raise ValueError(f"Family {family['family']} has a case outside every bound requirement")
    for case in family["cases"] + family["negative_controls"]:
        for item in case["inputs"]:
            if not item["fixture"] or ".." in item["fixture"].split("/"):
                raise ValueError(f"Invalid fixture path: {item['fixture']}")
        for assertion in case.get("assertions", []):
            if len(assertion) != 3 or assertion[1] not in _OPERATORS:
                raise ValueError(f"Invalid assertion in case {case['id']}")


# --- Validator derivation and report checks (registry-driven) -------------

def registry_index(operations: list[dict]) -> dict[str, dict]:
    return {item.get("id"): item for item in operations if isinstance(item, dict)}


def mandatory_validators(operation: dict) -> list[str]:
    validation = operation.get("validation", {})
    validators = validation.get("validators")
    if validation.get("required") is not True or not isinstance(validators, list) or not validators:
        raise ValueError(f"Operation has no mandatory validator chain: {operation.get('id')}")
    return list(validators)


def derive_validator_plan(operation: dict, validator: dict, transform_parameters: dict) -> tuple[
        list[tuple[str, str]], dict]:
    """Return ([(kind, slot)...] in validator input order, parameters) from bindings."""
    binding = operation["validation"].get("bindings", {}).get(validator["id"])
    # Legacy bindings (hull.convex_3) list the slot references directly, without an "artifacts" wrapper.
    artifacts = binding.get("artifacts") if isinstance(binding, dict) and "artifacts" in binding else binding
    if not isinstance(binding, dict) or not isinstance(artifacts, dict):
        raise ValueError(f"Registry lacks a validator binding: {operation['id']}/{validator['id']}")
    plan = []
    for slot in validator["io"]["inputs"]:
        reference = artifacts.get(slot["slot"])
        if not isinstance(reference, dict) or len(reference) != 1:
            raise ValueError(f"Validator slot is not bound: {validator['id']}/{slot['slot']}")
        (kind, source_slot), = reference.items()
        if kind not in {"input", "output"}:
            raise ValueError(f"Validator slot binding kind is unknown: {kind}")
        plan.append((kind, source_slot))
    if set(artifacts) != {slot["slot"] for slot in validator["io"]["inputs"]}:
        raise ValueError(f"Validator binding names unknown slots: {validator['id']}")
    parameters = {}
    for name, reference in binding.get("parameters", {}).items():
        source = reference.get("parameter") if isinstance(reference, dict) else None
        if source in transform_parameters:
            parameters[name] = copy.deepcopy(transform_parameters[source])
        elif not reference.get("optional"):
            raise ValueError(f"Required validator parameter is unbound: {validator['id']}/{name}")
    return plan, parameters


def _report_value(report: object, dotted: str) -> tuple[bool, object]:
    value = report
    parts = dotted.split(".")
    for position, part in enumerate(parts):
        if part.endswith("[*]"):
            # Closed projection: map the remaining path over every element of a list.
            head = part[:-3]
            if not (isinstance(value, dict) and head in value and isinstance(value[head], list)):
                return False, None
            projected = []
            for element in value[head]:
                found, item = _report_value(element, ".".join(parts[position + 1:]))                     if position + 1 < len(parts) else (True, element)
                if not found:
                    return False, None
                projected.append(item)
            return True, projected
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return False, None
    return True, value


def validator_report_failures(validator: dict, report: object, transform_id: str) -> list[str]:
    if not isinstance(report, dict):
        return ["report is not an object"]
    failures = []
    validation = validator.get("validation", {})
    if report.get("status") != "pass":
        failures.append("status")
    if "passed" in report and report.get("passed") is not True:
        failures.append("passed")
    if "validates" in report and report.get("validates") != transform_id:
        failures.append("validates")
    for key, expected in validation.get("required_report_checks", {}).items():
        if _report_value(report, key) != (True, expected):
            failures.append(key)
    for key in validation.get("required_report_fields", []):
        if not _report_value(report, key)[0]:
            failures.append(key)
    for key, minimum in validation.get("required_report_minimum", {}).items():
        _, value = _report_value(report, key)
        if (not isinstance(value, (int, float)) or isinstance(value, bool) or
                not math.isfinite(float(value)) or value < minimum):
            failures.append(key)
    return failures


# --- Closed assertion vocabulary ------------------------------------------

def _decode_text(content: bytes) -> str:
    return content.decode("ascii")


def _parse_off(content: bytes) -> tuple[list[tuple[float, ...]], list[list[int]]]:
    tokens = _decode_text(content).split()
    if not tokens or tokens[0] != "OFF":
        raise ValueError("not OFF")
    vertex_count, face_count = int(tokens[1]), int(tokens[2])
    cursor = 4
    vertices = []
    for _ in range(vertex_count):
        vertices.append(tuple(float(tokens[cursor + axis]) for axis in range(3)))
        cursor += 3
    faces = []
    for _ in range(face_count):
        size = int(tokens[cursor])
        faces.append([int(tokens[cursor + 1 + offset]) for offset in range(size)])
        cursor += size + 1
    return vertices, faces


def _off_measure(name: str, content: bytes) -> object:
    vertices, faces = _parse_off(content)
    if name == "vertex_count":
        return len(vertices)
    if name == "face_count":
        return len(faces)
    if name == "max_face_degree":
        return max(len(face) for face in faces)
    edges: dict[tuple[int, int], int] = {}
    for face in faces:
        for offset, first in enumerate(face):
            key = tuple(sorted((first, face[(offset + 1) % len(face)])))
            edges[key] = edges.get(key, 0) + 1
    if name == "boundary_edge_count":
        return sum(1 for count in edges.values() if count == 1)
    if name == "min_edge_length":
        return min(math.dist(vertices[a], vertices[b]) for a, b in edges)
    if name == "signed_volume":
        total = 0.0
        for face in faces:
            a = vertices[face[0]]
            for index in range(1, len(face) - 1):
                b, c = vertices[face[index]], vertices[face[index + 1]]
                total += (a[0] * (b[1] * c[2] - b[2] * c[1]) -
                          a[1] * (b[0] * c[2] - b[2] * c[0]) +
                          a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
        return total
    raise ValueError(f"unknown OFF measure {name}")


def _parse_points(content: bytes) -> tuple[list[tuple[float, ...]], list[tuple[float, ...]] | None]:
    lines = _decode_text(content).splitlines()
    if lines and lines[0].strip() == "ply":
        properties: list[str] = []
        count = None
        cursor = 1
        while lines[cursor].strip() != "end_header":
            parts = lines[cursor].split()
            if parts[:2] == ["element", "vertex"]:
                count = int(parts[2])
            elif parts[:1] == ["property"]:
                properties.append(parts[-1])
            elif parts[:2] == ["element", "face"]:
                raise ValueError("unexpected PLY face element")
            cursor += 1
        rows = [list(map(float, line.split())) for line in lines[cursor + 1:cursor + 1 + count]]
        index = {name: position for position, name in enumerate(properties)}
        points = [tuple(row[index[axis]] for axis in ("x", "y", "z")) for row in rows]
        normals = ([tuple(row[index[axis]] for axis in ("nx", "ny", "nz")) for row in rows]
                   if {"nx", "ny", "nz"} <= index.keys() else None)
        return points, normals
    rows = [list(map(float, line.split())) for line in lines if line.strip()]
    points = [tuple(row[:3]) for row in rows]
    normals = [tuple(row[3:6]) for row in rows] if rows and all(len(row) >= 6 for row in rows) else None
    return points, normals


def _points_measure(name: str, content: bytes) -> object:
    points, normals = _parse_points(content)
    if name == "count":
        return len(points)
    if normals is None:
        raise ValueError("point set has no normals")
    if name == "min_abs_normal_z":
        return min(abs(normal[2]) / math.sqrt(sum(value * value for value in normal))
                   for normal in normals)
    if name == "normal_z_sign_consistent":
        signs = {normal[2] > 0 for normal in normals if normal[2] != 0}
        return len(signs) == 1 and all(normal[2] != 0 for normal in normals)
    raise ValueError(f"unknown point measure {name}")


def measure(name: str, content: bytes) -> object:
    kind, _, field = name.partition(".")
    if kind == "off":
        return _off_measure(field, content)
    if kind == "points":
        return _points_measure(field, content)
    raise ValueError(f"unknown measure {name}")


def _approx(actual: object, expected: object, tolerance: float) -> bool:
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(actual) == len(expected) and
                all(_approx(a, e, tolerance) for a, e in zip(actual, expected)))
    return (isinstance(actual, (int, float)) and not isinstance(actual, bool) and
            math.isfinite(float(actual)) and abs(float(actual) - float(expected)) <= tolerance)


def _compare(actual: object, operator: str, expected: object) -> bool:
    if operator == "==":
        return type(actual) is type(expected) and actual == expected if isinstance(expected, bool) \
            else (not isinstance(actual, bool) and actual == expected)
    if operator == "!=":
        return actual != expected
    if operator == "approx":
        value, tolerance = expected
        return _approx(actual, value, tolerance)
    numeric = (isinstance(actual, (int, float)) and not isinstance(actual, bool) and
               isinstance(expected, (int, float)) and not isinstance(expected, bool))
    if not numeric:
        return False
    return {"<": actual < expected, "<=": actual <= expected,
            ">": actual > expected, ">=": actual >= expected}[operator]


_OPERATORS = {"==", "!=", "<", "<=", ">", ">=", "approx"}


class CaseView:
    """Resolve selectors against one traced transform exchange and its blobs."""

    def __init__(self, operation: dict, request: dict, response: dict,
                 blob_content: dict[str, bytes]):
        self.response = response
        self.inputs = {slot["slot"]: item for slot, item in
                       zip(operation["io"]["inputs"], request.get("inputs", []))}
        self.outputs = {item.get("slot"): item for item in response.get("outputs", [])
                        if isinstance(item, dict)}
        self.blob_content = blob_content

    def resolve(self, selector: str) -> object:
        if selector.startswith("metrics."):
            found, value = _report_value(self.response.get("metrics", {}), selector[len("metrics."):])
            if not found:
                raise KeyError(selector)
            return value
        side, slot, kind, *rest = selector.split(":", 3)
        table = {"input": self.inputs, "output": self.outputs}.get(side)
        if table is None or slot not in table:
            raise KeyError(selector)
        digest = table[slot].get("blob_sha256")
        if kind == "sha256":
            return digest
        content = self.blob_content[digest]
        if kind == "json":
            found, value = _report_value(json.loads(content.decode("utf-8")), rest[0])
            if not found:
                raise KeyError(selector)
            return value
        if kind == "measure":
            return measure(rest[0], content)
        raise KeyError(selector)


def assertion_failures(case: dict, view: CaseView) -> list[str]:
    failures = []
    for selector, operator, expected in case["assertions"]:
        try:
            actual = view.resolve(selector)
            if isinstance(expected, dict):
                expected = view.resolve(expected["path"])
            passed = _compare(actual, operator, expected)
        except (KeyError, ValueError, TypeError, IndexError, UnicodeError, ZeroDivisionError):
            passed = False
        if not passed:
            failures.append(f"{case['id']}: {selector} {operator} {expected!r}")
    return failures


def blob_bytes(blobs: dict[str, dict]) -> dict[str, bytes]:
    return {digest: base64.b64decode(value["content"], validate=True)
            for digest, value in blobs.items()}


for _family in GENERIC_FAMILIES.values():
    validate_contract(_family)
