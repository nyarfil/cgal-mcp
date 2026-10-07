# 2D・三角形分割・空間問合せの汎用core統合

12のtransformと11のvalidatorを正式workerへ追加し、固定12工具の公開面を維持したまま
必須検証付きで実行できます。新しい型は`PointSet2`、`Polygon2`、`PolygonWithHoles2`、
`SegmentGraph2`、`Triangulation2`、`Triangulation3`、`RayBatch3`と、報告型
`Polygon2AnalysisReport`、`SpatialQueryReport`です。厳格なparserで読み込みます。

- 2D凸包、3D点集合のbounding box、2D点集合のbounding box。
- 多角形の性質（向き・単純性・凸性・厳密な面積と重心・外接箱）と点の内外判定。
- 2D／3D Delaunay三角形分割、制約付き三角形分割（Delaunay有無を選択）。
- Kd木によるk近傍（orthogonal／general）と半径検索。
- AABB treeによるメッシュ最近点とray最初の交点。

各transformは基本健全性と専用の独立validatorを通過してからArtifactを公開します。
validatorは厳密predicateや総当たりでsourceから再計算し、改ざんした報告を拒否します。
単位はArtifactに保持し、半径やrayの単位不一致は`TYPE_ERROR`で拒否します。

原本要求との結合は[受入判定](CAPABILITY_ACCEPTANCE_JA.md)のfamily再試験で行い、
手計算の既知値（面積91、重心919/182、立方体の凸包体積8、最近点距離など）への
assertionと拒否されるnegative controlを持つ8要求だけを結び付けました。

| 要求 | 内容 |
|---|---|
| 7.2.01 | AABB最近点・ray最初の交点 |
| 7.2.02 | Kd木のk近傍・半径検索 |
| 7.2.03 | K_neighbor_search／Orthogonal_k_neighbor_search |
| 7.2.05 | Bbox_2／Bbox_3 |
| 7.11.01 | Delaunay 2D／3D |
| 7.11.02 | 制約付きDelaunay／制約付き三角形分割 |
| 7.12.01 | Polygon_2／Polygon_with_holes_2の性質と内外判定 |
| 7.13.01 | 2D／3D凸包 |

未結合の不足は[主要能力台帳](MAJOR_INVENTORY_JA.md)に記録しています
（7.2.04交差候補、7.11.03〜05、7.12.02〜07、7.13.02〜05）。

```powershell
.venv/Scripts/python.exe scripts/verify_master_wave_c.py `
  --worker build-master/Release/cgal-master-worker.exe `
  --output work/master-wave-c-local.json
```

実PCの記録は[`evidence/wave-c-windows-vs2026.json`](evidence/wave-c-windows-vs2026.json)。
Operationは`self_verified_not_independently_reviewed`で、独立レビューは未実施です。
全80要求・Standaloneの完成表示は引き続き未達です。
