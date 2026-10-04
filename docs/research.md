undefined
## 追加確認
- MCP公式Python SDKの最新リリースAPIはv2.3.0（2026-10-02公開）を返した。
  v2.3.0のMCPServer/runと公式Clientを使用し、CIの9テストが成功。
- CGAL v6.2.1のedge_collapse_garland_heckbert.cppでplane_and_lineを確認。
- edge_collapse_envelope.cppとConstrained_placement.hで組み合わせを確認。
- hausdorff_bounded_error_distance_example.cppとdistance.hのコメントで、
  symmetric APIとerror_boundの意味を確認。distance±error_boundで保守的判定。
- Surface_mesh_simplificationのConstrained_placement.hには
  GPL-3.0-or-later OR LicenseRef-CommercialのSPDX記載がある。
  別プロセス化だけで配布条件が解消されるとは扱わない。
- API索引はCGAL v6.2.1のGitHub contentsから102件の実在ヘッダーを収集。
  Spatial_searching、Triangulation_2/3、Convex_hull_3のdocumentation headersと
  Surface_mesh_simplification、Polygon_mesh_processingのimplementation headers。
  implementation headerは内部補助を含み得るためpublic API保証はしない。
  102件を102個の実装済み機能と表示しない。

未完了: MCP仕様本文とホスト別互換性、既存CGAL MCP比較、bindings範囲、
全対象パッケージのライセンス、型付きPlanner/job管理、実メッシュ検証拡充。

## MCP仕様と既存実装の追加確認
公式schema/2026-07-28/schema.tsのLATEST_PROTOCOL_VERSIONを確認。
SDK 2.3.0のClientソースでautoとlegacy交渉、StdioServerParametersを確認し、
両モードを実stdio subprocessでテスト。
既存実装検索はGitHub repository query "CGAL MCP"を使用。
MedAxisのREADMEは医用画像向けQt/VTK/ITK/OpenCASCADE/CGAL統合を示す。
今回の独立メッシュ簡略化workerと同じ用途の完成品とは確認できなかったため、
公式MCP SDKとCGALポリシーを再利用し、アプリ固有のRouter/job境界を実装。
この検索だけで全既存実装を網羅したとは扱わない。
