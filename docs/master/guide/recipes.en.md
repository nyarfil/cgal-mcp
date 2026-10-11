# Recipes: if the user wants X, do these steps

Each recipe is a verified workflow (run by the acceptance suite against the real worker). Read one with cgal_get_guide(topic="recipe:<id>") or resource cgal://guide/recipe/<id>; it contains fixtures, the exact cgal_plan request and the expected outcome.

## Positive recipes
- wf01-soup-orient-loop-inspect: If the user wants: Orient a flipped soup, subdivide, inspect
  JA: 裏返ったポリゴンスープの向きを直し、細分割して検査する
  ops: mesh.repair.orient -> mesh.subdivide.loop -> mesh.inspect.pmp
  keywords: mesh.repair.orientation; loop subdivision; triangle subdivision; ループ細分割; mesh health inspection; PMP predicates; メッシュ健全性検査
- wf02-fillholes-loop-measures: If the user wants: Fill hole, subdivide, measure
  JA: 穴を埋めて細分割し、面積・体積を測る
  ops: mesh.repair.fill_holes -> mesh.subdivide.loop -> mesh.analysis.measures
  keywords: mesh.repair.triangulate_holes; loop subdivision; triangle subdivision; ループ細分割; mesh area volume centroid; geometric measures; メッシュ計量
- wf03-stitch-components: If the user wants: Stitch seam then connected components
  JA: 割れた境界を縫合して連結成分を調べる
  ops: mesh.repair.stitch_borders -> mesh.analysis.connected_components
  keywords: mesh.repair.stitch; mesh components; face connected components; メッシュ連結成分
- wf04-degenerate-remove-selfintersect: If the user wants: Remove degenerate faces then self-intersection check
  JA: 退化面を除去し自己交差を確認する
  ops: mesh.repair.remove_degenerate -> mesh.analysis.self_intersections
  keywords: mesh.repair.remove_degenerate_faces; mesh self intersections; intersecting face pairs; 自己交差検査
- wf05-dirtysoup-clean-orient-measure: If the user wants: Polygon soup cleanup, orient, measure
  JA: 汚れたポリゴンスープを整理・向き付けして測る
  ops: mesh.repair.polygon_soup -> mesh.repair.orient -> mesh.analysis.measures
  keywords: mesh.repair.soup; mesh.repair.orientation; mesh area volume centroid; geometric measures; メッシュ計量
- wf06-remesh-simplify-hausdorff-join: If the user wants: Remesh and simplify branches joined by a Hausdorff report
  JA: リメッシュして軽量化し、Hausdorff距離で比較する
  ops: mesh.remesh.isotropic -> mesh.simplify.edge_collapse -> mesh.distance.hausdorff_approximate
  keywords: isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh simplification; edge collapse; surface mesh simplification; メッシュ簡略化; エッジ崩壊; approximate Hausdorff distance; Hausdorff distance of sampled points; mesh deviation sampling; 近似ハウスドルフ距離
- wf07-smooth-remesh-simplify: If the user wants: Smooth noisy sphere, remesh, simplify
  JA: 平滑化・リメッシュ・軽量化を続けて行う
  ops: mesh.smooth.shape -> mesh.remesh.isotropic -> mesh.simplify.edge_collapse
  keywords: smooth shape; mesh smoothing; curvature flow smoothing; fair surface; 形状スムージング; メッシュ平滑化; isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh simplification; edge collapse; surface mesh simplification; メッシュ簡略化; エッジ崩壊
- wf08-refine-measure: If the user wants: Locally refine a fan then measure
  JA: メッシュを細分して測定する
  ops: mesh.refine.local -> mesh.analysis.measures
  keywords: refine mesh; mesh refinement; densify triangles; メッシュ細分化; メッシュリファイン; mesh area volume centroid; geometric measures; メッシュ計量
- wf09-union-keeplargest-loop: If the user wants: Union of overlapping cubes, keep largest component, subdivide
  JA: 2つのメッシュを和にして最大成分を残し細分割する
  ops: mesh.boolean.union -> mesh.components.keep_largest -> mesh.subdivide.loop
  keywords: mesh.boolean.corefine_union; keep largest components; remove small components; 小成分削除; loop subdivision; triangle subdivision; ループ細分割
