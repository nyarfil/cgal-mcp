# 永続workerと結果cache（Phase 10）

計画書Phase 10の作業項目「persistent workers / artifact cache / AABB reuse」と、
設計書32.2〜32.3（AABB trees where safe、persistent workerでのparsed mesh表現、重複変換の回避）
への対応状況です。どちらも**opt-in**で、既定は従来どおり「1要求=1 process、cacheなし」です。

| 設定 | 既定 | 意味 |
|---|---|---|
| `CGAL_MASTER_PERSISTENT_WORKERS` | `0` | `1`で永続worker poolを使用 |
| `CGAL_MASTER_RESULT_CACHE` | `0` | `1`で検証済み結果cacheを使用 |

## 永続worker（session protocol 1）

- native workerに`--serve`を追加しました。1行1要求・1行1応答（flush）。`--manifest`と既定の
  1回実行は不変で、1回実行は複数要求を従来どおり`MULTIPLE_REQUESTS`で拒否します。
- 制御行`{"control":"ping"|"shutdown"}`。pongは`session_protocol: 1`と要求IDを返します。
- 各要求の前にCGALの既定乱数と`std::rand`を新規process相当へ戻します。`bad_alloc`や想定外例外は
  応答後にprocessを終了し、hostは再利用しません。
- supervisor（`cgal_mcp/master/supervisor.py`）: processごとにJob Object（kill-on-close、
  process memory上限）を付け、**同じmemory上限のjobだけ**で再利用します。再利用前と各job後に
  nonce付きhealth checkを行い、余分な出力・死んだprocessは失格（job後なら`worker_protocol`で失敗）。
- 退役条件: crash、timeout、protocol違反、error応答、job数上限（既定64要求）、寿命（600秒）、
  job後の私用メモリが上限の25%超、worker実行ファイルのdigest変化、idle 30秒（idle時の負荷ゼロ）。

## 結果cache

- `cgal_mcp/master/result_cache.py`。keyはOperation id・revision・正規化済みparameter・kernel・
  入力のtype/unit/format/sha256・registry revision・worker実行ファイルsha256・CGAL version。
- 登録は**同じjobで必須validatorが全て合格した後だけ**。失敗・拒否jobは登録されません。
- hit時もtransformだけを省略し、必須validatorは毎回live実行します（保存済み判定は記録用）。
- entryはcache固有の乱数鍵によるHMAC、出力blobは読込み時に再hash。不一致・欠損・stale
  （registry/worker変化）はmissとして削除します。件数・容量上限でLRU削除します。

## AABB／parsed geometry再利用（opt-in、Phase 10「AABB reuse」）

設定は永続workerの上でさらにopt-inです。**既定はOFF**で、1回実行（one-shot）経路は変更していません。

| 設定 | 既定 | 意味 |
|---|---|---|
| `CGAL_MASTER_SESSION_CACHE` | `0` | `1`かつ`CGAL_MASTER_PERSISTENT_WORKERS=1`のときだけ、永続worker内でparsed meshとAABB木を再利用（永続workerがOFFなら無視） |

- 対象Operation: `spatial.aabb.closest_points`、`spatial.aabb.ray_first_hits`、`spatial.aabb.intersections`、
  `mesh.location.locate`（`locate_with_AABB_tree`）、`mesh.distance.symmetric_hausdorff`（parsed＋健全性検査済みmeshのみ。
  CGALは内部AABB木を外から渡せないため木は毎回構築）。他のOperation（simplify、analysis、repair等）は
  従来どおり要求ごとに解析します。validator（独立実装・brute force）はcacheを使わず毎回live実行します。
- 実装: `worker/master/session_cache.h`。worker processごとのLRU（件数上限既定8、byte予算）。
  keyは**検証済みcontent sha256**＋Operation種別＋kernel/traits識別（Epick/Epeck、accelerate有無）＋宣言type/format/unit
  ＋CGAL version。異なるhashのentryは共有しません。entryは構築後immutable（`shared_ptr<const T>`、constクエリのみ）で、
  乱数stateは従来どおり要求ごとに初期化されます。hit時も**入力fileを再読込みして再hash**するため、
  改ざん・差替えされたfileはcold経路と同じ`sha256`不一致エラーになり、hitにはなりません。
- 結果はcold経路と**bit一致**です（同じ構築手順を1か所に集約: cold経路もcache経路も同じbuilderを使用）。
- memory: 予算はworkerのmemory上限の10%（`PersistentPolicy.session_cache_fraction`）で、事前の推定byte数が予算を
  超えるentryは保存しません（`oversize_skipped`）。予算・件数超過は古い順にevict。残留メモリ退役の閾値は
  「上限の25%＋cache予算」に拡張され、cache保持が「25%超で退役」の隔離保証を壊さないよう会計します
  （それ以外の残留は従来の25%で判定）。cache構築中の`bad_alloc`は、cache全削除→1回だけ再試行し、
  それでも失敗なら構造化`MEMORY_LIMIT`を返してprocess退役（新processのcacheは空）。
- 観測: 要求ごとのcounter（`hits`/`misses`/`stored`/`evictions`/`pressure_evictions`/`oversize_skipped`/`entries`/`bytes`）が
  workerの`metrics.session_cache`に入り、job詳細の`session_cache`（Operationごと）で参照できます。
- 退役（crash、job数、寿命、memory残留、実行ファイル変更、idle）でprocessと一緒にcacheも消えます。
- 証拠: `evidence/performance-robustness.json`の`deterministic.persistent.geometry_cache`
  （5 Operation×小/中/大、各で[miss, hit, hit, hit]とone-shotとのbit一致・validator live実行、別hash非共有、
  予算/evict/oversize/残留会計、cache保持中のbad_alloc封じ込め）。cold/warm時間は`timings.persistent`/`timings.geometry_cache`
  の参考値で、合否には使いません。native単体のtamper/stale/LRU試験は`tests/test_master_geometry_cache.py`。
- 範囲の注記: 設計書32.3の「同一hashを何度もSurface_meshへ変換しない」は上記Operationに対して実装しました。
  他の全mesh Operationの共有readerは未実装です（gateの判定項目ではなく、拡張候補）。

証拠は`evidence/performance-robustness.json`の`deterministic.persistent`
（`scripts/measure_master_robustness.py --stage persistent`）にあります。速度は参考値で、合否には使いません。
