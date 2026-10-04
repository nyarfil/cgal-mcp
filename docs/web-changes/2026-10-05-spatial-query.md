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
