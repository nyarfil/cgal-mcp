# レシピ: ユーザーがXを望むならこの手順

各レシピは検証済みワークフロー（受入試験が実workerで実行）。cgal_get_guide(topic="recipe:<id>")またはcgal://guide/recipe/<id>で読む。fixture、cgal_planのリクエスト全文、期待結果が載っている。

## 成功するレシピ
- wf01-soup-orient-loop-inspect: 要望: 裏返ったポリゴンスープの向きを直し、細分割して検査する
  EN: orient a flipped soup, subdivide, inspect
  ops: mesh.repair.orient -> mesh.subdivide.loop -> mesh.inspect.pmp
  keywords: mesh.repair.orientation; loop subdivision; triangle subdivision; ループ細分割; mesh health inspection; PMP predicates; メッシュ健全性検査
- wf02-fillholes-loop-measures: 要望: 穴を埋めて細分割し、面積・体積を測る
  EN: fill hole, subdivide, measure
  ops: mesh.repair.fill_holes -> mesh.subdivide.loop -> mesh.analysis.measures
  keywords: mesh.repair.triangulate_holes; fill selected holes; fill holes by id; 選んだ穴だけ埋める; 指定した穴だけ埋める; loop subdivision; triangle subdivision; ループ細分割; mesh area volume centroid; geometric measures; メッシュ計量
- wf03-stitch-components: 要望: 割れた境界を縫合して連結成分を調べる
  EN: stitch seam then connected components
  ops: mesh.repair.stitch_borders -> mesh.analysis.connected_components
  keywords: mesh.repair.stitch; mesh components; face connected components; メッシュ連結成分
- wf04-degenerate-remove-selfintersect: 要望: 退化面を除去し自己交差を確認する
  EN: remove degenerate faces then self-intersection check
  ops: mesh.repair.remove_degenerate -> mesh.analysis.self_intersections
  keywords: mesh.repair.remove_degenerate_faces; mesh self intersections; intersecting face pairs; 自己交差検査
- wf05-dirtysoup-clean-orient-measure: 要望: 汚れたポリゴンスープを整理・向き付けして測る
  EN: polygon soup cleanup, orient, measure
  ops: mesh.repair.polygon_soup -> mesh.repair.orient -> mesh.analysis.measures
  keywords: mesh.repair.soup; mesh.repair.orientation; mesh area volume centroid; geometric measures; メッシュ計量
- wf06-remesh-simplify-hausdorff-join: 要望: リメッシュして軽量化し、Hausdorff距離で比較する
  EN: remesh and simplify branches joined by a Hausdorff report
  ops: mesh.remesh.isotropic -> mesh.simplify.edge_collapse -> mesh.distance.hausdorff_approximate
  keywords: isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh simplification; edge collapse; surface mesh simplification; メッシュ簡略化; エッジ崩壊; approximate Hausdorff distance; Hausdorff distance of sampled points; mesh deviation sampling; 近似ハウスドルフ距離
- wf07-smooth-remesh-simplify: 要望: 平滑化・リメッシュ・軽量化を続けて行う
  EN: smooth noisy sphere, remesh, simplify
  ops: mesh.smooth.shape -> mesh.remesh.isotropic -> mesh.simplify.edge_collapse
  keywords: smooth shape; mesh smoothing; curvature flow smoothing; fair surface; 形状スムージング; メッシュ平滑化; isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh simplification; edge collapse; surface mesh simplification; メッシュ簡略化; エッジ崩壊
- wf08-refine-measure: 要望: メッシュを細分して測定する
  EN: locally refine a fan then measure
  ops: mesh.refine.local -> mesh.analysis.measures
  keywords: refine mesh; mesh refinement; densify triangles; メッシュ細分化; メッシュリファイン; mesh area volume centroid; geometric measures; メッシュ計量
- wf09-union-keeplargest-loop: 要望: 2つのメッシュを和にして最大成分を残し細分割する
  EN: union of overlapping cubes, keep largest component, subdivide
  ops: mesh.boolean.union -> mesh.components.keep_largest -> mesh.subdivide.loop
  keywords: mesh.boolean.corefine_union; keep largest components; remove small components; 小成分削除; loop subdivision; triangle subdivision; ループ細分割
