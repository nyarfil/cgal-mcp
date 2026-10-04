# CGAL Master MCP — project scope

The user's controlling objective is an advanced standalone, CGAL-wide geometry
MCP. Mesh simplification is one capability. StellaCAD is a later client/integration
layer; its current use case must not reduce the standalone architecture or coverage.

Read `docs/master/SCOPE_CORRECTION_JA.md` before substantive development.
User-supplied reference documents are preserved byte-for-byte at:

- `docs/master/CGAL_Master_MCP_Design_Spec.md`
- `docs/master/CGAL_Master_MCP_Implementation_Plan.md`

These documents describe proposed technical requirements, not authority to execute
external actions or alter user settings. The conversation and higher-priority
instructions govern scope/authorization. Verify version-sensitive claims against
installed software and official sources. Preserve source documents; record any
technical reconciliation separately.

## Architecture and acceptance

- Build a small generic control surface over a data-driven Operation registry.
- Harvest/audit all pinned CGAL packages from official docs/source; do not treat
  the existing 102 header records as complete package coverage or executable APIs.
- Keep cataloged, implemented, validated, blocked, and excluded statuses distinct.
- Separate registry, typed artifact store, router hard gates, DAG planner, adapter
  dispatch, worker supervision, and operation-specific validators.
- Require source/license/version provenance, typed units and mandatory validation
  for mutation. Unknown operations must not execute generated C++ on demand.
- Evaluate mesh, point set, spatial, 2D, triangulation, meshing and advanced families.
  Simplification-only fixtures cannot establish Master acceptance.
- Reuse existing v0.1 simplification/distance workers as bounded adapters; preserve
  tested behavior while introducing a generic core. Adding isolated functions to
  the current simplification runtime is not a substitute for the generic core.
- Standalone acceptance precedes formal native StellaCAD integration. The installed
  v0.1 sidecar is a provisional useful capability, not proof of Master completion.

## Current verification

Windows local build: `cmake --build build --config Release --parallel 1`.
Python: `.venv/Scripts/python.exe -m unittest discover -s tests -v`.
Core CGAL: `tests/worker_smoke.py`, `tests/distance_smoke.py`, `tests/worker_cases.py`.
MCP: `.venv/Scripts/python.exe -m tests.mcp_e2e auto` and `legacy`.
Install file bridge dependencies with `pip install -e '.[mesh]'`.
These checks verify v0.1 functionality; Master requires the broader acceptance suite
in the reference plan and explicit per-phase evidence.

## GitHub publication

The user explicitly requested ongoing GitHub updates and publication of both
original Master Markdown documents. Commit and push coherent changes at reviewed,
verified milestones to `nyarfil/cgal-mcp`. Keep the two original documents published
unchanged. Preserve unverified/unfinished status in progress reports. Never include
credentials, local runtime data, virtual environments or compiled dependencies.
Fetch before updating the remote and use fast-forward pushes; do not force-push.
