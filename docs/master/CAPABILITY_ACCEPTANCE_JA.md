# 原本の主要能力を実計算で判定する

原本7.1〜7.15の15分野・80要求を固定母数とし、実計算の再試験へ結び付けた要求は
80/80です（7.1カーネル5、7.7軽量化6、7.6メッシュ再生成5、7.3解析8、7.4修復6、7.5 Boolean・clip・split・corefine・slicer 5、7.9点群6、7.2空間問合せ5、7.11三角形分割（periodic・球面を含む）5、7.12多角形7、7.13凸包・alpha shape・alpha wrap・bounding volume・重心座標5、7.14 Mesh_2・Surface_mesher・Mesh_3・Mesh_3 criteria 4、7.15 LP/QP・補間・VSA近似・sorted matrix search 4、7.10曲面再構成3（Poisson・advancing front等・alpha wrap）、7.8 SDF区分化・細分割・最短経路・近似凸分解・骨格抽出・パラメータ化6）。
点群処理の個別Operationや凸包の基盤受入を、未完了の要求全体の達成へ加算しません。
結合済みの要求は、各要求の説明に列挙された全variantと台帳の全subcapability symbolを、
検証済みOperationと必須validatorを通る再試験ケースで網羅した場合だけ結び付けています。
一部だけ満たす要求は未結合のまま、不足を[主要能力台帳](MAJOR_INVENTORY_JA.md)へ記録します。

対応する正式workerで、全familyの固定harnessを実行してから要求判定します。

```powershell
.venv/Scripts/python.exe scripts/replay_master_capabilities.py `
  --worker build-master/Release/cgal-master-worker.exe `
  --work-dir work/master-capability-local
```

`--work-dir`は`family-<id>.json`をfamilyごとに書きます。`--family 7.4 --output work/x.json`で
単一familyだけを再試験できます。両方を省くと公開snapshot（`docs/master/evidence/`）を
更新しますが、catalogに承認済みのhashと一致しない場合は書き込む前に失敗します。

## family再試験の仕組み

7.7は従来の専用harness・契約をそのまま使います。7.2/7.3/7.4/7.5/7.6/7.9/7.11/7.12/7.13/7.14は
`scripts/master_replay_families.py`にデータとして宣言し、共通harness
`tests/master_family_replay_cases.py`で実行します。各familyは、固定fixture（sha256付き）、
Operation・parameter、behaviour assertion（閉じた比較演算子と選択子のみ）、同一入力の
比較ペア、拒否されるべきnegative controlを持ちます。validator要求はregistryの
`validation.bindings`から導出し、要求したreport check・field・最小値を検査します。
判定側（`scripts/master_acceptance.py`）は契約hash・契約source hash・harness記録・
ケース集合・assertion・validator連鎖・negative controlを再計算して照合し、
契約に無いfamily、未結合要求、他familyのreportを拒否します。

7.7のreportは内容を変えず、生成source変更に伴う`generator_source_sha256`だけを再生成しました。
7.8（surface reconstruction）と7.13（hull/alpha/wrap等）は、検証済みOperationが要求全体を
満たさないためfamilyを作っていません。

Linuxではworkerを`build-master/cgal-master-worker`へ置き換えます。

7.9.05（OpenGR登録）と7.10.02（PolyFitのSCIP）は任意依存です。これらを含むworkerでのみ再試験でき、含まないworkerでは当該Operationが`OPTIONAL_DEPENDENCY_NOT_BUILT`を返すため、80/80は両依存を含むbuildでの値です。版・license・取得元・sha256は[第三者依存](THIRD_PARTY_DEPENDENCIES_JA.md)に記録しています。
CIの再試験はOpenGR・SCIPを含まないworkerで走るため`--skip-unavailable-optional`で7.9・7.10を明示的に除外し、減った件数を報告します（CIは80/80を主張しません）。
7.9.05は`CGAL::OpenGR::register_point_sets`・`compute_registration_transformation`（OpenGR版）のみを対象とします。libpointmatcher版（`CGAL::pointmatcher::*`）は未導入で対象外です（台帳の必須symbolはOpenGRのヘッダを指し、pointmatcherは例題の言及のみ）。
7.10.01 `poisson_delaunay`はCGAL 6.2.1の制約（半径の2乗の取り違え）でR=10の球の約41%が未被覆になるため、R=2 mmの球で被覆95%以上を固定し、R=10の部分結果とトーラスは対象外（負例）です。
7.9.05の回転検査は直交性・行列式を1e-9の許容で確認します（厳密な有理数ではありません）。点の像は2進浮動小数の座標に対する厳密有理数演算で検査します。
checked-in reportを読むだけの`scripts/master_acceptance.py`は、再計算による確認が
ないため未完了を返します。JSON内の`pass`、hash、自己申告の完成表示だけを承認しません。
公開snapshotは当該buildの履歴資料です。CIはその環境で再試験し、別reportを保存します。

7.7の試験は7 cost/placement、5 stop predicate、constraint、bounded distance、normal-change、
Polyhedral Envelopeを含みます。同一入力でfilterの有無・厳しさを比較し、
stop条件は出力の計測値で確認します。22の合格ケースと44のvalidator実行について、
request・response・入力・出力・validator report・source・workerのhashを照合します。
FastEnvelopeの外部依存は別の未対応policyとして残っています。

