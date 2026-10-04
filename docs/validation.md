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
