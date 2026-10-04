# WEB change record: Spatial Query 7.2

Date: 2026-10-05 JST  
Branch: `web/spatial-query-7-2-20261005`  
Authoring path: ChatGPT web session using the GitHub connector.

## Rule

Changes made from this web session use commit messages beginning with `WEB:`.
This file is the durable audit trail for those changes.

## Scope

Implement CGAL Master MCP major requirement family 7.2 without changing the
Master MCP into a feature-specific server:

- major.7.2.01 AABB Tree
- major.7.2.02 KD Tree / spatial searching
- major.7.2.03 nearest-neighbor
- major.7.2.04 intersection candidates
- major.7.2.05 bounding boxes

The public MCP surface remains the fixed 12 control tools. Spatial functionality
is added as Registry operations and native worker handlers, with mandatory
validators and independent replay tests.

## External references checked

CGAL 6.2.1 official documentation:

- AABB Tree user manual: https://doc.cgal.org/latest/AABB_tree/
- AABB_tree class: https://doc.cgal.org/latest/AABB_tree/classCGAL_1_1AABB__tree.html
- AABB face-graph triangle primitive: https://doc.cgal.org/latest/AABB_tree/classCGAL_1_1AABB__face__graph__triangle__primitive.html
- dD Spatial Searching manual: https://doc.cgal.org/latest/Spatial_searching/
- Kd_tree: https://doc.cgal.org/latest/Spatial_searching/classCGAL_1_1Kd__tree.html
- K_neighbor_search: https://doc.cgal.org/latest/Spatial_searching/classCGAL_1_1K__neighbor__search.html
- Search_traits_3: https://doc.cgal.org/latest/Spatial_searching/classCGAL_1_1Search__traits__3.html

## Safety / correctness decisions

- Degenerate triangle meshes are rejected before AABB queries because CGAL
  documents degenerate AABB primitives as unsafe/undefined for the standard
  traits.
- Query parameters carry explicit length units and are converted to the source
  artifact unit; no implicit mm assumption.
- Read-only analysis operations publish reports only after deterministic
  producer checks; dedicated validators independently replay the CGAL query.
- Catalog status is not promoted to VALIDATED until the native worker,
  MCP path, and fixed replay harness pass in CI.
- Source artifacts are immutable.

## Web implementation history

The following commits are intentionally retained as separate `WEB:` commits.
Corrections are not squashed so it is possible to audit both the original web
change and its later fix.

- `e7d39ee` — start audit trail.
- `6cc91b3` — add Spatial Query operation interface.
- `83e091b` — first native Spatial Query implementation.
- `809a4b3` — compile Spatial module in cgal-master-worker.
- `94b6ff8` — register ten native operations.
- `6cb0571` — correct CGAL 6.2.1 API usage.
- `d1039da` — first formatting/iterator correction attempt.
- `f6be09b` — add bilingual Spatial routing concepts.
- `4a01568` — enforce precision contracts; KD paths do not silently downgrade exact requests.
- `0924d33` — align validator kernel metadata.
- `26d829b` — register Spatial operations as IMPLEMENTED in bundled Master catalog.
- `834734e` — add dedicated Wave C implementation catalog.
- `cdf4aee` — remove Boolean test's obsolete exact operation-count assumption.
- `39310da` — structure producer diagnostics.
- `b42a6a9` — add native positive/negative acceptance cases.
- `6b2cc14` — add official MCP client auto/legacy E2E cases.
- `f576451` — add non-self-certifying replay gate.
- `5395ebb` — run Spatial replay in Linux and Windows Master CI.
- `bb620fc` — attempted cleanup of literal newline escape artifacts.
- `386f6e0` — actual byte-level correction of those literal escape artifacts.
- `600c625`, `de69f9b`, `2218931` — separate canonical Principal Component Analysis package identity from the LGPL implementation-header provenance.
- `bf190ba` — add Wave C implementation/acceptance contract.

## CI status policy

Older red runs are deliberately left visible. In particular, pre-`386f6e0`
native builds exposed literal `\\n` characters introduced by the web update
path. Those failures remain part of the audit history and are not rewritten.

The current branch must obtain a fresh green run from the post-fix head on both
Ubuntu and Windows VS2022 before any Spatial operation is promoted from
`IMPLEMENTED` to `VALIDATED`.

Formal major-requirement progress remains unchanged until that promotion and the
main acceptance replay independently consume the new evidence.