bounded normal changeは、実行時の三角関数や対称形状のcost順序に依存しない固定OFFを
使います。唯一の最短辺をmidpointへcollapseすると、残存面の変更前後の法線内積が
OFFの十進token領域で厳密に`-1/2500`となります。さらに実際にworkerが保持する
IEEE-754 binary64座標を有理数へ戻して検証し、同じ辺が唯一のstop対象であり、法線内積が
`-3/10000`未満の負値になることもhash固定します。filter無効のcontrolは3辺を削除しますが、厳格validatorが
`OPEN_SURFACE_WINDING_CHANGED`で拒否します。このcandidateは合格geometryへ数えません。
同じ入力・kernel・parameterで`bounded_normal_change`だけを有効にしたケースはcollapseを
拒否して0辺削除となり、integrityとHausdorffの両validatorを通過します。reportはcontrolの
source/candidate/error、解析値、parameter差分を`negative_control_proofs`へhash付きで保存し、
合格した`operation_results`とは分離します。

受入runnerは登録済みの正式native workerと固定harnessを実行します。
任意の試験command、JSONから指定された未知のコード、test stubで要求を合格にしません。
実行するPython source自体の任意改変・monkeypatchを防ぐセキュリティ境界ではありません。
原本・registry・試験sourceの一致と、実行後の内容不変も検査します。

7.3.06の`mesh.distance.symmetric_hausdorff`は検証が必須で、独立validatorの面数上限（400面）に合わせて
`bounded_input`（最大400面）を前提条件に宣言しました。400面を超える入力は計算前にregistryが
`PRECONDITION_FAILED`で拒否し、対応範囲は400面以下のメッシュに限定されます。
この拒否は負例`distance-symmetric-over-face-limit-refused-up-front`で固定しています。

全80要求、300 intent、30以上のworkflow、全host/build/protocol、故障・資源・性能の
受入は未完了です。今回のreportも`standalone_accepted: false`を保持します。

## 実クライアント制約（71k面スキャン）への対応

StellaCADが使う約71k面のスキャンメッシュ（個人データのためrepositoryには含めない）で見つかった制約のうち、
次を対応しました。確認には、約70.9k面・半径60 mmのノイズ付き球に28個の穴（1面欠け25、
6/24/80面を欠いた穴3）を開けた合成メッシュを使い、合成メッシュ自体はコミットしていません。

- 速度: `mesh_metrics`の非多様体頂点数を、頂点ごとの`is_non_manifold_vertex`走査から
  一括の`PMP::non_manifold_vertices`へ置換しました。`fill_holes`は参考値（情報用、1回計測）で
  6.1 s → 0.5 s。旧workerと新workerで、repair/inspect/analysis 9 Operation × 既存fixture 34件
  （計306組）の出力とresponseが全て一致することを確認しました。
- stack overflow: `mesh.validate.simplification_integrity`は約1万面超でCGAL内部の再帰が
  Windows既定1 MiB stackを使い切り`0xC00000FD`で落ちていました。workerへ`/STACK:268435456`を
  付けて解消し、39,600面の閉メッシュで旧workerは異常終了、新workerは0.4 sで`pass`となることを
  確認しました。回帰試験は`tests/test_master_client_limits.py`（20,000面以上の閉球）です。
- 選択的な穴埋め: 新Operation `mesh.analysis.boundary_cycles`（安定したhole_id、辺数、周長、
  面積の目安、重心、bbox、周長順。合成メッシュで0.1 s）と、`mesh.repair.fill_holes`・
  `fill_holes_refine_fair`の新parameter `hole_ids`・`max_hole_perimeter`・`max_hole_area`を追加しました。
  指定なしの動作は従来通りです。選ばれなかった穴は変更されず、validatorがCGALと独立な辺写像で
  「未選択の穴が不変」「選択した穴が閉じた」を検証します。存在しないidは`HOLE_ID_NOT_FOUND`で拒否します。
  訂正: この時点の版は、別のメッシュで一覧したidでも同じ頂点番号の境界があれば別の穴を黙って埋め得ました
  （「古いidは拒否」は過大な記述でした）。後述の「追補: hole_idのメッシュ束縛」で修正しています。
  Registry説明とAI guideに「先に一覧、次にユーザーへ確認、最後にIDで指定して埋める」を記載しました。
  registryは228 Operation、catalog_revisionは`-6`です。MCPのtool面は変えていません。

未対応: 項目1（`mesh.distance.symmetric_hausdorff`の400面上限）と項目2（simplificationの
自己交差に対する再試行）は今回も未対応です。上記の時間は情報用の1回計測で、受入根拠ではありません。
`standalone_accepted`は引き続きfalseです。

## 実クライアント制約 項目2: simplificationの自己交差（`foldover_policy`）

