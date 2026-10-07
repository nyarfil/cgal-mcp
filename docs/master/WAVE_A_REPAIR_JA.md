# メッシュ修復の実装区切り

次の6修復と、各修復を公式CGAL 6.2.1で再計算して照合する専用validatorの12 Operationを
正式workerと汎用coreへ統合しました。

- 向き付け（`mesh.repair.orient`、`orient_polygon_soup`）。繰り返し頂点indexの面は拒否します。
- 境界の縫合（`mesh.repair.stitch_borders`）。
- 退化面・退化辺の除去（`mesh.repair.remove_degenerate`）。CGALが退化面を除去できない場合は候補を公開しません。
- 穴埋め（`mesh.repair.fill_holes`）。`max_hole_edges`は3以上2000以下。CGALの3乗時間fallbackは無効で、
  2D制約付きDelaunayで三角形分割できない穴は`HOLE_TRIANGULATION_FAILED`です。
- ポリゴンスープ修復（`mesh.repair.polygon_soup`）。重複方針と向き要件を明示します。
- 非多様体頂点の複製による前処理（`mesh.repair.manifold_preprocess`）。

入力はASCII三角形OFF（64 MiB・100万頂点・200万面以下）で、座標はbinary64です。
`package_recommended`のみ対応し、`exact_constructions`は黙って近似せず拒否します。
元Artifactは変更せず、単位を保持し、validatorが公式CGAL再計算との一致・修復固有の不変条件・
入力幾何の保持を確認するまで候補を合格させません。

これは原本7.4の全バリエーションの完了ではありません（例: 穴の細分・fairing・patch ID出力は未提供）。
再試験:

```powershell
.venv/Scripts/python.exe scripts/verify_master_wave_a_repair.py `
  --worker build-master/Release/cgal-master-worker.exe `
  --output work/master-wave-a-repair-local.json
```

実PCの記録は[`evidence/wave-a-repair-windows-vs2026.json`](evidence/wave-a-repair-windows-vs2026.json)です。
独立レビューで見つかった停止・crash・validator誤拒否の指摘は修正し、回帰試験を
`tests/master_wave_a_repair_cases.py`に追加しています。Standalone全体の受入は未達です。
