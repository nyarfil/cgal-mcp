# 主要能力の実装候補台帳

原本7.1〜7.15の全80要求を
[`catalog/major_capability_inventory.json`](../../catalog/major_capability_inventory.json)へ
対応付けました。source・版固定HTML・公式example・依存根拠から、
今後のadapter/validator/fixture実装の候補を調べるための資料です。

この台帳は実装状態を評価しません。実装・検証状態の正本はOperation registryと
実計算を再試験する受入報告です。source内で名前が見つかった事実と、宣言の
確認、実装、検証、原本要求全体の達成は別々に扱います。

- 原本の固定受入母数は80要求です。
- 203件のsymbolは暫定・非網羅の候補です。全203件を満たしても、
  原本の全主要能力を満たした証拠にはなりません。
- symbol出現は`CANDIDATE_SYMBOL_OCCURRENCE`、宣言は
  `DECLARATION_UNVERIFIED`です。呼出しや文字列の出現も含み得ます。
- OpenGRやEigenは、採用するAPIで必須か、別の数値型を選べるかを区別します。
- Approximate Convex Decompositionはsource package名を保持しつつ、
  `Convex_decomposition_3`の公式HTML・exampleへ関連付けています。
- FastEnvelopeはPolyhedral Envelopeの主要求と分離し、外部取得・版固定が
  必要な補助policyとして記録します。

再生成には、チェックサム検証済みの公式source/docsが必要です。

```sh
python scripts/build_major_inventory.py
```

CIは台帳を公式配布物から再生成してバイト一致を検査します。
原本要求のID・説明・必須指定と原本hashを正規化したprojectionに結び付け、
改行形式やbuildごとの実行証拠の違いを実装候補台帳へ混入させません。
原本MD自体は変更しません。台帳の独立レビューで見つかった、宣言判定、
候補件数の過大解釈、依存条件、docsの関連付けを修正しました。

## 再試験への結合状況

[受入判定](CAPABILITY_ACCEPTANCE_JA.md)で実計算に結び付いた要求と、未結合の理由です。
分母は各分野の原本要求数です。