- wf10-difference-measures: If the user wants: Difference of cubes then measures
  JA: メッシュの差（くり抜き）を作って測る
  ops: mesh.boolean.difference -> mesh.analysis.measures
  keywords: mesh.boolean.corefine_difference; mesh area volume centroid; geometric measures; メッシュ計量
- wf11-union-then-difference-chain: If the user wants: Chained booleans where the second consumes the first
  JA: 和のあとに差を取るBoolean連鎖
  ops: mesh.boolean.union -> mesh.boolean.difference -> mesh.inspect.pmp
  keywords: mesh.boolean.corefine_union; mesh.boolean.corefine_difference; mesh health inspection; PMP predicates; メッシュ健全性検査
- wf12-clip-measures: If the user wants: Clip a cube by a plane then measure
  JA: 平面でメッシュをクリップして測る
  ops: mesh.clip.plane -> mesh.analysis.measures
  keywords: clip mesh; plane clipping; cut by plane; クリッピング; mesh area volume centroid; geometric measures; メッシュ計量
- wf13-corefine-components: If the user wants: Corefine two tetrahedra then component analysis
  JA: 2つのメッシュをcorefineして成分を調べる
  ops: mesh.corefine -> mesh.analysis.connected_components
  keywords: corefinement; corefine meshes; refine along intersection; コリファイン; mesh components; face connected components; メッシュ連結成分
- wf14-catmull-triangulate-measure: If the user wants: Catmull-Clark to a soup, triangulate, measure
  JA: Catmull-Clark細分割から三角形化して測る
  ops: mesh.subdivide.catmull_clark -> mesh.triangulate.faces -> mesh.analysis.measures
  keywords: catmull clark; subdivision surface; 細分割; triangulate faces; triangulate polygon mesh; quad to triangle; convert polygons to triangles; 面の三角形分割; ポリゴンを三角形化; mesh area volume centroid; geometric measures; メッシュ計量
- wf15-points-alphawrap-remesh-measures: If the user wants: Alpha wrap a cloud, remesh, measure
  JA: 点群をalpha wrappingで面にしてリメッシュ・測定する
  ops: reconstruction.alpha_wrap -> mesh.remesh.isotropic -> mesh.analysis.measures
  keywords: alpha wrap; alpha wrapping; watertight wrap; shrink wrap; アルファラッピング; 包み込み再構成; isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh area volume centroid; geometric measures; メッシュ計量
- wf16-poisson-remesh-inspect: If the user wants: Poisson reconstruction from oriented normals, remesh, inspect
  JA: 法線付き点群からPoisson再構成してリメッシュ・検査する
  ops: reconstruction.poisson -> mesh.remesh.isotropic -> mesh.inspect.pmp
  keywords: Poisson reconstruction; surface from oriented points; implicit surface reconstruction; ポアソン曲面再構成; 点群から曲面再構成; isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh health inspection; PMP predicates; メッシュ健全性検査
- wf17-outliers-grid-afsr-measures: If the user wants: Denoise cloud, thin, advancing-front reconstruct, measure
  JA: 外れ値除去・格子間引きののちadvancing frontで面を作る
  ops: pointset.remove_outliers -> pointset.simplify.grid -> reconstruction.advancing_front -> mesh.analysis.measures
  keywords: point set outlier removal; remove noisy points; 点群外れ値除去; grid point simplification; voxel point reduction; 点群グリッド簡略化; advancing front reconstruction; interpolating surface reconstruction; Delaunay based reconstruction; アドバンシングフロント再構成; mesh area volume centroid; geometric measures; メッシュ計量
- wf18-jet-alphawrap-components: If the user wants: Jet smooth a noisy cloud then alpha wrap
  JA: jet平滑化した点群をalpha wrappingして成分を調べる
  ops: pointset.smooth.jet -> reconstruction.alpha_wrap -> mesh.analysis.connected_components
  keywords: jet point smoothing; smooth point cloud; 点群ジェット平滑化; alpha wrap; alpha wrapping; watertight wrap; shrink wrap; アルファラッピング; 包み込み再構成; mesh components; face connected components; メッシュ連結成分
