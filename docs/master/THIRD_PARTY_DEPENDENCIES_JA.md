# 任意の第三者依存（OpenGR・SCIP・SoPlex）

worker（`worker/CMakeLists.txt`）は、次の3つのライブラリを**任意依存**として扱います。
見つからない場合もworkerは通常どおりビルドされ、関連Operationは
`UNSUPPORTED` / `OPTIONAL_DEPENDENCY_NOT_BUILT` を返します（登録Operation自体は
manifestに載り、`info.optional_dependency_built` で有無を報告します）。

| 名前 | 版 | license | 取得元 | 配布物sha256 | 用途 |
|---|---|---|---|---|---|
| OpenGR | v2023.11 | Apache-2.0 | https://github.com/STORM-IRIT/OpenGR/archive/refs/tags/v2023.11.tar.gz | `3b2229c6c84d6025571f4a197accce3d952c9520d9a16a25ca61768eb51615b5` | `CGAL::OpenGR::register_point_sets`・`compute_registration_transformation`（Super4PCS） |
| SoPlex | 8.0.3 | Apache-2.0 | https://github.com/scipopt/soplex/archive/refs/tags/v8.0.3.tar.gz | `224eca4c49a2509a2a893a1d4b63e510e2ddb4ff374699cc6afc36f12af4e621` | SCIPのLP solver |
| SCIP | 10.0.3 | Apache-2.0 | https://github.com/scipopt/scip/archive/refs/tags/v10.0.3.tar.gz | `6eb97f4d647b6ef734dc9fbd8d35761de367b68de9d881cfd1bc8f460c0004f1` | `Polygonal_surface_reconstruction` の混合整数計画 |

- 配布物のsha256は取得時に公式tarballと照合済みです（記録: `E:\aiwork\deps\PROVENANCE.md`）。
  commit（OpenGR `abfe0f4d`、SoPlex `13e2ab24`、SCIP `d409edf9`）は研究時の固定値で、
  OpenGRのarchiveには`.git`がなく独立確認していません。
- インストール先（リポジトリ外）: `E:/aiwork/deps/opengr`、`E:/aiwork/deps/soplex`、`E:/aiwork/deps/scip`。
  ビルド成果物・ソース・ライブラリは**コミットしません**。
- ビルド条件: Visual Studio 18 2026 BuildTools、x64 Release、`/MD`。3つとも静的ライブラリで、
  追加のruntime DLLはありません（gmpはCGAL側で既存）。
- 主要な構成フラグ: OpenGRは`-DOpenGR_COMPILE_TESTS=OFF -DOpenGR_COMPILE_APPS=OFF`、SoPlexは
  `-DGMP=OFF -DBOOST=OFF -DZLIB=OFF -DPAPILO=OFF`、SCIPは`-DSHARED=OFF -DLPS=spx -DEXPRINT=none
  -DIPOPT=OFF -DZIMPL=OFF`。詳細は上記PROVENANCE.mdにあります。

## worker側の有効化

```
-DCMAKE_PREFIX_PATH=E:/aiwork/deps/soplex;E:/aiwork/deps/scip;E:/aiwork/deps/opengr
-DOpenGR_DIR=E:/aiwork/deps/opengr/lib/cmake/opengr
-DSCIP_DIR=E:/aiwork/deps/scip/lib/cmake/scip
```

`scip-config.cmake`が`SOPLEX_DIR`を上書きするため、SoPlexは`CMAKE_PREFIX_PATH`にも必要です。
OpenGRのみ・SCIPのみの組合せも可能で、それぞれのソースファイルだけがcompile definition
（`CGAL_LINKED_WITH_OPENGR`、`CGAL_USE_SCIP`）とinclude pathを受けます。

## 再現性と制約

- Super4PCSの乱数seedはOpenGR既定（`std::mt19937::default_seed`）に固定され、CGAL APIからは
  変更できません。探索は壁時計の上限（`maximum_running_time`）で打ち切られるため、上限に達した
  実行は拒否します。サンプル数・accuracy・overlapを全て型付きparameterとして固定し、
  結果のscoreとともに記録します。
- 記載の版・licenseは取得元の公開情報に基づきます。配布時のlicense表記の最終確認は
  リリース工程で必要です。

79/80はOpenGRとSCIPの両方を含むworkerでのみ再現できます。どちらかが無いworkerでは7.9または7.10が`OPTIONAL_DEPENDENCY_NOT_BUILT`となり、再試験は明確なメッセージ（requires OpenGR,SCIP）で終了するか、`--skip-unavailable-optional`で当該familyを除外して減った件数を報告します。libpointmatcherは導入しておらず対象外です。
