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

全80要求、300 intent、30以上のworkflow、全host/build/protocol、故障・資源・性能の
受入は未完了です。今回のreportも`standalone_accepted: false`を保持します。
