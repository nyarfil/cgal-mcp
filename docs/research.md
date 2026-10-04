# 調査記録
確認日: 2026-10-04（日本時間）。
以下はGitHubの公式原典を読んだ確認結果。Web全体の調査完了ではない。

- https://github.com/CGAL/cgal/releases/tag/v6.2.1
  最新リリースAPIはv6.2.1を返した。2026-09-04公開のbug-fix release。
- https://github.com/modelcontextprotocol/python-sdk/blob/main/README.md
  取得したREADMEはMCPServerを案内しPython 3.10+としている。
  mainのAPIを安定リリースとして断定しない。実装前にタグ/リリースを確認する。
- https://github.com/modelcontextprotocol/modelcontextprotocol
  MCP仕様の調査対象。現時点では仕様本文の確認未完了。

未完了: CGAL 6.2.1重点APIのヘッダー/examples確認、MCP仕様版選定、
既存CGAL MCP調査、Python bindings対応範囲、ライセンス確認。
前会話のGSoC/bindingsの記述は確認済み事実として扱わない。
