# 2D Delaunay細分メッシュ生成（Mesh_2）の汎用core統合

`CGAL::refine_Delaunay_mesh_2`（`Delaunay_mesh_size_criteria_2`）による2Dメッシュ生成の
1 transformと1 validatorを正式workerへ追加し、固定12工具の公開面を維持したまま
必須検証付きで実行できます。入力は穴付き多角形`PolygonWithHoles2`、出力は
`Triangulation2`（頂点、三角形、制約辺）で、単位はArtifactに保持します。

| Operation | 内容 | 必須validator |
|---|---|---|
| `mesh2.refine.delaunay` | 穴付き多角形を、形状（aspect）境界と最大辺長を満たす制約付きDelaunay三角形メッシュへ細分 | `mesh.validate.delaunay_refinement_2` |

parameterは`aspect_bound`（最小角の正弦の2乗。0.125＝約20.7度がMesh_2の停止保証、範囲は(0, 0.125]）と
`size_bound`（最長辺の上限、TypedLength）です。穴ごとに内部の種点を1つ渡し、穴を
メッシュ化しません。ドメイン頂点1000、出力三角形30000を上限とし、見積もりが超える場合は
`MESH_SIZE_LIMIT_EXCEEDED`（RESOURCE_LIMIT）で拒否します。自己交差、退化リング、
穴の領域外・接触・重なり・入れ子は`PRECONDITION_FAILED`、不正parameterは`INVALID_REQUEST`、
単位不一致は`TYPE_ERROR`です。

2つのOperationの状態は`VALIDATED`です（`self_verified_not_independently_reviewed`）。
validatorは被試験のメッシャを呼ばず、生のドメインと候補から有理数で次を再計算します。
ドメイン妥当性、三角形の反時計回り、辺の多様体性、Euler標数（V−E+F＝1−穴数）、
境界鎖がドメイン境界と一致すること、宣言された制約辺の一致、面積の被覆（相対1e-9）、
重心がドメイン内にあること、形状基準と辺長基準、制約付きDelaunay性
（拘束されない内部辺の対頂点が外接円の内側にないこと）。
改ざん候補（三角形の欠落・反転・重複、制約の欠落、境界頂点・角の移動、対角線の反転、
より厳しい基準、別ドメイン）は`VALIDATION_FAILED`で拒否します。

原本要求との結合は[受入判定](CAPABILITY_ACCEPTANCE_JA.md)のfamily 7.14再試験で行い、
既知値（面積100／91／7／92、個数、最小角、最大辺長、境界辺数＝制約辺数）へのassertion、
2組の対照（辺長2と1、未細分の10x1長方形と細分後）、13件のnegative controlを持つ
7.14.01を結び付けました（7.14は1/4）。

## 曲面メッシュ生成（Surface_mesher、7.14.02）

`CGAL::make_surface_mesh`（`Implicit_surface_3`、`Surface_mesh_default_criteria_3`、`Manifold_tag`）で、
列挙された型付き陰関数ドメイン`ImplicitSurfaceDomain`（`sphere`／`ellipsoid`／`torus`、寸法は検証済みの長さ）を
閉じた外向き三角形曲面`TriangleSurfaceMesh`（OFF）へ変換します。任意の式やコードは受け付けません
（未知の種別は`UNSUPPORTED_DOMAIN_KIND`）。

| Operation | 内容 | 必須validator |
|---|---|---|
| `mesh.surface.generate` | `angle_bound`（度、最大30）、`size_bound`、`distance_bound`（TypedLength）基準で曲面を三角形化 | `mesh.validate.surface_mesh` |

`distance_bound`は最小曲率半径の0.1倍以下、推定面数は30000以下です。出力は初期点の乱数を固定して決定的です。
validatorはSurface_mesherを呼ばず、OFFを生で読み、閉2-多様体・向き・単一連結・Euler標数（種数）、
全頂点の解析曲面上の位置（閉形式／Lagrange-Newton距離）、外向き法線、最小角・外接円半径・外心距離基準、
標本点距離、解析面積・体積（既知値16π、32π/3、4π²Rr、2π²Rr²、4πabc/3）を再計算します。
改ざん（三角形欠落・反転・重複、半径1.001倍、別ドメイン、より厳しい基準、粗い八面体）は拒否します。
Surface_mesherはCGAL 6.2.1で非推奨のパッケージです。陰関数ドメインは3種類のみで、鋭い特徴、
画像ドメインと特徴保存は未実装です。

