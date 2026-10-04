# StellaCAD CGAL Master MCP 実装計画書

**文書ID:** SC-CGAL-MCP-PLAN-001  
**版:** 1.0  
**基準日:** 2026-10-04  
**対象:** CGAL 6.2.1 / MCP 2026-07-28 / Python MCP SDK 2.2.0  
**状態:** 引き継ぎ用・実装基準文書

---

## 0. この文書の最重要ルール

本プロジェクトの目的は **CGALを「メッシュ軽量化ライブラリ」としてStellaCADへ追加することではない**。

目的は、CGALが持つ計算幾何機能を、AIエージェントが **発見・選択・組み合わせ・検証・実行** できる汎用Geometry MCPとして構築し、その完成後にStellaCADへ統合することである。

Surface Mesh Simplification、Hausdorff距離、Polyhedral Envelopeは重要なユースケースではあるが、**CGAL Master MCP全体の一機能群にすぎない**。

### 0.1 引き継ぎ先が変更してはならない事項

1. 「軽量化専用MCP」「メッシュ専用MCP」へ縮小しない。
2. CGALの機能を人手で数十個だけ選んで固定しない。
3. 全MCP tool定義を常時LLMコンテキストへ投入しない。
4. LLMに生のCGAL C++ APIを毎回直接生成させる設計にしない。
5. 便利だが未登録・未発見のCGAL機能が死蔵される構造にしない。
6. CGALの更新でパッケージ再編・API変更が起きても追従できない静的設計にしない。
7. geometry mutationを検証なしで成功扱いしない。
8. Python bindingsだけを唯一の実行基盤にしない。
9. StellaCAD本体とCGALのテンプレート・依存関係を密結合させない。
10. GPL/LGPL/商用ライセンス情報を機能カタログから落とさない。

この10項目に反する変更は「簡略化」ではなく**設計逸脱**として扱う。

---

# 1. プロジェクト目標

## 1.1 最終目標

AIから次のような自然言語要求を受けた場合に、CGALの適切なアルゴリズム群を自動で探索・計画・実行・検証できること。

- 「このメッシュを形状誤差0.05 mm以内で可能な限り軽量化」
- 「自己交差と穴を直してwatertightにして」
- 「この2つのシェルのBoolean differenceが失敗する原因を解析して直して」
- 「点群から表面を再構築して」
- 「この形状をセグメント分割して機能候補を抽出」
- 「AABBで衝突候補を絞って厳密交差判定」
- 「2D輪郭からstraight skeletonを求めてオフセット」
- 「Voronoi / Delaunay / Alpha Shapeを使って適切な構造を作成」
- 「表面上の最短経路を求める」
- 「3D mesh生成条件を満たすようにvolume meshを作る」
- 「この処理に使えるCGAL機能を探し、候補を比較してから実行」

AIはCGALのクラス名を知っている必要がない。MCP側がCGALの知識基盤を持つ。

## 1.2 成功条件

完成条件は「simplifyが動く」ではない。以下を満たして初めてCGAL Master MCP v1完成とする。

- CGAL 6.2.1の**全パッケージを機能カタログの探索対象**にできる。
- 主要パッケージは高レベルOperationとして実行可能。
- 未ラップ機能も公式docs/examples/source indexから発見できる。
- Capability Routerが自然言語要求から適切なOperation候補を返す。
- Plannerが前処理・本処理・検証・フォールバックをDAGとして構成できる。
- geometry mutation後は型・トポロジ・数値誤差など、Operationに対応する検証を行える。
- 100種類以上の機能が存在しても、それらの全schemaを常時LLMへ載せない。
- 新CGAL版でpackage/API差分を検知できる。
- StellaCADとはartifact/operation境界で接続可能で、CGAL依存をUI・CADコアに漏らさない。

---

# 2. 2026-10-04時点の技術基準

## 2.1 CGAL

本番ベースラインは **CGAL 6.2.1** とする。CGAL公式は6.2.1を2026年9月リリースの最新stableとしている。

CGAL 6.2ではPolygon Mesh Processingが再編され、少なくとも以下が独立したパッケージへ整理された。

