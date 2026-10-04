# CGAL-MCP接続（2026-10-04）

**位置付け修正:** この接続は軽量化v0.1の先行sidecarです。
ユーザーの最終目標は独立CGAL Master MCPの完成後の正式統合です。
この接続成功をMaster完成や正式統合の受入と扱いません。
開発基準: `E:/aiwork/cgal-mcp/docs/master/SCOPE_CORRECTION_JA.md`。

CGALはStellaCADの補助メッシュ計算MCPとして接続する。CAD生成バックエンドの
選択とは分離し、既存のFusion/FreeCAD/ClassCAD/CadQueryの選択・文書ガードを保持する。

- Python/MCP正本: `E:/aiwork/cgal-mcp`、専用 `.venv`、MCP SDK 2.3.0。
- CGAL 6.2.1: `V:/Program-files/CGAL/vcpkg_installed/x64-windows`。
- 実計算: `E:/aiwork/cgal-mcp/build/Release/cgal-worker.exe` と `cgal-distance.exe`。
- StellaCAD入口: `integration/cgal/stella_cgal_mcp.py`。
- MCP登録名: `cgal-mcp`。Codex共通設定、本体 `.codex/config.toml`、日本語のStellaCADチャット作業場所に登録。
- 監査/派生データ: `cadmcp-workspace/cgal-mcp`。正式CAD正本とは別に置く。

常時公開するのは独立MCPの11工具と `stella_cgal_simplify_file` の計12工具。
102ヘッダーはオンデマンド検索索引であり、102実行機能を意味しない。

## 利用

接続が読み込まれたら `discover_capabilities` と `describe_capability` で目的・Schemaを確認し、
ファイルを扱うときは `stella_cgal_simplify_file` に次を渡す。

```json
{
  "input_path": "V:/mouse/example/source.stl",
  "output_path": "V:/mouse/example/source_cgal.stl",
  "unit": "mm",
  "parameters": {
    "edge_ratio": 0.5,
    "tolerance": 0.1,
    "error_bound": 0.001,
    "envelope": 0.01,
    "preserve_border": true
  }
}
```

例の0.1 mmは汎用の合格閾値ではなく、案件で決める許容値。
`edge_ratio` は辺の割合で、面数割合の保証ではない。拘束が強いと目標に届かない。
STLには単位が保存されないため、単位は入力条件として明示する。
入力はOFF/STL、出力もOFF/STL。新規出力先だけを受け付ける。
入力変換時に同一座標の頂点を接続するが、丸め・修復・再メッシュはしない。
合格した計算結果をSTLへ書き出した後、その実際の書出しメッシュにもHausdorff検証を行う。
fail/indeterminate/failedには成果物を公開しない。

MCP再読込前のローカル入口:

```powershell
$env:CGAL_MCP_WORKER='E:\aiwork\cgal-mcp\build\Release\cgal-worker.exe'
$env:CGAL_MCP_DISTANCE='E:\aiwork\cgal-mcp\build\Release\cgal-distance.exe'
$env:CGAL_MCP_DATA='E:\aiwork\Stella_CAD_SYSTEM\cadmcp-workspace\cgal-mcp'
& E:\aiwork\cgal-mcp\.venv\Scripts\python.exe -m cgal_mcp.file_bridge V:\mouse\example\source.stl V:\mouse\example\source_cgal.stl --unit mm --ratio 0.5 --tolerance 0.1 --error-bound 0.001 --envelope 0.01
```

## CAD境界

STEP/F3Dからの三角形化は選択済みCADの許可された書出し工具を使う。
結果のメッシュは派生artifactとして表示・比較し、元の正確なB-repを上書きしない。
本体のcadMCPは要求・固体・検査・証拠を扱い、CGALはメッシュ簡略化と距離検証を扱う。
この接続は `CADHost.apply_mesh_atomic` の実装ではなく、ネイティブCADの選択モデル置換や
Undoトランザクションは未実装。今後実装する場合は本体のrevision/保護/証拠契約を使う。
旧AgentCADのACMメッシュ・ソース更新へ無理に接続しない。
