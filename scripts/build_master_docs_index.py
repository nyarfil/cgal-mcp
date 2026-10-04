"""Build a local, receipt-verified CGAL 6.2.1 documentation search index.

This utility indexes already-downloaded official documentation, public headers,
and examples.  It never invokes C++ or treats a search hit as executable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

from harvest_cgal import VERSION, build_catalog


HEADER_ORIGIN = re.compile(r"CGAL/cgal/blob/v6\.2\.1/([^/]+)/include/CGAL/")
HEADER_SUFFIXES = {".h", ".hpp", ".hxx", ".ipp"}
EXAMPLE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}
JAPANESE_ALIASES = {
    "triangulation": "三角形分割",
    "mesh": "メッシュ",
    "point": "点群",
    "polygon": "多角形",
    "surface": "曲面",
    "spatial": "空間検索",
    "convex": "凸包",
    "boolean": "ブーリアン",
    "intersection": "交差",
    "distance": "距離",
    "reconstruction": "再構成",
    "remesh": "リメッシュ",
    "simplification": "簡略化",
}


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_text(path: Path, html_source: bool = False) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if html_source:
        parser = _HTMLText()
        parser.feed(text)
        parser.close()
        text = " ".join(parser.parts)
    return " ".join(text.split())


def _aliases(package_id: str | None, title: str, extra: Iterable[str] = ()) -> str:
    English = " ".join(filter(None, [package_id or "", title, *extra])).replace("_", " ")
    lowered = English.casefold()
    japanese = [value for key, value in JAPANESE_ALIASES.items() if key in lowered]
    return " ".join([English, *japanese])


def _package_for_header(path: Path, package_ids: set[str]) -> str | None:
    match = HEADER_ORIGIN.search(_read_text(path))
    if match and match.group(1) in package_ids:
        return match.group(1)
    return path.stem if path.stem in package_ids else None


def _package_for_path(path: Path, root: Path, package_ids: set[str]) -> str | None:
    relative = path.relative_to(root)
    return relative.parts[0] if relative.parts and relative.parts[0] in package_ids else None


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _read_catalog(
    catalog_dir: Path, source_root: Path, docs_root: Path, provenance_inputs: dict[str, object] | None
) -> tuple[dict, dict[str, dict], dict[str, object]]:
    """Accept catalog files only when they equal a freshly verified harvest."""
    baseline = json.loads((catalog_dir / "baseline.json").read_text(encoding="utf-8"))
    manifest = json.loads((catalog_dir / "packages.json").read_text(encoding="utf-8"))
    docs_index = _read_jsonl(catalog_dir / "docs_index.jsonl")
    regenerated_baseline, regenerated_manifest, regenerated_docs_index = build_catalog(
        source_root, docs_root, provenance_inputs
    )
    if (baseline, manifest, docs_index) != (regenerated_baseline, regenerated_manifest, regenerated_docs_index):
        raise ValueError("catalog snapshot differs from the receipt-verified deterministic harvest")
    if baseline.get("cgal_version") != VERSION or baseline.get("package_count") != len(manifest.get("packages", [])):
        raise ValueError("catalog baseline/package manifest version or count mismatch")
    packages = {package["id"]: package for package in manifest["packages"]}
    if len(packages) != baseline["package_count"]:
        raise ValueError("catalog contains duplicate or incomplete package identifiers")
    provenance = {
        "mode": "official" if baseline["catalog_version"].endswith("master-baseline-1") else "test",
        "source": baseline["inputs"]["source"],
        "docs": baseline["inputs"]["docs"],
    }
    return baseline, packages, provenance


def _document_rows(source_root: Path, docs_root: Path, packages: dict[str, dict], package_manifest_sha256: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    package_ids = set(packages)
    for package_id, package in sorted(packages.items()):
        rows.append({
            "kind": "package", "package": package_id, "status": package["status"], "title": package["title"],
            "path": f"catalog/packages.json#{package_id}", "sha256": package_manifest_sha256,
            "content": package["reason"], "aliases": _aliases(package_id, package["title"]),
        })
    for path in sorted(docs_root.rglob("*.html")):
        package_id = _package_for_path(path, docs_root, package_ids)
        rows.append({
            "kind": "manual_page", "package": package_id, "status": packages.get(package_id, {}).get("status", "REFERENCE_ONLY"),
            "title": path.stem, "path": path.relative_to(docs_root).as_posix(), "sha256": _sha256(path),
            "content": _read_text(path, html_source=True), "aliases": _aliases(package_id, path.stem),
        })
    include_root = source_root / "include" / "CGAL"
    for path in sorted(item for item in include_root.rglob("*") if item.is_file() and item.suffix.lower() in HEADER_SUFFIXES):
        package_id = _package_for_header(path, package_ids)
        rows.append({
            "kind": "public_header", "package": package_id, "status": packages.get(package_id, {}).get("status", "REFERENCE_ONLY"),
            "title": path.stem, "path": path.relative_to(source_root).as_posix(), "sha256": _sha256(path),
            "content": _read_text(path), "aliases": _aliases(package_id, path.stem),
        })
    examples_root = source_root / "examples"
    for path in sorted(item for item in examples_root.rglob("*") if item.is_file() and item.suffix.lower() in EXAMPLE_SUFFIXES):
        package_id = _package_for_path(path, examples_root, package_ids)
        rows.append({
            "kind": "example", "package": package_id, "status": packages.get(package_id, {}).get("status", "REFERENCE_ONLY"),
            "title": path.stem, "path": path.relative_to(source_root).as_posix(), "sha256": _sha256(path),
            "content": _read_text(path), "aliases": _aliases(package_id, path.stem),
        })
    return rows


def _assert_output_scope(output: Path, repository: Path, allow_distribution_output: bool) -> None:
    if allow_distribution_output:
        return
    try:
        output.resolve().relative_to((repository / "work").resolve())
    except ValueError as error:
        raise ValueError("full-text SQLite output must remain below work/; pass --allow-distribution-output to override") from error


def build_index(
    source_root: Path,
    docs_root: Path,
    catalog_dir: Path,
    output: Path,
    *,
    allow_distribution_output: bool = False,
    provenance_inputs: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build FTS5 trigram search material from verified local CGAL inputs."""
    repository = Path(__file__).resolve().parents[1]
    _assert_output_scope(output, repository, allow_distribution_output)
    baseline, packages, provenance = _read_catalog(catalog_dir, source_root, docs_root, provenance_inputs)
    rows = _document_rows(source_root, docs_root, packages, _sha256(catalog_dir / "packages.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=output.parent, suffix=".sqlite")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript("""
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=OFF;
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE documents (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    package_id TEXT,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    aliases TEXT NOT NULL,
                    content TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE documents_fts USING fts5(
                    title, aliases, content, tokenize='trigram'
                );
            """)
            metadata = {
                "schema_version": 1,
                "cgal_version": VERSION,
                "catalog_version": baseline["catalog_version"],
                "package_count": len(packages),
                "provenance": provenance,
                "fts_tokenizer": "trigram",
            }
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                [(key, json.dumps(value, sort_keys=True)) for key, value in sorted(metadata.items())],
            )
            for row_id, row in enumerate(rows, start=1):
                connection.execute(
                    "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (row_id, row["kind"], row["package"], row["status"], row["title"], row["path"], row["sha256"], row["aliases"], row["content"]),
                )
                connection.execute(
                    "INSERT INTO documents_fts(rowid, title, aliases, content) VALUES (?, ?, ?, ?)",
                    (row_id, row["title"], row["aliases"], row["content"]),
                )
            connection.commit()
        finally:
            connection.close()
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["kind"])] = counts.get(str(row["kind"]), 0) + 1
    return {"output": str(output), "document_count": len(rows), "counts": counts, "package_count": len(packages)}


def query_index(database: Path, query: str, limit: int = 10) -> list[dict[str, object]]:
    """Search indexed references only; no query result executes any source code."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 through 100")
    if not database.is_file():
        raise ValueError(f"documentation index is not an existing regular file: {database}")
    if not query.strip():
        return []
    phrase = '"' + query.replace('"', '""') + '"'
    database_uri = database.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    try:
        try:
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        except sqlite3.DatabaseError as error:
            raise ValueError("documentation index schema is missing or invalid") from error
        if json.loads(metadata.get("schema_version", "null")) != 1 or json.loads(metadata.get("cgal_version", "null")) != VERSION:
            raise ValueError("documentation index schema or CGAL version is unsupported")
        if json.loads(metadata.get("fts_tokenizer", "null")) != "trigram":
            raise ValueError("documentation index does not declare the trigram tokenizer")
        matches = connection.execute(
            """SELECT d.kind, d.package_id, d.status, d.title, d.source_path, d.source_sha256,
                      snippet(documents_fts, 2, '[', ']', '…', 14)
               FROM documents_fts JOIN documents d ON d.id = documents_fts.rowid
               WHERE documents_fts MATCH ? ORDER BY bm25(documents_fts) LIMIT ?""",
            (phrase, limit),
        ).fetchall()
    finally:
        connection.close()
    fields = ("kind", "package", "status", "title", "source_path", "source_sha256", "snippet")
    return [{**dict(zip(fields, row)), "executable": False, "scope": "reference"} for row in matches]


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    build = subcommands.add_parser("build", help="build a local FTS5 trigram index")
    build.add_argument("--source", type=Path, default=repository / "work" / "master-baseline" / "source" / "CGAL-6.2.1")
    build.add_argument("--docs", type=Path, default=repository / "work" / "master-baseline" / "docs" / "doc_html")
    build.add_argument("--catalog", type=Path, default=repository / "catalog")
    build.add_argument("--output", type=Path, default=repository / "work" / "master-docs-index.sqlite")
    build.add_argument("--allow-distribution-output", action="store_true")
    query = subcommands.add_parser("query", help="search a built local index")
    query.add_argument("--database", type=Path, default=repository / "work" / "master-docs-index.sqlite")
    query.add_argument("--query", required=True)
    query.add_argument("--limit", type=int, default=10)
    arguments = parser.parse_args()
    if arguments.command == "build":
        print(json.dumps(build_index(arguments.source, arguments.docs, arguments.catalog, arguments.output,
                                     allow_distribution_output=arguments.allow_distribution_output), sort_keys=True))
    else:
        print(json.dumps(query_index(arguments.database, arguments.query, arguments.limit), sort_keys=True))


if __name__ == "__main__":
    main()
