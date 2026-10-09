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
HULL_INNER = {"fixture": "wave_c/hull_inner_points.xyz", "sha256": "c668facce23117d1339896b004d624f7188fdc8104b3fe7b695308bc07d02b19"}
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
        {"id": "hull3-oversized-shell-rejected", "operation": "hull.validate.convex_enclosure",
         "inputs": [_mesh(CUBE_A), _points(HULL_INNER)], "parameters": {},
         "expect_error_class": "VALIDATION_FAILED"},
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

L_PRISM = {"fixture": "wave_d/l_prism.off",
           "sha256": "72215189b66d423386e6b9d35dddf6081a96c01a521aaea239e9e3cd77a75305"}
HEXADECAGON_FAN = {"fixture": "wave_d/hexadecagon_fan.off",
                   "sha256": "58e93f910dcc1912da7a336fa485d5145efb3b02a99e8cab3495cdf347543a3d"}
SQUARE_FAN = {"fixture": "wave_d/square_fan.off",
              "sha256": "71b10da73091276930a2263e652dc9246ec98aa3ebb3d0287f460e4a14fe9089"}
SQUARE_TWO_TRIANGLES = {"fixture": "wave_d/square_two_triangles.off",
                        "sha256": "61893beb05b4264903232dd6a2acf21d19fd2c65bfc4daef30454839cc743f8e"}
GRID3_DISPLACED = {"fixture": "wave_d/grid3_displaced.off",
                   "sha256": "5bc59a14bc8fbf0a180714daedaf24decb45dabe7e47f071210dae8f48191722"}
GRID5_BUMP = {"fixture": "wave_d/grid5_bump.off",
              "sha256": "45509bdb7622ee34019183abff1eaeec63b6fe2b34101af5c937e67371481c63"}
ICOSPHERE2 = {"fixture": "wave_d/icosphere2.off",
              "sha256": "cce1858c5c297f8827cfe3a31bf95bd1e9dc7935e8386f44bd3f0a22f1697558"}
ICOSPHERE2_NOISY = {"fixture": "wave_d/icosphere2_noisy.off",
                    "sha256": "38d5ccc26c72a6a96f3b2ad053e320758bfd0f2b4360a6074bdf9f48052c1cb0"}
OBLATE = {"fixture": "wave_d/oblate_spheroid.off",
          "sha256": "5bb797ddfdd0aa47c3c2ca61768910d16a16ab48a93176754d18a4238fc8f49e"}


def _mm(value: float) -> dict:
    return {"value": value, "unit": "mm"}


HEXADECAGON_AREA = 32.0 * math.sin(math.pi / 8.0)
GRID3_RELAXED_MEAN_EDGE = (12.0 + 4.0 * SQRT2) / 16.0
NOISY_SPHERE_VOLUME = 4.0426073283768496
OBLATE_VOLUME = 6.644385307347405
# Uniform isotropic remesh (target 0.1) of OBLATE: a valid, close, but curvature-blind candidate.
OBLATE_UNIFORM = {"fixture": "wave_d/oblate_uniform_0p1.off", "sha256": "de7e7f8a43b86b0afdb2fe32751a0c28d17773844eaded75ac26c663324e2eab"}
_ADAPTIVE = {"tolerance": _mm(0.01), "min_edge_length": _mm(0.1), "max_edge_length": _mm(0.8),
             "number_of_iterations": 3, "max_deviation": _mm(0.05)}