`mesh.simplify.edge_collapse`の新parameter `foldover_policy`（`reject`が既定で従来動作、
`protect_and_retry`）、`max_retry_rounds`（1〜8、既定4）、`accept_target_shortfall`（既定false）を追加しました。
MCPのtool面は変えていません（既存Operationのparameterのみ）。`protect_and_retry`はworker内で
collapse結果を`PMP::self_intersections`で走査し、交差面の重心の周囲（元メッシュの平均辺長の3倍）にある
元の辺をconstrainedにして元メッシュから再実行します（中心は試行をまたいで蓄積）。独立validator
（integrity、Hausdorff）は必須のままで、検証に落ちた結果は公開されません。目標面数に届かない場合は、
達成できた最良の面数・辺数を載せた型付き拒否（`TARGET_NOT_REACHABLE_WITHOUT_SELF_INTERSECTION`）、
試行を使い切っても交差が残る場合は`SELF_INTERSECTION_UNRESOLVED`で拒否します。
`accept_target_shortfall=true`なら、検証済みの交差なし結果を目標未達（`metrics.target_reached=false`）として公開します。
metricsに`retry_attempts`、`protected_edge_count`、`attempt_log`（試行ごとの面数と交差ペア数）を出します。
registryの`catalog_revision`は`-7`（Operation数は228のまま）です。

合成メッシュでの前後（71,060面、半径20 mmのUV球、半径方向ノイズ±2%、seed 3、LindstromTurk、
目標35,600面。個人データは使っていません。欠陥は球の極付近に出るので、実スキャンの欠陥分布とは異なります）:

| | 面数 | 交差ペア | integrity validator |
|---|---|---|---|
| 変更前（`reject`） | 35,598 | 9 | `SELF_INTERSECTION`で拒否（結果なし） |
| 変更後（`protect_and_retry`） | 35,598 | 0 | pass（2試行、保護辺505、約3 s、情報用1回計測） |

ノイズ±0.4%は3試行・保護辺4,147、±1%は5試行・保護辺4,282でいずれも35,598面・交差0でした。
試行の途中で交差ペアが9→28→0や9→3→4→…→0と一時的に増えることがあります（保護で貪欲な順序が変わるため）。
保護半径を試行ごとに広げる案は、7試行目以降に全辺を保護して71,060面のまま目標に届かなくなったため
採用せず、固定半径＋中心の蓄積にしました。

Hausdorff: 71k面・35k面は`mesh.distance.*`の面数上限（400面の厳密validator、Wave Dの標本化measureも
面数上限あり）に当たり、35k面の結果の偏差は今回も測れていません（項目1は未対応のまま、上限は触っていません）。
replay用の小さい合成メッシュ（352面、ノイズ±10%、半径60 mm）では、plainのcollapse（198面）が
3ペア交差してvalidatorに拒否され、`protect_and_retry`は2試行・保護辺185で198面・交差0となり、
必須のHausdorff validatorが6.24 mm（許容15 mm）でpassしました。目標が厳しすぎると保護後の結果が
大きく歪む例も確認しています（別の合成球で134面、Hausdorff 79 mm。許容を大きくしない限りvalidatorが落とします）。
replay: family 7.3（major.7.3.07に`mesh.simplify.edge_collapse`を追加）に陽性1件、陰性対照5件
（交差したcollapse結果をintegrity validatorが拒否、目標未達の拒否、再試行枯渇の拒否、
policy無しの`max_retry_rounds`の拒否、未知policyの拒否）。simplificationのvalidatorはレポートを
入力に取らないため「改竄レポート拒否」は該当せず、改竄相当として「交差した候補の拒否」で代えています。
`standalone_accepted`は引き続きfalseです。項目1はこの時点で未対応でした（後述の項目1の節で対応）。

parameter名を`self_intersection_policy`ではなく`foldover_policy`としたのは、Operation検索が
parameter名も索引にするため、`self_intersection`の概念が`mesh.simplify.edge_collapse`にも一致して
「自己交差の組を列挙する」という問い合わせが`mesh.analysis.self_intersections`へ一意に
ルーティングされなくなる（既存の検索試験で検出）ためです。

## 実クライアント制約 項目1: Hausdorffの400面上限（`validation_mode=certified_bvh`）

400面上限の原因はCGALではなく独立validator（`mesh.validate.hausdorff_symmetric_report`）でした。
全頂点×全三角形のGMP有理数距離と総当たりのLipschitz bracketなので、71k×35k面では外挿で20時間以上かかります。
対策として、既存Operationに任意parameterを追加しました（新Operationなし、MCPのtool面は不変）:
`mesh.distance.symmetric_hausdorff`と`mesh.validate.hausdorff_symmetric_report`の`validation_mode`
（`bruteforce`、または省略で従来どおり／`certified_bvh`）、`mesh.simplify.edge_collapse`の
`hausdorff_validation_mode`（必須のHausdorff検証stepへ`validation_mode`として渡す）。registryの
`bounded_input`は`maximum_faces=400`のままで、新キー`relaxed_by_parameter`により
`validation_mode=certified_bvh`のstepだけ2,000,000面・1 GiBまで許します（planner・runtimeとも
実際のparameterで判定）。CGALの計算（`bounded_error_symmetric_Hausdorff_distance`）はどちらのモードでも同じで、
変わるのはvalidatorだけです。省略時の経路（≤400面の総当たり厳密validator）は変更していません。
`catalog_revision`は`-8`（Operation数228のまま）。

`certified_bvh`のvalidatorが保証する内容（CGALヘッダなし、自前実装）:
- 下限: 両メッシュの頂点と細分した部分三角形の中点について、相手メッシュへの実距離を、自前の三角形BVHの
  最近傍branch-and-bound（箱の距離が現在の最良値以上のときだけ枝刈り）で求めた最大値。
