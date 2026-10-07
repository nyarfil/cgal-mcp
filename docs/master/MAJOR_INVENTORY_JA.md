# 主要能力の実装候補台帳

原本7.1〜7.15の全80要求を
[`catalog/major_capability_inventory.json`](../../catalog/major_capability_inventory.json)へ
対応付けました。source・版固定HTML・公式example・依存根拠から、
今後のadapter/validator/fixture実装の候補を調べるための資料です。

この台帳は実装状態を評価しません。実装・検証状態の正本はOperation registryと
実計算を再試験する受入報告です。source内で名前が見つかった事実と、宣言の
確認、実装、検証、原本要求全体の達成は別々に扱います。

- 原本の固定受入母数は80要求です。
- 203件のsymbolは暫定・非網羅の候補です。全203件を満たしても、
  原本の全主要能力を満たした証拠にはなりません。
- symbol出現は`CANDIDATE_SYMBOL_OCCURRENCE`、宣言は
  `DECLARATION_UNVERIFIED`です。呼出しや文字列の出現も含み得ます。
- OpenGRやEigenは、採用するAPIで必須か、別の数値型を選べるかを区別します。
- Approximate Convex Decompositionはsource package名を保持しつつ、
  `Convex_decomposition_3`の公式HTML・exampleへ関連付けています。
- FastEnvelopeはPolyhedral Envelopeの主要求と分離し、外部取得・版固定が
  必要な補助policyとして記録します。

再生成には、チェックサム検証済みの公式source/docsが必要です。

```sh
python scripts/build_major_inventory.py
```

CIは台帳を公式配布物から再生成してバイト一致を検査します。
原本要求のID・説明・必須指定と原本hashを正規化したprojectionに結び付け、
改行形式やbuildごとの実行証拠の違いを実装候補台帳へ混入させません。
原本MD自体は変更しません。台帳の独立レビューで見つかった、宣言判定、
候補件数の過大解釈、依存条件、docsの関連付けを修正しました。

## 再試験への結合状況

[受入判定](CAPABILITY_ACCEPTANCE_JA.md)で実計算に結び付いた要求と、未結合の理由です。
分母は各分野の原本要求数です。

| 分野 | 結合/全体 | 結合済み要求 |
|---|---|---|
| 7.3 解析 | 3/8 | 7.3.01 検査・自己交差、7.3.03 法線、7.3.04 計測 |
| 7.4 修復 | 5/6 | 7.4.01 向き、.02 境界縫合、.03 退化除去、.05 polygon soup、.06 非多様体前処理 |
| 7.5 Boolean | 1/5 | 7.5.02 union/intersection/difference |
| 7.7 軽量化 | 6/6 | 7.7.01〜06 |
| 7.8 再構成 | 0/6 | なし（検証済みOperationなし） |
| 7.9 点群 | 2/6 | 7.9.01 法線推定・MST向き付け、7.9.04 grid/random/hierarchy簡略化 |
| 7.13 凸包等 | 0/5 | なし |

未結合要求の不足:

- 7.3.02: connected component / keep largest を公開Operationにしていない。
- 7.3.05: sharp edge / segmentation がない。
- 7.3.06: 距離はvalidator内部の上界付き対称Hausdorffのみで、他の距離関数がない。
- 7.3.07: 2メッシュ間の交差判定を公開していない。
- 7.3.08: locate（点位置・AABB問合せ）Operationがない。
- 7.4.04: `triangulate_refine_and_fair_hole`相当の穴埋めがない。
- 7.5.01: corefine / autorefine はBoolean内部のみで単独公開していない。
- 7.5.03〜05: clip、split、slicer がない。
- 7.9.02、7.9.06: `compute_average_spacing`等の解析を公開していない。
- 7.9.03: bilateral等のsmoothingがない。
- 7.9.05: registration がない。
- 7.8.01〜06: 再構成Operationがない。
- 7.13.01: 検証済みは3D凸包のみで2D凸包がない。7.13.02〜05: alpha shape、wrap、
  bounding volume、barycentric座標がない。