FAMILY_7_6 = {
    "family": "7.6",
    "scope": "family_7_6_meshing_remeshing_partial",
    "evidence_path": "docs/master/evidence/family-7.6-capabilities.json",
    "test_id": "family-7.6-replay-cases",
    "requirements": {
        "major.7.6.01": {
            "operation_ids": ["mesh.triangulate.faces"],
            "symbols": ["triangulate_faces", "triangulate_face"],
            "symbol_notes": "triangulate_faces (whole mesh) and triangulate_face (per face) are both "
                            "selected through the method parameter. The L-shaped prism with "
                            "non-convex hexagon caps becomes 20 triangles enclosing volume 3 and area "
                            "14; the quad cube becomes 12 triangles of volume 1. The independent "
                            "validator checks each triangle lies in exactly one source face with exact "
                            "per-face orientation.",
            "case_ids": ["tri-lprism-faces", "tri-lprism-face", "tri-quadcube"],
        },
        "major.7.6.02": {
            "operation_ids": ["mesh.refine.local"],
            "symbols": ["refine"],
            "symbol_notes": "refine inserts 13 interior vertices into a 14-triangle fan of a regular "
                            "16-gon (29 vertices, 40 faces, area 32 sin(pi/8)), and more at a higher "
                            "density control factor; the validator checks preserved source vertices "
                            "and boundary, the 2:1 face/vertex insertion relation and a certified "
                            "Hausdorff bound. fair is not listed in the inventory of this requirement.",
            "case_ids": ["refine-hexadecagon", "refine-hexadecagon-dense"],
        },
        "major.7.6.03": {
            "operation_ids": ["mesh.remesh.isotropic", "mesh.remesh.split_long_edges"],
            "symbols": ["isotropic_remeshing", "split_long_edges"],
            "symbol_notes": "Uniform isotropic_remeshing of an open planar square (area 16 kept, "
                            "mean edge within the target band), a closed sphere and an oblate "
                            "spheroid; split_long_edges of a two-triangle 4x4 square yields exactly "
                            "23 vertices and 28 faces with every source edge cut into pieces <= 1.",
            "case_ids": ["iso-square", "iso-sphere", "iso-oblate-uniform", "split-square"],
        },
        "major.7.6.04": {
            "operation_ids": ["mesh.smooth.tangential_relaxation", "mesh.smooth.shape"],
            "symbols": ["smooth_shape", "tangential_relaxation"],
            "symbol_notes": "tangential_relaxation moves the displaced centre of a 3x3 grid back to "
                            "the regular position (edges exactly 1 and sqrt 2); smooth_shape flattens a "
                            "bumped grid with a fixed boundary and smooths a noisy closed sphere while "
                            "preserving its volume to 1e-9. Validators check identical connectivity, "
                            "fixed boundary, quality/roughness improvement and a Hausdorff bound.",
            "case_ids": ["relax-grid3", "smooth-grid5", "smooth-sphere-volume"],
        },
        "major.7.6.05": {
            "operation_ids": ["mesh.remesh.adaptive"],
            "symbols": ["split_long_edges", "isotropic_remeshing"],
            "symbol_notes": "Adaptive_sizing_field drives both isotropic_remeshing and "
                            "split_long_edges on an oblate spheroid whose curvature ranges from about "
                            "0.1 to 12.5: the adaptive remesh spans an edge-length ratio above 5 "
                            "while staying within a certified 0.05 Hausdorff bound, whereas uniform "
                            "remeshing of the same input stays below ratio 3 and needs a 0.3 bound; the adaptive split preserves the exact "
                            "geometry while only refining long edges. The adaptive validator recomputes a curvature-driven "
                            "target from the raw source and rejects a uniform 0.1 remesh of the same input.",
            "case_ids": ["adaptive-oblate-isotropic", "adaptive-oblate-split"],
        },
    },
    "unbound": {},
    "cases": [
        _case("tri-lprism-faces", "mesh.triangulate.faces", [_mesh(L_PRISM, "PolygonSoup3")],
              {"method": "triangulate_faces"}, [
            ["input:source:measure:off.max_face_degree", "==", 6],
            ["output:geometry:measure:off.max_face_degree", "==", 3],
            ["output:geometry:measure:off.vertex_count", "==", 12],
            ["output:geometry:measure:off.face_count", "==", 20],
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.signed_volume", "approx", [3.0, 1e-12]],
            ["output:geometry:measure:off.area", "approx", [14.0, 1e-12]],
        ]),
        _case("tri-lprism-face", "mesh.triangulate.faces", [_mesh(L_PRISM, "PolygonSoup3")],
              {"method": "triangulate_face"}, [
            ["output:geometry:measure:off.max_face_degree", "==", 3],
            ["output:geometry:measure:off.face_count", "==", 20],
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.signed_volume", "approx", [3.0, 1e-12]],
            ["output:geometry:measure:off.area", "approx", [14.0, 1e-12]],
            ["metrics.method", "==", "triangulate_face"],
        ]),
        _case("tri-quadcube", "mesh.triangulate.faces", [_mesh(QUAD_CUBE, "PolygonSoup3")],
              {"method": "triangulate_faces"}, [
            ["input:source:measure:off.max_face_degree", "==", 4],
            ["output:geometry:measure:off.face_count", "==", 12],
            ["output:geometry:measure:off.vertex_count", "==", 8],
            ["output:geometry:measure:off.signed_volume", "approx", [1.0, 1e-12]],
        ]),
        _case("refine-hexadecagon", "mesh.refine.local", [_mesh(HEXADECAGON_FAN)],
              {"density_control_factor": SQRT2, "max_deviation": _mm(0.01)}, [
            ["input:source:measure:off.vertex_count", "==", 16],
            ["metrics.inserted_vertices", "==", 13],
            ["metrics.new_faces", "==", 26],
            ["output:geometry:measure:off.vertex_count", "==", 29],
            ["output:geometry:measure:off.face_count", "==", 40],
            ["output:geometry:measure:off.boundary_edge_count", "==", 16],
            ["output:geometry:measure:off.area", "approx", [HEXADECAGON_AREA, 1e-9]],
        ]),
        _case("refine-hexadecagon-dense", "mesh.refine.local", [_mesh(HEXADECAGON_FAN)],
              {"density_control_factor": 3.0, "max_deviation": _mm(0.01)}, [
            ["metrics.inserted_vertices", ">", 13],
            ["output:geometry:measure:off.boundary_edge_count", "==", 16],
            ["output:geometry:measure:off.area", "approx", [HEXADECAGON_AREA, 1e-9]],
        ]),
        _case("iso-square", "mesh.remesh.isotropic", [_mesh(SQUARE_FAN)],
              {"target_edge_length": _mm(0.5), "number_of_iterations": 3,
               "number_of_relaxation_steps": 1, "max_deviation": _mm(0.01)}, [
            ["output:geometry:measure:off.area", "approx", [16.0, 1e-9]],
            ["output:geometry:measure:off.mean_edge_length", ">=", 0.4],
            ["output:geometry:measure:off.mean_edge_length", "<=", 2.0 / 3.0],
            ["output:geometry:measure:off.face_count", ">",
             {"path": "input:source:measure:off.face_count"}],
            ["metrics.target_edge_length", "==", 0.5],
        ]),
        _case("iso-sphere", "mesh.remesh.isotropic", [_mesh(ICOSPHERE2)],
              {"target_edge_length": _mm(0.2), "number_of_iterations": 3,
               "number_of_relaxation_steps": 1, "max_deviation": _mm(0.05)}, [
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.mean_edge_length", ">=", 0.16],
            ["output:geometry:measure:off.mean_edge_length", "<=", 0.8 / 3.0],
            ["output:geometry:measure:off.signed_volume", ">", 3.95],
            ["output:geometry:measure:off.signed_volume", "<", 4.19],
        ]),
        _case("iso-oblate-uniform", "mesh.remesh.isotropic", [_mesh(OBLATE)],
              {"target_edge_length": _mm(0.3), "number_of_iterations": 3,
               "number_of_relaxation_steps": 1, "max_deviation": _mm(0.3)}, [
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.edge_length_ratio", "<", 3.0],
        ]),
        _case("split-square", "mesh.remesh.split_long_edges", [_mesh(SQUARE_TWO_TRIANGLES)],
              {"max_length": _mm(1.0)}, [
            ["output:geometry:measure:off.vertex_count", "==", 23],
            ["output:geometry:measure:off.face_count", "==", 28],
            ["output:geometry:measure:off.boundary_edge_count", "==", 16],
            ["output:geometry:measure:off.area", "approx", [16.0, 1e-12]],
        ]),
        _case("relax-grid3", "mesh.smooth.tangential_relaxation", [_mesh(GRID3_DISPLACED)],
              {"number_of_iterations": 1, "max_deviation": _mm(0.01)}, [
            ["output:geometry:measure:off.min_edge_length", "approx", [1.0, 1e-9]],
            ["output:geometry:measure:off.max_edge_length", "approx", [SQRT2, 1e-9]],
            ["output:geometry:measure:off.mean_edge_length", "approx",
             [GRID3_RELAXED_MEAN_EDGE, 1e-9]],
            ["output:geometry:measure:off.area", "approx", [4.0, 1e-12]],
        ]),
        _case("smooth-grid5", "mesh.smooth.shape", [_mesh(GRID5_BUMP)],
              {"time_step": 0.01, "number_of_iterations": 1, "preserve_volume": False,
               "max_deviation": _mm(1.0)}, [
            ["output:geometry:measure:off.vertex_count", "==", 25],
            ["output:geometry:measure:off.boundary_edge_count", "==", 16],
            ["output:geometry:measure:off.bbox_diagonal", "<",
             {"path": "input:source:measure:off.bbox_diagonal"}],
        ]),
        _case("smooth-sphere-volume", "mesh.smooth.shape", [_mesh(ICOSPHERE2_NOISY)],
              {"time_step": 0.01, "number_of_iterations": 1, "preserve_volume": True,
               "max_deviation": _mm(0.2)}, [
            ["input:source:measure:off.signed_volume", "approx", [NOISY_SPHERE_VOLUME, 1e-12]],
            ["output:geometry:measure:off.signed_volume", "approx", [NOISY_SPHERE_VOLUME, 1e-9]],
            ["output:geometry:measure:off.edge_length_ratio", "<",
             {"path": "input:source:measure:off.edge_length_ratio"}],
        ]),
        _case("adaptive-oblate-isotropic", "mesh.remesh.adaptive", [_mesh(OBLATE)],
              {**_ADAPTIVE, "mode": "isotropic_remeshing"}, [
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.edge_length_ratio", ">", 5.0],
            ["output:geometry:measure:off.max_edge_length", ">", 0.5],
            ["metrics.algorithm", "==", "CGAL::Polygon_mesh_processing::isotropic_remeshing"],
        ]),
        _case("adaptive-oblate-split", "mesh.remesh.adaptive", [_mesh(OBLATE)],
              {**_ADAPTIVE, "mode": "split_long_edges"}, [
            ["output:geometry:measure:off.vertex_count", ">",
             {"path": "input:source:measure:off.vertex_count"}],
            ["output:geometry:measure:off.signed_volume", "approx", [OBLATE_VOLUME, 1e-9]],
            ["output:geometry:measure:off.max_edge_length", "<=",
             {"path": "input:source:measure:off.max_edge_length"}],
            ["metrics.algorithm", "==", "CGAL::Polygon_mesh_processing::split_long_edges"],
        ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["refine-hexadecagon", "refine-hexadecagon-dense"]},
        {"kind": "different_outputs", "cases": ["iso-oblate-uniform", "adaptive-oblate-isotropic"]},
    ],
    "negative_controls": [
        {"id": "tri-wrong-vertices-rejected", "operation": "mesh.validate.triangulated_faces",
         "inputs": [_mesh(CUBE_A), _mesh(QUAD_CUBE, "PolygonSoup3")], "parameters": {},
         "expect_error_class": "VALIDATION_FAILED"},
        {"id": "refine-nonmanifold-rejected", "operation": "mesh.refine.local",
         "inputs": [_mesh(NONMANIFOLD)],
         "parameters": {"density_control_factor": SQRT2, "max_deviation": _mm(0.01)},
         "expect_error_class": "PRECONDITION_FAILED"},
        {"id": "iso-unremeshed-rejected", "operation": "mesh.validate.isotropic_remesh",
         "inputs": [_mesh(SQUARE_FAN), _mesh(SQUARE_FAN)],
         "parameters": {"target_edge_length": _mm(0.5), "max_deviation": _mm(0.01)},
         "expect_error_class": "VALIDATION_FAILED"},
        {"id": "iso-nonpositive-length-rejected", "operation": "mesh.remesh.isotropic",
         "inputs": [_mesh(SQUARE_FAN)],
         "parameters": {"target_edge_length": _mm(0.0), "number_of_iterations": 1,
                        "number_of_relaxation_steps": 1, "max_deviation": _mm(0.01)},
         "expect_error_class": "INVALID_REQUEST"},
        {"id": "split-unsplit-rejected", "operation": "mesh.validate.split_long_edges",
         "inputs": [_mesh(SQUARE_TWO_TRIANGLES), _mesh(SQUARE_TWO_TRIANGLES)],
         "parameters": {"max_length": _mm(1.0)}, "expect_error_class": "VALIDATION_FAILED"},
        {"id": "relax-changed-connectivity-rejected",
         "operation": "mesh.validate.tangential_relaxation",
         "inputs": [_mesh(GRID5_BUMP), _mesh(GRID3_DISPLACED)],
         "parameters": {"max_deviation": _mm(0.01)}, "expect_error_class": "VALIDATION_FAILED"},
        {"id": "smooth-unsmoothed-rejected", "operation": "mesh.validate.shape_smoothing",
         "inputs": [_mesh(GRID5_BUMP), _mesh(GRID5_BUMP)],
         "parameters": {"max_deviation": _mm(1.0), "preserve_volume": False},
         "expect_error_class": "VALIDATION_FAILED"},
        {"id": "smooth-open-volume-rejected", "operation": "mesh.smooth.shape",
         "inputs": [_mesh(GRID5_BUMP)],
         "parameters": {"time_step": 0.01, "number_of_iterations": 1, "preserve_volume": True,
                        "max_deviation": _mm(1.0)},
         "expect_error_class": "PRECONDITION_FAILED"},
        {"id": "adaptive-uniform-remesh-rejected", "operation": "mesh.validate.adaptive_remesh",
         "inputs": [_mesh(OBLATE_UNIFORM), _mesh(OBLATE)],
         "parameters": {**{k: v for k, v in _ADAPTIVE.items() if k != "number_of_iterations"},
                        "mode": "isotropic_remeshing"},
         "expect_error_class": "VALIDATION_FAILED"},
        {"id": "adaptive-inverted-range-rejected", "operation": "mesh.remesh.adaptive",
         "inputs": [_mesh(OBLATE)],
         "parameters": {**_ADAPTIVE, "min_edge_length": _mm(0.8), "max_edge_length": _mm(0.1),
                        "mode": "isotropic_remeshing"},
         "expect_error_class": "INVALID_REQUEST"},
    ],
}

RECT_10X1 = {"fixture": "wave_e/rect_10x1.json",
             "sha256": "340646ffe0cf50adc5194dc15b16e7b739fb4b041ef5310e21ff491211a4fc5f"}
SQUARE_10 = {"fixture": "wave_e/square10.json",
             "sha256": "ffb231e94b4521e4a08334a7514aef2d82acd7c2af6f3899dee5abbfa519300c"}
TWO_HOLES = {"fixture": "wave_e/two_holes.json",
             "sha256": "cf06284fc29f97fb5e147d92529bd2adbd85716c846a4f4754debf3104c51643"}
HOLE_SQUARE = {"fixture": "wave_c/polygon_with_hole.json",
               "sha256": "b88fd8eeacddaa021697227ce5caa3a2fe22bd026592f9676a97bf17963d7959"}
L_SHAPE = {"fixture": "wave_c/polygon_l_shape.json",
           "sha256": "dec71795a9fc825548732ea647003420ad0b4fd1419443f4440308bdbe7f4b4d"}
BOWTIE = {"fixture": "wave_c/polygon_bowtie.json",
          "sha256": "44351418b0b2c4af582cf01a32eda634860b502b0026459e767f0924ba4cc71f"}
HOLE_OUTSIDE = {"fixture": "wave_e/hole_outside.json",
                "sha256": "9753d01982dac2231a1bdacb012e870e896bc4aae168b8a9a0bd404ec38d1578"}
HOLE_TOUCHING = {"fixture": "wave_e/hole_touching.json",
                 "sha256": "7f1dfcdd608fa14933e24ac36379fa0ac273a5a732a5b407cbaa97dc3a6e9ecd"}
HOLE_NESTED = {"fixture": "wave_e/hole_nested.json",
               "sha256": "608ce22a5a9e152c5f03b4e03de5c40204d81c3e4d5221a0b71fef29db2bc94a"}
HOLE_FAR_OUTSIDE = {"fixture": "wave_e/hole_far_outside.json",
                    "sha256": "0744fdb999d26df7f76317dee550d9584500a5b773da84ede58b61643a7e949e"}
SQUARE_MESH = {"fixture": "wave_e/square10_mesh.json",
               "sha256": "831c615cff3f9204c3c25ec5a575c10215d3e1f5da20b4800dc846355e3f2389"}
SQUARE_MESH_MISSING = {"fixture": "wave_e/square10_mesh_missing_triangle.json",
                       "sha256": "16eec39c116bf3b5574504f252394d44142de0431d3f9a250e6335c03b4a1fc9"}
SQUARE_MESH_SHIFTED = {"fixture": "wave_e/square10_mesh_shifted_boundary.json",
                       "sha256": "1b2a5e0ef565e0f723abd7f6a935349ed1780799e262dd5de3ed974c2a0de4a9"}
HOLED_MESH_FLIPPED = {"fixture": "wave_e/holed_mesh_flipped_diagonal.json",
                      "sha256": "ce1055676afa581be4b77529ed817f127fdb297dc757e9fc6c761802e25533dd"}

# Shape bound 0.125 = sin^2 of the smallest angle: asin(sqrt(0.125)) = 20.7048 degrees.
MESH2_MIN_ANGLE = math.degrees(math.asin(math.sqrt(0.125)))
MESH2_LOOSE_MIN_ANGLE = math.degrees(math.asin(0.25))


def _mesh2(aspect: float, size: float) -> dict:
    return {"aspect_bound": aspect, "size_bound": _mm(size)}


def _domain(fixture: dict) -> dict:
    return _json_input(fixture, "PolygonWithHoles2")


def _fx(name: str, sha: str, folder: str = "wave_e") -> dict:
    return {"fixture": f"{folder}/{name}", "sha256": sha}


DOM_SPHERE = _fx("domain_sphere.json", "bc34d6ea177e51f89badee9a56c54929a18a0cab280ecd095eea4d5439df1ed6")
DOM_SPHERE_R25 = _fx("domain_sphere_r25.json", "9b15c56b66cf83fb18c9e878f01ab5c5589e7ecb6227ccf94d98e0b79b962ae4")
DOM_ELLIPSOID = _fx("domain_ellipsoid.json", "bb3b0067560f83b79c9372ebf47b5d1c2ef75277286e150d43e2b94165afe269")
DOM_TORUS = _fx("domain_torus.json", "6822f541ac8f34998be9ef12aa51cb0e8988de34a685a5872d9982f0eeba0b9e")
DOM_EXPRESSION = _fx("domain_expression.json", "be8b9c7977654d9326afed6001eb9db463b82034a90ab5e37d5366043c317ebd")
DOM_UNKNOWN_KIND = _fx("domain_unknown_kind.json", "a646cf9a2c48e3d1269eff355ef3c73d496535106de86569e848a877fbffaf00")
DOM_NEGATIVE_RADIUS = _fx("domain_negative_radius.json", "40ef4479ff98b887c0279587718b32308c8c619e4603d5a6983cadb5d03623e0")
DOM_EXTRA_PARAMETER = _fx("domain_extra_parameter.json", "5b01da327554bd849b695d003e3a0d6b20bef63ca4b1708da1c809a2e188fa42")
DOM_THICK_TORUS = _fx("domain_thick_torus.json", "1c93cbf031ad545809fbd9ba43073e83f23d1be3a27cc753f5074a1a4d8cdebb")
DOM_NEEDLE_ELLIPSOID = _fx("domain_needle_ellipsoid.json", "14561aba29339e7d769642cce1c5e82d79db217de0a6cd577c15612b5defa180")
SURF_SPHERE_MESH = _fx("surface_sphere_r2_mesh.off", "128b742b0aea3c0da348cbe856bb5a611aba590743cc718edfeee7121542f750")
SURF_MISSING = _fx("surface_sphere_missing_triangle.off", "2f89f887201ed532235528999a624b5b76a0293fd6a491ceb0c72568fdc1532f")
SURF_FLIPPED_ALL = _fx("surface_sphere_flipped_all.off", "326b7a0e0c0ae264cd474619b0216bcaf4e0fccc1f919e2f2cf42ab1060a64b2")
SURF_FLIPPED_ONE = _fx("surface_sphere_flipped_one.off", "0efe1df86efcd3a70565ca731afb87e6ec7a31652606b11b83b0327f42adad5f")
SURF_DUPLICATE = _fx("surface_sphere_duplicate_face.off", "a18539731c0aaaf41edeb6e7d9c8422b71080043214854e4d1acdd26b8deb4cd")
SURF_SCALED = _fx("surface_sphere_scaled.off", "31c68fac197cf56d032b2fa5e28547de5e96211bffb85f1efdba72a81fd4e883")
SURF_OCTAHEDRON = _fx("surface_octahedron_r2.off", "61089e4b1f1f2475529b65641a4a0fa7f3f67534391cf5d950b94208918d2555")
SURF_TORUS_MESH = _fx("surface_torus_mesh.off", "8a5e1dc8db3e21e561eca23e8d26891850c5dead694fdf3734f176bab3e1a56d")
SURF_ELLIPSOID_MESH = _fx("surface_ellipsoid_mesh.off", "fb02c088721b20ac3c828dea43e62e564687da5bd6b3515c518421f905f10b9f")

VOL_SPHERE_MESH = _fx("volume_sphere_r2_mesh.json", "d153848e5d3fcff06fba3a9345bd6ce1825d714d6ab02cdf61d073ae3b8bca0a")
VOL_ELLIPSOID_MESH = _fx("volume_ellipsoid_mesh.json", "9490fd102d47883165355fd14f74b2a9b66b7d8bcfe29aa7190312fe22657e52")
VOL_TORUS_MESH = _fx("volume_torus_mesh.json", "9595cc950410e7b00e7c70b38899a5ac05b88344aab6c68a301db876f56d4572")
VOL_MISSING_INTERIOR = _fx("volume_sphere_missing_interior_cell.json", "ca92a6c8b3b0d7541da662c5f979fb329812b064daf619653ccc0dcf6bfdf484")
VOL_MISSING_BOUNDARY = _fx("volume_sphere_missing_boundary_cell.json", "bb1c0f466f82b70d08d6541420b0eaa09ae4b510951a3c2c6af68e4ae45decf9")
VOL_FLIPPED = _fx("volume_sphere_flipped_cell.json", "6dd6ac3303ad12e1e1a81834e8c9f5169be60cf5641f83dcc1bb5ebe4ae0f691")
VOL_DUPLICATE = _fx("volume_sphere_duplicate_cell.json", "cea461efb035d26d51d1ddc715bc4ef15df8f71955111b4fa46bf82e5fb0ed44")
VOL_SCALED = _fx("volume_sphere_scaled.json", "16e4a1f1d21a838c3af902eaa4d788bb260830c1d34ade88b4169a030aeb7a0d")
VOL_TWO_SUBDOMAINS = _fx("volume_sphere_two_subdomains.json", "98cb02dfa2ad5026d88d83118ffc57b0a59ee1413202235b69dd0304c2273665")
VOL_OCTAHEDRON = _fx("volume_sphere_octahedron_r2.json", "774ac96291ff9e2d0c5eb11c3fd8abb0b81fd32d8849408e00ab9bf258bc0931")

POLY_CUBE = _fx("poly_cube.off", "7c6caa2b4ca6ceb1ddcfb09bdd6764fbf9311763e99b3f0e716064c8164e28ac")
POLY_L_PRISM = _fx("poly_l_prism.off", "ff474d287097017c7ef598c85696efa92a11b7d6b7a1bd16dd96c471c4a650bb")
POLY_STAIR_PRISM = _fx("poly_stair_prism.off", "dc7f8a1e59f99c4d0f0fae2baf292ef91bdb70e3b0bc1f0aa4390fd66d2c9569")
POLY_TILTED_BOX = _fx("poly_tilted_box.off", "eac37c93d9ecb251360f0070544e5f9eb4f710c3dd8ab55ddfcf67fb24adc991")
POLY_CUBE_OPEN = _fx("poly_cube_open.off", "0446fa9718591641b6f2c066e98dd4f64068b14bb6ebbf53f884452c9ea4872a")
POLY_CUBE_INVERTED = _fx("poly_cube_inverted.off", "351c7f2977d911fbcd75c7df03ce1e163cef0bb92a32c4d0b0d9176296c3087b")
POLY_CUBE_INCONSISTENT = _fx("poly_cube_inconsistent.off", "f5979445dbaad5a9ddbb050c3ccb257c169fec7382e690cc8e17f3a690a18e9b")
POLY_CUBE_SELF_INTERSECTING = _fx("poly_cube_self_intersecting.off", "54645a9fd72fb8f16efe43cff9c5ca2c5084a5f76de6e59d70fadcb4aa066d61")
POLY_CUBE_NONMANIFOLD = _fx("poly_cube_nonmanifold.off", "42af0e10714897a1129e1ef2acc815fe95501ae40b3f19c48d712deab375ae7b")
POLY_TWO_CUBES = _fx("poly_two_cubes.off", "7d2e06074561d742d2743d87c19ec287ae4fbfe45b41e76f02aba4c3d65aa305")
POLY_ICOSPHERE = _fx("poly_icosphere.off", "53b740bfd5bb10c0ba6b583e2b9853f6f4b6cd60a38aa5230845aa8b36bc4c9f")
POLY_CUBE_FEATURES_MESH = _fx("poly_cube_features_mesh.json", "1cdef17597beb6e1876bbecd415732d1b855cc047134843573b14f7fdedd24fd")
POLY_CUBE_MESH = _fx("poly_cube_mesh.json", "a634d1ad14ac59e768c6c00e7959739c90b1ee46e7742081a5fc8d6e0d747717")
POLY_L_MESH = _fx("poly_l_prism_mesh.json", "157e6ae4f2a3a96b6ba0e90a4663d26f487ed6fef15ea1ac59c69a6ec9c595f8")
POLY_BOX_IN_L_MESH = _fx("poly_box_in_l_prism_mesh.json", "3e93ece081fd80f8abd2d72fc9e9f31cfcaff24c7849e24c043321f29bbd440c")
POLY_MISSING_INTERIOR = _fx("poly_cube_missing_interior_cell.json", "52b17bcaebaa67000d42ad46f8a30c96b504d2f088485eb82e889668c3ccb2b1")
POLY_MISSING_BOUNDARY = _fx("poly_cube_missing_boundary_cell.json", "4a4f5afc9509252640a9fd78bbf41eaeac235d450f6341bd329708cb305e8439")
POLY_FLIPPED = _fx("poly_cube_flipped_cell.json", "6c815354d6407623a8a43fa4acc8d501335040f4f4aadae163c46ed2d4b0562c")
POLY_DUPLICATE = _fx("poly_cube_duplicate_cell.json", "8387ec688a11e0283b8cda8c7d0d0b1b4f1f1867f51f2b07a8d72f9f85d37c6f")
POLY_SHIFTED = _fx("poly_cube_shifted.json", "71cb8f7ac36a89027acb07cb784d15e23efd21cf5487a6d04fd932ad3f2a1638")
POLY_SCALED = _fx("poly_cube_scaled.json", "30587f6995545aeee9563080c5b23fd4b2a7deabbd3a869c925a5f08b743404e")
POLY_BUMPED = _fx("poly_cube_bumped_vertex.json", "2ad85ea3a6532c27e05adf7eaffa54ed8774723080f1375ac945442e8ca306b0")
POLY_TWO_SUBDOMAINS = _fx("poly_cube_two_subdomains.json", "102457603f2f90b74ddf4b3fa3502828754d69310c58f63742ab880aa6bc8923")

VOL_GEN = "mesh.volume.generate"
VOL_VAL = "mesh.validate.volume_mesh"


def _vol(angle: float, size: float, distance: float, ratio: float, cell: float) -> dict:
    return {"facet_angle": angle, "facet_size": _mm(size), "facet_distance": _mm(distance),
            "cell_radius_edge_ratio": ratio, "cell_size": _mm(cell)}


def _regions(*boxes) -> list:
    """Typed cell_size_regions entries: (low corner, high corner, cell size)."""
    return [{"box_min": {a: _mm(low[i]) for i, a in enumerate("xyz")},
             "box_max": {a: _mm(high[i]) for i, a in enumerate("xyz")}, "cell_size": _mm(size)}
            for low, high, size in boxes]


def _box_name(prefix: str, low, high) -> str:
    return f"{prefix}({','.join(str(c) for c in (*low, *high))})"


SPHERE_BOX = ((0.0, 0.0, 0.0), (2.5, 2.5, 2.5))


def _tet(fixture: dict) -> dict:
    return _json_input(fixture, "TetrahedralMesh")


def _volume_checks(domain: str = "CGAL::Labeled_mesh_domain_3") -> list[list]:
    return [
        ["metrics.algorithm", "==", "CGAL::make_mesh_3"],
        ["metrics.criteria", "==", "CGAL::Mesh_criteria_3"],
        ["metrics.domain", "==", domain],
        ["metrics.perturbation", "==", False],
        ["metrics.exudation", "==", False],
        ["output:geometry:measure:tet.tetrahedron_count", "==", {"path": "metrics.tetrahedron_count"}],
        ["output:geometry:measure:tet.vertex_count", "==", {"path": "metrics.vertex_count"}],
        ["output:geometry:measure:tet.boundary_face_count", "==", {"path": "metrics.boundary_facet_count"}],
        ["output:geometry:measure:tet.max_face_use", "<=", 2],
        ["output:geometry:measure:tet.subdomain_count", "==", 1],
        ["output:geometry:measure:tet.min_tetrahedron_volume", ">", 0.0],
    ]


def _poly(fixture: dict) -> dict:
    return _mesh(fixture)


def _poly_checks(name: str, volume: float, area: float, volume_tolerance: float, size: float,
                 distance: float, angle: float, ratio: float, cell: float) -> list[list]:
    """Assertions on a polyhedral Mesh_3 output, re-measured against the raw OFF source."""
    off = f"({name})"
    return [
        *_volume_checks("CGAL::Polyhedral_mesh_domain_3"),
        ["metrics.domain_kind", "==", "polyhedral"],
        ["metrics.feature_protection", "==", False],
        ["metrics.source_volume", "approx", [volume, 1e-9]],
        ["metrics.source_area", "approx", [area, 1e-9]],
        ["output:geometry:measure:tet.euler_characteristic", "==", 1],
        ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
        ["output:geometry:measure:tet.volume", "approx", [volume, volume_tolerance * volume]],
        ["output:geometry:measure:tet.volume", "<=", volume + 1e-9],
        ["output:geometry:measure:tet.boundary_area", "approx", [area, 0.06 * area]],
        ["output:geometry:measure:tet.max_boundary_vertex_distance_to_off" + off, "<=", 1e-9],
        ["output:geometry:measure:tet.max_boundary_sample_distance_to_off" + off, "<=", size],
        ["output:geometry:measure:tet.max_off_sample_distance_to_boundary" + off, "<=", 2.0 * size],
        ["output:geometry:measure:tet.max_boundary_facet_center_distance_to_off" + off, "<=", distance + 1e-9],
        ["output:geometry:measure:tet.min_boundary_facet_angle", ">=", angle],
        ["output:geometry:measure:tet.max_boundary_facet_circumradius", "<=", size + 1e-9],
        ["output:geometry:measure:tet.max_circumradius", "<=", cell + 1e-9],
        ["output:geometry:measure:tet.max_radius_edge", "<=", ratio + 1e-9],
    ]


SURF_GEN = "mesh.surface.generate"
SURF_VAL = "mesh.validate.surface_mesh"
PI = math.pi
ELLIPSOID_AREA = 4.0 * PI * (((3.0 * 2.0) ** 1.6075 + (3.0 * 1.5) ** 1.6075 +
                              (2.0 * 1.5) ** 1.6075) / 3.0) ** (1 / 1.6075)


def _surf(angle: float, size: float, distance: float) -> dict:
    return {"angle_bound": angle, "size_bound": _mm(size), "distance_bound": _mm(distance)}


def _surface(fixture: dict) -> dict:
    return _json_input(fixture, "ImplicitSurfaceDomain")


def _surface_checks() -> list[list]:
    return [
        ["metrics.algorithm", "==", "CGAL::make_surface_mesh"],
        ["metrics.criteria", "==", "CGAL::Surface_mesh_default_criteria_3"],
        ["output:geometry:measure:off.boundary_edge_count", "==", 0],
        ["output:geometry:measure:off.max_face_degree", "==", 3],
        ["output:geometry:measure:off.face_count", "==", {"path": "metrics.facet_count"}],
        ["output:geometry:measure:off.vertex_count", "==", {"path": "metrics.vertex_count"}],
        ["output:geometry:measure:off.euler_characteristic", "==", {"path": "metrics.euler_characteristic"}],
    ]


FAMILY_7_14 = {
    "family": "7.14",
    "scope": "family_7_14_mesh_generation_partial",
    "evidence_path": "docs/master/evidence/family-7.14-capabilities.json",
    "test_id": "family-7.14-replay-cases",
    "requirements": {
        "major.7.14.01": {
            "operation_ids": ["mesh2.refine.delaunay"],
            "symbols": ["refine_Delaunay_mesh_2", "Delaunay_mesh_size_criteria_2"],
            "symbol_notes": "refine_Delaunay_mesh_2 with Delaunay_mesh_size_criteria_2 meshes a 10x10 "
                            "square (area 100), the same square with a 3x3 hole (91), an L-shape (7) "
                            "and a square with two holes (92). Output area is recomputed exactly "
                            "from the produced mesh; triangles are counterclockwise and meet the "
                            "aspect bound (smallest angle >= asin(sqrt(B))) and the maximum edge "
                            "length; boundary edges equal the refined constraints. A 10x1 "
                            "rectangle with a loose aspect bound stays the two input triangles "
                            "(smallest angle atan(1/10)); the default bound forces refinement. "
                            "The independent validator re-derives constraint preservation, "
                            "coverage, criteria and the constrained Delaunay property.",
            "case_ids": ["mesh2-square-size2", "mesh2-square-size1", "mesh2-square-loose-angle",
                         "mesh2-hole", "mesh2-lshape", "mesh2-two-holes", "mesh2-rect-unrefined",
                         "mesh2-rect-refined"],
        },
        "major.7.14.02": {
            "operation_ids": [SURF_GEN],
            "symbols": ["make_surface_mesh", "Implicit_surface_3", "Surface_mesh_default_criteria_3"],
            "symbol_notes": "CGAL::make_surface_mesh (Surface_mesher, deprecated in CGAL 6.2.1) with "
                            "Implicit_surface_3 meshes a fixed enumerated set of typed implicit "
                            "domains (sphere, ellipsoid, torus; no free-form expressions) under angle, "
                            "size and distance criteria. Checks are recomputed from the OFF output: "
                            "closed 2-manifold (no boundary), Euler characteristic 2 for sphere and "
                            "ellipsoid and 0 for the torus, every vertex on the analytic surface "
                            "(radius 2; ellipsoid 3x2x1.5; torus R=3 r=1), smallest facet angle >= "
                            "the angle bound, facet circumradius <= the size bound, and area and "
                            "volume within sampling error of 16 pi and 32 pi / 3 (sphere), "
                            "4 pi^2 R r and 2 pi^2 R r^2 (torus), 4 pi abc / 3 (ellipsoid). Finer "
                            "criteria give more facets and another radius gives another mesh. The "
                            "independent validator recomputes topology, orientation, analytic "
                            "distance, criteria and analytic area and volume.",
            "case_ids": ["surface-sphere", "surface-sphere-fine", "surface-sphere-r25",
                         "surface-ellipsoid", "surface-torus"],
        },
        "major.7.14.03": {
            "operation_ids": [VOL_GEN],
            "symbols": ["make_mesh_3", "Labeled_mesh_domain_3", "Polyhedral_mesh_domain_3",
                        "Mesh_criteria_3"],
            "symbol_notes": "CGAL::make_mesh_3 (Mesh_3) over a Polyhedral_mesh_domain_3 built from a "
                            "validated closed, outward oriented, single-component, intersection-free "
                            "TriangleSurfaceMesh (no feature protection) meshes the solid with typed "
                            "criteria: a unit cube (volume 1), an L-shaped prism (3), a staircase prism "
                            "(6) and a tilted 1x2x3 box (6). Every output is re-measured here from the "
                            "raw OFF source: boundary vertices lie on the source triangles, boundary "
                            "facet samples are within facet_size of the source and source samples "
                            "within twice facet_size of the boundary facets, facet circumcentres are "
                            "within facet_distance, the cell volume is within the stated bound of the "
                            "divergence-theorem volume, Euler characteristics are 1 and 2, and the "
                            "facet and cell criteria hold. Open, non-manifold, self-intersecting, "
                            "inconsistently oriented, inverted or multi-component sources are refused; "
                            "tampered, shifted, scaled, wrong-source and too-coarse meshes are "
                            "rejected by the validator. Image domains, polyhedral feature protection, "
                            "perturbation and exudation are not implemented. Implicit domains: "
                            "CGAL::make_mesh_3 (Mesh_3) over a Labeled_mesh_domain_3 built from a fixed "
                            "enumerated set of typed implicit domains (sphere radius 2 and 2.5, ellipsoid "
                            "3x2x1.5, torus R=3 r=1; no free-form expressions) meshes the solid with "
                            "typed facet angle/size/distance and cell radius-edge/size criteria. The "
                            "TetrahedralMesh output is re-measured here: every interior face is shared "
                            "by two cells, cells are positive, V-E+F-C is 1 for the balls and 0 for the "
                            "solid torus, the boundary is a closed surface with Euler characteristic 2 "
                            "or 0, boundary vertices lie on the analytic surface and interior vertices "
                            "strictly inside, the cell volume sums to 32 pi / 3, 4 pi abc / 3 and "
                            "2 pi^2 R r^2 within the sampling bound, the boundary area to 16 pi and "
                            "4 pi^2 R r, and the facet angle, facet radius, cell circumradius and "
                            "radius-edge criteria hold. Finer criteria give more cells. The independent "
                            "validator recomputes topology, exact orientation, the analytic domain "
                            "relation and every criterion without calling Mesh_3.",
            "case_ids": ["volume-sphere", "volume-sphere-fine", "volume-sphere-r25", "volume-ellipsoid",
                         "volume-torus", "volume-poly-cube", "volume-poly-cube-fine", "volume-poly-l-prism",
                         "volume-poly-stair-prism", "volume-poly-tilted-box"],
        },
        "major.7.14.04": {
            "operation_ids": [VOL_GEN],
            "symbols": ["Mesh_criteria_3", "Mesh_cell_criteria_3", "Mesh_facet_criteria_3",
                        "Polyhedral_mesh_domain_with_features_3"],
            "symbol_notes": "Typed MeshCriteria3 parameters (facet_angle, facet_size, facet_distance, "
                            "cell_radius_edge_ratio, cell_size, cell_size_regions, facet_topology, edge_size; "
                            "units checked, ranges checked, unknown keys rejected, no free-form expressions) "
                            "are passed to CGAL::Mesh_criteria_3 by mesh.volume.generate and re-checked one "
                            "criterion at a time by mesh.validate.volume_mesh. Each criterion has a "
                            "measurable effect re-derived here from the raw output: cell_size_regions (a "
                            "sizing field of up to four enumerated boxes, evaluated at the cell "
                            "circumcentre) bounds the circumradius of the cells inside the box by 0.3 while "
                            "the global 0.6 still holds outside and the plain mesh exceeds 0.3 there; "
                            "edge_size on the polyhedral unit cube (12 sharp edges, normal angle above 60 "
                            "degrees, protected through Polyhedral_mesh_domain_with_features_3) bounds the "
                            "gaps between consecutive mesh vertices on each cube edge and the mesh edge "
                            "lengths there by 0.5 and 0.25 (36 and 48 segments); facet_topology is carried "
                            "through and checked (every boundary facet vertex on the single-patch domain "
                            "surface). The negative controls tighten each criterion against a pinned genuine "
                            "mesh and expect that criterion's own code. Not covered: image domains, "
                            "multi-patch facet topology, sizing fields other than the enumerated boxes, "
                            "mesh.surface.generate (Surface_mesher criteria are not Mesh_criteria_3), and "
                            "facet and cell criteria on facets and cells that touch a protected feature "
                            "when edge_size is given.",
            "case_ids": ["volume-sphere-baseline-box", "volume-sphere-regions", "volume-sphere-topology-surface",
                         "volume-sphere-topology-patch", "volume-poly-cube-edge-size-half",
                         "volume-poly-cube-edge-size-quarter"],
        },
    },
    "unbound": {},
    "cases": [
        _case("mesh2-square-size2", "mesh2.refine.delaunay", [_domain(SQUARE_10)], _mesh2(0.125, 2.0), [
            ["metrics.algorithm", "==", "CGAL::refine_Delaunay_mesh_2"],
            ["metrics.criteria", "==", "CGAL::Delaunay_mesh_size_criteria_2"],
            ["metrics.input_vertex_count", "==", 4],
            ["metrics.ring_count", "==", 1],
            ["metrics.triangle_count", ">=", 58],
            ["metrics.triangle_count", "<", 231],
            ["output:mesh:measure:tri2.area", "approx", [100.0, 1e-9]],
            ["output:mesh:measure:tri2.max_edge_length", "<=", 2.0],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_MIN_ANGLE],
            ["output:mesh:measure:tri2.max_edge_use", "<=", 2],
            ["output:mesh:measure:tri2.boundary_edge_count", ">=", 20],
            ["output:mesh:measure:tri2.boundary_edge_count", "==", {"path": "metrics.constrained_edge_count"}],
            ["output:mesh:measure:tri2.triangle_count", "==", {"path": "metrics.triangle_count"}],
        ]),
        _case("mesh2-square-size1", "mesh2.refine.delaunay", [_domain(SQUARE_10)], _mesh2(0.125, 1.0), [
            ["output:mesh:measure:tri2.area", "approx", [100.0, 1e-9]],
            ["output:mesh:measure:tri2.max_edge_length", "<=", 1.0],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_MIN_ANGLE],
            ["output:mesh:measure:tri2.boundary_edge_count", ">=", 40],
            ["metrics.triangle_count", ">=", 231],
        ]),
        _case("mesh2-square-loose-angle", "mesh2.refine.delaunay", [_domain(SQUARE_10)],
              _mesh2(0.0625, 2.0), [
            ["output:mesh:measure:tri2.area", "approx", [100.0, 1e-9]],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_LOOSE_MIN_ANGLE],
            ["output:mesh:measure:tri2.max_edge_length", "<=", 2.0],
        ]),
        _case("mesh2-hole", "mesh2.refine.delaunay", [_domain(HOLE_SQUARE)], _mesh2(0.125, 2.0), [
            ["metrics.input_vertex_count", "==", 8],
            ["metrics.ring_count", "==", 2],
            ["output:mesh:measure:tri2.area", "approx", [91.0, 1e-9]],
            ["output:mesh:measure:tri2.max_edge_length", "<=", 2.0],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_MIN_ANGLE],
            ["output:mesh:measure:tri2.boundary_edge_count", "==", {"path": "metrics.constrained_edge_count"}],
            ["output:mesh:measure:tri2.max_edge_use", "<=", 2],
        ]),
        _case("mesh2-lshape", "mesh2.refine.delaunay", [_domain(L_SHAPE)], _mesh2(0.125, 2.0), [
            ["metrics.input_vertex_count", "==", 6],
            ["output:mesh:measure:tri2.area", "approx", [7.0, 1e-9]],
            ["output:mesh:measure:tri2.max_edge_length", "<=", 2.0],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_MIN_ANGLE],
            ["output:mesh:measure:tri2.boundary_edge_count", ">=", 10],
        ]),
        _case("mesh2-two-holes", "mesh2.refine.delaunay", [_domain(TWO_HOLES)], _mesh2(0.125, 2.0), [
            ["metrics.input_vertex_count", "==", 12],
            ["metrics.ring_count", "==", 3],
            ["output:mesh:measure:tri2.area", "approx", [92.0, 1e-9]],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_MIN_ANGLE],
            ["output:mesh:measure:tri2.boundary_edge_count", "==", {"path": "metrics.constrained_edge_count"}],
        ]),
        _case("mesh2-rect-unrefined", "mesh2.refine.delaunay", [_domain(RECT_10X1)],
              _mesh2(0.001, 100.0), [
            ["metrics.triangle_count", "==", 2],
            ["metrics.vertex_count", "==", 4],
            ["metrics.steiner_vertex_count", "==", 0],
            ["output:mesh:measure:tri2.area", "approx", [10.0, 1e-12]],
            ["output:mesh:measure:tri2.min_angle_degrees", "approx", [math.degrees(math.atan(0.1)), 1e-9]],
        ]),
        _case("mesh2-rect-refined", "mesh2.refine.delaunay", [_domain(RECT_10X1)],
              _mesh2(0.125, 100.0), [
            ["metrics.triangle_count", ">", 2],
            ["metrics.steiner_vertex_count", ">", 0],
            ["output:mesh:measure:tri2.area", "approx", [10.0, 1e-9]],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_MIN_ANGLE],
            ["output:mesh:measure:tri2.boundary_edge_count", "==", {"path": "metrics.constrained_edge_count"}],
        ]),
        _case("surface-sphere", SURF_GEN, [_surface(DOM_SPHERE)], _surf(25.0, 0.5, 0.05), [
            *_surface_checks(),
            ["metrics.domain_kind", "==", "sphere"],
            ["metrics.euler_characteristic", "==", 2],
            ["metrics.facet_count", ">=", 260],
            ["output:geometry:measure:off.min_vertex_radius", "approx", [2.0, 1e-5]],
            ["output:geometry:measure:off.max_vertex_radius", "approx", [2.0, 1e-5]],
            ["output:geometry:measure:off.area", "approx", [16.0 * PI, 0.03 * 16.0 * PI]],
            ["output:geometry:measure:off.signed_volume", "approx", [32.0 * PI / 3.0, 0.06 * 32.0 * PI / 3.0]],
            ["output:geometry:measure:off.min_angle_degrees", ">=", 25.0],
            ["output:geometry:measure:off.max_circumradius", "<=", 0.5 + 1e-9],
        ]),
        _case("surface-sphere-fine", SURF_GEN, [_surface(DOM_SPHERE)], _surf(25.0, 0.3, 0.02), [
            *_surface_checks(),
            ["metrics.euler_characteristic", "==", 2],
            ["metrics.facet_count", ">", 600],
            ["output:geometry:measure:off.min_vertex_radius", "approx", [2.0, 1e-5]],
            ["output:geometry:measure:off.max_vertex_radius", "approx", [2.0, 1e-5]],
            ["output:geometry:measure:off.area", "approx", [16.0 * PI, 0.01 * 16.0 * PI]],
            ["output:geometry:measure:off.min_angle_degrees", ">=", 25.0],
            ["output:geometry:measure:off.max_circumradius", "<=", 0.3 + 1e-9],
        ]),
        _case("surface-sphere-r25", SURF_GEN, [_surface(DOM_SPHERE_R25)], _surf(25.0, 0.5, 0.05), [
            *_surface_checks(),
            ["metrics.euler_characteristic", "==", 2],
            ["output:geometry:measure:off.min_vertex_radius", "approx", [2.5, 1e-5]],
            ["output:geometry:measure:off.max_vertex_radius", "approx", [2.5, 1e-5]],
            ["output:geometry:measure:off.area", "approx", [25.0 * PI, 0.03 * 25.0 * PI]],
            ["output:geometry:measure:off.signed_volume", "approx", [4.0 / 3.0 * PI * 15.625,
                                                                  0.06 * 4.0 / 3.0 * PI * 15.625]],
        ]),
        _case("surface-ellipsoid", SURF_GEN, [_surface(DOM_ELLIPSOID)], _surf(25.0, 0.6, 0.04), [
            *_surface_checks(),
            ["metrics.domain_kind", "==", "ellipsoid"],
            ["metrics.euler_characteristic", "==", 2],
            ["output:geometry:measure:off.max_ellipsoid_residual(3,2,1.5)", "approx", [0.0, 1e-5]],
            # Knud Thomsen's approximation of the ellipsoid area (error <= 1.1 percent) plus the
            # inscribed-facet sampling loss gives a 4 percent bound.
            ["output:geometry:measure:off.area", "approx", [ELLIPSOID_AREA, 0.04 * ELLIPSOID_AREA]],
            ["output:geometry:measure:off.signed_volume", "approx", [4.0 / 3.0 * PI * 9.0,
                                                                  0.06 * 4.0 / 3.0 * PI * 9.0]],
            ["output:geometry:measure:off.min_angle_degrees", ">=", 25.0],
            ["output:geometry:measure:off.max_circumradius", "<=", 0.6 + 1e-9],
        ]),
        _case("surface-torus", SURF_GEN, [_surface(DOM_TORUS)], _surf(25.0, 0.5, 0.03), [
            *_surface_checks(),
            ["metrics.domain_kind", "==", "torus"],
            ["metrics.euler_characteristic", "==", 0],
            ["output:geometry:measure:off.max_torus_residual(3,1)", "approx", [0.0, 1e-5]],
            ["output:geometry:measure:off.area", "approx", [12.0 * PI * PI, 0.03 * 12.0 * PI * PI]],
            ["output:geometry:measure:off.signed_volume", "approx", [6.0 * PI * PI, 0.06 * 6.0 * PI * PI]],
            ["output:geometry:measure:off.min_angle_degrees", ">=", 25.0],
            ["output:geometry:measure:off.max_circumradius", "<=", 0.5 + 1e-9],
        ]),
        _case("volume-sphere", VOL_GEN, [_surface(DOM_SPHERE)], _vol(25.0, 0.5, 0.05, 3.0, 0.6), [
            *_volume_checks(),
            ["metrics.domain_kind", "==", "sphere"],
            ["metrics.tetrahedron_count", ">=", 280],
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.min_boundary_vertex_radius", "approx", [2.0, 1e-6]],
            ["output:geometry:measure:tet.max_boundary_vertex_radius", "approx", [2.0, 1e-6]],
            ["output:geometry:measure:tet.max_interior_vertex_radius", "<", 2.0 - 1e-6],
            ["output:geometry:measure:tet.volume", "approx", [32.0 * PI / 3.0, 0.08 * 32.0 * PI / 3.0]],
            ["output:geometry:measure:tet.boundary_area", "approx", [16.0 * PI, 0.04 * 16.0 * PI]],
            ["output:geometry:measure:tet.min_boundary_facet_angle", ">=", 25.0],
            ["output:geometry:measure:tet.max_boundary_facet_circumradius", "<=", 0.5 + 1e-9],
            ["output:geometry:measure:tet.max_circumradius", "<=", 0.6 + 1e-9],
            ["output:geometry:measure:tet.max_radius_edge", "<=", 3.0 + 1e-9],
        ]),
        _case("volume-sphere-fine", VOL_GEN, [_surface(DOM_SPHERE)], _vol(25.0, 0.3, 0.02, 2.5, 0.3), [
            *_volume_checks(),
            ["metrics.tetrahedron_count", ">=", 2000],
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.volume", "approx", [32.0 * PI / 3.0, 0.04 * 32.0 * PI / 3.0]],
            ["output:geometry:measure:tet.boundary_area", "approx", [16.0 * PI, 0.02 * 16.0 * PI]],
            ["output:geometry:measure:tet.max_circumradius", "<=", 0.3 + 1e-9],
            ["output:geometry:measure:tet.max_radius_edge", "<=", 2.5 + 1e-9],
            ["output:geometry:measure:tet.max_boundary_facet_circumradius", "<=", 0.3 + 1e-9],
        ]),
        _case("volume-sphere-r25", VOL_GEN, [_surface(DOM_SPHERE_R25)], _vol(25.0, 0.5, 0.05, 3.0, 0.6), [
            *_volume_checks(),
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.min_boundary_vertex_radius", "approx", [2.5, 1e-6]],
            ["output:geometry:measure:tet.max_boundary_vertex_radius", "approx", [2.5, 1e-6]],
            ["output:geometry:measure:tet.volume", "approx", [4.0 / 3.0 * PI * 15.625,
                                                             0.08 * 4.0 / 3.0 * PI * 15.625]],
        ]),
        _case("volume-ellipsoid", VOL_GEN, [_surface(DOM_ELLIPSOID)], _vol(25.0, 0.6, 0.04, 3.0, 0.8), [
            *_volume_checks(),
            ["metrics.domain_kind", "==", "ellipsoid"],
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.max_boundary_ellipsoid_residual(3,2,1.5)", "approx", [0.0, 1e-6]],
            ["output:geometry:measure:tet.volume", "approx", [4.0 / 3.0 * PI * 9.0, 0.08 * 4.0 / 3.0 * PI * 9.0]],
            ["output:geometry:measure:tet.boundary_area", "approx", [ELLIPSOID_AREA, 0.04 * ELLIPSOID_AREA]],
            ["output:geometry:measure:tet.min_boundary_facet_angle", ">=", 25.0],
            ["output:geometry:measure:tet.max_circumradius", "<=", 0.8 + 1e-9],
            ["output:geometry:measure:tet.max_radius_edge", "<=", 3.0 + 1e-9],
        ]),
        _case("volume-torus", VOL_GEN, [_surface(DOM_TORUS)], _vol(25.0, 0.5, 0.03, 3.0, 0.6), [
            *_volume_checks(),
            ["metrics.domain_kind", "==", "torus"],
            ["output:geometry:measure:tet.euler_characteristic", "==", 0],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 0],
            ["output:geometry:measure:tet.max_boundary_torus_residual(3,1)", "approx", [0.0, 1e-6]],
            ["output:geometry:measure:tet.volume", "approx", [6.0 * PI * PI, 0.08 * 6.0 * PI * PI]],
            ["output:geometry:measure:tet.boundary_area", "approx", [12.0 * PI * PI, 0.04 * 12.0 * PI * PI]],
            ["output:geometry:measure:tet.min_boundary_facet_angle", ">=", 25.0],
            ["output:geometry:measure:tet.max_circumradius", "<=", 0.6 + 1e-9],
            ["output:geometry:measure:tet.max_radius_edge", "<=", 3.0 + 1e-9],
        ]),
        _case("volume-poly-cube", VOL_GEN, [_poly(POLY_CUBE)], _vol(25.0, 0.25, 0.02, 3.0, 0.3),
              _poly_checks("poly_cube.off", 1.0, 6.0, 0.02, 0.25, 0.02, 25.0, 3.0, 0.3)),
        _case("volume-poly-cube-fine", VOL_GEN, [_poly(POLY_CUBE)], _vol(25.0, 0.15, 0.01, 2.5, 0.15), [
            *_poly_checks("poly_cube.off", 1.0, 6.0, 0.01, 0.15, 0.01, 25.0, 2.5, 0.15),
            ["metrics.tetrahedron_count", ">=", 2000],
        ]),
        _case("volume-poly-l-prism", VOL_GEN, [_poly(POLY_L_PRISM)], _vol(25.0, 0.4, 0.03, 3.0, 0.5),
              _poly_checks("poly_l_prism.off", 3.0, 14.0, 0.02, 0.4, 0.03, 25.0, 3.0, 0.5)),
        _case("volume-poly-stair-prism", VOL_GEN, [_poly(POLY_STAIR_PRISM)], _vol(25.0, 0.4, 0.03, 3.0, 0.5),
              _poly_checks("poly_stair_prism.off", 6.0, 24.0, 0.02, 0.4, 0.03, 25.0, 3.0, 0.5)),
        _case("volume-poly-tilted-box", VOL_GEN, [_poly(POLY_TILTED_BOX)], _vol(25.0, 0.5, 0.04, 3.0, 0.6),
              _poly_checks("poly_tilted_box.off", 6.0, 22.0, 0.02, 0.5, 0.04, 25.0, 3.0, 0.6)),
        _case("volume-sphere-baseline-box", VOL_GEN, [_surface(DOM_SPHERE)], _vol(25.0, 0.5, 0.05, 3.0, 0.6), [
            *_volume_checks(),
            ["metrics.cell_size_region_count", "==", 0],
            ["output:geometry:measure:tet." + _box_name("max_circumradius_in_box", *SPHERE_BOX), ">", 0.3 + 1e-6],
            ["output:geometry:measure:tet.tetrahedron_count", "<=", 1000],
        ]),
        _case("volume-sphere-regions", VOL_GEN, [_surface(DOM_SPHERE)],
              {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": _regions((*SPHERE_BOX, 0.3))}, [
            *_volume_checks(),
            ["metrics.domain_kind", "==", "sphere"],
            ["metrics.cell_size_region_count", "==", 1],
            ["output:geometry:measure:tet." + _box_name("max_circumradius_in_box", *SPHERE_BOX), "<=", 0.3 + 1e-9],
            ["output:geometry:measure:tet." + _box_name("max_circumradius_outside_box", *SPHERE_BOX), ">", 0.3],
            ["output:geometry:measure:tet." + _box_name("cell_count_in_box", *SPHERE_BOX), ">=", 400],
            ["output:geometry:measure:tet.max_circumradius", "<=", 0.6 + 1e-9],
            ["output:geometry:measure:tet.max_radius_edge", "<=", 3.0 + 1e-9],
            ["output:geometry:measure:tet.tetrahedron_count", ">=", 1200],
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.volume", "approx", [32.0 * PI / 3.0, 0.08 * 32.0 * PI / 3.0]],
        ]),
        *[_case(f"volume-sphere-topology-{tag}", VOL_GEN, [_surface(DOM_SPHERE)],
                {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "facet_topology": topology}, [
            *_volume_checks(),
            ["metrics.facet_topology", "==", topology],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.max_boundary_vertex_radius", "approx", [2.0, 1e-6]],
            ["output:geometry:measure:tet.min_boundary_vertex_radius", "approx", [2.0, 1e-6]],
            ["output:geometry:measure:tet.max_circumradius", "<=", 0.6 + 1e-9],
        ]) for tag, topology in (("surface", "FACET_VERTICES_ON_SURFACE"),
                                 ("patch", "FACET_VERTICES_ON_SAME_SURFACE_PATCH"))],
        _case("volume-poly-cube-edge-size-half", VOL_GEN, [_poly(POLY_CUBE)],
              {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "edge_size": _mm(0.5)}, [
            *_volume_checks("CGAL::Polyhedral_mesh_domain_with_features_3"),
            ["metrics.domain_kind", "==", "polyhedral"],
            ["metrics.feature_protection", "==", True],
            ["metrics.sharp_edge_count", "==", 12],
            ["metrics.edge_size", "==", 0.5],
            ["metrics.source_volume", "approx", [1.0, 1e-9]],
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.volume", "approx", [1.0, 0.02]],
            ["output:geometry:measure:tet.boundary_area", "approx", [6.0, 0.36]],
            ["output:geometry:measure:tet.max_boundary_vertex_distance_to_off(poly_cube.off)", "<=", 1e-9],
            ["output:geometry:measure:tet.max_boundary_sample_distance_to_off(poly_cube.off)", "<=", 0.25],
            ["output:geometry:measure:tet.max_off_sample_distance_to_boundary(poly_cube.off)", "<=", 0.5],
            ["output:geometry:measure:tet.max_cube_edge_vertex_gap", "<=", 0.5 + 1e-9],
            ["output:geometry:measure:tet.max_cube_edge_vertex_gap", ">", 0.25],
            ["output:geometry:measure:tet.max_cube_edge_mesh_segment", "<=", 0.5 + 1e-9],
            ["output:geometry:measure:tet.cube_edge_mesh_segment_count", "==", 36],
        ]),
        _case("volume-poly-cube-edge-size-quarter", VOL_GEN, [_poly(POLY_CUBE)],
              {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "edge_size": _mm(0.25)}, [
            *_volume_checks("CGAL::Polyhedral_mesh_domain_with_features_3"),
            ["metrics.domain_kind", "==", "polyhedral"],
            ["metrics.feature_protection", "==", True],
            ["metrics.sharp_edge_count", "==", 12],
            ["metrics.edge_size", "==", 0.25],
            ["metrics.source_volume", "approx", [1.0, 1e-9]],
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.volume", "approx", [1.0, 0.02]],
            ["output:geometry:measure:tet.boundary_area", "approx", [6.0, 0.36]],
            ["output:geometry:measure:tet.max_boundary_vertex_distance_to_off(poly_cube.off)", "<=", 1e-9],
            ["output:geometry:measure:tet.max_boundary_sample_distance_to_off(poly_cube.off)", "<=", 0.25],
            ["output:geometry:measure:tet.max_off_sample_distance_to_boundary(poly_cube.off)", "<=", 0.5],
            ["output:geometry:measure:tet.max_cube_edge_vertex_gap", "<=", 0.25 + 1e-9],
            ["output:geometry:measure:tet.max_cube_edge_vertex_gap", ">", 0.125],
            ["output:geometry:measure:tet.max_cube_edge_mesh_segment", "<=", 0.25 + 1e-9],
            ["output:geometry:measure:tet.cube_edge_mesh_segment_count", "==", 48],
        ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["volume-sphere", "volume-sphere-regions"]},
        {"kind": "different_outputs", "cases": ["volume-poly-cube", "volume-poly-cube-edge-size-half"]},
        {"kind": "different_outputs", "cases": ["volume-poly-cube-edge-size-half", "volume-poly-cube-edge-size-quarter"]},
        {"kind": "different_outputs", "cases": ["volume-poly-cube", "volume-poly-cube-fine"]},
        {"kind": "different_outputs", "cases": ["surface-sphere", "surface-sphere-fine"]},
        {"kind": "different_outputs", "cases": ["volume-sphere", "volume-sphere-fine"]},
        {"kind": "different_outputs", "cases": ["mesh2-square-size2", "mesh2-square-size1"]},
        {"kind": "different_outputs", "cases": ["mesh2-rect-unrefined", "mesh2-rect-refined"]},
    ],
    "negative_controls": [
        {"id": "surface-expression-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_EXPRESSION)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "UNSUPPORTED_DOMAIN_KIND"},
        {"id": "surface-unknown-kind-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_UNKNOWN_KIND)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "UNSUPPORTED_DOMAIN_KIND"},
        {"id": "surface-negative-radius-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_NEGATIVE_RADIUS)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "INVALID_DOMAIN"},
        {"id": "surface-extra-parameter-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_EXTRA_PARAMETER)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "SCHEMA_MISMATCH"},
        {"id": "surface-thick-torus-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_THICK_TORUS)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "INVALID_DOMAIN"},
        {"id": "surface-needle-ellipsoid-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_NEEDLE_ELLIPSOID)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "INVALID_DOMAIN"},
        {"id": "surface-angle-above-guarantee-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _surf(31.0, 0.5, 0.05),
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "surface-distance-too-coarse-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.5),
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "surface-unit-mismatch-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_SPHERE)],
         "parameters": {"angle_bound": 25.0, "size_bound": {"value": 0.5, "unit": "cm"},
                        "distance_bound": _mm(0.05)},
         "expect_error_class": "TYPE_ERROR", "expect_error_code": "UNIT_MISMATCH"},
        {"id": "surface-size-budget-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.01, 0.0001),
         "expect_error_class": "RESOURCE_LIMIT", "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
        {"id": "surface-missing-triangle-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_MISSING), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SURFACE_NOT_CLOSED"},
        {"id": "surface-flipped-one-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_FLIPPED_ONE), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "INCONSISTENT_ORIENTATION"},
        {"id": "surface-flipped-all-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_FLIPPED_ALL), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "ORIENTATION_NOT_OUTWARD"},
        {"id": "surface-duplicate-face-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_DUPLICATE), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "NON_MANIFOLD_EDGE"},
        {"id": "surface-scaled-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SCALED), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "surface-wrong-radius-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SPHERE_MESH), _surface(DOM_SPHERE_R25)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "surface-sphere-vs-ellipsoid-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SPHERE_MESH), _surface(DOM_ELLIPSOID)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "surface-sphere-vs-torus-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SPHERE_MESH), _surface(DOM_TORUS)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "EULER_CHARACTERISTIC_MISMATCH"},
        {"id": "surface-torus-vs-sphere-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_TORUS_MESH), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "EULER_CHARACTERISTIC_MISMATCH"},
        {"id": "surface-ellipsoid-vs-sphere-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_ELLIPSOID_MESH), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.6, 0.04),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "surface-stricter-angle-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _surf(35.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "ANGLE_CRITERION_VIOLATED"},
        {"id": "surface-stricter-size-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.2, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SIZE_CRITERION_VIOLATED"},
        {"id": "surface-stricter-distance-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.02),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "DISTANCE_CRITERION_VIOLATED"},
        {"id": "surface-coarse-octahedron-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_OCTAHEDRON), _surface(DOM_SPHERE)], "parameters": _surf(30.0, 5.0, 5.0),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "AREA_MISMATCH"},
        {"id": "volume-expression-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_EXPRESSION)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "UNSUPPORTED_DOMAIN_KIND"},
        {"id": "volume-unknown-kind-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_UNKNOWN_KIND)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "UNSUPPORTED_DOMAIN_KIND"},
        {"id": "volume-negative-radius-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_NEGATIVE_RADIUS)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "INVALID_DOMAIN"},
        {"id": "volume-extra-parameter-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_EXTRA_PARAMETER)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "SCHEMA_MISMATCH"},
        {"id": "volume-thick-torus-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_THICK_TORUS)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "INVALID_DOMAIN"},
        {"id": "volume-needle-ellipsoid-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_NEEDLE_ELLIPSOID)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "INVALID_DOMAIN"},
        {"id": "volume-angle-above-guarantee-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _vol(31.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-radius-edge-below-guarantee-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 1.99, 0.6),
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-distance-too-coarse-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.5, 3.0, 0.6),
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-size-budget-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.05),
         "expect_error_class": "RESOURCE_LIMIT", "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
        {"id": "volume-unit-mismatch-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size": {"value": 0.6, "unit": "cm"}},
         "expect_error_class": "TYPE_ERROR", "expect_error_code": "UNIT_MISMATCH"},
        {"id": "volume-missing-interior-cell-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_MISSING_INTERIOR), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "MULTIPLE_BOUNDARY_SURFACES"},
        {"id": "volume-missing-boundary-cell-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_MISSING_BOUNDARY), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-flipped-cell-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_FLIPPED), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "INVERTED_TETRAHEDRON"},
        {"id": "volume-duplicate-cell-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_DUPLICATE), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "NON_MANIFOLD_FACE"},
        {"id": "volume-scaled-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SCALED), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OUTSIDE_DOMAIN"},
        {"id": "volume-two-subdomains-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_TWO_SUBDOMAINS), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SUBDOMAIN_INDEX_INVALID"},
        {"id": "volume-wrong-radius-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE_R25)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-sphere-vs-ellipsoid-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_ELLIPSOID)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OUTSIDE_DOMAIN"},
        {"id": "volume-sphere-vs-torus-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_TORUS)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "EULER_CHARACTERISTIC_MISMATCH"},
        {"id": "volume-torus-vs-sphere-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_TORUS_MESH), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "EULER_CHARACTERISTIC_MISMATCH"},
        {"id": "volume-ellipsoid-vs-sphere-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_ELLIPSOID_MESH), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.6, 0.04, 3.0, 0.8),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OUTSIDE_DOMAIN"},
        {"id": "volume-stricter-facet-angle-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _vol(35.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_ANGLE_VIOLATED"},
        {"id": "volume-stricter-facet-size-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.3, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_SIZE_VIOLATED"},
        {"id": "volume-stricter-facet-distance-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.02, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_DISTANCE_VIOLATED"},
        {"id": "volume-stricter-cell-size-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.4),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "CELL_SIZE_VIOLATED"},
        {"id": "volume-stricter-radius-edge-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 1.5, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "RADIUS_EDGE_VIOLATED"},
        {"id": "volume-coarse-octahedron-size-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_OCTAHEDRON), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_SIZE_VIOLATED"},
        {"id": "volume-coarse-octahedron-area-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_OCTAHEDRON), _surface(DOM_SPHERE)], "parameters": _vol(30.0, 5.0, 5.0, 100.0, 50.0),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "AREA_MISMATCH"},
        {"id": "volume-poly-open-source-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE_OPEN)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "MESH_NOT_CLOSED"},
        {"id": "volume-poly-open-source-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE_OPEN)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_MESH_NOT_CLOSED"},
        {"id": "volume-poly-inverted-source-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE_INVERTED)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "INWARD_ORIENTED_INPUT"},
        {"id": "volume-poly-inverted-source-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE_INVERTED)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_INWARD_ORIENTED_INPUT"},
        {"id": "volume-poly-inconsistent-source-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE_INCONSISTENT)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "INCONSISTENT_ORIENTATION"},
        {"id": "volume-poly-inconsistent-source-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE_INCONSISTENT)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_INCONSISTENT_ORIENTATION"},
        {"id": "volume-poly-self-intersecting-source-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE_SELF_INTERSECTING)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "SELF_INTERSECTING_INPUT"},
        {"id": "volume-poly-self-intersecting-source-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE_SELF_INTERSECTING)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_SELF_INTERSECTING_INPUT"},
        {"id": "volume-poly-two-components-source-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_TWO_CUBES)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "MULTIPLE_COMPONENTS"},
        {"id": "volume-poly-two-components-source-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_TWO_CUBES)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_MULTIPLE_COMPONENTS"},
        {"id": "volume-poly-non-manifold-source-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE_NONMANIFOLD)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "NON_MANIFOLD_INPUT"},
        {"id": "volume-poly-non-manifold-source-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE_NONMANIFOLD)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_NON_MANIFOLD_INPUT"},
        {"id": "volume-poly-missing-interior-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_MISSING_INTERIOR), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "BOUNDARY_NOT_CLOSED"},
        {"id": "volume-poly-missing-boundary-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_MISSING_BOUNDARY), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_DISTANCE_VIOLATED"},
        {"id": "volume-poly-flipped-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_FLIPPED), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "INVERTED_TETRAHEDRON"},
        {"id": "volume-poly-duplicate-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_DUPLICATE), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "NON_MANIFOLD_FACE"},
        {"id": "volume-poly-shifted-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_SHIFTED), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-poly-scaled-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_SCALED), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-poly-bumped-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_BUMPED), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-poly-two-subdomains-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_TWO_SUBDOMAINS), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SUBDOMAIN_INDEX_INVALID"},
        {"id": "volume-poly-cube-vs-l-prism-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_L_PRISM)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-poly-cube-vs-tilted-box-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_TILTED_BOX)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-poly-l-prism-vs-cube-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_L_MESH), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.4, 0.03, 3.0, 0.5),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-poly-partial-fill-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_BOX_IN_L_MESH), _poly(POLY_L_PRISM)], "parameters": _vol(25.0, 0.4, 0.03, 3.0, 0.5),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "ORIENTATION_NOT_OUTWARD"},
        {"id": "volume-poly-stricter-angle-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": _vol(35.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_ANGLE_VIOLATED"},
        {"id": "volume-poly-stricter-size-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.15, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_SIZE_VIOLATED"},
        {"id": "volume-poly-stricter-distance-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.005, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_DISTANCE_VIOLATED"},
        {"id": "volume-poly-stricter-cell-size-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.2),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "CELL_SIZE_VIOLATED"},
        {"id": "volume-poly-stricter-radius-edge-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 1.5, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "RADIUS_EDGE_VIOLATED"},
        {"id": "volume-poly-size-budget-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.0001, 3.0, 0.3),
         "expect_error_class": "RESOURCE_LIMIT", "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
        {"id": "volume-poly-angle-above-guarantee-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE)], "parameters": _vol(31.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-poly-unit-mismatch-rejected", "operation": VOL_GEN,
         "inputs": [{**_poly(POLY_CUBE), "unit": "cm"}], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "TYPE_ERROR", "expect_error_code": "UNIT_MISMATCH"},
        {"id": "volume-region-unrefined-mesh-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": _regions((*SPHERE_BOX, 0.3))},
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "CELL_SIZE_REGION_VIOLATED"},
        {"id": "volume-poly-region-unrefined-mesh-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "cell_size_regions": _regions(((0.0, 0.0, 0.0), (0.5, 0.5, 0.5), 0.1))},
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "CELL_SIZE_REGION_VIOLATED"},
        {"id": "volume-poly-edge-size-unprotected-mesh-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "edge_size": _mm(0.5)},
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FEATURE_EDGE_NOT_PROTECTED"},
        {"id": "volume-poly-edge-size-tightened-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_FEATURES_MESH), _poly(POLY_CUBE)], "parameters": {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "edge_size": _mm(0.25)},
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "EDGE_SIZE_VIOLATED"},
        {"id": "volume-poly-features-mesh-without-edge-size-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_FEATURES_MESH), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_ANGLE_VIOLATED"},
        {"id": "volume-edge-size-implicit-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "edge_size": _mm(0.3)},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "CRITERION_NOT_APPLICABLE"},
        {"id": "volume-edge-size-implicit-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "edge_size": _mm(0.3)},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "CRITERION_NOT_APPLICABLE"},
        {"id": "volume-poly-edge-size-no-sharp-edges-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_ICOSPHERE)], "parameters": {**_vol(25.0, 0.3, 0.02, 3.0, 0.4), "edge_size": _mm(0.3)},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "CRITERION_NOT_APPLICABLE"},
        {"id": "volume-poly-edge-size-patch-topology-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE)], "parameters": {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "edge_size": _mm(0.5), "facet_topology": "FACET_VERTICES_ON_SAME_SURFACE_PATCH"},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "CRITERION_NOT_APPLICABLE"},
        {"id": "volume-poly-edge-size-budget-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE)], "parameters": {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "edge_size": _mm(0.0005)},
         "expect_error_class": "RESOURCE_LIMIT", "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
        {"id": "volume-region-outside-domain-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": _regions(((5.0, 5.0, 5.0), (6.0, 6.0, 6.0), 0.3))},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "REGION_OUTSIDE_DOMAIN"},
        {"id": "volume-region-not-smaller-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": _regions((*SPHERE_BOX, 0.6))},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-region-inverted-box-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": _regions((SPHERE_BOX[1], SPHERE_BOX[0], 0.3))},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-region-too-many-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": _regions(*[(*SPHERE_BOX, 0.3)] * 5)},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-region-empty-list-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": []},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-region-unit-mismatch-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": [{**_regions((*SPHERE_BOX, 0.3))[0], "cell_size": {"value": 0.3, "unit": "cm"}}]},
         "expect_error_class": "TYPE_ERROR", "expect_error_code": "UNIT_MISMATCH"},
        {"id": "volume-region-free-form-key-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": [{**_regions((*SPHERE_BOX, 0.3))[0], "expression": "x*x"}]},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-topology-unknown-value-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "facet_topology": "FACET_VERTICES_ANYWHERE"},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-unknown-criterion-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "mystery_criterion": 1},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "UNSUPPORTED_PARAMETER"},
        {"id": "volume-region-validator-unit-mismatch-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": [{**_regions((*SPHERE_BOX, 0.3))[0], "cell_size": {"value": 0.3, "unit": "cm"}}]},
         "expect_error_class": "TYPE_ERROR", "expect_error_code": "UNIT_MISMATCH"},
        {"id": "mesh2-bowtie-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(BOWTIE)], "parameters": _mesh2(0.125, 2.0),
         "expect_error_class": "PRECONDITION_FAILED",
         "expect_error_code": "SELF_INTERSECTING_DOMAIN"},
        {"id": "mesh2-hole-outside-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(HOLE_OUTSIDE)], "parameters": _mesh2(0.125, 2.0),
         "expect_error_class": "PRECONDITION_FAILED",
         "expect_error_code": "SELF_INTERSECTING_DOMAIN"},
        {"id": "mesh2-hole-touching-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(HOLE_TOUCHING)], "parameters": _mesh2(0.125, 2.0),
         "expect_error_class": "PRECONDITION_FAILED",
         "expect_error_code": "SELF_INTERSECTING_DOMAIN"},
        {"id": "mesh2-hole-far-outside-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(HOLE_FAR_OUTSIDE)], "parameters": _mesh2(0.125, 2.0),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "HOLE_OUTSIDE_DOMAIN"},
        {"id": "mesh2-nested-hole-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(HOLE_NESTED)], "parameters": _mesh2(0.125, 2.0),
         "expect_error_class": "PRECONDITION_FAILED",
         "expect_error_code": "NESTED_HOLE"},
        {"id": "mesh2-aspect-above-guarantee-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(SQUARE_10)], "parameters": _mesh2(0.5, 2.0),
         "expect_error_class": "INVALID_REQUEST",
         "expect_error_code": "INVALID_PARAMETER"},
        {"id": "mesh2-zero-size-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(SQUARE_10)], "parameters": _mesh2(0.125, 0.0),
         "expect_error_class": "INVALID_REQUEST",
         "expect_error_code": "INVALID_PARAMETER"},
        {"id": "mesh2-unit-mismatch-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(SQUARE_10)],
         "parameters": {"aspect_bound": 0.125, "size_bound": {"value": 2.0, "unit": "cm"}},
         "expect_error_class": "TYPE_ERROR",
         "expect_error_code": "UNIT_MISMATCH"},
        {"id": "mesh2-size-budget-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(SQUARE_10)], "parameters": _mesh2(0.125, 0.01),
         "expect_error_class": "RESOURCE_LIMIT",
         "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
        {"id": "mesh2-missing-triangle-rejected", "operation": "mesh.validate.delaunay_refinement_2",
         "inputs": [_json_input(SQUARE_MESH_MISSING, "Triangulation2"), _domain(SQUARE_10)],
         "parameters": _mesh2(0.125, 2.0), "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "EULER_CHARACTERISTIC_MISMATCH"},
        {"id": "mesh2-shifted-boundary-rejected", "operation": "mesh.validate.delaunay_refinement_2",
         "inputs": [_json_input(SQUARE_MESH_SHIFTED, "Triangulation2"), _domain(SQUARE_10)],
         "parameters": _mesh2(0.125, 2.0), "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "CONSTRAINT_NOT_PRESERVED"},
        {"id": "mesh2-flipped-diagonal-rejected", "operation": "mesh.validate.delaunay_refinement_2",
         "inputs": [_json_input(HOLED_MESH_FLIPPED, "Triangulation2"), _domain(HOLE_SQUARE)],
         "parameters": _mesh2(0.001, 50.0), "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "NOT_LOCALLY_DELAUNAY"},
        {"id": "mesh2-stricter-size-rejected", "operation": "mesh.validate.delaunay_refinement_2",
         "inputs": [_json_input(SQUARE_MESH, "Triangulation2"), _domain(SQUARE_10)],
         "parameters": _mesh2(0.125, 0.5), "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "SIZE_CRITERION_VIOLATED"},
        {"id": "mesh2-stricter-aspect-rejected", "operation": "mesh.validate.delaunay_refinement_2",
         "inputs": [_json_input(SQUARE_MESH, "Triangulation2"), _domain(SQUARE_10)],
         "parameters": _mesh2(0.6, 2.0), "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "SHAPE_CRITERION_VIOLATED"},
        {"id": "mesh2-wrong-domain-rejected", "operation": "mesh.validate.delaunay_refinement_2",
         "inputs": [_json_input(SQUARE_MESH, "Triangulation2"), _domain(L_SHAPE)],
         "parameters": _mesh2(0.125, 2.0), "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "DOMAIN_VERTEX_MISSING"},
    ],
}

def _kfx(name: str, sha: str) -> dict:
    return {"fixture": f"kernel/{name}", "sha256": sha}


K_PRIMITIVES = _kfx("primitives.json", "1a9f4ab76ebd3a4e9d2c7a5c32d1e8a3cba4ec495c11810674d515e79715809d")
K_PREDICATES = _kfx("predicates.json", "d7539b43cb71ebc3763be3f82d219627f294e9d19b10baa7921ed9336c66f635")
K_ROBUSTNESS = _kfx("robustness.json", "7a3993562218161ee1e3bced2486e5713b8665ddbac8dcc76d2bd185a57e8cae")
K_INTERSECTIONS = _kfx("intersections.json", "31ffe025532815c5b7e52c3f586d029fcf90085145384766afb1a3cf312243e0")
K_DISTANCES = _kfx("distances.json", "9d1537895b4990cc0c9ceecc4b4f6c57f21f38a3f335c20928e3794e0ad5e18d")
K_COLLINEAR = _kfx("collinear_circumcenter.json", "df062464e9594d835b828197044d7e7a697505a730814b75a432701994e568d8")
K_UNSUPPORTED = _kfx("unsupported_pair.json", "b93850e03b83b9f065b77914843f9124e289b4d9e68580b34d09fedb25d9e081")
K_TAMPERED = {
    "primitives": _kfx("tampered_primitives_report.json",
                       "235cc74fc24a0dedcb2d70092cd0c83caa7a5cb2807e30ae974989cd93f9f320"),
    "predicates": _kfx("tampered_predicates_report.json",
                       "d90b72a2956772070d4fd6c42edeeb170899ffc3ba5599c306caf4fd643f300d"),
    "robustness": _kfx("tampered_robustness_report.json",
                       "de707aaf94f58019557de540896bb2e374554b83fabf64683e22afd6415cd214"),
    "intersections": _kfx("tampered_intersections_report.json",
                          "eaf43580fd50be9004ab4dcdb692004f2b30744a70b80c09ea4444a0a3497c43"),
    "distances": _kfx("tampered_distances_report.json",
                      "d5c6031be8eafca4898cea1a79ede060df93d381e606d7a69a338a04a091445f"),
}
KERNEL_TYPES = {
    "simple_cartesian_double": "CGAL::Simple_cartesian<double>",
    "cartesian_double": "CGAL::Cartesian<double>",
    "epick": "CGAL::Exact_predicates_inexact_constructions_kernel",
    "epeck": "CGAL::Exact_predicates_exact_constructions_kernel",
}
# Double nearest to 1/3 (the centroid of (0,0),(1,0),(0,1) in every binary64-based kernel).
THIRD_BINARY64 = "6004799503160661/18014398509481984"
PRIMITIVE_KINDS = ["Point_2", "Vector_2", "Segment_2", "Line_2", "Ray_2", "Triangle_2", "Circle_2",
                   "Iso_rectangle_2", "Aff_transformation_2", "Point_3", "Vector_3", "Segment_3", "Line_3",
                   "Ray_3", "Plane_3", "Triangle_3", "Tetrahedron_3", "Sphere_3", "Iso_cuboid_3",
                   "Aff_transformation_3"]
PREDICATE_RESULTS = ["left_turn", "right_turn", "collinear", "positive", "negative", "coplanar",
                     True, False, True, False, True, False, True, False]
PREDICATE_CONSTRUCTIONS_EXACT = [["2", "0"], ["0", "0", "1"], ["4/3", "4/3"], ["1/2", "1/2", "1/2"],
                                 ["2", "2"], ["1", "1", "0"], ["1", "1", "1"]]
INTERSECTION_RESULTS = [
    {"point": ["2", "2"], "type": "point"}, {"points": [["1", "0"], ["2", "0"]], "type": "segment"},
    {"type": "empty"}, True, False,
    {"point": ["1", "1"], "type": "point"}, {"type": "empty"},
    {"coefficients": ["-1", "1", "0"], "type": "line"}, False,
    {"points": [["1", "3"], ["1", "1"], ["3", "1"]], "type": "triangle"},
    {"points": [["0", "3"], ["3/2", "0"], ["3", "0"], ["7/2", "1/2"], ["0", "4"]], "type": "polygon"},
    {"point": ["4", "0"], "type": "point"}, {"points": [["0", "4"], ["4", "0"]], "type": "segment"},
    {"type": "empty"}, True,
    {"point": ["1", "1", "0"], "type": "point"}, {"point": ["1", "1", "0"], "type": "point"},
    {"points": [["0", "0", "0"], ["1", "1", "0"]], "type": "line"}, {"type": "empty"}, False,
    {"point": ["1", "1", "0"], "type": "point"}, {"type": "empty"},
    {"points": [["-1", "1", "0"], ["5", "1", "0"]], "type": "segment"}, True,
    {"points": [["0", "0", "0"], ["0", "-1", "0"]], "type": "line"}, {"type": "empty"},
    {"coefficients": ["0", "0", "1", "0"], "type": "plane"}, False,
    {"point": ["1", "1", "0"], "type": "point"}, {"type": "empty"},
    {"points": [["0", "1", "0"], ["3", "1", "0"]], "type": "segment"}, False,
    {"point": ["1", "1", "0"], "type": "point"}, {"type": "empty"}, True,
    {"point": ["0", "0", "0"], "type": "point"}, {"type": "empty"}, {"type": "empty"},
    {"points": [["0", "0", "0"], ["1", "0", "0"]], "type": "line"}, False,
]
DISTANCE_RESULTS = ["25", "1", "1/2", "2", "4", "0", "9", "2", "3", "9", "9", "18", "1", "2", "4", "1",
                    "smaller", "equal", "larger", "larger"]


def _kq(fixture: dict) -> dict:
    return _json_input(fixture, "KernelQuerySet")


def _kernel_checks(kernel: str, queries: int) -> list[list]:
    exact_predicates = kernel in ("epick", "epeck")
    return [
        ["metrics.kernel", "==", kernel],
        ["metrics.kernel_type", "==", KERNEL_TYPES[kernel]],
        ["metrics.exact_predicates", "==", exact_predicates],
        ["metrics.exact_constructions", "==", kernel == "epeck"],
        ["metrics.query_count", "==", queries],
        ["output:analysis:json:input_representation", "==",
         "exact_rational" if kernel == "epeck" else "binary64_round_to_nearest"],
    ]


def _robustness_case(kernel: str) -> dict:
    exact_predicates = kernel in ("epick", "epeck")
    third = "1/3" if kernel == "epeck" else THIRD_BINARY64
    return _case(f"kernel-robustness-{kernel}", "kernel.predicates.evaluate", [_kq(K_ROBUSTNESS)],
                 {"kernel": kernel}, _kernel_checks(kernel, 3) + [
                     ["output:analysis:json:results.queries[*].result", "==",
                      ["left_turn" if exact_predicates else "right_turn", exact_predicates, [third, third]]],
                 ])


FAMILY_7_1 = {
    "family": "7.1",
    "scope": "family_7_1_geometry_kernel",
    "evidence_path": "docs/master/evidence/family-7.1-capabilities.json",
    "test_id": "family-7.1-replay-cases",
    "requirements": {
        "major.7.1.01": {
            "operation_ids": ["kernel.predicates.evaluate"],
            "symbols": ["Simple_cartesian", "Cartesian", "Exact_predicates_inexact_constructions_kernel",
                        "Exact_predicates_exact_constructions_kernel"],
            "symbol_notes": "The same exact-dyadic input (p = ((2^51+21)/2^52, (2^51+24)/2^52), q = (12,12), "
                            "r = (24,24); exact orientation is a left turn) is evaluated in all four kernels. "
                            "Simple_cartesian<double> and Cartesian<double> return the floating-point answer "
                            "right_turn; EPICK and EPECK return the exact left_turn. The centroid of (0,0),(1,0),"
                            "(0,1) is the binary64 value nearest 1/3 in the three double-based kernels and exactly "
                            "1/3 only in EPECK. Each report is checked by an independent GMP-rational validator; a "
                            "report that claims the floating-point answer for EPICK is rejected.",
            "case_ids": [f"kernel-robustness-{k}" for k in KERNEL_TYPES],
        },
        "major.7.1.02": {
            "operation_ids": ["kernel.primitives.construct"],
            "symbols": ["Point_2", "Point_3", "Vector_2", "Vector_3", "Line_2", "Line_3", "Ray_2", "Ray_3",
                        "Segment_2", "Segment_3", "Plane_3", "Circle_2", "Sphere_3", "Triangle_2", "Triangle_3",
                        "Tetrahedron_3", "Iso_rectangle_2", "Iso_cuboid_3", "Aff_transformation_2",
                        "Aff_transformation_3"],
            "symbol_notes": "One fixture holds one primitive of each of the 20 kinds plus affine images of 2D/3D "
                            "points and vectors. Hand-derived exact values are pinned in EPECK (tetrahedron volume "
                            "1/6, plane z=1, iso-cuboid volume 18, transformed point (5/2,-5/3)); the "
                            "Simple_cartesian case shows the same kinds and integer results in binary64. Every "
                            "derived property is recomputed by the independent rational validator.",
            "case_ids": ["kernel-primitives-epeck", "kernel-primitives-simple-cartesian"],
        },
        "major.7.1.03": {
            "operation_ids": ["kernel.predicates.evaluate"],
            "symbols": ["orientation", "collinear", "coplanar", "left_turn", "right_turn", "midpoint",
                        "centroid", "circumcenter"],
            "symbol_notes": "2D/3D orientation (all three signs), collinear, coplanar, left_turn and right_turn "
                            "with true and false answers, and midpoint, centroid and circumcenter (2D, 3D from 3 "
                            "and from 4 points) with hand-derived exact results.",
            "case_ids": ["kernel-predicates-epeck", "kernel-predicates-epick"],
        },
        "major.7.1.04": {
            "operation_ids": ["kernel.intersections.compute"],
            "symbols": ["intersection", "do_intersect"],
            "symbol_notes": "Segment/segment, line/line and triangle/triangle in 2D and line/plane, segment/"
                            "plane, plane/plane, segment/triangle, ray/triangle and line/line in 3D, covering "
                            "point, segment, line, plane, triangle, polygon and empty results plus do_intersect "
                            "true/false. Results are re-derived by exact parametric and half-plane clipping "
                            "formulas in the validator.",
            "case_ids": ["kernel-intersections-epeck", "kernel-intersections-epick"],
        },
        "major.7.1.05": {
            "operation_ids": ["kernel.distance.squared"],
            "symbols": ["squared_distance", "compare_distance", "compare_distance_to_point"],
            "symbol_notes": "squared_distance for point/point, point/line, point/segment and segment/segment in "
                            "2D and point/point, point/line, point/segment, point/plane, point/triangle (interior "
                            "and edge region), segment/segment (interior and endpoint) and line/line (skew and "
                            "parallel) in 3D, plus compare_distance and compare_distance_to_point with smaller/"
                            "equal/larger outcomes; hand-derived values are pinned.",
            "case_ids": ["kernel-distances-epeck", "kernel-distances-simple-cartesian"],
        },
    },
    "unbound": {},
    "cases": [
        *[_robustness_case(kernel) for kernel in KERNEL_TYPES],
        _case("kernel-primitives-epeck", "kernel.primitives.construct", [_kq(K_PRIMITIVES)], {"kernel": "epeck"},
              _kernel_checks("epeck", 4) + [
                  ["metrics.primitive_count", "==", 20],
                  ["output:analysis:json:results.primitives[*].kind", "==", PRIMITIVE_KINDS],
                  ["output:analysis:json:results.primitives.16.signed_volume", "==", "1/6"],
                  ["output:analysis:json:results.primitives.16.orientation", "==", "positive"],
                  ["output:analysis:json:results.primitives.14.coefficients", "==", ["0", "0", "1", "-1"]],
                  ["output:analysis:json:results.primitives.18.volume", "==", "18"],
                  ["output:analysis:json:results.primitives.5.signed_area", "==", "6"],
                  ["output:analysis:json:results.primitives.15.squared_area", "==", "4"],
                  ["output:analysis:json:results.primitives.17.squared_radius", "==", "9/4"],
                  ["output:analysis:json:results.primitives.0.coordinates", "==", ["1/3", "5/2"]],
                  ["output:analysis:json:results.queries[*].result", "==", [
                      {"coordinates": ["5/2", "-5/3"], "kind": "Point_2"},
                      {"coordinates": ["4", "3"], "kind": "Vector_2"},
                      {"coordinates": ["3", "4", "5"], "kind": "Point_3"},
                      {"coordinates": ["2", "-4", "4"], "kind": "Vector_3"}]],
              ]),
        _case("kernel-primitives-simple-cartesian", "kernel.primitives.construct", [_kq(K_PRIMITIVES)],
              {"kernel": "simple_cartesian_double"}, _kernel_checks("simple_cartesian_double", 4) + [
                  ["output:analysis:json:results.primitives[*].kind", "==", PRIMITIVE_KINDS],
                  ["output:analysis:json:results.primitives.14.coefficients", "==", ["0", "0", "1", "-1"]],
                  ["output:analysis:json:results.primitives.18.volume", "==", "18"],
                  ["output:analysis:json:results.queries.2.result.coordinates", "==", ["3", "4", "5"]],
              ]),
        _case("kernel-predicates-epeck", "kernel.predicates.evaluate", [_kq(K_PREDICATES)], {"kernel": "epeck"},
              _kernel_checks("epeck", 21) + [
                  ["output:analysis:json:results.queries[*].result", "==",
                   PREDICATE_RESULTS + PREDICATE_CONSTRUCTIONS_EXACT],
              ]),
        _case("kernel-predicates-epick", "kernel.predicates.evaluate", [_kq(K_PREDICATES)], {"kernel": "epick"},
              _kernel_checks("epick", 21) + [
                  *[[f"output:analysis:json:results.queries.{index}.result", "==", value]
                    for index, value in enumerate(PREDICATE_RESULTS)],
                  ["output:analysis:json:results.queries.18.result", "==", ["2", "2"]],
                  ["output:analysis:json:results.queries.20.result", "==", ["1", "1", "1"]],
              ]),
        _case("kernel-intersections-epeck", "kernel.intersections.compute", [_kq(K_INTERSECTIONS)],
              {"kernel": "epeck"}, _kernel_checks("epeck", 40) + [
                  ["output:analysis:json:results.queries[*].result", "==", INTERSECTION_RESULTS],
              ]),
        _case("kernel-intersections-epick", "kernel.intersections.compute", [_kq(K_INTERSECTIONS)],
              {"kernel": "epick"}, _kernel_checks("epick", 40) + [
                  ["output:analysis:json:results.queries[*].result", "==", INTERSECTION_RESULTS],
              ]),
        _case("kernel-distances-epeck", "kernel.distance.squared", [_kq(K_DISTANCES)], {"kernel": "epeck"},
              _kernel_checks("epeck", 20) + [
                  ["output:analysis:json:results.queries[*].result", "==", DISTANCE_RESULTS],
              ]),
        _case("kernel-distances-simple-cartesian", "kernel.distance.squared", [_kq(K_DISTANCES)],
              {"kernel": "simple_cartesian_double"}, _kernel_checks("simple_cartesian_double", 20) + [
                  ["output:analysis:json:results.queries[*].result", "==", DISTANCE_RESULTS],
              ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["kernel-robustness-simple_cartesian_double",
                                                "kernel-robustness-epick"]},
        {"kind": "different_outputs", "cases": ["kernel-robustness-epick", "kernel-robustness-epeck"]},
    ],
    "negative_controls": [
        {"id": "kernel-circumcenter-collinear-rejected", "operation": "kernel.predicates.evaluate",
         "inputs": [_kq(K_COLLINEAR)], "parameters": {"kernel": "epeck"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "DEGENERATE_CONFIGURATION"},
        {"id": "kernel-intersection-unsupported-pair-rejected", "operation": "kernel.intersections.compute",
         "inputs": [_kq(K_UNSUPPORTED)], "parameters": {"kernel": "epeck"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "UNSUPPORTED_PRIMITIVE_PAIR"},
        {"id": "kernel-intersection-inexact-kernel-rejected", "operation": "kernel.intersections.compute",
         "inputs": [_kq(K_INTERSECTIONS)], "parameters": {"kernel": "simple_cartesian_double"},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "kernel-primitives-tampered-volume-rejected", "operation": "kernel.validate.primitives_report",
         "inputs": [_json_input(K_TAMPERED["primitives"], "KernelReport", "none"), _kq(K_PRIMITIVES)],
         "parameters": {"kernel": "epeck"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "CONSTRUCTION_MISMATCH"},
        {"id": "kernel-predicates-tampered-circumcenter-rejected",
         "operation": "kernel.validate.predicates_report",
         "inputs": [_json_input(K_TAMPERED["predicates"], "KernelReport", "none"), _kq(K_PREDICATES)],
         "parameters": {"kernel": "epeck"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "CONSTRUCTION_MISMATCH"},
        {"id": "kernel-epick-floating-orientation-rejected", "operation": "kernel.validate.predicates_report",
         "inputs": [_json_input(K_TAMPERED["robustness"], "KernelReport", "none"), _kq(K_ROBUSTNESS)],
         "parameters": {"kernel": "epick"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "PREDICATE_MISMATCH"},
        {"id": "kernel-intersections-tampered-vertex-rejected",
         "operation": "kernel.validate.intersections_report",
         "inputs": [_json_input(K_TAMPERED["intersections"], "KernelReport", "none"), _kq(K_INTERSECTIONS)],
         "parameters": {"kernel": "epeck"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "INTERSECTION_MISMATCH"},
        {"id": "kernel-distances-tampered-value-rejected", "operation": "kernel.validate.distances_report",
         "inputs": [_json_input(K_TAMPERED["distances"], "KernelReport", "none"), _kq(K_DISTANCES)],
         "parameters": {"kernel": "epeck"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "CONSTRUCTION_MISMATCH"},
    ],
}

def _ofx(name: str, sha: str) -> dict:
    return {"fixture": f"optimization/{name}", "sha256": sha}


O_LP_OPTIMAL = _ofx("lp_optimal.json", "39f216d1cb4b671dcfc907fdc2f75238522b2e7f13ff0e6fb49937ddd8f56f3f")
O_LP_INFEASIBLE = _ofx("lp_infeasible.json", "06ea282e24c6a0ddacb787b0f25b705ccadca9fd3bd3fd5993687c73e548c3ff")
O_LP_UNBOUNDED = _ofx("lp_unbounded.json", "e0c7aedf77ab751f2a89dbf663bba48d2e15a569afb1bdc2b8c6fd7531524bd9")
O_QP_OPTIMAL = _ofx("qp_optimal.json", "44c0aa115176621890a8ac784ae1bdc7970f46f6d9dc2ba52d413a7fcf520cae")
O_QP_UNBOUNDED = _ofx("qp_unbounded.json", "44f43f1a37b14952dde7ab5ed2f5f84b5b3a450178fc6a4a9c5d959102d487ac")
O_QP_NONCONVEX = _ofx("qp_nonconvex.json", "fd67140fb8d6d5981ac39427d97203b8df1a83621505099ba3c5c3f883758a17")
O_LINEAR_FIELD = _ofx("interp_linear_field.json", "fcd79ed29c102c4170174b4adbc5247d3ee50be7a9bacad4b121fcff3e2f7054")
O_SPHERICAL_FIELD = _ofx("interp_spherical_field.json",
                         "db1c08c7ccbdb4576df5505edfffbdee8c58a9ddc60bc8995a704292d5f610bc")
O_QUERY_OUTSIDE = _ofx("interp_query_outside.json", "251976708b5c66e9d346b78d4038e40e2344728d67f906c7b15b950983b34e35")
O_COLLINEAR_SITES = _ofx("interp_collinear_sites.json",
                         "2a68c7406297ee269f1ab51d12676b8cd71af1af12d56a5b4b2eafd936cd3f13")
O_LINE_POINTS = _ofx("line_points.json", "d8acf54ec688ae6f8a01532eb79526c1ee0cf503501f6cc8583823c7525e2005")
O_CUBE = _ofx("cube_subdivided.off", "57afc11a0b7d545762e74d8c5fc417dc4d34489829b1b2835a16281879900c79")
O_TAMPERED = {
    "lp": _ofx("tampered_lp_report.json", "863221837d76cb39bedb9f769480719c03512e92a90df11fa7e1c21dd23ea830"),
    "interpolation": _ofx("tampered_interpolation_report.json",
                          "d48fa2eccd939e10aa4783ddbc46aefd5a3474680cb66f0753cca5cb27df0665"),
    "approximation": _ofx("tampered_approximation_report.json",
                          "e53254224cc276d883f7a90ffc819008b4979c3f95686e909a9e40fd7b8e1a76"),
    "matrix_search": _ofx("tampered_matrix_search_report.json",
                          "9013236ae6abf263451c793c47a9a0cfea4f365cacad7230c702c407d9b238fd"),
}
QP_SOLVER_GMPQ = "CGAL::solve_{}_program on CGAL::Quadratic_program<CGAL::Gmpq>"
VSA_FINE = {"max_number_of_proxies": 12, "number_of_iterations": 20, "seeding": "hierarchical"}
VSA_COARSE = {"max_number_of_proxies": 3, "number_of_iterations": 20, "seeding": "incremental"}


def _qp(fixture: dict) -> dict:
    return _json_input(fixture, "QuadraticProgram", "none")


def _program_case(case_id: str, fixture: dict, solver: str, status: str, extra: list[list]) -> dict:
    return _case(case_id, "optimization.quadratic_program", [_qp(fixture)], {"solver": solver}, [
        ["metrics.solver", "==", solver],
        ["metrics.algorithm", "==", QP_SOLVER_GMPQ.format(solver)],
        ["metrics.exact_number_type", "==", "CGAL::Gmpq"],
        ["metrics.status", "==", status],
        ["output:analysis:json:report_kind", "==", "quadratic_program"],
        ["output:analysis:json:results.status", "==", status],
        ["output:analysis:json:results.certificate.kind", "==",
         {"optimal": "optimality", "infeasible": "infeasibility", "unbounded": "unboundedness"}[status]],
    ] + extra)


def _interpolation_case(case_id: str, fixture: dict, method: str, values: list[str]) -> dict:
    kernel = ("CGAL::Exact_predicates_exact_constructions_kernel" if method == "linear"
              else "CGAL::Exact_predicates_inexact_constructions_kernel")
    function = "linear_interpolation" if method == "linear" else "sibson_c1_interpolation"
    return _case(case_id, "optimization.interpolate", [_json_input(fixture, "InterpolationData2")],
                 {"method": method}, [
                     ["metrics.method", "==", method],
                     ["metrics.kernel", "==", kernel],
                     ["metrics.algorithm", "==", f"CGAL::natural_neighbor_coordinates_2 + CGAL::{function}"],
                     ["metrics.site_count", "==", 13],
                     ["metrics.query_count", "==", 5],
                     ["output:analysis:json:results.input_representation", "==",
                      "exact_rational" if method == "linear" else "binary64_round_to_nearest"],
                     ["output:analysis:json:results.queries[*].value", "==", values],
                     ["output:analysis:json:results.queries.4.neighbors", "==", [{"coordinate": "1", "site": 10}]],
                 ])


FAMILY_7_15 = {
    "family": "7.15",
    "scope": "family_7_15_optimization_numerical_geometry",
    "evidence_path": "docs/master/evidence/family-7.15-capabilities.json",
    "test_id": "family-7.15-replay-cases",
    "requirements": {
        "major.7.15.01": {
            "operation_ids": ["optimization.quadratic_program"],
            "symbols": ["Quadratic_program", "solve_linear_program", "solve_quadratic_program"],
            "symbol_notes": "Programs are built as CGAL::Quadratic_program<CGAL::Gmpq> (A, b, relations, finite "
                            "and infinite bounds, c, c0, 2D) and solved exactly. solve_linear_program yields an "
                            "optimal LP (x = (8/5, 6/5, 8/5), objective -14/5, an equality row and a free "
                            "variable), an infeasible LP and an unbounded LP; solve_quadratic_program yields the "
                            "manual's first_qp optimum (2, 3) with objective 8 and an unbounded convex QP. The "
                            "independent GMP validator checks primal feasibility, convexity (exact LDL^T) and the "
                            "solver's optimality/Farkas/unboundedness certificate against the QP_solver manual's "
                            "lemmas; a non-PSD D and a quadratic program sent to the LP solver are rejected.",
            "case_ids": ["optimization-lp-optimal", "optimization-lp-infeasible", "optimization-lp-unbounded",
                         "optimization-qp-optimal", "optimization-qp-unbounded"],
        },
        "major.7.15.02": {
            "operation_ids": ["optimization.interpolate"],
            "symbols": ["natural_neighbor_coordinates_2", "linear_interpolation", "sibson_c1_interpolation"],
            "symbol_notes": "13 scattered sites with values and gradients; natural_neighbor_coordinates_2 on a "
                            "Delaunay_triangulation_2 feeds linear_interpolation (EPECK, exact rationals: it "
                            "reproduces the linear field 2 + 3x - y exactly) and sibson_c1_interpolation (EPICK, "
                            "with gradients: it reproduces the spherical quadratic 1/4 + 1.3x - 0.7y + 0.2(x^2+y^2) "
                            "to rounding, which linear interpolation does not). The validator recomputes every "
                            "natural-neighbour coordinate as an exact Voronoi-area ratio and re-evaluates both "
                            "interpolants; queries outside the hull and collinear sites are rejected.",
            "case_ids": ["optimization-interpolation-linear-exact", "optimization-interpolation-sibson-c1",
                         "optimization-interpolation-linear-on-quadratic"],
        },
        "major.7.15.03": {
            "operation_ids": ["optimization.approximate_mesh"],
            "symbols": ["approximate_triangle_mesh"],
            "symbol_notes": "Surface_mesh_approximation::approximate_triangle_mesh (Variational Shape "
                            "Approximation, L21 metric) on a subdivided 48-face cube: 12 hierarchical proxies fit "
                            "the six planes with zero L21 error and an anchor mesh lying on the source, while 3 "
                            "incremental proxies leave a positive squared L21 error (unit mm2). The validator "
                            "recomputes the partition, patch connectivity, area-weighted proxy normals, the "
                            "squared error, output-mesh validity and anchor deviation; too many proxies and a "
                            "tampered proxy are rejected.",
            "case_ids": ["optimization-vsa-fine", "optimization-vsa-coarse"],
        },
        "major.7.15.04": {
            "operation_ids": ["optimization.matrix_search"],
            "symbols": ["sorted_matrix_search"],
            "symbol_notes": "The 1D interval p-center problem is solved by sorted_matrix_search over a "
                            "Cartesian_matrix of exact pairwise gaps (row- and column-sorted) with a greedy cover "
                            "feasibility predicate: 12 points need diameter 9 for p = 3 and 7 for p = 4. The "
                            "validator scans every candidate gap exactly to confirm feasibility and minimality "
                            "and checks the reported centers cover every point; p >= n and a tampered optimum "
                            "are rejected.",
            "case_ids": ["optimization-p-center-3", "optimization-p-center-4"],
        },
    },
    "unbound": {},
    "cases": [
        _program_case("optimization-lp-optimal", O_LP_OPTIMAL, "linear", "optimal", [
            ["metrics.objective_value", "==", "-14/5"],
            ["output:analysis:json:results.variable_values", "==", ["8/5", "6/5", "8/5"]],
            ["output:analysis:json:results.objective_value", "==", "-14/5"],
        ]),
        _program_case("optimization-lp-infeasible", O_LP_INFEASIBLE, "linear", "infeasible", [
            ["output:analysis:json:results.variable_values", "==", None],
            ["output:analysis:json:results.objective_value", "==", None],
        ]),
        _program_case("optimization-lp-unbounded", O_LP_UNBOUNDED, "linear", "unbounded", [
            ["output:analysis:json:results.objective_value", "==", None],
        ]),
        _program_case("optimization-qp-optimal", O_QP_OPTIMAL, "quadratic", "optimal", [
            ["output:analysis:json:results.variable_values", "==", ["2", "3"]],
            ["output:analysis:json:results.objective_value", "==", "8"],
        ]),
        _program_case("optimization-qp-unbounded", O_QP_UNBOUNDED, "quadratic", "unbounded", [
            ["output:analysis:json:results.objective_value", "==", None],
        ]),
        _interpolation_case("optimization-interpolation-linear-exact", O_LINEAR_FIELD, "linear",
                            ["51/10", "1", "32/5", "10", "25/4"]),
        _interpolation_case("optimization-interpolation-sibson-c1", O_SPHERICAL_FIELD, "sibson_c1",
                            ["4643211215818981/2251799813685248", "950759921333771/9007199254740992",
                             "2534400690302747/562949953421312", "6136154492292299/1125899906842624",
                             "6839841934068941/2251799813685248"]),
        _interpolation_case("optimization-interpolation-linear-on-quadratic", O_SPHERICAL_FIELD, "linear",
                            ["10777359153449/4860199956600", "4545973641103/17660716152000",
                             "189707811510337/41238365474800", "135747/24280", "243/80"]),
        _case("optimization-vsa-fine", "optimization.approximate_mesh", [_mesh(O_CUBE)], VSA_FINE, [
            ["metrics.proxy_count", "==", 12],
            ["metrics.is_manifold", "==", True],
            ["metrics.l21_error", "approx", [0.0, 1e-12]],
            ["output:analysis:json:results.face_count", "==", 48],
            ["output:analysis:json:results.l21_error.unit", "==", "mm2"],
            ["output:analysis:json:results.l21_error.squared_length", "==", True],
            ["output:analysis:json:results.anchor_max_distance_to_source.value", "approx", [0.0, 1e-12]],
        ]),
        _case("optimization-vsa-coarse", "optimization.approximate_mesh", [_mesh(O_CUBE)], VSA_COARSE, [
            ["metrics.proxy_count", "==", 3],
            ["metrics.l21_error", ">", 1.0],
            ["output:analysis:json:results.face_count", "==", 48],
            ["output:analysis:json:results.l21_error.unit", "==", "mm2"],
        ]),
        _case("optimization-p-center-3", "optimization.matrix_search", [_json_input(O_LINE_POINTS, "PointSet1")],
              {"centers": 3}, [
                  ["metrics.point_count", "==", 12],
                  ["metrics.matrix_dimension", "==", 12],
                  ["output:analysis:json:results.optimal_diameter", "==", "9"],
                  ["output:analysis:json:results.optimal_radius", "==", "9/2"],
                  ["output:analysis:json:results.centers", "==", ["9/2", "17", "53/2"]],
              ]),
        _case("optimization-p-center-4", "optimization.matrix_search", [_json_input(O_LINE_POINTS, "PointSet1")],
              {"centers": 4}, [
                  ["metrics.point_count", "==", 12],
                  ["output:analysis:json:results.optimal_diameter", "==", "7"],
                  ["output:analysis:json:results.optimal_radius", "==", "7/2"],
                  ["output:analysis:json:results.centers", "==", ["7/2", "23/2", "39/2", "67/2"]],
              ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["optimization-interpolation-sibson-c1",
                                                "optimization-interpolation-linear-on-quadratic"]},
        {"kind": "different_outputs", "cases": ["optimization-vsa-fine", "optimization-vsa-coarse"]},
        {"kind": "different_outputs", "cases": ["optimization-p-center-3", "optimization-p-center-4"]},
    ],
    "negative_controls": [
        {"id": "optimization-qp-nonconvex-rejected", "operation": "optimization.quadratic_program",
         "inputs": [_qp(O_QP_NONCONVEX)], "parameters": {"solver": "quadratic"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "NOT_POSITIVE_SEMIDEFINITE"},
        {"id": "optimization-lp-quadratic-term-rejected", "operation": "optimization.quadratic_program",
         "inputs": [_qp(O_QP_OPTIMAL)], "parameters": {"solver": "linear"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "NONZERO_QUADRATIC_TERM"},
        {"id": "optimization-lp-tampered-objective-rejected", "operation": "optimization.validate.quadratic_program",
         "inputs": [_json_input(O_TAMPERED["lp"], "OptimizationReport", "none"), _qp(O_LP_OPTIMAL)],
         "parameters": {"solver": "linear"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "OBJECTIVE_MISMATCH"},
        {"id": "optimization-interpolation-outside-hull-rejected", "operation": "optimization.interpolate",
         "inputs": [_json_input(O_QUERY_OUTSIDE, "InterpolationData2")], "parameters": {"method": "linear"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "QUERY_OUTSIDE_HULL"},
        {"id": "optimization-interpolation-collinear-rejected", "operation": "optimization.interpolate",
         "inputs": [_json_input(O_COLLINEAR_SITES, "InterpolationData2")], "parameters": {"method": "linear"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "DEGENERATE_SITES"},
        {"id": "optimization-interpolation-tampered-value-rejected",
         "operation": "optimization.validate.interpolation",
         "inputs": [_json_input(O_TAMPERED["interpolation"], "OptimizationReport", "none"),
                    _json_input(O_LINEAR_FIELD, "InterpolationData2")],
         "parameters": {"method": "linear"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "INTERPOLATION_MISMATCH"},
        {"id": "optimization-vsa-too-many-proxies-rejected", "operation": "optimization.approximate_mesh",
         "inputs": [_mesh(O_CUBE)], "parameters": {"max_number_of_proxies": 49, "number_of_iterations": 5,
                                                    "seeding": "hierarchical"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "TOO_MANY_PROXIES"},
        {"id": "optimization-vsa-tampered-proxy-rejected", "operation": "optimization.validate.mesh_approximation",
         "inputs": [_json_input(O_TAMPERED["approximation"], "OptimizationReport", "none"), _mesh(O_CUBE)],
         "parameters": VSA_FINE, "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "PROXY_MISMATCH"},
        {"id": "optimization-p-center-trivial-rejected", "operation": "optimization.matrix_search",
         "inputs": [_json_input(O_LINE_POINTS, "PointSet1")], "parameters": {"centers": 12},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "TRIVIAL_CENTER_COUNT"},
        {"id": "optimization-p-center-tampered-optimum-rejected", "operation": "optimization.validate.matrix_search",
         "inputs": [_json_input(O_TAMPERED["matrix_search"], "OptimizationReport", "none"),
                    _json_input(O_LINE_POINTS, "PointSet1")],
         "parameters": {"centers": 3}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "OPTIMUM_MISMATCH"},
    ],
}


def _rfx(name: str, sha: str) -> dict:
    return {"fixture": f"reconstruction/{name}", "sha256": sha}


R_SPHERE_DENSE = _rfx("sphere_dense_normals.ply", "95f3480275a8d98f7ac71a3ead6dc015ea8cf7090f85e31759e309edbedae873")
R_TORUS_NORMALS = _rfx("torus_normals.ply", "105a7aec80dc4270226d68f1e03ca21de00c10ab8f2ce7f859ffe40120b2dd0c")
R_SPHERE_ZERO = _rfx("sphere_zero_normal.ply", "42a4b031f696ca314abc6a694add71096009ed99272a2fbf2c8e73b8847e1b7c")
R_SPHERE_XYZ = _rfx("sphere_points.xyz", "eec51f63b0fd681275fb2cb2039b36f5908d814253d4f0963019e36cd05b6db0")
R_TORUS_XYZ = _rfx("torus_points.xyz", "1b431b05d6b8c211119a08793b2c330ed4982cddb648d1c0751b8dfb3582a4f5")
R_TAMPERED = {
    "poisson_flipped": _rfx("tampered_poisson_flipped.off",
                            "00ace823ccd9ae18dc81058043ab5f40ec1fa338d0be911540af5430728127c8"),
    "poisson_shrunk": _rfx("tampered_poisson_shrunk.off",
                           "9955446bffdb0c7722e0ead7aab7af8ea7f440078417609b3ac42c37fb36cf57"),
    "wrap_shrunk": _rfx("tampered_wrap_shrunk.off",
                        "7b847cabf11a419700223a603cd06b979cb5750865a43007c67f12241036bf7c"),
    "wrap_grown": _rfx("tampered_wrap_grown.off",
                       "557f1674b859cea6ad08842168d3de6befd75e365cd09851b5a2933b208118d3"),
    "wrap_vertex_inside": _rfx("tampered_wrap_vertex_inside.off",
                               "7504c4c5c66f4292d74cf46e05ebdd58fbc9b8c9b6445b988b10bd738f12ad6c"),
}
R_POISSON_SPHERE = {"sm_angle": 20, "sm_radius": 2, "sm_distance": 0.375, "max_deviation": _mm(3.0)}
R_POISSON_TORUS = {"sm_angle": 20, "sm_radius": 2, "sm_distance": 0.375, "max_deviation": _mm(4.0)}
R_POISSON_TORUS_FINE = {"sm_angle": 20, "sm_radius": 1.5, "sm_distance": 0.25, "max_deviation": _mm(4.0)}
R_WRAP_SPHERE = {"alpha": _mm(3.0), "offset": _mm(0.5)}
R_WRAP_TORUS_FINE = {"alpha": _mm(2.5), "offset": _mm(0.5)}
R_WRAP_TORUS_COARSE = {"alpha": _mm(15.0), "offset": _mm(0.5)}
R_SPHERE_VOLUME = 4.0 / 3.0 * math.pi * 1000.0
R_SPHERE_AREA = 4.0 * math.pi * 100.0
R_TORUS_VOLUME = 2.0 * math.pi ** 2 * 10.0 * 16.0
R_TORUS_AREA = 4.0 * math.pi ** 2 * 10.0 * 4.0
R_POISSON_ALGORITHM = "CGAL::Poisson_reconstruction_function + CGAL::make_mesh_3"


def _closed_mesh_checks(euler: int) -> list[list]:
    return [
        ["output:geometry:measure:off.boundary_edge_count", "==", 0],
        ["output:geometry:measure:off.max_face_degree", "==", 3],
        ["output:geometry:measure:off.euler_characteristic", "==", euler],
        ["output:geometry:measure:off.face_count", "==", {"path": "metrics.facet_count"}],
        ["output:geometry:measure:off.vertex_count", "==", {"path": "metrics.vertex_count"}],
        ["metrics.boundary_edge_count", "==", 0],
        ["metrics.euler_characteristic", "==", euler],
    ]


def _poisson_case(case_id: str, fixture: dict, parameters: dict, euler: int, points: int, extra: list[list]) -> dict:
    return _case(case_id, "reconstruction.poisson", [_points(fixture, "PointSet3Normals", "ply")], parameters, [
        ["metrics.algorithm", "==", R_POISSON_ALGORITHM],
        ["metrics.mesh_domain", "==", "CGAL::Poisson_mesh_domain_3"],
        ["metrics.mesh_3_options", "==", "surface_only().manifold()"],
        ["metrics.point_count", "==", points],
        ["input:points:measure:points.count", "==", points],
        ["output:geometry:measure:off.min_angle_degrees", ">=", 19.9],
    ] + _closed_mesh_checks(euler) + extra)


def _wrap_case(case_id: str, fixture: dict, parameters: dict, euler: int, points: int, extra: list[list]) -> dict:
    return _case(case_id, "reconstruction.alpha_wrap", [_points(fixture)], parameters, [
        ["metrics.algorithm", "==", "CGAL::alpha_wrap_3"],
        ["metrics.alpha", "==", parameters["alpha"]["value"]],
        ["metrics.offset", "==", 0.5],
        ["metrics.point_count", "==", points],
        ["input:points:measure:points.count", "==", points],
    ] + _closed_mesh_checks(euler) + extra)


FAMILY_7_10 = {
    "family": "7.10",
    "scope": "family_7_10_surface_reconstruction_partial",
    "evidence_path": "docs/master/evidence/family-7.10-capabilities.json",
    "test_id": "family-7.10-replay-cases",
    "requirements": {
        "major.7.10.01": {
            "operation_ids": ["reconstruction.poisson"],
            "symbols": ["Poisson_reconstruction_function", "Poisson_mesh_domain_3", "make_mesh_3",
                        "compute_average_spacing"],
            "symbol_notes": "Poisson_surface_reconstruction_3: Poisson_reconstruction_function over a "
                            "Poisson_mesh_domain_3 and a surface-only make_mesh_3 (closed manifold option) on "
                            "oriented point sets sampled from a radius-10 sphere (1500 points) and a torus "
                            "(R=10, r=4, 640 points). The mesh size criteria are tied to compute_average_spacing. "
                            "The independent validator (own PLY/OFF parsers) checks a closed edge- and "
                            "vertex-manifold consistently outward oriented mesh by exact signed volume, source "
                            "normals agreeing with the surface, exact GMP point-to-triangle distances from every "
                            "source point within max_deviation and a certified surface-to-source cover bound. "
                            "Replay asserts hand-derived Euler characteristics (2 and 0), the analytic radius, "
                            "torus residual, volume and area within sampling error and the facet angle bound; a "
                            "finer facet size gives a different, larger mesh. CGAL::poisson_surface_reconstruction_"
                            "delaunay (the packaged one-call wrapper, a candidate symbol of the ledger) is NOT "
                            "exposed: in CGAL 6.2.1 it appends manifold_with_boundary() after the caller tag "
                            "and measurably leaves 24 to 214 boundary edges on these closed fixtures, so its "
                            "output cannot satisfy the closed-surface validator.",
            "case_ids": ["reconstruction-poisson-sphere", "reconstruction-poisson-torus",
                         "reconstruction-poisson-torus-fine"],
        },
        "major.7.10.03": {
            "operation_ids": ["reconstruction.alpha_wrap"],
            "symbols": ["alpha_wrap_3"],
            "symbol_notes": "alpha_wrap_3 wraps unoriented point sets (the same sphere and torus samples, "
                            "320 and 640 points) with typed alpha and offset. The independent validator checks a "
                            "closed outward oriented 2-manifold, every input point strictly enclosed (exact "
                            "axis-ray parity), every wrap vertex in the offset band of the input (exact "
                            "distances), and a certified surface-to-source bound of alpha plus offset. Replay "
                            "asserts hand-derived Euler characteristics: the sphere wrap is 2; with alpha 2.5 "
                            "the torus wrap keeps its hole (0) while alpha 15 exceeds the 6 mm hole and fills "
                            "it (2); wrap vertices lie within offset of the radius-10 sphere and the torus. "
                            "Only the point-set oracle is replayed; mesh and soup oracles, the 2D wrap, "
                            "alpha_wrap_3 with a Surface_mesh input and the pause-and-resume API are not exposed.",
            "case_ids": ["reconstruction-wrap-sphere", "reconstruction-wrap-torus-fine",
                         "reconstruction-wrap-torus-coarse"],
        },
    },
    "unbound": {
        "major.7.10.02": "Advancing_front_surface_reconstruction (advancing_front_surface_reconstruction) and "
                         "Scale_space_reconstruction_3 (Jet_smoother plus Advancing_front_mesher) are implemented "
                         "with independent validators and covered by tests/master_reconstruction_cases.py, but the "
                         "ledger family also names Polygonal_surface_reconstruction, which needs a mixed-integer "
                         "program solver (SCIP or GLPK; neither is part of this build), and "
                         "Kinetic_surface_reconstruction, which has no operation. The requirement stays unbound "
                         "until every named family is replayed.",
    },
    "cases": [
        _poisson_case("reconstruction-poisson-sphere", R_SPHERE_DENSE, R_POISSON_SPHERE, 2, 1500, [
            ["output:geometry:measure:off.min_vertex_radius", ">", 9.7],
            ["output:geometry:measure:off.max_vertex_radius", "<", 10.4],
            ["output:geometry:measure:off.signed_volume", "approx", [R_SPHERE_VOLUME, 150.0]],
            ["output:geometry:measure:off.area", "approx", [R_SPHERE_AREA, 40.0]],
        ]),
        _poisson_case("reconstruction-poisson-torus", R_TORUS_NORMALS, R_POISSON_TORUS, 0, 640, [
            ["output:geometry:measure:off.max_torus_residual(10,4)", "<", 0.6],
            ["output:geometry:measure:off.signed_volume", "approx", [R_TORUS_VOLUME, 400.0]],
            ["output:geometry:measure:off.area", "approx", [R_TORUS_AREA, 100.0]],
            ["metrics.facet_count", "<", 400],
        ]),
        _poisson_case("reconstruction-poisson-torus-fine", R_TORUS_NORMALS, R_POISSON_TORUS_FINE, 0, 640, [
            ["output:geometry:measure:off.max_torus_residual(10,4)", "<", 0.6],
            ["output:geometry:measure:off.signed_volume", "approx", [R_TORUS_VOLUME, 400.0]],
            ["metrics.facet_count", ">", 400],
        ]),
        _wrap_case("reconstruction-wrap-sphere", R_SPHERE_XYZ, R_WRAP_SPHERE, 2, 320, [
            ["output:geometry:measure:off.min_vertex_radius", ">", 9.49],
            ["output:geometry:measure:off.max_vertex_radius", "<", 10.51],
            ["output:geometry:measure:off.signed_volume", ">", 4000.0],
            ["output:geometry:measure:off.signed_volume", "<", 4.0 / 3.0 * math.pi * 10.5 ** 3],
        ]),
        _wrap_case("reconstruction-wrap-torus-fine", R_TORUS_XYZ, R_WRAP_TORUS_FINE, 0, 640, [
            ["output:geometry:measure:off.max_torus_residual(10,4)", "<=", 0.500001],
            ["output:geometry:measure:off.signed_volume", ">", R_TORUS_VOLUME * 0.9],
        ]),
        _wrap_case("reconstruction-wrap-torus-coarse", R_TORUS_XYZ, R_WRAP_TORUS_COARSE, 2, 640, [
            ["output:geometry:measure:off.max_torus_residual(10,4)", "<=", 0.500001],
            ["output:geometry:measure:off.signed_volume", ">", R_TORUS_VOLUME],
        ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["reconstruction-poisson-torus", "reconstruction-poisson-torus-fine"]},
        {"kind": "different_outputs", "cases": ["reconstruction-wrap-torus-fine", "reconstruction-wrap-torus-coarse"]},
    ],
    "negative_controls": [
        {"id": "reconstruction-poisson-zero-normal-rejected", "operation": "reconstruction.poisson",
         "inputs": [_points(R_SPHERE_ZERO, "PointSet3Normals", "ply")], "parameters": R_POISSON_SPHERE,
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "ZERO_NORMAL"},
        {"id": "reconstruction-poisson-unoriented-points-rejected", "operation": "reconstruction.poisson",
         "inputs": [_points(R_SPHERE_XYZ)], "parameters": R_POISSON_SPHERE,
         "expect_error_class": "TYPE_ERROR", "expect_error_code": "INPUT_TYPE_MISMATCH"},
        {"id": "reconstruction-wrap-too-fine-rejected", "operation": "reconstruction.alpha_wrap",
         "inputs": [_points(R_TORUS_XYZ)], "parameters": {"alpha": _mm(0.1), "offset": _mm(0.5)},
         "expect_error_class": "RESOURCE_LIMIT", "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
        {"id": "reconstruction-poisson-flipped-orientation-rejected", "operation": "reconstruction.validate.poisson",
         "inputs": [_mesh(R_TAMPERED["poisson_flipped"]), _points(R_SPHERE_DENSE, "PointSet3Normals", "ply")],
         "parameters": {"max_deviation": _mm(3.0)}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "ORIENTATION_NOT_OUTWARD"},
        {"id": "reconstruction-poisson-shrunk-surface-rejected", "operation": "reconstruction.validate.poisson",
         "inputs": [_mesh(R_TAMPERED["poisson_shrunk"]), _points(R_SPHERE_DENSE, "PointSet3Normals", "ply")],
         "parameters": {"max_deviation": _mm(3.0)}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "SOURCE_TO_SURFACE_BOUND_EXCEEDED"},
        {"id": "reconstruction-wrap-shrunk-not-enclosing-rejected", "operation": "reconstruction.validate.alpha_wrap",
         "inputs": [_mesh(R_TAMPERED["wrap_shrunk"]), _points(R_SPHERE_XYZ)], "parameters": R_WRAP_SPHERE,
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_NOT_ENCLOSED"},
        {"id": "reconstruction-wrap-grown-surface-rejected", "operation": "reconstruction.validate.alpha_wrap",
         "inputs": [_mesh(R_TAMPERED["wrap_grown"]), _points(R_SPHERE_XYZ)], "parameters": R_WRAP_SPHERE,
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SURFACE_TO_SOURCE_BOUND_EXCEEDED"},
        {"id": "reconstruction-wrap-vertex-inside-band-rejected", "operation": "reconstruction.validate.alpha_wrap",
         "inputs": [_mesh(R_TAMPERED["wrap_vertex_inside"]), _points(R_SPHERE_XYZ)], "parameters": R_WRAP_SPHERE,
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_INSIDE_OFFSET_BAND"},
    ],
}

GENERIC_FAMILIES: dict[str, dict] = {
    family["family"]: family for family in (FAMILY_7_1, FAMILY_7_2, FAMILY_7_3, FAMILY_7_4, FAMILY_7_5, FAMILY_7_6,
                   FAMILY_7_9, FAMILY_7_11, FAMILY_7_12, FAMILY_7_13, FAMILY_7_14, FAMILY_7_15, FAMILY_7_10)
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
    # A feature-scoped report (criteria_scope.scoped) must carry the scoped keys instead of the full
    # ones; the full key must then be absent so a scoped pass cannot read as a full pass.
    scoped = isinstance(report.get("criteria_scope"), dict) and report["criteria_scope"].get("scoped") is True
    scoped_keys = validation.get("scoped_report_checks", {})
    for key, expected in validation.get("required_report_checks", {}).items():
        if scoped and key in scoped_keys:
            if _report_value(report, key)[0] or _report_value(report, scoped_keys[key]) != (True, expected):
                failures.append(key)
            continue
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
    if name == "euler_characteristic":
        return len(vertices) - len(edges) + len(faces)
    if name in {"min_vertex_radius", "max_vertex_radius"}:
        radii = [math.sqrt(sum(c * c for c in vertex)) for vertex in vertices]
        return min(radii) if name == "min_vertex_radius" else max(radii)
    if name.startswith("max_ellipsoid_residual(") or name.startswith("max_torus_residual("):
        # Largest first-order distance of any vertex from the analytic surface.
        numbers = [float(item) for item in name[name.index("(") + 1:-1].split(",")]
        worst = 0.0
        for x, y, z in vertices:
            if name.startswith("max_torus_residual("):
                worst = max(worst, abs(math.hypot(math.hypot(x, y) - numbers[0], z) - numbers[1]))
            else:
                a, b, c = numbers
                value = x * x / (a * a) + y * y / (b * b) + z * z / (c * c) - 1.0
                gradient = math.sqrt((2 * x / (a * a)) ** 2 + (2 * y / (b * b)) ** 2 + (2 * z / (c * c)) ** 2)
                worst = max(worst, abs(value) / gradient)
        return worst
    if name in {"min_angle_degrees", "max_circumradius"}:
        smallest, widest = 180.0, 0.0
        for face in faces:
            a, b, c = (vertices[index] for index in face[:3])
            sides = [math.dist(a, b), math.dist(b, c), math.dist(c, a)]
            u = [b[k] - a[k] for k in range(3)]
            w = [c[k] - a[k] for k in range(3)]
            twice = math.hypot(u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2],
                               u[0] * w[1] - u[1] * w[0])
            widest = max(widest, sides[0] * sides[1] * sides[2] / (2.0 * twice))
            for first, second, third in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
                # Law of cosines on the side opposite each corner.
                cosine = (sides[first] ** 2 + sides[third] ** 2 - sides[second] ** 2) / \
                         (2.0 * sides[first] * sides[third])
                smallest = min(smallest, math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
        return smallest if name == "min_angle_degrees" else widest
    if name == "boundary_edge_count":
        return sum(1 for count in edges.values() if count == 1)
    lengths = [math.dist(vertices[a], vertices[b]) for a, b in edges]
    if name == "min_edge_length":
        return min(lengths)
    if name == "max_edge_length":
        return max(lengths)
    if name == "mean_edge_length":
        return sum(lengths) / len(lengths)
    if name == "edge_length_ratio":
        return max(lengths) / min(lengths)
    if name == "bbox_diagonal":
        return math.dist([min(v[axis] for v in vertices) for axis in range(3)],
                         [max(v[axis] for v in vertices) for axis in range(3)])
    if name == "area":
        total = 0.0
        for face in faces:
            a = vertices[face[0]]
            for index in range(1, len(face) - 1):
                b, c = vertices[face[index]], vertices[face[index + 1]]
                u = [b[k] - a[k] for k in range(3)]
                w = [c[k] - a[k] for k in range(3)]
                total += 0.5 * math.hypot(u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2],
                                          u[0] * w[1] - u[1] * w[0])
        return total
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


def _tri2_measure(name: str, content: bytes) -> object:
    """Independent facts of a Triangulation2 JSON artifact (exact rational area)."""
    from fractions import Fraction
    mesh = json.loads(content.decode("utf-8"))
    vertices = [(Fraction(x), Fraction(y)) for x, y in mesh["vertices"]]
    triangles = mesh["triangles"]
    if name == "vertex_count":
        return len(vertices)
    if name == "triangle_count":
        return len(triangles)
    edges: dict[tuple[int, int], int] = {}
    twice = Fraction(0)
    smallest = 180.0
    longest = 0.0
    for a, b, c in triangles:
        (ax, ay), (bx, by), (cx, cy) = vertices[a], vertices[b], vertices[c]
        twice += (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        corners = [(float(x), float(y)) for x, y in (vertices[a], vertices[b], vertices[c])]
        for index in range(3):
            p, q, r = corners[index], corners[(index + 1) % 3], corners[(index + 2) % 3]
            u, v = (q[0] - p[0], q[1] - p[1]), (r[0] - p[0], r[1] - p[1])
            cosine = (u[0] * v[0] + u[1] * v[1]) / (math.hypot(*u) * math.hypot(*v))
            smallest = min(smallest, math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
            longest = max(longest, math.dist(p, q))
        for first, second in ((a, b), (b, c), (c, a)):
            key = (min(first, second), max(first, second))
            edges[key] = edges.get(key, 0) + 1
    if name == "area":
        return float(twice / 2)
    if name == "min_angle_degrees":
        return smallest
    if name == "max_edge_length":
        return longest
    if name == "boundary_edge_count":
        return sum(1 for count in edges.values() if count == 1)
    if name == "max_edge_use":
        return max(edges.values())
    raise ValueError(f"unknown triangulation measure {name}")


def _point_triangle_distance(p, a, b, c) -> float:
    """Closest-point distance by barycentric region tests (Ericson), independent of the worker."""
    def sub(u, v): return [u[k] - v[k] for k in range(3)]
    def dot(u, v): return sum(x * y for x, y in zip(u, v))
    ab, ac, ap = sub(b, a), sub(c, a), sub(p, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return math.dist(p, a)
    bp = sub(p, b)
    d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return math.dist(p, b)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3)
        return math.dist(p, [a[k] + v * ab[k] for k in range(3)])
    cp = sub(p, c)
    d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return math.dist(p, c)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        w = d2 / (d2 - d6)
        return math.dist(p, [a[k] + w * ac[k] for k in range(3)])
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return math.dist(p, [b[k] + w * (c[k] - b[k]) for k in range(3)])
    denominator = 1.0 / (va + vb + vc)
    v, w = vb * denominator, vc * denominator
    return math.dist(p, [a[k] + ab[k] * v + ac[k] * w for k in range(3)])


def _lattice(a, b, c, divisions: int):
    for i in range(divisions + 1):
        for j in range(divisions + 1 - i):
            s, t = i / divisions, j / divisions
            yield [a[k] * (1 - s - t) + b[k] * s + c[k] * t for k in range(3)]


def _tet_off_measure(name: str, source: str, vertices, boundary, boundary_vertices) -> float:
    """Distances between a TetrahedralMesh boundary and a raw OFF source fixture (pinned by the
    input artifact hash of the same file)."""
    from pathlib import Path
    lines = (Path(__file__).resolve().parents[1] / FIXTURE_ROOT / "wave_e" / source).read_text("utf-8").split("\n")
    count, face_count = (int(x) for x in lines[1].split()[:2])
    points = [[float(x) for x in line.split()] for line in lines[2:2 + count]]
    triangles = [[points[int(i)] for i in line.split()[1:4]] for line in lines[2 + count:2 + count + face_count]]
    facets = [[vertices[i] for i in face] for face in boundary]

    def to_source(point):
        return min(_point_triangle_distance(point, *t) for t in triangles)

    def to_boundary(point):
        return min(_point_triangle_distance(point, *f) for f in facets)

    if name == "max_boundary_vertex_distance_to_off":
        return max(to_source(vertices[i]) for i in boundary_vertices)
    if name == "max_boundary_sample_distance_to_off":
        return max(to_source(p) for f in facets for p in _lattice(*f, 4))
    if name == "max_off_sample_distance_to_boundary":
        return max(to_boundary(p) for t in triangles for p in _lattice(*t, 8))
    if name == "max_boundary_facet_center_distance_to_off":
        worst = 0.0
        for a, b, c in facets:
            sides = [math.dist(b, c), math.dist(c, a), math.dist(a, b)]
            weights = [s * s * (sides[(i + 1) % 3] ** 2 + sides[(i + 2) % 3] ** 2 - s * s) for i, s in enumerate(sides)]
            total = sum(weights)
            centre = [(weights[0] * a[k] + weights[1] * b[k] + weights[2] * c[k]) / total for k in range(3)]
            worst = max(worst, to_source(centre))
        return worst
    raise ValueError(f"unknown tetrahedral-versus-OFF measure {name}")


def _tet_measure(name: str, content: bytes) -> object:
    """Independent facts of a TetrahedralMesh JSON artifact (exact rational volume)."""
    from fractions import Fraction
    mesh = json.loads(content.decode("utf-8"))
    vertices = mesh["vertices"]
    cells = mesh["tetrahedra"]
    if name == "vertex_count":
        return len(vertices)
    if name == "tetrahedron_count":
        return len(cells)
    if name == "subdomain_count":
        return len(set(mesh["subdomains"]))

    def determinant(p):
        a, b, c = ([Fraction(p[i][k]) - Fraction(p[0][k]) for k in range(3)] for i in (1, 2, 3))
        return (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0]))

    face_use: dict[tuple, int] = {}
    boundary_candidates: dict[tuple, tuple] = {}
    edges = set()
    smallest_volume = None
    volume = Fraction(0)
    radius_edge = widest = 0.0
    spheres = []
    for cell in cells:
        points = [vertices[i] for i in cell]
        signed = determinant(points) / 6
        volume += signed
        smallest_volume = signed if smallest_volume is None else min(smallest_volume, signed)
        for slot in ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1)):
            key = tuple(sorted(cell[i] for i in slot))
            face_use[key] = face_use.get(key, 0) + 1
            boundary_candidates[key] = tuple(cell[i] for i in slot)
        for i in range(4):
            for j in range(i + 1, 4):
                edges.add(tuple(sorted((cell[i], cell[j]))))
        a, b, c = ([points[i][k] - points[0][k] for k in range(3)] for i in (1, 2, 3))
        rows = [[2 * x for x in v] for v in (a, b, c)]
        rhs = [sum(x * x for x in v) for v in (a, b, c)]

        def det3(m):
            return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                    - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                    + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

        def column(index):
            m = [r[:] for r in rows]
            for r in range(3):
                m[r][index] = rhs[r]
            return det3(m)
        d = det3(rows)
        radius = math.hypot(column(0) / d, column(1) / d, column(2) / d)
        spheres.append(([points[0][k] + column(k) / d for k in range(3)], radius))
        widest = max(widest, radius)
        shortest = min(math.dist(points[i], points[j]) for i in range(4) for j in range(i + 1, 4))
        radius_edge = max(radius_edge, radius / shortest)
    if name.startswith(("max_circumradius_in_box(", "max_circumradius_outside_box(", "cell_count_in_box(")):
        low_high = [float(x) for x in name[name.index("(") + 1:-1].split(",")]
        low, high = low_high[:3], low_high[3:]
        inside = [r for c, r in spheres if all(low[k] <= c[k] <= high[k] for k in range(3))]
        outside = [r for c, r in spheres if not all(low[k] <= c[k] <= high[k] for k in range(3))]
        if name.startswith("cell_count_in_box("):
            return len(inside)
        chosen = inside if name.startswith("max_circumradius_in_box(") else outside
        return max(chosen) if chosen else 0.0
    if name in {"max_cube_edge_vertex_gap", "max_cube_edge_mesh_segment", "cube_edge_mesh_segment_count"}:
        tolerance = 1e-9
        gaps, segment_lengths = [], []
        for axis in range(3):
            first, second = [k for k in range(3) if k != axis]
            for a in (0.0, 1.0):
                for b in (0.0, 1.0):
                    on = [i for i, v in enumerate(vertices)
                          if abs(v[first] - a) <= tolerance and abs(v[second] - b) <= tolerance
                          and -tolerance <= v[axis] <= 1.0 + tolerance]
                    ts = sorted([0.0, 1.0] + [vertices[i][axis] for i in on])
                    gaps.append(max(y - x for x, y in zip(ts, ts[1:])))
                    members = set(on)
                    segment_lengths += [math.dist(vertices[i], vertices[j]) for i, j in edges
                                        if i in members and j in members]
        if name == "max_cube_edge_vertex_gap":
            return max(gaps)
        if name == "max_cube_edge_mesh_segment":
            return max(segment_lengths) if segment_lengths else float("inf")
        return len(segment_lengths)
    if name == "volume":
        return float(volume)
    if name == "min_tetrahedron_volume":
        return float(smallest_volume)
    if name == "max_circumradius":
        return widest
    if name == "max_radius_edge":
        return radius_edge
    if name == "max_face_use":
        return max(face_use.values())
    boundary = [boundary_candidates[key] for key, count in face_use.items() if count == 1]
    boundary_vertices = {v for face in boundary for v in face}
    if name == "euler_characteristic":
        return len(vertices) - len(edges) + len(face_use) - len(cells)
    if name == "boundary_face_count":
        return len(boundary)
    boundary_edges: dict[tuple, int] = {}
    for face in boundary:
        for i in range(3):
            key = tuple(sorted((face[i], face[(i + 1) % 3])))
            boundary_edges[key] = boundary_edges.get(key, 0) + 1
    if name == "boundary_euler_characteristic":
        if any(count != 2 for count in boundary_edges.values()):
            raise ValueError("tetrahedral boundary is not a closed surface")
        return len(boundary_vertices) - len(boundary_edges) + len(boundary)
    if name in {"min_boundary_vertex_radius", "max_boundary_vertex_radius"}:
        radii = [math.sqrt(sum(c * c for c in vertices[i])) for i in boundary_vertices]
        return min(radii) if name.startswith("min") else max(radii)
    if name == "max_interior_vertex_radius":
        return max(math.sqrt(sum(c * c for c in vertices[i])) for i in range(len(vertices))
                   if i not in boundary_vertices)
    if name.startswith("max_boundary_ellipsoid_residual(") or name.startswith("max_boundary_torus_residual("):
        numbers = [float(item) for item in name[name.index("(") + 1:-1].split(",")]
        worst = 0.0
        for i in boundary_vertices:
            x, y, z = vertices[i]
            if name.startswith("max_boundary_torus_residual("):
                worst = max(worst, abs(math.hypot(math.hypot(x, y) - numbers[0], z) - numbers[1]))
            else:
                a, b, c = numbers
                value = x * x / (a * a) + y * y / (b * b) + z * z / (c * c) - 1.0
                gradient = math.sqrt((2 * x / (a * a)) ** 2 + (2 * y / (b * b)) ** 2 + (2 * z / (c * c)) ** 2)
                worst = max(worst, abs(value) / gradient)
        return worst
    if name in {"boundary_area", "min_boundary_facet_angle", "max_boundary_facet_circumradius"}:
        area, smallest, widest_facet = 0.0, 180.0, 0.0
        for face in boundary:
            pa, pb, pc = (vertices[i] for i in face)
            sides = [math.dist(pb, pc), math.dist(pc, pa), math.dist(pa, pb)]
            u = [pb[k] - pa[k] for k in range(3)]
            w = [pc[k] - pa[k] for k in range(3)]
            twice = math.hypot(u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2],
                               u[0] * w[1] - u[1] * w[0])
            area += twice / 2
            widest_facet = max(widest_facet, sides[0] * sides[1] * sides[2] / (2.0 * twice))
            for i in range(3):
                s1, s2 = sides[(i + 1) % 3], sides[(i + 2) % 3]
                cosine = (s1 * s1 + s2 * s2 - sides[i] * sides[i]) / (2.0 * s1 * s2)
                smallest = min(smallest, math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
        return {"boundary_area": area, "min_boundary_facet_angle": smallest,
                "max_boundary_facet_circumradius": widest_facet}[name]
    if "(" in name and name.endswith(".off)"):
        return _tet_off_measure(name[:name.index("(")], name[name.index("(") + 1:-1], vertices, boundary,
                                boundary_vertices)
    raise ValueError(f"unknown tetrahedral measure {name}")


def measure(name: str, content: bytes) -> object:
    kind, _, field = name.partition(".")
    if kind == "off":
        return _off_measure(field, content)
    if kind == "tri2":
        return _tri2_measure(field, content)
    if kind == "tet":
        return _tet_measure(field, content)
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