| 分野 | 結合/全体 | 結合済み要求 |
|---|---|---|
| 7.1 カーネル | 5/5 | 7.1.01 Simple_cartesian・Cartesian・EPICK・EPECK（同一の準退化入力で浮動小数点kernelは誤判定、厳密述語kernelは正答）、.02 20種のprimitive、.03 述語・構成、.04 intersection・do_intersect、.05 squared_distance・距離比較。validatorはCGALを使わないGMP有理数の独立再計算 |
| 7.2 空間問合せ | 5/5 | 7.2.01 AABB、.02 Kd木、.03 k近傍、.04 do_intersect・any/all_intersected_primitives（AABB_tree、ray対三角形メッシュ、独立厳密validator）、.05 bbox |
| 7.3 解析 | 7/8 | 7.3.01 検査・自己交差、.02 connected_components・connected_component・keep_largest_connected_components、.03 法線、.04 計測、.05 `detect_sharp_edges`・`sharp_edges_segmentation`（厳密な有理数の面法線で再計算）、.07 `do_intersect`・`intersection_polylines`（2メッシュ間。全三角形対をGMP有理数で独立判定し、交線の各点・各線分が両メッシュ上にあり厳密な交線を覆うことを検証。共面重なりと開メッシュの内側判定は拒否）と自己交差、.08 locate・locate_with_AABB_tree |
| 7.4 修復 | 6/6 | 7.4.01 向き、.02 境界縫合、.03 退化除去、.04 `triangulate_hole`・`triangulate_refine_and_fair_hole`（球ドームの12辺の穴を平面三角形分割と密度1.41・C1／2.5・C2のフェアリングで埋め、位相・原面保存・新面の厳密な非退化をvalidatorが検証。フェアリングの浮動小数点解そのものは独立再導出せずCGALの再実行）、.05 polygon soup、.06 非多様体前処理 |
| 7.5 Boolean | 5/5 | 7.5.01 `corefine`・`autorefine`（単独操作、厳密な面分割と自己交差の残存なしを検証）、7.5.02 union/intersection/difference、.03 `clip`（体積・曲面、厳密な重み付き面積の分割で検証）、.04 `split`・`corefine`（同、2面側の分離も検証）、.05 Polygon_mesh_slicer |
| 7.6 再メッシュ | 5/5 | 7.6.01 面の三角形分割、.02 refine、.03 等方remesh・長辺分割、.04 平滑化・最適化、.05 適応remesh |
| 7.7 軽量化 | 6/6 | 7.7.01〜06 |
| 7.8 再構成 | 2/6 | 7.8.04 `Surface_mesh_shortest_path`（三角形64面以内、頂点または面の重心座標の始点8・終点32まで。面列の展開と可視窓、頂点上のDijkstraをlong doubleで独立再計算し、許容は対角線の1e-9倍と明記）、7.8.06 CatmullClark_subdivision・Loop_subdivision（独立マスク再計算validator） |
| 7.9 点群 | 5/6 | 7.9.01 法線推定・MST向き付け、.02 `remove_outliers`（既存の`pointset.remove_outliers`に独立validatorを追加）、.04 grid/random/hierarchy簡略化、.05 登録（`register_point_sets`・`compute_registration_transformation`、OpenGR v2023.11のSuper4PCS、任意依存。変換は厳密な有理数で直交性・各点の像・RMS・inlier率を独立validatorが検証し、乱数seedはOpenGR既定、全parameterを固定。壁時計上限に達した実行は拒否）、.06 再構成前処理（`compute_average_spacing`・`remove_outliers`）。validatorは全点対の総当たり（long double、相対1e-9の許容、境界近傍は曖昧として拒否） |
| 7.11 三角形分割 | 4/5 | 7.11.01 Delaunay 2D/3D、.02 制約付き、.03 `Regular_triangulation_2/3`（重み付き点の持ち上げをGMP有理数で検証、重みは長さの二乗）、.05 `Voronoi_diagram_2`（外心・双対辺をGMP有理数で再計算） |
| 7.12 多角形 | 7/7 | 7.12.01 Polygon_2/with_holesの性質・内外判定、.05 `create_interior_straight_skeleton_2`・`create_exterior_straight_skeleton_2`（輪郭の完全一致・辺ごとに1面・節点が領域内部・節点時刻が接する面辺の直線への距離に等しく境界から離れていること・面積の厳密和をvalidatorが検証、距離は対角線の1e-9倍の許容を明記。外側は穴なし単純多角形のみ）、.06 `create_interior_skeleton_and_offset_polygons_2`・`create_exterior_skeleton_and_offset_polygons_2`（各辺が元の辺に平行で距離d・凸多角形は半平面交差と、矩形は厳密な(w∓2d)(h∓2d)と照合。軸平行な非凸多角形（L字・穴あき正方形）は正方形[-d,d]²による厳密な収縮・膨張とオフセット格子上の境界片・リング数・厳密面積で照合。軸平行でない非凸多角形の空でない結果は未証明のため拒否し、保証範囲は凸多角形と軸平行多角形に限る）、.02 `Arrangement_2`・`insert`・`zone`、.03 `overlay`（面ラベル加算）、.07 `minkowski_sum_2`・`minkowski_sum_by_reduced_convolution_2`（畳み込み片の厳密判定）、.04 `Polygon_set_2`のjoin・intersection・difference（EPECK、境界鎖をGMP有理数で独立再計算） |
| 7.13 凸包等 | 5/5 | 7.13.01 2D/3D凸包、.02 `Alpha_shape_2`・`Alpha_shape_3`・`Fixed_alpha_shape_3`（regularized。Delaunay単体の空球探索と外接半径をGMP有理数で再計算しalpha以下の内部単体と正則な境界辺／面を厳密比較。空の円・球に追加点が乗る入力は拒否）、.03 `alpha_wrap_3`（既存の`reconstruction.alpha_wrap`を7.13の再試験ケースで再結合）、.04 `Min_circle_2`・`Min_sphere_of_spheres_d`（最小球をGMP有理数の支持集合列挙で検証、半径は平方根のため許容付き）、.05 mean_value・wachspress・discrete_harmonic coordinates（2D、境界点は拒否） |
| 7.14 メッシュ生成 | 4/4 | 7.14.01 Mesh_2（`refine_Delaunay_mesh_2`）、7.14.02 Surface_mesher（`make_surface_mesh`、球・楕円体・トーラス）、7.14.03 Mesh_3（`make_mesh_3`、同3種のimplicit domainと、閉じた三角形メッシュの多面体domain）、7.14.04 `Mesh_criteria_3`の型付きcriteria（列挙boxのsizing field、facet_topology、多面体の1D特徴辺edge_size）。画像domainと複数パッチtopologyは未実装 |
| 7.10 曲面再構成 | 3/3 | 7.10.03 `alpha_wrap_3`（点群oracle、alpha/offsetの型付き長さ、入力の厳密な内包・offset帯・alpha+offset上限を独立検証）。validatorはCGALを使わない独立再計算（GMP有理数の点-三角形距離・符号付き体積・軸線交差の偶奇）。7.10.01 `reconstruction.poisson`（`Poisson_reconstruction_function`＋`Poisson_mesh_domain_3`＋表面のみの`make_mesh_3`、閉曲面）と`reconstruction.poisson_delaunay`（`poisson_surface_reconstruction_delaunay`）。後者はCGAL 6.2.1が`manifold_with_boundary()`を強制するため**境界付き多様体**で、球33本・トーラス86本の境界辺を開示し、閉曲面とは主張しない。validator（`reconstruction.validate.poisson_boundary`）は辺・頂点の多様体性、向きの一貫性（閉成分は厳密な符号付き体積で外向き）、点群の`min_coverage`以上が`max_deviation`内に被覆されること、被覆点での法線一致、三角形ごとの証明付き上界、厳密な外接円半径上限を検査する。向きは連結成分ごとの法線投票で決める。7.10.02 `advancing_front`・`scale_space`・`polygonal_surface`（PolyFit、SCIP 10.0.3、任意依存）・`kinetic_surface`。箱（376点、体積10×8×6=480、四角形6面・8頂点）とL字柱（328点、体積336）でPolyFit・Kineticとも手計算値に一致する。L字柱ではPolyFitが14面16頂点、Kineticは8面で共線の余分な頂点を持つ（開示）。validatorは生のbinary64上の厳密有理数で面の平面性（Newell法線、型付き許容）・単純多角形（厳密な耳切り）・閉じた辺多様体・頂点リンク・外向き・点から面までの距離・法線一致を検査する |
| 7.15 最適化・数値幾何 | 4/4 | 7.15.01 QP_solver（`Quadratic_program<Gmpq>`、`solve_linear_program`・`solve_quadratic_program`、最適・実行不能・非有界と証明書）、.02 Interpolation（`natural_neighbor_coordinates_2`＋`linear_interpolation`はEPECKで線形場を厳密再現、`sibson_c1_interpolation`は勾配付きで球面二次関数を再現）、.03 Surface_mesh_approximation（`approximate_triangle_mesh`、L21のVSA、二乗誤差はmm2）、.04 Matrix_search（`sorted_matrix_search`による1次元区間p-center）。validatorはCGALを使わない独立再計算（GMP有理数の証明書補題・Voronoi面積・全候補走査、VSAはlong double） |

