# Wave C: Spatial Query 7.2 実装区切り

確認日: 2026-10-05（日本時間）  
変更系列: `web/spatial-query-7-2-20261005`  
この文書はWeb/ChatGPT経由で追加した実装区切りの記録であり、Standalone Master完成報告ではない。

## 目的

原本の7.2 Spatial Queryを、固定12 MCP Control Toolsの公開面を増やさずに
Capability Registry・typed Planner・native CGAL worker・専用validatorへ組み込む。

対象要求:

- `major.7.2.01`: AABB Tree
- `major.7.2.02`: KD Tree / spatial searching
- `major.7.2.03`: nearest-neighbor
- `major.7.2.04`: intersection candidates
- `major.7.2.05`: bounding boxes

軽量化専用MCPへの回帰は行わない。Spatial QueryはCGAL Master全体の一能力群として追加する。

## Operation構成

| Producer | Validator | 主CGAL API |
|---|---|---|
| `spatial.aabb.closest_point` | `spatial.validate.aabb_closest_point` | `AABB_tree::closest_point_and_primitive`, `squared_distance` |
| `spatial.kdtree.range` | `spatial.validate.kdtree_range` | `Kd_tree::search`, `Fuzzy_sphere` |
| `spatial.nearest_neighbors` | `spatial.validate.nearest_neighbors` | `Orthogonal_k_neighbor_search` |
| `spatial.intersection_candidates` | `spatial.validate.intersection_candidates` | `AABB_tree::all_intersected_primitives`, `do_intersect` |
| `spatial.bounding_box` | `spatial.validate.bounding_box` | `CGAL::bounding_box` |

全producerは`GeometryAnalysisReport`を生成し、専用validatorが同一CGAL計算を別worker呼出しで
再実行して、source hash/型/単位/parameterと結果を照合する。
producer自身のdiagnosticだけでは成果物を公開しない。

## 型と単位

- AABB mesh query: `TriangleSurfaceMesh/OFF`
- KD/range/kNN/bbox: `PointSet3/XYZ`
- 長さ単位: `mm`, `cm`, `m`
- query point/segment endpoint: `{value:[x,y,z], unit:<unit>}`
- radius/epsilon: typed length
- 結果report: `GeometryAnalysisReport/json/none`

入力Artifactの座標系を維持し、長さparameterだけをsource unitへ明示変換する。
入力を上書きしない。

## 精度契約

### AABB Tree

AABB closest/intersectionは既存MasterのEPECK座標を使用する。
closest pointはbinary64近似値だけでなく、EPECK座標のexact文字列表現もreportへ保持する。
squared distanceもexact表現を保持する。

CGAL公式AABB Tree manualはstandard traitsで退化triangle/segmentを入れることを
undefined behavior/crashの可能性として警告しているため、退化triangleを
`AABB_DEGENERATE_PRIMITIVE`で演算前に拒否する。

### Spatial Searching

`Kd_tree` / `Orthogonal_k_neighbor_search`は
`Exact_predicates_inexact_constructions_kernel`を使用する。
この経路は`package_recommended`限定とし、`exact_constructions`要求を受けて
黙ってEPICKへ落とさない。未対応精度要求は
`OUTPUT_PRECISION_PROFILE_UNSUPPORTED`でfail-closedする。

range searchの`epsilon=0`はexact range query。
epsilon>0はCGALのFuzzy_sphere契約に従う。

### Bounding box

公開package identityはCGAL docsの`Principal_component_analysis`。
使用header `CGAL/bounding_box.h`のCGAL 6.2.1 source originは
`Principal_component_analysis_LGPL`で、header SPDXは
`LGPL-3.0-or-later OR LicenseRef-Commercial`。
package identityと実際にリンクするheaderのlicense provenanceを分離して記録する。

## Router

既存の日英Capability retrievalへ以下を追加する。

- closest point / nearest point / 最近点
- range search / radius search / 半径検索 / 半径内
- nearest neighbor / k近傍 / 最近傍
- segment intersection candidates / 交差候補
- bounding box / AABB / バウンディングボックス

入力Artifact typeをhard gateとして使用する。
例えば「最近点」がpoint setならKD系、triangle meshならAABB closestを候補にできる。
名前一致だけで異なるgeometry typeを自動実行しない。

## 安全性・資源制限

- AABB mesh: 最大400,000 face
- PointSet: 最大2,000,000 point
- report: 最大16 MiB
- 列挙結果: 最大100,000
- zero-length segmentは拒否
- kは1以上かつpoint count以下
- source hashをworker実行前後で維持
- unverified candidateはArtifactとして公開しない

## 試験

Native:
- `tests/master_wave_c_spatial_cases.py`

MCP:
- `tests/master_wave_c_spatial_mcp_e2e.py auto`
- `tests/master_wave_c_spatial_mcp_e2e.py legacy`

Replay gate:
- `scripts/verify_master_wave_c_spatial.py`

試験には正常系に加えて以下を含む。

- exact KD requestのfail-closed
- degenerate AABB primitive拒否
- zero-length segment拒否
- k > point count拒否
- forged analysis reportのvalidator拒否
- source Artifact hash不変
- 日本語intentから5 Operationを発見可能
- 固定12 MCP toolsを維持
- Plannerによるdedicated validator自動挿入

## 正式受入の条件

このbranch上のOperationはまず`IMPLEMENTED`として登録する。

次をすべて満たすまで`VALIDATED`へ昇格しない。

1. 公式CGAL 6.2.1 sourceでnative workerがcompile。
2. Linux CIでnative + MCP auto/legacy replay合格。
3. Windows VS2022 CIで同じreplay合格。
4. 既存Master regressionが全合格。
5. Catalog/worker manifest一致。
6. Routerの5 intentが実MCP経路で正しく候補化。
7. validator改ざんnegative test合格。
8. evidence hashを固定して受入runnerへ接続。

`VALIDATED`昇格後に初めて`major.7.2.01`〜`major.7.2.05`へ
受入evidenceを接続する。単にworkerがcompileしただけでは5/5完了としない。

## 公式参照

- https://doc.cgal.org/latest/AABB_tree/
- https://doc.cgal.org/latest/Spatial_searching/
- https://doc.cgal.org/latest/Spatial_searching/classCGAL_1_1Kd__tree.html
- https://doc.cgal.org/latest/Principal_component_analysis/
- https://doc.cgal.org/latest/Principal_component_analysis/group__PkgPrincipalComponentAnalysisDbb.html

実装はCGAL 6.2.1 release source/headerを優先し、検索結果や記憶だけでAPIを推測しない。
