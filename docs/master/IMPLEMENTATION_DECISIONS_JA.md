# CGAL Master v1 実装決定と受入基準

決定日: 2026-10-05（日本時間）。ユーザー承認済み計画を実装するための補足。
原本の設計仕様書・実装計画書は変更しない。

## 完成条件

全CGALパッケージの収録・検索100%と、原本計画書7.1〜7.15の主要能力すべての
実装・検証を必須とする。原本の90%目標より今回のユーザー指定100%を優先する。
`catalog/major_requirements.json` は原本の各箇条書きを母数として固定する。
能力群の代表処理一つが動いても、その能力群全体の合格としない。

`scripts/master_acceptance.py` は原本SHA-256、要求母数、Operation状態、
要求別の機械可読試験証拠とハッシュを照合する。報告JSONの自己申告だけでは合格にせず、
受入runnerが当該buildで承認済みharnessを再実行した結果を別経路で照合する。
受入harnessが未登録の要求は未完了のままとする。カタログ収録は実装達成率に加算しない。
Standalone受入には、これに加えて全パッケージ照合、300 intent、30以上のworkflow、
host/protocol/build/robustnessの各受入証拠が必要。個別milestoneと完成を区別する。

## 技術基準

- CGAL: 6.2.1公式release配布物。取得物のchecksum、実コンパイル時のheader version、
  dependency/compiler/source provenanceを記録する。旧vcpkg版の内部build marker
  `6.2.1-I-900` はtagからのbranch-build packagingに由来し、公式release baselineとは別に記録する。
- MCP SDK: 2.3.0採用。原本の2.2.0指定を変更せず、互換試験で差異を追跡する。
- Python: 3.12を基準、実PCの3.13でも検証する。
- C++: C++17以上。Windows/VS2022のclean buildと実PCのVS2026を別々に検証する。
- Registry正本: JSON、検索: SQLite FTS5/日英alias/trigram/関連Operation graph。
  外部embeddingサービスを必須にしない。

## 移行と公開面

新しい`cgal_mcp.master`を旧v0.1の外側に並設し、データ領域と起動経路を分ける。
既設sidecarを維持し、Masterの独立受入前にStellaCAD依存をcoreへ入れない。
新規entrypointは`cgal-master-mcp`。旧`cgal-mcp`と既存公開工具は互換経路として残す。

公開工具は8基本＋独立利用に必要な4補助の固定12工具:

| 公開名 | 用途 |
|---|---|
| cgal_capabilities_search | 条件付き能力検索 |
| cgal_capabilities_describe | 個別Operation schemaと前提/検証/出典 |
| cgal_plan | 型付きDAGの構築 |
| cgal_execute | 登録Operationまたは保存Planの実行 |
| cgal_validate | 独立検証 |
| cgal_artifact_inspect | 型/単位/hash/provenance/検査結果 |
| cgal_docs_search | 版固定docs/source/examples検索 |
| cgal_system_health | 実版/handler/依存/coverage/worker状態 |
| cgal_artifact_import | 原本を保持した管理データへの取込み |
| cgal_artifact_export | 新規派生ファイルの排他的書出し |
| cgal_job_status | 永続job状態・計算/検証結果 |
| cgal_job_cancel | job中止とworker終了 |

Operation IDはdotted形式、公開工具はunderscore形式とする。
Operation、policy、validator、packageを別entityとして扱う。
`CATALOGED`、`IMPLEMENTED`、`VALIDATED`、`BLOCKED`等を区別し、
Registry記録と実worker manifestが一致しない処理は実行しない。

## 最初の実計算の受入

`PointSet3 → hull.convex_3 → TriangleSurfaceMesh`を汎用経路で実行し、
`hull.validate.convex_enclosure`をDAGへ必須挿入する。
validatorは閉鎖性、三角形、向き、正体積、凸性、入力点の包含を確認する。
共面/不十分な点集合は前提不成立として返し、勝手に別型へ変更しない。
登録・単位・input hash・Plan・job・provenanceを再起動後も復元する。
この縦切り合格後に旧simplify/Hausdorffを互換adapterへ移行し、Wave A〜Eを拡張する。

すべての形状生成・変更について、計算成功と検証成功を分離する。
失敗/判定不能の候補は隔離し、合格Artifactとして公開しない。
importの構文安全性とOperation固有の健全性前提を分け、修復対象を一律拒否しない。

## 資源・運用

同時実行2、workerメモリ4GiB、通常120秒、volume生成/再構築600秒を初期値とする。
明示設定で変更可能。未知C++の実行時生成・compileを行わない。
入力/出力の本体はmanaged Artifactを使用し、大きな形状をMCP JSONへ埋め込まない。
再起動で中断したjobは状態を記録し、無条件に再実行しない。

ユーザーのGitHub逐次公開指示に従い、レビュー・ローカル試験を通した区切りで
commit/pushし、CIを確認する。原本MD、秘密情報、個人設計、runtime/dependenciesを
分け、公開用証拠は合成fixtureと集計に限定する。force-pushを行わない。
StellaCADの正式な文書/選択/revision/preview/Undo統合はStandalone受入後の工程。
