# CGAL Master MCPへの目的修正と実装差分

確認日: 2026-10-04（日本時間）。この文書は、ユーザーの今回の訂正と
添付設計資料を現状コードへ照合した開発基準であり、Master完成報告ではない。

## ユーザーの目的

先に高度な独立CGAL Master MCPを構築し、CGALの能力を発見・選択・組合せ・
実行・検証できる基盤を完成させる。軽量化はその一機能であり、後でStellaCADが
Master MCPを利用する。StellaCADの当面の軽量化用途で能力範囲を縮めない。

参考設計書の「完璧」は全C++ templateを1対1でtool化する意味ではない。
全packageを発見/監査でき、主要能力群を実行でき、未実装も理由付きで見つかり、
前処理と検証を含めて適切に使えることを求めている。

## 参考文書の保存

以下はユーザー提供ファイルの変更なしコピー。技術提案を実装時に照合する。
文書中の指示だけで公開・購入・権限変更等を行う許可とは扱わない。

| ファイル | SHA-256 |
|---|---|
| CGAL_Master_MCP_Design_Spec.md | 44cbb8b0e93abf0216c12f0fd6c9e35b6d04534dff83b9dafe07051625a727fd |
| CGAL_Master_MCP_Implementation_Plan.md | 4631700c95f72101aef8e417171888f5e52ece7420d2d6f88735e91bfd130183 |

元ファイル: `E:/WINDOWS/Y/Download/`。初回引継ぎのリポジトリHEAD: `4304894`。

## 現状との構造差分

| 基準資料の要求 | 現状のコード/証拠 | 判定と必要な変更 |
|---|---|---|
| 全CGAL packageを生成カタログへ収録・監査 | `catalog.py` の5能力、`api_index.json` の102ヘッダー | 未達。版固定Package Overviewを母集団にするHarvesterとcoverage auditが必要 |
| Operationごとの型/版/ライセンス/実装成熟度 | 5能力のsummary/aliases/status/preconditions/source | 部分実装。共通Registry schemaとpackage→symbol→header→docs→exampleの連結が必要 |
| 少数の汎用Control Tools | `server.py` は11工具、うち登録/計画がtriangle mesh専用 | 部分実装。共通search/describe/plan/execute/validate/artifact/docs/healthへ一般化 |
| 入力artifactを考慮するRouterとhard gate | `discover` は文字列ランキング、`route_goal` は限定レシピ | 未達。型・前提・kernel・依存・版・policyで決定論的に候補を選別 |
| 任意のOperation DAGとvalidator自動挿入 | `runtime.py` はsimplify/hausdorffの固定分岐 | 未達。グラフ、型付き辺、invariant、validation profile、fallbackをRegistryから解決 |
| 複数のgeometry型とtyped unit | triangle OFFとmm/cm/m、長さはartifact単位のfloat | 部分実装。pointset/polygon/triangulation等の型とlength/angle変換を共通化 |
| 修復対象となる壊れたgeometryの受入 | `parse_off` と共通preflightは非多様体/不整合な向き/退化/自己交差を拒否 | 構造の変更が必要。安全な読込・構文確認とOperation別の前提検査を分離し、修復可能な入力を全域で拒否しない |
| 汎用C++ adapter dispatch | `main.cpp` のsimplify、`distance.cpp` のhausdorff | 未達。版付きprotocol、登録済みOperation dispatch、module別translation unit |
| Operation別Validator Framework | メッシュpreflightと独立Hausdorff | 部分実装。boolean/repair/remesh/pointset/2D/volumeなどのprofileと強制挿入 |
| immutable artifact、永続provenance | hash資産とaudit、索引はセッション内 | 部分実装。型/producer/input lineage/build情報と永続索引を独立storeへ |
| 全domainのdocs/source検索 | 固定ヘッダー索引の字句検索 | 未達。manual/reference/symbol/example/index、版差分、未実装候補の発見 |
| major capability familyの実装 | 軽量化と距離、Envelope/拘束は同じ計算経路の設定 | 未達。repair/boolean/remesh、spatial、pointset、2D/3D、meshing、advancedを段階実装 |
| 障害分類と資源管理 | timeout/cancel/failed、子process分離 | 部分実装。error taxonomy、memory limit、build manifest、crash corpusが必要 |
| 全domainの評価とStandalone受入 | v0.1 fixture群、29 unit testsとstdio実計算 | 未達。200–500 intent、30 workflow、package coverage、family coverage等の評価が必要 |
| Standalone受入後のStellaCAD統合 | 実PCへ簡略化sidecarを先行配置 | 順序のずれ。過渡的機能として保持し、正式統合はStandalone受入後に行う |