- 上限: 部分三角形Tと相手の任意の三角形Sについて、d(・,S)はT上で凸なので sup_T d(p,B) ≤ min_S max_i d(v_i,S)。
  これをBVHのbranch-and-bound（箱の下界 max_i d(v_i,箱)）で全Sについて厳密に評価し、Lipschitz上界も併用します。
  上界が「下限+幅」を超える三角形を4分割し続け、閉じた三角形の上界の最大値を上限とします。
  幅は min(0.5%×対角線, error_bound/2)。すなわち 下限 ≤ 厳密な対称Hausdorff距離 ≤ 上限、上限−下限 ≤ 幅。
- 丸め: 距離はbinary64で評価し、丸め誤差は宣言マージン ε=1e-9×(1+対角線)（120 mm級で約1.2e-7 mm）で覆います。
  これは区間演算による形式的証明ではなく、数十演算分の丸め誤差（相対1e-15程度）に対する大きめの宣言値です。
  制約: εは座標の大きさに比例しないため、原点から対角線の約1e6倍より遠くへ平行移動したメッシュでは
  丸め誤差を覆う保証がありません（その場合は先に原点付近へ移動してください）。
- 独立検査: BVH最近傍の結果を、証拠点2点と頂点の等間隔標本（計約68点）について全三角形の総当たりと照合し、
  証拠点の距離は全三角形（浮動小数の最小値+ε以内のもの）でGMP有理数により再計算して一致を確認します。
- 判定: 報告値がbracket±error_bound±εの外なら`DISTANCE_OUT_OF_BRACKET`で拒否。さらに独立の判定
  `certified_verdict`（上限+ε ≤ tolerance ならpass、下限−ε > tolerance ならfail、それ以外indeterminate）を出し、
  報告のverdictがこれと矛盾すれば`CERTIFICATE_CONTRADICTION`で拒否します（bracket検査を通る改竄では
  到達しない多重防御）。validatorレポートに`certified_lower_bound`、`certified_upper_bound`、`certified_verdict`、
  `certified_within_tolerance`、細分ノード数、距離評価回数、照合点数、GMP再計算値を出します。
  制約: producerの`pass`はbracketが`fail`を示さない限り受理されます。`certified_verdict`が
  `indeterminate`のとき、厳密な距離はtoleranceを最大でerror_bound/2（＋ε）上回り得ます。合格を保証として
  扱う場合は、validatorレポートの`certified_within_tolerance=true`を確認してください。
- 信頼の境界: 細分の原理（部分三角形での凸距離上界）は、CGALのbounded-error実装も使う標準的な上界です。
  validatorは実装（BVH、距離計算、細分、照合）がCGALから独立していますが、数学的な手法まで別物ではありません。
  手法の違う検査は、総当たりとの照合（標本のみ）とGMPでの証拠点再計算（2点のみ）に限られます。

合成メッシュでの前後（個人データ不使用。半径60 mmのUV球、半径方向ノイズ±0.05%（±0.03 mm）、seed 11、
LindstromTurk＋`foldover_policy=protect_and_retry`で半分の面数へ。tolerance 0.1 mm、error_bound 0.01 mm。
時間はworker 1回分の実測で、他の負荷により変動します。情報用で、受入根拠ではありません）:

| ペア | 変更前 | 変更後: CGAL producer | 変更後: certified validator | 保証されたbracket |
|---|---|---|---|---|
| 71,200面 vs 35,598面 | 400面上限で拒否（総当たりなら外挿20時間以上） | 15〜23 s、ピーク約0.5 GiB | 9〜10 s、ピーク35 MiB、細分6.8M節点 | [0.06688, 0.07186] mm → pass（≤0.1 mm） |
| 139,440面 vs 69,718面 | 同上 | 27〜42 s、ピーク約0.75 GiB | 13〜16 s、ピーク63 MiB、細分10.0M節点 | [0.05362, 0.05862] mm → pass |

CGALの推定値（0.0669 mm、0.0436 mm、いずれも±0.01 mm）はbracketと整合しています。
`MasterRuntime`経由の71k面simplification（`hausdorff_validation_mode=certified_bvh`）は、2つの必須validatorを
通って`succeeded/passed`になります。指定しない場合は従来どおりHausdorff stepで`requires faces<=400`により失敗します。
厳密値そのものは求めていません（保証するのは幅≤min(0.5%対角線, error_bound/2)の区間と丸めマージンまで）。
節点予算6,000万・深さ48を超えると`BRACKET_NOT_CONVERGED`で拒否します（例: error_boundを極端に小さくした場合）。
validatorより時間がかかるのは現在CGAL側（error_bound 0.01 mm）です。

replay: family 7.3（major.7.3.06）に、1,152面の平面グリッドと中心頂点を0.5 mm持ち上げたグリッド
（厳密な距離0.5 mm）の陽性2件（tolerance 0.1 mmでfail、0.6 mmでpass。validatorはどちらも報告を確認）、
陰性対照3件（スパイクを隠した改竄レポートを`DISTANCE_OUT_OF_BRACKET`で拒否、`validation_mode`なしの
validatorは400面上限で拒否、未知の`validation_mode`の拒否）を追加しました。単体試験では、tolerance 0.49 mmで
CGALの報告がindeterminate（0.5±0.01）のときに、より狭いcertified bracketがfailを保証することと、
≤400面のペアで両モードのbracketがどちらも厳密値0.5 mmを含むことも確認しています。
simplification計画の「達成偏差の報告」への連動は、必須validatorのレポート（上記bracket）で代え、
追加実装はしていません。`standalone_accepted`は引き続きfalseです。

