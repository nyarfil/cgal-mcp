# メッシュ検査・計測の実装区切り

以下の6処理を、元メッシュを変更しないanalysisとして実装し、正式workerと
汎用coreへ統合しました。専用validatorを含む12 Operationは`VALIDATED`です。

- PMPとraw OFFの健全性検査。
- 面の連結成分。
- 面・頂点法線と、面法線を各cornerへ割り当てたflat corner report。
- 面積、閉鎖性・向き等の前提を満たす場合の体積・体積重心。
- 明示したdeg／radの角度に基づくsharp feature。
- 自己交差する面対の検出。

結果は`GeometryAnalysisReport/json/none`として扱い、元メッシュのID・hash・型・
形式・長さ単位を保持します。面積・体積・位置は結果内に次元と単位を記録します。
取得不能な量には理由を返します。report全体の`none`は、量の単位省略を意味しません。
cornerはflat方式です。任意のsmooth／crease方式を提供する完成表示ではありません。

各処理の後に、元メッシュと候補reportを入力とする別の専用validatorを実行します。
producer内の診断だけでは合格Artifactにせず、validatorの失敗・判定不能は隔離します。
角度の単位変換もPlan・Artifactの履歴へ記録します。

健全性検査とそのvalidatorは`PolygonSoup3/OFF`も扱い、退化・非多様体・
非三角形・辺向き不整合を取込み後に診断できます。他のanalysisは構成可能な
三角形メッシュを前提とします。取込みの退化判定は、必要時にbinary64座標を
正確な有理数へ変換して行い、微小形状のunderflowによる誤分類を防ぎます。

bounded reportと列挙の上限を使い、大量の結果を無制限にMCPへ返しません。
体積の前提を満たさない開放・自己交差メッシュや数値のoverflow／underflowは、利用不能を明示します。
退化・非多様体・自己交差などの検査結果と、安全な構文読込みを分けています。
近似binary64で返す法線・計測・角度判定は`package_recommended`限定です。
exact-constructions要求を黙って近似出力に変更しません。

これは原本7.3全体の完了ではありません。距離、mesh間交差、location、その他の
predicateや選択可能なAPI・named parameterの対応は、別途確認・実装が必要です。
修復、Boolean、remeshingもそれぞれ専用の実装区切りで進めます。

実装候補の直接試験は`tests/master_wave_a_mesh_cases.py`、MCP試験は
`tests.master_wave_a_mesh_mcp_e2e`のauto／legacyです。
次のreport生成コマンドは、全12件が`VALIDATED`の正式buildで再試験するゲートです。

```powershell
.venv/Scripts/python.exe scripts/verify_master_wave_a_mesh.py `
  --worker build-master/Release/cgal-master-worker.exe `
  --output work/master-wave-a-mesh-local.json
```

実worker・拡張したMCP auto／legacy試験・独立レビューを確認しました。
レビューの残存High／Mediumは0です。実PCの記録は
[`evidence/wave-a-mesh-windows-vs2026.json`](evidence/wave-a-mesh-windows-vs2026.json)です。
Standalone全体の受入は未達です。
