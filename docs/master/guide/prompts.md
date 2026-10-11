# Prompts

## start_here
arguments: [{"description": "What the user wants, in their own words", "name": "request", "required": true}]

### EN
The user asks: <<request>>
Work through this with the CGAL Master MCP.
1. cgal_get_guide(topic="start").
2. Check topic="recipes" for a matching verified recipe; if one fits, read recipe:<id> and follow it with the user's own files.
3. Otherwise cgal_capabilities_search(query=<request>), read the card with cgal_get_guide(topic="op:<id>") for the best candidate, confirm units with the user if unknown.
4. Import, cgal_plan, cgal_execute, poll cgal_job_status. Report only numbers from job outputs and validation reports.
5. If the server refuses, relay the code and the remedy from topic="errors"; for ambiguous_route ask the user which option they mean.

### JA
ユーザーの要望: <<request>>
CGAL Master MCPで進める。
1. cgal_get_guide(topic="start", lang="ja")。
2. topic="recipes"で合う検証済みレシピを探し、あればrecipe:<id>を読んでユーザー自身のファイルで従う。
3. なければcgal_capabilities_search(query=<要望>)→最有力候補をcgal_get_guide(topic="op:<id>")で読む。単位が不明ならユーザーに確認。
4. 取込み→cgal_plan→cgal_execute→cgal_job_statusで確認。数値はjob出力と検証レポートにあるものだけ報告。
5. 拒否されたらコードとtopic="errors"の対処を伝える。ambiguous_routeはどの選択肢かユーザーに尋ねる。

## repair_and_simplify_mesh
arguments: [{"description": "Path of the mesh file the server can read", "name": "mesh_path", "required": true}, {"description": "mm, cm or m", "name": "unit", "required": true}, {"description": "Fraction of faces to keep, for example 0.5", "name": "target_ratio", "required": false}]

### EN
Repair the mesh <<mesh_path>> (unit <<unit>>) and then simplify it to about <<target_ratio>> of its faces.
1. Import it (artifact_type PolygonSoup3 if it is a soup, otherwise TriangleSurfaceMesh) with the stated unit.
2. Inspect first (mesh.inspect.pmp, mesh.repair.polygon_soup, mesh.repair.orient, mesh.repair.stitch_borders, mesh.analysis.boundary_cycles, mesh.repair.fill_holes, mesh.repair.remove_degenerate, mesh.simplify.edge_collapse, mesh.distance.symmetric_hausdorff: start with mesh.inspect.pmp) to learn what is wrong: open borders, flipped faces, degenerate faces, non-manifold parts.
3. Repair only what the inspection shows. Holes are never filled blindly: list them first with mesh.analysis.boundary_cycles (hole_id, edge count, perimeter, area estimate, location), show that list to the user, ask which holes to close, and only then run mesh.repair.fill_holes with hole_ids (list first, ask the user, then fill by ids); unselected holes stay open. Verified recipes: wf05-dirtysoup-clean-orient-measure, wf02-fillholes-loop-measures, wf35-simplify-loop-inspect, wf06-remesh-simplify-hausdorff-join; read them with cgal_get_guide(topic="recipe:<id>").
4. Simplify with mesh.simplify.edge_collapse: its card (topic "op:mesh.simplify.edge_collapse") lists the required stop rule, policy, max_symmetric_deviation and hausdorff_error_bound. Non-manifold input is refused; meshes above the card's face bound are refused.
5. Compare the result with the original using the Hausdorff operations (at most 400 faces) or rely on the mandatory simplification validator; report only validated numbers.

### JA
メッシュ <<mesh_path>>（単位 <<unit>>）を修復し、面数を約 <<target_ratio>> に軽量化する。
1. 指定単位で取り込む（ポリゴンスープならartifact_type PolygonSoup3、そうでなければTriangleSurfaceMesh）。
2. まず検査（mesh.inspect.pmp, mesh.repair.polygon_soup, mesh.repair.orient, mesh.repair.stitch_borders, mesh.analysis.boundary_cycles, mesh.repair.fill_holes, mesh.repair.remove_degenerate, mesh.simplify.edge_collapse, mesh.distance.symmetric_hausdorff: mesh.inspect.pmpから）で問題（開境界・反転・退化面・非多様体）を把握する。
3. 検査で分かった問題だけを直す。穴は勝手に全部埋めない: まずmesh.analysis.boundary_cycles（hole_id・辺数・周長・面積目安・位置）で一覧し、一覧をユーザーに見せてどの穴を埋めるか確認し、そのあとでmesh.repair.fill_holesにhole_idsを渡して埋める（先に一覧、次に確認、最後にIDで指定）。選ばれなかった穴は開いたまま残る。検証済みレシピ: wf05-dirtysoup-clean-orient-measure, wf02-fillholes-loop-measures, wf35-simplify-loop-inspect, wf06-remesh-simplify-hausdorff-join。cgal_get_guide(topic="recipe:<id>")で読む。
4. mesh.simplify.edge_collapseで軽量化。カード（topic "op:mesh.simplify.edge_collapse"）に停止条件・policy・max_symmetric_deviation・hausdorff_error_boundが載っている。非多様体や面数上限超過は拒否される。
5. 元との比較はHausdorff系（400面以下）または必須の軽量化検証器に任せ、検証済みの数値だけ報告する。

