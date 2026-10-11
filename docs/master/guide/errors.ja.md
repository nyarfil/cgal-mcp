# エラー・拒否と対処

エラーは {class, code, message, recoverable, suggested_operations, details} で届く。codeが示す原因を直す。invalid_input・unmet_precondition・unsupported_adapter・validation_failureの失敗を同じ要求のまま再試行しない。

## ジョブの状態
- queued: 受付済み・未実行
- running: worker実行中。cgal_job_statusをポーリング
- succeeded: 全stepが完了し全必須検証器が合格。出力が公開される
- rejected: 検証器が結果を確認できず却下。未検証の出力は公開されない
- failed: 実行・検証が完了できなかった（error.class/error.code参照）。失敗stepの出力は公開されない
- cancelled: cgal_job_cancelで中止

## 失敗クラス
- invalid_input: データや引数の誤り。直す
- unmet_precondition: 文書化された前提条件の不成立（上限・閉性・点数など）
- unsupported_adapter: 実行可能な操作がない。再試行しない
- validation_failure: 独立検証器が結果を却下
- resource_limit / timeout: 時間・メモリ上限。入力を小さくするか上限内で引き上げる
- cgal_precondition / cgal_exception / numeric_failure: CGAL自体が入力を拒否（退化・非多様体・数値的に危険）
- worker_crash / worker_protocol / worker_io / worker_error: native workerの問題。cgal_system_healthを呼び、再試行は多くても1回

## グループ別エラーコード

### 入力ファイルを解析できない
意味: ファイルが壊れているか非対応の形式（ASCII OFF/OBJ/PLY、STL、XYZ、型付きJSON）。
対処: ファイルを直すか再出力する。同じ入力の再試行は無意味。構文の修復はサーバ側では行わない（修復操作は解析済み幾何のみ対象）。
- `inexact_integer`
- `json_nonfinite`
- `json_syntax`
- `obj_encoding`
- `obj_face`
- `obj_index`
- `obj_vertex`
- `off_counts`
- `off_encoding`
- `off_face`
- `off_header`
- `off_index`
- `off_trailing`
- `off_truncated`
- `ply_element`
- `ply_face`
- `ply_format`
- `ply_header`
- `ply_properties`
- `ply_trailing`
- `ply_truncated`
- `ply_vertex`
- `stl_syntax`
- `unsupported_domain_kind`
- `unsupported_format`
- `xyz_encoding`
- `xyz_syntax`

### 取込み内容が要求した型として不正
意味: 解析結果が型付きアーティファクトの契約に反する（空、非有限、不正な頂点番号、重複、型違い、512MiB超）。
対処: データを直すか正しいartifact_typeを指定する。型の意味はcgal_get_guideのglossaryを参照。
- `degenerate_ray`
- `duplicate_site`
- `empty_geometry`
- `import_source`
- `import_too_large`: ファイルが取込み上限512MiBを超えている。
- `index_out_of_range`
- `insufficient_elements`
- `invalid_domain`
- `nonfinite_coordinate`
- `schema_mismatch`
- `type_mismatch`

### 不明なID・単位規則・ファイルアクセス規則
意味: artifact/plan/jobのIDが存在しない、単位がmm/cm/mでない（レポートは'none'）、保存blobが変化した、パスが許可ルート外、またはエクスポート先が既に存在する。
対処: ID は直前の応答の値をそのまま使う。単位はmm/cm/mから選ぶ。エクスポート先は許可ルート内の新しいパス。
- `analysis_report`
- `artifact_hash_changed`
- `artifact_unit`: 幾何の単位はmm/cm/m。レポートや単位なし型は'none'。
- `export_parent`
- `file_access_denied`: パスが設定済みファイルルートの外（HTTP配備ではルートが制限される）。
- `input_hash_changed`
- `unknown_artifact`
- `unknown_job`
- `unknown_plan`