- Polygon Mesh Processing core
- Boolean Operations on Meshes
- Meshing and Remeshing of Polygon Meshes
- Polygon Mesh Repair

したがってMCPカタログは「昔のPMP一枚岩」前提で作らない。

CGAL 6.2.1はC++17以上、CMake 3.22以上を要求し、WindowsではVisual C++ 17.14（VS2022）等が継続テスト対象。CGAL本体は5.0以降header-onlyだが、GMP/MPFR等の依存は別途存在する。

## 2.2 MCP

MCP基準は **2026-07-28 revision**。

Python側は **MCP Python SDK v2系**を使用する。2026-10-04時点の公式GitHub latest releaseはv2.2.0。

重要な設計前提:

- modern MCPは`server/discover`を使用する。
- `tools/list` / `resources/list` / `resources/read`等はcache hintを持てる。
- 2026-07-28ではツール・Resource定義をキャッシュ可能。
- Tasks extensionはdraftであり、Python SDKの必須基盤にはしない。
- 長時間処理はMCP Tasksに依存せず動作する設計とし、Tasks対応は追加機能扱い。

## 2.3 Python bindingsの扱い

2026 GSoCにより新しいCGAL Python bindingsは大幅に改善し、Surface Mesh関連を含む9パッケージ、Named Parameters、property maps、visitors、NumPy連携、Windows CI等が拡張された。

ただしMaster MCPの実行基盤をPython bindingsのcoverageへ制限してはならない。

**方針:**

- Primary execution: C++ CGAL Worker
- MCP/control plane: Python
- Python bindings: プロトタイピング、比較、補助backend

---

# 3. 全体アーキテクチャ計画

```text
AI / StellaCAD / Cursor / Codex / Claude
                 |
                 | MCP
                 v
+---------------------------------------------+
| CGAL Master MCP Server (Python)             |
|                                             |
|  Control Tools                              |
|  Capability Search / Describe               |
|  Semantic Router                            |
|  Workflow Planner                           |
|  Schema + Preconditions                     |
|  Validator Selector                         |
|  Artifact Manager                           |
|  Documentation / Source Search              |
|  Execution Supervisor                       |
+-----------------------+---------------------+
                        |
           Control-plane JSON-RPC
           Data-plane artifact handles
                        |
                        v
+---------------------------------------------+
| cgal-worker (C++17)                         |
|                                             |
| Kernel / Primitive adapters                 |
| Mesh adapters                               |
| Point-set adapters                          |
| 2D/3D triangulation adapters                |
| Arrangement / Polygon adapters              |
| Spatial query adapters                      |
| Meshing adapters                            |
| Reconstruction adapters                     |
| Optimization / analysis adapters            |
| ...                                         |
+-----------------------+---------------------+
                        |
                        v
                    CGAL 6.2.1
```

### 設計思想

LLMへ100+個の巨大tool schemaを常時見せるのではなく、常駐するのは少数の**control-plane tools**のみ。

全CGAL能力はCapability Registryに保持し、必要なOperation schemaだけを遅延取得する。

---

# 4. MCP公開面の計画

## 4.1 常時公開するControl Tools

原則として以下だけを常時`tools/list`へ載せる。

1. `cgal.capabilities.search`
2. `cgal.capabilities.describe`
3. `cgal.plan`
4. `cgal.execute`
5. `cgal.validate`
6. `cgal.artifact.inspect`
7. `cgal.docs.search`
8. `cgal.system.health`

必要に応じて追加:

9. `cgal.plan.explain`
10. `cgal.operation.schema`
11. `cgal.operation.compare`
12. `cgal.pipeline.execute`

### 理由

- コンテキスト消費を小さくする。
- tool choiceの探索空間を制限する。
- CGALの追加機能をMCP tool数の爆発なしで追加する。
- 100～1000 Operationまで自然にスケールする。

## 4.2 Operation Registry

CGALの実処理はToolではなくOperationとして管理する。

例:

