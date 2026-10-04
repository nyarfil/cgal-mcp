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