### プラン要求の形が不正・不整合
意味: DAGが循環・未知のstep/slot参照、辺の型や形式が不一致、入力スロット数が合わない、オペランドの単位が異なる（unit_mismatch）、または計画後にレジストリが変わった（stale_plan_*）。
対処: 操作カード（topic 'op:<id>'）でスロット名と型を確認する。結合前に単位を揃える。stale_plan_*は再度planする。
- `cyclic_plan`
- `dag_format`
- `dag_type`: step入力が型の合わない出力につながっている、またはグラフが循環している。
- `duplicate_step`
- `input_arity`
- `input_binding`: 入力スロットが欠けている・誤った束縛。カードのスロット名を使う。
- `input_bindings`
- `input_format`
- `input_slots`
- `input_type`
- `kernel_unsupported`
- `missing_step_output`
- `missing_validator`
- `operation_id`
- `plan_alternatives`
- `plan_operation`
- `plan_parameters`
- `plan_policy`
- `plan_request`
- `plan_rules`
- `plan_step`
- `plan_steps`
- `stale_plan_operation`
- `stale_plan_registry`: 別のレジストリ版に対するプラン。cgal_planをやり直す。
- `unit_mismatch`: オペランドの単位が異なる（例: mmとcm）。正しい単位で取り込み直す。アーティファクト間の暗黙変換はしない。
- `unknown_step_reference`

### パラメータが拒否された
意味: 必須パラメータの欠落、未知のパラメータ、範囲・enum違反、長さ/角度が{value, unit}形式でない、またはパラメータ前提条件の違反。
対処: パラメータ名・範囲・既定値はカードからそのまま写す。長さは{"value": n, "unit": "mm"|"cm"|"m"}、角度は{"value": n, "unit": "deg"|"rad"}。route_parameter_*はgoal文が暗に要求するパラメータを明示せよという意味。
- `parameter_angle`
- `parameter_const`
- `parameter_enum`
- `parameter_finite`
- `parameter_length`
- `parameter_one_of`
- `parameter_precondition`
- `parameter_range`
- `parameter_type`
- `parameter_unit`
- `parameter_unit_overflow`
- `parameters_required`: 必須パラメータが欠けている。必須は操作カードに全て載っている。
- `parameters_unknown`: スキーマにないパラメータ名（スキーマは閉じている）。
- `route_parameter_conflict`
- `route_parameter_feature_conflict`
- `route_parameter_feature_contract`
- `route_parameter_missing`

### goalを1つの操作に決められない
意味: ambiguous_route: 複数の操作が同等に当てはまる。unsupported_operation: 実行可能な操作がない、または登録済みだが非対応のCGALパッケージを指している。detailsに記録済みの質問と選択肢がある。
対処: 推測しない。details.optionsを読み、ユーザーにどれか尋ね、operation_id付きでcgal_planを呼ぶ。非対応パッケージはdetails.unsupported_cgal_packagesを読み、未対応だとユーザーに伝える。
- `ambiguous_route`: goalが複数の操作に同等に当てはまる。ユーザーに尋ね、operation_idでplanする。タイブレークはしない。
- `search_limit`
- `search_query`

### 方針（コスト/配置/ライセンス）を選べない
意味: 必須の方針選択が欠けている・未登録、またはプランのライセンス/依存/kernel方針が操作を除外している。
対処: カードに載っている方針から選ぶ。allowed_licenses/dependenciesの緩和はユーザーの同意がある場合のみ。
- `policy_evidence`
- `policy_selection`
- `policy_selector`
- `policy_unavailable`

### 資源上限の超過・不正指定
意味: wall_time_ms/memory_mbがサーバ上限外（cgal_system_healthで確認）、またはworkerが壁時間・メモリ上限に達した。
対処: 入力を小さくする（先に軽量化）か、報告された上限内でexecution={"wall_time_ms":..., "memory_mb":...}を指定する。再試行を繰り返さない。
- `execution_limits`: wall_time_ms/memory_mbが許容範囲外（cgal_system_healthで確認）。
- `inspection_memory_limit_unavailable`
- `inspection_protocol_limit`
- `inspection_timeout`
- `memory_limit`
- `memory_limit_unavailable`
- `resource_limit`
- `worker_limits`
- `worker_output_too_large`
- `worker_stdout_limit`
- `worker_timeout`

