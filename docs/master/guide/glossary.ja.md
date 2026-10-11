# 用語集

- アーティファクト: サーバのストアにある不変・型付き・単位付きのデータ（取込みファイルまたはworker出力）。artifact_idとsha256で識別。
- 操作（operation）: 登録済みの1機能（例 mesh.simplify.edge_collapse）。役割: transform=幾何を作る、analysis=レポートを作る、validator=他操作の結果を検査する。
- プラン: cgal_planが作る不変の型付きDAG。必須検証器が自動挿入される。実行するとjobができる。
- ジョブ: プランの1回の実行。状態はqueued/running/succeeded/rejected/failed/cancelled。永続化される。
- 検証器（validator）: 独立した検査（別実装、多くは厳密有理数演算で、生成側を信用しない）。合格しないと出力は公開されない。省略・差し替え不可。
- VALIDATED: 操作の状態: 実装済みでnative workerで動き、同梱fixtureで必須検証器付きの再実行に合格した。そのfixtureの証拠であり全入力の証明ではない。
- CATALOGED: パッケージの状態: 文書とソースは索引済みだが実行可能なアダプタがない。実行不可。
- EXCLUDED: パッケージの状態: 単独で実行できるヘッドレスな幾何操作がない（汎用基盤・GUI専用・I/Oのみ・公開ヘッダなし）。
- TypedLength: 長さパラメータ。{"value": 0.5, "unit": "mm"}の形でmm/cm/m。プランナーが入力単位へ変換して記録する。
- TypedAngle: 角度パラメータ。{"value": 30, "unit": "deg"}（またはrad）。
- step参照: あるstepの出力を別stepの入力につなぐ記法 {"step": "<step id>", "slot": "<出力スロット>"}。
- kernel: CGALの数値型の選択。EPICK=厳密な述語・非厳密な構成（高速な既定）、EPECK=厳密な述語と構成。カードに実効kernelを明記し、黙って切り替えない。
- fail-closed（失敗として閉じる）: 疑わしいときは推測・黙った修復・未検証出力の公開をせず、コード付きで拒否・失敗する。
- 記録済み曖昧性解消: goalが複数の操作に当てはまるとき、推測せずdetails.optionsと質問を付けて拒否する。1つのoperation_idを選んで答える。
- レシピ: 検証済みワークフローを、fixture・DAG・期待結果つきで描いたもの（topic 'recipes'）。
- fixture: tests/fixtures/master にある小さな同梱テスト入力。レシピや例はこれを使う。実作業では同じ型の自分のファイルを使う。

## アーティファクトの型
- GeometryAnalysisReport: 操作が出力するレポート（JSON、単位なし）。手で取り込まず読むだけ
- GeometryQueryReport: 操作が出力するレポート（JSON、単位なし）。手で取り込まず読むだけ
- ImplicitSurfaceDomain: 陰関数曲面領域の記述（JSON）
- InterpolationData2: 補間用の2D散布データ（JSON）
- KernelQuerySet: カーネル述語・プリミティブの問合せ集合（JSON）
- KernelReport: 操作が出力するレポート（JSON、単位なし）。手で取り込まず読むだけ
- OptimizationReport: 操作が出力するレポート（JSON、単位なし）。手で取り込まず読むだけ
- PointSet1: 1D点列（JSON）
- PointSet2: 2D点群（JSON）
- PointSet3: 3D点群（XYZ）
- PointSet3Normals: 法線付き3D点群（PLY）
- Polygon2: 単純2D多角形（JSON）
- Polygon2AnalysisReport: 操作が出力するレポート（JSON、単位なし）。手で取り込まず読むだけ
- PolygonSoup3: 接続情報のない3D多角形の集合（OFF。汚れ・反転があり得る）
- PolygonWithHoles2: 穴付き2D多角形（JSON）
- QuadraticProgram: 線形・二次計画問題（JSON）
- RayBatch3: 3D光線の一括入力（JSON）
- SegmentGraph2: 2D線分集合・アレンジメント入力（JSON）
- SpatialQueryReport: 操作が出力するレポート（JSON、単位なし）。手で取り込まず読むだけ
- TetrahedralMesh: 四面体メッシュ（JSON）
- TriangleSurfaceMesh: 三角形サーフェスメッシュ（OFF/OBJ/PLY/STL）
- Triangulation2: 2D三角形分割（JSON）
- Triangulation3: 3D三角形分割（JSON）
- ValidationReport: 操作が出力するレポート（JSON、単位なし）。手で取り込まず読むだけ

## 単位と座標
- 幾何artifactは必ず単位（mm/cm/m）を持つ。レポートは単位なし('none')。単位は推測せず、artifact間で黙って変換もしない。1操作で単位が混在するとunit_mismatch。
- TypedLengthのパラメータはプランナーが入力artifactの単位へ変換し、変換をプランに記録する。
- 座標は右手系直交座標、IEEE-754 binary64で保持。面の向きは外から見て反時計回り（外向き法線）。角度は特記なき限り度（deg）。