- wf19-hull3-loop-measures: If the user wants: 3D hull of a cloud then subdivision and measures
  JA: 点群の3D凸包を作り細分割して測る
  ops: hull.convex_3 -> mesh.subdivide.loop -> mesh.analysis.measures
  keywords: 3d convex hull; convex hull points; 包絡凸包; 3次元凸包; loop subdivision; triangle subdivision; ループ細分割; mesh area volume centroid; geometric measures; メッシュ計量
- wf20-outlier-normals-orient: If the user wants: Outlier removal, normals, orientation
  JA: 外れ値を除き法線を推定して向きを揃える
  ops: pointset.remove_outliers -> pointset.normals.estimate -> pointset.normals.orient_mst
  keywords: point set outlier removal; remove noisy points; 点群外れ値除去; estimate point normals; pca normals; jet normals; 点群法線推定; orient point normals; mst normal orientation; 点群法線方向付け
- wf21-random-delaunay3: If the user wants: Random thinning then 3D Delaunay
  JA: ランダム点から3D Delaunay三角形分割を作る
  ops: pointset.simplify.random -> triangulation.delaunay_3
  keywords: random point simplification; seeded point sampling; 点群ランダム簡略化; delaunay triangulation 3d; tetrahedralization; 3次元ドロネー三角形分割; 四面体分割
- wf22-wrap-and-thinned-cloud-join: If the user wants: Alpha-wrapped surface and thinned cloud branches joined by closest-point queries
  JA: ラップした面と間引いた点群を合わせて扱う
  ops: reconstruction.alpha_wrap -> pointset.simplify.random -> spatial.aabb.closest_points
  keywords: alpha wrap; alpha wrapping; watertight wrap; shrink wrap; アルファラッピング; 包み込み再構成; random point simplification; seeded point sampling; 点群ランダム簡略化; aabb tree closest point; closest point on mesh; nearest point on surface; AABBツリー最近点; メッシュ最近点
- wf23-remesh-closest-points: If the user wants: Remesh then closest points of queries
  JA: リメッシュ後に最近点を問い合わせる
  ops: mesh.remesh.isotropic -> spatial.aabb.closest_points
  keywords: isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; aabb tree closest point; closest point on mesh; nearest point on surface; AABBツリー最近点; メッシュ最近点
- wf24-grid-maxdistance-join: If the user wants: Thinned cloud against a reference mesh
  JA: 格子間引き点群からメッシュへの最大距離を測る
  ops: pointset.simplify.grid -> mesh.distance.max_to_mesh
  keywords: grid point simplification; voxel point reduction; 点群グリッド簡略化; max distance to triangle mesh; maximum point to mesh distance; point set to surface deviation; 点群からメッシュへの最大距離
- wf25-random-bbox: If the user wants: Random thinning then bounding box
  JA: ランダム点のバウンディングボックスを求める
  ops: pointset.simplify.random -> spatial.bbox_3
  keywords: random point simplification; seeded point sampling; 点群ランダム簡略化; bounding box 3d; bbox 3d; axis aligned bounding box; 3次元バウンディングボックス; 外接直方体
- wf26-remesh-slice: If the user wants: Remesh then planar slice
  JA: リメッシュしたメッシュを平面でスライスする
  ops: mesh.remesh.isotropic -> mesh.slice.compute
  keywords: isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh slicer; plane section; cross section polylines; 断面
- wf27-hull2-polygon-boolean: If the user wants: 2D hull of points boolean-joined with a polygon
  JA: 2D凸包の多角形同士でBooleanを行う
  ops: hull.convex_2 -> polygon.boolean
  keywords: 2d convex hull; planar convex hull; convex hull of points in the plane; convex_hull_2; 2次元凸包; 平面凸包; polygon boolean; polygon union; polygon difference; 2D set operations; ポリゴンブーリアン