### 必須の検証器が結果を却下した
意味: 操作は実行されたが独立した検証器が結果を確認できなかった（または検証器が動かなかった）。未検証の出力は公開されない（job state 'rejected' または 'failed'）。
対処: 出力を使わない・偽造しない。job.validation[].reportで失敗した検査を読み、ユーザーが許せば上限を緩める、または別の操作・レシピを選ぶ。
- `validation_failed`: 検証器が出力を却下した。出力は公開されない。
- `validation_report`
- `validation_report_malformed`
- `validation_report_too_large`
- `validator_binding`: 指定した検証器の束縛がレジストリと一致しない。検証器の偽装・省略はできない。
- `validator_not_run`
- `validator_parameter_binding`
- `validator_reference`
- `validator_type`

### ネイティブworker・マニフェストの問題
意味: 隔離workerが起動できない・異常終了・不正なプロトコル、またはビルドのマニフェストがレジストリと不一致（要求ではなく導入/ビルドの問題）。
対処: cgal_system_healthを呼び、worker/build欄をユーザーに報告する。再試行は多くても1回。
- `inspection_crash`
- `inspection_protocol`
- `internal_failure`
- `manifest_binding_mismatch`
- `manifest_build_mismatch`
- `manifest_cgal_version`
- `manifest_dependency_mismatch`
- `manifest_failed`
- `manifest_kernel_mismatch`
- `manifest_malformed`
- `manifest_metadata_mismatch`
- `manifest_missing_operation`
- `manifest_protocol`
- `manifest_registry_mismatch`
- `manifest_role_mismatch`
- `manifest_start`
- `manifest_timeout`
- `worker_missing`
- `worker_output_missing`
- `worker_output_path`
- `worker_output_schema`
- `worker_output_slot`
- `worker_output_unit`
- `worker_response_identity`
- `worker_response_malformed`
- `worker_response_schema`
- `worker_session_unsupported`
- `worker_start`

### レジストリ・カタログ・文書索引・ガイドの問題
意味: サーバ側データの読込・検証失敗、またはガイドのtopicが存在しない（guide_topic）。
対処: guide_topicは返されたtopic一覧から選ぶ。それ以外はコードをユーザーに報告する（サーバは推測せず失敗として閉じる）。
- `docs_catalog_fallback`
- `docs_index_catalog`
- `docs_index_missing`
- `docs_index_provenance`
- `docs_index_query`
- `docs_index_schema`
- `docs_index_version`
- `docs_search`
- `guide_topic`: 不明なガイドtopic。エラーに有効なtopic一覧がある。
- `operation_aliases`
- `operation_evidence`
- `operation_io`
- `operation_kernel`
- `operation_license`
- `operation_metadata`
- `operation_parameters`
- `operation_preconditions`
- `operation_resources`
- `operation_revision`
- `operation_role`
- `operation_schema`
- `operation_sources`
- `operation_status`
- `operation_validation`
- `policy_id`
- `policy_implementation`
- `policy_metadata`
- `policy_operation`
- `policy_reason`
- `policy_registry_build`
- `policy_registry_conflict`
- `policy_registry_read`
- `policy_registry_schema`
- `policy_registry_version`
- `policy_revision`
- `policy_schema`
- `policy_status`
- `registry_build`
- `registry_conflict`
- `registry_empty`
- `registry_read`
- `registry_schema`
- `search_data_read`
- `search_data_schema`

## worker（CGAL側）のコード
UPPER_SNAKE_CASEのコードはnative workerや検証器由来で操作固有。例: AMBIGUOUS_COMPONENT_TIE, EMPTY_RECONSTRUCTION, HAUSDORFF_WITHIN_MAX_DEVIATION_FAILED, MALFORMED_OFF, MESH_NOT_CLOSED, ROUGHNESS_NOT_REDUCED, VALIDATION_BUDGET_EXCEEDED.
まずerror.class（上表）、次にcodeとmessageを読む.
