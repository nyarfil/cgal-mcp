CGAL Master MCP: CGAL 6.2.1 上のデータ駆動の幾何サーバ。228個の操作（ユーザー向け118、独立検証器110）を15分野で登録: 7.1 カーネル; 7.2 空間問合せ; 7.3 解析; 7.4 修復; 7.5 Boolean; 7.6 再メッシュ; 7.7 軽量化; 7.8 メッシュ解析・分解; 7.9 点群; 7.10 曲面再構成; 7.11 三角形分割; 7.12 多角形; 7.13 凸包等; 7.14 メッシュ生成; 7.15 最適化・数値幾何。全操作は隔離されたnative workerで動き、全結果は公開前に必須検証器の合格が必要。

呼び出し順序（飛ばさない）
1. cgal_get_guide(topic="start", lang="ja")を最初に1回。topic: start, families, recipes, recipe:<id>, op:<operation_id>, family:<id>, errors, glossary, limits-and-status。resource cgal://guide/ja/... とprompts（start_here, repair_and_simplify_mesh, reconstruct_surface_from_points, validate_geometry, compare_meshes, 2d_boolean_offset, choose_operation）も同内容。
2. 探す: 要望が既知ワークフローならtopic="recipes"（Xを望むならこの手順）。そうでなければcgal_capabilities_search(query=<goal、任意の言語>)→cgal_get_guide(topic="op:<operation_id>")で完全なカード（パラメータ・単位・上限・呼び出し例）。
3. 入力: cgal_artifact_import(path, unit, artifact_type)。unitはmm/cm/mで必須（推測しない）。形式: off, obj, ply, stl, xyz, 型付きjson。最大512MiB。解析のみで修復はしない。
4. cgal_plan(request): {"operation_id", "inputs": {slot: artifact_id}, "parameters"}、または出力を{"step", "slot"}でつなぐ{"steps": [...]} のDAG。検証器は自動挿入され省略不可。長さは{"value", "unit"}。
5. cgal_execute(plan_id)は即座にjobを返す。cgal_job_statusをsucceeded/rejected/failed/cancelledまで確認。結果はjob.outputs（型・単位・properties）とjob.validation[].reportからのみ読む。cgal_artifact_exportは新しいパスへバイト列を書く。

状態の語彙（ユーザーに正直に）
操作: 228 VALIDATED。VALIDATEDは実行可能で、同梱fixtureで独立検証器つきの再実行に合格した意味。全入力の証明ではない。パッケージ（CGAL 126個）: VALIDATED 45（実行可能な操作あり）、CATALOGED 69（文書索引のみ。実行不可）、EXCLUDED 12（単独のヘッドレス操作なし: GUI専用・汎用基盤・I/Oのみ）。サーバ全体の受入達成はここでは主張しない。

規約
単位はartifactごとにmm/cm/m。1操作での単位混在はunit_mismatch。レポートは単位なし。座標は右手系直交・binary64、外向き法線は反時計回り。角度は特記なき限り度。

ツール（13個）
cgal_get_guide（最初に呼ぶ: ガイド・カード・レシピ）、cgal_capabilities_search（goalに合う操作の順位付け）、cgal_capabilities_describe（レジストリ定義の原本）、cgal_artifact_import / cgal_artifact_inspect / cgal_artifact_export（データの出し入れ）、cgal_plan（型付き不変プラン）、cgal_execute / cgal_job_status / cgal_job_cancel（実行・確認・中止）、cgal_validate（既存artifactをsourceと再照合）、cgal_docs_search（固定されたCGAL文書索引。文書は実行ではない）、cgal_system_health（上限・workerビルド・レジストリrev）。

アーティファクトの型
GeometryAnalysisReport, GeometryQueryReport, ImplicitSurfaceDomain, InterpolationData2, KernelQuerySet, KernelReport, OptimizationReport, PointSet1, PointSet2, PointSet3, PointSet3Normals, Polygon2, Polygon2AnalysisReport, PolygonSoup3, PolygonWithHoles2, QuadraticProgram, RayBatch3, SegmentGraph2, SpatialQueryReport, TetrahedralMesh, TriangleSurfaceMesh, Triangulation2, Triangulation3, ValidationReport。操作カードに各入力slotが受ける型と各出力slotが作る型を明記。JSONレポート型は読むもので取り込むものではない。

fail-closed
推測せず、コード付きで拒否・失敗する。rejected=検証器が結果を確認できず出力は非公開。unmet_precondition=宣言済みの上限・性質が計算前に不成立（例: 距離/Hausdorff系は400面以下。各カードに上限）。resource_limit/timeout=入力を小さくするか、cgal_system_healthの上限内でexecution={"wall_time_ms","memory_mb"}を指定。invalid_input・unmet_precondition・unsupported_operation・検証失敗の後に同じ要求を再試行しない。未知の操作は拒否され、C++をその場で生成しない。

曖昧さ
cgal_plan(goal=...)は1つの操作が明確に当てはまるときだけ。ambiguous_route（またはdetails.optionsつきunsupported_operation）は記録済みの質問と選択肢を持つ。推測せずユーザーに尋ね、operation_idで再plan。検索でquery_analysis.abstained=trueは実行可能な該当なしの意味。

未対応
CATALOGED/EXCLUDEDのパッケージ（topic "limits-and-status"に理由コード付きで一覧）は実行不可。名指しするとdetails.unsupported_cgal_packagesで失敗。その旨を伝え、最も近い実行可能な操作は質問として示し、黙って代用しない。既定: 同時実行2、worker 4096MiB、壁時間120秒（実値はcgal_system_health）。エラーはtopic="errors"。数値はjob出力・検証レポートにあるものだけを示す。