- wf28-hull2-minkowski: If the user wants: 2D hull then Minkowski sum
  JA: 2D凸包を作りMinkowski和を求める
  ops: hull.convex_2 -> polygon.minkowski_sum
  keywords: 2d convex hull; planar convex hull; convex hull of points in the plane; convex_hull_2; 2次元凸包; 平面凸包; minkowski sum; minkowski sum of polygons; polygon dilation by polygon; configuration space obstacle; ミンコフスキー和; ミンコフスキー和ポリゴン
- wf29-hull2-barycentric: If the user wants: 2D hull then barycentric coordinates of queries
  JA: 2D凸包上で重心座標を求める
  ops: hull.convex_2 -> shape.barycentric
  keywords: 2d convex hull; planar convex hull; convex hull of points in the plane; convex_hull_2; 2次元凸包; 平面凸包; barycentric coordinates; wachspress coordinates; mean value coordinates; discrete harmonic coordinates; generalized barycentric coordinates; 重心座標
- wf30-surface-generate-remesh-measures: If the user wants: Implicit surface meshing then remesh and measure
  JA: 曲面メッシュを生成してリメッシュ・測定する
  ops: mesh.surface.generate -> mesh.remesh.isotropic -> mesh.analysis.measures
  keywords: surface mesh generation; make_surface_mesh; surface mesher; implicit surface meshing; mesh an implicit surface; isosurface triangulation; sphere mesh generation; ellipsoid mesh generation; torus mesh generation; 曲面メッシュ生成; 陰関数曲面のメッシュ化; 球面メッシュ生成; トーラスメッシュ生成; isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh area volume centroid; geometric measures; メッシュ計量
- wf31-unit-propagation-cm: If the user wants: Centimetre mesh flows through remesh and simplify with millimetre parameters
  JA: cm単位のメッシュをmm指定のパラメータでリメッシュ・軽量化する
  ops: mesh.remesh.isotropic -> mesh.simplify.edge_collapse -> mesh.analysis.measures
  keywords: isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh simplification; edge collapse; surface mesh simplification; メッシュ簡略化; エッジ崩壊; mesh area volume centroid; geometric measures; メッシュ計量
- wf33-hull-clip-measure: If the user wants: Hull of a cloud, clip by a plane, measure
  JA: 凸包を作り平面でクリップして測る
  ops: hull.convex_3 -> mesh.clip.plane -> mesh.analysis.measures
  keywords: 3d convex hull; convex hull points; 包絡凸包; 3次元凸包; clip mesh; plane clipping; cut by plane; クリッピング; mesh area volume centroid; geometric measures; メッシュ計量
- wf34-clip-loop-inspect: If the user wants: Clip a cube, subdivide, inspect
  JA: クリップして細分割し検査する
  ops: mesh.clip.plane -> mesh.subdivide.loop -> mesh.inspect.pmp
  keywords: clip mesh; plane clipping; cut by plane; クリッピング; loop subdivision; triangle subdivision; ループ細分割; mesh health inspection; PMP predicates; メッシュ健全性検査
- wf35-simplify-loop-inspect: If the user wants: Simplify then subdivide and inspect
  JA: 軽量化してから細分割し検査する
  ops: mesh.simplify.edge_collapse -> mesh.subdivide.loop -> mesh.inspect.pmp
  keywords: mesh simplification; edge collapse; surface mesh simplification; メッシュ簡略化; エッジ崩壊; loop subdivision; triangle subdivision; ループ細分割; mesh health inspection; PMP predicates; メッシュ健全性検査
- wf36-cloud-hull-loop-selfintersect: If the user wants: Hull of a cloud, subdivide, self-intersection check
  JA: 点群の凸包を細分割し自己交差を確認する
  ops: hull.convex_3 -> mesh.subdivide.loop -> mesh.analysis.self_intersections
  keywords: 3d convex hull; convex hull points; 包絡凸包; 3次元凸包; loop subdivision; triangle subdivision; ループ細分割; mesh self intersections; intersecting face pairs; 自己交差検査
