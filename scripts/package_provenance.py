"""Package-wide license resolution, status/coverage derivation and machine checks.

Provenance data only: licenses are transcribed from official CGAL 6.2.1 sources
(Package Overview license tag, per-header SPDX identifiers, license-check headers).
Nothing here is legal advice; ambiguous cases are flagged NEEDS_HUMAN_REVIEW.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OPERATIONS = REPO / "cgal_mcp" / "master" / "operations.json"
DEFAULT_POLICY = REPO / "catalog" / "package_status_policy.json"

PACKAGE_STATUSES = ("VALIDATED", "IMPLEMENTED", "ADAPTER_PLANNED", "CATALOGED", "BLOCKED", "EXCLUDED")
LICENSE_STATUSES = ("RESOLVED", "MIXED", "NEEDS_HUMAN_REVIEW", "UNRESOLVABLE", "UNRESOLVED")
VALIDATED_REASON = "has_validated_operations"
UNCLASSIFIED_REASON = "unclassified_in_policy"
MIXED_LICENSE_REF = "LicenseRef-CGAL-Mixed-File-Licenses"
NOTICE = ("Provenance data transcribed from official CGAL 6.2.1 sources; "
          "not legal advice. Confirm with the CGAL licensing terms before distribution.")
BENIGN_EXCEPTION_PREFIXES = ("BSL-1.0", "MIT", "CC0-1.0")

_SPDX = re.compile(r"SPDX-License-Identifier:\s*([^\r\n*]+)")
_SECTION = re.compile(r'<h2><a class="anchor" id="Pkg[^"]*"></a>(.*?)(?=<h2><a class="anchor" id="Pkg|\Z)', re.S)
_SECTION_HREF = re.compile(r'href="\.\./([A-Za-z0-9_]+)/index\.html')
_LICENSE_LINE = re.compile(r"<b>License:</b>(.*?)<br>", re.S)
_LICENSE_LINK = re.compile(r'href="license\.html#licenses(L?GPL)"[^>]*>([^<]*)</a>')


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_overview_licenses(overview: Path) -> dict[str, dict[str, object]]:
    """Map package directory -> official Package Overview license tag."""
    text = overview.read_text(encoding="utf-8")
    result: dict[str, dict[str, object]] = {}
    for section in _SECTION.findall(text):
        href = _SECTION_HREF.search(section)
        line = _LICENSE_LINE.search(section)
        if not href or not line:
            continue
        link = _LICENSE_LINK.search(line.group(1))
        if not link:
            continue
        label = " ".join(link.group(2).split())
        license_class = "LGPL" if "LGPL" in label else "GPL"
        result[href.group(1)] = {"label": label, "class": license_class,
                                 "anchor": link.group(1),
                                 "anchor_mismatch": link.group(1) != license_class}
    return result


def header_expression(path: Path) -> str:
    text = path.read_bytes()[:8192].decode("utf-8", errors="ignore")
    found = sorted({match.strip() for match in _SPDX.findall(text)})
    return " ; ".join(found) if found else "(none)"


def designated_expression(license_class: str) -> str:
    return f"{license_class}-3.0-or-later OR LicenseRef-Commercial"


def _is_benign(expression: str, designated: str) -> bool:
    if expression.startswith("( " + designated + " ) AND ") and \
            expression.split(" AND ", 1)[1].strip() in BENIGN_EXCEPTION_PREFIXES:
        return True
    if expression in BENIGN_EXCEPTION_PREFIXES:
        return True
    # LGPL files inside a GPL package are less restrictive than the package designation.
    return designated.startswith("GPL") and expression == designated.replace("GPL", "LGPL", 1)


def resolve_license(package_id: str, overview_entry: dict[str, object] | None,
                    overview_evidence: dict[str, object] | None, headers: list[Path],
                    source_root: Path, legacy: dict[str, object]) -> dict[str, object]:
    """Combine the official overview tag with every header SPDX identifier."""
    result = dict(legacy)
    result["notice"] = NOTICE
    if overview_entry is None:
        if not headers:
            result.update({
                "status": "UNRESOLVABLE", "resolved_expression": None,
                "review_reasons": [],
                "reason": ("package has no header in the pinned release tree and no license tag in the "
                           "official Package Overview; no official source designates a license"),
            })
        return result
    license_class = str(overview_entry["class"])
    designated = designated_expression(license_class)
    histogram: Counter[str] = Counter()
    by_file: list[tuple[str, str]] = []
    for header in headers:
        expression = header_expression(header)
        histogram[expression] += 1
        by_file.append((header.relative_to(source_root).as_posix(), expression))
    exceptions = [{"path": path, "spdx": expression} for path, expression in by_file
                  if expression != designated]
    review: list[str] = []
    if not by_file:
        review.append("overview license tag cannot be corroborated: package has no headers")
    elif histogram.get(designated, 0) == 0:
        dominant = histogram.most_common(1)[0][0]
        review.append(f"overview tag {overview_entry['label']} disagrees with every header SPDX "
                      f"(dominant: {dominant})")
    grouped: dict[str, list[str]] = {}
    for item in exceptions:
        if not _is_benign(item["spdx"], designated) and histogram.get(designated, 0) > 0:
            grouped.setdefault(item["spdx"], []).append(item["path"])
    for expression, paths in sorted(grouped.items()):
        review.append(f"{len(paths)} file(s) carry non-standard license {expression} "
                      f"(first: {paths[0]})")
    evidence = list(result.get("evidence", []))
    if overview_evidence:
        evidence.append({**overview_evidence, "kind": "package_overview",
                         "label": overview_entry["label"], "anchor": overview_entry["anchor"]})
    legacy_expression = legacy.get("resolved_expression")
    designation = {"source": "official_package_overview", "label": overview_entry["label"],
                   "class": license_class, "anchor": overview_entry["anchor"],
                   "anchor_mismatch": overview_entry["anchor_mismatch"], "expression": designated}
    result.update({"designation": designation, "evidence": evidence,
                   "header_spdx_histogram": dict(sorted(histogram.items())),
                   "file_exceptions": exceptions,
                   "review_reasons": review})
    if legacy_expression and legacy_expression != designated:
        result["superseded_license_check_header_expression"] = {
            "expression": legacy_expression,
            "reason": ("include/CGAL/license/<package>.h carries the same SPDX identifier for every package "
                       "(including GPL-designated ones), so it cannot discriminate the package license")}
    if review:
        result.update({"status": "NEEDS_HUMAN_REVIEW", "resolved_expression": None,
                       "provisional_expression": designated if histogram.get(designated, 0) else
                       (histogram.most_common(1)[0][0] if histogram else None),
                       "reason": "; ".join(review)})
    elif exceptions:
        result.update({"status": "MIXED", "resolved_expression": designated,
                       "mixed_license_ref": MIXED_LICENSE_REF,
                       "reason": ("package designation per official Package Overview corroborated by header "
                                  f"SPDX; {len(exceptions)} file(s) carry a different, compatible or "
                                  "permissive identifier (see file_exceptions)")})
    else:
        result.update({"status": "RESOLVED", "resolved_expression": designated,
                       "reason": ("official Package Overview license tag corroborated by SPDX identifiers "
                                  f"of all {len(by_file)} package headers")})
    return result


def count_docs_example_pages(docs_root: Path, package_id: str) -> int:
    folder = docs_root / package_id
    return len(list(folder.glob("*-example.html"))) if folder.is_dir() else 0


def explain_corroboration(package_id: str, missing: list[str], docs_examples: int,
                          header_count: int) -> dict[str, str]:
    explanations: dict[str, str] = {}
    for code in missing:
        if code == "examples_not_found":
            explanations[code] = (
                f"official docs reference {docs_examples} example page(s) whose sources live under other "
                "examples/ directories" if docs_examples else
                "no examples/<package> directory and no example page in the pinned docs")
        elif code == "headers_not_found":
            explanations[code] = ("no header attributed to this package in the pinned release tree "
                                  "(include/CGAL release URLs)")
        elif code == "docs_entry_missing":
            explanations[code] = "no extracted HTML chapter in the pinned docs"
    return explanations


def load_policy(path: Path = DEFAULT_POLICY) -> dict:
    if not path.is_file():
        return {"reason_codes": {}, "packages": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def load_operations(path: Path = DEFAULT_OPERATIONS) -> list[dict]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["operations"] if isinstance(data, dict) else data


def operation_packages(operation: dict) -> tuple[str, list[str]]:
    constituents = [part.strip() for part in operation["license"]["package"].split("+")]
    return operation["package"], constituents


def derive_coverage(package: dict, operations: list[dict], policy: dict) -> dict[str, object]:
    package_id = package["id"]
    primary = [op for op in operations if operation_packages(op)[0] == package_id]
    dependency = [op for op in operations
                  if package_id in operation_packages(op)[1] and operation_packages(op)[0] != package_id]
    validated = sorted(op["id"] for op in primary if op["status"] == "VALIDATED")
    implemented = sorted(op["id"] for op in primary if op["status"] == "IMPLEMENTED")
    evidence_headers = sorted({item["path"] for op in primary for item in op["license"]["evidence"]
                               if item["path"] in set(package["headers"]["paths"])})
    coverage: dict[str, object] = {
        "operations": {"validated": len(validated), "implemented": len(implemented),
                       "total": len(primary), "validated_ids": validated,
                       "dependency_use": sorted(op["id"] for op in dependency)},
        "headers": {"total": package["headers"]["count"],
                    "referenced_by_operation_evidence": len(evidence_headers)},
        "scope": "partial" if validated else "none",
    }
    entry = policy.get("packages", {}).get(package_id)
    if validated:
        coverage.update({"status": "VALIDATED", "reason_code": VALIDATED_REASON,
                         "reason": (f"{len(validated)} VALIDATED operation(s) with this package as primary "
                                    f"package; header coverage is partial "
                                    f"({len(evidence_headers)}/{package['headers']['count']} headers cited "
                                    "by operation license evidence)")})
    elif entry:
        coverage.update({"status": entry["status"], "reason_code": entry["reason_code"],
                         "reason": entry["rationale"]})
    else:
        coverage.update({"status": "CATALOGED", "reason_code": UNCLASSIFIED_REASON,
                         "reason": "no validated operation and no policy classification recorded"})
    return coverage


def apply_status(package: dict, coverage: dict[str, object], legacy_reason: str) -> None:
    package["coverage"] = coverage
    package["status"] = coverage["status"]
    package["reason_code"] = coverage["reason_code"]
    package["reason"] = f"{coverage['reason']}; {legacy_reason}" if legacy_reason else coverage["reason"]


# ----------------------------------------------------------------- checking

def derive_operation_expression(operation: dict, packages: dict[str, dict]) -> tuple[str | None, list[str]]:
    """Operation license = most restrictive designated package expression among constituents."""
    expressions: list[str] = []
    review: list[str] = []
    for name in operation_packages(operation)[1]:
        package = packages.get(name)
        if package is None:
            return None, [f"unknown package {name}"]
        license_record = package["license"]
        expression = license_record.get("resolved_expression") or license_record.get("provisional_expression")
        if license_record["status"] == "NEEDS_HUMAN_REVIEW":
            review.append(name)
        if expression:
            expressions.append(expression)
    if not expressions:
        return None, review
    restrictive = [item for item in expressions if item.startswith("GPL")]
    return (restrictive or expressions)[0], review


def _hash_ok(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def check_catalog(catalog_dir: Path, *, operations: list[dict] | None = None,
                  policy: dict | None = None, inventory: dict | None = None,
                  evidence_dir: Path | None = None, source_root: Path | None = None,
                  repo: Path = REPO) -> dict[str, object]:
    """Machine-check package status, license and provenance; returns a gate result."""
    reasons: list[str] = []
    baseline = json.loads((catalog_dir / "baseline.json").read_text(encoding="utf-8"))
    rows = json.loads((catalog_dir / "packages.json").read_text(encoding="utf-8"))["packages"]
    operations = load_operations() if operations is None else operations
    policy = load_policy() if policy is None else policy
    packages = {row["id"]: row for row in rows}
    if len(packages) != len(rows) or len(rows) != baseline["package_count"]:
        reasons.append("package ids are duplicated or differ from baseline package_count")
    codes = policy.get("reason_codes", {})
    status_counts: Counter[str] = Counter()
    license_counts: Counter[str] = Counter()
    review_packages: list[dict[str, object]] = []
    unresolvable: list[dict[str, str]] = []
    for pid, package in sorted(packages.items()):
        status = package.get("status")
        coverage = package.get("coverage") or {}
        status_counts[str(status)] += 1
        if status not in PACKAGE_STATUSES:
            reasons.append(f"{pid}: status {status!r} outside vocabulary")
        if coverage.get("status") != status or coverage.get("reason_code") != package.get("reason_code"):
            reasons.append(f"{pid}: coverage block disagrees with package status/reason_code")
        code = package.get("reason_code")
        if not isinstance(code, str) or not code or not str(package.get("reason", "")).strip():
            reasons.append(f"{pid}: status requires reason_code and reason")
        elif code == UNCLASSIFIED_REASON:
            reasons.append(f"{pid}: unclassified (no policy entry and no validated operation)")
        elif status == "VALIDATED":
            if code != VALIDATED_REASON:
                reasons.append(f"{pid}: VALIDATED package carries reason_code {code}")
        elif codes.get(code, {}).get("status") != status:
            reasons.append(f"{pid}: reason_code {code} is not defined for status {status}")
        primary = [op for op in operations if operation_packages(op)[0] == pid]
        validated = sorted(op["id"] for op in primary if op["status"] == "VALIDATED")
        stored = coverage.get("operations", {})
        if (stored.get("validated") != len(validated) or stored.get("validated_ids") != validated
                or stored.get("total") != len(primary)):
            reasons.append(f"{pid}: operation counts differ from the operations catalog")
        if (status == "VALIDATED") != bool(validated):
            reasons.append(f"{pid}: status {status} inconsistent with {len(validated)} validated operation(s)")
        if coverage.get("headers", {}).get("total") != package["headers"]["count"]:
            reasons.append(f"{pid}: header count differs from the package record")
        # provenance hashes
        if package["docs"]["local_entry"] and not _hash_ok(package["docs"].get("sha256")):
            reasons.append(f"{pid}: docs sha256 missing")
        if package["headers"]["count"] and not _hash_ok(package["headers"].get("tree_sha256")):
            reasons.append(f"{pid}: header tree sha256 missing")
        if (package["headers"]["count"] or package["examples"]["count"]) and not _hash_ok(
                package["source"].get("tree_sha256")):
            reasons.append(f"{pid}: source tree sha256 missing")
        if package["source"].get("release_archive_sha256") != baseline["inputs"]["source"]["sha256"]:
            reasons.append(f"{pid}: release archive sha256 differs from baseline")
        for kind in package["corroboration"]["missing"]:
            if kind not in package["corroboration"].get("explanations", {}):
                reasons.append(f"{pid}: corroboration gap {kind} has no recorded explanation")
        # license
        record = package["license"]
        license_counts[str(record.get("status"))] += 1
        if record.get("status") not in LICENSE_STATUSES or record.get("status") == "UNRESOLVED":
            reasons.append(f"{pid}: license status {record.get('status')!r} is not a final classification")
        elif record["status"] in ("RESOLVED", "MIXED"):
            expected = record.get("designation", {}).get("expression")
            if not expected or record.get("resolved_expression") != expected:
                reasons.append(f"{pid}: resolved license expression lacks official designation")
            if not record.get("evidence") or not all(_hash_ok(item.get("sha256")) for item in record["evidence"]):
                reasons.append(f"{pid}: license evidence hashes missing")
            if record["status"] == "MIXED" and not record.get("file_exceptions"):
                reasons.append(f"{pid}: MIXED license lists no file exceptions")
        elif record["status"] == "NEEDS_HUMAN_REVIEW":
            if not record.get("review_reasons"):
                reasons.append(f"{pid}: NEEDS_HUMAN_REVIEW without reasons")
            review_packages.append({"package": pid, "reasons": record.get("review_reasons", [])})
        elif record["status"] == "UNRESOLVABLE":
            if not str(record.get("reason", "")).strip():
                reasons.append(f"{pid}: UNRESOLVABLE license without recorded reason")
            unresolvable.append({"package": pid, "reason": record.get("reason", "")})
        if source_root is not None and record.get("evidence"):
            for item in record["evidence"]:
                if item.get("kind") == "package_overview":
                    continue
                target = source_root / item["path"]
                if not target.is_file() or sha256_bytes(target.read_bytes()) != item["sha256"]:
                    reasons.append(f"{pid}: license evidence {item['path']} does not match the pinned tree")
    for pid in policy.get("packages", {}):
        if pid not in packages:
            reasons.append(f"policy names unknown package {pid}")
        elif packages[pid]["status"] == "VALIDATED":
            reasons.append(f"policy classifies {pid} although it has validated operations")
    # operations: license derivation and evidence
    review_operations: list[dict[str, object]] = []
    published = ""
    if evidence_dir is not None and evidence_dir.is_dir():
        published = "\n".join(path.read_text(encoding="utf-8") for path in sorted(evidence_dir.glob("*.json")))
    for operation in operations:
        expected, review = derive_operation_expression(operation, packages)
        if expected is None:
            reasons.append(f"{operation['id']}: license cannot be derived ({'; '.join(review)})")
        elif operation["license"]["expression"] != expected:
            reasons.append(f"{operation['id']}: license {operation['license']['expression']} differs from "
                           f"package-derived {expected}")
        if review:
            review_operations.append({"operation": operation["id"], "packages": review})
        if operation["status"] == "VALIDATED":
            tests = operation.get("evidence", {}).get("tests", [])
            if not tests or not all((repo / item.split(":", 1)[0]).is_file() for item in tests):
                reasons.append(f"{operation['id']}: VALIDATED without existing test evidence files")
            if evidence_dir is not None and f'"{operation["id"]}"' not in published:
                reasons.append(f"{operation['id']}: VALIDATED but absent from every published evidence report")
    inventory_bound = 0
    if inventory is not None:
        for item in inventory["items"]:
            ids = item["package_ids"]
            known = [pid for pid in ids if pid in packages]
            unbound = [pid for pid in ids if pid not in packages]
            if unbound and not item["availability"].get("exception_reason"):
                reasons.append(f"{item['id']}: package ids {unbound} neither cataloged nor excepted")
            elif known or item["availability"].get("exception_reason"):
                inventory_bound += 1
    return {
        "package_count": len(packages),
        "status_distribution": dict(sorted(status_counts.items())),
        "license_distribution": dict(sorted(license_counts.items())),
        "human_review": {"packages": review_packages, "operations": review_operations},
        "unresolvable_licenses": unresolvable,
        "inventory_items_bound": inventory_bound,
        "blocking_reasons": reasons,
    }


if __name__ == "__main__":
    import sys
    outcome = check_catalog(REPO / "catalog",
                            inventory=json.loads((REPO / "catalog/major_capability_inventory.json")
                                                 .read_text(encoding="utf-8")),
                            evidence_dir=REPO / "docs/master/evidence")
    sys.stdout.write(json.dumps(outcome, indent=2, ensure_ascii=False) + "\n")
