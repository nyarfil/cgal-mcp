# 原本の主要能力を実計算で判定する

原本7.1〜7.15の15分野・80要求を固定母数とし、軽量化の7.7に列挙された6要求を
実計算の再試験へ結び付けました。現在の合格範囲は6/80です。
点群処理の個別Operationや凸包の基盤受入を、未完了の要求全体の達成へ加算しません。

対応する正式workerで、固定harnessを実行してから要求判定します。

```powershell
.venv/Scripts/python.exe scripts/replay_master_capabilities.py `
  --worker build-master/Release/cgal-master-worker.exe `
  --output work/master-capability-local.json
```

Linuxではworkerを`build-master/cgal-master-worker`へ置き換えます。
checked-in reportを読むだけの`scripts/master_acceptance.py`は、再計算による確認が
ないため未完了を返します。JSON内の`pass`、hash、自己申告の完成表示だけを承認しません。
公開snapshotは当該buildの履歴資料です。CIはその環境で再試験し、別reportを保存します。

試験は7 cost/placement、5 stop predicate、constraint、bounded distance、normal-change、
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
