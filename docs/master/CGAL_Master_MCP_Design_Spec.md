# StellaCAD CGAL Master MCP 設計仕様書

**文書ID:** SC-CGAL-MCP-DESIGN-001  
**版:** 1.0  
**基準日:** 2026-10-04  
**対象:** CGAL Master MCP standalone v1  
**次工程:** Standalone MCP受入後にStellaCAD統合設計を確定

---

# 0. 設計宣言

本システムは**CGAL全体のAI利用基盤**である。

`mesh.simplify.*`はその一部であり、システム構造・API・テスト・評価指標をSurface Mesh Simplification中心に設計してはならない。

CGALのPackage Overviewに将来追加される機能も、MCPサーバー自体の大改造なしにCatalogへ追加・検索・adapter実装へ昇格できることを設計条件とする。

---

# 1. 要求仕様

## 1.1 Functional Requirements

### FR-001 Capability Discovery

自然言語intent、artifact type、制約、desired outputからCGAL capability候補を検索できること。

### FR-002 Capability Description

各capabilityについて以下を取得できること。

- 何をするか
- input/output type
- preconditions
- parameters
- algorithm alternatives
- accuracy/robustness notes
- mutability
- expected validators
- CGAL package/header/example
- CGAL version
- license
- implementation status

### FR-003 Planning

複数OperationをDAGとして組み合わせられること。

### FR-004 Execution

OperationをC++ workerで実行できること。

### FR-005 Validation

geometry mutation後の品質・不変条件をOperation別に検証できること。

### FR-006 Artifact Management

入力・出力geometryをimmutable artifactとして管理できること。

### FR-007 Long-tail Discovery

未登録OperationでもCGAL公式docs/headers/examplesから関連APIを検索できること。

### FR-008 Coverage Audit

CGAL Package OverviewとCapability Registryの差分を出せること。

### FR-009 Version Awareness

CGAL versionによるpackage/API差分を識別できること。

### FR-010 License Awareness

Operationごとのpackage licenseを取得できること。

### FR-011 Diagnostics

失敗を以下のレベルで区別すること。

- invalid input
- unmet precondition
- unsupported adapter
- CGAL precondition/assertion
- numeric failure
- timeout
- worker crash
- resource limit
- validation failure

### FR-012 Explainability

Router/Plannerが「なぜそのOperationを選んだか」をstructured resultで返せること。

### FR-013 Multiple Frontends

Standalone MCPとしてCursor/Codex/Claude/StellaCAD等から利用できること。

### FR-014 Dynamic Expansion

新Operation追加時にcontrol tool数を原則増やさないこと。

### FR-015 Safety Gate

destructive/mutating Operationは入力artifactを上書きしないこと。

---

## 1.2 Non-Functional Requirements

### NFR-001 Context Efficiency

CGALの全function schemaをLLM contextへ常時ロードしない。

### NFR-002 Reproducibility

CGAL version、compiler、worker build、parameters、input hashを実行結果へ保存する。

### NFR-003 Crash Isolation

worker crashでMCP serverやStellaCADを落とさない。

### NFR-004 Performance

大規模mesh/point setをJSON payloadへ展開しない。

### NFR-005 Extensibility

新package追加時はRegistry + Adapter追加で対応し、Router本体の分岐増殖を避ける。

### NFR-006 Deterministic Guardrails

型・precondition・license・mutation riskはLLM判断だけに依存しない。

### NFR-007 Observability

全実行にtrace IDを付与し、planner decisionとworker metricsを追跡可能にする。

### NFR-008 Offline Capability

version-pinned docs indexをローカル利用できること。

### NFR-009 Windows First

Windows 11 / VS2022をfirst-class環境とする。

### NFR-010 Backward Compatibility

MCP 2026-07-28をprimaryとしつつ、公式SDKがサポートするlegacy client互換を阻害しない。

---

# 2. システム構成

