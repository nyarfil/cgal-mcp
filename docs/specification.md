# CGAL MCP 設計仕様書 v0.1
## 目的と完了境界
独立MCPが登録済みメッシュを簡略化し、拘束と誤差を検証した成果物を返す。
PythonはMCP/Router/Planner/job管理、C++17はCGAL 6.2.1の幾何処理。
v0.1の実行機能は簡略化の5能力。全CGAL APIの実行実装を意味しない。
102件の長尾索引はヘッダー単位であり実行できないAPIも明示する。

## 入口（常時11ツール）
discover_capabilities、describe_capability、search_api、route_goal、
register_mesh、plan_simplification、plan_hausdorff、execute_plan、job_status、cancel_job、get_artifact。
機能名を100件プロンプトに提示しない。検索の要約→個別定義→明示計画で進める。
describeのJSON Schemaを読んでparametersを渡す。
ホスト側の動的ツール登録に依存しない。MCP resourcesでも個別定義を提供する。

## 入力
ASCII三角形OFF（4 MiB以下、100,000頂点/200,000面以下）。
単位はmm/cm/m。出力は同じ座標系・単位。自動単位変換なし。
有限座標、三角形、面インデックス、重複面、向き、辺の多様性、退化をPythonで検査。
CGALで接続妥当性、退化、自己交差を再検査。自動修復は行わない。
asset_idは単位とSHA-256に基づく。モデル変更は入力ハッシュで拒否。

## 計画
edge_ratioは残す辺数の割合(0,1)。面数指定ではない。
tolerance、error_boundは同じ入力単位。0<error_bound<tolerance。
envelope>=0、0ならフィルタ無効。preserve_borderは既定true。
constrained_edgesは入力頂点番号の2要素配列のリスト。実在する辺だけ許可。
余計なパラメータ、不正値、未知のasset/plan/jobは拒否する。
Plannerは型付き固定DAGであり、任意コード生成や恣意的自動選択はしない。
Routerはランキングと明示候補を返し、曖昧な自然言語から勝手に実行しない。

## workerと検証
plane+line cost/placement、Constrained placement、edge map、
任意Envelopeを組み合わせる。保護セグメントの端点と存在を再検証する。
出力メッシュの自己交差と退化を検査。
独立workerでbounded_error_symmetric_Hausdorff_distanceを実行。
distance±error_boundを保守的な境界とし、
upper<=toleranceならpass、lower>toleranceならfail、それ以外はindeterminate。
Envelopeの通過だけでHausdorff合格としない。
目標未達と幾何検証不合格は別。拘束で目標未達でも停止結果は記録する。

## job
queued→running→succeeded/rejected/failed/timed_out/cancelled。
同時2worker job、最大16待機/実行job。workerごと120秒。
シェルを使用せず構成済みバイナリだけ起動。MCP入力に任意パスはない。
取消/timeoutはプロセスをkillしてwait。検証合格のみ出力assetを登録する。
plan、計算値、検証値、結果IDをaudit.jsonへatomic renameで記録する。
資産/plan/jobの索引はセッション内。再起動時のジョブ復旧・クラスタ分散は対象外。

## 対応と制限
stdioが基本。公式Clientでmodern自動交渉とlegacyを試験。
SDK 2.3.0がMCP仕様版の交渉を担当する。独自JSON-RPC実装なし。
検証対象はLinux/Python3.12/C++17。Windows/macOSは未検証。
入力は位置・接続だけで、材質/UV/B-rep/面IDの自動維持は提供しない。
CADへの適用は明示操作とundo可能なホストトランザクションが必要。
