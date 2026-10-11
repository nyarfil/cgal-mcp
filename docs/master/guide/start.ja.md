# クイックスタート

## 1. 操作を探す
- 既知のワークフローか？ cgal_get_guide(topic="recipes")→topic="recipe:<id>"。違えばcgal_capabilities_search(query=<goalを任意の言語で>)。
- 候補の読み方: operation_id・status・score・why・input_types・output_types・route_supported。query_analysis.abstained=trueは該当する実行可能な操作がないという意味。そのまま伝える。
- 次にカードを読む: cgal_get_guide(topic="op:<operation_id>")（パラメータ・単位・上限・例）。

## 2. 入力を取り込む
- cgal_artifact_import(path, unit, artifact_type?)はファイルを不変ストアへ複製して解析する（修復はしない）。artifact_id・型・単位・propertiesを返す。pathはサーバから読めること。
- 拡張子だけで曖昧なとき（json、xyz）はartifact_typeを渡す。単位は必須でmm/cm/m。

## 3. プランを作る
- 単一操作: cgal_plan(request={"operation_id": ..., "inputs": {<slot>: <artifact_id>}, "parameters": {...}})。パイプライン: request={"steps": [{"id", "operation", "inputs": {<slot>: <artifact_id> | {"step": id, "slot": 出力slot}}, "parameters"}]}。
- 必須検証器は自動で挿入される。プランにはestimate（コスト階層・リスク）も載る。計画段階の失敗は計算前に起きる。

## 4. 実行して読む
- cgal_execute(plan_id[, execution={"wall_time_ms", "memory_mb"}])はすぐjob_idを返す。cgal_job_status(job_id)をstateがsucceeded/rejected/failed/cancelledになるまで1〜2秒おきに確認する。
- succeeded時: job.outputs[]にartifact_id・型・単位・形式・sha256・properties、job.validation[]に各検証器のレポート。数値はここから報告し、作り話をしない。
- cgal_artifact_inspect(artifact_id)でメタデータと来歴、cgal_artifact_export(artifact_id, path)で正確なバイト列を新しいパスへ書き出す。
- rejected/failed: job.error {class, code, message}を読む（topic 'errors'）。却下された出力を結果として示さない。

## 5. 実例（hull.convex_3）
呼び出し例（fixture使用。出典: workflow wf19-hull3-loop-measures)
1. cgal_artifact_import {"artifact_type": "PointSet3", "path": "tests/fixtures/master/cube_with_interior.xyz", "unit": "mm"}  -> artifact_id（$cube_with_interiorと呼ぶ）
2. cgal_plan {"request": {"inputs": {"points": "$cube_with_interior"}, "operation_id": "hull.convex_3", "parameters": {}}}  （$nameは対応するimportのartifact_idに置換）
3. cgal_execute {"plan_id": <plan_id>}  ->  cgal_job_status {"job_id": <job_id>} をstateがsucceeded/rejected/failedになるまで

## 心得
- 単位・操作ID・パラメータを推測しない。カードを読む。
- サーバが拒否したら拒否をそのまま伝える。検証器の回避や非対応パッケージへの迂回をしない。
- 複数が同等（ambiguous_route）ならユーザーに尋ね、operation_idでplanする。
- プロンプト: start_here, repair_and_simplify_mesh, reconstruct_surface_from_points, validate_geometry, compare_meshes, 2d_boolean_offset, choose_operation。
