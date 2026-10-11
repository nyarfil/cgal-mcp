"""Tests for master_derive. Run with the CGAL venv:
E:/aiwork/cgal-mcp/.venv/Scripts/python.exe -m unittest integration/cgal/test_master_derive.py -v
Live tests start the real cgal-mcp (CGAL Master) server from .mcp.json and are skipped if its worker is missing.
"""
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import master_derive as md  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "stella_icosphere_r10mm_320f.stl"
ENTRY = json.loads(md.DEFAULT_CONFIG.read_text(encoding="utf-8-sig"))["mcpServers"]["cgal-mcp"]
WORKER = Path(ENTRY["env"]["CGAL_MASTER_WORKER"])


class Offline(unittest.TestCase):
    def test_config_keeps_persistence_off_and_data_in_workspace(self):
        self.assertEqual(ENTRY["env"]["CGAL_MASTER_PERSISTENT_WORKERS"], "0")
        self.assertEqual(ENTRY["env"]["CGAL_MASTER_RESULT_CACHE"], "0")
        self.assertIn("cadmcp-workspace/cgal-master", ENTRY["env"]["CGAL_MASTER_DATA"])
        self.assertEqual(ENTRY["args"], ["-m", "cgal_mcp.master.server", "stdio"])

    def test_path_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "a.off"
            source.write_text("OFF\n0 0 0\n")
            with self.assertRaises(md.DerivationRefused):
                md.check_paths(source, source)
            with self.assertRaises(md.DerivationRefused):
                md.check_paths(source, root / "b.stl")
            existing = root / "b.off"
            existing.write_text("x")
            with self.assertRaises(md.DerivationRefused):
                md.check_paths(source, existing)
            (root / "c.off.provenance.json").write_text("{}")
            with self.assertRaises(md.DerivationRefused):
                md.check_paths(source, root / "c.off")

    def test_accept_requires_every_validator_to_pass(self):
        good = {"state": "succeeded", "validation_status": "passed", "outputs": [{}],
                "validation": [{"operation": "v1", "metrics": {"status": "pass"}},
                               {"operation": "v2", "metrics": {"verdict": "pass"}}]}
        md.accept(good)
        for bad in ({**good, "state": "rejected"}, {**good, "validation_status": "failed"},
                    {**good, "validation": []}, {**good, "outputs": []},
                    {**good, "validation": [{"operation": "v", "metrics": {"verdict": "fail"}}]}):
            with self.assertRaises(md.DerivationRefused):
                md.accept(bad)

    def test_unit_is_mandatory_and_checked_before_any_server_call(self):
        with self.assertRaises(md.DerivationRefused):
            asyncio.run(md.derive_simplified(None, FIXTURE, Path("x.off"), "inch", face_ratio=0.5,
                                             error_bound=0.05, max_deviation=1.0))


@unittest.skipUnless(WORKER.is_file(), "cgal-mcp (Master) worker not built")
class Live(unittest.TestCase):
    def run_derive(self, root: Path, source: Path, output: Path, **overrides):
        arguments = dict(face_ratio=0.5, error_bound=0.05, max_deviation=1.0)
        arguments.update(overrides)
        return asyncio.run(md.derive_via_config(source, output, "mm", data_dir=root / "data", **arguments))

    def test_real_simplification_with_provenance_and_refusals(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / FIXTURE.name
            source.write_bytes(FIXTURE.read_bytes())
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            output = root / "derived.off"
            record = self.run_derive(root, source, output)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            self.assertEqual(record["validation_status"], "passed")
            self.assertLess(record["output"]["faces"], record["output"]["source_faces"])
            self.assertEqual(record["output"]["unit"], "mm")
            saved = json.loads(Path(record["provenance_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["source"]["sha256"], before)
            self.assertEqual(saved["output"]["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(saved["operations"][0], md.SIMPLIFY_OPERATION)
            self.assertIn("mesh.distance.symmetric_hausdorff", saved["operations"])
            self.assertTrue(all(v["verdict"] == "pass" for v in saved["validators"]))
            with self.assertRaises(md.DerivationRefused):  # no overwrite
                self.run_derive(root, source, output)
            # A deviation limit the real simplification cannot meet must publish nothing.
            rejected = root / "tight.off"
            with self.assertRaises(md.DerivationRefused):
                self.run_derive(root, source, rejected, max_deviation=0.01)
            self.assertFalse(rejected.exists())
            self.assertFalse(rejected.with_name("tight.off.provenance.json").exists())


if __name__ == "__main__":
    unittest.main()
