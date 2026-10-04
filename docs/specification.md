# CGAL MCP 設計仕様書
状態: 初期仕様。全CGAL APIの実装完了を意味しない。

## 目的
独立したPython MCPサーバーとC++17 CGAL workerを実装・検証した後、StellaCADへ統合する。
100以上の機能を常時モデルへ提示せず、能力索引から候補を検索し、必要な定義だけ取得する。

## 公開入口
discover(query, limit): 小さい候補一覧と選択理由。
describe(capability_id): 入出力スキーマ、前提条件、制約、検証方法。
plan(goal, asset_id, parameters): 型付き実行計画。曖昧な目的は候補を返す。
execute(plan_id): 検査済み計画だけ実行しjob_idを返す。
job_status(job_id), cancel(job_id): 状態取得と取消。
search_api(query): 版固定の公式API索引を検索。未対応APIは実行不可と明示する。

describeはアプリケーション内の定義取得であり、MCPホストの動的ツール登録を保証しない。
基本構成は固定入口と機能ID方式とする。tools/listの動的変更はホスト互換性確認後に任意対応する。

## カタログ
機能ID、別名（日英）、要約、CGALパッケージ、バージョン、原典URL、
入力/出力JSON Schema、必要メッシュ特性、単位、ライセンス、
実装状態、worker操作名、検証戦略を保持する。
状態は planned / implemented / verified。未実装を成功応答や代替幾何処理で偽装しない。
100以上への拡張は実在APIの索引として行い、同一機能の名前変更で件数を水増ししない。

## 重点機能
Surface Mesh Simplification、Garland-Heckbert plane+line、
Polyhedral Envelope、edge constraints、Constrained placement、
双方向Hausdorff検証。
目標割合は辺数か面数かを明示し、CGAL stop predicateの意味と区別する。
拘束により目標未達でも停止理由と実測値を返す。
Envelope通過を双方向Hausdorff保証と見なさない。
推定距離と保証付き境界を別の結果型にする。

## 実行契約
入力は登録済みasset_id。任意パス、任意シェル、任意C++コードは受け付けない。
単位未指定、非有限座標、空メッシュ、壊れた接続、非三角形を検査する。
自己交差、閉性、向き、退化要素は操作ごとの要件として検査する。
自動修復は入力を上書きせず独立した操作として記録する。
入力ハッシュ、CGAL/worker版、パラメータ、拘束、検証値、停止理由を成果物に添える。
検証不合格の結果はStellaCADへ適用不可とする。

## 受入条件
MCP公式クライアントでinitialize/tools/list/tools/call/resourcesを確認。
候補検索の上位一致、誤選択拒否、未実装拒否を確認。
CGAL 6.2.1をC++17でビルドして実メッシュで重点機能を検証。
境界、穴、鋭い稜線、明示拘束、退化、非多様体、自己交差を含むfixturesを使用。
元メッシュ破損なし、拘束保持、誤差判定、取消、timeout、worker異常終了を確認。
100以上のAPI索引と実装済み件数は別々に報告する。