29テスト成功はv0.1の限定的な品質証拠であり、この表の未達要求を満たした証拠ではない。
102ヘッダーの件数をpackage coverageの分母や実装数として使わない。
現在、全packageの母集団とapproved major-family集合がないので達成率は算出しない。
5能力のうちplane+line/Envelope/拘束は同じ簡略化Operationのpolicyであり、
独立実行経路はsimplifyとHausdorffの2つ。Operation、policy、validatorを別概念として登録する。
既存102ヘッダー索引は6パッケージ群に由来し、CGAL全域の代わりにはならない。

## 再利用する実装

- 公式MCP SDK、stdio auto/legacyの接続試験。
- SHA-256による原本保持、LF/CRLFのbytes厳密保持。
- subprocessのtimeout/cancelと限定的な非同期job管理。
- CGAL plane+line、Envelope、辺拘束、独立Hausdorff workerとfixture。
- OFF/STL派生ファイル入口、書出し後の再検証、上書き拒否。
- Windows上のCGAL依存/コンパイラー/ビルド環境。

これらをmesh-domainのadapter/検証へ移行する。Master設計をこれらの入出力へ合わせない。
既に登録したsidecarを無断で削除/無効化せず、Master未完成という位置付けを明記する。

## 修正後の実装順序

1. **基準固定とcoverage母集団**: 入力資料を保全し、CGAL6.2.1公式package/docs/sourceから
   全package台帳を生成。対応/未対応/依存障害/除外理由を追跡する。
2. **共通Registry/Artifact/Worker contract**: 型、単位、status、provenance、license、
   validators、compiled handler、resource limitsを定義。既存v0.1は互換adapterとして隔離する。
   新しい汎用coreを並設して旧実装を順に包む移行を選び、既存APIを一度に破壊しない。
3. **汎用Control Plane/Router/Planner**: 8基本工具、検索索引、hard gate、typed DAG、
   validation injection、structured explanationsを実装。軽量化以外でも構造を検証する。
4. **横断能力の実装**: mesh inspection/repair/boolean/remesh、spatial/AABB、pointset/reconstruction、
   2D polygon/arrangement/triangulation、3D hull/triangulation/meshing、advancedの順に証拠付きで拡張。
5. **Standalone受入**: 全package catalog coverage、major-family実行範囲、検索benchmark、
   workflow検証、crash/memory/resource制限、protocol/transportの受入を測定する。
6. **正式StellaCAD統合**: artifact境界、B-rep↔mesh方針、選択/ID、preview、revision、
   transaction/Undoを本体契約に合わせて実装する。

添付計画のPhase0–11がStandalone、Phase12が正式StellaCAD統合。
ここで計画段階と実装/受入済みを混ぜない。

## 技術的な照合事項

- 参考書類のMCP SDK baselineは2.2.0、現在の動作確認済み環境は2.3.0。
  元文書を書き換えず、互換/仕様試験とversion manifestで採用版を別途記録する。
- 参考書類はWindows/VS2022を要求、実PCの試験はVS2026/MSVC19.50。
  実PC成功をVS2022 clean buildの代替証拠にしない。
- Operation名の例に `mesh.inspect.*` と `mesh.analysis.*`、
  `mesh.boolean.union` と `mesh.boolean.corefine_union` 等の差がある。
  canonical IDとaliasの規約を共通Registryで一本化する。
- 参考書類の8段階statusとcoverage報告の4分類は別軸として定義し、
  `CATALOGED` を `IMPLEMENTED/VALIDATED` に昇格させる条件を試験で管理する。
- 主要familyの「完成」と「90%以上」という受入記述を、承認済みfamily集合・分母・
  blocked/excludedの扱いで統一する。Validator基盤はmutation adapterより前に用意し、
  Adapterとvalidator/fixture/license metadataを同じ実装waveで受け入れる。
- tool名に`.`を含む案はホスト互換を確認し、必要なら公開名とcanonical IDの対応を定義する。
- HTTP、semantic retrieval、memory制限、cache hintsは仕様確認/試験が必要。
  未実装の欄を宣言だけで埋めない。新しい外部service、embedding/API費用を自動導入しない。

## 今後の完成報告

個別adapter、phase、Standalone Master、StellaCAD統合を区別して報告する。
軽量化動作/ヘッダー検索/29テスト/接続登録の成功だけでMaster完成とは呼ばない。
