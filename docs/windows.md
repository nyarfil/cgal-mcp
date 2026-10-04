# Windows導入とStellaCAD接続

このPCでは `E:/aiwork/cgal-mcp` に独立環境を配置し、既存の
`V:/Program-files/CGAL` のCGAL 6.2.1を利用する。
CGAL本体、Eigen、JSONの依存を使い、他のCAD Python環境とは混ぜない。

```powershell
cd E:\aiwork\cgal-mcp
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e '.[mesh]'
& V:\Program-files\CGAL\vcpkg\vcpkg.exe install eigen3:x64-windows nlohmann-json:x64-windows --x-install-root=V:\Program-files\CGAL\vcpkg_installed
cmake -S worker -B build -G 'Visual Studio 18 2026' -A x64 -DCMAKE_TOOLCHAIN_FILE=V:/Program-files/CGAL/vcpkg/scripts/buildsystems/vcpkg.cmake -DVCPKG_INSTALLED_DIR=V:/Program-files/CGAL/vcpkg_installed
cmake --build build --config Release --parallel 1
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe tests/worker_smoke.py build/Release/cgal-worker.exe
& .\.venv\Scripts\python.exe tests/distance_smoke.py build/Release/cgal-distance.exe
& .\.venv\Scripts\python.exe tests/worker_cases.py build/Release/cgal-worker.exe
& .\.venv\Scripts\python.exe -m tests.mcp_e2e auto
& .\.venv\Scripts\python.exe -m tests.mcp_e2e legacy
```

Visual Studioのgeneratorは実際に導入した版に合わせる。Eigenは3.1以上を要求し、
このPCのvcpkg版5.0.1でビルド・実計算を確認した。
vcpkgがworker横にGMP/MPFR DLLをコピーするので、そのDLLも保持する。

StellaCAD側は `integration/cgal/stella_cgal_mcp.py` を起動する。
再配置時は、このリポジトリの `integration/stellacad/` に保存したlauncherと接続試験を
StellaCAD側の `integration/cgal/` へコピーしてから登録する。
独立MCPの11工具と、STL/OFF派生ファイルの軽量化工具を追加する。
設定登録は次を実行する。既存のMCP設定は保持し、変更前の設定はCodexのbackupsに保存する。

```powershell
& .\.venv\Scripts\python.exe scripts/link_stella.py --stella-root E:\aiwork\Stella_CAD_SYSTEM --codex-home C:\Users\nikis\.codex --codex-project 'Z:\windows_SystemFile\ドキュメント\ChatGPT\ステラキャド'
codex mcp get cgal-mcp
```

設定登録後は新しいチャット/セッションで工具を読み込む。
現在のチャットからも `python -m cgal_mcp.file_bridge` または公式SDKのstdio接続で実行できる。
接続設定の確認と、工具への実呼び出し成功は別に報告する。
STEP/F3Dは選択済みCADの許可された読取・書出し経路で三角形STLへ書き出してから渡す。
結果は新規STL/OFFで、元のB-rep、ネイティブ編集履歴、UV、材質、面IDを復元しない。
