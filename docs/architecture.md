# CGAL MCP 設計書 v0.1
## 構成
catalog.py: 5能力と日英別名。api_index.json/api_search.py: 102件の版固定ヘッダー索引。
server.py: 公式MCPServerと11個の固定入口。
runtime.py: OFF検査、資産ハッシュ、Pydantic計画、Semaphore、非同期subprocess、結果公開。
worker/main.cpp: plane+line簡略化、Envelope、拘束。
worker/distance.cpp: 双方向bounded-error距離と三値判定。
worker/preflight.h: CGALで退化/自己交差の入力出力検査。
stellacad.py: revision付きスナップショットとatomic applyのホスト境界。

## 選択とオンデマンドロード
discoverはID/要約/状態/スコアだけ。describeがSchemaと実行レシピを返す。
Routerの低確信・曖昧な選択は候補一覧に留める。
Plannerは入力単位・存在する辺・数値条件を検証して固定処理順序を構成する。
能力情報の取得と実行計画を分離し、未対応の長尾APIは検索だけにする。

## 成果物
root/<asset_id>.offは内容ハッシュ付き資産。root/<job_id>/audit.jsonは監査記録。
candidate.offはjob私有の一時出力。合格時に登録し、finallyで候補を削除する。
元メッシュは上書きしない。読み直し時にハッシュを確認する。
MCPサーバーはローカルの信頼されたCAD/AIホスト向け。HTTP公開や複数利用者認証は対象外。

## 障害
worker欠落、exit非0、壊れたJSON、応答版不一致、巨大応答、結果欠落をfailedにする。
計算のtimeoutはtimed_out。取消はcancelled。許容誤差fail/indeterminateはrejected。
queued取消は実行前に終了する。実行中は子プロセスをkillしてwaitする。
プロセスを子階層に分けないCGAL workerが前提。
再起動時のplan/job索引復旧は未実装。監査ファイルと資産は残る。

## 再利用とライセンス
MCP公式SDKを使用。CGAL公式例とポリシーを組み合わせ、幾何アルゴリズムを再実装しない。
CGAL各パッケージのGPL/commercialライセンス条件は配布対象ごとに確認する。
別プロセス化をライセンス回避と扱わない。
