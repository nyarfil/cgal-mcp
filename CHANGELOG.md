# Changelog

## Unreleased

- New operation `mesh.boolean.rounded` (status IMPLEMENTED, not independently reviewed) with the
  mandatory validator `mesh.validate.boolean_rounded`: union / intersection / difference of closed
  meshes in general position. The exact Booleans publish only results whose coordinates are exact
  binary64 values and refuse everything else with `OUTPUT_BINARY64_LOSS` (two spheres already
  fail); that error now names `mesh.boolean.rounded` in `suggested_operations`. The rounded
  operation rounds the exact EPECK result to binary64, refuses a result that rounding broke, and its
  validator accepts the candidate only within a stated absolute tolerance of the exact replay
  (closeness, not exact set equality).
- Face bounds raised to 200,000 input faces (1,000,000 output faces) for `mesh.features.detect`,
  `mesh.clip.plane`, `mesh.split.plane`, `mesh.corefine`, `mesh.autorefine` (was 600) and
  `mesh.intersections.do_intersect`, `mesh.intersections.polylines` (was 200). The independent
  validators keep their exact GMP decisions; triangle pairs now reach them through a conservative
  bounding-box hierarchy instead of an all-pairs loop. `mesh.clip.plane`, `mesh.split.plane`,
  `mesh.corefine` and `mesh.autorefine` still require exactly representable output coordinates.
- Registry: 230 operations (228 VALIDATED, 2 IMPLEMENTED), `catalog_revision` `-9`.
- Linux fixes: `reconstruction.poisson` refuses a non-finite implicit function with
  `EMPTY_RECONSTRUCTION` instead of dying on GMP's SIGFPE; the supervisor starts POSIX workers in
  their own session and kills the whole session on timeout, cancel and after exit (a grandchild
  holding the pipes no longer defeats the timeout); on Linux a worker dies with its host
  (`PR_SET_PDEATHSIG`); the symmetric Hausdorff report validator evaluates the verdict rule in
  binary64 like the producer (long double disagreed at an exact tolerance boundary on Linux).
- Replay contract: closed polylines are compared independently of start point and direction; six
  fixture digests corrected to the LF repository content; five numeric expectations that differ
  between MSVC and gcc are now ranges (skeleton vertex counts, Poisson facet counts and radius band,
  one ARAP UV pin removed). Mandatory validators are unchanged.
- Evidence under `docs/master/evidence/` regenerated on Linux (gcc 13.3, OpenGR and SCIP built in):
  80/80 requirements replayed. Earlier evidence was generated on Windows.
- Opt-in AABB-tree and parsed-mesh reuse inside persistent workers
  (`CGAL_MASTER_SESSION_CACHE=1`, requires `CGAL_MASTER_PERSISTENT_WORKERS=1`; default off, one-shot
  path unchanged): per-worker LRU keyed by verified content hash, bounded by count and a memory
  budget accounted in the recycle threshold, results bit-identical to the cold path, hit/miss
  counters in `metrics.session_cache` and job detail. Covers `spatial.aabb.*`,
  `mesh.location.locate` (AABB strategy) and `mesh.distance.symmetric_hausdorff` (parsed mesh).

## 1.0.0 - 2026-10-11

- The Master MCP (`cgal_mcp.master`) is now the primary and only supported server.
  Console script `cgal-mcp` runs it (default transport: stdio).
- Removed the `cgal-master-mcp` entry point (use `cgal-mcp`).
- The v0.1 simplification server is deprecated and superseded. It remains available as
  `cgal-mcp-legacy` / `python -m cgal_mcp.server` for compatibility tests only.
- README rewritten for Master. Status stays honest: 80/80 per-requirement replay
  validation; standalone acceptance gates (search, host matrix, performance/AABB,
  package-harvest license review) are unmet and `standalone_accepted` is false.
- StellaCAD registers the Master server as `cgal-mcp` (derived-file adapter only;
  native CADHost/Undo integration is not implemented).
