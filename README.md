# CGAL MCP
独立CGAL MCPを実装し、検証後にStellaCADへ統合するプロジェクト。

## 実装状態
- 能力検索・オンデマンド定義取得: 実装、CI検証済み。
- MCP公式SDK 2.3.0の通信入口: 実装、公式Clientで検証済み。
- C++17 CGAL 6.2.1 worker: plane+line簡略化、境界拘束、Constrained placement、
  任意のPolyhedral Envelopeフィルタを実装。CIでビルド/実計算検証。
- Hausdorff、明示稜線拘束、asset/job管理、Planner、100+ API索引: 未実装。

MCP入口は現段階で検索/定義取得のみ。workerは内部CLIとして独立し、
MCPからの幾何計算実行はまだ公開しません。
全CGAL機能を完全に検証済みという意味ではありません。

## 導入
Python 3.10以上、C++17コンパイラ、CMake 3.22以上、CGAL 6.2.1、
Boost、GMP、MPFR、nlohmann-jsonが必要です。

```sh
git clone https://github.com/nyarfil/cgal-mcp.git
cd cgal-mcp
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m cgal_mcp.server
```

最後のコマンドはstdio MCPサーバーを起動します。MCPホストから同じコマンドを
起動し、作業ディレクトリをこのリポジトリに設定してください。

```sh
cmake -S worker -B build -DCGAL_DIR=/absolute/path/to/CGAL-6.2.1 -DCMAKE_BUILD_TYPE=Release
cmake --build build -j1
python tests/worker_smoke.py build/cgal-worker
```

workerはstdinでversion=1, operation=simplify, input, output, edge_ratio,
preserve_border, envelopeを持つJSONを1件読み、stdoutにJSONを1件返します。
edge_ratioは残す辺の割合で(0,1)。envelopeは入力座標の単位で0なら無効。
入力の上書き防止、単位、パス管理、self-intersection検査は今後のjob層で実装するため、
workerを外部ユーザーに直接公開しないでください。
Hausdorff保証は未実装で、結果のhausdorff_verifiedは常にfalseです。

## 資料
- [設計仕様](docs/specification.md)
- [設計書](docs/architecture.md)
- [StellaCAD統合案](docs/stellacad-integration.md)
- [調査記録](docs/research.md)
- [検証記録](docs/validation.md)