- wf37-cm-unit-loop-measures: If the user wants: Centimetre cube subdivides and measures in centimetres
  JA: cm単位メッシュを細分割して測る
  ops: mesh.subdivide.loop -> mesh.analysis.measures
  keywords: loop subdivision; triangle subdivision; ループ細分割; mesh area volume centroid; geometric measures; メッシュ計量
- wf38-union-simplify-compare: If the user wants: Union then simplify with a Hausdorff comparison joining both
  JA: 和を作って軽量化し元と比較する
  ops: mesh.boolean.union -> mesh.simplify.edge_collapse -> mesh.distance.hausdorff_approximate
  keywords: mesh.boolean.corefine_union; mesh simplification; edge collapse; surface mesh simplification; メッシュ簡略化; エッジ崩壊; approximate Hausdorff distance; Hausdorff distance of sampled points; mesh deviation sampling; 近似ハウスドルフ距離
- wf39-hull2-arrangement-overlay: If the user wants: 2D hull overlaid with a polygon
  JA: 2D凸包でアレンジメントとオーバーレイを作る
  ops: hull.convex_2 -> arrangement.overlay
  keywords: 2d convex hull; planar convex hull; convex hull of points in the plane; convex_hull_2; 2次元凸包; 平面凸包; overlay of arrangements; polygon overlay; overlay two polygons; map overlay; face overlay labels; オーバーレイ; ポリゴンオーバーレイ
- wf40-outliers-grid-delaunay3: If the user wants: Outlier removal, grid thinning, Delaunay
  JA: 外れ値除去・格子間引きののち3D Delaunayを作る
  ops: pointset.remove_outliers -> pointset.simplify.grid -> triangulation.delaunay_3
  keywords: point set outlier removal; remove noisy points; 点群外れ値除去; grid point simplification; voxel point reduction; 点群グリッド簡略化; delaunay triangulation 3d; tetrahedralization; 3次元ドロネー三角形分割; 四面体分割
- wf41-noisy-smooth-loop-measures: If the user wants: Smooth a noisy sphere then subdivide and measure
  JA: ノイズのあるメッシュを平滑化して細分割・測定する
  ops: mesh.smooth.shape -> mesh.subdivide.loop -> mesh.analysis.measures
  keywords: smooth shape; mesh smoothing; curvature flow smoothing; fair surface; 形状スムージング; メッシュ平滑化; loop subdivision; triangle subdivision; ループ細分割; mesh area volume centroid; geometric measures; メッシュ計量
- wf42-rules-soup-loop-auto-orient-inspect: If the user wants: A flipped soup feeds subdivision directly; the planner inserts orient before and inspection after
  JA: プランナー規則で前処理（向き）と後処理（検査）を自動挿入する
  ops: mesh.subdivide.loop
  keywords: loop subdivision; triangle subdivision; ループ細分割
- wf43-fallback-plan-time-block: If the user wants: A union of millimetre and centimetre operands is blocked at planning; the declared same-unit union then subdivision is served
  JA: 単位不一致で計画段階でブロックされたら宣言済みの代替案で実行する
  ops: mesh.boolean.union
  keywords: mesh.boolean.corefine_union
- wf44-fallback-runtime-failure: If the user wants: Poisson from estimated normals yields nothing; the alpha-wrap alternative is served
  JA: 実行時に失敗したら宣言済みの代替案に切り替える
  ops: pointset.normals.estimate -> pointset.normals.orient_mst -> reconstruction.poisson
  keywords: estimate point normals; pca normals; jet normals; 点群法線推定; orient point normals; mst normal orientation; 点群法線方向付け; Poisson reconstruction; surface from oriented points; implicit surface reconstruction; ポアソン曲面再構成; 点群から曲面再構成
- wf45-fallback-validator-rejection: If the user wants: Jet smoothing is rejected by its validator; direct alpha wrapping is served
  JA: 検証器に却下されたら宣言済みの代替案に切り替える
  ops: pointset.smooth.jet -> reconstruction.alpha_wrap
  keywords: jet point smoothing; smooth point cloud; 点群ジェット平滑化; alpha wrap; alpha wrapping; watertight wrap; shrink wrap; アルファラッピング; 包み込み再構成

