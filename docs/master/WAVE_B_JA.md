# 点群処理の汎用core統合

7 transformと5 validatorを正式workerへ追加し、各処理を必須検証付きで実行できます。
固定12工具の公開面を維持しています。

- 外れ値除去。
- grid・seed付きrandom・hierarchyによる間引き。
- Jet平滑化。
- PCA／Jetによる法線推定。
- MSTによる法線の向き統一。

各transformは基本健全性と専用contract validatorの両方を通過してから
Artifactを公開します。専用validatorはsourceと固定parameterから公式CGAL処理を
再計算して照合します。randomでは期待点数と選択、法線ではunit-vectorや
局所近傍の前提も検査します。近傍が不適切な入力を正常な法線として公開しません。

法線付き点群は`PointSet3Normals`のASCII PLYで安全に取込み・書出しできます。
非unit法線を安全な読込み段階で拒否することと、MST前提として拒否することは
分けています。点群の原本を保持し、型・単位・生成処理を履歴へ記録します。

外れ値除去→法線推定→MSTの型付きDAGも実計算済みです。先行stepで決まる
点数は計画時に推測せず、出力のinspection後・worker実行前に前提を解決します。
過大な近傍指定では結果を公開しません。

精度の対応範囲は明示しています。現在の点群adapterはEPICK/Eigenの
`package_recommended`を採用し、exact-constructions要求には対応しません。
極端な座標・小尺度・座標/cell比・translation/span比・局所rank不足は
計算前に理由付きで拒否します。範囲を黙って丸めたり精度を下げたりしません。
詳細な数値条件はOperation metadataへ記録しています。

数値tokenの読込みはlocaleに依存しない`std::from_chars`でbinary64へ変換します。
表現可能な極小値は構文として受け入れ、非unit法線は幾何validatorで拒否します。
binary64の範囲外、非有限値、十六進表記、余分な符号やsuffixは計算前に拒否します。
Linuxの`std::stod`が表現可能なsubnormalにもrange例外を出す差異を解消し、
同じ入力に対する分類をWindowsと揃えています。

独立レビューの残存High/Mediumは0。公式6.2.1 worker、各algorithm・偽候補・
数値境界の直接試験、MCP auto/legacy、型付きDAGが合格しています。

```powershell
.venv/Scripts/python.exe scripts/verify_master_wave_b.py `
  --worker build-master/Release/cgal-master-worker.exe `
  --output work/master-wave-b-local.json
```

Linuxではworkerを`build-master/cgal-master-worker`へ置き換えます。
実PCの記録は[`evidence/wave-b-windows-vs2026.json`](evidence/wave-b-windows-vs2026.json)。

これは原本7.9全体の完了を意味しません。registration、bilateral平滑化、
その他の前処理や再構築などは別途実装・検証が必要です。
全80要求・Standaloneの完成表示は引き続き未達です。