## reconstruct_surface_from_points
arguments: [{"description": "Path of the point file (xyz or ply with normals)", "name": "points_path", "required": true}, {"description": "mm, cm or m", "name": "unit", "required": true}]

### EN
Reconstruct a surface from the points in <<points_path>> (unit <<unit>>).
1. Import as PointSet3 (xyz) or PointSet3Normals (ply with normals).
2. Clean first when noisy: pointset.remove_outliers, pointset.normals.estimate, pointset.normals.orient_mst, reconstruction.alpha_wrap, reconstruction.poisson, reconstruction.advancing_front (outlier removal, normal estimation and orientation).
3. Pick a method by the data: alpha wrapping for a watertight envelope, Poisson for oriented normals, advancing front for clean dense samples. Recipes: wf15-points-alphawrap-remesh-measures, wf16-poisson-remesh-inspect, wf17-outliers-grid-afsr-measures, wf20-outlier-normals-orient.
4. Read each chosen card (topic "op:<id>") for parameters; lengths need units.
5. An empty or unverifiable reconstruction is a failure, not a result: report the error code instead of a surface.

### JA
<<points_path>>（単位 <<unit>>）の点群から曲面を再構成する。
1. PointSet3（xyz）またはPointSet3Normals（法線付きply）として取り込む。
2. ノイズがあれば先に整える: pointset.remove_outliers, pointset.normals.estimate, pointset.normals.orient_mst, reconstruction.alpha_wrap, reconstruction.poisson, reconstruction.advancing_front（外れ値除去・法線推定と向き付け）。
3. データで手法を選ぶ: 水密な外皮ならalpha wrapping、向きの揃った法線があればPoisson、きれいで密な点ならadvancing front。レシピ: wf15-points-alphawrap-remesh-measures, wf16-poisson-remesh-inspect, wf17-outliers-grid-afsr-measures, wf20-outlier-normals-orient。
4. 選んだ操作のカード（topic "op:<id>"）でパラメータを確認。長さには単位が要る。
5. 空や検証できない再構成は結果でなく失敗。曲面ではなくエラーコードを報告する。

## validate_geometry
arguments: [{"description": "Path of the geometry file", "name": "path", "required": true}, {"description": "mm, cm or m", "name": "unit", "required": true}, {"description": "For example TriangleSurfaceMesh", "name": "artifact_type", "required": false}]

### EN
Check whether <<path>> (unit <<unit>>, type <<artifact_type>>) is sound geometry.
1. Import it exactly as given; a parse error (off_*/obj_*/ply_*/stl_*/xyz_*) already answers the question: relay it.
2. Run the analysis operations (mesh.inspect.pmp, mesh.analysis.self_intersections, mesh.analysis.connected_components, mesh.analysis.measures, mesh.analysis.normals) as separate cgal_plan calls; they only read.
3. Summarize: closed or open, manifold or not, self-intersections, number of connected components, area and volume, with units from the outputs.
4. Suggest repair operations only if a problem was found (topic "families", repair). Do not modify the input: every operation creates new artifacts. Recipes with checks: wf04-degenerate-remove-selfintersect, wf01-soup-orient-loop-inspect.

### JA
<<path>>（単位 <<unit>>、型 <<artifact_type>>）が健全な幾何かを調べる。
1. そのまま取り込む。解析エラー（off_*/obj_*/ply_*/stl_*/xyz_*）が出ればそれが答えなので伝える。
2. 解析操作（mesh.inspect.pmp, mesh.analysis.self_intersections, mesh.analysis.connected_components, mesh.analysis.measures, mesh.analysis.normals）を個別のcgal_planで実行する（読み取りのみ）。
3. 要約: 閉/開、多様体か、自己交差、連結成分数、面積・体積（単位は出力のもの）。
4. 問題があったときだけ修復操作を提案（topic "families"の修復）。入力は変更しない（全操作が新しいartifactを作る）。検査を含むレシピ: wf04-degenerate-remove-selfintersect, wf01-soup-orient-loop-inspect。

## compare_meshes
arguments: [{"description": "Reference mesh file", "name": "reference_path", "required": true}, {"description": "Candidate mesh file", "name": "candidate_path", "required": true}, {"description": "mm, cm or m (both files)", "name": "unit", "required": true}]

