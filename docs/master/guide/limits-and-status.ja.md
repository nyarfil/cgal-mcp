# 上限と正直な対応範囲

## 操作の状態
VALIDATED: 226 (CGAL 6.2.1)
実行できるのはVALIDATED/IMPLEMENTEDの操作だけ。VALIDATEDは同梱fixtureで独立検証器つきの再実行に合格した意味で、全入力の証明ではない。システム全体の受入は再実行束縛の評価器（scripts/master_acceptance.py）が別に管理し、このガイドは達成を主張しない。

## パッケージ目録
126 CGAL packages: VALIDATED 45, CATALOGED 69, EXCLUDED 12
VALIDATED=実行可能な検証済み操作が1つ以上ある。CATALOGED=文書・ソースの索引のみで実行不可。EXCLUDED=単独のヘッドレス操作が存在しない。

## 上限
- import: at most 512 MiB per file; formats off, obj, ply (ASCII), stl, xyz and typed json; units mm, cm or m (reports: none)
- execution defaults: concurrency 2, worker memory 4096 MiB, wall time 120 s, ceiling 86400 s; live values: cgal_system_health; per call: cgal_execute execution={"wall_time_ms":..., "memory_mb":...}
- 操作ごとの面数上限（各カードに明記）: 64 faces: 1 ops; 200 faces: 2 ops; 400 faces: 7 ops; 600 faces: 5 ops; 1500 faces: 2 ops; 2000 faces: 5 ops; 3000 faces: 2 ops; 20000 faces: 12 ops; 200000 faces: 6 ops; 400000 faces: 3 ops; 2000000 faces: 17 ops
- 厳しい上限の例: 400 faces: mesh.distance.hausdorff_approximate, mesh.distance.hausdorff_approximate_symmetric, mesh.distance.hausdorff_bounded, mesh.distance.max_to_mesh, mesh.distance.max_to_points, mesh.distance.sample_points, mesh.distance.symmetric_hausdorff

## 未対応（CATALOGEDまたはEXCLUDEDのパッケージ）
これらを名指しした要求は、cgal_capabilities_search/cgal_planがfail-closed（unsupported_operation、details.unsupported_cgal_packages）。ユーザーに未対応と伝え、近い操作を黙って代用しない。

### CATALOGED
- Algebraic_kernel_d: algorithm_adapter_not_implemented (代数カーネル)
- Alpha_wrap_2: algorithm_adapter_not_implemented (2dアルファラップ)
- Apollonius_graph_2: algorithm_adapter_not_implemented (アポロニウス)
- Barycentric_coordinates_3: algorithm_adapter_not_implemented (3次元重心座標)
- Box_intersection_d: algorithm_adapter_not_implemented (ボックス交差)
- Circular_kernel_2: algorithm_adapter_not_implemented (円弧カーネル)
- Circular_kernel_3: algorithm_adapter_not_implemented (球カーネル)
- Classification: algorithm_adapter_not_implemented (点群分類)
- Combinatorial_map: data_structure_adapter_not_implemented
- Cone_spanners_2: algorithm_adapter_not_implemented (コーンスパナー)
- Constrained_triangulation_3: algorithm_adapter_not_implemented (3d制約付き三角形分割)
- Convex_hull_d: algorithm_adapter_not_implemented (高次元凸包)
- Envelope_2: algorithm_adapter_not_implemented (包絡線)
- Envelope_3: algorithm_adapter_not_implemented (3d包絡)
- Frechet_distance: algorithm_adapter_not_implemented (フレシェ)
- Generalized_map: data_structure_adapter_not_implemented
- Generator: algorithm_adapter_not_implemented (乱数点生成)
- HalfedgeDS: data_structure_adapter_not_implemented
- Heat_method_3: algorithm_adapter_not_implemented (熱法)
- Hyperbolic_triangulation_2: algorithm_adapter_not_implemented (双曲)
- Inscribed_areas: algorithm_adapter_not_implemented (最大内接)
- Interval_skip_list: data_structure_adapter_not_implemented
- Isosurfacing_3: algorithm_adapter_not_implemented (等値面抽出)
- Jet_fitting_3: algorithm_adapter_not_implemented (局所微分特性)
- Kernel_d: algorithm_adapter_not_implemented (高次元カーネル)
- Kinetic_space_partition: algorithm_adapter_not_implemented (動的空間分割)
- Linear_cell_complex: data_structure_adapter_not_implemented
- Minkowski_sum_3: algorithm_adapter_not_implemented (3dミンコフスキー和)
- Modular_arithmetic: algorithm_adapter_not_implemented (モジュラー演算)
- Nef_2: algorithm_adapter_not_implemented (ネフ多角形)
- Nef_3: algorithm_adapter_not_implemented (ネフ多面体)
- Nef_S2: algorithm_adapter_not_implemented (球面上のネフ)
- Optimal_bounding_box: algorithm_adapter_not_implemented (最適バウンディングボックス)
- Optimal_transportation_reconstruction_2: algorithm_adapter_not_implemented (最適輸送)
- Orthtree: algorithm_adapter_not_implemented (四分木)
- Partition_2: algorithm_adapter_not_implemented (多角形分割)
- Periodic_3_mesh_3: algorithm_adapter_not_implemented (周期メッシュ生成)
- Periodic_4_hyperbolic_triangulation_2: algorithm_adapter_not_implemented (周期双曲)
- Point_set_2: algorithm_adapter_not_implemented (2d範囲探索)
- Point_set_3: data_structure_adapter_not_implemented
- Polygon_repair: algorithm_adapter_not_implemented
- Polyhedron: data_structure_adapter_not_implemented
- Polyline_simplification_2: algorithm_adapter_not_implemented (ポリライン簡略化)
- Polynomial: algorithm_adapter_not_implemented (多項式)
- Polytope_distance_d: algorithm_adapter_not_implemented (多面体間の最短距離)
- Principal_component_analysis: algorithm_adapter_not_implemented
- Ridges_3: algorithm_adapter_not_implemented (リッジ)
- SMDS_3: data_structure_adapter_not_implemented
- SearchStructures: algorithm_adapter_not_implemented (レンジツリー)
- Segment_Delaunay_graph_2: algorithm_adapter_not_implemented (線分ドロネーグラフ)
- Segment_Delaunay_graph_Linf_2: algorithm_adapter_not_implemented (l無限大)
- Set_movable_separability_2: algorithm_adapter_not_implemented (移動可能分離)
- Shape_detection: algorithm_adapter_not_implemented (形状検出)
- Shape_regularization: algorithm_adapter_not_implemented (形状正則化)
- Skin_surface_3: algorithm_adapter_not_implemented (スキンサーフェス)
- Snap_rounding_2: algorithm_adapter_not_implemented (スナップラウンディング)
- Spatial_sorting: algorithm_adapter_not_implemented (空間ソート)
- Stream_lines_2: algorithm_adapter_not_implemented (流線)
- Surface_mesh: data_structure_adapter_not_implemented
- Surface_mesh_deformation: algorithm_adapter_not_implemented (メッシュ変形)
- Surface_mesh_topology: algorithm_adapter_not_implemented (ホモトピー)
- Surface_sweep_2: algorithm_adapter_not_implemented (曲線の交差)
- TDS_2: data_structure_adapter_not_implemented
- TDS_3: data_structure_adapter_not_implemented
- Tetrahedral_remeshing: algorithm_adapter_not_implemented (四面体リメッシュ)
- Triangulation: algorithm_adapter_not_implemented (高次元三角形分割)
- Triangulation_on_hyperbolic_surface_2: algorithm_adapter_not_implemented (双曲曲面)
- Visibility_2: algorithm_adapter_not_implemented (可視領域)
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