- wf10-difference-measures: 要望: メッシュの差（くり抜き）を作って測る
  EN: difference of cubes then measures
  ops: mesh.boolean.difference -> mesh.analysis.measures
  keywords: mesh.boolean.corefine_difference; mesh area volume centroid; geometric measures; メッシュ計量
- wf11-union-then-difference-chain: 要望: 和のあとに差を取るBoolean連鎖
  EN: chained booleans where the second consumes the first
  ops: mesh.boolean.union -> mesh.boolean.difference -> mesh.inspect.pmp
  keywords: mesh.boolean.corefine_union; mesh.boolean.corefine_difference; mesh health inspection; PMP predicates; メッシュ健全性検査
- wf12-clip-measures: 要望: 平面でメッシュをクリップして測る
  EN: clip a cube by a plane then measure
  ops: mesh.clip.plane -> mesh.analysis.measures
  keywords: clip mesh; plane clipping; cut by plane; クリッピング; mesh area volume centroid; geometric measures; メッシュ計量
- wf13-corefine-components: 要望: 2つのメッシュをcorefineして成分を調べる
  EN: corefine two tetrahedra then component analysis
  ops: mesh.corefine -> mesh.analysis.connected_components
  keywords: corefinement; corefine meshes; refine along intersection; コリファイン; mesh components; face connected components; メッシュ連結成分
- wf14-catmull-triangulate-measure: 要望: Catmull-Clark細分割から三角形化して測る
  EN: Catmull-Clark to a soup, triangulate, measure
  ops: mesh.subdivide.catmull_clark -> mesh.triangulate.faces -> mesh.analysis.measures
  keywords: catmull clark; subdivision surface; 細分割; triangulate faces; triangulate polygon mesh; quad to triangle; convert polygons to triangles; 面の三角形分割; ポリゴンを三角形化; mesh area volume centroid; geometric measures; メッシュ計量
- wf15-points-alphawrap-remesh-measures: 要望: 点群をalpha wrappingで面にしてリメッシュ・測定する
  EN: alpha wrap a cloud, remesh, measure
  ops: reconstruction.alpha_wrap -> mesh.remesh.isotropic -> mesh.analysis.measures
  keywords: alpha wrap; alpha wrapping; watertight wrap; shrink wrap; アルファラッピング; 包み込み再構成; isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh area volume centroid; geometric measures; メッシュ計量
- wf16-poisson-remesh-inspect: 要望: 法線付き点群からPoisson再構成してリメッシュ・検査する
  EN: Poisson reconstruction from oriented normals, remesh, inspect
  ops: reconstruction.poisson -> mesh.remesh.isotropic -> mesh.inspect.pmp
  keywords: Poisson reconstruction; surface from oriented points; implicit surface reconstruction; ポアソン曲面再構成; 点群から曲面再構成; isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh health inspection; PMP predicates; メッシュ健全性検査
- wf17-outliers-grid-afsr-measures: 要望: 外れ値除去・格子間引きののちadvancing frontで面を作る
  EN: denoise cloud, thin, advancing-front reconstruct, measure
  ops: pointset.remove_outliers -> pointset.simplify.grid -> reconstruction.advancing_front -> mesh.analysis.measures
  keywords: point set outlier removal; remove noisy points; 点群外れ値除去; grid point simplification; voxel point reduction; 点群グリッド簡略化; advancing front reconstruction; interpolating surface reconstruction; Delaunay based reconstruction; アドバンシングフロント再構成; mesh area volume centroid; geometric measures; メッシュ計量
- wf18-jet-alphawrap-components: 要望: jet平滑化した点群をalpha wrappingして成分を調べる
  EN: jet smooth a noisy cloud then alpha wrap
  ops: pointset.smooth.jet -> reconstruction.alpha_wrap -> mesh.analysis.connected_components
  keywords: jet point smoothing; smooth point cloud; 点群ジェット平滑化; alpha wrap; alpha wrapping; watertight wrap; shrink wrap; アルファラッピング; 包み込み再構成; mesh components; face connected components; メッシュ連結成分