## 追補: hole_idのメッシュ束縛（レビュー指摘への修正）

hole_idは「境界上の最小の頂点番号」なので、メッシュXで一覧したidをメッシュYに渡すと、Yに同じ番号の境界が
あれば別の穴を黙って埋め得ました。修正内容:

- `mesh.analysis.boundary_cycles`の`results.source_mesh_sha256`に入力メッシュの内容SHA-256を載せ、
  `id_rule`にもidがそのメッシュに限り有効であることを明記しました。独立validatorも同じ値を再計算するため、
  この値を書き換えたレポートは`REPORT_SEMANTICS_MISMATCH`で拒否されます。
- `fill_holes`・`fill_holes_refine_fair`は`hole_ids`を使うとき`source_mesh_sha256`が必須です
  （なければ`HOLE_IDS_SOURCE_REQUIRED`、`hole_ids`なしで指定すると`HOLE_SELECTION_CONFLICT`）。
  入力メッシュの検証済みSHA-256と違えば`HOLE_IDS_SOURCE_MISMATCH`（PRECONDITION_FAILED）で拒否し、何も公開しません。
- validatorにも束縛し、別メッシュのSHA-256が渡された場合は`HOLE_IDS_SOURCE_MISMATCH`（VALIDATION_FAILED）で
  拒否します。合格時はchecksに`hole_ids_bound_to_source_sha256`が付きます。
- 穴ごとの指紋（縁の頂点座標のハッシュ）は追加していません。メッシュ全体のSHA-256が一致すれば頂点番号と
  境界はバイト単位で同じなので、穴ごとの指紋は追加の保証になりません。
- replay（family 7.4）: 既存のid指定ケースに`source_mesh_sha256`を追加し、負の対照として
  別メッシュのid（穴を全部閉じた同じ頂点番号のメッシュに番号49を指定、fill/fairの2件）、SHA-256なしのid、
  validatorへの別メッシュSHA-256、`source_mesh_sha256`を書き換えたboundary_cyclesレポートの拒否を追加しました。
- guideとregistry説明に「一覧レポートの`source_mesh_sha256`と一緒にidを渡す」ことを追記しました。
  MCPのtool面は変えていません。

## プロ用途の制約 第1区切り: 一般形状のBooleanと厳密validatorの面数上限（2026-11-13）

この節の作業はLinux（gcc 13.3、公式CGAL 6.2.1、OpenGR・SCIPなし）で行いました。時間は情報用の1回計測で、
受入根拠ではありません。`docs/master/evidence/`の各レポートは今回再生成していません（後述）。
`standalone_accepted`は引き続きfalseです。

### 見つかった制約

- `mesh.boolean.union`・`intersection`・`difference`、`mesh.clip.plane`、`mesh.split.plane`、`mesh.corefine`、
  `mesh.autorefine`は、結果の全座標が厳密にbinary64で表せる場合だけ結果を公開します。軸に揃った2進有理数の
  入力（既存fixtureの立方体）では成り立ちますが、一般的な位置のメッシュではほぼ成り立ちません。
  半径10 mmのUV球（360面）と(7.3, 1.1, 0.4) mmずらした同じ球の和は`OUTPUT_BINARY64_LOSS`、
  同じ球の平面クリップは`OUTPUT_NOT_REPRESENTABLE`で拒否されます。面数上限より前にある制約です。
- 厳密validator（batch 2のclip/split/corefine/autorefine/features、batch 5のdo_intersect/polylines）は
  全三角形ペアの総当たりで、上限が600面・200面でした。

### 対応1: `mesh.boolean.rounded`（新Operation、status `IMPLEMENTED`）

- parameter `operation`: `union`・`intersection`・`difference`。入力条件は厳密Booleanと同じ
  （閉じた外向きの三角形メッシュ、自己交差なし、最大200,000頂点・400,000面）。
- producerは厳密Booleanと同じEPECKのcorefinementを実行し、各座標を隣接するbinary64値へ丸めます。
  丸めた結果が健全な体積境界でなくなった場合（退化面、自己交差など）は
  `NUMERIC_FAILURE/ROUNDING_INVALIDATED_RESULT`で拒否し、何も公開しません。
- 必須validator `mesh.validate.boolean_rounded`は、厳密Booleanを再計算し、候補を許容誤差つきで比較します:
  候補の位相・閉性・向き・自己交差なし、空/非空の一致、頂点数・面数の一致、
  体積差が「許容誤差×参照面積×1.01」以内、候補の全頂点が参照曲面から許容誤差以内、
  参照の全頂点が候補曲面から許容誤差以内。距離は、binary64の探索木で選んだ証人三角形への
  厳密な有理数距離で判定します（探索は証人の選択だけに使い、合否は厳密比較）。
- 許容誤差は「両入力の最大絶対座標を超える最小の2の冪 × 2^-40」です（上の球の例で2.9e-11 mm）。
  validatorが保証するのは厳密な結果への近さで、集合としての厳密一致ではありません。
  CGALを使わない独立オラクルではなく、同じcorefinementの再計算との比較です（厳密Booleanのvalidatorと同じ方式）。
