# CGAL Master MCP（開発中）

目標は、CGAL全体の能力を発見・選択・組合せ・実行・検証できる独立MCP。
**現在のコードは軽量化関連のv0.1で、Master MCPの要求は未達です。**
ユーザー提供の設計書と現状差分、修正した開発順序は
[開発基準](docs/master/SCOPE_CORRECTION_JA.md) を参照してください。
StellaCADはStandalone受入後に正式統合する利用側です。

## 現在実装済みのv0.1
Python MCP/Router/PlannerとC++17 CGAL 6.2.1 workerによる、検証付きメッシュ簡略化。

## 提供する機能
- 常時11ツールだけ提示。日英能力検索、個別Schema取得、Router、型付き計画。単独比較はplan_hausdorffで計画。
- 102件の版固定CGALヘッダー索引をオンデマンド検索。102件の実行機能ではありません。
- plane+line簡略化、任意Envelope、境界/明示辺拘束、Constrained placement。
- 双方向bounded-error Hausdorff検証。合格した成果物のみ公開。
- 資産ハッシュ、非同期job、timeout、cancel、監査記録。
- StellaCADのrevision/undo付きホスト境界と統合設計。

## 導入（Linux）
Python 3.10+、C++17、CMake 3.22+。CIはUbuntu/Python3.12で検証します。

```sh
git clone https://github.com/nyarfil/cgal-mcp.git
cd cgal-mcp
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
sudo apt-get update
sudo apt-get install -y libboost-all-dev libgmp-dev libmpfr-dev libeigen3-dev nlohmann-json3-dev
mkdir -p work
curl -fL https://github.com/CGAL/cgal/releases/download/v6.2.1/CGAL-6.2.1.tar.xz -o work/cgal.tar.xz
echo 'b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf  work/cgal.tar.xz' | sha256sum -c -
tar -xf work/cgal.tar.xz -C work
cmake -S worker -B build -DCGAL_DIR="$PWD/work/CGAL-6.2.1" -DCMAKE_BUILD_TYPE=Release
cmake --build build -j1
python -m unittest discover -s tests -v
python tests/worker_smoke.py build/cgal-worker
python tests/distance_smoke.py build/cgal-distance
python tests/worker_cases.py build/cgal-worker
PYTHONPATH=. python tests/mcp_e2e.py
```

CGALを含む配布では対象パッケージのGPL/commercial条件を確認してください。
Windowsの導入・実計算手順は [Windows導入](docs/windows.md) を参照してください。
macOSとネイティブCADの置換/Undo統合は未検証です。

## MCP接続
MCPホストのstdio設定に、以下のcommand/args/envを登録します。
ホストによって設定ファイル形式は異なるため、絶対パスを実環境に置き換えてください。

```json
{
  "command": "/absolute/path/cgal-mcp/.venv/bin/python",
  "args": ["-m", "cgal_mcp.server"],
  "env": {
    "CGAL_MCP_WORKER": "/absolute/path/cgal-mcp/build/cgal-worker",
    "CGAL_MCP_DISTANCE": "/absolute/path/cgal-mcp/build/cgal-distance",
    "CGAL_MCP_DATA": "/absolute/path/cgal-mcp/work/data"
  }
}
```

## 操作例
1. discover_capabilities(query="軽量化") または route_goal。
2. describe_capability(capability_id="mesh.simplify")で入力Schema取得。
3. register_mesh(off=<ASCII三角形OFF>, unit="mm")でasset_idを取得。
4. plan_simplification(asset_id, parameters)でplan_idを取得。
5. execute_plan(plan_id)でjob_idを取得。
6. job_status(job_id)でsucceededまで確認。取消はcancel_job。
7. get_artifact(asset_id=<結果artifactのID>)でOFF/単位/ハッシュを取得。

parameters例:
```json
{
  "edge_ratio": 0.5,
  "tolerance": 0.1,
  "error_bound": 0.001,
  "envelope": 0.01,
  "preserve_border": true,
  "constrained_edges": [[0, 1]]
}
```

残す辺の割合50%、mm入力なら許容誤差0.1mm。指定辺は入力頂点番号で実在する必要があります。
拘束により割合に届かない場合も実測値とtarget_metを返します。
検証fail/indeterminateはrejectedで、成果物を公開しません。
stdio出力はMCP通信専用。診断はworker結果かjobのerrorで確認します。

## 制限
入力OFFは4MiB以下の三角形メッシュ。材質・UV・B-rep・面IDの自動維持は対象外。
plan/job索引はセッション内。再起動で復旧しませんが監査ファイルと資産は残ります。
ローカルの信頼されたホスト向けで、HTTP公開・複数利用者認証・分散処理は対象外。
全CGAL APIを実行する完成品という意味ではなく、重点機能を接続したv0.1です。
StellaCAD本体への接続には本体リポジトリのホスト実装が必要です。

## 設計と検証
- [設計仕様](docs/specification.md)
- [設計書](docs/architecture.md)
- [StellaCAD統合設計](docs/stellacad-integration.md)
- [調査記録](docs/research.md)
- [検証記録](docs/validation.md)
