"""Tests for the local-only, receipt-verified CGAL documentation index."""
from __future__ import annotations

import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "scripts"))

from build_master_docs_index import build_index, query_index  # noqa: E402
from fetch_master_baseline import archive_receipt  # noqa: E402
from harvest_cgal import build_catalog  # noqa: E402


class MasterDocsIndexTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path, dict[str, object]]:
        source, docs, catalog = root / "source", root / "docs", root / "catalog"
        (source / "include" / "CGAL").mkdir(parents=True)
        (source / "examples" / "Triangulation_2").mkdir(parents=True)
        (docs / "Manual").mkdir(parents=True)
        (docs / "Triangulation_2").mkdir(parents=True)
        (docs / "Miscellany").mkdir(parents=True)
        catalog.mkdir()
        (source / "VERSION").write_text("6.2.1\n", encoding="utf-8")
        (source / "include" / "CGAL" / "fixture.h").write_text(
            "// $URL: https://github.com/CGAL/cgal/blob/v6.2.1/Triangulation_2/include/CGAL/fixture.h\n"
            "namespace CGAL { class Fixture_header {}; }\n", encoding="utf-8"
        )
        (source / "examples" / "Triangulation_2" / "example.cpp").write_text(
            "#include <CGAL/fixture.h>\n// triangulation example\n", encoding="utf-8"
        )
        (docs / "Manual" / "packages.html").write_text(
            "<h2>2D Triangulations</h2><a href='../Triangulation_2/index.html'>User Manual</a>"
            "<h2>Miscellaneous</h2><a href='../Miscellany/index.html'>User Manual</a>", encoding="utf-8"
        )
        (docs / "Triangulation_2" / "index.html").write_text(
            "<h1>2D Triangulations</h1><p>Reference and API documentation.</p>", encoding="utf-8"
        )
        (docs / "Miscellany" / "index.html").write_text("<h1>Miscellaneous</h1>", encoding="utf-8")
        provenance: dict[str, object] = {"mode": "test"}
        for kind, directory in (("source", source), ("docs", docs)):
            archive = root / f"{kind}.tar.xz"
            with tarfile.open(archive, "w:xz") as tar:
                tar.add(directory, arcname=kind)
            provenance[kind] = {
                "archive_path": archive,
                "receipt": archive_receipt(archive, kind, {"filename": archive.name, "directory": kind}),
            }
        baseline, manifest, docs_index = build_catalog(source, docs, provenance)
        (catalog / "baseline.json").write_text(json.dumps(baseline, sort_keys=True), encoding="utf-8")
        (catalog / "packages.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        with (catalog / "docs_index.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for entry in docs_index:
                stream.write(json.dumps(entry, sort_keys=True) + "\n")
        return source, docs, catalog, provenance

    def test_builds_trigram_index_and_finds_japanese_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, docs, catalog, provenance = self._fixture(root)
            output = root / "index.sqlite"
            summary = build_index(source, docs, catalog, output, allow_distribution_output=True, provenance_inputs=provenance)
            results = query_index(output, "三角形分割")
        self.assertEqual(summary["package_count"], 2)
        self.assertGreaterEqual(summary["counts"]["manual_page"], 2)
        self.assertTrue(any(result["package"] == "Triangulation_2" for result in results))
        self.assertTrue(all(result["executable"] is False and result["scope"] == "reference" for result in results))

    def test_unsupported_package_remains_reference_searchable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, docs, catalog, provenance = self._fixture(root)
            output = root / "index.sqlite"
            build_index(source, docs, catalog, output, allow_distribution_output=True, provenance_inputs=provenance)
            results = query_index(output, "Miscellaneous")
        package_results = [result for result in results if result["kind"] == "package"]
        self.assertEqual(package_results[0]["status"], "CATALOGED")

    def test_distribution_output_requires_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, docs, catalog, provenance = self._fixture(root)
            with self.assertRaisesRegex(ValueError, "work/"):
                build_index(source, docs, catalog, root / "index.sqlite", provenance_inputs=provenance)

    def test_query_refuses_missing_database_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.sqlite"
            with self.assertRaisesRegex(ValueError, "existing regular file"):
                query_index(missing, "triangulation")
            self.assertFalse(missing.exists())

    def test_query_limit_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, docs, catalog, provenance = self._fixture(root)
            output = root / "index.sqlite"
            build_index(source, docs, catalog, output, allow_distribution_output=True, provenance_inputs=provenance)
            for value in (-1, 0, 101, True, "1"):
                with self.assertRaisesRegex(ValueError, "1 through 100"):
                    query_index(output, "triangulation", value)  # type: ignore[arg-type]

    def test_changed_catalog_snapshot_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, docs, catalog, provenance = self._fixture(root)
            manifest_path = catalog / "packages.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["packages"][0]["status"] = "VALIDATED"
            manifest["packages"][0]["reason"] = "fake executable"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "deterministic harvest"):
                build_index(source, docs, catalog, root / "index.sqlite", allow_distribution_output=True,
                            provenance_inputs=provenance)


if __name__ == "__main__":
    unittest.main()
