"""Evidence-gated Master acceptance; discovery never counts as implementation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ORIGINALS = {
    "CGAL_Master_MCP_Design_Spec.md": "44cbb8b0e93abf0216c12f0fd6c9e35b6d04534dff83b9dafe07051625a727fd",
    "CGAL_Master_MCP_Implementation_Plan.md": "4631700c95f72101aef8e417171888f5e52ece7420d2d6f88735e91bfd130183",
}


def verify_originals(root: Path = REPO) -> dict:
    checks = {}
    for name, expected in ORIGINALS.items():
        path = root / "docs" / "master" / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        checks[name] = {"sha256": actual, "matches_original": actual == expected}
    if not all(item["matches_original"] for item in checks.values()):
        raise ValueError("Original Master document bytes changed")
    return checks


def extract_requirements(root: Path = REPO) -> dict:
    verify_originals(root)
    path = root / "docs/master/CGAL_Master_MCP_Implementation_Plan.md"
    families = []
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^## (7\.(\d+)) (.+)$", line)
        if heading:
            number = int(heading[2])
            if not 1 <= number <= 15:
                raise ValueError("Unexpected major-family number")
            current = {"id": heading[1], "title": heading[3], "requirements": []}
            families.append(current)
        elif line.startswith("#") and not line.startswith("###"):
            current = None
        elif current is not None and line.startswith("- "):
            n = len(current["requirements"]) + 1
            current["requirements"].append({
                "id": f"major.{current['id']}.{n:02d}",
                "description": line[2:],
                "required": True,
                "operation_ids": [],
                "evidence": [],
            })
    if [f["id"] for f in families] != [f"7.{n}" for n in range(1, 16)]:
        raise ValueError("All fifteen original major families must be retained")
    if any(not f["requirements"] for f in families):
        raise ValueError("Empty family cannot establish complete coverage")
    return {
        "schema_version": 1,
        "source": "docs/master/CGAL_Master_MCP_Implementation_Plan.md",
        "source_sha256": ORIGINALS[path.name],
        "acceptance_policy": "all_listed_major_requirements_validated",
        "catalog_target_percent": 100,
        "major_requirements_target_percent": 100,
        "families": families,
    }


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


@dataclass(frozen=True)
class ReplayedEvidence:
    """In-memory result from the trusted acceptance runner, never loaded from JSON.

    A checked-in report is a reproducibility record. Only re-executing its approved
    harness against this build can establish acceptance. The runner passes the
    resulting canonical report hash separately; evidence files cannot supply it.
    """
    canonical_report_sha256: str


def _evidence_reasons(report: dict, item: dict, operations: dict[str, dict], root: Path,
                      replay: ReplayedEvidence | None = None) -> list[str]:
    """Tie evidence to a baseline, actual handler build, fixtures and executable tests."""
    reasons = []
    if replay is None or replay.canonical_report_sha256 != _canonical_hash(report):
        reasons.append("Evidence has not been reproduced by the acceptance runner for this build")
    if report.get("schema_version") != 1 or report.get("generator") != "master-capability-acceptance":
        reasons.append("Unknown acceptance evidence schema/generator")
    if report.get("status") != "pass" or item["id"] not in report.get("requirements", []):
        reasons.append("Evidence does not establish this requirement")
    baseline_path = root / "catalog/baseline.json"
    if not baseline_path.is_file() or report.get("catalog_baseline_sha256") != hashlib.sha256(baseline_path.read_bytes()).hexdigest():
        reasons.append("Evidence catalog baseline mismatch")
    manifest = report.get("worker_manifest")
    manifest_digest = None
    declared = {}
    if not isinstance(manifest, dict) or manifest.get("protocol") != 1:
        reasons.append("Evidence has no actual worker manifest")
    else:
        manifest_digest = _canonical_hash(manifest)
        build = manifest.get("build", {})
        if (manifest.get("actual_cgal_version") != "6.2.1" or
                build.get("source_kind") != "official_release" or
                build.get("source_sha256") != "b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf"):
            reasons.append("Evidence worker differs from the official CGAL baseline")
        declared = {o.get("id"): o for o in manifest.get("operations", []) if isinstance(o, dict)}
        if report.get("worker_manifest_sha256") != manifest_digest:
            reasons.append("Evidence worker manifest hash mismatch")
    tests = {}
    for case in report.get("tests", []):
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            reasons.append("Evidence has an invalid test record")
            continue
        path = (root / str(case.get("source_path", ""))).resolve()
        if (not path.is_relative_to((root / "tests").resolve()) or not path.is_file() or
                hashlib.sha256(path.read_bytes()).hexdigest() != case.get("source_sha256") or
                case.get("status") != "pass"):
            reasons.append("Evidence test source/result mismatch")
            continue
        tests[case["id"]] = case
    results = report.get("operation_results", [])
    for operation_id in item.get("operation_ids", []):
        operation = operations.get(operation_id, {})
        handler = declared.get(operation_id, {})
        if handler.get("revision") != operation.get("revision"):
            reasons.append(f"Evidence handler revision mismatch: {operation_id}")
        matches = [r for r in results if isinstance(r, dict) and r.get("operation_id") == operation_id]
        if not matches:
            reasons.append(f"Evidence has no execution result: {operation_id}")
        for result in matches:
            if (result.get("revision") != operation.get("revision") or
                    result.get("worker_manifest_sha256") != manifest_digest or
                    result.get("test_id") not in tests):
                reasons.append(f"Evidence execution/build/test mismatch: {operation_id}")
            for field in ("input_hashes", "output_hashes"):
                values = result.get(field)
                if not isinstance(values, list) or not values or not all(_valid_digest(v) for v in values):
                    reasons.append(f"Evidence fixture/artifact hash missing: {operation_id}")
            validation = result.get("validation")
            if (not isinstance(validation, dict) or validation.get("status") != "pass" or
                    not isinstance(validation.get("checks"), dict) or not validation["checks"] or
                    not all(c.get("pass") is True for c in validation["checks"].values() if isinstance(c, dict)) or
                    not all(isinstance(c, dict) for c in validation["checks"].values())):
                reasons.append(f"Evidence validation checks missing/failed: {operation_id}")
    return reasons


def evaluate_requirements(requirements: dict, operations: dict[str, dict], root: Path = REPO,
                          *, replayed_evidence: dict[str, ReplayedEvidence] | None = None) -> dict:
    """A requirement needs all declared adapters and nonempty valid evidence files."""
    fresh = extract_requirements(root)
    expected = {r["id"]: r["description"] for f in fresh["families"] for r in f["requirements"]}
    actual = [r for f in requirements.get("families", []) for r in f.get("requirements", [])]
    if len(actual) != len(expected) or {r.get("id"): r.get("description") for r in actual} != expected:
        raise ValueError("Acceptance denominator differs from the original major requirements")
    rows = []
    for item in actual:
        reasons = []
        if item.get("required") is not True:
            reasons.append("Required capability was disabled")
        ids = item.get("operation_ids", [])
        if not ids:
            reasons.append("No complete operation binding")
        for operation_id in ids:
            operation = operations.get(operation_id)
            if operation is None or operation.get("status") != "VALIDATED":
                reasons.append(f"Operation not validated: {operation_id}")
        evidence = item.get("evidence", [])
        if not evidence:
            reasons.append("No acceptance evidence")
        for record in evidence:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                reasons.append("Invalid evidence record")
                continue
            path = (root / record["path"]).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                reasons.append("Missing or unmanaged evidence")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if record.get("sha256") != digest:
                reasons.append("Evidence hash mismatch")
                continue
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                reasons.append("Evidence is not a machine-readable report")
                continue
            if not isinstance(report, dict):
                reasons.append("Evidence report must be an object")
                continue
            reasons.extend(_evidence_reasons(report, item, operations, root,
                           (replayed_evidence or {}).get(digest)))
        rows.append({"id": item["id"], "description": item["description"],
                     "status": "VALIDATED" if not reasons else "INCOMPLETE", "reasons": reasons})
    validated = sum(row["status"] == "VALIDATED" for row in rows)
    return {"required": len(rows), "validated": validated,
            "percent": 100 * validated / len(rows) if rows else 0,
            "complete": bool(rows) and validated == len(rows), "requirements": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-requirements", action="store_true")
    parser.add_argument("--originals-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    originals = verify_originals()
    target = REPO / "catalog/major_requirements.json"
    if args.refresh_requirements:
        if target.exists():
            raise SystemExit("Refusing to overwrite existing operation/evidence bindings")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(extract_requirements(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"original_documents": originals, "standalone_accepted": False}
    if not args.originals_only:
        requirements = json.loads(target.read_text(encoding="utf-8"))
        operation_path = REPO / "cgal_mcp/master/operations.json"
        operation_data = json.loads(operation_path.read_text(encoding="utf-8")) if operation_path.exists() else []
        if isinstance(operation_data, dict):
            operation_data = operation_data.get("operations", [])
        operations = {o.get("id", o.get("operation", {}).get("id")): o for o in operation_data}
        report["major_capabilities"] = evaluate_requirements(requirements, operations)
        report["standalone_acceptance_reason"] = "Additional package, routing, workflow, host and robustness gates required"
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content)


if __name__ == "__main__":
    main()
