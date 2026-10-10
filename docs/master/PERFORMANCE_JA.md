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

各規模1回の合成fixture測定です（既定の1要求=1 process、cacheなしで測定）。
永続workerと結果cacheはopt-inで、その証拠は下記「永続workerと結果cache」と
[`PERSISTENT_WORKER_CACHE_JA.md`](PERSISTENT_WORKER_CACHE_JA.md)を参照してください。
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
`scripts/robustness_fault_proxy.py`で行い、環境変数でのみ選択されます。

結果（`evaluate_performance_gate`、`standalone_gates`に出力。判定は未達）:

- 規模測定: 15 family全てで3規模が成功し検証済み。最大RSSは最大約519MiB（7.4 500k面）。
- 封じ込め: 27種類・518試行で100%（kill、abort、アクセス違反、timeout、孫process、不正/巨大出力、
  不正入力、実workerの外部kill、host強制終了）。各試行で出力非公開、process回収、staging残留なし、
  次の呼び出しが正しい結果を再現することを確認。試行数は計画に記載がないため各20回と宣言。
- 修正した実欠陥: `triangulation.delaunay_3`と`mesh2.refine.delaunay`のvalidatorがスタックオーバーフロー(0xC00000FD)で落ちた原因は、Epeck(lazy)の面積・体積を三角形ごとに`+=`で累積して作られる深いlazy DAGの再帰評価でした。各加算後に`CGAL::exact`でDAGを畳み、再帰を排除しました（検証意味は不変）。両Operationは宣言範囲の上限（1000点、size 0.25）でも成功・検証済みです。メモリ上限超過は、workerが`std::bad_alloc`を捕捉して構造化`RESOURCE_LIMIT/MEMORY_LIMIT`を返し、supervisorが`memory_limit`(resource_limit)へ分類します（64MiB上限の実測ケースで確認）。`mesh.split.plane`の出力型宣言をPolygonSoup3から実際のTriangleSurfaceMeshへ修正し、`mesh.validate.split`の候補入力型も合わせました。
- 永続workerと結果cache（opt-in、`--stage persistent`）: 再利用中のprocessへの故障注入13種×20試行
  （proxy経由のkill/abort/アクセス違反/hang/孫process/不正・複数行・後続ゴミ出力/巨大出力/偽ID/stderr氾濫、
  実workerの外部kill、実workerのメモリ上限64MiB）が全て封じ込められ、毎回新processへ置換され、次の呼び出しが
  golden結果を再現。15 family代表Operationを1つの永続processで順・逆・再実行し、1回実行と出力hashが一致
  （job間汚染なし）。cache hitも15件一致。job数・寿命・残留メモリ・実行ファイル変更での退役、idle 30秒後の
  process 0、memory上限ごとのpool分離、cacheの改ざん・stale→miss、正しく署名された誤候補をlive validatorが拒否、
  件数上限での削除を確認。速度は参考値のみ（`timings.persistent`）。
- 未達の理由（残り1件）: AABB木／parsed geometryのjob間再利用（計画Phase 10「AABB reuse」、設計書32.2/32.3）は
  未実装です。理由は[`PERSISTENT_WORKER_CACHE_JA.md`](PERSISTENT_WORKER_CACHE_JA.md)に記載。
- 修正: 孫processがpipeを保持するとtimeoutが効かない不具合を`supervisor.py`で修正（job closeを先に実行）。
- 多くのOperationはworker内部上限がregistryの宣言値より小さく、上限超過は構造化エラーで拒否される
  （例: `pointset.remove_outliers`は400点、simplify検証は400面）。上限超過probeは証拠の`ceiling_probes`に記録。
