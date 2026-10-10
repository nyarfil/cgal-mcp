# 全package harvest: status・license・provenanceの機械検査

`catalog/packages.json`（126 package、CGAL 6.2.1固定）の各recordは、次を持ちます。

- `status` / `reason_code` / `reason` / `coverage`: 語彙は `VALIDATED`・`CATALOGED`・`BLOCKED`・`EXCLUDED`
  （`IMPLEMENTED`・`ADAPTER_PLANNED`も許容）。`VALIDATED` は `cgal_mcp/master/operations.json` に
  primary packageとして `VALIDATED` Operationが1件以上ある場合だけで、`coverage` にOperation数とヘッダー被覆
  （部分被覆）を記録します。それ以外は `catalog/package_status_policy.json` の理由コード
  （`gui_only`、`io_only`、`generic_support_infrastructure`、`no_public_headers`、
  `data_structure_adapter_not_implemented`、`algorithm_adapter_not_implemented`）が必須です。
  `BLOCKED`（`needs_third_party_lib`）は定義済みですが、現在は該当packageがありません。
- `license`: 公式Package Overviewのlicenseタグを指定元とし、全ヘッダーのSPDXで裏付けます。
  `RESOLVED` / `MIXED`（ファイル単位の例外を列挙）/ `NEEDS_HUMAN_REVIEW` / `UNRESOLVABLE`（理由を記録）。
  `include/CGAL/license/<package>.h` のSPDXは全packageで同一のため、package licenseの判別には使いません。
  **これは出典付きのprovenanceデータであり、法的助言ではありません。**
- Operationのlicenseは、構成packageの記録から導出して一致を検査します。

再生成: `python scripts/harvest_cgal.py`（固定入力が必要）後に `python scripts/sync_master_package_catalog.py`。
検査: `python scripts/package_provenance.py`、およびstandalone gate `package_harvest_provenance`
（`python -m scripts.master_acceptance`）。人手のlicense確認が残る間、このgateは `unmet` のままです。