## Expected refusals (fail-closed demonstrations)
- neg01-invalid-index-import: mesh with an out-of-range vertex index is refused at import -> {"stage": "import", "state": "refused"}
- neg02-nonmanifold-simplify: non-manifold input is rejected by the worker and nothing is published -> {"code": "MALFORMED_OFF", "stage": "execute", "state": "failed"}
- neg03-unit-mismatch-boolean: millimetre and centimetre operands cannot be combined -> {"code": "unit_mismatch", "stage": "plan", "state": "refused"}
- neg04-type-mismatch-dag-edge: a point set output cannot feed a mesh-only input -> {"code": "dag_type", "stage": "plan", "state": "refused"}
- neg05-cyclic-dag: a cyclic dependency graph is refused -> {"code": "dag_type", "stage": "plan", "state": "refused"}
- neg06-validator-rejects-remesh: remesh with a deviation bound the result cannot meet is rejected by its validator -> {"code": "HAUSDORFF_WITHIN_MAX_DEVIATION_FAILED", "stage": "execute", "state": "rejected"}
- neg06b-validator-budget-exceeded: a validator bound too tight for its validation budget fails closed -> {"code": "VALIDATION_BUDGET_EXCEEDED", "stage": "execute", "state": "failed"}
- neg07-validator-rejects-jet-smoothing: jet smoothing that does not reduce roughness is rejected -> {"code": "ROUGHNESS_NOT_REDUCED", "stage": "execute", "state": "rejected"}
- neg08-empty-reconstruction-fails-closed: Poisson reconstruction from estimated normals yields nothing and publishes nothing -> {"code": "EMPTY_RECONSTRUCTION", "stage": "execute", "state": "failed"}
- neg09-face-limit-refused-at-plan: a mesh over the Hausdorff face limit is refused when planning -> {"code": "unmet_precondition", "stage": "plan", "state": "refused"}
- neg10-face-limit-refused-at-runtime: an intermediate mesh over a downstream face limit is refused before dispatch -> {"code": "unmet_precondition", "stage": "execute", "state": "failed"}
- neg10b-torus-simplify-limit: a large mesh is simplified but its Hausdorff validator is refused over the face limit -> {"code": "unmet_precondition", "stage": "execute", "state": "failed"}
- neg11-wall-time-limit-out-of-range: an out-of-range wall-time request is refused -> {"code": "execution_limits", "stage": "execute_limits", "state": "refused"}
- neg12-memory-limit-out-of-range: an out-of-range memory request is refused -> {"code": "execution_limits", "stage": "execute_limits", "state": "refused"}
- neg13-missing-required-parameter: a missing required parameter is refused -> {"code": "parameters_required", "stage": "plan", "state": "refused"}
- neg14-unhealthy-boolean-operand: an open surface fails closed as a boolean volume operand -> {"code": "MESH_NOT_CLOSED", "stage": "execute", "state": "failed"}
- neg15-unknown-operation: an unregistered operation is refused -> {"stage": "plan", "state": "refused"}
- neg16-spoofed-validator-binding: an explicit validator that is not bound exactly to its transform is refused -> {"code": "validator_binding", "stage": "plan", "state": "refused"}
- neg17-license-policy-gate: a license policy that excludes the package refuses the workflow -> {"stage": "plan", "state": "refused"}
- neg18-missing-input-slot: a step lacking a required input slot is refused -> {"code": "input_binding", "stage": "plan", "state": "refused"}
- neg19-ambiguous-component-tie: keeping the largest of equal-sized components is refused as ambiguous -> {"code": "AMBIGUOUS_COMPONENT_TIE", "stage": "execute", "state": "failed"}
- neg20-fallback-chain-exhausted: every declared alternative also fails; the job fails closed with the whole chain recorded and nothing published -> {"code": "EMPTY_RECONSTRUCTION", "stage": "execute", "state": "failed"}
- neg21-fallback-all-blocked: every candidate is blocked at planning so nothing runs -> {"code": "unmet_precondition", "stage": "plan", "state": "refused"}