```text
mesh.analysis.self_intersections
mesh.analysis.distance.hausdorff
mesh.repair.stitch_borders
mesh.repair.remove_degenerate_faces
mesh.boolean.corefine_union
mesh.boolean.corefine_difference
mesh.remesh.isotropic
mesh.simplify.edge_collapse
mesh.simplify.envelope_bounded
mesh.segment.sdf
mesh.parameterize.lscm
mesh.path.shortest
pointset.remove_outliers
pointset.smooth.jet
pointset.reconstruct.poisson
spatial.aabb.intersections
triangulation.delaunay_2
triangulation.delaunay_3
polygon.straight_skeleton.interior
polygon.offset.interior
arrangement.overlay
hull.convex_3
alpha_shape.3d
mesh3.generate
optimization.linear
```

この一覧は手作業だけで固定せず、公式docs/headers/examplesから生成・監査する。

---

# 5. Capability Registry実装計画

## 5.1 1 Operationに必須のメタデータ

```yaml
id: mesh.simplify.envelope_bounded
version: 1
cgal:
  version_min: 6.2
  package: Triangulated Surface Mesh Simplification
  headers:
    - CGAL/Surface_mesh_simplification/edge_collapse.h
license:
  family: GPL
intent:
  - simplify mesh
  - reduce polygon count
  - preserve shape within tolerance
input_types:
  - TriangleSurfaceMesh
output_types:
  - TriangleSurfaceMesh
preconditions:
  - oriented_2_manifold_preferred
  - triangulated
parameters:
  tolerance:
    type: length
    required: true
risks:
  topology_change: possible
  geometry_change: true
validators:
  - mesh.analysis.distance.hausdorff
  - mesh.analysis.self_intersections
  - mesh.analysis.manifold
alternatives:
  - mesh.simplify.edge_collapse
examples:
  - simplify within 0.05 mm
```

## 5.2 Registryの情報源

優先順位:

1. インストール済みCGALと同一versionのDoxygen/XML/HTML
2. CGAL package metadata
3. CGAL `examples/`
4. 公開headers
5. tests
6. release notes / changelog
7. hand-authored semantic metadata

**LLMの記憶だけからAPI catalogを作らない。**

## 5.3 Registry DB

- canonical source: versioned YAML/JSON
- runtime index: SQLite
- lexical retrieval: FTS5
- semantic retrieval: optional embedding index
- graph: SQLite tablesまたは軽量graph representation
- generated docs: Markdown / JSON Schema

---

# 6. Tool選択器の実装計画

単純な「キーワード→関数」では不足する。

## 6.1 選択パイプライン

```text
User Intent
   |
   v
Intent Normalization
   |
   v
Input Artifact Type Detection
   |
   v
Hard Constraint Gate
   |
   v
Lexical + Semantic Candidate Retrieval
   |
   v
Precondition Compatibility Filter
   |
   v
Risk / Accuracy / Cost Ranking
   |
   v
Operation Candidate Set
   |
   v
Workflow Planner
   |
   v
Required Validators + Fallbacks
```

## 6.2 Hard Gate

LLMの好みより先に決定論的制約を適用する。

例:

- inputがtriangle meshでない → triangulate前処理が必要
- closed volume必須 → `does_bound_a_volume`相当検査
- 2-manifold必須 → manifold検査
- exact predicateが必要 → kernel条件を変更
- tolerance未指定 → operationが安全に推論できない場合はPlannerが不足情報として扱う
- package license不許可 →候補除外

## 6.3 Candidate score

概念式:

```text
score =
  intent_similarity
+ type_match
+ precondition_match
+ proven_workflow_prior
+ validation_coverage
+ version_confidence
- destructive_risk
- conversion_cost
- runtime_cost
- unsupported_feature_penalty
```

重みは設定可能にする。AIが勝手に重みを書き換えない。

## 6.4 Workflow templates

代表処理は「単一API」ではなく既知のworkflowとして登録する。

例: tolerance bounded simplification

```text
inspect
 -> repair_if_required
 -> feature_detection
 -> constraint_generation
 -> simplification
 -> symmetric_distance_validation
 -> topology_validation
 -> report
```

こうすることで、便利な検証機能が存在するのに使われない問題を抑止する。

---

# 7. CGAL能力範囲

