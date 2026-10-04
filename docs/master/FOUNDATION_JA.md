# Master基盤の実装と利用

CGAL Master v1の最初の区切り。全主要能力の完成・Standalone受入とは区別する。
ユーザーの原本MDは変更せず、基準と差分を別文書へ記録している。

## 範囲

公式CGAL 6.2.1のsource/docs archiveをチェックサム付きで取得し、配布物と
展開された全ファイルの照合receiptから126パッケージの台帳を生成する。
旧102ヘッダー索引は母集団に使用しない。ライセンスの根拠を保持し、
単一条件を解決できないパッケージは理由付きの未解決状態とする。

新coreは旧runtimeと別の`cgal-master-mcp` entrypoint・データ領域を使う。
公開工具は固定12個。`PointSet3/XYZ → hull.convex_3 → TriangleSurfaceMesh/OFF`
を実行し、`hull.validate.convex_enclosure`が必ず元点群と結果を照合する。
不合格候補は隔離され、合格Artifactのみ公開する。点群、Plan、jobと生成履歴は
SQLiteへ保存し、再起動後も確認できる。blobの内容hashと型付きArtifact IDは別で管理する。

## ビルドと実測

Python基準3.12、実PC3.13、MCP SDK 2.3.0。WindowsのVS2022とLinuxはCI、
実PCのVS2026は別のビルド証拠として扱う。

```powershell
python -m pip install -e '.[mesh]'
python scripts/fetch_master_baseline.py --root work/master-baseline
python scripts/harvest_cgal.py --source work/master-baseline/source/CGAL-6.2.1 --docs work/master-baseline/docs/doc_html --output catalog
python scripts/sync_master_package_catalog.py
```

CMakeでは`CGAL_DIR`を上記公式sourceへ指定する。Windowsは既存のvcpkg toolchainと
依存ライブラリの場所を併記する。再現可能なOS別の設定は
[worker CI](../../.github/workflows/master-worker.yml) に保存する。

```powershell
cmake --build build-master --config Release --target cgal-master-worker --parallel 1
python -m unittest discover -s tests -v
python tests/master_worker_smoke.py build-master/Release/cgal-master-worker.exe
python tests/master_worker_cases.py build-master/Release/cgal-master-worker.exe
python -m tests.master_mcp_e2e auto
python -m tests.master_mcp_e2e legacy
python -m tests.master_http_e2e auto
python -m tests.master_http_e2e legacy
python scripts/verify_master_foundation.py --output work/master-foundation.json
```

Linuxのworkerは`build-master/cgal-master-worker`。受入scriptは実際のC++処理・必須検証・
原本保持・再起動後の復元を確認する。主要能力の80要求を合格扱いにするscriptではない。
実PCの測定報告は [Windows/VS2026の基盤受入](evidence/foundation-windows-vs2026.json) に保存する。

## MCP起動

既設の旧MCP設定を保ち、別サーバーとして次を登録する。絶対パスは導入先に合わせる。

```json
{
  "command": "E:/aiwork/cgal-mcp/.venv/Scripts/python.exe",
  "args": ["-m", "cgal_mcp.master.server", "stdio"],
  "env": {
    "CGAL_MASTER_WORKER": "E:/aiwork/cgal-mcp/build-master/Release/cgal-master-worker.exe",
    "CGAL_MASTER_DATA": "E:/aiwork/cgal-mcp/work/master-data"
  }
}
```

`cgal_artifact_import(path, unit="mm")`で管理Artifactへコピーし、
`cgal_plan(request={operation_id:"hull.convex_3", inputs:[artifact_id]})`、
`cgal_execute(plan_id)`、`cgal_job_status(job_id)`の順に使う。
成功した出力は`cgal_artifact_inspect`で型・単位・hash・履歴を確認できる。
取消は`cgal_job_cancel`。形状変更やvalidatorの省略をPlanから指定することはできない。

HTTPは`python -m cgal_mcp.master.server streamable-http --host 127.0.0.1 --port 8000`。
HTTPのfile取込み・書出し範囲は`CGAL_MASTER_FILE_ROOTS`へOSのpath separator区切りで
明示設定する。未設定ではファイルアクセスを許可しない。

## 全文資料検索

```powershell
python scripts/build_master_docs_index.py build --source work/master-baseline/source/CGAL-6.2.1 --docs work/master-baseline/docs/doc_html --catalog catalog --output work/master-docs-index.sqlite
python scripts/build_master_docs_index.py query --database work/master-docs-index.sqlite --query AABB_tree --limit 3
```

索引にはpackage、manual/API、公開header、examplesの出典pathとSHA-256を保持する。
全文SQLiteは生成物としてGitへ入れない。MCP経由の全文検索は
`CGAL_MASTER_DOCS_INDEX`へその絶対パスを設定する。
未設定でも同梱126パッケージの版固定資料台帳を検索できる。

## 完成判定

15分野・80要求、300件の日英検索、30本以上のworkflow、障害・性能・host接続・buildの
全受入をそろえる。報告JSONの記載だけでは主要能力を検証済みにしない。
合格した区切りをGitHubへ反映し、CI結果を確認する。正式なStellaCAD統合はStandalone受入後。