```text
+------------------------------------------------------------+
| MCP HOST                                                   |
| StellaCAD / Codex / Cursor / Claude / other client         |
+-------------------------------+----------------------------+
                                |
                                | MCP 2026-07-28
                                v
+------------------------------------------------------------+
| CGAL MASTER MCP                                            |
|                                                            |
| +------------------+   +--------------------------------+  |
| | MCP Interface    |-->| Request Normalizer             |  |
| +------------------+   +---------------+----------------+  |
|                                         |                  |
|                              +----------v----------+       |
|                              | Capability Router   |       |
|                              +----------+----------+       |
|                                         |                  |
|            +----------------------------+--------------+   |
|            |                                           |   |
| +----------v----------+                       +--------v--+ |
| | Capability Registry |                       | Docs/Code | |
| | SQLite + manifests  |                       | Index     | |
| +----------+----------+                       +-----------+ |
|            |                                               |
|            v                                               |
| +----------+----------+                                    |
| | Workflow Planner    |                                    |
| +----------+----------+                                    |
|            |                                               |
| +----------v----------+      +---------------------------+ |
| | Policy / Validator  |----->| Artifact Manager          | |
| +----------+----------+      +---------------------------+ |
|            |                                               |
| +----------v---------------------------------------------+ |
| | Worker Supervisor                                      | |
| +----------+---------------------------------------------+ |
+------------|------------------------------------------------+
             |
             | local IPC + artifact handles
             v
+------------------------------------------------------------+
| CGAL C++ WORKER LAYER                                      |
| core | mesh | pointset | triangulation | meshing | other   |
+-----------------------------+------------------------------+
                              |
                              v
                           CGAL 6.2.1
```

---

# 3. Process Boundary

## 3.1 MCP Server process

言語: Python 3.12系を推奨。最低要件はMCP SDKのPython 3.10+に従うが、プロジェクト側でpinする。

責務:

- MCP protocol
- JSON Schema
- routing
- planning
- registry
- docs search
- artifact metadata
- worker lifecycle
- validation orchestration
- logging

**CGAL template codeは原則ここへ入れない。**

## 3.2 C++ Worker

言語: C++17以上。

責務:

- CGAL object construction
- kernel selection
- algorithms
- adapters
- file/binary conversion
- low-level geometry diagnostics

CGAL 6.2.1はheader-onlyだが、worker buildはGMP/MPFR/Boost等依存を含む。

## 3.3 Worker process isolationの理由

- CGAL assertion/abort isolation
- template/ABI leakage防止
- optional dependency isolation
- memory leak/fragmentation回収
- timeout時kill可能
- StellaCAD本体からlicense/build依存を分離

---

# 4. MCP API設計

## 4.1 Tool: `cgal.capabilities.search`

### Purpose

ユーザー要求に合うOperationを上位候補として検索。

### Input

```json
{
  "query": "自己交差を直してwatertightにしたい",
  "artifact_ids": ["art_xxx"],
  "constraints": {
    "preserve_boundary": true
  },
  "limit": 8
}
```

### Output

```json
{
  "candidates": [
    {
      "operation_id": "mesh.repair.self_intersections",
      "score": 0.93,
      "why": ["input is TriangleSurfaceMesh", "repair intent matched"],
      "preconditions": [],
      "implementation_status": "implemented"
    }
  ]
}
```

---

## 4.2 Tool: `cgal.capabilities.describe`

指定Operationの完全schemaだけをオンデマンドで返す。

```json
{
  "operation_id": "mesh.boolean.corefine_difference",
  "include": ["schema", "preconditions", "validators", "examples"]
}
```

これにより全operation definitionを常時promptへ載せない。

---

## 4.3 Tool: `cgal.plan`

### Input

```json
{
  "goal": "このミッドシェルを最大偏差0.05mm以内で軽量化。合わせ面は固定",
  "artifacts": ["art_mid_shell"],
  "policy": {
    "accuracy": "high",
    "preserve_input": true,
    "allow_repairs": "safe_only"
  }
}
```

### Output

```json
{
  "plan_id": "plan_...",
  "steps": [
    {"id":"s1","op":"mesh.inspect.topology"},
    {"id":"s2","op":"mesh.features.detect"},
    {"id":"s3","op":"mesh.simplify.envelope_bounded"},
    {"id":"s4","op":"mesh.distance.symmetric_hausdorff"},
    {"id":"s5","op":"mesh.inspect.self_intersections"}
  ],
  "success_criteria": {
    "max_hausdorff_mm": 0.05
  }
}
```

Plannerは単に「simplify」を呼ぶのではなく、検査と検証をDAGへ挿入する。

---

## 4.4 Tool: `cgal.execute`

### Input