以下は**最低限の能力群**であり、範囲上限ではない。実際のcatalogはCGAL 6.2.1 Package Overviewから生成する。

## 7.1 Geometry Kernel / primitives

- Cartesian / exact-predicate kernels
- point / vector / line / ray / segment / plane / sphere / triangle / tetrahedron等
- predicates / constructions
- intersections
- distances

## 7.2 Spatial query

- AABB Tree
- KD Tree / spatial searching
- nearest-neighbor
- intersection candidates
- bounding boxes

## 7.3 Polygon Mesh Processing core

- predicates
- components
- normals
- measures
- feature detection
- distances
- intersections / self-intersection
- location

## 7.4 Mesh Repair

- orientation
- stitching
- degenerate element repair
- hole filling
- polygon soup repair
- manifold-related preprocessing

## 7.5 Boolean Operations

- corefinement
- union / intersection / difference
- clipping
- splitting
- slicing

## 7.6 Meshing / Remeshing

- triangulation
- refinement
- isotropic remeshing
- smoothing / optimization
- adaptive processing

## 7.7 Surface Mesh Simplification

- edge collapse
- Lindstrom-Turk
- Garland-Heckbert families
- placement/cost/constraints
- Polyhedral Envelope filter
- bounded normal-change constraints

**注意:** この節はMCP全体の一部である。

## 7.8 Mesh analysis / decomposition

- SDF segmentation
- Approximate Convex Decomposition
- skeletonization
- shortest path
- parameterization
- subdivision

## 7.9 Point Set Processing

- normal estimation
- outlier removal
- smoothing
- simplification
- registration-related primitives
- reconstruction preprocessing

## 7.10 Surface Reconstruction

- Poisson
- advancing front等、CGALに存在するreconstruction family
- wrapping系

## 7.11 2D / 3D triangulations

- Delaunay
- constrained triangulation
- regular triangulation
- periodic/spherical variants where available
- Voronoi duals

## 7.12 Polygon / Arrangement

- Polygon 2D operations
- arrangements
- overlay
- Boolean polygon set operations
- straight skeleton
- offsets
- Minkowski-related operations

## 7.13 Shapes / Hulls

- convex hull 2D/3D
- alpha shapes
- alpha wrapping
- bounding volumes
- barycentric coordinates

## 7.14 Mesh generation

- Mesh_2
- Surface_mesh generation
- Mesh_3 / tetrahedral volume meshing
- domain criteria

## 7.15 Optimization / numerical geometry

- linear/quadratic programming interfaces
- interpolation
- approximation
- matrix-search-related geometry support

**Acceptance rule:** 上記に載っていないCGAL packageも、catalog harvesterが発見・検索できなければならない。

---

# 8. C++ Worker実装計画

## 8.1 Worker分離

CGALはtemplate-heavyであり、assert/exception/巨大メモリ消費をStellaCAD本体やMCPサーバーへ波及させないため別process化する。

初期構成:

```text
cgal-worker-core.exe
cgal-worker-mesh.exe
cgal-worker-pointset.exe
cgal-worker-triangulation.exe
cgal-worker-advanced.exe
```

ただしmodule数は性能計測後に統合可能。

## 8.2 Control/Data plane分離

大きなmeshをJSONへ埋め込まない。

Control plane:

- Operation ID
- parameter
- artifact ID
- execution option

Data plane:

- managed local artifact
- PLY/OFF/OBJ/STL等
- internal binary cache

## 8.3 IPC

v1はローカル専用で十分。

推奨:

- JSON-RPC 2.0 over stdio または Named Pipe
- large dataはartifact handle
- stdout protocol contamination禁止
- logsはstderr / structured log

---

# 9. Artifact System計画

AIがfile pathを直接雑に扱うのではなく、MCP内部でartifact化する。

```text
artifact_id: art_01J...
type: TriangleSurfaceMesh
format: ply
units: mm
source: fusion-export
hash: sha256:...
immutable: true
metadata:
  vertices: 19123
  faces: 38214
  closed: false
```

Mutationは新artifactを作る。

```text
original -> simplified -> validated
```

provenanceを残し、元データを破壊しない。

