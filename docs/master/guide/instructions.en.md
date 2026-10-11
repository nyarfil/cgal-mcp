CGAL Master MCP: a data-driven geometry server over CGAL 6.2.1. It registers 228 operations (118 user-facing, 110 independent validators) in 15 families: 7.1 Geometry kernel; 7.2 Spatial queries; 7.3 Mesh inspection and analysis; 7.4 Mesh repair; 7.5 Boolean operations; 7.6 Remeshing and subdivision; 7.7 Simplification; 7.8 Mesh segmentation and decomposition; 7.9 Point-set processing; 7.10 Surface reconstruction; 7.11 Triangulations; 7.12 Polygons, arrangements and offsets; 7.13 Convex hulls and shapes; 7.14 Mesh generation; 7.15 Optimization and numerical geometry. Every operation runs in an isolated native worker; every result must pass a mandatory validator before it is published.

CALL ORDER (do not skip)
1. cgal_get_guide(topic="start") once. It is the quickstart; topics: start, families, recipes, recipe:<id>, op:<operation_id>, family:<id>, errors, glossary, limits-and-status. lang="ja" gives Japanese. Resources cgal://guide/... and prompts (start_here, repair_and_simplify_mesh, reconstruct_surface_from_points, validate_geometry, compare_meshes, 2d_boolean_offset, choose_operation) carry the same content.
2. Discover: if the request matches a workflow, topic="recipes" lists verified recipes (if the user wants X, do these steps). Otherwise cgal_capabilities_search(query=<goal, any language>) then cgal_get_guide(topic="op:<operation_id>") for the complete card (parameters, units, limits, example call).
3. Import inputs: cgal_artifact_import(path, unit, artifact_type) with unit mm, cm or m (mandatory; never guessed). Formats: off, obj, ply, stl, xyz and typed json; at most 512 MiB. Files are parsed, never repaired.
4. cgal_plan(request): {"operation_id", "inputs": {slot: artifact_id}, "parameters"} or a {"steps": [...]} DAG wiring outputs with {"step", "slot"}. Validators are inserted automatically and cannot be skipped. Lengths are {"value", "unit"}.
5. cgal_execute(plan_id) returns a job at once; poll cgal_job_status until succeeded, rejected, failed or cancelled. Read results only from job.outputs (type, unit, properties) and job.validation[].report. cgal_artifact_export writes bytes to a NEW path.

STATUS VOCABULARY (be honest with the user)
Operations: 228 VALIDATED. VALIDATED means executable and replay-verified on bundled fixtures with an independent validator; it is evidence, not a proof for every input. Packages (126 CGAL packages): 45 VALIDATED (have executable operations), 69 CATALOGED (documentation indexed only, NOT executable), 12 EXCLUDED (no standalone headless operation: GUI-only, generic infrastructure, I/O only). Overall acceptance of this server is not claimed here.

CONVENTIONS
Units mm/cm/m per artifact; mixing units in one operation fails with unit_mismatch. Reports are unitless. Coordinates are right-handed Cartesian binary64; outward normals are counter-clockwise. Angles are degrees unless the card says otherwise.

TOOLS (13)
cgal_get_guide (CALL FIRST: guides, cards, recipes), cgal_capabilities_search (rank operations for a goal), cgal_capabilities_describe (raw registry definition), cgal_artifact_import / cgal_artifact_inspect / cgal_artifact_export (move data in and out), cgal_plan (typed immutable plan), cgal_execute / cgal_job_status / cgal_job_cancel (run, poll, stop), cgal_validate (re-check an artifact against its source), cgal_docs_search (pinned CGAL documentation index; documentation is not execution), cgal_system_health (limits, worker build, registry revision).

ARTIFACT TYPES
GeometryAnalysisReport, GeometryQueryReport, ImplicitSurfaceDomain, InterpolationData2, KernelQuerySet, KernelReport, OptimizationReport, PointSet1, PointSet2, PointSet3, PointSet3Normals, Polygon2, Polygon2AnalysisReport, PolygonSoup3, PolygonWithHoles2, QuadraticProgram, RayBatch3, SegmentGraph2, SpatialQueryReport, TetrahedralMesh, TriangleSurfaceMesh, Triangulation2, Triangulation3, ValidationReport. Operation cards name the exact type each input slot accepts and each output slot produces; a JSON report type is read, not imported.

FAIL-CLOSED BEHAVIOUR
The server refuses or fails with a coded error instead of guessing. rejected = a validator did not confirm the result (output unpublished). unmet_precondition = a documented bound or property failed before compute (for example the distance/Hausdorff operations accept at most 400 faces, except mesh.distance.symmetric_hausdorff with validation_mode certified_bvh: up to 2,000,000 faces; every card lists its bounds). resource_limit/timeout = shrink the input or raise execution={"wall_time_ms","memory_mb"} within cgal_system_health maxima. Never retry an unchanged request after invalid_input, unmet_precondition, unsupported_operation or validation failure. Unknown operations are refused; the server never generates C++ on demand.

AMBIGUITY
cgal_plan(goal=...) works only when one operation clearly fits. ambiguous_route (or unsupported_operation with details.options) carries a recorded question and options (operation_id, summary, distinguishing_concepts). Do not guess: ask the user which one, then re-plan with operation_id. Search with query_analysis.abstained=true means nothing executable fits.

NOT SUPPORTED
CATALOGED and EXCLUDED packages (topic "limits-and-status" lists them with reason codes) cannot run; requests naming them fail with details.unsupported_cgal_packages. Say so, offer the nearest executable operation as a question, never as a silent substitute. Other limits: defaults concurrency 2, 4096 MiB per worker, 120 s wall time (cgal_system_health shows live values). On error read topic="errors". Present only numbers that appear in job outputs or validation reports.
