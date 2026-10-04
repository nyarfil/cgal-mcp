"""Build the 80-item CGAL 6.2.1 major-capability implementation inventory.

This inventory is evidence for planning only.  It never marks a CGAL symbol as
an implemented MCP operation and never executes C++ source or examples.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from fetch_master_baseline import sha256_file, verified_official_provenance
from master_acceptance import extract_requirements


VERSION = "6.2.1"
FREE_DEPENDENCIES = {
    "cgal": {"name": "CGAL 6.2.1", "kind": "required", "source": "pinned official release archive", "url": "https://github.com/CGAL/cgal/releases/tag/v6.2.1"},
    "boost": {"name": "Boost", "kind": "free dependency", "source": "CGAL third-party dependency manual", "url": "https://www.boost.org/"},
    "gmp": {"name": "GMP", "kind": "free dependency for exact arithmetic", "source": "CGAL third-party dependency manual", "url": "https://gmplib.org/"},
    "mpfr": {"name": "MPFR", "kind": "free dependency for exact arithmetic", "source": "CGAL third-party dependency manual", "url": "https://www.mpfr.org/"},
    "eigen": {"name": "Eigen3", "kind": "optional free dependency", "source": "CGAL package configuration / Poisson reconstruction support", "url": "https://gitlab.com/libeigen/eigen"},
    "fastenvelope": {"name": "fast-envelope", "kind": "optional external policy dependency", "source": "CGAL FastEnvelope_filter direct include", "url": "https://github.com/wildmeshing/fast-envelope"},
    "opengr": {"name": "OpenGR", "kind": "optional external registration dependency", "source": "CGAL Point Set Processing documentation", "url": "https://github.com/STORM-IRIT/OpenGR"},
}
DEPENDENCY_MANUAL_TERMS = {"boost": "Boost", "gmp": "GMP", "mpfr": "MPFR", "eigen": "Eigen"}
CONFIG_DEPENDENCY_EVIDENCE = {
    "boost": ("cmake/modules/CGAL_SetupBoost.cmake", "find_package( Boost 1.74 REQUIRED )"),
    "gmp": ("cmake/modules/CGAL_SetupGMP.cmake", "find_package(GMP QUIET)"),
    "mpfr": ("cmake/modules/CGAL_SetupGMP.cmake", "find_package(MPFR QUIET)"),
    "eigen": ("cmake/modules/CGAL_Eigen3_support.cmake", "find_package(Eigen3 3.3.7 QUIET)"),
}
CONDITIONAL_DEPENDENCIES = {
    "major.7.10.01": ["eigen"],
    "major.7.8.03": ["eigen"],
    "major.7.8.05": ["eigen"],
    "major.7.9.05": ["opengr"],
    "major.7.14.03": ["eigen"],
    "major.7.14.04": ["eigen"],
    "major.7.15.03": ["eigen"],
    "major.7.15.01": ["gmp"],
}
CONDITIONAL_DEPENDENCY_STATUS = {
    "major.7.8.03": "REQUIRED_FOR_SELECTED_API",
    "major.7.8.05": "REQUIRED_FOR_SELECTED_API",
    "major.7.9.05": "REQUIRED_FOR_SELECTED_API",
    "major.7.10.01": "REQUIRED_FOR_SELECTED_API",
    "major.7.14.03": "REQUIRED_FOR_SELECTED_API",
    "major.7.14.04": "REQUIRED_FOR_SELECTED_API",
    "major.7.15.01": "OPTIONAL_EXACT_NUMBER_CHOICE",
    "major.7.15.03": "REQUIRED_FOR_SELECTED_API",
}
DEPENDENCY_DOCUMENTATION_EVIDENCE = {
    "major.7.8.03": ("Surface_mesh_skeletonization/index.html", "Eigen"),
    "major.7.8.05": ("Surface_mesh_parameterization/index.html", "Eigen"),
    "major.7.9.05": ("Point_set_processing_3/index.html", "OpenGR"),
    "major.7.14.03": ("Mesh_3/group__PkgMesh3Ref.html", "Eigen"),
    "major.7.14.04": ("Mesh_3/group__PkgMesh3Ref.html", "Eigen"),
    "major.7.15.03": ("Surface_mesh_approximation/group__PkgTSMARef.html", "Eigen"),
}

# This source package has no own Package Overview entry or extracted HTML
# chapter. Its API documentation and example are cross-referenced through
# Convex_decomposition_3 while retaining the source package identity.
SOURCE_ONLY_PACKAGES = {
    "Surface_mesh_decomposition": {
        "headers": {"paths": ["include/CGAL/approximate_convex_decomposition.h"]},
        "examples": {"paths": ["examples/Convex_decomposition_3/approximate_convex_decomposition.cpp"]},
        "docs": None,
    },
}

_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)


def _candidate_occurrence(text: str, symbol: str) -> int | None:
    """Return a non-comment identifier occurrence; it is not declaration proof."""
    source = _COMMENTS.sub(lambda match: "\n" * match.group(0).count("\n"), text)
    match = re.search(rf"\b{re.escape(symbol)}\b", source)
    return source.count("\n", 0, match.start()) + 1 if match else None

# requirement id: (packages, exact source tokens, proposed operation ids, dependency ids)
SPECS = {
"major.7.1.01": (["Kernel_23"],["Exact_predicates_inexact_constructions_kernel"],["kernel.create.epick"],["cgal"]),
"major.7.1.02": (["Kernel_23"],["Point_3","Vector_3","Line_3","Ray_3","Segment_3","Plane_3","Sphere_3","Triangle_3","Tetrahedron_3"],["kernel.primitives.construct"],["cgal"]),
"major.7.1.03": (["Kernel_23"],["orientation"],["kernel.predicates.evaluate"],["cgal"]),
"major.7.1.04": (["Kernel_23"],["intersection"],["kernel.intersections.compute"],["cgal"]),
"major.7.1.05": (["Kernel_23"],["squared_distance"],["kernel.distance.squared"],["cgal"]),
"major.7.2.01": (["AABB_tree"],["AABB_tree"],["spatial.aabb.build"],["cgal"]),
"major.7.2.02": (["Spatial_searching"],["Kd_tree"],["spatial.kd.build"],["cgal"]),
"major.7.2.03": (["Spatial_searching"],["K_neighbor_search"],["spatial.nearest_neighbors.query"],["cgal"]),
"major.7.2.04": (["AABB_tree"],["do_intersect"],["spatial.aabb.intersections"],["cgal"]),
"major.7.2.05": (["Kernel_23"],["Bbox_3"],["spatial.bounding_box.compute"],["cgal"]),
"major.7.3.01": (["Polygon_mesh_processing"],["does_self_intersect"],["mesh.predicates.evaluate"],["cgal"]),
"major.7.3.02": (["Polygon_mesh_processing"],["connected_components"],["mesh.components.compute"],["cgal"]),
"major.7.3.03": (["Polygon_mesh_processing"],["compute_face_normals"],["mesh.normals.compute"],["cgal"]),
"major.7.3.04": (["Polygon_mesh_processing"],["area"],["mesh.measures.compute"],["cgal"]),
"major.7.3.05": (["Polygon_mesh_processing"],["detect_sharp_edges"],["mesh.features.detect"],["cgal"]),
"major.7.3.06": (["Polygon_mesh_processing"],["approximate_Hausdorff_distance"],["mesh.distance.hausdorff"],["cgal"]),
"major.7.3.07": (["Polygon_mesh_processing"],["self_intersections"],["mesh.intersections.self"],["cgal"]),
"major.7.3.08": (["Polygon_mesh_processing"],["locate"],["mesh.location.locate"],["cgal"]),
"major.7.4.01": (["PMP_Mesh_repair"],["orient_to_bound_a_volume"],["mesh.repair.orient"],["cgal"]),
"major.7.4.02": (["PMP_Mesh_repair"],["stitch_borders"],["mesh.repair.stitch_borders"],["cgal"]),
"major.7.4.03": (["PMP_Mesh_repair"],["remove_degenerate_faces"],["mesh.repair.remove_degenerate"],["cgal"]),
"major.7.4.04": (["PMP_Mesh_repair"],["triangulate_hole"],["mesh.repair.fill_holes"],["cgal"]),
"major.7.4.05": (["PMP_Mesh_repair"],["repair_polygon_soup"],["mesh.repair.polygon_soup"],["cgal"]),
"major.7.4.06": (["PMP_Mesh_repair"],["duplicate_non_manifold_vertices"],["mesh.repair.manifold_preprocess"],["cgal"]),
"major.7.5.01": (["PMP_Boolean_operations"],["corefine"],["mesh.boolean.corefine"],["cgal"]),
"major.7.5.02": (["PMP_Boolean_operations"],["corefine_and_compute_union"],["mesh.boolean.union","mesh.boolean.intersection","mesh.boolean.difference"],["cgal"]),
"major.7.5.03": (["PMP_Boolean_operations"],["clip"],["mesh.boolean.clip"],["cgal"]),
"major.7.5.04": (["PMP_Boolean_operations"],["split"],["mesh.boolean.split"],["cgal"]),
"major.7.5.05": (["PMP_Boolean_operations"],["Polygon_mesh_slicer"],["mesh.slice.compute"],["cgal"]),
"major.7.6.01": (["PMP_Remeshing"],["triangulate_faces"],["mesh.triangulate.faces"],["cgal"]),
"major.7.6.02": (["PMP_Remeshing"],["refine"],["mesh.refine.local"],["cgal"]),
"major.7.6.03": (["PMP_Remeshing"],["isotropic_remeshing"],["mesh.remesh.isotropic"],["cgal"]),
"major.7.6.04": (["PMP_Remeshing"],["smooth_shape"],["mesh.smooth.shape"],["cgal"]),
"major.7.6.05": (["PMP_Remeshing"],["split_long_edges"],["mesh.remesh.adaptive"],["cgal"]),
"major.7.7.01": (["Surface_mesh_simplification"],["edge_collapse"],["mesh.simplify.edge_collapse"],["cgal"]),
"major.7.7.02": (["Surface_mesh_simplification"],["LindstromTurk_cost"],["mesh.simplify.lindstrom_turk"],["cgal"]),
"major.7.7.03": (["Surface_mesh_simplification"],["GarlandHeckbert_plane_policies"],["mesh.simplify.garland_heckbert"],["cgal"]),
"major.7.7.04": (["Surface_mesh_simplification"],["Constrained_placement"],["mesh.simplify.constrained"],["cgal"]),
"major.7.7.05": (["Surface_mesh_simplification","Polygon_mesh_processing"],["Polyhedral_envelope_filter"],["mesh.simplify.polyhedral_envelope_filter"],["cgal","boost"]),
"major.7.7.06": (["Surface_mesh_simplification"],["Bounded_normal_change_filter"],["mesh.simplify.normal_change_filter"],["cgal"]),
"major.7.8.01": (["Surface_mesh_segmentation"],["sdf_values"],["mesh.segment.sdf"],["cgal"]),
"major.7.8.02": (["Surface_mesh_decomposition","Convex_decomposition_3"],["approximate_convex_decomposition"],["mesh.decompose.approx_convex"],["cgal"]),
"major.7.8.03": (["Surface_mesh_skeletonization"],["extract_mean_curvature_flow_skeleton"],["mesh.skeletonize.mean_curvature"],["cgal"]),
"major.7.8.04": (["Surface_mesh_shortest_path"],["Surface_mesh_shortest_path"],["mesh.path.shortest"],["cgal"]),
"major.7.8.05": (["Surface_mesh_parameterization"],["parameterize"],["mesh.parameterize"],["cgal"]),
"major.7.8.06": (["Subdivision_method_3"],["CatmullClark_subdivision"],["mesh.subdivide.catmull_clark"],["cgal"]),
"major.7.9.01": (["Point_set_processing_3"],["jet_estimate_normals"],["pointset.normals.estimate"],["cgal"]),
"major.7.9.02": (["Point_set_processing_3"],["remove_outliers"],["pointset.outliers.remove"],["cgal"]),
"major.7.9.03": (["Point_set_processing_3"],["bilateral_smooth_point_set"],["pointset.smooth.bilateral"],["cgal"]),
"major.7.9.04": (["Point_set_processing_3"],["grid_simplify_point_set"],["pointset.simplify.grid"],["cgal"]),
"major.7.9.05": (["Point_set_processing_3"],["register_point_sets"],["pointset.registration.register"],["cgal"]),
"major.7.9.06": (["Point_set_processing_3"],["compute_average_spacing"],["pointset.preprocess.spacing"],["cgal"]),
"major.7.10.01": (["Poisson_surface_reconstruction_3"],["poisson_surface_reconstruction_delaunay"],["surface.reconstruct.poisson"],["cgal"]),
"major.7.10.02": (["Advancing_front_surface_reconstruction","Scale_space_reconstruction_3","Polygonal_surface_reconstruction","Kinetic_surface_reconstruction"],["advancing_front_surface_reconstruction"],["surface.reconstruct.advancing_front"],["cgal"]),
"major.7.10.03": (["Alpha_wrap_3"],["alpha_wrap_3"],["surface.reconstruct.alpha_wrap"],["cgal"]),
"major.7.11.01": (["Triangulation_2","Triangulation_3"],["Delaunay_triangulation_2","Delaunay_triangulation_3"],["triangulation.delaunay"],["cgal"]),
"major.7.11.02": (["Triangulation_2"],["Constrained_Delaunay_triangulation_2"],["triangulation.constrained"],["cgal"]),
"major.7.11.03": (["Triangulation_2","Triangulation_3"],["Regular_triangulation_2","Regular_triangulation_3"],["triangulation.regular"],["cgal"]),
"major.7.11.04": (["Periodic_2_triangulation_2","Periodic_3_triangulation_3","Triangulation_on_sphere_2"],["Periodic_2_triangulation_2","Delaunay_triangulation_on_sphere_2"],["triangulation.periodic_or_spherical"],["cgal"]),
"major.7.11.05": (["Voronoi_diagram_2"],["Voronoi_diagram_2"],["triangulation.voronoi_dual"],["cgal"]),
"major.7.12.01": (["Polygon"],["Polygon_2"],["polygon.operations"],["cgal"]),
"major.7.12.02": (["Arrangement_on_surface_2"],["Arrangement_2"],["arrangement.build"],["cgal"]),
"major.7.12.03": (["Arrangement_on_surface_2"],["overlay"],["arrangement.overlay"],["cgal"]),
"major.7.12.04": (["Boolean_set_operations_2"],["Polygon_set_2"],["polygon.boolean"],["cgal"]),
"major.7.12.05": (["Straight_skeleton_2"],["create_interior_straight_skeleton_2"],["polygon.straight_skeleton"],["cgal"]),
"major.7.12.06": (["Straight_skeleton_2"],["create_interior_skeleton_and_offset_polygons_2"],["polygon.offset"],["cgal"]),
"major.7.12.07": (["Minkowski_sum_2"],["minkowski_sum_2"],["polygon.minkowski_sum"],["cgal"]),
"major.7.13.01": (["Convex_hull_2","Convex_hull_3"],["convex_hull_2","convex_hull_3"],["shape.convex_hull"],["cgal"]),
"major.7.13.02": (["Alpha_shapes_2","Alpha_shapes_3"],["Alpha_shape_2","Alpha_shape_3"],["shape.alpha"],["cgal"]),
"major.7.13.03": (["Alpha_wrap_3"],["alpha_wrap_3"],["shape.alpha_wrap"],["cgal"]),
"major.7.13.04": (["Bounding_volumes"],["Min_sphere_of_spheres_d"],["shape.bounding_volume"],["cgal"]),
"major.7.13.05": (["Barycentric_coordinates_2"],["mean_value_coordinates_2"],["shape.barycentric"],["cgal"]),
"major.7.14.01": (["Mesh_2"],["refine_Delaunay_mesh_2"],["meshing.mesh_2"],["cgal"]),
"major.7.14.02": (["Surface_mesher"],["make_surface_mesh"],["meshing.surface"],["cgal"]),
"major.7.14.03": (["Mesh_3"],["make_mesh_3"],["meshing.mesh_3"],["cgal","boost"]),
"major.7.14.04": (["Mesh_3"],["Mesh_criteria_3"],["meshing.domain_criteria"],["cgal","boost"]),
"major.7.15.01": (["QP_solver"],["solve_quadratic_program"],["optimization.quadratic_program"],["cgal","boost"]),
"major.7.15.02": (["Interpolation"],["linear_interpolation"],["optimization.interpolate"],["cgal"]),
"major.7.15.03": (["Surface_mesh_approximation"],["approximate_triangle_mesh"],["optimization.approximate_mesh"],["cgal"]),
"major.7.15.04": (["Matrix_search"],["sorted_matrix_search"],["optimization.matrix_search"],["cgal"]),
}

# Fixed planning denominator beneath each of the 80 requirements.  Symbols are
# deliberately concrete public API/type names, not inferred operation support.
SUBCAPABILITY_SYMBOLS = {
"major.7.1.01": ["Exact_predicates_inexact_constructions_kernel", "Exact_predicates_exact_constructions_kernel", "Simple_cartesian", "Cartesian"],
"major.7.1.02": ["Point_2", "Point_3", "Vector_2", "Vector_3", "Line_2", "Line_3", "Ray_2", "Ray_3", "Segment_2", "Segment_3", "Plane_3", "Circle_2", "Sphere_3", "Triangle_2", "Triangle_3", "Tetrahedron_3", "Iso_rectangle_2", "Iso_cuboid_3", "Aff_transformation_2", "Aff_transformation_3"],
"major.7.1.03": ["orientation", "collinear", "coplanar", "left_turn", "right_turn", "midpoint", "centroid", "circumcenter"],
"major.7.1.04": ["intersection", "do_intersect"],
"major.7.1.05": ["squared_distance", "compare_distance", "compare_distance_to_point"],
"major.7.2.01": ["AABB_tree", "AABB_traits", "AABB_face_graph_triangle_primitive"],
"major.7.2.02": ["Kd_tree", "Search_traits_3"],
"major.7.2.03": ["K_neighbor_search", "Orthogonal_k_neighbor_search"],
"major.7.2.04": ["do_intersect", "any_intersected_primitive", "all_intersected_primitives"],
"major.7.2.05": ["Bbox_2", "Bbox_3", "bbox_2", "bbox_3"],
"major.7.3.01": ["does_self_intersect", "is_closed", "is_triangle_mesh"],
"major.7.3.02": ["connected_components", "connected_component", "keep_largest_connected_components"],
"major.7.3.03": ["compute_face_normals", "compute_vertex_normals", "compute_normals"],
"major.7.3.04": ["area", "volume", "centroid"],
"major.7.3.05": ["detect_sharp_edges", "sharp_edges_segmentation"],
"major.7.3.06": ["sample_triangle_mesh", "max_distance_to_triangle_mesh", "approximate_Hausdorff_distance", "approximate_symmetric_Hausdorff_distance", "approximate_max_distance_to_point_set", "bounded_error_Hausdorff_distance", "bounded_error_symmetric_Hausdorff_distance"],
"major.7.3.07": ["self_intersections", "does_self_intersect"],
"major.7.3.08": ["locate", "locate_with_AABB_tree"],
"major.7.4.01": ["orient_to_bound_a_volume", "orient_polygon_soup"],
"major.7.4.02": ["stitch_borders"],
"major.7.4.03": ["remove_degenerate_faces", "remove_degenerate_edges"],
"major.7.4.04": ["triangulate_hole", "triangulate_refine_and_fair_hole"],
"major.7.4.05": ["repair_polygon_soup"],
"major.7.4.06": ["duplicate_non_manifold_vertices", "non_manifold_vertices"],
"major.7.5.01": ["corefine", "autorefine"],
"major.7.5.02": ["corefine_and_compute_union", "corefine_and_compute_intersection", "corefine_and_compute_difference"],
"major.7.5.03": ["clip", "corefine_and_compute_intersection"],
"major.7.5.04": ["split", "corefine"],
"major.7.5.05": ["Polygon_mesh_slicer"],
"major.7.6.01": ["triangulate_faces", "triangulate_face"],
"major.7.6.02": ["refine"],
"major.7.6.03": ["isotropic_remeshing", "split_long_edges"],
"major.7.6.04": ["smooth_shape", "tangential_relaxation"],
"major.7.6.05": ["split_long_edges", "isotropic_remeshing"],
"major.7.7.01": ["edge_collapse", "Edge_profile"],
"major.7.7.02": ["LindstromTurk_cost", "LindstromTurk_placement"],
"major.7.7.03": ["GarlandHeckbert_plane_policies", "GarlandHeckbert_triangle_policies", "GarlandHeckbert_probabilistic_plane_policies"],
"major.7.7.04": ["Constrained_placement", "Edge_length_cost", "Midpoint_placement"],
"major.7.7.05": ["Polyhedral_envelope_filter", "Polyhedral_envelope"],
"major.7.7.06": ["Bounded_normal_change_filter", "Bounded_normal_change_placement"],
"major.7.8.01": ["sdf_values", "segmentation_from_sdf_values"],
"major.7.8.02": ["approximate_convex_decomposition"],
"major.7.8.03": ["extract_mean_curvature_flow_skeleton", "Mean_curvature_flow_skeletonization"],
"major.7.8.04": ["Surface_mesh_shortest_path", "shortest_path_sequence_to_source_points"],
"major.7.8.05": ["parameterize", "Discrete_conformal_map_parameterizer_3"],
"major.7.8.06": ["CatmullClark_subdivision", "Loop_subdivision"],
"major.7.9.01": ["jet_estimate_normals", "pca_estimate_normals"],
"major.7.9.02": ["remove_outliers", "compute_average_spacing"],
"major.7.9.03": ["bilateral_smooth_point_set", "jet_smooth_point_set"],
"major.7.9.04": ["grid_simplify_point_set", "random_simplify_point_set"],
"major.7.9.05": ["register_point_sets", "compute_registration_transformation"],
"major.7.9.06": ["compute_average_spacing", "remove_outliers"],
"major.7.10.01": ["poisson_surface_reconstruction_delaunay", "Poisson_reconstruction_function"],
"major.7.10.02": ["advancing_front_surface_reconstruction", "Advancing_front_surface_reconstruction", "Scale_space_reconstruction_3", "Polygonal_surface_reconstruction", "Kinetic_surface_reconstruction"],
"major.7.10.03": ["alpha_wrap_3"],
"major.7.11.01": ["Delaunay_triangulation_2", "Delaunay_triangulation_3"],
"major.7.11.02": ["Constrained_Delaunay_triangulation_2", "Constrained_triangulation_2"],
"major.7.11.03": ["Regular_triangulation_2", "Regular_triangulation_3"],
"major.7.11.04": ["Periodic_2_triangulation_2", "Periodic_3_Delaunay_triangulation_3", "Delaunay_triangulation_on_sphere_2"],
"major.7.11.05": ["Voronoi_diagram_2"],
"major.7.12.01": ["Polygon_2", "Polygon_with_holes_2", "is_simple"],
"major.7.12.02": ["Arrangement_2", "insert", "zone"],
"major.7.12.03": ["overlay", "Overlay_traits"],
"major.7.12.04": ["Polygon_set_2", "join", "difference"],
"major.7.12.05": ["create_interior_straight_skeleton_2", "create_exterior_straight_skeleton_2"],
"major.7.12.06": ["create_interior_skeleton_and_offset_polygons_2", "create_exterior_skeleton_and_offset_polygons_2"],
"major.7.12.07": ["minkowski_sum_2", "minkowski_sum_by_reduced_convolution_2"],
"major.7.13.01": ["convex_hull_2", "convex_hull_3"],
"major.7.13.02": ["Alpha_shape_2", "Alpha_shape_3", "Fixed_alpha_shape_3"],
"major.7.13.03": ["alpha_wrap_3"],
"major.7.13.04": ["Min_sphere_of_spheres_d", "Min_circle_2", "Min_sphere_of_spheres_d_traits_3"],
"major.7.13.05": ["mean_value_coordinates_2", "wachspress_coordinates_2", "discrete_harmonic_coordinates_2"],
"major.7.14.01": ["refine_Delaunay_mesh_2", "Delaunay_mesh_size_criteria_2"],
"major.7.14.02": ["make_surface_mesh", "Surface_mesh_default_criteria_3"],
"major.7.14.03": ["make_mesh_3"],
"major.7.14.04": ["Mesh_criteria_3", "Mesh_facet_criteria_3"],
"major.7.15.01": ["solve_quadratic_program", "solve_linear_program", "Quadratic_program"],
"major.7.15.02": ["linear_interpolation", "sibson_c1_interpolation"],
"major.7.15.03": ["approximate_triangle_mesh"],
"major.7.15.04": ["sorted_matrix_search"],
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _header_evidence(source_root: Path, packages: dict[str, dict], package_ids: list[str], tokens: list[str]) -> list[dict]:
    candidates: list[Path] = []
    for package_id in package_ids:
        if package_id not in packages:
            raise ValueError(f"unknown official package ID: {package_id}")
        candidates.extend(source_root / path for path in packages[package_id]["headers"]["paths"])
    evidence: list[dict] = []
    for token in tokens:
        matches = []
        for path in candidates:
            occurrence_line = _candidate_occurrence(path.read_text(encoding="utf-8", errors="ignore"), token)
            if occurrence_line is not None:
                matches.append((path, occurrence_line))
        if not matches:
            raise ValueError(f"no public-header candidate occurrence for token {token!r} in {package_ids}")
        path, occurrence_line = sorted(matches, key=lambda item: item[0].as_posix())[0]
        evidence.append({
            "symbol": token,
            "path": path.relative_to(source_root).as_posix(),
            "sha256": sha256_file(path),
            "occurrence_line": occurrence_line,
            "evidence_kind": "CANDIDATE_SYMBOL_OCCURRENCE",
            "verification_status": "DECLARATION_UNVERIFIED",
            "matching_rule": "exact_identifier_outside_comments",
        })
    return evidence


def _examples(source_root: Path, packages: dict[str, dict], package_ids: list[str], tokens: list[str]) -> list[dict]:
    result: list[dict] = []
    for package_id in package_ids:
        paths = packages[package_id]["examples"]["paths"]
        matches: list[tuple[str, list[str]]] = []
        for relative in paths:
            path = source_root / relative
            text = path.read_text(encoding="utf-8", errors="ignore")
            mentioned = [token for token in tokens if token in text]
            if mentioned:
                matches.append((relative, mentioned))
        for relative, mentioned in matches[:3]:
            path = source_root / relative
            result.append({
                "package": package_id,
                "path": relative,
                "sha256": sha256_file(path),
                "matched_symbols": mentioned,
                "evidence_kind": "symbol_mentioned_in_official_example",
            })
    return result


def _documentation_evidence(docs_root: Path, packages: dict[str, dict], package_ids: list[str]) -> list[dict]:
    result: list[dict] = []
    for package_id in package_ids:
        docs = packages[package_id].get("docs")
        if docs is None:
            continue
        path = docs_root / docs["local_entry"]
        if not path.is_file() or sha256_file(path) != docs["sha256"]:
            raise ValueError(f"package documentation evidence mismatch: {package_id}")
        result.append({"package": package_id, "path": docs["local_entry"], "sha256": docs["sha256"]})
    return result


def _dependency_evidence(source_root: Path, docs_root: Path, dependency_ids: list[str]) -> list[dict]:
    manual = docs_root / "Manual" / "thirdparty.html"
    manual_text = manual.read_text(encoding="utf-8", errors="strict")
    manual_evidence = {"path": "Manual/thirdparty.html", "sha256": sha256_file(manual)}
    result: list[dict] = []
    for dependency_id in dependency_ids:
        entry = dict(FREE_DEPENDENCIES[dependency_id])
        if dependency_id == "cgal":
            entry["evidence"] = {"kind": "verified_release_receipt"}
        elif dependency_id == "fastenvelope":
            raise ValueError("fastenvelope evidence must be bound to FastEnvelope_filter header")
        else:
            term = DEPENDENCY_MANUAL_TERMS[dependency_id]
            if term not in manual_text:
                raise ValueError(f"third-party manual does not mention {term}")
            entry["evidence"] = {"kind": "cgal_manual", **manual_evidence, "term": term}
            relative, required_code = CONFIG_DEPENDENCY_EVIDENCE[dependency_id]
            config = source_root / relative
            config_text = config.read_text(encoding="utf-8", errors="strict")
            if required_code not in config_text:
                raise ValueError(f"missing configured dependency evidence: {dependency_id}")
            entry["configuration_evidence"] = {"path": relative, "sha256": sha256_file(config), "code": required_code}
        result.append(entry)
    return result


def _conditional_dependency_evidence(source_root: Path, docs_root: Path, requirement_id: str) -> list[dict]:
    result: list[dict] = []
    for dependency_id in CONDITIONAL_DEPENDENCIES.get(requirement_id, []):
        entry = dict(FREE_DEPENDENCIES[dependency_id])
        entry["requirement"] = CONDITIONAL_DEPENDENCY_STATUS[requirement_id]
        if dependency_id in CONFIG_DEPENDENCY_EVIDENCE:
            relative, required_code = CONFIG_DEPENDENCY_EVIDENCE[dependency_id]
            path = source_root / relative
            text = path.read_text(encoding="utf-8", errors="strict")
            if required_code not in text:
                raise ValueError(f"missing configured dependency evidence: {dependency_id}")
            entry["configuration_evidence"] = {"path": relative, "sha256": sha256_file(path), "code": required_code}
        if dependency_id in {"eigen", "opengr"} and requirement_id in DEPENDENCY_DOCUMENTATION_EVIDENCE:
            relative, term = DEPENDENCY_DOCUMENTATION_EVIDENCE[requirement_id]
            path = docs_root / relative
            text = path.read_text(encoding="utf-8", errors="strict")
            if term not in text:
                raise ValueError(f"missing package documentation dependency evidence: {requirement_id}")
            entry["package_documentation_evidence"] = {"path": relative, "sha256": sha256_file(path), "term": term}
        if requirement_id == "major.7.15.01" and dependency_id == "gmp":
            example = source_root / "examples/QP_solver/first_qp.cpp"
            example_text = example.read_text(encoding="utf-8", errors="strict")
            if "#include <CGAL/Gmpz.h>" not in example_text:
                raise ValueError("QP exact-number example lost its Gmpz include")
            entry["official_example_evidence"] = {
                "path": "examples/QP_solver/first_qp.cpp",
                "sha256": sha256_file(example),
                "code": "#include <CGAL/Gmpz.h>",
            }
        result.append(entry)
    return result


def _fastenvelope_policy(source_root: Path) -> dict:
    relative = "include/CGAL/Surface_mesh_simplification/Policies/Edge_collapse/FastEnvelope_filter.h"
    path = source_root / relative
    text = path.read_text(encoding="utf-8", errors="strict")
    occurrence_line = _candidate_occurrence(text, "FastEnvelope_filter")
    if occurrence_line is None or "#include <fastenvelope/FastEnvelope.h>" not in text:
        raise ValueError("FastEnvelope_filter occurrence or direct fastenvelope include missing")
    return {
        "id": "supplemental.fast_envelope_filter",
        "classification": "OPTIONAL_POLICY_NOT_MAJOR_7_7_05",
        "implementation_status": "NOT_ASSESSED_BY_PLANNING_INVENTORY",
        "completion_status": "NOT_ASSESSED_BY_PLANNING_INVENTORY",
        "public_api_evidence": {
            "symbol": "FastEnvelope_filter",
            "path": relative,
            "sha256": sha256_file(path),
            "occurrence_line": occurrence_line,
            "evidence_kind": "CANDIDATE_SYMBOL_OCCURRENCE",
            "verification_status": "DECLARATION_UNVERIFIED",
            "matching_rule": "exact_identifier_outside_comments",
        },
        "external_dependency": {
            **FREE_DEPENDENCIES["fastenvelope"],
            "required_by_header_include": "<fastenvelope/FastEnvelope.h>",
            "acquisition_pin_status": "UNPINNED_ACQUISITION_REQUIRED_BEFORE_BUILD",
        },
    }


def requirement_description_view(document: dict) -> dict:
    """Immutable planning input; execution evidence has its own acceptance store."""
    return {"source": document["source"], "source_sha256": document["source_sha256"],
        "families": [{"id": family["id"], "title": family["title"],
            "requirements": [{key: item[key] for key in ("id", "description", "required")}
                             for item in family["requirements"]]}
                     for family in document["families"]]}


def build_inventory(repository: Path, source_root: Path, docs_root: Path) -> dict:
    requirements_path = repository / "catalog" / "major_requirements.json"
    requirements = _read_json(requirements_path)
    descriptions = requirement_description_view(requirements)
    if descriptions != requirement_description_view(extract_requirements(repository)):
        raise ValueError("Planning inventory denominator differs from the original requirements")
    if sha256_file(repository / requirements["source"]) != requirements["source_sha256"]:
        raise ValueError("major requirements source digest mismatch")
    provenance = verified_official_provenance(source_root, docs_root)
    manifest = _read_json(repository / "catalog" / "packages.json")
    packages = {item["id"]: item for item in manifest["packages"]}
    packages.update(SOURCE_ONLY_PACKAGES)
    records: list[dict] = []
    subcapability_count = 0
    for family in requirements["families"]:
        for requirement in family["requirements"]:
            requirement_id = requirement["id"]
            if requirement_id not in SPECS:
                raise ValueError(f"missing inventory mapping for {requirement_id}")
            package_ids, _primary_tokens, operation_ids, dependencies = SPECS[requirement_id]
            symbols = SUBCAPABILITY_SYMBOLS[requirement_id]
            api_evidence = _header_evidence(source_root, packages, package_ids, symbols)
            subcapabilities = []
            for ordinal, evidence in enumerate(api_evidence, start=1):
                subcapabilities.append({
                    "id": f"api.{ordinal:02d}",
                    "symbol": evidence["symbol"],
                    "implementation_status": "NOT_ASSESSED_BY_PLANNING_INVENTORY",
                    "completion_status": "NOT_ASSESSED_BY_PLANNING_INVENTORY",
                    "public_api_evidence": evidence,
                })
            subcapability_count += len(subcapabilities)
            example_candidates = _examples(source_root, packages, package_ids, symbols)
            documentation_evidence = _documentation_evidence(docs_root, packages, package_ids)
            source_only = [package_id for package_id in package_ids if package_id in SOURCE_ONLY_PACKAGES]
            exception_reason = (
                "official source package has no own Package Overview or extracted HTML chapter; "
                "documentation/examples are cross-referenced through Convex_decomposition_3: " + ", ".join(source_only)
                if source_only else None
            )
            records.append({
                "id": requirement_id,
                "family": {"id": family["id"], "title": family["title"]},
                "description": requirement["description"],
                "required": requirement["required"],
                "implementation_status": "NOT_ASSESSED_BY_PLANNING_INVENTORY",
                "completion_status": "NOT_ASSESSED_BY_PLANNING_INVENTORY",
                "availability": {
                    "cgal_version": VERSION,
                    "source_present": True,
                    "catalog_overview_present": bool([package_id for package_id in package_ids if package_id not in SOURCE_ONLY_PACKAGES]),
                    "documentation_present": bool(documentation_evidence),
                    "exception_reason": exception_reason,
                },
                "adoption": {
                    "baseline_version": VERSION,
                    "adapter_implementation_present": None,
                    "status": "PLANNING_CANDIDATE",
                    "exception_reason": exception_reason or "adapter implementation is outside this inventory",
                },
                "package_ids": package_ids,
                "public_api_evidence": api_evidence,
                "subcapability_inventory_status": "TEMPORARY_NONEXHAUSTIVE_CANDIDATE_SCOPE",
                "subcapabilities": subcapabilities,
                "documentation_evidence": documentation_evidence,
                "example_candidates": example_candidates,
                "example_status": (
                    "OFFICIAL_SYMBOL_MATCHING_EXAMPLE" if example_candidates
                    else "NO_OFFICIAL_SYMBOL_MATCHING_EXAMPLE_FOUND"
                ),
                "free_dependencies": _dependency_evidence(source_root, docs_root, dependencies),
                "conditional_free_dependencies": _conditional_dependency_evidence(source_root, docs_root, requirement_id),
                "proposed_operation_ids": operation_ids,
                "validator_proposal": "operation-specific validator required before publish; source presence is not execution evidence",
                "fixture_proposal": f"fixtures/major/{requirement_id.replace('.', '_')}/",
            })
    if set(SPECS) != {item["id"] for family in requirements["families"] for item in family["requirements"]}:
        raise ValueError("SPECS does not exactly match major requirements population")
    if set(SUBCAPABILITY_SYMBOLS) != set(SPECS):
        raise ValueError("subcapability map does not exactly match major requirements population")
    return {
        "schema_version": 1,
        "source": {"major_requirements": "catalog/major_requirements.json",
            "sha256": hashlib.sha256((json.dumps(descriptions, ensure_ascii=False,
                sort_keys=True, indent=2) + "\n").encode("utf-8")).hexdigest(),
            "sha256_encoding": "sorted-json-indent2-utf8-lf",
            "sha256_scope": "original_requirement_descriptions_without_execution_bindings",
            "requirements_source": requirements["source"],
            "requirements_source_sha256": requirements["source_sha256"]},
        "cgal": {"version": VERSION, "provenance": provenance},
        "inventory_status": "PLANNING_ONLY_NOT_EXECUTION_EVIDENCE_OR_API_COMPLETENESS_CLAIM",
        "execution_status_source": "cgal_mcp/master/operations.json and trusted capability acceptance reports; not assessed by this inventory",
        "requirement_count": len(records),
        "candidate_subcapability_count": subcapability_count,
        "candidate_subcapability_status": "TEMPORARY_NONEXHAUSTIVE_LIST; 80 requirements are the only fixed denominator",
        "supplemental_policies": [_fastenvelope_policy(source_root)],
        "items": records,
    }


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=repository / "work" / "master-baseline" / "source" / "CGAL-6.2.1")
    parser.add_argument("--docs", type=Path, default=repository / "work" / "master-baseline" / "docs" / "doc_html")
    parser.add_argument("--output", type=Path, default=repository / "catalog" / "major_capability_inventory.json")
    arguments = parser.parse_args()
    inventory = build_inventory(repository, arguments.source, arguments.docs)
    output = arguments.output
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(inventory, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(f"requirement_count={inventory['requirement_count']}")


if __name__ == "__main__":
    main()