---

# 10. 検証システム計画

各Operationにvalidator policyを持つ。

例:

| Operation | 必須検証例 |
|---|---|
| simplification | Hausdorff / normal / self-intersection / manifold |
| boolean | volume validity / self-intersection / expected component |
| repair | defect count before/after |
| remesh | topology / boundary preservation / quality metrics |
| reconstruction | watertight / components / deviation if reference exists |
| tetrahedral mesh | cell validity / criteria |

結果は必ずmachine-readableにする。

```json
{
  "status": "pass",
  "checks": [
    {"id":"self_intersections","value":0,"pass":true},
    {"id":"hausdorff_max_mm","value":0.0471,"limit":0.05,"pass":true}
  ]
}
```

---

# 11. Documentation / Long-tail Search計画

「便利な機能があるのにMCPが知らない」を撲滅するため、catalog外検索を正式機能にする。

## 11.1 Index対象

インストールしたCGAL versionと同一の:

- Package Overview
- user manuals
- reference pages
- examples
- header symbols
- changelog
- known deprecations

## 11.2 検索フロー

```text
Capability Registry miss
       |
       v
Local Docs FTS search
       |
       v
Header/Symbol search
       |
       v
Examples search
       |
       v
Candidate API discovery
       |
       v
Known adapter exists? ---- yes -> execute
       |
       no
       v
Report unsupported adapter + generated implementation candidate
```

MCP自身が本番実行時に勝手にC++コードをコンパイルして未知APIを使用することはv1では禁止。

---

# 12. 実装フェーズ

## Phase 0 — Baseline lock

### 作業

- CGAL 6.2.1 pin
- MCP Python SDK 2.2.0 pin
- C++ compiler / CMake version固定
- dependencies manifest作成
- license inventory開始

### 完了条件

- clean Windows machine相当でreproducible build
- version report JSON出力

---

## Phase 1 — Catalog Harvester

### 作業

- CGAL package overview parser
- Doxygen metadata parser
- headers symbol extractor
- examples indexer
- package/license/version metadata抽出

### 完了条件

- 全packageがcatalog DBに登場
- package → docs → headers → examplesを相互参照可能
- unclassified package = 0を目標

---

## Phase 2 — Capability Registry & Search

### 作業

- Operation schema v1
- FTS5 index
- semantic alias辞書
- 日本語/英語intent aliases
- capability search API

### 完了条件

- 代表200クエリでtop-k retrieval評価
- 「簡略化」以外の全domainを含める

---

## Phase 3 — C++ Worker Foundation

### 作業

- worker protocol
- artifact loader/saver
- kernel policy
- exception boundary
- timeout/cancel boundary
- structured diagnostics

### 完了条件

- crashしたworkerをMCPが復旧可能
- stdout汚染なし
- artifact input/output round-trip

---

## Phase 4 — MCP Control Plane

### 作業

- MCPServer v2
- stdio
- Streamable HTTP
- `server/discover`
- tool/resource cache hints
- schemas
- structured output

### 完了条件

- MCP conformance tests
- Cursor/Codex/Claude系hostの最低2種で接続試験

---

## Phase 5 — Router v1

### 作業

- intent normalization
- type gate
- candidate retrieval
- deterministic precondition filtering
- ranker
- explanation output

### 完了条件

- benchmark intent setでtop-1/top-3測定
- unsupported要求を無理に別toolへ誤ルートしない

---

## Phase 6 — Planner v1

### 作業

- Operation DAG
- preprocess/postprocess rules
- validator injection
- fallback chain
- cost/risk estimate

### 完了条件

- 代表workflow 30本以上
- single-operation biasを防ぐ

---

## Phase 7 — Major Capability Implementation

優先実装順は「StellaCADへの有用度」だけでなく、CGAL全体を使える基盤の確認を兼ねる。

### Wave A: Mesh foundation

- inspection
- distance
- intersection
- repair
- boolean
- remesh
- simplification

### Wave B: Spatial / point set / reconstruction

- AABB
- spatial search
- point-set processing
- surface reconstruction

### Wave C: 2D geometry