```json
{
  "operation_id": "mesh.remesh.isotropic",
  "inputs": ["art_x"],
  "parameters": {
    "target_edge_length": {"value": 0.25, "unit": "mm"}
  },
  "execution": {
    "timeout_s": 120,
    "validate": true
  }
}
```

### Output

```json
{
  "execution_id": "exec_...",
  "status": "success",
  "outputs": ["art_y"],
  "metrics": {},
  "validation": {}
}
```

---

## 4.5 Tool: `cgal.validate`

Operation-independent validation entry point。

```json
{
  "artifact_id": "art_candidate",
  "against": "art_reference",
  "checks": [
    "manifold",
    "self_intersections",
    "symmetric_hausdorff"
  ],
  "limits": {
    "symmetric_hausdorff": {"value":0.05,"unit":"mm"}
  }
}
```

---

## 4.6 Tool: `cgal.artifact.inspect`

取得項目例:

- geometry type
- unit
- vertex/edge/face/cell count
- bbox
- components
- boundary count
- manifold flags
- orientation
- format
- hash
- producer

---

## 4.7 Tool: `cgal.docs.search`

Registryで見つからない高度要求用。

```json
{
  "query": "generalized barycentric coordinates convex simplicial polytope",
  "scope": ["manual", "reference", "examples", "headers"],
  "cgal_version": "6.2.1"
}
```

---

## 4.8 Tool: `cgal.system.health`

- CGAL version
- worker version
- compiler
- kernel support
- dependency status
- capability catalog version
- catalog coverage
- worker pool status

---

# 5. MCP Resources設計

MCP Resourcesは静的/準静的知識を載せる。

例:

```text
cgal://catalog/index
cgal://catalog/operation/{id}
cgal://packages/{package}
cgal://docs/{version}/{path}
cgal://executions/{id}/report
cgal://artifacts/{id}/metadata
cgal://coverage/report
```

`resources/read`には適切なTTL/cacheScopeを設定する。

### Cache policy例

| Resource | TTL |
|---|---:|
| package catalog | 24h以上 |
| operation schema | 24h以上 |
| health | 5-30s |
| artifact metadata | immutableなら長期 |
| execution report | immutableなら長期 |

MCP 2026-07-28のlist/read cache hintsを活用する。

---

# 6. Capability Registry Schema

## 6.1 Core entity

```yaml
operation:
  id: mesh.distance.symmetric_hausdorff
  revision: 1
  title: Symmetric Hausdorff Distance
  description: Compute or bound two-sided mesh distance.

classification:
  domain: mesh
  family: distance
  intents:
    - compare geometry
    - maximum deviation
    - validate simplification

cgal:
  baseline_version: 6.2.1
  package: Polygon Mesh Processing
  symbols: []
  headers: []
  docs: []
  examples: []

io:
  inputs:
    - TriangleSurfaceMesh
    - TriangleSurfaceMesh
  output: ValidationMetric

requirements:
  hard: []
  soft: []

mutation:
  modifies_input: false

parameters: {}

validation:
  validators: []

execution:
  backend: cpp_worker
  module: mesh
  handler: mesh.distance.symmetric_hausdorff

quality:
  maturity: production
  deterministic: true

license:
  package_license: GPL
```

## 6.2 Implementation status

列挙値:

```text
DISCOVERED
CATALOGED
ADAPTER_PLANNED
IMPLEMENTED
VALIDATED
DEPRECATED
BLOCKED
EXCLUDED
```

`DISCOVERED`と`IMPLEMENTED`を混同しない。

---

# 7. Type System

CGALのC++ typeをそのままLLM schemaへ露出しない。

## 7.1 Canonical geometry types

```text
Point2
Point3
PointSet3
Polyline2
Polyline3
Polygon2
PolygonWithHoles2
PolygonSoup3
TriangleSurfaceMesh
PolygonSurfaceMesh
TetrahedralMesh
Arrangement2
Triangulation2
Triangulation3
VolumeDomain3
AABBIndex
SkeletonGraph
ScalarField
FeatureSet
```

## 7.2 Properties

artifact typeにpropertyを追加する。

```yaml
geometry_properties:
  triangulated: true
  closed: false
  oriented: true
  manifold_2: true
  self_intersections: unknown
  units: mm
```

Routerはこのpropertyでhard gateする。

---

# 8. Unit System

