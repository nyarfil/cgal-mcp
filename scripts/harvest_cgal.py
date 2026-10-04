"""Generate an auditable CGAL package baseline from pinned local release inputs."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

from fetch_master_baseline import ARTIFACTS, VERSION, sha256_file, verified_official_provenance, verify_receipt


DOCS_BASE_URL = f"https://doc.cgal.org/{VERSION}"
SOURCE_BASE_URL = f"https://github.com/CGAL/cgal/tree/v{VERSION}"
RELEASE_BASE_URL = f"https://github.com/CGAL/cgal/releases/download/v{VERSION}"
MASTER_REFERENCE_DOCUMENTS = {
    "docs/master/CGAL_Master_MCP_Design_Spec.md": "44cbb8b0e93abf0216c12f0fd6c9e35b6d04534dff83b9dafe07051625a727fd",
    "docs/master/CGAL_Master_MCP_Implementation_Plan.md": "4631700c95f72101aef8e417171888f5e52ece7420d2d6f88735e91bfd130183",
}
_PACKAGE_HREF = re.compile(r"(?:^|/)\.?\.?/([A-Za-z0-9_]+)/index\.html(?:#.*)?$")
_SPDX = re.compile(r"SPDX-License-Identifier:\s*([^\r\n*]+)")
_IDENTIFIER = re.compile(r"\b(?:CGAL::)?[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*")
_HEADER_ORIGIN = re.compile(r"CGAL/cgal/blob/v6\.2\.1/([^/]+)/include/CGAL/")


class PackageOverviewParser(HTMLParser):
    """Collect package links from a local ``Manual/packages.html`` file."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._text: list[str] = []
        self._in_heading = False
        self._heading_text: list[str] = []
        self._current_heading: str | None = None
        self.packages: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h2":
            self._in_heading = True
            self._heading_text = []
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._in_heading:
            self._heading_text.append(data)
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            title = " ".join("".join(self._heading_text).split())
            self._current_heading = html.unescape(title) or None
            self._in_heading = False
            self._heading_text = []
            return
        if tag != "a" or self._href is None:
            return
        href = unquote(self._href)
        match = _PACKAGE_HREF.search(urlparse(href).path)
        title = " ".join("".join(self._text).split())
        if match and title and match.group(1) != "Manual":
            item = {"id": match.group(1), "title": self._current_heading or html.unescape(title), "href": href}
            if item not in self.packages:
                self.packages.append(item)
        self._href = None
        self._text = []


def parse_package_overview(path: Path) -> list[dict[str, str]]:
    parser = PackageOverviewParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    if not parser.packages:
        raise ValueError(f"no package links found in official Package Overview: {path}")
    return parser.packages


def _tree_hash(root: Path, files: list[Path]) -> str | None:
    if not files:
        return None
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _find_package_root(source_root: Path, package_id: str) -> Path | None:
    direct = source_root / "include" / "CGAL" / package_id
    return direct if direct.is_dir() else None


def _collect_files(root: Path | None, suffixes: set[str]) -> list[Path]:
    if root is None or not root.is_dir():
        return []
    return sorted((path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in suffixes),
                  key=lambda item: item.relative_to(root).as_posix())


def _spdx_evidence(source_root: Path, package_id: str, headers: list[Path]) -> list[dict[str, object]]:
    """Retain path-level SPDX evidence without treating mixed headers as a license decision."""
    license_header = source_root / "include" / "CGAL" / "license" / f"{package_id}.h"
    candidates: list[tuple[Path, str]] = []
    if license_header.is_file():
        candidates.append((license_header, "package_license_header"))
    candidates.extend((header, "package_header") for header in headers[:32] if header != license_header)
    reuse = source_root / "REUSE.toml"
    if reuse.is_file():
        candidates.append((reuse, "root_reuse"))
    evidence: list[dict[str, object]] = []
    for path, kind in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        expressions = sorted({match.strip() for match in _SPDX.findall(text)})
        if expressions or kind == "root_reuse":
            evidence.append({
                "path": path.relative_to(source_root).as_posix(),
                "sha256": sha256_file(path),
                "raw_spdx": expressions,
                "kind": kind,
            })
    return evidence


def _license_metadata(source_root: Path, package_id: str, headers: list[Path]) -> dict[str, object]:
    evidence = _spdx_evidence(source_root, package_id, headers)
    observed = sorted({expression for item in evidence for expression in item["raw_spdx"]})
    designated = [item for item in evidence if item["kind"] == "package_license_header"]
    designated_expressions = sorted({expression for item in designated for expression in item["raw_spdx"]})
    if len(designated_expressions) == 1:
        return {
            "status": "RESOLVED",
            "resolved_expression": designated_expressions[0],
            "raw_spdx": observed,
            "evidence": evidence,
            "reason": "designated CGAL package license header provides the package SPDX expression",
        }
    return {
        "status": "UNRESOLVED",
        "resolved_expression": None,
        "raw_spdx": observed,
        "evidence": evidence,
        "reason": "no single designated CGAL package license header expression; raw SPDX observations are not a license decision",
    }


