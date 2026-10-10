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


## Wave D 後の測定状況（2026-10-08、report再生成値）

- 7.6の20件（面の三角形分割・細分・等方remesh・平滑化最適化・適応remesh）を`documentation_only`から`eligible`へ再分類した。期待Operationは`mesh.triangulate.faces`、`mesh.refine.local`、`mesh.remesh.isotropic`、`mesh.smooth.tangential_relaxation`、`mesh.remesh.adaptive`。非三角形面の入力は実際の入力型である`PolygonSoup3`へ修正した。
- 語彙は幾何概念として追加した（細分、等方、適応サイズ場、長辺分割、フェアリング、メッシュ品質）。穴埋めの一段階としてのrefine／fair、平滑化と併記された最適化・固定特徴辺は独立要求としない。Operation IDが明示する概念を要約中の言及より優先する加点を加えた。
- eligible top-3 recall: 109/109 (100%)、documentation discovery: 191/191 (100%)。eligibleのtop-1は99件、明示的曖昧は10件（従前14件）。誤route・未分類エラーは0。
- `unmeasured_input_model`は64件のまま。goal routingは未測定64件のため`passes=false`、`execute`は呼ばず`passes_acceptance=false`、`overall_standalone_ready=false`を維持する。

## 検索ゲートの実測と判定（2026-10-10、再生成値）

上記のWave C/D記録は、各intentの`expected_execution`ラベルがWave C/D時点のregistryで固定されたままである。その後80/80 requirementsが検証済みOperationに束縛されたため、`documentation_only`の191件には現在は実行可能Operationへ正しくルーティングされるものが多数含まれる。ラベルが古いため、ラベル基準の指標は現在の能力を過小評価する。そこで、ルーターから独立した束縛を正解として全300件を測る第二の測定を追加した。

### 検索再現率（カタログ束縛・全300件）

- 正解は各intentの原本requirementに束縛された検証済みOperation ID（`catalog/major_requirements.json`の`operation_ids`）。ルーターやコーパスのラベルから導出しない。
- 本番`capabilities_search`をlimit 3、artifact絞り込みなしで呼ぶ。top-1は先頭、top-3は上位3件のいずれかが正解Operationであること。
- ベースライン（語彙改善前）: top-1 191/300 (63.67%)、top-3 240/300 (80.00%)。
- 現在: top-1 239/300 (79.67%)、top-3 278/300 (92.67%)。目標95%に未達（不足7件）。
- 分割はrequirement IDのSHA-256を3で割った余りで固定する（`held_out`は余り0）。development 175件はtop-3 169件 (96.57%)、held_out 125件はtop-3 109件 (87.20%)。
- 来歴の宣言: コーパスは固定済みの独立ベンチマークではなく、ルーティング開発と並行して育てた作成済み開発コーパスである。語彙の追加はdevelopmentの失敗のみから導いた幾何概念・二言語名詞であり、Operation IDやクエリ文字列の直書きはない。ただしベースラインの失敗一覧（intent IDと期待Operation）は全分割で閲覧済みのため、held_outは盲検ではなく弱い汎化推定である。
- 事前に報告済みのラベル基準の指標（型付きeligible top-3 107/109、documentation discovery 191/191、package smoke 126/126、planner gate 4/4）は維持した。

### 検索ゲートの判定: 未達（`search_and_retrieval_acceptance`はunmetのまま）

未達の理由は次の通りで、いずれも報告に実数で残す。

1. 全300件のtop-3が92.67%で、95%に届かない（top-1は79.67%）。
2. goal routingが通らない。`unmeasured_input_model`が64件（現行の型付きartifactで表現できない入力）。さらに`documentation_only`ラベルのうち52件が現在は実行可能planに到達し（ラベルの陳腐化。再分類にはこれらの入力型の合成artifactが必要）、7件が別Operationへ誤ルートして後段エラーになる。eligibleでは誤route 2件と未分類エラー2件が残る。
3. `execute`は一度も呼ばない。自動実行は`UNMEASURED`のままである。

`standalone_accepted`は`false`を維持する。未達ゲート4件の一覧は変更しない。ゲートが満たされると評価器は`met_pending_gate_list_update`を返し、一覧と全family evidenceの再生成を要求する。

