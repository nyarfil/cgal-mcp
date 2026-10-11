# Errors, refusals and how to react

Errors arrive as {class, code, message, recoverable, suggested_operations, details}. Fix the cause named by the code; never retry an unchanged request that failed with invalid_input, unmet_precondition, unsupported_adapter or validation_failure.

## Job states
- queued: accepted, not yet running
- running: worker(s) executing; keep polling cgal_job_status
- succeeded: every step ran and every mandatory validator passed; outputs are published
- rejected: a validator did not confirm the result; the unverified output is not published
- failed: execution or validation could not complete (see error.class / error.code); nothing is published for the failed step
- cancelled: stopped by cgal_job_cancel

## Failure classes
- invalid_input: your data/arguments are wrong; fix them
- unmet_precondition: a documented precondition fails (bounds, closedness, point counts)
- unsupported_adapter: no executable operation matches; do not retry
- validation_failure: the independent validator rejected the result
- resource_limit / timeout: time or memory ceiling reached; shrink the input or raise limits within bounds
- cgal_precondition / cgal_exception / numeric_failure: CGAL itself refused the input (degenerate, non-manifold, numerically unsafe)
- worker_crash / worker_protocol / worker_io / worker_error: native worker problem; call cgal_system_health, retry at most once

## Error codes by group

### Input file could not be parsed
Meaning: The file is malformed or not in a supported encoding (ASCII OFF/OBJ/PLY, STL, XYZ, or the typed JSON schemas).
Do: Fix or re-export the file; do not retry unchanged. Never ask the server to repair syntax: repair operations work on parsed geometry only.
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

### Imported content is invalid for the requested type
Meaning: Parsed content violates the typed artifact contract (empty, non-finite, bad index, duplicates, wrong type, over 512 MiB).
Do: Correct the data or pass the right artifact_type; check cgal_get_guide topic 'glossary' for type meanings.
- `degenerate_ray`
- `duplicate_site`
- `empty_geometry`
- `import_source`
- `import_too_large`: File exceeds the 512 MiB import bound.
- `index_out_of_range`
- `insufficient_elements`
- `invalid_domain`
- `nonfinite_coordinate`
- `schema_mismatch`
- `type_mismatch`

### Unknown id, unit rule, or file-access rule
Meaning: An artifact/plan/job id does not exist, a unit is not mm/cm/m (or not 'none' for reports), a stored blob changed, or the path is outside the configured file roots / the export target already exists.
Do: Use ids exactly as returned by earlier calls; pick a unit from mm/cm/m; export to a new path inside the allowed roots.
- `analysis_report`
- `artifact_hash_changed`
- `artifact_unit`: Unit must be mm, cm or m for geometry; reports and unitless types use 'none'.
- `export_parent`
- `file_access_denied`: Path is outside the configured file roots (HTTP deployments restrict roots).
- `input_hash_changed`
- `unknown_artifact`
- `unknown_job`
- `unknown_plan`

### Plan request is malformed or inconsistent
Meaning: The DAG is cyclic or references unknown steps/slots, an edge has the wrong artifact type or format, input slots/arity do not match the operation, operands have different units (unit_mismatch), or the registry changed since planning (stale_plan_*).
Do: Read the operation card (cgal_get_guide topic 'op:<id>') for slot names and types; convert inputs to one unit before combining; re-plan after stale_plan_*.
- `cyclic_plan`
- `dag_format`
- `dag_type`: A step input is wired to an output of the wrong type, or the graph is cyclic.
- `duplicate_step`
- `input_arity`
- `input_binding`: An input slot is missing or bound to the wrong thing; use slot names from the card.
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
- `stale_plan_registry`: Plan was made against another registry revision; call cgal_plan again.
- `unit_mismatch`: Operands carry different units (e.g. mm and cm). Re-import one with the right unit; the server never converts silently between artifacts.
- `unknown_step_reference`