- wf19-hull3-loop-measures: 要望: 点群の3D凸包を作り細分割して測る
  EN: 3D hull of a cloud then subdivision and measures
  ops: hull.convex_3 -> mesh.subdivide.loop -> mesh.analysis.measures
  keywords: 3d convex hull; convex hull points; 包絡凸包; 3次元凸包; loop subdivision; triangle subdivision; ループ細分割; mesh area volume centroid; geometric measures; メッシュ計量
- wf20-outlier-normals-orient: 要望: 外れ値を除き法線を推定して向きを揃える
  EN: outlier removal, normals, orientation
  ops: pointset.remove_outliers -> pointset.normals.estimate -> pointset.normals.orient_mst
  keywords: point set outlier removal; remove noisy points; 点群外れ値除去; estimate point normals; pca normals; jet normals; 点群法線推定; orient point normals; mst normal orientation; 点群法線方向付け
- wf21-random-delaunay3: 要望: ランダム点から3D Delaunay三角形分割を作る
  EN: random thinning then 3D Delaunay
  ops: pointset.simplify.random -> triangulation.delaunay_3
  keywords: random point simplification; seeded point sampling; 点群ランダム簡略化; delaunay triangulation 3d; tetrahedralization; 3次元ドロネー三角形分割; 四面体分割
- wf22-wrap-and-thinned-cloud-join: 要望: ラップした面と間引いた点群を合わせて扱う
  EN: alpha-wrapped surface and thinned cloud branches joined by closest-point queries
  ops: reconstruction.alpha_wrap -> pointset.simplify.random -> spatial.aabb.closest_points
  keywords: alpha wrap; alpha wrapping; watertight wrap; shrink wrap; アルファラッピング; 包み込み再構成; random point simplification; seeded point sampling; 点群ランダム簡略化; aabb tree closest point; closest point on mesh; nearest point on surface; AABBツリー最近点; メッシュ最近点
- wf23-remesh-closest-points: 要望: リメッシュ後に最近点を問い合わせる
  EN: remesh then closest points of queries
  ops: mesh.remesh.isotropic -> spatial.aabb.closest_points
  keywords: isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; aabb tree closest point; closest point on mesh; nearest point on surface; AABBツリー最近点; メッシュ最近点
- wf24-grid-maxdistance-join: 要望: 格子間引き点群からメッシュへの最大距離を測る
  EN: thinned cloud against a reference mesh
  ops: pointset.simplify.grid -> mesh.distance.max_to_mesh
  keywords: grid point simplification; voxel point reduction; 点群グリッド簡略化; max distance to triangle mesh; maximum point to mesh distance; point set to surface deviation; 点群からメッシュへの最大距離
- wf25-random-bbox: 要望: ランダム点のバウンディングボックスを求める
  EN: random thinning then bounding box
  ops: pointset.simplify.random -> spatial.bbox_3
  keywords: random point simplification; seeded point sampling; 点群ランダム簡略化; bounding box 3d; bbox 3d; axis aligned bounding box; 3次元バウンディングボックス; 外接直方体
- wf26-remesh-slice: 要望: リメッシュしたメッシュを平面でスライスする
  EN: remesh then planar slice
  ops: mesh.remesh.isotropic -> mesh.slice.compute
  keywords: isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh slicer; plane section; cross section polylines; 断面
- wf27-hull2-polygon-boolean: 要望: 2D凸包の多角形同士でBooleanを行う
  EN: 2D hull of points boolean-joined with a polygon
  ops: hull.convex_2 -> polygon.boolean
  keywords: 2d convex hull; planar convex hull; convex hull of points in the plane; convex_hull_2; 2次元凸包; 平面凸包; polygon boolean; polygon union; polygon difference; 2D set operations; ポリゴンブーリアン
