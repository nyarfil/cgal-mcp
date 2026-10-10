"""Measure the blind search set once and record the result as evidence.

The blind set (docs/master/search_blind_set.json) was authored from operation
documentation before any routing output was inspected.  This script is run once
after search tuning is frozen; it never changes the set or the router.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
BLIND = REPO / "docs" / "master" / "search_blind_set.json"
EVIDENCE = REPO / "docs" / "master" / "evidence" / "search-blind.json"


def _arg(name: str, default: Path) -> Path:
    # Optional "--set PATH" / "--evidence PATH" (relative to the repository root) select another blind set.
    return REPO / sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


BLIND = _arg("--set", BLIND)
EVIDENCE = _arg("--evidence", EVIDENCE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure() -> dict:
    from cgal_mcp.master.runtime import MasterRuntime
    blind = json.loads(BLIND.read_text(encoding="utf-8"))
    requirements = json.loads((REPO / "catalog" / "major_requirements.json").read_text(encoding="utf-8"))
    bound = {r["id"]: set(r["operation_ids"]) for f in requirements["families"] for r in f["requirements"]}
    runtime = MasterRuntime(Path(tempfile.mkdtemp()) / "store", require_memory_limit=False)
    cases = []
    try:
        for item in blind["intents"]:
            ids = [c["operation_id"] for c in runtime.capabilities_search(
                item["query"], artifact_ids=[], constraints={}, limit=3)["candidates"]]
            exact = set(item["expected_operations"])
            req = bound[item["requirement_id"]]
            cases.append({"id": item["id"], "language": item["language"], "family": item["family"],
                          "expected": sorted(exact), "returned": ids,
                          "op_top1": bool(ids and ids[0] in exact), "op_top3": bool(exact & set(ids)),
                          "req_top1": bool(ids and ids[0] in req), "req_top3": bool(req & set(ids))})
        # Informational fail-closed probes (not in the denominators): record what search returns.
        out_of_scope = [{"id": item["id"], "language": item["language"], "query": item["query"],
                         "returned": [c["operation_id"] for c in runtime.capabilities_search(
                             item["query"], artifact_ids=[], constraints={}, limit=3)["candidates"]]}
                        for item in blind.get("out_of_scope_intents", [])]
    finally:
        runtime.close()
    n = len(cases)
    pct = lambda key, rows=cases: round(100 * sum(c[key] for c in rows) / len(rows), 2) if rows else None
    return {"schema_version": 1, "generator": "measure-blind-search",
            "blind_set_sha256": _sha(BLIND), "generator_sha256": _sha(Path(__file__)),
            "search_py_sha256": _sha(REPO / "cgal_mcp" / "master" / "search.py"),
            "registry_py_sha256": _sha(REPO / "cgal_mcp" / "master" / "registry.py"),
            "operations_sha256": _sha(REPO / "cgal_mcp" / "master" / "operations.json"),
            "search_data_sha256": _sha(REPO / "cgal_mcp" / "master" / "search_data.json"),
            "count": n, "families": sorted({c["family"] for c in cases}),
            "operation_level": {"top1_pct": pct("op_top1"), "top3_pct": pct("op_top3")},
            "requirement_level": {"top1_pct": pct("req_top1"), "top3_pct": pct("req_top3")},
            "by_language": {lang: {"count": len(rows), "op_top1_pct": pct("op_top1", rows),
                                   "op_top3_pct": pct("op_top3", rows),
                                   "req_top3_pct": pct("req_top3", rows)}
                            for lang in ("en", "ja") for rows in [[c for c in cases if c["language"] == lang]]},
            **({"out_of_scope_probes": out_of_scope} if out_of_scope else {}),
            "cases": cases}


if __name__ == "__main__":
    result = measure()
    if "--publish" in sys.argv:
        # Keep the human-authored run history and add this run (never re-measured).
        previous = json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.is_file() else {}
        note = (sys.argv[sys.argv.index("--note") + 1] if "--note" in sys.argv else "")
        history = list(previous.get("measurement_history", []))
        history.append(f"{note} Result: op top-1 {result['operation_level']['top1_pct']}%, "
                       f"top-3 {result['operation_level']['top3_pct']}%.")
        result["measurement_history"] = history
        result["interpretation"] = previous.get("interpretation", "")
        EVIDENCE.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, ensure_ascii=False, indent=1))