- polygons
- arrangements
- straight skeleton
- offsets
- triangulation 2D

### Wave D: 3D geometry

- triangulation 3D
- hulls
- alpha shapes/wrapping
- mesh generation

### Wave E: specialized packages

- parameterization
- shortest paths
- segmentation
- decomposition
- skeletons
- optimization/interpolation
- remaining package families

### 完了条件

- package coverage report生成
- 「catalog-only」「implemented」「validated」を明確に分離

---

## Phase 8 — Validator Framework

### 作業

- invariant library
- distance validation
- topology validation
- tolerance units
- validation recipe catalog

### 完了条件

- mutating Operationにvalidation recipe未設定ならCI失敗

---

## Phase 9 — Robustness / Failure Knowledge

### 作業

- failure taxonomy
- known CGAL issue mapping
- retry policy
- alternate algorithm policy
- artifact minimization for bug repro

### 完了条件

- segfault/exception/timeout/invalid geometryを区別
- silent success禁止

---

## Phase 10 — Performance

### 作業

- persistent workers
- artifact cache
- AABB reuse
- parallel-safe Operation検証
- memory limits
- profiling

### 完了条件

- representative small/medium/large modelsで基準値作成
- idle時StellaCADへ不要なメモリ負荷を与えない

---

## Phase 11 — Full Coverage Audit

### 作業

- Package Overviewとの差分
- docs indexとの差分
- unwrapped high-value candidates
- obsolete/deprecated operation
- license check

### 完了条件

以下の4分類をCGAL全packageについて出力可能:

```text
IMPLEMENTED
CATALOGED
BLOCKED_BY_DEPENDENCY
EXCLUDED_WITH_REASON
```

理由なしの未収録は禁止。

---

## Phase 12 — StellaCAD Integration Designへ移行

Master MCPが独立で合格してから実施。

この段階で初めて:

- StellaCAD document/object mapping
- selection/face/edge/vertex mapping
- undo/redo
- persistent geometry IDs
- FreeCAD/OpenCascade bridge
- project artifact storage
- GUI commands
- AI intent handoff

を設計する。

**MCP完成前にStellaCAD都合でCGAL能力を削らない。**

---

# 13. テスト計画

## 13.1 Unit

- schema
- router filters
- planner graph
- artifact hashes
- unit conversion
- each C++ adapter

## 13.2 Golden geometry

- primitive geometries
- intentionally broken meshes
- open/closed/manifold/non-manifold
- self-intersecting
- high aspect ratio
- tiny numerical scale
- large coordinates

## 13.3 Regression corpus

CGAL upstream issueで再現可能なgeometryも、ライセンス確認の上でrepro corpusへ追加する。

例としてSurface Mesh Simplificationには過去にconstraint条件で停止し続ける報告や、特定policyで異常な頂点placementが発生した事例があるため、timeoutとpost-validationを必須設計とする。

## 13.4 Router benchmark

最低200～500 intent。

カテゴリ均等化し、mesh simplification比率を意図的に低くする。

例:

- mesh: 25%
- point set/reconstruction: 15%
- 2D geometry: 15%
- triangulation/spatial: 15%
- meshing: 10%
- analysis/path/parameterization: 10%
- other/specialized: 10%

## 13.5 Acceptance

- top-3 capability recall >= 95%（benchmark定義後）
- destructive workflowのvalidator omission = 0
- cataloged package coverage = 100%
- implemented major-family coverage target >= 90%（関数単位ではなく承認済Capability family単位）
- crash containment 100%

---

# 14. ライセンス計画

CGALはdual-licenseで、各packageにはGPL/LGPL等の区分がある。CGAL公式はOpen Source条件に従わない利用にはcommercial licenseを案内している。

そのためCapability Registryに必ずlicense metadataを持つ。

```text
operation -> CGAL package -> package license
```

StellaCADをclosed-source配布する場合、プロセス分離しただけでGPL義務が自動的に消えるとは判断しない。最終配布モデルは別途法務・ライセンス判断が必要。

MCP設計段階では:

- package license可視化
- build manifest記録
- commercial-license modeを想定
- optional packageをfeature flag化

まで実装する。