- wf28-hull2-minkowski: 要望: 2D凸包を作りMinkowski和を求める
  EN: 2D hull then Minkowski sum
  ops: hull.convex_2 -> polygon.minkowski_sum
  keywords: 2d convex hull; planar convex hull; convex hull of points in the plane; convex_hull_2; 2次元凸包; 平面凸包; minkowski sum; minkowski sum of polygons; polygon dilation by polygon; configuration space obstacle; ミンコフスキー和; ミンコフスキー和ポリゴン
- wf29-hull2-barycentric: 要望: 2D凸包上で重心座標を求める
  EN: 2D hull then barycentric coordinates of queries
  ops: hull.convex_2 -> shape.barycentric
  keywords: 2d convex hull; planar convex hull; convex hull of points in the plane; convex_hull_2; 2次元凸包; 平面凸包; barycentric coordinates; wachspress coordinates; mean value coordinates; discrete harmonic coordinates; generalized barycentric coordinates; 重心座標
- wf30-surface-generate-remesh-measures: 要望: 曲面メッシュを生成してリメッシュ・測定する
  EN: implicit surface meshing then remesh and measure
  ops: mesh.surface.generate -> mesh.remesh.isotropic -> mesh.analysis.measures
  keywords: surface mesh generation; make_surface_mesh; surface mesher; implicit surface meshing; mesh an implicit surface; isosurface triangulation; sphere mesh generation; ellipsoid mesh generation; torus mesh generation; 曲面メッシュ生成; 陰関数曲面のメッシュ化; 球面メッシュ生成; トーラスメッシュ生成; isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh area volume centroid; geometric measures; メッシュ計量
- wf31-unit-propagation-cm: 要望: cm単位のメッシュをmm指定のパラメータでリメッシュ・軽量化する
  EN: centimetre mesh flows through remesh and simplify with millimetre parameters
  ops: mesh.remesh.isotropic -> mesh.simplify.edge_collapse -> mesh.analysis.measures
  keywords: isotropic remeshing; uniform remesh; remesh to target edge length; 等方リメッシュ; リメッシュ; mesh simplification; edge collapse; surface mesh simplification; メッシュ簡略化; エッジ崩壊; mesh area volume centroid; geometric measures; メッシュ計量
- wf33-hull-clip-measure: 要望: 凸包を作り平面でクリップして測る
  EN: hull of a cloud, clip by a plane, measure
  ops: hull.convex_3 -> mesh.clip.plane -> mesh.analysis.measures
  keywords: 3d convex hull; convex hull points; 包絡凸包; 3次元凸包; clip mesh; plane clipping; cut by plane; クリッピング; mesh area volume centroid; geometric measures; メッシュ計量
- wf34-clip-loop-inspect: 要望: クリップして細分割し検査する
  EN: clip a cube, subdivide, inspect
  ops: mesh.clip.plane -> mesh.subdivide.loop -> mesh.inspect.pmp
  keywords: clip mesh; plane clipping; cut by plane; クリッピング; loop subdivision; triangle subdivision; ループ細分割; mesh health inspection; PMP predicates; メッシュ健全性検査
- wf35-simplify-loop-inspect: 要望: 軽量化してから細分割し検査する
  EN: simplify then subdivide and inspect
  ops: mesh.simplify.edge_collapse -> mesh.subdivide.loop -> mesh.inspect.pmp
  keywords: mesh simplification; edge collapse; surface mesh simplification; メッシュ簡略化; エッジ崩壊; loop subdivision; triangle subdivision; ループ細分割; mesh health inspection; PMP predicates; メッシュ健全性検査
- wf36-cloud-hull-loop-selfintersect: 要望: 点群の凸包を細分割し自己交差を確認する
  EN: hull of a cloud, subdivide, self-intersection check
  ops: hull.convex_3 -> mesh.subdivide.loop -> mesh.analysis.self_intersections
  keywords: 3d convex hull; convex hull points; 包絡凸包; 3次元凸包; loop subdivision; triangle subdivision; ループ細分割; mesh self intersections; intersecting face pairs; 自己交差検査
