# MCP接続の障害隔離試験

`tests/master_fault_mcp_e2e.py`は、固定のテスト用Python workerを使って
実際のMCPサーバーに障害を起こし、同じ接続で後続処理が使えるかを検査します。
CGALの幾何能力を証明する試験とは別に扱います。

検査する故障は、process終了、assertion相当の応答、不正JSON、request ID不一致、
stdout上限超過、timeout、OSで強制したメモリ超過です。中止も検査します。
各故障について分類・失敗状態・出力非公開・入力保持を確認し、
その直後に同じMCP接続で新しいjobを成功させます。

```sh
python -m tests.master_fault_mcp_e2e auto
python -m tests.master_fault_mcp_e2e legacy
```

実PCでは両モードが合格しました。中止の測定値はauto 0.009秒、legacy 0.006秒。
これは制御されたsleep fixtureでの値であり、大きなCGALデータの性能結果では
ありません。CIのPython3.12/3.13・Linux/Windowsでも同じ試験を実行します。

実CGALの各algorithmでの障害、代表データの最大メモリ、cache・永続workerの
障害回復と資源回収は別の受入項目です。これらが未達の間はStandaloneを
完成扱いにしません。
