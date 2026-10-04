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