CAD統合では単位事故を最優先で防ぐ。

すべてのlength parameterは単なる`double`ではなく:

```json
{"value":0.05,"unit":"mm"}
```

をcanonical inputとする。

内部workerはartifact unitを基準に正規化。

angleもdeg/radを明示。

---

# 9. Kernel Policy

CGALではkernel選択がrobustness/性能へ影響する。

LLMへkernel class名を自由入力させない。

MCP policy enumを定義:

```text
fast_inexact
robust_predicates
exact_constructions
package_recommended
```

Router/adapterがCGAL kernelへmappingする。

例:

```text
fast_inexact          -> Simple_cartesian<double> where permitted
robust_predicates     -> EPICK系
exact_constructions   -> EPECK系
package_recommended   -> adapter-defined
```

**package manualが特定kernel要件を持つ場合はadapter側要件を優先。**

---

# 10. Router詳細設計

## 10.1 Stage A: Query normalization

抽出:

- action
- subject geometry
- target geometry
- precision/tolerance
- preservation constraints
- desired topology
- performance preference
- mutability allowance

## 10.2 Stage B: Artifact-aware context

artifact metadataを取得し、LLM textより優先する。

例:

ユーザーが「solid mesh」と言っていても実artifactがopen meshなら、closed-volume-only operationを直接実行しない。

## 10.3 Stage C: Candidate generation

候補取得をhybrid化。

1. intent alias exact match
2. FTS5 BM25
3. semantic retrieval
4. workflow prior
5. related-operation graph

## 10.4 Stage D: Hard filter

- type compatibility
- CGAL version
- adapter implemented
- dependencies available
- license mode
- preconditions

## 10.5 Stage E: Ranking

```text
S =
  0.28 * intent
+ 0.20 * type
+ 0.16 * precondition
+ 0.12 * quality_prior
+ 0.10 * validation_coverage
+ 0.08 * workflow_prior
+ 0.06 * performance_fit
- risk_penalties
```

初期値。benchmarkで調整する。

## 10.6 Stage F: Ambiguity handling

候補が競合するときはPlannerが比較Planを作れる。

例:

```text
Garland-Heckbert vs Lindstrom-Turk
```

両方の候補を小規模previewで実行し、品質metricで選ぶことも可能。

ただし高コストの場合は事前cost estimateで抑制。

---

# 11. Planner詳細設計

## 11.1 Plan node

```yaml
node:
  id: step_1
  operation: mesh.repair.orient
  inputs:
    mesh: ${input.mesh}
  parameters: {}
  on_failure:
    policy: stop
  validators: []
```

## 11.2 Plan edge

artifact dependencyで接続する。

## 11.3 Invariant propagation

各Operationはinvariantを宣言する。

例:

```text
triangulate
  produces: triangulated=true

orient
  produces: oriented=true

repair_self_intersections
  aims: self_intersections=false
```

Plannerは必要invariantから前処理を逆算できる。

## 11.4 Automatic validator injection

Mutation Operationには`required_validation_profile`を設定。

LLMがvalidationを省略してもPlannerが挿入する。

---

# 12. C++ Adapter ABI

worker内部ではC++ interfaceを統一する。

概念:

```cpp
struct OperationContext {
    ArtifactStore& artifacts;
    DiagnosticSink& diagnostics;
    CancellationToken& cancel;
};

class OperationAdapter {
public:
    virtual OperationResult execute(
        const OperationRequest& request,
        OperationContext& context) = 0;
};
```

Registry:

```cpp
registry.register_adapter(
    "mesh.simplify.envelope_bounded",
    make_envelope_simplifier
);
```

CGAL template instantiationは個別adapter translation unitに閉じ込める。

---

# 13. Worker Protocol

## 13.1 Request

```json
{
  "protocol": 1,
  "request_id": "wrk_123",
  "operation": "mesh.inspect.self_intersections",
  "inputs": ["art_123"],
  "parameters": {},
  "limits": {
    "wall_time_ms": 60000,
    "memory_mb": 4096
  }
}
```

## 13.2 Response

```json
{
  "request_id": "wrk_123",
  "status": "ok",
  "outputs": [],
  "metrics": {
    "intersection_pairs": 0
  },
  "diagnostics": []
}
```

## 13.3 Error

