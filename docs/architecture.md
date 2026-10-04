# CGAL MCP 設計書
## データフロー
MCP入口 → 能力検索 → 定義取得 → Planner → 前提条件検査 → job manager →
C++17 worker → 独立検証 → artifact store。
Pythonはプロトコル・選択・実行管理を担当し、幾何計算はCGALで行う。

## 再利用
MCPの通信、ライフサイクル、スキーマ処理は公式Python SDKを使う。
幾何アルゴリズムはCGALの公式実装とexamplesを基準にする。
独自実装は能力索引、計画、資産管理、検証結果の統一に限定する。
SDK mainのREADMEとリリースAPIの一致を確認して版固定する。

## Router
現段階は依存なしの決定的な能力検索を先に実装する。
完全一致・別名一致を優先し、トークン一致で補う。
implemented_onlyで実行可能候補だけに絞れる。
低スコアでは無理に機能を選ばない。意味検索追加時も状態・前提条件を優先する。
検索の出力は能力ID、要約、状態、スコアのみ。詳細スキーマはdescribeで取得する。

## Workerとjob管理（未実装）
版付きJSON要求を標準入力で受け、標準出力はJSON結果だけとする。
診断は標準エラー。boundedな入力サイズ、出力サイズ、実行時間とプロセス数を設定。
ジョブごとに作業領域と元メッシュのコピーを作る。
SIGTERM後の猶予を経てkillし、不完全な成果物を公開しない。
要求ID、input hash、schema hashを照合し、古い計画の実行を拒否する。
出力は一時ファイルからatomic renameで確定する。

## 検証
C++ workerの操作結果と検証結果を分離する。
許容誤差は入力単位で指定。bbox相対誤差は明示変換して記録する。
Hausdorffの方向、推定/境界、誤差幅、乱数seedを結果に含める。
トポロジー妥当性と幾何誤差は別々に判定する。
constraintsのedge collapse禁止とplacementによる位置保持を別要件にする。

## リリース
verifiedは対象版の実計算とMCP統合テストの証拠がある場合だけ設定。
GitHub ActionsはまずRouterをテストする。workerとMCPのテストが加わるまで
このCIの成功をCGAL MCP全体の検証と扱わない。