### EN
Compare <<candidate_path>> against <<reference_path>> (both in <<unit>>).
1. Import both as TriangleSurfaceMesh with the same unit; different units fail with unit_mismatch.
2. Use the distance operations (mesh.distance.hausdorff_bounded, mesh.distance.symmetric_hausdorff, mesh.distance.hausdorff_approximate, mesh.analysis.measures). The Hausdorff operations and their validators accept at most 400 faces each: simplify first if larger.
3. mesh.distance.symmetric_hausdorff needs tolerance and error_bound (lengths with units) and answers pass, fail or indeterminate: report indeterminate honestly.
4. Add mesh.analysis.measures to each mesh for area/volume context. Recipes: wf38-union-simplify-compare, wf06-remesh-simplify-hausdorff-join.

### JA
<<candidate_path>>を<<reference_path>>と比較する（どちらも単位 <<unit>>）。
1. 同じ単位のTriangleSurfaceMeshとして2つ取り込む。単位が違うとunit_mismatch。
2. 距離系操作（mesh.distance.hausdorff_bounded, mesh.distance.symmetric_hausdorff, mesh.distance.hausdorff_approximate, mesh.analysis.measures）を使う。Hausdorff系と検証器はどちらも400面以下: 大きければ先に軽量化。
3. mesh.distance.symmetric_hausdorffはtoleranceとerror_bound（単位付き長さ）が必要で、pass/fail/indeterminateを返す。indeterminateはそのまま正直に報告する。
4. 面積・体積の文脈としてmesh.analysis.measuresも各メッシュに。レシピ: wf38-union-simplify-compare, wf06-remesh-simplify-hausdorff-join。

## 2d_boolean_offset
arguments: [{"description": "Path of the 2D polygon JSON file", "name": "polygon_path", "required": true}, {"description": "mm, cm or m", "name": "unit", "required": true}, {"description": "Offset distance as a number in the stated unit", "name": "offset", "required": false}]

### EN
Do 2D polygon boolean and offset work on <<polygon_path>> (unit <<unit>>, offset <<offset>>).
1. Import as Polygon2 or PolygonWithHoles2 (json) with the unit.
2. Operations: polygon.boolean, polygon.offset.interior, polygon.offset.exterior, polygon.minkowski_sum, polygon.analysis.properties. Read each card (topic "op:<id>"): offsets take the distance as a typed length {"value", "unit"}; the guaranteed shapes are stated on the card (for example convex or axis-aligned polygons for offsets; non-covered inputs are refused, not approximated).
3. For two polygons use polygon.boolean (join, intersection or difference as its card states) on the same unit.
4. Recipes: wf27-hull2-polygon-boolean, wf28-hull2-minkowski. Report areas and vertex counts only from outputs and validator reports.

### JA
<<polygon_path>>（単位 <<unit>>、オフセット <<offset>>）に対し2D多角形のBooleanとオフセットを行う。
1. Polygon2またはPolygonWithHoles2（json）として単位つきで取り込む。
2. 操作: polygon.boolean, polygon.offset.interior, polygon.offset.exterior, polygon.minkowski_sum, polygon.analysis.properties。各カード（topic "op:<id>"）を読む。オフセットの距離は型付き長さ{"value", "unit"}。保証される形状はカードに明記（例: オフセットは凸や軸平行の多角形。対象外は近似せず拒否）。
3. 2つの多角形はpolygon.boolean（カードの通りjoin/intersection/difference）。同じ単位で。
4. レシピ: wf27-hull2-polygon-boolean, wf28-hull2-minkowski。面積や頂点数は出力と検証レポートからだけ報告する。

## choose_operation
arguments: [{"description": "The user's goal in plain words", "name": "goal", "required": true}]

### EN
Choose the right CGAL Master operation for: <<goal>>
1. cgal_capabilities_search(query=<goal>, limit=8). If query_analysis.abstained is true, or unsupported_cgal_packages is present, tell the user it is not supported and why (topic "limits-and-status").
2. Compare the top candidates: why, input_types versus the user's data, output_types, status. Read the cards (topic "op:<id>") of the best two.
3. If several fit equally, ask the user one short question listing the options; do not pick silently.
4. Confirm units and the input file type, then plan with operation_id.

### JA
次の目的に合うCGAL Master操作を選ぶ: <<goal>>
1. cgal_capabilities_search(query=<目的>, limit=8)。query_analysis.abstainedがtrue、またはunsupported_cgal_packagesがあれば、未対応であることと理由（topic "limits-and-status"）を伝える。
2. 上位候補を比較: why、input_typesとユーザーのデータ、output_types、status。上位2つのカード（topic "op:<id>"）を読む。
3. 同等に当てはまる複数があれば、選択肢を挙げて短く1つ質問する。黙って選ばない。
4. 単位と入力ファイルの型を確認し、operation_idでplanする。
