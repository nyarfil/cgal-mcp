# 実PCへの導入と接続確認

開発中のMasterはPython仮想環境と公式CGAL 6.2.1のC++ workerを使います。
既存のv0.1 StellaCAD sidecarとは別の`cgal-master`として、CodexとCursorへ
stdio設定を登録しています。Standalone合格前の正式StellaCAD統合は未実施です。

確認済みの範囲:

- 実PCのVS2026/Python3.13でのworkerとMCP実計算。
- SDKのstdio auto/legacy、Streamable HTTP auto/legacy。
- インストール済みCodex app-server経由の12工具取得・health実呼出し・
  点群取込み→凸包計画→実行→必須検証→合格Artifact検査。
- Cursorの既存MCP設定を保持した追加登録。

Codexの試験は、実際のインストール済みホストを使ったin-memory接続fixtureです。
モデル推論を開始せず、ユーザー用の永続チャットも作りません。
デスクトップUIで工具を選択した操作と、Cursor自身からの実呼出しは未確認です。
設定登録やSDK clientの成功だけで、その未確認項目を合格扱いにしません。

接続設定の例（絶対パスは自分の環境へ置換）:

```json
{
  "command": "/absolute/path/cgal-mcp/.venv/bin/python",
  "args": ["-m", "cgal_mcp.master.server", "stdio"],
  "env": {
    "CGAL_MASTER_WORKER": "/absolute/path/cgal-mcp/build-master/cgal-master-worker",
    "CGAL_MASTER_DATA": "/absolute/path/cgal-mcp/work/master-data",
    "CGAL_MASTER_CATALOG": "/absolute/path/cgal-mcp/catalog",
    "CGAL_MASTER_DOCS_INDEX": "/absolute/path/cgal-mcp/work/master-docs-index.sqlite"
  }
}
```

WindowsのPythonは`.venv/Scripts/python.exe`、VS multi-config workerは
`build-master/Release/cgal-master-worker.exe`です。全文索引は任意で、未生成なら
`CGAL_MASTER_DOCS_INDEX`を省略できます。

Codexホスト試験の再実行:

```sh
python scripts/verify_master_codex_host.py \
  --codex /absolute/path/to/installed/codex \
  --output work/codex-host-evidence.json
```

`--config-home`でCodex設定ディレクトリ、`--server`で登録名を指定できます。
runnerは設定を読取り、対象以外のMCPを子プロセス内のoverrideで停止します。
ディスク上の設定は変更しません。実際の工具結果を取得してから報告を生成し、
workerが試験中に変更されていないことをハッシュで確認します。

実PCの報告は[`evidence/codex-host-windows.json`](evidence/codex-host-windows.json)。
この報告も`standalone_accepted: false`です。
ホスト試験の実装根拠は[公式Codex app-server文書](https://learn.chatgpt.com/docs/app-server)と、
インストール済み実行ファイルから生成したprotocol schemaです。
