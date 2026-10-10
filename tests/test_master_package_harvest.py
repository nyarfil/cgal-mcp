"""Package-wide harvest honesty: statuses, reasons, licenses and provenance are machine-checked."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts import master_acceptance as acceptance
from scripts import package_provenance as rules

REPO = acceptance.REPO
OVERVIEW = """
<h2><a class="anchor" id="PkgAlpha"></a>Alpha</h2>
<a href="../Alpha/index.html#Chapter_Alpha">User Manual</a>
<b>License:</b> <a class="el" href="license.html#licensesGPL">GPL</a> <br>
<h2><a class="anchor" id="PkgBeta"></a>Beta</h2>
<a href="../Beta/index.html#Chapter_Beta">User Manual</a>
<b>License:</b> <a class="el" href="license.html#licensesGPL">LGPL</a> <br>
<h2><a class="anchor" id="PkgGamma"></a>Gamma</h2>
<a href="../Gamma/index.html#Chapter_Gamma">User Manual</a>
"""
GPL = "GPL-3.0-or-later OR LicenseRef-Commercial"


def _header(root: Path, name: str, expression: str | None) -> Path:
    path = root / "include" / "CGAL" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(("// SPDX-License-Identifier: " + expression + "\n") if expression else "// none\n",
                    encoding="utf-8")
    return path


class LicenseResolutionTests(unittest.TestCase):
    def test_overview_tag_text_wins_over_anchor_and_is_parsed_per_directory(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "packages.html"
            path.write_text(OVERVIEW, encoding="utf-8")
            parsed = rules.parse_overview_licenses(path)
        self.assertEqual(parsed["Alpha"]["class"], "GPL")
        self.assertEqual(parsed["Beta"]["class"], "LGPL")
        self.assertTrue(parsed["Beta"]["anchor_mismatch"])
        self.assertNotIn("Gamma", parsed)

    def _resolve(self, entry, headers, root):
        legacy = {"status": "RESOLVED", "resolved_expression": "LGPL-3.0-or-later OR LicenseRef-Commercial",
                  "raw_spdx": [], "evidence": [], "reason": "legacy"}
        return rules.resolve_license("P", entry, {"path": "Manual/packages.html", "sha256": "0" * 64},
                                     headers, root, legacy)

    def test_resolution_classes(self) -> None:
        entry = {"label": "GPL", "class": "GPL", "anchor": "GPL", "anchor_mismatch": False}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            uniform = [_header(root, "a.h", GPL), _header(root, "b.h", GPL)]
            record = self._resolve(entry, uniform, root)
            self.assertEqual((record["status"], record["resolved_expression"]), ("RESOLVED", GPL))
            self.assertIn("superseded_license_check_header_expression", record)
            mixed = uniform + [_header(root, "c.h", "( " + GPL + " ) AND MIT")]
            record = self._resolve(entry, mixed, root)
            self.assertEqual(record["status"], "MIXED")
            self.assertEqual(record["file_exceptions"][0]["path"], "include/CGAL/c.h")
            odd = uniform + [_header(root, "d.h", "LicenseRef-RFL")]
            record = self._resolve(entry, odd, root)
            self.assertEqual(record["status"], "NEEDS_HUMAN_REVIEW")
            self.assertIsNone(record["resolved_expression"])
            disagree = self._resolve({**entry, "label": "LGPL", "class": "LGPL"}, uniform, root)
            self.assertEqual(disagree["status"], "NEEDS_HUMAN_REVIEW")
            self.assertEqual(disagree["provisional_expression"], GPL)
            self.assertEqual(self._resolve(None, [], root)["status"], "UNRESOLVABLE")


class CatalogCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.outcome = rules.check_catalog(
            REPO / "catalog",
            inventory=json.loads((REPO / "catalog/major_capability_inventory.json").read_text(encoding="utf-8")),
            evidence_dir=REPO / "docs/master/evidence")

    def test_every_package_is_classified_with_a_reason_and_final_license(self) -> None:
        self.assertEqual(self.outcome["blocking_reasons"], [])
        self.assertEqual(self.outcome["package_count"], 126)
        self.assertEqual(sum(self.outcome["status_distribution"].values()), 126)
        self.assertNotIn("UNRESOLVED", self.outcome["license_distribution"])
        self.assertEqual(self.outcome["inventory_items_bound"], 80)

    def test_tampering_is_detected(self) -> None:
        rows = json.loads((REPO / "catalog/packages.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "baseline.json").write_bytes((REPO / "catalog/baseline.json").read_bytes())
            damaged = copy.deepcopy(rows)
            damaged["packages"][0]["status"] = "DONE"
            damaged["packages"][1]["reason_code"] = ""
            damaged["packages"][2]["license"]["status"] = "UNRESOLVED"
            (root / "packages.json").write_text(json.dumps(damaged), encoding="utf-8")
            reasons = rules.check_catalog(root)["blocking_reasons"]
        text = "\n".join(reasons)
        self.assertIn("outside vocabulary", text)
        self.assertIn("requires reason_code", text)
        self.assertIn("not a final classification", text)

    def test_validated_status_requires_operations_in_the_registry(self) -> None:
        operations = rules.load_operations()
        reduced = [op for op in operations if op["package"] != "Convex_hull_3"]
        reasons = rules.check_catalog(REPO / "catalog", operations=reduced)["blocking_reasons"]
        self.assertTrue(any("Convex_hull_3: status VALIDATED inconsistent" in item for item in reasons))


class PackageGateTests(unittest.TestCase):
    def test_gate_reports_review_items_and_never_accepts_standalone(self) -> None:
        gate = acceptance.evaluate_package_harvest_gate(REPO)
        self.assertEqual(gate["gate"], "package_harvest_provenance")
        review = gate["measured"]["human_review"]
        if review["packages"] or review["operations"]:
            self.assertEqual(gate["status"], "unmet")
            self.assertTrue(any("human license review" in item for item in gate["reasons"]))
        else:
            self.assertEqual((gate["status"], gate["reasons"]), ("met", []))
        self.assertEqual(gate["measured"]["package_count"], 126)
        self.assertTrue(gate["measured"]["bundled_catalog_matches"])


if __name__ == "__main__":
    unittest.main()
