# 検証記録
## 4033374a748b6306c68968a58be22f551c135fca
[Python/MCP CI](https://github.com/nyarfil/cgal-mcp/actions/runs/37207081290): 成功。
Python 3.12、MCP 2.3.0。9テスト成功。
公式Clientによるツール列挙、検索、定義取得を確認。in-process接続であり、
外部ホストのstdio接続・resources・HTTP transportは別途検証する。

[CGAL CI](https://github.com/nyarfil/cgal-mcp/actions/runs/37207081249):
初回ビルド失敗: Eigen/Denseが見つからない。Eigen3を明示依存として追加して再実行。
成功前にverifiedとして扱わない。
実計算は10x10平面グリッドの簡略化、Envelope、境界頂点の位置保持、
不正ratio拒否を確認する。一般形状の保証・Hausdorff検証ではない。

## f00b2441095642218e2a301f3acfe089fcc1e0fb
[CGAL worker CI](https://github.com/nyarfil/cgal-mcp/actions/runs/37207199664): 成功。
Eigen依存を修正。plane+line、Envelope、境界拘束のグリッド実計算が成功。

## 02879d575bc99ec2f6bc1f4583a1774d4584f0c6
[CGAL worker + distance CI](https://github.com/nyarfil/cgal-mcp/actions/runs/37207278502): 成功。
C++17、CGAL 6.2.1の配布archiveをSHA-256確認して使用。
1単位離れた平行三角形の双方向bounded-error距離を確認。
許容値1.01でpass、0.9でfail、1.0でindeterminate。
この限定fixtureでの成功を全メッシュ種類での検証として扱わない。

## 最終検証: e44dcc514e877e24461adf339ad7f6bcab2f627d
確認日: 2026-10-04（日本時間）。
- [Python / MCP CI](https://github.com/nyarfil/cgal-mcp/actions/runs/37208836611): 成功、23テスト。
- [CGAL / MCP通しCI](https://github.com/nyarfil/cgal-mcp/actions/runs/37208836604): 成功。

検証内容:
1. 102件の版固定索引、日英候補検索、個別定義取得、正しいレシピへのRouter選択。
2. 公式SDK 2.3.0によるin-process通信と実stdio通信（auto/legacy）、resource取得。
3. パッケージのeditable install、スキーマ検査、不正値/不正OFF/未知ID/入力変更拒否。
4. 非同期jobのqueued取消、実行中取消、timeout、プロセス終了、worker欠落のfailed。
5. CGAL 6.2.1/C++17ビルド、plane+line、Envelope、境界/明示辺拘束、
   Constrained placement、自己交差/退化検査。
6. 平面グリッド、閉じた曲面、穴付き平面、自己交差入力。
7. 双方向bounded-error Hausdorff、pass/fail/indeterminate。
8. MCP登録→型付き計画→job実行→CGAL簡略化→独立検証→受理成果物取得。
9. MCPによる2資産の単独Hausdorff計画と実行。
10. CAD変更時の適用拒否、atomic applyのホスト契約、同形状の別オブジェクトの分離。

限界:
- fixtureでの成功は全CGAL API・全入力の検証を意味しない。
- 102件はヘッダー検索索引。実行対象は重点の5能力とその組み合わせ。
- StellaCAD本体ソースに対するパッチ・実UI/Undo試験は未実施。
- Windows/macOS、HTTP公開、分散job、再起動時のjob復旧は未検証/対象外。