### 理由コード
- algorithm_adapter_not_implemented (CATALOGED): In-scope algorithmic package without an implemented, validated operation adapter.
- data_structure_adapter_not_implemented (CATALOGED): Official chapter <title> defines a data structure; the MCP uses typed artifacts for exchange and has no dedicated operation or adapter for it yet (not excluded: operations over it remain in scope).
- generic_support_infrastructure (EXCLUDED): Official chapter <title> is generic-programming or arithmetic infrastructure (concepts, number types, containers, property maps, graph/solver adapters) consumed by other packages; it has no standalone geometric operation to expose.
- gui_only (EXCLUDED): Official chapter <title> is an interactive visualization/GUI integration (Qt Graphics View, Ipe, or the Basic Viewer); it produces no headless geometric result that a typed artifact operation could return.
- has_validated_operations (VALIDATED): At least one VALIDATED operation lists this package as its primary package (derived, never listed here).
- io_only (EXCLUDED): Official chapter <title> covers stream/file I/O and formatting; file formats are handled by the MCP artifact import/export layer, not as geometry operations.
- needs_third_party_lib (BLOCKED): Whole package unusable without a third-party library that is not available in the build; no package currently qualifies (optional-dependency packages such as Polygonal_surface_reconstruction/SCIP are built and validated).
- no_public_headers (EXCLUDED): Chapter <title> (profiling tools, hash map, union-find, modifiers) has 0 headers attributed to it in the pinned 6.2.1 release tree and no license tag in the Package Overview; nothing is available to wrap.
- unclassified_in_policy (CATALOGED): Fallback emitted when no policy entry exists; the gate fails while any package carries it.

### 検証済みパッケージ
AABB_tree, Advancing_front_surface_reconstruction, Alpha_shapes_2, Alpha_shapes_3, Alpha_wrap_3, Arrangement_on_surface_2, Barycentric_coordinates_2, Boolean_set_operations_2, Bounding_volumes, Convex_decomposition_3, Convex_hull_2, Convex_hull_3, Interpolation, Kernel_23, Kinetic_surface_reconstruction, Matrix_search, Mesh_2, Mesh_3, Minkowski_sum_2, PMP_Boolean_operations, PMP_Mesh_repair, PMP_Remeshing, Periodic_2_triangulation_2, Periodic_3_triangulation_3, Point_set_processing_3, Poisson_surface_reconstruction_3, Polygon, Polygon_mesh_processing, Polygonal_surface_reconstruction, QP_solver, Scale_space_reconstruction_3, Spatial_searching, Straight_skeleton_2, Subdivision_method_3, Surface_mesh_approximation, Surface_mesh_parameterization, Surface_mesh_segmentation, Surface_mesh_shortest_path, Surface_mesh_simplification, Surface_mesh_skeletonization, Surface_mesher, Triangulation_2, Triangulation_3, Triangulation_on_sphere_2, Voronoi_diagram_2