| 要求 | 状態 | 内容 |
|---|---|---|
| 7.14.01 | 結合済み | Mesh_2の`refine_Delaunay_mesh_2` |
| 7.14.02 | 結合済み | Surface_mesherの`make_surface_mesh`（球・楕円体・トーラス） |
| 7.14.03 | 結合済み | Mesh_3の`make_mesh_3`（球・楕円体・トーラスのimplicit domainと、閉じた向き付き三角形メッシュの多面体domain） |
| 7.14.04 | 結合済み | `Mesh_criteria_3`の型付きcriteria（facet角・サイズ・距離、cell外接半径／最短辺比・サイズに加え、列挙boxのsizing field、facet_topology、多面体の1D特徴辺`edge_size`） |

Mesh_2のconforming専用、局所サイズ基準、Lloyd最適化も未実装です。
全体の未結合は[主要能力台帳](MAJOR_INVENTORY_JA.md)を参照。

## TetrahedralMesh と独立validator（7.14.03の基盤、Mesh_3は未呼出）

型付き成果物`TetrahedralMesh`（JSON：`vertices`、`tetrahedra`（4頂点index）、`subdomains`（各セルの1以上の整数）、長さ単位mm/cm/m）。
Operation `mesh.validate.tetrahedral_mesh`はMesh_3を呼ばず、生JSONから次を再計算します。

| 検査 | 内容 |
|---|---|
| 頂点・セル | 位置重複なし、未使用頂点なし、全セルが正確な向き述語で正の向き・非退化 |
| 面隣接 | 内部面はちょうど2セルが共有し向きが逆、3セル以上や同側重なりは拒否 |
| 境界 | 全境界面が閉じた向き付き単一曲面（穴・T接合・空洞を拒否）、境界発散体積とセル体積和が一致 |
| 頂点リンク | 内部頂点は球面、境界頂点は円板（3-多様体）、面連結は1本体 |
| 統計 | 体積、二面角の最小・最大、外接半径／最短辺比、サブドメイン別体積 |
| 任意基準 | `domain_volume`（＋`volume_relative_tolerance`）、`minimum_dihedral_angle`、`maximum_radius_edge_ratio`、`minimum_tetrahedron_volume`は指定時のみ強制 |

fixtureは単一四面体、立方体の6分割・5分割、2サブドメイン、八面体（球状、体積4/3）。
陰性対照は反転、退化、穴（体積不一致）、T接合、重複・未使用頂点、重複セル、同側重なり、分離した内部体です。
セル同士のグローバルな貫入は、`domain_volume`指定時の体積比較以外では除外できません（既知の限界）。
`mesh.volume.generate`（次節）がこのvalidatorの検査を再利用して7.14.03を結合しました。

## Mesh_3 体積メッシュ生成（7.14.03）

Operation `mesh.volume.generate`は2種類のdomainに`CGAL::make_mesh_3`（`Mesh_criteria_3`）を実行し、`TetrahedralMesh`を出力します。
- `ImplicitSurfaceDomain`（球・楕円体・トーラスの列挙済み型付きdomain）: `Labeled_mesh_domain_3`。
- `TriangleSurfaceMesh`（OFF、多面体domain）: `Polyhedral_mesh_domain_3`（`edge_size`指定時は`Polyhedral_mesh_domain_with_features_3`）。入力は閉じ・多様体・一貫した向き・外向き（体積正）・単一連結・自己交差なしでなければならず、
  開いた面・非多様体・自己交差・向き不整合・反転・複数成分は`PRECONDITION_FAILED`で拒否します（面数上限20000）。
自由式と生成C++は受け付けません。画像domain、perturbation、exudationは未実装（無効）です。多面体の鋭い特徴保存は`edge_size`指定時のみ有効です（7.14.04）。
多面体domainの鋭い折れ（法線の回転が約90度を超える凹み等）はMesh_3の出力がvalidatorで拒否されるため非対応です（階段形角柱までを確認）。

parameterは`facet_angle`（30度以下）、`facet_size`、`facet_distance`（最小曲率半径の0.1倍以下）、
`cell_radius_edge_ratio`（2以上）、`cell_size`で、長さは単位付きです。
乱数種は固定で出力は決定的です。推定セル数5万・面3万・出力10万セルを超える要求は`MESH_SIZE_LIMIT_EXCEEDED`で拒否します。