---

# 15. 更新戦略

## 15.1 Stable-first

- 本番はCGAL stable pin
- main/master直追従は禁止
- 次stableが出たら差分CI

## 15.2 Update pipeline

```text
new CGAL release
  -> download/index
  -> package diff
  -> symbol diff
  -> example diff
  -> deprecation diff
  -> license diff
  -> adapter compile matrix
  -> regression test
  -> catalog version bump
```

## 15.3 AIの最新情報利用

MCP実行中に毎回Web検索する設計にはしない。

代わりに、version-pinned official docs/source indexをローカルに保持する。更新作業時のみ公式情報を同期する。

これにより再現性と最新性を両立する。

---

# 16. 納品物

CGAL Master MCP v1の納品物は最低限以下。

```text
/cgal-master-mcp
  /server
  /router
  /planner
  /registry
  /workers
  /adapters
  /schemas
  /artifacts
  /docs_index
  /tests
  /benchmarks
  /scripts
  /licenses
  CMakeLists.txt
  pyproject.toml
  uv.lock
  README.md
```

加えて:

- generated capability catalog
- package coverage report
- license report
- router benchmark report
- geometry regression report
- MCP conformance report

---

# 17. Definition of Done

以下を全て満たすまで「完成」と呼ばない。

- [ ] CGAL 6.2.1全packageをcatalog harvesterが認識
- [ ] 少数Control Toolsで全Operationへ到達可能
- [ ] docs/source long-tail searchが利用可能
- [ ] Routerが型・前提条件・精度・riskを考慮
- [ ] Plannerがvalidatorを自動挿入
- [ ] C++ worker crashがMCP/StellaCADへ伝播しない
- [ ] geometry artifact provenanceが保持される
- [ ] major capability familyが実装・テスト済み
- [ ] 未実装packageは理由付きで報告
- [ ] CGAL package licenseがOperationまで追跡可能
- [ ] MCP 2026-07-28互換
- [ ] Python MCP SDK v2でconformance確認
- [ ] Windows 11 / VS2022環境で再現build
- [ ] simplification以外のbenchmarkが十分含まれる
- [ ] StellaCAD統合前にStandalone MCPとして受入試験合格

---

# 18. 公式情報源（2026-10-04確認）

1. CGAL latest stable / releases  
   https://www.cgal.org/releases.html
2. CGAL 6.2.1 Manual  
   https://doc.cgal.org/latest/Manual/index.html
3. CGAL Package Overview  
   https://doc.cgal.org/latest/Manual/packages.html
4. CGAL Polygon Mesh Processing 6.2.1  
   https://doc.cgal.org/latest/Polygon_mesh_processing/
5. CGAL Surface Mesh Simplification  
   https://doc.cgal.org/latest/Surface_mesh_simplification/
6. CGAL compiler/dependency requirements  
   https://doc.cgal.org/latest/Manual/thirdparty.html
7. CGAL CMake usage  
   https://doc.cgal.org/latest/Manual/devman_create_and_use_a_cmakelist.html
8. CGAL License  
   https://www.cgal.org/license.html
9. MCP Python SDK  
   https://github.com/modelcontextprotocol/python-sdk
10. MCP Python SDK releases  
    https://github.com/modelcontextprotocol/python-sdk/releases
11. MCP Python SDK v2 notes  
    https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/whats-new.md
12. MCP caching behavior  
    https://py.sdk.modelcontextprotocol.io/client/caching/
13. MCP Skills extension  
    https://skills.extensions.modelcontextprotocol.io/specification/stable/skills
14. CGAL Python bindings GSoC 2026 summary  
    https://github.com/CGAL/cgal/issues/9610

---

## 付記

この計画書における「CGALを完璧に使いこなす」とは、CGALの全template/APIを1対1でMCP tool化することではない。

**必要な能力を漏れなく発見し、適切なAPI/アルゴリズムを選び、必要な前処理・検証を組み合わせ、未実装部分も明示的に発見可能にすること**を意味する。

この方針が、100種類を超える機能を持ちながらプロンプト肥大化とtool死蔵を同時に避けるための中心設計である。
