# Changelog

## Unreleased

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