- wf37-cm-unit-loop-measures: 要望: cm単位メッシュを細分割して測る
  EN: centimetre cube subdivides and measures in centimetres
  ops: mesh.subdivide.loop -> mesh.analysis.measures
  keywords: loop subdivision; triangle subdivision; ループ細分割; mesh area volume centroid; geometric measures; メッシュ計量
- wf38-union-simplify-compare: 要望: 和を作って軽量化し元と比較する
  EN: union then simplify with a Hausdorff comparison joining both
  ops: mesh.boolean.union -> mesh.simplify.edge_collapse -> mesh.distance.hausdorff_approximate
  keywords: mesh.boolean.corefine_union; mesh simplification; edge collapse; surface mesh simplification; メッシュ簡略化; エッジ崩壊; approximate Hausdorff distance; Hausdorff distance of sampled points; mesh deviation sampling; 近似ハウスドルフ距離
- wf39-hull2-arrangement-overlay: 要望: 2D凸包でアレンジメントとオーバーレイを作る
  EN: 2D hull overlaid with a polygon
  ops: hull.convex_2 -> arrangement.overlay
  keywords: 2d convex hull; planar convex hull; convex hull of points in the plane; convex_hull_2; 2次元凸包; 平面凸包; overlay of arrangements; polygon overlay; overlay two polygons; map overlay; face overlay labels; オーバーレイ; ポリゴンオーバーレイ
- wf40-outliers-grid-delaunay3: 要望: 外れ値除去・格子間引きののち3D Delaunayを作る
  EN: outlier removal, grid thinning, Delaunay
  ops: pointset.remove_outliers -> pointset.simplify.grid -> triangulation.delaunay_3
  keywords: point set outlier removal; remove noisy points; 点群外れ値除去; grid point simplification; voxel point reduction; 点群グリッド簡略化; delaunay triangulation 3d; tetrahedralization; 3次元ドロネー三角形分割; 四面体分割
- wf41-noisy-smooth-loop-measures: 要望: ノイズのあるメッシュを平滑化して細分割・測定する
  EN: smooth a noisy sphere then subdivide and measure
  ops: mesh.smooth.shape -> mesh.subdivide.loop -> mesh.analysis.measures
  keywords: smooth shape; mesh smoothing; curvature flow smoothing; fair surface; 形状スムージング; メッシュ平滑化; loop subdivision; triangle subdivision; ループ細分割; mesh area volume centroid; geometric measures; メッシュ計量
- wf42-rules-soup-loop-auto-orient-inspect: 要望: プランナー規則で前処理（向き）と後処理（検査）を自動挿入する
  EN: a flipped soup feeds subdivision directly; the planner inserts orient before and inspection after
  ops: mesh.subdivide.loop
  keywords: loop subdivision; triangle subdivision; ループ細分割
- wf43-fallback-plan-time-block: 要望: 単位不一致で計画段階でブロックされたら宣言済みの代替案で実行する
  EN: a union of millimetre and centimetre operands is blocked at planning; the declared same-unit union then subdivision is served
  ops: mesh.boolean.union
  keywords: mesh.boolean.corefine_union
- wf44-fallback-runtime-failure: 要望: 実行時に失敗したら宣言済みの代替案に切り替える
  EN: Poisson from estimated normals yields nothing; the alpha-wrap alternative is served
  ops: pointset.normals.estimate -> pointset.normals.orient_mst -> reconstruction.poisson
  keywords: estimate point normals; pca normals; jet normals; 点群法線推定; orient point normals; mst normal orientation; 点群法線方向付け; Poisson reconstruction; surface from oriented points; implicit surface reconstruction; ポアソン曲面再構成; 点群から曲面再構成
- wf45-fallback-validator-rejection: 要望: 検証器に却下されたら宣言済みの代替案に切り替える
  EN: jet smoothing is rejected by its validator; direct alpha wrapping is served
  ops: pointset.smooth.jet -> reconstruction.alpha_wrap
  keywords: jet point smoothing; smooth point cloud; 点群ジェット平滑化; alpha wrap; alpha wrapping; watertight wrap; shrink wrap; アルファラッピング; 包み込み再構成

