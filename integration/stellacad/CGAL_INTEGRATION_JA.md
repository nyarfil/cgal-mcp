# CGAL-MCP接続（Master / v0.1 sidecar）

StellaCADには2つのCGAL MCPを登録している。**AIエージェントは `cgal-master` を使い、`cgal-mcp` は互換フォールバック**とする。

| 登録名 | 実体 | 位置付け |
|---|---|---|
| `cgal-master` | `python -m cgal_mcp.master.server stdio`（`E:/aiwork/cgal-mcp`、branch `codex/master-v1`） | 汎用CGAL Master MCP。13工具・12 resources・7 prompts。登録は`.mcp.json`/`.codex/config.toml`/`.claude/settings.json` |
| `cgal-mcp` | `integration/cgal/stella_cgal_mcp.py`（v0.1 sidecar） | 先行の軽量化専用。互換のため無変更で維持 |

## Masterの状態（2026-10-11、正直な範囲）

- 80/80の要件は、replay束縛の受入評価で個別に検証済み（要件ごとの実C++実行と独立validator）。
- ただし**standalone受入gateは未達のものが残る**: 検索・host・性能・package（人手license確認待ち）。
  性能gateはAABB木/parsed geometryのjob間再利用が未実装のため未達。persistent workerと結果cacheは実装済みだが**既定OFF**で、StellaCAD登録でも明示的にOFF。
- host証拠はCodex app-serverのin-memory試験とSDK stdio/HTTPのみ。Cursor自身からの実呼出し、デスクトップUI操作は未確認。
- 本統合は「StellaCAD側の接続と派生ファイル橋」であり、**Master完成宣言ではない**。ネイティブ`CADHost.apply_mesh_atomic`/Undoは未実装。

## AIエージェントの開始手順（cgal-master）

1. 最初に `cgal_get_guide`（topic=`start`）か resource `cgal://guide/start` を読む。日本語は `lang="ja"`（resource は `cgal://guide/ja/...`）。
2. 目的が決まっていれば `cgal_get_guide(topic="recipes")`、未定なら `cgal_capabilities_search(query=目的)`。`abstained=true`/`unsupported_cgal_packages` は「できない」と報告する。
3. `cgal_get_guide(topic="op:<operation_id>")` でパラメータ・単位・上限を読む。推測しない。
4. `cgal_artifact_import(path, unit)`（単位は必須: mm/cm/m）→ `cgal_plan` → `cgal_execute` → `cgal_job_status`をpoll。
5. `state=succeeded` かつ `validation_status=passed` の結果だけを使う。`rejected/failed`の出力は使わず、`error.code`を報告する。ツール呼出し自体の拒否は、メッセージ中のJSON（`class/code/message`）を読む。
6. 結果は `cgal_artifact_export(artifact_id, 新規path)` で新規ファイルへ。**元のCADを上書きしない**。

STL/OBJ/PLYは「ポリゴンスープ」として取り込まれ、そのままでは簡略化に使えない（`TriangleSurfaceMesh`が必要）。
StellaCADでは完全一致頂点の結合だけを行うOFF変換（修復・再メッシュなし）を経由する（下記adapter）。
Hausdorff検証の対象は400面以下で、超える入力は`unmet_precondition`で実行前に拒否される（例: 500面の`shaft/model.stl`）。

### 許可の方針（`.claude/settings.json`）

- 自動許可（読取/計画のみ）: `cgal_get_guide`、`cgal_capabilities_search/describe`、`cgal_docs_search`、`cgal_system_health`、`cgal_artifact_inspect`、`cgal_plan`、`cgal_validate`、`cgal_job_status`。
- 確認を求める: `cgal_artifact_import`（任意ファイルの読込）、`cgal_execute`（計算実行）、`cgal_artifact_export`（ファイル書込）、`cgal_job_cancel`。
- 派生物のみ・単位明示。登録データ領域は `cadmcp-workspace/cgal-master`（git管理外）。

## StellaCAD adapter（派生ファイル橋）

`integration/cgal/master_derive.py`（CGAL repoのvenvで実行）:

```powershell
E:\aiwork\cgal-mcp\.venv\Scripts\python.exe integration\cgal\master_derive.py simplify SRC.stl OUT.off --unit mm --face-ratio 0.5 --error-bound 0.05 --max-deviation 1.0
```

- `.mcp.json`の`cgal-master`をそのまま起動（stdio）。`mesh.simplify.edge_collapse` + 必須validator（simplification_integrity、symmetric_hausdorff）。
- 出力は新規`.off`と`<出力>.provenance.json`（op id、パラメータ、validator判定と数値、registry revision、CGAL版、plan/job id、元/出力のSHA-256、単位）。
- succeeded かつ全validator passのときだけ公開。既存ファイル・元ファイルは上書き拒否、実行後に元のSHA-256を再確認。
- 試験: `integration/cgal/test_master_derive.py`（実サーバー起動を含む5件）。接続試験: `integration/cgal/verify_master_connection.py`。

### 残作業（TODO）

- `CADHost`/`StellaCADAdapter`（revision照合つきatomic apply、Undo、UI非同期）: StellaCAD本体側にPythonのCADHost境界が存在せず未実装。設計は`E:/aiwork/cgal-mcp/docs/stellacad-integration.md`。
- 出力のSTL書出しと書出し後の再検証（v0.1は実施済み、Master経路は未実装）。400面超の入力の扱い（事前に別手段で粗くするか、上限緩和のMaster側拡張）。
- 同梱CGALのlicense（GPL-3.0-or-later OR 商用）確認、OS別worker配布、update方式。
- Cursor等の他host実機証拠、standalone受入gate（検索・host・性能・package）の達成後に正式統合を再評価。

### 接続証拠（2026-10-11）

`docs/evidence/cgal-master-connection-20261011.json`（`verify_master_connection.py`の出力）。要約:
stdio初期化→tools 13 / resources 12 / prompts 7 → `cgal://guide/start`読取 → `cgal_get_guide`のop card → health（worker利用可、persistent worker one_shot、結果cache無効）→
StellaCAD fixture `stella_icosphere_r10mm_320f.stl`（半径10 mm、320面）を単位mm明示で簡略化 320→158面、validator 2件pass（Hausdorff距離0.468 mm、許容1.0 mm内）、provenance生成、元ファイル不変 →
500面の`shaft/model.stl`は`unmet_precondition`（faces<=400）で拒否され出力なし → v0.1 `cgal-mcp`フォールバックも200→92面で成功。

## パス表記（integration/cgal と integration/stellacad）

正本は**StellaCADの`integration/cgal/`**（登録・起動・本ドキュメントが参照する場所）。CGAL repoの`integration/stellacad/`は同内容の控えで、再配置時にコピー元となる。
`stella_cgal_mcp.py`と`verify_connection.py`はgit blobがバイト一致（作業ツリーのCRLF/LF差のみ）。本書もCGAL repo側へ同じ内容で控える。

---

# v0.1 sidecar（2026-10-04、互換フォールバック）

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