```json
{
  "status": "error",
  "error": {
    "class": "PRECONDITION_FAILED",
    "code": "MESH_NOT_TRIANGULATED",
    "message": "...",
    "recoverable": true,
    "suggested_operations": ["mesh.convert.triangulate_faces"]
  }
}
```

---

# 14. Artifact Store設計

## 14.1 Directory

```text
.artifacts/
  sha256-abcd.../
    metadata.json
    geometry.ply
    properties.json
```

content-addressed storageを推奨。

## 14.2 Immutability

同じhashは同じcontent。

Mutationは新しいartifact ID。

## 14.3 Provenance

```json
{
  "created_by": {
    "operation":"mesh.simplify.envelope_bounded",
    "execution_id":"exec_...",
    "inputs":["art_original"]
  },
  "software": {
    "cgal":"6.2.1",
    "worker":"1.0.0"
  }
}
```

---

# 15. Geometry I/O

## 15.1 Supported public formats v1

最低限:

- OFF
- PLY
- OBJ
- STL

必要に応じ:

- polygon soup JSON/binary
- XYZ point cloud

STEP/BRepはCGALの主データ形式ではないため、StellaCAD/OpenCascade側でtessellation/bridgeを担当する。

MCPが「CGALだけでSTEP CAD kernelになる」と誤認しないこと。

---

# 16. Validation Framework

## 16.1 Validator type

```text
predicate
metric
comparison
structural
statistical
```

## 16.2 Common validators

- valid polygon mesh
- triangulated
- manifold
- closed
- oriented
- self-intersection count
- volume sign / bounded volume
- component count
- Hausdorff/deviation
- boundary deviation
- normal inversion/change
- area/volume change
- cell quality

## 16.3 Pass policy

validation failureはOperation execution successと分離する。

```text
EXECUTION_SUCCESS + VALIDATION_FAIL
```

を許し、AIが誤って成功扱いしないようstatusを明示する。

---

# 17. Surface Mesh Simplification Adapter例

**この章は代表例であり、システムの中心章ではない。**

Operation:

```text
mesh.simplify.envelope_bounded
```

内部候補:

- Garland-Heckbert family
- Polyhedral envelope placement/filter
- constrained edges/placement
- normal change guard

入力:

- TriangleSurfaceMesh
- tolerance
- optional constrained feature set

処理:

```text
inspect
 -> constraints mapping
 -> simplify
 -> output artifact
 -> symmetric deviation validation
 -> topology validation
```

CGAL 6.2.1のSurface Mesh Simplificationはpolicy-based edge collapseで、cost / placement / filter / constraints / stop predicateを組み合わせる。

本Operationでは`target_face_count`を必須にせず、tolerance主導で停止するprofileを持てるようにする。

---

# 18. Boolean Adapter設計

Operation family:

```text
mesh.boolean.union
mesh.boolean.intersection
mesh.boolean.difference
mesh.clip
mesh.split
mesh.slice
```

Planner前処理:

- self-intersection
- orientation
- closedness where required
- triangulation

失敗時:

- diagnostics
- repair候補
- alternate kernel/profile

Boolean failureを「CGAL失敗」で終わらせず、原因分類まで返す。

---

# 19. Repair Adapter設計

Repairは万能auto-fixにしない。

操作を分離:

```text
mesh.repair.orient
mesh.repair.stitch_borders
mesh.repair.remove_degenerate_faces
mesh.repair.fill_holes
mesh.repair.polygon_soup
mesh.repair.self_intersections
```

Plannerが必要なものだけ選ぶ。

geometryを大きく変えるrepairはrisk levelを上げる。

---

# 20. Docs/Source Knowledge Base

## 20.1 Index schema

```text
document
package
symbol
header
example
version
license
keywords
text
```

## 20.2 Symbol link

Capability Registry Operationから:

```text
operation -> CGAL symbol -> header -> docs -> example
```

を辿れる。

## 20.3 Auto-generation

CGAL更新時:

- Package list crawl
- Doxygen parse
- header scan
- example scan
- symbol diff

を行う。

人間が手で全機能リストを保守する構造を避ける。

---

# 21. 「使われない便利機能」を防ぐ仕組み

## 21.1 Related operation graph

例:

```text
self_intersection_detection
  -> repair
  -> corefinement readiness

feature_detection
  -> constrained simplification
  -> segmentation

AABB tree
  -> intersection acceleration
  -> distance queries
```