- 厳密Booleanの`OUTPUT_BINARY64_LOSS`は`suggested_operations`に`mesh.boolean.rounded`を返します。
- 確認（`tests/test_master_boolean_rounded.py`）: 一般位置の球2つで3演算がvalidatorに合格、
  CGALと独立な包除原理（|A∪B|+|A∩B|=|A|+|B|、|A−B|=|A|−|A∩B|、差1e-8 mm³以内）、
  演算の取り違え・入力をそのまま候補にした場合・1頂点を1e-3/1e-6/1e-9 mm動かした改竄の拒否、
  厳密に表せる立方体では厳密体積12と一致、交わらない入力の積が空、開いた入力の拒否。
  1e-13 mmの移動は許容誤差未満なので合格します（契約どおり）。
- 情報用の計測（1回）: 球2つ（各101,760面）の和が14.8 s、validatorが18.6 s。最大頂点偏差は2e-15 mm。
- statusを`VALIDATED`にしていない理由: 原本要求へのreplay束縛と独立レビューが未実施のためです。

### 対応2: 厳密validatorの面数上限（600面・200面 → 200,000面）

- 対象: `mesh.features.detect`、`mesh.clip.plane`、`mesh.split.plane`、`mesh.corefine`、`mesh.autorefine`
  （600 → 200,000面、出力4,000 → 1,000,000面）、`mesh.intersections.do_intersect`、
  `mesh.intersections.polylines`（200 → 200,000面）。
- validatorの判定（GMP有理数の厳密計算）は変えていません。厳密判定へ渡すペアの選択を、総当たりから
  保守的な箱階層（`worker/master/batch2/b2_broadphase.h`、CGALヘッダなし）へ替えました。箱はbinary64入力座標の
  厳密なmin/max（有理数の点は2 ulp外側へ拡張）で、閉じた箱が交わらないペアだけを省きます。
  交わらない箱の図形は点を共有しないので、判定結果は総当たりと同じです。
- `mesh.intersections.polylines`のproducerにあった全ペアの共面チェックも同じ箱階層で絞っています。
- 確認: 既存の`tests/master_batch2_cases.py`と`tests/master_batch5_cases.py`（陽性と改竄の陰性対照）が
  変更後のworkerで全て合格。6,912面の格子立方体で6 Operationとvalidatorが合格し、
  切っていない立方体をsplit結果とした場合と、clip結果から1面を除いた場合はvalidatorが拒否、
  202,800面は`FACE_LIMIT_EXCEEDED`で拒否。
- 情報用の計測（1回、199,692面の格子立方体）: validatorはclip 4.7 s、split 6.0 s、corefine 7.1 s、
  features 1.7 s、do_intersect 1.9 s、polylines 2.1 s。切断帯の小さい入力なので、交差の多い入力では長くなります。
- `tests/master_batch2_cases.py`の1件（138行目）は、変更前のworkerでも`INPUT_TYPE_MISMATCH`で失敗していました
  （validatorの入力型が`TriangleSurfaceMesh`になった後もテストが`PolygonSoup3`を渡していた）。型を合わせました。

### 未対応・注意

- `mesh.clip.plane`・`mesh.split.plane`・`mesh.corefine`・`mesh.autorefine`は、面数上限を上げましたが、
  厳密に表せる出力だけを公開する契約のままです。一般位置の入力では今も拒否されます（丸め版は未実装）。
- 距離系（400面）、細分（2,000面）、骨格（3,000面）、パラメータ化（2,000面）、SDF（1,500面）、
  凸分解（2,000面）、最短経路（64面）、点群間隔（400点）、最小円・球（64点・32点）の上限は変えていません。
- registryは230 Operation（VALIDATED 228、IMPLEMENTED 2）、`catalog_revision`は`-9`です。
  `docs/master/evidence/`の各レポートは旧revision（`-8`）と別のworker（Windows）に束縛されたままで、
  今回は再生成していません。registryに束縛する受入gateの判定は、再生成するまで古い証拠を指します。
- 検索: `mesh.boolean.rounded`はregistryで`fallback_for`（厳密Boolean 3件）を宣言します。検索は、別名かidが
  一致しない限りこのOperationを自動ルートの候補にせず、厳密Booleanの後ろに並べます
  （「重なる体積だけ残す」などの一般の問い合わせが曖昧にならないようにするため）。
  `search_data.json`に2 Operationの語句を追加し、package台帳の`Polygon_mesh_processing`の
  Operation数（total 50、implemented 2）を更新しました。
- 既存テストの不整合（今回の変更と無関係）: `tests/master_wave_a_repair_cases.py`は、穴の選択を使うと
  validatorが追加するchecks（`selected_holes_closed`・`unselected_holes_untouched`）を想定しておらず失敗していたため、
  必須checksを含むことの確認に直しました。`tests/master_wave_b_cases.py`は
  `validator_parameter_bindings`の期待値が古く、171行目で失敗します（未修正）。
- 証拠の再生成が必要（未実施、merge前の残作業）: `docs/master/evidence/`の各レポートはregistry全体に
  束縛されているため、registryを変更した今回のcommitの時点で古くなっています。
  `tests.test_master_acceptance`は76件中、失敗81（subTestを含む）・エラー1です。内訳:
  `test_published_family_reports_fail_only_for_missing_replay`の74要求（registry変更が原因。変更前は合格）、
  変更前のHEADでもこのLinux環境で失敗していた4件（検索証拠の束縛3件、workflow gate 1件）、
  workerが必要で変更前はskipされていた証拠束縛の試験3件とエラー1件
  （性能証拠の束縛、geometry cache証拠、runtimeでの証拠再現、障害封じ込めの再実行。
  Windowsで生成した証拠とLinux workerの差か今回の変更かは、ここでは切り分けていません）。
  全分野の再生成にはOpenGR・SCIPを組み込んだworkerが必要で（7.9・7.10）、このLinux環境にはありません。
  再生成は基準環境（Windows、OpenGR・SCIPあり）で行ってください。
