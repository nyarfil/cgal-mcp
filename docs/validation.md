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

## Windows引継ぎ・StellaCAD sidecarのローカル検証

確認日: 2026-10-04（日本時間）、元commit `4304894` からのローカル変更。
環境: Windows x64、Python 3.13.4、MCP SDK 2.3.0、MSVC 19.50、
CGAL 6.2.1、Eigen 5.0.1、nlohmann-json 3.12.0、trimesh 4.12.2。

- 引継ぎ直後: 23テスト中7件が失敗。Windowsのtext writeによる改行変換が
  登録時とファイルのハッシュを変えたため。資産をUTF-8 bytesのまま保存・取得して修正。
- 更新後: unittest 28件成功。LF/CRLFの厳密なhash往復、workerパス、
  実子プロセスのtimeout/cancel、STLの完全一致頂点接続、上書き拒否、却下時未公開を確認。
- `worker_smoke.py`: plane+line、Envelope、境界位置保持、不正ratio拒否 PASS。
- `distance_smoke.py`: 双方向Hausdorff、pass/fail/indeterminate PASS。
- `worker_cases.py`: 曲面、穴付き平面、自己交差入力拒否 PASS。
- `tests.mcp_e2e`: in-process、stdio auto、stdio legacyで登録→計画→実worker→
  独立Hausdorff→受理artifact→単独距離検証 PASS。
- StellaCADの実Codex設定から隔離workspaceへ起動したsidecar: 12工具の列挙成功。
  auto/legacyとも200面STL→92面STL。計算結果とSTL書出し後の再読込検証の両方がpass。
  元ファイルのSHA-256不変、出力SHA-256一致、再実行での上書き拒否を確認。

実PCの証拠:
`E:/aiwork/Stella_CAD_SYSTEM/integration/cgal/verification/20261004-installed/report.json`。
ネイティブCADの選択オブジェクト置換・Undo、STEP/F3D直接処理、macOSは未検証/未実装。

追加回帰検証: export後の距離検証がfail/indeterminateの場合に派生ファイルを
公開しない試験を追加し、2026-10-04にunittest 29件が成功。
これらはv0.1の証拠であり、Master MCPの受入は
`master/SCOPE_CORRECTION_JA.md` の差分/基準により別途判定する。
