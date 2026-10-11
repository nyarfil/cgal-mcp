# Limits and honest coverage

## Operation status
VALIDATED: 226 (CGAL 6.2.1)
Only VALIDATED/IMPLEMENTED operations can execute. VALIDATED means replay-verified on bundled fixtures with an independent validator, not a proof for every input. Whole-system acceptance is tracked separately by the replay-bound evaluator (scripts/master_acceptance.py) and is not claimed by this guide.

## Package catalog
126 CGAL packages: VALIDATED 45, CATALOGED 69, EXCLUDED 12
VALIDATED = has at least one executable validated operation. CATALOGED = documentation/source indexed only, NOT executable. EXCLUDED = no standalone headless operation exists.

## Limits
- import: at most 512 MiB per file; formats off, obj, ply (ASCII), stl, xyz and typed json; units mm, cm or m (reports: none)
- execution defaults: concurrency 2, worker memory 4096 MiB, wall time 120 s, ceiling 86400 s; live values: cgal_system_health; per call: cgal_execute execution={"wall_time_ms":..., "memory_mb":...}
- per-operation face bounds (cards list each one): 64 faces: 1 ops; 200 faces: 2 ops; 400 faces: 7 ops; 600 faces: 5 ops; 1500 faces: 2 ops; 2000 faces: 5 ops; 3000 faces: 2 ops; 20000 faces: 12 ops; 200000 faces: 6 ops; 400000 faces: 3 ops; 2000000 faces: 17 ops
- tightest common bound: 400 faces: mesh.distance.hausdorff_approximate, mesh.distance.hausdorff_approximate_symmetric, mesh.distance.hausdorff_bounded, mesh.distance.max_to_mesh, mesh.distance.max_to_points, mesh.distance.sample_points, mesh.distance.symmetric_hausdorff

## Not supported (cataloged or excluded packages)
When a request names one of these, cgal_capabilities_search/cgal_plan fail closed (unsupported_operation with details.unsupported_cgal_packages). Tell the user it is not supported; do not substitute a nearby operation silently.

### CATALOGED
- Algebraic_kernel_d: algorithm_adapter_not_implemented
- Alpha_wrap_2: algorithm_adapter_not_implemented
- Apollonius_graph_2: algorithm_adapter_not_implemented
- Barycentric_coordinates_3: algorithm_adapter_not_implemented
- Box_intersection_d: algorithm_adapter_not_implemented
- Circular_kernel_2: algorithm_adapter_not_implemented
- Circular_kernel_3: algorithm_adapter_not_implemented
- Classification: algorithm_adapter_not_implemented
- Combinatorial_map: data_structure_adapter_not_implemented
- Cone_spanners_2: algorithm_adapter_not_implemented
- Constrained_triangulation_3: algorithm_adapter_not_implemented
- Convex_hull_d: algorithm_adapter_not_implemented
- Envelope_2: algorithm_adapter_not_implemented
- Envelope_3: algorithm_adapter_not_implemented
- Frechet_distance: algorithm_adapter_not_implemented
- Generalized_map: data_structure_adapter_not_implemented
- Generator: algorithm_adapter_not_implemented
- HalfedgeDS: data_structure_adapter_not_implemented
- Heat_method_3: algorithm_adapter_not_implemented
- Hyperbolic_triangulation_2: algorithm_adapter_not_implemented
- Inscribed_areas: algorithm_adapter_not_implemented
- Interval_skip_list: data_structure_adapter_not_implemented
- Isosurfacing_3: algorithm_adapter_not_implemented
- Jet_fitting_3: algorithm_adapter_not_implemented
- Kernel_d: algorithm_adapter_not_implemented
- Kinetic_space_partition: algorithm_adapter_not_implemented
- Linear_cell_complex: data_structure_adapter_not_implemented
- Minkowski_sum_3: algorithm_adapter_not_implemented
- Modular_arithmetic: algorithm_adapter_not_implemented
- Nef_2: algorithm_adapter_not_implemented
- Nef_3: algorithm_adapter_not_implemented
- Nef_S2: algorithm_adapter_not_implemented
- Optimal_bounding_box: algorithm_adapter_not_implemented
- Optimal_transportation_reconstruction_2: algorithm_adapter_not_implemented
- Orthtree: algorithm_adapter_not_implemented
- Partition_2: algorithm_adapter_not_implemented
- Periodic_3_mesh_3: algorithm_adapter_not_implemented
- Periodic_4_hyperbolic_triangulation_2: algorithm_adapter_not_implemented
- Point_set_2: algorithm_adapter_not_implemented
- Point_set_3: data_structure_adapter_not_implemented
- Polygon_repair: algorithm_adapter_not_implemented
- Polyhedron: data_structure_adapter_not_implemented
- Polyline_simplification_2: algorithm_adapter_not_implemented
- Polynomial: algorithm_adapter_not_implemented
- Polytope_distance_d: algorithm_adapter_not_implemented
- Principal_component_analysis: algorithm_adapter_not_implemented
- Ridges_3: algorithm_adapter_not_implemented
- SMDS_3: data_structure_adapter_not_implemented
- SearchStructures: algorithm_adapter_not_implemented
- Segment_Delaunay_graph_2: algorithm_adapter_not_implemented
- Segment_Delaunay_graph_Linf_2: algorithm_adapter_not_implemented
- Set_movable_separability_2: algorithm_adapter_not_implemented
- Shape_detection: algorithm_adapter_not_implemented
- Shape_regularization: algorithm_adapter_not_implemented
- Skin_surface_3: algorithm_adapter_not_implemented
- Snap_rounding_2: algorithm_adapter_not_implemented
- Spatial_sorting: algorithm_adapter_not_implemented
- Stream_lines_2: algorithm_adapter_not_implemented
- Surface_mesh: data_structure_adapter_not_implemented
- Surface_mesh_deformation: algorithm_adapter_not_implemented
- Surface_mesh_topology: algorithm_adapter_not_implemented
- Surface_sweep_2: algorithm_adapter_not_implemented
- TDS_2: data_structure_adapter_not_implemented
- TDS_3: data_structure_adapter_not_implemented
- Tetrahedral_remeshing: algorithm_adapter_not_implemented
- Triangulation: algorithm_adapter_not_implemented
- Triangulation_on_hyperbolic_surface_2: algorithm_adapter_not_implemented
- Visibility_2: algorithm_adapter_not_implemented
- Weights: algorithm_adapter_not_implemented

