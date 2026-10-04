"""Focused checks for the release-pinned CGAL package baseline harvester."""
from __future__ import annotations

import hashlib
import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "scripts"))

from fetch_master_baseline import (  # noqa: E402
    ARTIFACTS,
    archive_receipt,
    safe_extract_tar_xz,
    verify_extracted_tree,
)
from harvest_cgal import VERSION, build_catalog, parse_package_overview, validate_snapshot  # noqa: E402


class MasterHarvesterTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        source = root / "source"
        docs = root / "docs"
        (source / "include" / "CGAL").mkdir(parents=True)
        (source / "examples" / "Fixture_package").mkdir(parents=True)
        (docs / "Manual").mkdir(parents=True)
        (docs / "Fixture_package").mkdir(parents=True)
        (source / "VERSION").write_text(f"{VERSION}\n", encoding="utf-8")
        (docs / "Manual" / "packages.html").write_text(
            "<h2><a class='anchor' id='PkgFixture'></a>Fixture Package</h2>"
            "<a class='elRef' href='../Fixture_package/index.html#Chapter_Fixture'>User Manual</a>",
            encoding="utf-8",
        )
        (docs / "Fixture_package" / "index.html").write_text("fixture docs", encoding="utf-8")
        (source / "include" / "CGAL" / "fixture.h").write_text(
            "// $URL: https://github.com/CGAL/cgal/blob/v6.2.1/Fixture_package/include/CGAL/fixture.h\n"
            "// SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Commercial\n"
            "namespace CGAL { class Fixture {}; }\n",
            encoding="utf-8",
        )
        (source / "include" / "CGAL" / "license").mkdir()
        (source / "include" / "CGAL" / "license" / "Fixture_package.h").write_text(
            "// SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Commercial\n", encoding="utf-8"
        )
        (source / "examples" / "Fixture_package" / "example.cpp").write_text(
            "#include <CGAL/fixture.h>\nint main() {}\n", encoding="utf-8"
        )
        return source, docs

    def _test_provenance(self, root: Path, source: Path, docs: Path) -> dict[str, object]:
        result: dict[str, object] = {"mode": "test"}
        for kind, directory in (("source", source), ("docs", docs)):
            archive = root / f"{kind}.tar.xz"
            with tarfile.open(archive, "w:xz") as tar:
                tar.add(directory, arcname=kind)
            result[kind] = {
                "archive_path": archive,
                "receipt": archive_receipt(archive, kind, {"filename": archive.name, "directory": kind}),
            }
        return result

    def test_parser_uses_package_heading_not_user_manual_link_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            overview = Path(temporary) / "packages.html"
            overview.write_text(
                "<h2>Named Package</h2><a href='../Named_package/index.html#Chapter'>User Manual</a>",
                encoding="utf-8",
            )
            self.assertEqual(
                parse_package_overview(overview),
                [{"id": "Named_package", "title": "Named Package", "href": "../Named_package/index.html#Chapter"}],
            )

    def test_source_reconciliation_uses_embedded_cgal_release_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, docs = self._fixture(root)
            baseline, manifest, index = build_catalog(source, docs, self._test_provenance(root, source, docs))
        package = manifest["packages"][0]
        self.assertEqual(baseline["package_count"], 1)
        self.assertEqual(baseline["catalog_version"], "cgal-6.2.1-test-baseline-1")
        self.assertEqual(package["title"], "Fixture Package")
        self.assertEqual(package["headers"]["count"], 1)
        self.assertEqual(package["examples"]["count"], 1)
        self.assertEqual(package["corroboration"]["missing"], [])
        self.assertEqual(package["license"]["status"], "RESOLVED")
        self.assertEqual(package["license"]["raw_spdx"], ["LGPL-3.0-or-later OR LicenseRef-Commercial"])
        self.assertEqual(index[0]["source_snippets"][0]["path"], "include/CGAL/fixture.h")
        self.assertIn("docs/master/CGAL_Master_MCP_Design_Spec.md", baseline["master_reference_documents"])

    def test_incomplete_snapshot_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "VERSION").write_text(f"{VERSION}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incomplete docs snapshot"):
                validate_snapshot(source, root / "docs")

    def test_original_master_documents_remain_byte_exact(self) -> None:
        expected = {
            "CGAL_Master_MCP_Design_Spec.md": "44cbb8b0e93abf0216c12f0fd6c9e35b6d04534dff83b9dafe07051625a727fd",
            "CGAL_Master_MCP_Implementation_Plan.md": "4631700c95f72101aef8e417171888f5e52ece7420d2d6f88735e91bfd130183",
        }
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((REPOSITORY / "docs" / "master" / name).read_bytes()).hexdigest(), digest)

    def test_archive_member_traversal_and_links_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "bad.tar.xz"
            with tarfile.open(archive, "w:xz") as tar:
                traversal = tarfile.TarInfo("../outside.txt")
                traversal.size = 1
                tar.addfile(traversal, io.BytesIO(b"x"))
            with self.assertRaisesRegex(ValueError, "unsafe tar member"):
                safe_extract_tar_xz(archive, root / "output")
            self.assertFalse((root / "outside.txt").exists())
            archive.unlink()
            with tarfile.open(archive, "w:xz") as tar:
                link = tarfile.TarInfo("escape")
                link.type = tarfile.SYMTYPE
                link.linkname = "../outside.txt"
                tar.addfile(link)
            with self.assertRaisesRegex(ValueError, "non-regular tar member"):
                safe_extract_tar_xz(archive, root / "output-link")

    def test_pinned_release_checksums_are_present(self) -> None:
        self.assertEqual(ARTIFACTS["source"]["sha256"], "b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf")
        self.assertEqual(ARTIFACTS["docs"]["sha256"], "805127da33223e32837adcdc00e75faac1f6e8c93bace90cea0ef69f09ca23bb")

    def test_receipt_binds_archive_members_to_extracted_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "fixture.tar.xz"
            with tarfile.open(archive, "w:xz") as tar:
                entry = tarfile.TarInfo("fixture/file.txt")
                entry.size = 2
                tar.addfile(entry, io.BytesIO(b"ok"))
            receipt = archive_receipt(archive, "fixture", {"filename": archive.name, "directory": "fixture"})
            safe_extract_tar_xz(archive, root / "output")
            verify_extracted_tree(root / "output", receipt)

    def test_tampered_extraction_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "fixture.tar.xz"
            with tarfile.open(archive, "w:xz") as tar:
                entry = tarfile.TarInfo("fixture/file.txt")
                entry.size = 2
                tar.addfile(entry, io.BytesIO(b"ok"))
            receipt = archive_receipt(archive, "fixture", {"filename": archive.name, "directory": "fixture"})
            output = root / "output"
            safe_extract_tar_xz(archive, output)
            (output / "fixture" / "file.txt").write_bytes(b"no")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                verify_extracted_tree(output, receipt)

    def test_production_snapshot_requires_verified_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, docs = self._fixture(root)
            with self.assertRaises(ValueError):
                build_catalog(source, docs)

    def test_unresolved_license_does_not_conflate_mixed_header_spdx(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, docs = self._fixture(root)
            (source / "include" / "CGAL" / "license" / "Fixture_package.h").unlink()
            (source / "include" / "CGAL" / "fixture_extra.h").write_text(
                "// $URL: https://github.com/CGAL/cgal/blob/v6.2.1/Fixture_package/include/CGAL/fixture_extra.h\n"
                "// SPDX-License-Identifier: GPL-3.0-or-later OR LicenseRef-Commercial\n", encoding="utf-8"
            )
            _, manifest, _ = build_catalog(source, docs, self._test_provenance(root, source, docs))
            license_metadata = manifest["packages"][0]["license"]
            self.assertEqual(license_metadata["status"], "UNRESOLVED")
            self.assertIsNone(license_metadata["resolved_expression"])
            self.assertEqual(len(license_metadata["raw_spdx"]), 2)

    def test_test_provenance_cannot_impersonate_official_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, docs = self._fixture(root)
            provenance = self._test_provenance(root, source, docs)
            source_receipt = provenance["source"]["receipt"]  # type: ignore[index]
            source_receipt["archive"]["sha256"] = ARTIFACTS["source"]["sha256"]  # type: ignore[index]
            with self.assertRaisesRegex(ValueError, "archive digest"):
                build_catalog(source, docs, provenance)


if __name__ == "__main__":
    unittest.main()
