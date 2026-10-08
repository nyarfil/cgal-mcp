# メッシュの三角形分割・細分・再メッシュ・平滑化の汎用core統合

`PMP_Remeshing`系の7 transformと7 validatorを正式workerへ追加し、固定12工具の公開面を
維持したまま必須検証付きで実行できます。入力と出力は`TriangleSurfaceMesh`（三角形面のみ）
または非三角形面を含むOFFで、単位はArtifactに保持します。

| Operation | 内容 | 必須validator |
|---|---|---|
| `mesh.triangulate.faces` | 面の三角形分割（`triangulate_faces`／`triangulate_face`） | `mesh.validate.triangulated_faces` |
| `mesh.refine.local` | 局所細分（refine） | `mesh.validate.refinement` |
| `mesh.remesh.isotropic` | 等方remesh | `mesh.validate.isotropic_remesh` |
| `mesh.remesh.split_long_edges` | 長辺分割 | `mesh.validate.split_long_edges` |
| `mesh.smooth.tangential_relaxation` | 接線方向の緩和 | `mesh.validate.tangential_relaxation` |
| `mesh.smooth.shape` | 形状平滑化 | `mesh.validate.shape_smoothing` |
| `mesh.remesh.adaptive` | サイズ場に基づく適応remesh | `mesh.validate.adaptive_remesh` |

全14 Operationの状態は`VALIDATED`です（`self_verified_not_independently_reviewed`）。
validatorは被試験のアルゴリズムを呼ばず、生のOFFから位相・向き・境界・辺長帯・面積の分割・
サンプリングによる証明付きの両側Hausdorff上界を再計算し、改ざんした候補を拒否します。
適応remeshのvalidator（`mesh.validate.adaptive_remesh`）は`tolerance`を受け取り、生のソースOFFから独立に曲率
（角欠損とcotan平均曲率）を推定して目標辺長`clamp(sqrt(6*tol/k - 3*tol^2), min, max)`を再計算し、
候補辺長／目標の分布（5・50・95パーセンタイル、対数相関）が帯内にあるか検査します
（`edges_follow_curvature_sizing`）。一様remesh（目標0.1／0.3）は曲率を無視するため拒否され、
negative controlとして7.6に結び付けています。
生成側も検証予算を事前に確認します。非多様体入力、非三角形入力、不正parameterは拒否します。

原本要求との結合は[受入判定](CAPABILITY_ACCEPTANCE_JA.md)のfamily 7.6再試験で行い、
既知値（個数、面積、体積、辺長統計）へのassertion、2組の対照、9件のnegative controlを持つ
5要求すべてを結び付けました（7.6は5/5）。

| 要求 | 内容 |
|---|---|
| 7.6.01 | triangulate_faces／triangulate_face |
| 7.6.02 | refine |
| 7.6.03 | isotropic_remeshing、split_long_edges |
| 7.6.04 | 接線緩和、smooth_shape |
| 7.6.05 | 適応的サイズ場remesh |

7.6の未結合の不足はありません。全体の未結合は[主要能力台帳](MAJOR_INVENTORY_JA.md)を参照。

```powershell
.venv/Scripts/python.exe scripts/verify_master_wave_d.py `
  --worker build-master/Release/cgal-master-worker.exe `
  --output work/master-wave-d-local.json
```

実PCの記録は[`evidence/wave-d-windows-vs2026.json`](evidence/wave-d-windows-vs2026.json)。
MCP経路は`tests/master_wave_d_mcp_e2e.py`（auto／legacy）で確認します。
独立レビューは未実施で、全80要求・Standaloneの完成表示は引き続き未達です。
