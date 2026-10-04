# Wave A: メッシュBooleanの受入範囲

CGAL 6.2.1のPMP corefinementを、汎用coreの3処理と3つの専用validatorへ組み込んだ。公開MCP工具は12個のまま維持する。

| 処理 | 必須validator |
|---|---|
| `mesh.boolean.union` | `mesh.validate.boolean_union` |
| `mesh.boolean.intersection` | `mesh.validate.boolean_intersection` |
| `mesh.boolean.difference` | `mesh.validate.boolean_difference` |

canonical registryは`catalog/operations_wave_a_boolean.json`、受入済みrevisionは`wave-a-boolean-validated-1`である。native・汎用core・実MCP auto/legacyの独立レビューはHigh 0件、Medium 0件だった。この6 Operationの受入は、PMP全体やStandalone完成の判定ではない。

## 入出力と精度

入力は同じ単位の閉鎖三角形メッシュ2個で、OFF形式、mm/cm/mに対応する。異なる単位を黙って混ぜず、計画時に拒否する。構文を読み込める形状でも、開放面、非多様体、退化、自己交差、体積境界として不適切な向きは計算前に拒否する。空洞と複数の体積成分も検証対象に含めた。

入力のbinary64座標を正確な二進有理数としてEPECKへ渡す。出力の標準OFFにはbinary64で正確に表せる座標だけを公開し、表現できない交点は`OUTPUT_BINARY64_LOSS`で失敗させる。無断の丸めやkernelの精度低下は行わない。

空の積・差は、頂点数・面数がともに0のcanonical OFFとして保存する。接触の結果が非多様体となる和集合は出力せず、原因を返す。各入力の上限は256 MiB、20万頂点、40万面で、座標尺度にもregistry記載の数値範囲を適用する。

## 検証と履歴

専用validatorは結果、入力A、入力B、処理種別を計画へ厳密に結び付ける。公式アルゴリズムの別process再計算に加え、体積、集合としての相互差、内外分類、閉鎖性、向き、自己交差を検査する。producerの成功通知だけでは公開しない。失敗・判定不能は診断用に保存し、原本を保持する。

直接試験では重なり、分離、包含、同一形状、面・点接触、部分共面、空出力、改ざん、精度損失を確認した。MCP auto/legacyでも計画、必須validator挿入、実計算、検査、原子的公開、原本保持を確認した。

```powershell
.\.venv\Scripts\python.exe scripts/verify_master_wave_a_boolean.py --worker build-master/Release/cgal-master-worker.exe --output work/master-wave-a-boolean.json
```

このgeneratorは6 Operationが`VALIDATED`であることを要求し、nativeと実MCP auto/legacyを再実行する。レポートの`standalone_accepted`は`false`を維持する。原本7.3には修復、remeshなどの残項目があり、この文書から機能群全体の完成を推定しない。
