# 実装状況

プロジェクト全体の目標はCGAL Master MCP。現在の軽量化v0.1では未達。
実装対象と順序は [目的修正と差分](master/SCOPE_CORRECTION_JA.md) に従う。
以下の「作成済み」「成功」はv0.1の局所結果であり、Master完成を意味しない。
## 独立MCP重点機能版 v0.1
設計仕様、設計書、Python MCP/Router/Planner/資産/job管理、
C++17 CGAL worker、102ヘッダー索引、テスト、CI、READMEを作成済み。
最終コードcommit e44dcc514e877e24461adf339ad7f6bcab2f627dの
Python/MCP 23テストとCGAL/MCP通しテストが成功。
証拠はvalidation.mdに記録。

## StellaCAD
ホスト境界のadapterソース、競合防止テスト、統合設計書を作成済み。
現在は実PCのStellaCAD本体を調査済み。選択モデルのメッシュ置換/Undoの互換APIはなく、
そのネイティブ統合は未実装。下記の補助MCPで検証付き派生ファイルを提供する。

## Windows/実PCへの引継ぎ（2026-10-04）

`E:/aiwork/cgal-mcp` に専用Python/MCP環境を配置し、CGAL 6.2.1のWindows workerをビルド済み。
改行変換による資産ハッシュ不一致とWindowsのworkerパスを修正した。
Python/MCP/file bridgeの28テスト、簡略化・距離worker fixture、
MCP stdio auto/legacyによる実計算をこのPCで検証した。

StellaCADの `integration/cgal/stella_cgal_mcp.py` をCodex共通設定とプロジェクト設定へ登録。
実設定を読み込んだ別プロセスのMCP clientから `stella_cgal_simplify_file` を呼び、
200面STLから92面の検証済み新規STLを取得した。派生メッシュの補助MCP接続であり、
ネイティブCADHostの置換/Undo実装ではない。新規チャットで追加工具を読み込む。
28テストとWindows実計算はローカル結果。更新したGitHub Actionsの実行結果は別途確認が必要。

## 全CGALへの拡張
102件の索引を102件の実行可能APIとは表示しない。
重点機能以外を実行可能にするには、APIごとのSchema、前提条件、
worker dispatch、独立検証、fixturesを追加する必要がある。
「全CGALを完璧に使う」という無限定の保証はしていない。
