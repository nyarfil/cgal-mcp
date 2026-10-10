# 凸包の性能測定と資源設定

実PCのWindows／VS2026／Python 3.13で、公式CGAL 6.2.1の実workerを測定しました。
単位立方体の8頂点と内部点を固定seedで生成し、各規模を別Python process・別storeで
試験しています。計算時間には凸包生成と必須validatorを含みます。

| 入力点数 | 取込み | 生成＋検証 | worker最大RSS |
|---:|---:|---:|---:|
| 1,000 | 0.145秒 | 0.325秒 | 6.6MiB |
| 100,000 | 0.405秒 | 1.710秒 | 31.3MiB |
| 1,000,000 | 2.705秒 | 14.667秒 | 251.3MiB |

RSSはWindowsの`GetProcessMemoryInfo`による各計算・validator processのpeakの最大値です。
Python host、取込みparser、manifest照会のメモリはこの値に含みません。
100万点のworker稼働中に中止を要求し、約0.008秒で中止応答、process回収、
入力保持、未検証出力の非公開を確認しました。中止時点はnative process起動から50ms後で、
アルゴリズム内部の特定区間での応答時間を保証する測定ではありません。

各規模1回の合成fixture測定です。全主要能力の性能受入、cache効果、永続workerの
復旧・資源回収は未完了です。結果cacheは無効で、workerは処理ごとに起動します。
機械可読の入力・出力・worker hashと測定範囲は
[`evidence/hull-performance-windows.json`](evidence/hull-performance-windows.json)に記録しています。

```powershell
.venv/Scripts/python.exe scripts/measure_master_hull.py `
  --worker build-master/Release/cgal-master-worker.exe `
  --output work/hull-performance-local.json
```

## 明示的な資源設定

Masterは初期値として同時実行2、workerメモリ上限4GiB、通常処理120秒を使います。
Operationの実行profileで再構築・volume生成は600秒を指定できます。
未実装Operationのprofileを選べることは、そのOperationの実装証拠ではありません。
以下の環境変数でhost起動時に変更できます。

| 設定 | 初期値 | 有効範囲 |
|---|---:|---|
| `CGAL_MASTER_CONCURRENCY` | 2 | 1〜64 |
| `CGAL_MASTER_MAX_MEMORY_MB` | 4096 | 64〜1048576MiB |
| `CGAL_MASTER_DEFAULT_MEMORY_MB` | 上限と4096の小さい方 | 64MiB〜設定上限 |
| `CGAL_MASTER_DEFAULT_WALL_TIME_MS` | 120000 | 1ms〜設定上限 |
| `CGAL_MASTER_MAX_WALL_TIME_MS` | 86400000 | 設定した通常処理時間以上〜86400000ms |

非整数・範囲外・上限と矛盾する設定は起動時に拒否します。各jobの要求も設定上限以下に
制限します。実際の設定値は`cgal_system_health`で確認できます。
WindowsではJob Object、POSIXではprocessの資源制限を使用します。

## 全15 familyの性能・資源・故障封じ込め測定

`scripts/measure_master_robustness.py`が実workerで、各familyの代表Operationを小・中・大の3規模で測り、
資源制限の拒否、故障注入、host強制終了を試験します。証拠は
[`evidence/performance-robustness.json`](evidence/performance-robustness.json)です。
`deterministic`部（hash固定）と`timings`部（時間・最大RSS。速度では合否を決めず、宣言した
メモリ上限4GiB・壁時間上限だけで判定）を分けています。故障注入は試験専用の
`scripts/robustness_fault_proxy.py`で行い、環境変数でのみ選択されます。native workerとregistryは変更していません。

結果（`evaluate_performance_gate`、`standalone_gates`に出力。判定は未達）:

- 規模測定: 15 family全てで3規模が成功し検証済み。最大RSSは最大約519MiB（7.4 500k面）。
- 封じ込め: 27種類・518試行で100%（kill、abort、アクセス違反、timeout、孫process、不正/巨大出力、
  不正入力、実workerの外部kill、host強制終了）。各試行で出力非公開、process回収、staging残留なし、
  次の呼び出しが正しい結果を再現することを確認。試行数は計画に記載がないため各20回と宣言。
- 未達の理由（実測）: `triangulation.delaunay_3`（1000点以上）と`mesh2.refine.delaunay`（size 0.25）で
  validator processがスタックオーバーフロー(0xC00000FD)で落ちる（封じ込めは成功するが宣言範囲内で動かない）。
  メモリ上限64MiB超過時、workerは無言でexit 1となり`worker_crash`と分類される（期待は`memory_limit`）。
  永続worker、結果cache、AABB再利用は未実装で効果は未測定。
- 修正: 孫processがpipeを保持するとtimeoutが効かない不具合を`supervisor.py`で修正（job closeを先に実行）。
- 多くのOperationはworker内部上限がregistryの宣言値より小さく、上限超過は構造化エラーで拒否される
  （例: `pointset.remove_outliers`は400点、simplify検証は400面）。上限超過probeは証拠の`ceiling_probes`に記録。
