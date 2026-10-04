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
stop条件は出力の計測値で確認します。23の合格ケースと46のvalidator実行について、
request・response・入力・出力・validator report・source・workerのhashを照合します。
FastEnvelopeの外部依存は別の未対応policyとして残っています。

受入runnerは登録済みの正式native workerと固定harnessを実行します。
任意の試験command、JSONから指定された未知のコード、test stubで要求を合格にしません。
実行するPython source自体の任意改変・monkeypatchを防ぐセキュリティ境界ではありません。
原本・registry・試験sourceの一致と、実行後の内容不変も検査します。

全80要求、300 intent、30以上のworkflow、全host/build/protocol、故障・資源・性能の
受入は未完了です。今回のreportも`standalone_accepted: false`を保持します。