Routerは直接intent一致だけでなく隣接capabilityも候補にできる。

## 21.2 Workflow priors

既知の良い組合せを登録。

## 21.3 Validation dependencies

Operation実装者がvalidatorを登録しない場合CIで警告/失敗。

## 21.4 Usage telemetry

ローカルで以下を記録可能:

- candidateに出たが選ばれないOperation
- high scoreなのに失敗したOperation
- fallback成功率

外部送信はしない。

dead capability reportを生成し、死蔵を検出する。

---

# 22. Security / File Boundary

## 22.1 Path policy

workerへ任意pathを渡さない。

MCP Artifact Managerが許可したpathのみ。

## 22.2 Input limits

- max file size
- max vertices/faces
- decompression limit
- timeout
- memory

## 22.3 Command execution

Operation schemaから任意shell commandを生成しない。

C++ adapterはcompile-time registered IDのみ実行。

---

# 23. Cancellation / Long Running Jobs

MCP Tasks extensionは2026-10-04時点でdraft/SDK gapがあるため、v1の必須依存にはしない。

基本:

- tool call lifecycle内でworker timeout/cancel
- Streamable HTTP cancellation
- worker supervisorがprocess kill可能

将来:

- clientがTasks extension対応ならjob化adapterを追加

ただしcore APIはTasksなしでも完結する。

---

# 24. Logging

structured log:

```json
{
  "trace_id":"tr_...",
  "execution_id":"exec_...",
  "operation":"mesh.boolean.difference",
  "stage":"worker",
  "level":"warning",
  "code":"SELF_INTERSECTION_DETECTED"
}
```

geometry contentそのものをlogへ大量出力しない。

---

# 25. Error Taxonomy

```text
INPUT_INVALID
TYPE_MISMATCH
PRECONDITION_FAILED
CAPABILITY_NOT_IMPLEMENTED
DEPENDENCY_UNAVAILABLE
LICENSE_DISALLOWED
NUMERIC_FAILURE
CGAL_EXCEPTION
CGAL_ASSERTION
TIMEOUT
CANCELLED
OUT_OF_MEMORY
WORKER_CRASH
VALIDATION_FAILED
SERIALIZATION_FAILED
INTERNAL_ERROR
```

recoverableフラグとsuggested next operationを返す。

---

# 26. Build構成

```text
/cpp
  /worker
  /core
  /modules
    /mesh
    /pointset
    /triangulation
    /meshing
    /polygon
    /spatial
    /advanced
/python
  /mcp_server
  /router
  /planner
  /registry
  /artifact_store
  /docs_index
/schemas
/catalog
/tests
```

CMake基本:

```cmake
find_package(CGAL REQUIRED)
target_link_libraries(cgal_worker PRIVATE CGAL::CGAL)
```

package固有dependencyはmodule target単位で追加。

---

# 27. Dependency baseline

本番baseline:

- CGAL 6.2.1
- C++17+
- CMake 3.22+
- Boost 1.74+（CGAL公式最低要件）
- GMP / MPFR as required
- Python MCP SDK 2.2.0 baseline
- Python 3.10+、project推奨3.12

optional dependencyはCapability Registryへ反映。

---

# 28. MCP 2026-07-28対応

設計で利用する点:

- `server/discover`
- stateless modern request model
- `tools/list`/resources cache hints
- structured tool outputs/schema
- stdio + Streamable HTTP

大量Operationを全tool listへ展開しないため、schema cacheだけに依存するのではなくControl Tool + Resource architectureを採用する。

旧client互換は公式SDK v2へ任せ、独自protocol compatibility layerを再発明しない。

---

# 29. Skills利用方針

MCP Skills extensionが利用可能なhostでは、複雑なworkflow instructionをSkillとして公開可能。

候補:

```text
cgal://skill/mesh-repair
cgal://skill/boolean-debugging
cgal://skill/tolerance-preserving-simplification
cgal://skill/pointcloud-reconstruction
```

ただしSkills非対応hostでもControl Toolsだけで全機能を利用可能であること。

---

# 30. Versioning

3種類を分離する。

```text
MCP server version
Capability Catalog version
CGAL runtime version
```

例:

