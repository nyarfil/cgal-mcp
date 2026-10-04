# StellaCAD統合設計 v0.1
初版ではStellaCAD本体ソース未提供のためホスト境界を定義した。
2026-10-04に実PCの本体を調査し、補助MCP接続を追加した。
現在の接続手順は [Windows導入](windows.md) および
StellaCADの `docs/CGAL_INTEGRATION_JA.md`。下記のatomic apply契約はネイティブ統合の設計であり、
派生ファイルsidecarの実装済み機能と区別する。

## 実装した境界
cgal_mcp.stellacad.CADHost:
- snapshot(object_id)→Snapshot(object_id,revision,off,unit)
- apply_mesh_atomic(object_id,expected_revision,off,unit,metadata)
後者はrevision照合・置換・undo履歴登録を一つのトランザクションで実行するホスト責務。

StellaCADAdapter.prepareはスナップショットを資産登録して計画を作る。
execute_plan/job_statusで非同期実行する。
applyは成功かつ検証passを必須とし、最新revision/形状/単位を再照合する。
ホストのatomic applyで競合を防ぐ。適用後に同じ計画の再適用を拒否する。
tests/test_stellacad.pyが変更済みモデルの拒否と適用経路を検証する。

## UI
選択モデル→目的検索→削減割合/許容誤差/保持辺の設定→計画→実行→結果プレビュー→適用。
結果には辺数、目標達成、拘束保持、Hausdorff境界、判定、失敗理由を表示する。
cancelで元モデルは変更しない。検証不合格には適用ボタンを提供しない。

## 形状表現
メッシュスナップショットはモデルローカル座標系で生成し同じ系で適用。
ワールド変換はホストが保持し、単位は明示する。
B-repモデルを三角形化する場合は独立のmesh結果として扱う。
元の正確なB-rep/UV/材質/面IDが簡略化結果に自動復元される前提を置かない。
機械的接合箇所は境界またはconstrained_edgesに変換する。

## 本体への接続作業
StellaCADの選択取得、メッシュ抽出、revision、Undo、UI非同期処理をCADHostへ実装する。
Plugin/IPC形式は本体リポジトリで確認後に確定する。
同梱CGALのライセンス、OS別worker配布、アップデート方式を確定する。
派生メッシュのsidecarは実PCへ配置・接続試験済み。
正確な固体正本を保持し、native apply_mesh_atomic/Undoは別の本体実装として残る。