必須validator `mesh.validate.volume_mesh`はMesh_3を呼ばず、`mesh.validate.tetrahedral_mesh`と同じ独立な位相・正確な向き検査に加え、
次を再計算します：サブドメイン、オイラー標数（球・楕円体1、トーラス0）、境界頂点が解析曲面上・内部頂点が内側、
境界向きが外向き、facet角・サイズ・距離、Hausdorff境界、cellサイズと外接半径／最短辺比、
解析面積・体積（標本化誤差の上限付き）。
多面体domainでは、同じvalidatorが生のOFFから入力を再検証し（閉・多様体・向き・単一成分・自己交差なし）、境界頂点が入力三角形上にあること、
境界facetから入力三角形への標本Hausdorff距離（facet_size以下）と入力標本から境界facetへの逆方向被覆（facet_sizeの2倍以下）、
facet外心距離（facet_distance以下）、境界向きと最近傍入力三角形の法線の一致（不一致5%以下）、境界・立体のオイラー標数（入力の値と半分）、
体積を入力の発散定理体積と比較（許容は入力面積×測定Hausdorff距離）を再計算します。
fixtureは単位立方体（体積1）、L字角柱（3）、階段形角柱（6）、傾けた1x2x3箱（6）です。
多面体の陰性対照は開・反転・向き不整合・自己交差・2成分・非多様体の入力、欠落セル（内部・境界）、反転・重複セル、平行移動・拡大・頂点移動した境界、
サブドメイン不正、別形状、入力の一部だけを満たすメッシュ、基準の厳格化5種、粗い立方体6分割、サイズ予算超過です。
陰性対照は欠落セル（内部・境界）、反転、重複、拡大、サブドメイン不正、粗い八面体、別domain、基準の厳格化5種、
式・未知種別・負半径・過大トーラス・針状楕円体、範囲外parameter、サイズ予算超過です。

## Mesh_3 domain criteria（7.14.04）

`mesh.volume.generate`と`mesh.validate.volume_mesh`は同じ厳格な型付き`MeshCriteria3`を受け取ります（未知キー拒否、単位・範囲検査、自由式なし）。
追加の任意parameterは次の3つです。
- `cell_size_regions`（最大4個の軸平行box、各`box_min`/`box_max`/`cell_size`）: Mesh_3のcell_sizeにsizing fieldを与えます。
  cell外接中心がboxに入るcellの外接半径はそのbox内の最小値以下、box外は全体の`cell_size`以下です。
  boxは`cell_size`より小さい値で、domainと交わる必要があります（`REGION_OUTSIDE_DOMAIN`）。
- `facet_topology`（`FACET_VERTICES_ON_SURFACE`／`FACET_VERTICES_ON_SAME_SURFACE_PATCH`）: domainは単一パッチなので境界facetの全頂点がdomain面上にあることを確認します。
- `edge_size`（多面体domainのみ）: `Polyhedral_mesh_domain_with_features_3`（法線角60度超の鋭い辺を検出）で1D特徴辺を保護し、特徴辺の長さをedge_size以下にします。
  鋭い辺が無い入力・implicit domain・`FACET_VERTICES_ON_SAME_SURFACE_PATCH`との併用は`CRITERION_NOT_APPLICABLE`、辺が60度閾値の1度以内なら`FEATURE_ANGLE_AMBIGUOUS`で拒否します。

validatorは各criterionを出力とrequestだけから独立に再計算します：領域別cell外接半径（`CELL_SIZE_REGION_VIOLATED`）、
特徴辺ごとのメッシュ辺連鎖の被覆と長さ（`FEATURE_EDGE_NOT_PROTECTED`／`EDGE_SIZE_VIOLATED`）、facet頂点のdomain面上確認。
多面体の体積許容はfacetごとの標本最大偏差から導き、境界が緩すぎれば`VOLUME_BOUND_TOO_LOOSE`で失敗します（0.5へのクランプはしません）。
再生試験は、box内外の外接半径、立方体12辺上の頂点間隔と辺長（edge_size 0.5で36、0.25で48区間）、基準を締めた陰性対照（各criterion固有のcode）を生出力から再計算します。
`edge_size`指定時は保護された特徴に接するfacetとcellにはfacet／cell基準を適用しません（Mesh_3が保護球内を細分しないため。既知の限界）。
`facet_topology`は単一パッチのdomainでは出力が変わりません（受理・伝達・検査のみ）。
未実装の範囲: 画像domain、複数パッチのfacet_topology、列挙box以外のsizing field、`mesh.surface.generate`のMesh_3 criteria（Surface_mesher基準のまま）、perturbation／exudation、Lloyd/ODT。
逆方向被覆と体積の許容は保守的な上限で、セル同士の貫入はface隣接と体積和で除外します（点位置による独立検査ではありません）。
単独の`mesh.validate.tetrahedral_mesh`は`domain_volume`未指定ではセルの貫入を除外しません。貫入の除外は`mesh.validate.volume_mesh`（境界と体積の比較）だけです。

```powershell
.venv/Scripts/python.exe scripts/verify_master_wave_e.py `
  --worker build-master/Release/cgal-master-worker.exe `
  --output work/master-wave-e-local.json
```

実PCの記録は[`evidence/wave-e-windows-vs2026.json`](evidence/wave-e-windows-vs2026.json)。
MCP経路は`tests/master_wave_e_mcp_e2e.py`（auto／legacy）で確認します。
独立レビューは未実施で、全80要求・Standaloneの完成表示は引き続き未達です。