def _headers_by_source_package(source_root: Path) -> dict[str, list[Path]]:
    """Use CGAL's embedded release URL to reconcile flattened headers to packages."""
    headers = _collect_files(source_root / "include" / "CGAL", {".h", ".hpp", ".hxx", ".ipp"})
    packages: dict[str, list[Path]] = {}
    for header in headers:
        text = header.read_text(encoding="utf-8", errors="ignore")
        match = _HEADER_ORIGIN.search(text)
        if match:
            packages.setdefault(match.group(1), []).append(header)
    return packages


def _examples_for(source_root: Path, package_id: str) -> list[Path]:
    return _collect_files(source_root / "examples" / package_id, {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"})


def _docs_entry(docs_root: Path, package_id: str) -> Path | None:
    candidate = docs_root / package_id / "index.html"
    return candidate if candidate.is_file() else None


def _source_identifiers(headers: list[Path], limit: int = 24) -> list[str]:
    identifiers: set[str] = set()
    for path in headers[:limit]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        identifiers.update(token for token in _IDENTIFIER.findall(text) if token.startswith("CGAL"))
    return sorted(identifiers)[:limit]


def _source_snippets(source_root: Path, headers: list[Path], limit: int = 3) -> list[dict[str, str]]:
    snippets: list[dict[str, str]] = []
    for path in headers[:limit]:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        meaningful = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("//")]
        snippets.append({
            "path": path.relative_to(source_root).as_posix(),
            "sha256": sha256_file(path),
            "snippet": " ".join(meaningful[:2])[:240],
        })
    return snippets


def _test_provenance(source_root: Path, docs_root: Path, provenance_inputs: dict[str, object]) -> dict[str, object]:
    """Validate an explicit test-only receipt pair without claiming official inputs."""
    if provenance_inputs.get("mode") != "test":
        raise ValueError("custom provenance inputs must declare mode='test'")
    result: dict[str, object] = {"mode": "test"}
    for kind, extracted_root in (("source", source_root), ("docs", docs_root)):
        supplied = provenance_inputs.get(kind)
        if not isinstance(supplied, dict):
            raise ValueError(f"test provenance is missing {kind}")
        archive_path = supplied.get("archive_path")
        receipt = supplied.get("receipt")
        if not isinstance(archive_path, (str, Path)) or not isinstance(receipt, dict):
            raise ValueError(f"test provenance for {kind} requires archive_path and receipt")
        archive = Path(archive_path)
        verify_receipt(archive, extracted_root.parent, receipt)
        archive_info = receipt.get("archive")
        if not isinstance(archive_info, dict) or archive_info.get("sha256") == ARTIFACTS[kind]["sha256"]:
            raise ValueError("test provenance may not impersonate an official archive")
        result[kind] = {
            "filename": archive_info["filename"], "sha256": archive_info["sha256"], "root": receipt["root"],
            "member_count": len(receipt["members"]), "tree_sha256": receipt["tree_sha256"],
        }
    return result


def validate_snapshot(source_root: Path, docs_root: Path, provenance_inputs: dict[str, object] | None = None) -> tuple[Path, dict[str, object]]:
    """Require a complete tree and cryptographically verified provenance before harvest."""
    version = source_root / "VERSION"
    if not version.is_file() or version.read_text(encoding="utf-8").strip() != VERSION:
        raise ValueError(f"incomplete or wrong source snapshot: expected CGAL {VERSION} at {source_root}")
    overview = docs_root / "Manual" / "packages.html"
    if not overview.is_file():
        raise ValueError(f"incomplete docs snapshot: missing {overview}")
    provenance = verified_official_provenance(source_root, docs_root) if provenance_inputs is None else _test_provenance(source_root, docs_root, provenance_inputs)
    return overview, provenance


def _validate_master_reference_documents() -> dict[str, str]:
    repository = Path(__file__).resolve().parents[1]
    for relative, expected in MASTER_REFERENCE_DOCUMENTS.items():
        actual = sha256_file(repository / relative)
        if actual != expected:
            raise ValueError(f"preserved Master reference digest mismatch for {relative}: {actual}")
    return dict(MASTER_REFERENCE_DOCUMENTS)


def build_catalog(source_root: Path, docs_root: Path, provenance_inputs: dict[str, object] | None = None) -> tuple[dict, dict, list[dict]]:
    overview, provenance = validate_snapshot(source_root, docs_root, provenance_inputs)
    overview_packages = parse_package_overview(overview)
    source_header_index = _headers_by_source_package(source_root)
    source_archive = provenance["source"]
    docs_archive = provenance["docs"]
    packages: list[dict] = []
    docs_index: list[dict] = []
    for listed in overview_packages:
        package_id = listed["id"]
        package_root = _find_package_root(source_root, package_id)
        headers = source_header_index.get(package_id, [])
        examples = _examples_for(source_root, package_id)
        docs_entry = _docs_entry(docs_root, package_id)
        license_metadata = _license_metadata(source_root, package_id, headers)
        missing: list[str] = []
        if docs_entry is None:
            missing.append("docs_entry_missing")
        if not headers:
            missing.append("headers_not_found")
        if not examples:
            missing.append("examples_not_found")
        status = "CATALOGED"
        reason = "official Package Overview entry; execution/validation status is outside this baseline"
        if missing:
            reason += "; incomplete corroboration: " + ", ".join(missing)
        package = {
            "id": package_id,
            "title": listed["title"],
            "status": status,
            "reason": reason,
            "docs": {
                "overview_href": listed["href"],
                "local_entry": docs_entry.relative_to(docs_root).as_posix() if docs_entry else None,
                "url": f"{DOCS_BASE_URL}/{package_id}/index.html",
                "sha256": sha256_file(docs_entry) if docs_entry else None,
            },
            "source": {
                "package_directory": package_id if headers else None,
                "local_header_root": "include/CGAL",
                "url": f"{SOURCE_BASE_URL}/{package_id}",
                "tree_sha256": _tree_hash(source_root, headers + examples),
                "release_archive_sha256": source_archive["sha256"],
            },
            "headers": {
                "count": len(headers),
                "paths": [path.relative_to(source_root).as_posix() for path in headers],
                "tree_sha256": _tree_hash(source_root, headers),
            },
            "examples": {
                "count": len(examples),
                "paths": [path.relative_to(source_root).as_posix() for path in examples],
                "tree_sha256": _tree_hash(source_root, examples),
            },
            "license": license_metadata,
            "corroboration": {"missing": missing},
        }
        packages.append(package)
        docs_index.append({
            "kind": "package",
            "package": package_id,
            "title": listed["title"],
            "status": status,
            "reason": reason,
            "docs_url": package["docs"]["url"],
            "header_count": len(headers),
            "example_count": len(examples),
            "identifiers": _source_identifiers(headers),
            "source_snippets": _source_snippets(source_root, headers),
        })
    baseline = {
        "schema_version": 1,
        "catalog_version": f"cgal-{VERSION}-master-baseline-1" if provenance["mode"] == "official" else f"cgal-{VERSION}-test-baseline-1",
        "cgal_version": VERSION,
        "sdk": {"package": "mcp", "version": "2.3.0"},
        "inputs": {
            "source": {**source_archive, **({"url": f"{RELEASE_BASE_URL}/{source_archive['filename']}"} if provenance["mode"] == "official" else {})},
            "docs": {**docs_archive, **({"url": f"{RELEASE_BASE_URL}/{docs_archive['filename']}"} if provenance["mode"] == "official" else {})},
            "package_overview": {
                "local_path": overview.relative_to(docs_root).as_posix(),
                "sha256": sha256_file(overview),
                "url": f"{DOCS_BASE_URL}/Manual/packages.html",
            },
        },
        "master_reference_documents": _validate_master_reference_documents(),
        "package_count": len(packages),
        "population": "all entries parsed from the pinned official local Package Overview",
        "coverage": {"cataloged": len(packages), "unclassified": 0},
    }
    package_manifest = {"schema_version": 1, "baseline": baseline["catalog_version"], "packages": packages}
    return baseline, package_manifest, docs_index


def write_catalog(source_root: Path, docs_root: Path, output: Path, provenance_inputs: dict[str, object] | None = None) -> dict:
    baseline, packages, docs_index = build_catalog(source_root, docs_root, provenance_inputs)
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("baseline.json", baseline), ("packages.json", packages)):
        with (output / name).open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
    with (output / "docs_index.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for entry in docs_index:
            stream.write(json.dumps(entry, sort_keys=True) + "\n")
    return baseline


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", "--source-root", dest="source_root", type=Path, default=repository / "work" / "master-baseline" / "source" / "CGAL-6.2.1")
    parser.add_argument("--docs", "--docs-root", dest="docs_root", type=Path, default=repository / "work" / "master-baseline" / "docs" / "doc_html")
    parser.add_argument("--output", type=Path, default=repository / "catalog")
    arguments = parser.parse_args()
    baseline = write_catalog(arguments.source_root, arguments.docs_root, arguments.output)
    print(f"package_count={baseline['package_count']}")


if __name__ == "__main__":
    main()