## 期待される拒否・失敗（fail-closedの実演）
- neg01-invalid-index-import: 頂点番号が範囲外のメッシュは取込み時に拒否される -> {"stage": "import", "state": "refused"}
- neg02-nonmanifold-simplify: 非多様体メッシュの軽量化は実行時に失敗する -> {"code": "MALFORMED_OFF", "stage": "execute", "state": "failed"}
- neg03-unit-mismatch-boolean: mmとcmの入力はBooleanで組み合わせられない -> {"code": "unit_mismatch", "stage": "plan", "state": "refused"}
- neg04-type-mismatch-dag-edge: 型が合わないDAG辺は計画段階で拒否される -> {"code": "dag_type", "stage": "plan", "state": "refused"}
- neg05-cyclic-dag: 循環するDAGは拒否される -> {"code": "dag_type", "stage": "plan", "state": "refused"}
- neg06-validator-rejects-remesh: 満たせない偏差上限のリメッシュは検証器が却下する -> {"code": "HAUSDORFF_WITHIN_MAX_DEVIATION_FAILED", "stage": "execute", "state": "rejected"}
- neg06b-validator-budget-exceeded: 検証器の計算予算を超えると失敗として閉じる -> {"code": "VALIDATION_BUDGET_EXCEEDED", "stage": "execute", "state": "failed"}
- neg07-validator-rejects-jet-smoothing: 粗さが減らないjet平滑化は検証器が却下する -> {"code": "ROUGHNESS_NOT_REDUCED", "stage": "execute", "state": "rejected"}
- neg08-empty-reconstruction-fails-closed: 空の再構成結果は失敗として閉じる -> {"code": "EMPTY_RECONSTRUCTION", "stage": "execute", "state": "failed"}
- neg09-face-limit-refused-at-plan: 面数上限超過は計画段階で拒否される -> {"code": "unmet_precondition", "stage": "plan", "state": "refused"}
- neg10-face-limit-refused-at-runtime: 面数上限超過は実行時にも拒否される -> {"code": "unmet_precondition", "stage": "execute", "state": "failed"}
- neg10b-torus-simplify-limit: トーラスの軽量化も面数上限で拒否される -> {"code": "unmet_precondition", "stage": "execute", "state": "failed"}
- neg11-wall-time-limit-out-of-range: 範囲外の壁時間指定は拒否される -> {"code": "execution_limits", "stage": "execute_limits", "state": "refused"}
- neg12-memory-limit-out-of-range: 範囲外のメモリ指定は拒否される -> {"code": "execution_limits", "stage": "execute_limits", "state": "refused"}
- neg13-missing-required-parameter: 必須パラメータの欠落は計画段階で拒否される -> {"code": "parameters_required", "stage": "plan", "state": "refused"}
- neg14-unhealthy-boolean-operand: 閉じていないメッシュのBooleanは失敗として閉じる -> {"code": "MESH_NOT_CLOSED", "stage": "execute", "state": "failed"}
- neg15-unknown-operation: 未登録の操作は拒否される（その場でC++は生成しない） -> {"stage": "plan", "state": "refused"}
- neg16-spoofed-validator-binding: 偽装した検証器の束縛は拒否される -> {"code": "validator_binding", "stage": "plan", "state": "refused"}
- neg17-license-policy-gate: ライセンス方針に反する操作は拒否される -> {"stage": "plan", "state": "refused"}
- neg18-missing-input-slot: 入力スロットの欠落は拒否される -> {"code": "input_binding", "stage": "plan", "state": "refused"}
- neg19-ambiguous-component-tie: 最大成分が同点だと曖昧として失敗する -> {"code": "AMBIGUOUS_COMPONENT_TIE", "stage": "execute", "state": "failed"}
- neg20-fallback-chain-exhausted: 代替案をすべて試しても失敗なら失敗として閉じる -> {"code": "EMPTY_RECONSTRUCTION", "stage": "execute", "state": "failed"}
- neg21-fallback-all-blocked: 代替案がすべて計画段階でブロックされると拒否される -> {"code": "unmet_precondition", "stage": "plan", "state": "refused"}