```json
{
  "server":"1.2.0",
  "catalog":"2026.10.04.3",
  "cgal":"6.2.1"
}
```

Operationにもrevisionを持つ。

---

# 31. CGAL Update Compatibility

CGAL 6.2でPMPが複数packageへ再編されたことを前例として、package path/nameは固定文字列ロジックに埋め込まない。

update audit:

```text
added packages
removed packages
moved symbols
changed headers
changed license
deprecated API
new examples
compile break
behavior regression
```

---

# 32. Performance設計

## 32.1 Lazy load

- Registry detailsはオンデマンド
- docs本文もオンデマンド
- workersもmoduleごとlazy start可能

## 32.2 Cache

- immutable artifact metadata
- AABB trees where safe
- parsed mesh representation in persistent worker
- router retrieval index

## 32.3 Avoid duplicate conversion

同一artifact/hashを何度もPLY→CGAL Surface_meshへ変換しない仕組みをworker cacheへ用意する。

---

# 33. Quality Profiles

Operationごとに共通profileを使える。

```text
preview
balanced
high_quality
robust
exact
```

例:

`preview`: speed優先  
`high_quality`:より厳しい検証  
`robust`: exact predicates/repair checks強化  
`exact`:利用可能packageでexact construction優先

LLMが数十個の低レベルparameterを毎回設定する必要を減らす。

---

# 34. Plan Policy

```yaml
policy:
  preserve_original: true
  mutation_validation: required
  auto_repair: conservative
  allow_lossy_conversion: false
  prefer_official_cgal_algorithm: true
  allow_experimental_adapter: false
```

これをproject/userごとに切替可能。

---

# 35. Testing Architecture

## 35.1 Adapter tests

各Operation:

- valid input
- invalid input
- boundary values
- deterministic output metadata
- memory safety

## 35.2 Differential tests

可能なものは:

- CGAL official example output
- alternative CGAL policy
- independent metric

と比較。

## 35.3 Planner tests

自然言語→plan snapshotをgolden化しすぎない。

重要なのは:

- 必須preconditionを満たす
- 必須validatorが入る
- forbidden operationを選ばない

というproperty-based assertion。

## 35.4 Fuzz/property tests

小さなrandom geometryで:

- crashしない
- invalid successを返さない
- input artifactを変更しない

を確認。

---

# 36. Acceptance Example: マウスミッドシェル

入力:

```text
38,000 triangle mesh
max deviation <= 0.05 mm
mechanical interfaces fixed
```

MCPが行うべきこと:

1. artifact inspect
2. mesh validity check
3. protected region/feature resolve
4. simplification candidates検索
5. appropriate policy選択
6. simplify
7. independent symmetric distance validation
8. topology/self-intersection validation
9. before/after report

**この例が成功してもMCP完成ではない。**

同じRouter/PlannerがBoolean、point set、triangulation、straight skeleton、Mesh_3等にも拡張なしで到達できることが重要。

---

# 37. StellaCAD統合境界

Standalone MCP v1ではStellaCAD内部objectへ直接依存しない。

後続Integration Layerが:

```text
StellaCAD object
  -> tessellated/artifact representation
  -> CGAL MCP
  -> result artifact
  -> StellaCAD object/update
```

を担当。

この境界により、CGAL MCP単体を他CADやautomationでも再利用できる。

---

# 38. StellaCAD統合時に追加予定の仕様

次工程で別文書化する。

- document/session mapping
- BRep↔mesh conversion policy
- face/edge selection preservation
- persistent topology naming
- transaction / undo-redo
- UI preview
- background calculation
- project cache
- FreeCAD/OpenCascade bridge
- AI agent tool routingとの統合

Standalone MCP設計をこれらに引きずらせない。

---

# 39. ライセンス設計

Capability単位でpackage licenseを追跡。

```yaml
license:
  package: "Triangulated Surface Mesh Simplification"
  type: GPL
  commercial_alternative: true
```

LGPL packageとGPL packageを区別する。

closed-source StellaCADへの配布形態についてはcommercial CGAL licenseを含め別途判断する。

worker分離を「GPL回避策」と断定しない。

---

# 40. 禁止設計一覧

以下をPR reviewでrejectする。