未結合要求の不足（7.1・7.6は5/5、7.15は4/4結合済みで不足なし）:

- 7.3.06: 7シンボルのうち6つ（`sample_triangle_mesh`・`max_distance_to_triangle_mesh`・`approximate_Hausdorff_distance`・`approximate_symmetric_Hausdorff_distance`・`approximate_max_distance_to_point_set`・`bounded_error_Hausdorff_distance`）は独立validator付きのOperationになったが、`bounded_error_symmetric_Hausdorff_distance`は軽量化validatorの`mesh.distance.symmetric_hausdorff`（validation.requiredがfalse、出力にソースハッシュなし）でしか呼べず、必須validator連鎖を持てないため再試験できない。同じCGAL関数に2つ目のOperationを作ることは1関数1Operationの規則に反する（要Opus判断: 当該Operationを必須validator連鎖付きの解析Operationへ昇格するか）。
- 7.9.03: bilateral等のsmoothingがない。
- 7.8.01〜03、05: 区分化(SDF)・凸分解・骨格・パラメータ化のOperationがない。
- 7.11.04: periodic・on-sphere がない。

注記 (7.3): 7.3.03 法線は、軸整列立方体(外向き/内向き巻きの2ケース)の各面法線・各頂点法線を
手計算の定数と照合して束縛している。必須validatorは同一workerコードを再実行する整合性チェックであり、
独立オラクルではない。7.3.01の `triangulated` はworker内の面次数フラグ由来で、CGAL::is_triangle_mesh
直接ではない(worker変更は全evidence再生成を要するため未対応、TODO)。