- `docs/master/evidence/first-contact.json`もguideのhashに束縛されており、guideを再生成した今回の時点で古く
  なっています（`tests.test_master_guide`の`test_evidence_bound_to_current_guide_and_informational`が失敗）。
  同じ理由で再生成していません。同テストの`test_sample_examples_execute_and_validate`は、このLinux workerに
  OpenGRがないため`pointset.registration.compute_transformation`の例で失敗します（環境要因）。
- family 7.3のreplayケース`intersect-polylines-shifted-cubes`は、このLinux/gcc 13.3のworkerでは
  polylineの点の並び順が期待値と違い失敗します（points.3とpoints.7）。`b5_intersect_ops.cpp`を
  変更前に戻したworkerでも同じ失敗になることを確認しました（今回の変更が原因ではなく、
  `intersection_polylines`の出力順の環境差）。期待値を順序に依存しない形へ直す必要があります（未修正）。
- 今回の変更後に合格を確認したもの（Linux worker）: `tests.test_master_boolean_rounded`（12件）、
  `tests.test_master_search_*`・`test_master_goal_routing`・`test_master_package_harvest`、
  workerケースのbatch 2〜6、Wave A（simplify・mesh・Boolean・repair）、Wave C・D・E、query、kernel、
  optimization、reconstruction、worker cases。

### 追補: Linuxでの証拠再生成の準備（2026-11-13、未完了）

ユーザーの判断により、証拠の再生成をこのLinux環境で行う準備を進めました。再生成そのものは未完了で、
`docs/master/evidence/`はまだ更新していません。

- OpenGR `abfe0f4d`（v2023.11）、SoPlex `13e2ab24`（v8.0.3）、SCIP `d409edf9`（v10.0.3）をtag指定のgit cloneで取得し、
  `THIRD_PARTY_DEPENDENCIES_JA.md`に記録されたcommitと一致することを確認しました（tarballのsha256は、
  この環境からsource archiveを取得できないため照合していません）。SCIPの構成には、文書に記載のflagに加えて
  `-DPAPILO=OFF -DREADLINE=OFF -DZLIB=OFF -DAMPL=OFF`が必要でした。workerのmanifestは
  `optional_dependencies: OpenGR,SCIP`、`source_kind: official_release`です。
- replay契約の修正（`scripts/master_replay_families.py`）:
  - 閉じたpolylineの開始点と向きはbuildで変わるため、順序に依存しない比較演算子を追加しました
    （`contains`、`same_closed_cycle`）。`intersect-polylines-shifted-cubes`（7.3）、`slice-cube-mid`・
    `slice-cube-diagonal`（7.5）に適用。Linuxでは同じ閉曲線が別の開始点で出力されます。
  - batch 3の改竄fixture 6件（regular2/regular3/voronoi）のsha256が、CRLFのworking copyで計算された値でした。
    repositoryの内容は`.gitattributes`の`eol=lf`でLFなので、新しいcheckout（CIを含む）では必ず不一致になります。
    LFの内容のsha256へ直しました。
- この修正後、Linux workerでfamily 7.1・7.2・7.3・7.4・7.5・7.6・7.9・7.11・7.12・7.13・7.14・7.15の
  固定harnessが合格します。
- 残り（判断待ち）: 7.8と7.10は、数値計算の結果そのものがWindows（MSVC）とLinux（gcc）で違い、
  Windowsの値に固定されたassertionが失敗します。必須validatorはどちらの結果も合格としています。
  - `skeleton-tube-function`・`skeleton-tube-class`: 頂点0のx座標が1.0583（期待）に対し1.3471。
  - `skeleton-torus-class`: 骨格の頂点・辺が25（期待）に対し24、頂点0のx座標が2.87712に対し2.87646。
  - `poisson-delaunay-sphere`: 最大頂点半径が上限2.05に対し2.0512。
  - `poisson-delaunay-sphere-fine`: 面数1518（期待）に対し1542、最大頂点半径2.0534。
  これらを通すにはassertionを環境に依存しない形（範囲など）へ変える必要があり、受入基準の変更になるため
  未実施です。

### 追補2: Linuxでの証拠再生成（2026-11-13、実施済み）

上の「証拠の再生成が必要（未実施）」と「追補: 準備（未完了）」の記述は、この節で置き換わります。
`docs/master/evidence/`のfamily 15件・`wave-a-capabilities.json`・`search-retrieval.json`・`workflows.json`・
`first-contact.json`・`performance-robustness.json`を、このLinux環境で再生成しました。
`*-windows-vs2026.json`・`codex-host-windows.json`・`hull-performance-windows.json`・blind set関連は
再生成していません（Windowsでの記録のまま）。`standalone_accepted`は引き続きfalseです。

- 生成環境: Linux、gcc 13.3、公式CGAL 6.2.1（sha256照合済み）、OpenGR・SCIP・SoPlexを組み込んだworker
  （manifestの`optional_dependencies`は`OpenGR,SCIP`、`source_kind`は`official_release`）。
  **これまでの証拠はWindows（MSVC）で生成されており、生成環境が変わっています。**