### Parameters rejected
Meaning: A required parameter is missing, an unknown one was supplied, a value is outside its range/enum, a length/angle is not {value, unit}, or a precondition on parameters failed.
Do: Copy parameter names, ranges and defaults from the card; lengths are {"value": n, "unit": "mm"|"cm"|"m"}, angles {"value": n, "unit": "deg"|"rad"}. route_parameter_* means the goal text implies a parameter you must pass explicitly.
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
- `parameters_required`: A required parameter is missing; the card lists every required one.
- `parameters_unknown`: A parameter name is not in the schema (schemas are closed).
- `route_parameter_conflict`
- `route_parameter_feature_conflict`
- `route_parameter_feature_contract`
- `route_parameter_missing`

### Goal could not be routed to exactly one operation
Meaning: ambiguous_route: several operations match equally. unsupported_operation: nothing executable matches, or the request names a CGAL package that is cataloged but not executable. Details hold the recorded question and options.
Do: Never guess. Read details.options (each has operation_id, summary, distinguishing_concepts), ask the user which one they mean, then call cgal_plan with operation_id. For unsupported packages read details.unsupported_cgal_packages and tell the user it is not supported.
- `ambiguous_route`: Goal fits several operations equally. Ask the user, then plan with operation_id. No tie-break is applied.
- `search_limit`
- `search_query`

### Policy (cost/placement/licence) not selectable
Meaning: A required policy choice is missing or not registered, or the licence/dependency/kernel policy in the plan excludes the operation.
Do: Choose among the policies listed on the card; relax allowed_licenses/dependencies only if the user agrees.
- `policy_evidence`
- `policy_selection`
- `policy_selector`
- `policy_unavailable`

### Resource limit exceeded or invalid
Meaning: wall_time_ms or memory_mb is outside the server bounds (see cgal_system_health), or the worker hit its wall-time/memory ceiling.
Do: Reduce the input (simplify first), or pass execution={"wall_time_ms":..., "memory_mb":...} within the reported maxima; do not loop retries.
- `execution_limits`: wall_time_ms or memory_mb outside the allowed bounds reported by cgal_system_health.
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

### Result rejected by its mandatory validator
Meaning: The operation ran but the independent validator did not confirm the result, or the validator could not run. The unverified output is NOT published (job state 'rejected' or 'failed').
Do: Do not use or fabricate the output. Read job.validation[].report for the failed check, loosen the stated bound if the user accepts it, or choose a different operation/recipe.
- `validation_failed`: The validator rejected the output; output not published.
- `validation_report`
- `validation_report_malformed`
- `validation_report_too_large`
- `validator_binding`: A supplied validator binding does not match the registry; validators cannot be spoofed or skipped.
- `validator_not_run`
- `validator_parameter_binding`
- `validator_reference`
- `validator_type`

### Native worker or manifest problem
Meaning: The isolated worker could not start, crashed, spoke an invalid protocol, or its build manifest does not match the registry (installation or build problem, not a problem with your request).
Do: Call cgal_system_health and report its worker/build fields to the user; retry once at most.
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

### Registry, catalog, docs index or guide data problem
Meaning: Server-side data failed to load or validate, or a guide topic does not exist (guide_topic).
Do: For guide_topic use the list returned in details/available topics. Otherwise report the code to the user; the server fails closed rather than guessing.
- `docs_catalog_fallback`
- `docs_index_catalog`
- `docs_index_missing`
- `docs_index_provenance`
- `docs_index_query`
- `docs_index_schema`
- `docs_index_version`
- `docs_search`
- `guide_topic`: Unknown guide topic; the error lists valid topics.
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

## Worker (CGAL-side) codes
UPPER_SNAKE_CASE codes come from the native worker or a validator and are operation specific, e.g. AMBIGUOUS_COMPONENT_TIE, EMPTY_RECONSTRUCTION, HAUSDORFF_WITHIN_MAX_DEVIATION_FAILED, MALFORMED_OFF, MESH_NOT_CLOSED, ROUGHNESS_NOT_REDUCED, VALIDATION_BUDGET_EXCEEDED.
Read error.class first (table above), then the code and message.
