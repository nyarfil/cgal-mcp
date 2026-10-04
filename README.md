# CGAL MCP

StellaCADへの統合を目指す独立CGAL MCPプロジェクト。

## 現在の状態
初期の能力カタログ検索・オンデマンド定義取得と、そのテストを実装。
CGAL C++17 worker、MCP transport、Planner、job manager、100+ API索引は未実装。
カタログの5つの重点機能はplannedであり、幾何計算はまだ実行できません。
CI成功はカタログのテスト成功を意味し、CGAL全体の検証を意味しません。

## 導入・テスト
Python 3.10以上。現時点のカタログは外部依存なし。

```sh
git clone https://github.com/nyarfil/cgal-mcp.git
cd cgal-mcp
python -m unittest discover -s tests -v
python -c "from cgal_mcp.catalog import discover; print(discover('軽量化'))"
```

## 設計資料
- [設計仕様書](docs/specification.md)
- [設計書](docs/architecture.md)
- [StellaCAD統合案](docs/stellacad-integration.md)
- [公式情報の調査記録](docs/research.md)

## 実装順
1. CGAL 6.2.1の公式ヘッダー/examples、MCP仕様、SDKリリース、既存実装を確認。
2. C++17 workerを実装し、簡略化・plane+line・Envelope・拘束・Hausdorffを実メッシュで検証。
3. 公式SDKのMCP入口、型付きPlanner、前提条件検査、job管理を追加。
4. 実在APIを100以上索引化し、状態を明示した長尾API検索を追加。
5. MCP統合試験と障害試験を実施し、StellaCADソースに基づきadapter設計を確定。

コミットごとに実装状態と検証結果を記録します。