### EXCLUDED
- Algebraic_foundations: generic_support_infrastructure
- BGL: generic_support_infrastructure
- Basic_viewer: gui_only
- CGAL_ipelets: gui_only
- Circulator: generic_support_infrastructure
- GraphicsView: gui_only
- Miscellany: no_public_headers
- Number_types: generic_support_infrastructure
- Property_map: generic_support_infrastructure
- STL_Extension: generic_support_infrastructure
- Solver_interface: generic_support_infrastructure
- Stream_support: io_only

### Reason codes
- algorithm_adapter_not_implemented (CATALOGED): In-scope algorithmic package without an implemented, validated operation adapter.
- data_structure_adapter_not_implemented (CATALOGED): Official chapter <title> defines a data structure; the MCP uses typed artifacts for exchange and has no dedicated operation or adapter for it yet (not excluded: operations over it remain in scope).
- generic_support_infrastructure (EXCLUDED): Official chapter <title> is generic-programming or arithmetic infrastructure (concepts, number types, containers, property maps, graph/solver adapters) consumed by other packages; it has no standalone geometric operation to expose.
- gui_only (EXCLUDED): Official chapter <title> is an interactive visualization/GUI integration (Qt Graphics View, Ipe, or the Basic Viewer); it produces no headless geometric result that a typed artifact operation could return.
- has_validated_operations (VALIDATED): At least one VALIDATED operation lists this package as its primary package (derived, never listed here).
- io_only (EXCLUDED): Official chapter <title> covers stream/file I/O and formatting; file formats are handled by the MCP artifact import/export layer, not as geometry operations.
- needs_third_party_lib (BLOCKED): Whole package unusable without a third-party library that is not available in the build; no package currently qualifies (optional-dependency packages such as Polygonal_surface_reconstruction/SCIP are built and validated).
- no_public_headers (EXCLUDED): Chapter <title> (profiling tools, hash map, union-find, modifiers) has 0 headers attributed to it in the pinned 6.2.1 release tree and no license tag in the Package Overview; nothing is available to wrap.
- unclassified_in_policy (CATALOGED): Fallback emitted when no policy entry exists; the gate fails while any package carries it.

### Validated packages
AABB_tree, Advancing_front_surface_reconstruction, Alpha_shapes_2, Alpha_shapes_3, Alpha_wrap_3, Arrangement_on_surface_2, Barycentric_coordinates_2, Boolean_set_operations_2, Bounding_volumes, Convex_decomposition_3, Convex_hull_2, Convex_hull_3, Interpolation, Kernel_23, Kinetic_surface_reconstruction, Matrix_search, Mesh_2, Mesh_3, Minkowski_sum_2, PMP_Boolean_operations, PMP_Mesh_repair, PMP_Remeshing, Periodic_2_triangulation_2, Periodic_3_triangulation_3, Point_set_processing_3, Poisson_surface_reconstruction_3, Polygon, Polygon_mesh_processing, Polygonal_surface_reconstruction, QP_solver, Scale_space_reconstruction_3, Spatial_searching, Straight_skeleton_2, Subdivision_method_3, Surface_mesh_approximation, Surface_mesh_parameterization, Surface_mesh_segmentation, Surface_mesh_shortest_path, Surface_mesh_simplification, Surface_mesh_skeletonization, Surface_mesher, Triangulation_2, Triangulation_3, Triangulation_on_sphere_2, Voronoi_diagram_2
