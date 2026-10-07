# Master 検索受入評価

この評価は、自然文検索、自然文からの production planner 経路選択、固定パッケージ名の発見、planner の制約拒否を分けて測る。`plan(goal=...)` までは実際に呼ぶが、`execute` は呼ばない。そのため自動実行は常に `UNMEASURED` であり、この評価だけで Standalone 完成とは判定しない。

## コーパス

`tests/fixtures/master/search_intents.json` は、入力データ、処理、期待結果を具体的に記した300件の幾何タスクである。

- 日本語150件、英語150件。
- 原本の80 major requirementsと15 familyをすべて含む。
- eligible と documentation-only の双方を同じ300件の分母に残し、分類件数は生成reportから読む。
- mesh simplification と point-set simplification は、ラベルではなく紐付く requirement ID から数え、合計15件以下とする。
- 同一の定型文、連番付き文、過度に反復する文構造・書き出し、近似重複を拒否する。機械的なゲートだけでは文章品質を保証できないため、独立レビューも行う。
- 各件を原本major requirement、family、`major_capability_inventory.json`のpackage evidenceへ結び付ける。自然文の期待packageは、そのタスクで実際に要求する手法に絞る。

`tests/fixtures/master/package_discovery_cases.json` は別枠のsmoke corpusである。固定126 package IDを1件ずつ完全一致で問い合わせ、natural intent recallへ混ぜない。

## 測定方法

実行可能intentでは、宣言された`input_types`に対応する有効な合成artifactをimmutable storeへimportし、そのartifact IDを`capabilities_search`へ渡す。期待operationが現行registryで非実行でも分母から除外しない。上位3件のどれかが期待operationなら retrieval hit とする。

documentation-only intentでは`docs_search`を呼び、期待packageが結果にあり、全結果が`scope=reference`かつ`executable=false`であることを要求する。

goal routing は、現在のartifact modelで入力意味を忠実に表現できるintentについて production の`plan(goal=...)`を呼ぶ。PointSet3、法線付き点群、TriangleSurfaceMesh、PolygonSoup3の合成fixtureを用い、二入力処理には二つのartifact bindingを渡す。検索候補のoperation schemaから有効なparametersを構成するため、入力不足やparameter不足による後段エラーを安全な拒否の証拠にはしない。

入力型の表現可否は現在のtyped artifact（PointSet2、Polygon2、PolygonWithHoles2、SegmentGraph2、Triangulation2、Triangulation3、RayBatch3を含む）で判定する。ring/hole付きpolygon、拘束線分、ray batch、Delaunay三角形分割はこれらの型で表現できるため`measured`とし、validated operationがあるものは`eligible`としてtop-1ルーティングを、無いものは`unsupported_operation`または`ambiguous_route`によるfail-closedを要求する。
weighted site、周期・球面domain、曲線arrangement・overlay、複数成分polygon set、平面・box・plane stack、幾何primitive、移動segment、混在collection、曲面/3D meshing domain、最適化変数、scalar sample、matrix-search問題など、現行artifact型で表現できないintentだけを`unmeasured_input_model`として明示し、planner拒否の成功件数へ含めない。これらも300件の分母に残り、goal-routing判定を失敗させる。

- eligible intentは期待operationがtop-1で選ばれることを要求する。`ambiguous_route`は明示的な曖昧性として別計上する。
- method指定を追加で求める`route_parameter_missing`、矛盾した指定を示す`route_parameter_conflict`、その他の後段エラーは失敗として記録する。
- documentation-only intentの安全な拒否は`unsupported_adapter/unsupported_operation`または`invalid_input/ambiguous_route`の完全一致だけである。実行可能plan、parameter不足、型・formatエラーは失敗にする。
- reportには各caseの入力型、実際のparameters、候補、選択operation、または例外class/code/reasonを保存する。選択候補が後段のparameter・preconditionエラーを出した場合も、期待外operationならwrong routeとして分類する。

planner hard gateはnatural intentから分離した4件で測る。有効な`PointSet3` artifactを入力し、次のclass/codeが完全一致することを確認する。

| Gate | 期待class | 期待code |
|---|---|---|
| 未対応kernel | `invalid_input` | `kernel_unsupported` |
| 不足dependency | `unmet_precondition` | `unmet_precondition` |
| license policy不適合 | `unmet_precondition` | `unmet_precondition` |
| 未登録operation | `unsupported_adapter` | `unsupported_operation` |

## 判定

- eligible natural intentのtop-3 retrieval recall: 95%以上。
- documentation discovery recall: 95%以上。
- exact package smoke: 126/126。
- goal routing: eligibleで誤operationや未分類エラーがなく、documentation-onlyで実行可能planや未分類エラーがないこと。
- planner hard gate: 4/4。

`passes_search_acceptance`は上記をすべて満たした場合だけtrueになる。`execute`を一度も呼ばないため、結果にかかわらず`passes_acceptance=false`、`overall_standalone_ready=false`を維持する。最新の件数と失敗内容は生成reportを正本とし、この文書へ可変の測定値を転記しない。

## 実行と完全性情報

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_master_search.py --output work/master-search-acceptance.json
.\.venv\Scripts\python.exe -m unittest tests.test_master_search_acceptance
```

reportはcorpus、package smoke、generator、test source、operation registry、package catalog、major requirements、inventoryのSHA-256を記録する。また、言語別・family別retrieval、全300件のrouting分類と実際に呼んだplanner件数、4 planner gates、126 package smoke、自動実行を呼ばなかった事実を含む。reportは`work/`の生成物であり、native workerの幾何計算、MCP transport、実行結果の正しさを証明しない。

## Wave C 後の測定状況（2026-10-08、report再生成値）

- `unmeasured_input_model`: 104件 → 64件。40件を再分類した。
- 再分類の内訳: 12件は`eligible`化（ray first hits 4件 -> `spatial.aabb.ray_first_hits`、制約付きDelaunay 4件 -> `triangulation.constrained_2`、polygon特性 4件 -> `polygon.analysis.properties`/`polygon.query.containment`）。28件はvalidated operationが無いためfail-closedを要求する`documentation_only`のまま測定対象化（Voronoi、arrangement、straight skeleton、offset、Minkowski、barycentric、Mesh_2）。
- 残る64件の不足artifact: 幾何primitive/plane/box/plane stack/moving segment（Kernel_23、AABB、clipping、slicing）、weighted site、周期・球面domain、arrangement overlay、複数成分polygon set、曲面・3D meshing domain、QP変数、scalar sample、matrix-search。
- eligible top-3 recall: 89/89 (100%)、documentation discovery: 211/211 (100%)。goal routingは未測定64件のため`passes=false`のまま。
- `execute`は呼ばず、`passes_acceptance=false`、`overall_standalone_ready=false`を維持する。

