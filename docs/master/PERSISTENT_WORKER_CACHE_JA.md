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

## AABB／parsed geometry再利用（未実装・gate未達の理由）

計画書Phase 10は「AABB reuse」を明記し、設計書32.2/32.3はworker内のparsed mesh表現とAABB木の
再利用を求めています。現状は未実装です。入力解析は各Operation内で個別に行われ
（共有native readerは`read_off_mesh`等の一部のみ）、AABB木も複数fileで異なるkernel・primitiveで
構築されます。job間でnative cacheを保持すると、そのメモリが次jobのprocess memory上限に算入され、
上記の「上限の25%超で退役」という隔離保証と衝突します。安全に行うには共有artifact reader、
cache量を含むメモリ会計、cache有無で結果hashが一致する証拠が必要です。そのため
`performance_resource_and_robustness_acceptance`はこの1点を理由に未達のままです。

証拠は`evidence/performance-robustness.json`の`deterministic.persistent`
（`scripts/measure_master_robustness.py --stage persistent`）にあります。速度は参考値で、合否には使いません。