### 再現と検証

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_master_search.py --output work/master-search-acceptance.json --publish-retrieval-evidence
.\.venv\Scripts\python.exe -m unittest tests.test_master_acceptance.SearchGateEvidenceTests
```

[`evidence/search-retrieval.json`](evidence/search-retrieval.json)は全300件の返却Operationとコーパス、requirement束縛、registry、語彙、ランカー、生成器のSHA-256を記録する。`scripts/master_acceptance.py`の`evaluate_search_gate`は、束縛ハッシュ、各caseの期待Operation、ヒット判定、要約を検証し、本番検索を全件再実行して記録と一致することを確認したうえでゲートを判定する（`standalone_gates`欄）。いずれかの束縛が古い、または記録が改ざんされていればゲートは成立しない。

## 操作側検索フレーズによる汎化改善と盲検再測定（2026-10-11）

盲検セット（`search_blind_set.json`、118件）は、調整済みルーターで top-1 38.14% / top-3 47.46% と、300件コーパスの値を大きく下回っていた。原因は語彙依存の字句ルーターが、レジストリの別名文字列を避けた言い換えに一般化できないことだった。

### 変更（クエリ側ではなく操作側から）

- `cgal_mcp/master/search_data.json`: 全226 Operationについて、各Operation自身のsummary・CGAL文書から、利用者がそのタスクをどう呼ぶかを英語と日本語で簡潔に作文した検索フレーズ（非CGAL用語の言い換えを含む）。検索専用データであり、固定されたレジストリのハッシュ（`operations.json`、policy）には含めない。実行可否、パラメータ、policyには影響しない。`tests/test_master_search_data.py`が全Operationの被覆、日英の両方を含むこと、Operation IDやコーパス文との不一致を検査する。
- `search.py`: IDF重み付きのフレーズ証拠（英語は語幹正規化、日本語は文字bigram）、日英の幾何名詞ブリッジ語彙の拡張。クエリ個別の分岐はない。
- `registry.py` / `runtime.py`: `capabilities_search`だけが発見モード（`discovery=True`）でフレーズ証拠とFTS索引を使い、未被覆概念だけを理由とする候補を最下位へ沈めずに減点付きで順位づけする。計画（`plan(goal=...)`）は従来の保守的な証拠のままで、検索フレーズの影響を受けない。ハードゲート（validator明示意図、パラメータ矛盾）は不変。
- 手順の厳守: 盲検の取りこぼし一覧は閲覧せず、調整にも使っていない。開発用の自作プローブ（言い換え約60件、リポジトリには含めない）だけで仕組みを確認した。

### 実測値（報告再生成値）

| 指標 | 変更前 | 変更後 |
|---|---|---|
| 300件 カタログ束縛 top-1 / top-3 | 261 (87.0%) / 289 (96.33%) | 266 (88.67%) / 294 (98.0%) |
| 盲検118件 top-1 / top-3 | 38.14% / 47.46% | 79.66% / 87.29%（英語 89.83%、日本語 84.75%） |
| 型付きeligible top-3 | 296/300 | 296/300 |
| 実行サンプル | 10/15 | 15/15 |

### 判定: 検索ゲートは未達のまま

盲検 top-3 87.29% は目標95%に届かない。goal routingの未達（曖昧50件ほか）と、15件サンプルを超える自動実行の未測定も残る。基準は緩めていない。

### 盲検セットの汚染と、新しい盲検セットの手順

盲検セットは複数回の測定と、フレーズ作成者がその存在を知っていたことにより、今後の調整に対して汚染済みとみなす。今回の値は「汚染前に一度盲検で測った」参考値であり、受入根拠には再利用しない。新しい盲検セットは次の手順で作る。

1. 作成者は、ルーター・語彙・フレーズ・過去の盲検セットを閲覧していない別のエージェントとする。入力は原本requirementと各Operationの公開説明だけ。
2. 件数は各family 10件以上、日英同数、期待Operationは原本の`operation_ids`に束縛する。言い換えはレジストリの別名やフレーズの文字列を意図的に避ける。
3. 作成後にSHA-256を記録し、リポジトリへ保存してから測定する。測定前にルーター側の変更を凍結し、測定は1回だけ。取りこぼしの閲覧と再調整が必要になった場合、そのセットは開発用へ格下げし、さらに新しい盲検セットを作る。
4. 検索ゲートは、新しい盲検セットで top-3 95%以上を満たした場合にのみ判定する。

### 実行サンプルの失敗原因（10/15 → 15/15）

失敗は検索の誤選択ではなく、評価器の合成入力が選択Operationの前提を満たしていないことだった。`_EXECUTE_OVERRIDES`で選択Operation向けの入力とパラメータだけを差し替えた（三角形限定の修復へ四角形soup、corefineの両オペランドに同一メッシュ、10点以上が必要な再構成へ4点、スキーマ最小値の許容誤差、線形計画ソルバー指定の誤り）。選択されたOperationは変えず、行ごとに差し替えをreportへ記録する。