1. `if query contains "simplify" ...`のような巨大キーワード分岐Router
2. CGAL全関数をMCP Toolへ1:1展開
3. 全tool schemaの常時prompt投入
4. geometry本体をbase64 JSONで毎回搬送
5. input file上書き
6. validatorなしmutation
7. `catch (...) { success=true; }`
8. package license metadataなしOperation
9. version metadataなしresult
10. docs/source provenanceなし自動生成adapterの即本番化
11. Python bindings coverageをCGAL全機能とみなす
12. StellaCAD専用型をCGAL worker coreへ混入
13. simplification benchmarkだけでrouter品質評価
14. upstream issue/known limitationを無視した無制限retry
15. current stableではなくCGAL mainを無条件production追従

---

# 41. 完成判定

## Architecture

- [ ] Control Tool architecture完成
- [ ] Registry/Router/Planner/Worker/Validator分離
- [ ] Artifact immutable model完成

## Coverage

- [ ] CGAL 6.2.1 package catalog coverage 100%
- [ ] 全packageにstatus/reason
- [ ] major capability family adapter完成

## Intelligence

- [ ] hybrid retrieval
- [ ] deterministic hard gate
- [ ] workflow planner
- [ ] validator injection
- [ ] long-tail docs search

## Reliability

- [ ] worker crash containment
- [ ] timeout
- [ ] memory limit
- [ ] structured error
- [ ] regression corpus

## MCP

- [ ] Python SDK v2
- [ ] MCP 2026-07-28
- [ ] stdio
- [ ] Streamable HTTP
- [ ] structured outputs
- [ ] cache hints

## Governance

- [ ] version manifest
- [ ] package license map
- [ ] coverage report
- [ ] update diff pipeline

---

# 42. 実装優先度

```text
P0  Catalog/Registry foundation
P0  Worker isolation
P0  MCP control-plane
P0  Router hard gates
P0  Planner + validator injection
P1  Mesh core/repair/boolean/remesh/simplification
P1  Spatial/AABB
P1  Point set/reconstruction
P1  2D polygon/arrangement/triangulation
P1  3D triangulation/hull/alpha/meshing
P2  Specialized analysis and optimization packages
P2  Skills extension
P2  optional Python backend
P3  MCP Tasks extension when stable in SDK
```

軽量化はP1のmesh group内に置く。P0へ昇格させて全体設計を支配させない。

---

# 43. 公式情報源（2026-10-04確認）

- CGAL latest stable: https://www.cgal.org/releases.html
- CGAL 6.2.1 Manual: https://doc.cgal.org/latest/Manual/index.html
- CGAL Packages: https://doc.cgal.org/latest/Manual/packages.html
- CGAL 6.2 PMP reorganization: https://doc.cgal.org/latest/Polygon_mesh_processing/
- Surface Mesh Simplification: https://doc.cgal.org/latest/Surface_mesh_simplification/
- CGAL dependencies/compilers: https://doc.cgal.org/latest/Manual/thirdparty.html
- CGAL CMake: https://doc.cgal.org/latest/Manual/devman_create_and_use_a_cmakelist.html
- CGAL license: https://www.cgal.org/license.html
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- MCP Python SDK releases: https://github.com/modelcontextprotocol/python-sdk/releases
- MCP v2 / 2026-07-28 notes: https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/whats-new.md
- MCP protocol versions: https://py.sdk.modelcontextprotocol.io/protocol-versions/
- MCP cache hints: https://py.sdk.modelcontextprotocol.io/client/caching/
- MCP Skills extension: https://skills.extensions.modelcontextprotocol.io/specification/stable/skills
- MCP Tasks draft: https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks
- CGAL Python bindings GSoC 2026: https://github.com/CGAL/cgal/issues/9610

---

# 44. 最終設計意図

CGAL Master MCPの価値は「CGAL関数をMCP経由で呼べる」ことではない。

価値は、AIにCGALの膨大なAPI知識を常時背負わせずに、

```text
発見
→ 選択
→ 前提条件確認
→ workflow構成
→ 実行
→ 検証
→ fallback
→ provenance保存
```

までをシステム側へ移すことにある。

これにより、100種類以上・将来的には数百のCapabilityが増えても、**使われない機能・誤用される機能・promptを圧迫する機能**を最小化できる。

StellaCADはこのMaster MCPの一クライアントとして統合する。CGALの能力をStellaCADの当面の一用途へ縮小しないことを、本設計の最重要原則とする。
