# 汎用coreへの軽量化移行

CGAL Masterは開発中です。この区切りは軽量化・関連検証の移行であり、
原本7.1〜7.15の全80要求やStandalone受入の達成を意味しません。

新しい固定12工具から、以下のOperationを計画・実行できます。

- `mesh.simplify.edge_collapse`
- `mesh.validate.simplification_integrity`
- `mesh.distance.symmetric_hausdorff`

軽量化には両validatorが自動挿入されます。どちらかが失敗・判定不能なら、
候補を診断用に保存し、合格Artifactとして公開しません。入力を保持します。
長さは`{value, unit}`で渡し、変換を履歴へ記録します。

実装・実計算試験済みの範囲:

- Lindstrom–Turk、edge-length/midpoint、Garland–Heckbertのplane、triangle、
  plane+line、probabilistic plane、probabilistic triangleの7 cost/placement。
- edge count/ratio、face count/ratio、edge lengthの5 stop predicate。
- boundary/指定edge constraint、bounded distance、bounded normal change、
  `Polyhedral_envelope_filter`。
- 複数component、穴・genus、入れ子のcavity、開放・閉鎖混在、open winding、
  self-intersection、non-manifold、保護edgeの検査。
- 極小・大座標、平行移動した小形状、単位変換のoverflow/underflowの回帰。

符号付き体積と法線方向の比較はbinary64の入力をEPECKへ変換し、
exact演算の符号で判定します。出力の点座標自体はEPICKです。
距離検証の誤差境界を省略したり、要求kernelを黙って変更したりしません。

`FastEnvelope_filter`は別の外部ヘッダー依存が未導入のため`BLOCKED`です。
この機能を要求する計画は実行できません。主要要件7.7.05の
`Polyhedral_envelope_filter`とは別の補助policyです。

Windowsでの再試験:

```powershell
.venv/Scripts/python.exe scripts/verify_master_wave_a.py `
  --worker build-master/Release/cgal-master-worker.exe `
  --output work/master-wave-a-local.json
```

Linuxではworkerを`build-master/cgal-master-worker`へ置き換えます。
このrunnerは実worker試験とMCP auto/legacyの実計算を再実行してから、
manifest・catalog・試験コードのハッシュ付き報告を生成します。
報告の`requirements`は空、`standalone_accepted`はfalseです。
主要能力の完成判定とは別の証拠として扱います。

実PCのVS2026/Python3.13結果は
[`evidence/wave-a-windows-vs2026.json`](evidence/wave-a-windows-vs2026.json)。
独立レビューの残存High/Mediumは0です。CIでは公式6.2.1からLinuxと
Windows VS2022をビルドし、同じrunnerを実行します。
