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
| 7.3 解析 | 5/8 | 7.3.01 検査・自己交差、.02 connected_components・connected_component・keep_largest_connected_components、.03 法線、.04 計測、.08 locate・locate_with_AABB_tree |
| 7.4 修復 | 5/6 | 7.4.01 向き、.02 境界縫合、.03 退化除去、.05 polygon soup、.06 非多様体前処理 |
| 7.5 Boolean | 2/5 | 7.5.02 union/intersection/difference、.05 Polygon_mesh_slicer |
| 7.6 再メッシュ | 5/5 | 7.6.01 面の三角形分割、.02 refine、.03 等方remesh・長辺分割、.04 平滑化・最適化、.05 適応remesh |
| 7.7 軽量化 | 6/6 | 7.7.01〜06 |
| 7.8 再構成 | 1/6 | 7.8.06 CatmullClark_subdivision・Loop_subdivision（独立マスク再計算validator） |
| 7.9 点群 | 2/6 | 7.9.01 法線推定・MST向き付け、7.9.04 grid/random/hierarchy簡略化 |
| 7.11 三角形分割 | 2/5 | 7.11.01 Delaunay 2D/3D、.02 制約付き |
| 7.12 多角形 | 1/7 | 7.12.01 Polygon_2/with_holesの性質・内外判定 |
| 7.13 凸包等 | 2/5 | 7.13.01 2D/3D凸包、.05 mean_value・wachspress・discrete_harmonic coordinates（2D、境界点は拒否） |
| 7.14 メッシュ生成 | 4/4 | 7.14.01 Mesh_2（`refine_Delaunay_mesh_2`）、7.14.02 Surface_mesher（`make_surface_mesh`、球・楕円体・トーラス）、7.14.03 Mesh_3（`make_mesh_3`、同3種のimplicit domainと、閉じた三角形メッシュの多面体domain）、7.14.04 `Mesh_criteria_3`の型付きcriteria（列挙boxのsizing field、facet_topology、多面体の1D特徴辺edge_size）。画像domainと複数パッチtopologyは未実装 |
| 7.10 曲面再構成 | 1/3 | 7.10.03 `alpha_wrap_3`（点群oracle、alpha/offsetの型付き長さ、入力の厳密な内包・offset帯・alpha+offset上限を独立検証）。validatorはCGALを使わない独立再計算（GMP有理数の点-三角形距離・符号付き体積・軸線交差の偶奇）。7.10.01 Poisson（`Poisson_reconstruction_function`＋`Poisson_mesh_domain_3`＋表面のみの`make_mesh_3`）は実装・独立検証済みだが未結合。7.10.02はAdvancing_frontとScale_spaceをOperation化・検証済みだが、台帳のPolygonal_surface_reconstruction（SCIP/GLPKなどのMIP solverが未導入）とKinetic_surface_reconstruction（Operationなし）が未実装のため未結合 |
| 7.15 最適化・数値幾何 | 4/4 | 7.15.01 QP_solver（`Quadratic_program<Gmpq>`、`solve_linear_program`・`solve_quadratic_program`、最適・実行不能・非有界と証明書）、.02 Interpolation（`natural_neighbor_coordinates_2`＋`linear_interpolation`はEPECKで線形場を厳密再現、`sibson_c1_interpolation`は勾配付きで球面二次関数を再現）、.03 Surface_mesh_approximation（`approximate_triangle_mesh`、L21のVSA、二乗誤差はmm2）、.04 Matrix_search（`sorted_matrix_search`による1次元区間p-center）。validatorはCGALを使わない独立再計算（GMP有理数の証明書補題・Voronoi面積・全候補走査、VSAはlong double） |

未結合要求の不足（7.1・7.6は5/5、7.15は4/4結合済みで不足なし）:

- 7.10.01: 台帳のシンボル`poisson_surface_reconstruction_delaunay`を再試験していない。CGAL 6.2.1の`poisson_surface_reconstruction.h`は呼び出し側のtagの後に`manifold_with_boundary()`を付けるため、閉曲面の球・トーラスで24〜214本の境界辺が残り、閉曲面validatorを通せない。このシンボルを再試験するまで未結合（`reconstruction.poisson`自体は実装・検証済み）。
- 7.10.02: Polygonal_surface_reconstruction（MIP solver未導入）とKinetic_surface_reconstructionがない。Advancing_frontとScale_spaceは実装・検証済みだが、台帳の全familyを再試験するまで未結合。
- 7.3.05: sharp edge / segmentation がない。
- 7.3.06: 距離はvalidator内部の上界付き対称Hausdorffのみで、他の距離関数がない。
- 7.3.07: 2メッシュ間の交差判定を公開していない。
- 7.4.04: `triangulate_refine_and_fair_hole`相当の穴埋めがない。
- 7.5.01: corefine / autorefine はBoolean内部のみで単独公開していない。
- 7.5.03〜04: clip、split がない。
- 7.9.02、7.9.06: `compute_average_spacing`等の解析を公開していない。
- 7.9.03: bilateral等のsmoothingがない。
- 7.9.05: registration がない。
- 7.8.01〜05: 区分化・凸分解・骨格・最短経路・パラメータ化のOperationがない。
- 7.11.03〜05: regular、periodic・on-sphere、Voronoiがない。
- 7.12.02〜07: Arrangement、overlay、Polygon_set Boolean、skeleton、offset、Minkowskiがない。
- 7.13.02〜04: alpha shape、wrap、bounding volume がない。

注記 (7.3): 7.3.03 法線は、軸整列立方体(外向き/内向き巻きの2ケース)の各面法線・各頂点法線を
手計算の定数と照合して束縛している。必須validatorは同一workerコードを再実行する整合性チェックであり、
独立オラクルではない。7.3.01の `triangulated` はworker内の面次数フラグ由来で、CGAL::is_triangle_mesh
直接ではない(worker変更は全evidence再生成を要するため未対応、TODO)。
