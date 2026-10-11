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
  「未選択の穴が不変」「選択した穴が閉じた」を検証します。古いidは`HOLE_ID_NOT_FOUND`で拒否します。
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
`standalone_accepted`は引き続きfalseです。項目1は未対応です。

parameter名を`self_intersection_policy`ではなく`foldover_policy`としたのは、Operation検索が
parameter名も索引にするため、`self_intersection`の概念が`mesh.simplify.edge_collapse`にも一致して
「自己交差の組を列挙する」という問い合わせが`mesh.analysis.self_intersections`へ一意に
ルーティングされなくなる（既存の検索試験で検出）ためです。