- 結果: 全family再試験は80/80（除外なし）。検索は実行サンプル240/240、文書検索298/300（再生成前と同じ）。
  workflowは67件。first-contactは例119/119、依頼32件中32件が実行成功（recipe一致25、再生成前と同じ傾向）。
  障害封じ込めは全27 modeで全試行を封じ込め。
- 残る失敗（1件、今回の変更と無関係）: `tests.test_master_acceptance`の
  `test_gate_cannot_be_met_without_the_target_and_full_acceptance`は、mainでも失敗しています。
  blind set 1のtop-3が目標95%未満であることを前提にしたassertionで、記録値は目標以上のため成立しません（未修正）。

#### 受入基準の変更（ユーザー承認: 期待値を環境に依存しない範囲にする）

数値計算の結果がWindows（MSVC）とLinux（gcc）で違うため、Windowsの値に固定されていたassertionを変更しました。
必須validatorの検査は変えていません。

| ケース | 変更前 | 変更後 | 実測（MSVC／gcc 13） |
|---|---|---|---|
| `skeleton-tube-function`・`skeleton-tube-class` | 頂点11・辺10、頂点0のx=1.0583（±1e-6） | 頂点9〜13、辺8〜12（x座標の固定を削除） | 11・10／11・10（頂点順が違う） |
| `skeleton-torus-class` | 頂点25・辺25、頂点0のx=2.87712 | 頂点23〜27、辺23〜27 | 25・25／24・24 |
| `poisson-delaunay-sphere`（2件） | 面数が560・1518と一致、頂点半径1.95〜2.05 | 面数が基準の±5%かつ出力メッシュと一致、頂点半径1.94〜2.06 | 560・1518／560・1542、最大半径2.0512・2.0534 |
| `param-arap-lambda-1000` | 頂点40のUV=(0.645, 1.191)（±1e-6） | UV座標の固定を削除 | (0.645, 1.191)／(-0.124, 0.292) |

`param-arap-lambda-1000`は、ほぼ等長な写像で平面内の位置と回転が自由なため座標が変わります。
骨格の位相（連結成分、閉路数が種数に一致）、写像の全単射性と歪みの上限はvalidatorが検査します。

#### Linuxで見つかった不具合の修正

- `reconstruction.poisson`: 陰関数が非有限値になる入力で、CGALのMesh_3内部からGMPが`SIGFPE`を出し
  workerが異常終了していました（Windowsではシグナルが出ず空の結果になり`EMPTY_RECONSTRUCTION`で拒否）。
  POSIXでは`make_mesh_3`の間だけ`SIGFPE`を捕捉し、同じ`EMPTY_RECONSTRUCTION`で拒否するようにしました
  （`worker/master/reconstruction/reconstruction_operations.cpp`）。workflow `neg08`・`wf44`・`neg20`が
  Windowsと同じ結果になります。
- `mesh.validate.hausdorff_symmetric_report`: 報告された上下限と判定の整合性検査をlong doubleで行っていたため、
  long doubleがdoubleより広い環境（Linux x86-64）では、ちょうど境界の入力（推定0.5、誤差0.01、許容0.49）で
  producer（binary64）と結論が食い違い、正しい報告を`VERDICT_MISMATCH`で拒否していました（安全側の誤り）。
  producerと同じbinary64で判定するようにしました。`tests.test_master_certified_hausdorff`で確認。
- supervisor（`cgal_mcp/master/supervisor.py`、POSIX）:
  - workerを独立sessionで起動し、timeout・cancel・終了後にsession全体をkillします。以前はworker本体だけを
    killしていたため、pipeを引き継いだ孫processが残るとsupervisorが待ち続け、timeoutが効きませんでした
    （WindowsはJob objectで一括終了）。
  - Linuxでは`PR_SET_PDEATHSIG`を設定し、host processが死んだらworkerも終了します。以前はworkerが残りました
    （`host_process_killed`が0/5 → 5/5）。
- 計測script（`scripts/measure_master_robustness.py`）: zombie processを生存扱いしない、Linuxでworkerの
  ピークRSSを`/proc`のVmHWMから約1 msごとに標本化して記録（真のピークの下限。上限そのものは`RLIMIT_AS`で
  kernelが強制）、worker実行ファイルのコピーで実行権限を保持、`faces-over-limit`のケースを上限を引き上げた
  `mesh.clip.plane`から`mesh.subdivide.loop`（2,000面上限に対し2,048面）へ変更。
- `tests/master_wave_b_cases.py`: 後のwaveで追加された必須validatorを許容するよう修正（CIのLinux worker jobが
  ここで止まっていました）。

#### 再生成の手順（Linux）

`scripts/replay_master_capabilities.py --work-dir`で全familyを再試験し、各reportを公開位置へコピーして
`catalog/major_requirements.json`のevidence sha256を更新（公開位置へ直接書く経路は、承認済みhashと一致しない
reportを書き込む前に失敗するため）。続けて`evaluate_master_search.py --publish-retrieval-evidence`、
`run_master_workflows.py --output`、`evaluate_first_contact.py --output`、`measure_master_robustness.py --output`。
検索の実行サンプルには`work/master-docs-index.sqlite`（`build_master_docs_index.py build`）が必要です。
