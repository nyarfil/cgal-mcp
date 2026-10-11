# Quickstart

## 1. Find the operation
- Known workflow? cgal_get_guide(topic="recipes") then topic="recipe:<id>". Otherwise cgal_capabilities_search(query=<goal in any language>).
- Read candidates: operation_id, status, score, why, input_types, output_types, route_supported. query_analysis.abstained=true means nothing relevant is executable: say so.
- Then read the card: cgal_get_guide(topic="op:<operation_id>") (parameters, units, limits, an example).

## 2. Import inputs
- cgal_artifact_import(path, unit, artifact_type?) copies the file into immutable storage and parses it (no repair). Returns artifact_id, type, unit, properties. The path must be readable by the server.
- Pass artifact_type when the extension is ambiguous (json, xyz). Unit is mandatory: mm, cm or m.

## 3. Plan
- Single operation: cgal_plan(request={"operation_id": ..., "inputs": {<slot>: <artifact_id>}, "parameters": {...}}). Pipeline: request={"steps": [{"id", "operation", "inputs": {<slot>: <artifact_id> | {"step": id, "slot": output_slot}}, "parameters"}]}.
- Mandatory validators are inserted for you; the plan lists them with estimate (cost tier, risk). Planning failures happen before any compute.

## 4. Execute and read
- cgal_execute(plan_id[, execution={"wall_time_ms", "memory_mb"}]) returns job_id at once. Poll cgal_job_status(job_id) every second or two until state is succeeded, rejected, failed or cancelled.
- On succeeded: job.outputs[] hold artifact_id, type, unit, format, sha256, properties; job.validation[] hold each validator report. Report numbers from these, never invent them.
- cgal_artifact_inspect(artifact_id) for metadata and provenance; cgal_artifact_export(artifact_id, path) writes the exact bytes to a NEW path.
- rejected/failed: read job.error {class, code, message}; see topic 'errors'. Do not present rejected output as a result.

## 5. Worked example (hull.convex_3)
Example call (fixture-backed; source: workflow wf19-hull3-loop-measures)
1. cgal_artifact_import {"artifact_type": "PointSet3", "path": "tests/fixtures/master/cube_with_interior.xyz", "unit": "mm"}  -> artifact_id, call it $cube_with_interior
2. cgal_plan {"request": {"inputs": {"points": "$cube_with_interior"}, "operation_id": "hull.convex_3", "parameters": {}}}  (replace each $name by the artifact_id from the import)
3. cgal_execute {"plan_id": <plan_id>}  ->  cgal_job_status {"job_id": <job_id>} until state is succeeded/rejected/failed

## Rules of thumb
- Never guess units, operation ids or parameters; read the card.
- If the server refuses, relay the refusal; do not work around validators or route to an unsupported package.
- Several goals match equally (ambiguous_route)? ask the user, then plan with operation_id.
- Prompts: start_here, repair_and_simplify_mesh, reconstruct_surface_from_points, validate_geometry, compare_meshes, 2d_boolean_offset, choose_operation.
