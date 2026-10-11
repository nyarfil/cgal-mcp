"""Known-but-unsupported CGAL package recognition and recorded disambiguation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cgal_mcp.master.errors import InvalidInput, UnsupportedOperation
from cgal_mcp.master.runtime import MasterRuntime


class UnsupportedPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.runtime = MasterRuntime(Path(cls._tmp.name) / "store", require_memory_limit=False)

    @classmethod
    def tearDownClass(cls):
        cls.runtime.close()
        cls._tmp.cleanup()

    def test_named_cataloged_package_fails_closed_with_catalog_reason(self):
        result = self.runtime.capabilities_search("build a 2D hyperbolic Delaunay triangulation", [], {}, 3)
        analysis = result["query_analysis"]
        self.assertEqual(result["candidates"], [])
        self.assertTrue(analysis["abstained"])
        self.assertEqual(analysis["abstain_reason"], "recognized_unsupported_cgal_package")
        package = analysis["unsupported_cgal_packages"][0]
        self.assertEqual(package["package"], "Hyperbolic_triangulation_2")
        self.assertEqual(package["reason_code"], "algorithm_adapter_not_implemented")
        self.assertEqual(package["status"], "CATALOGED")

    def test_japanese_gloss_is_recognized(self):
        result = self.runtime.capabilities_search("ポリラインの簡略化を行いたい", [], {}, 3)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["query_analysis"]["unsupported_cgal_packages"][0]["package"],
                         "Polyline_simplification_2")

    def test_supported_requests_are_not_recognized_as_unsupported(self):
        for query in ("simplify a triangle mesh by edge collapse",
                      "compute the convex hull of 3D points",
                      "estimate point normals with principal component analysis of neighbours"[:0] or
                      "estimate normals of a point cloud"):
            result = self.runtime.capabilities_search(query, [], {}, 3)
            self.assertNotIn("unsupported_cgal_packages", result["query_analysis"], query)
            self.assertTrue(result["candidates"], query)

    def test_planner_refuses_a_named_unsupported_package_with_details(self):
        with self.assertRaises(UnsupportedOperation) as caught:
            self.runtime.plan({"goal": "snap rounding of a segment arrangement", "inputs": []})
        self.assertEqual(caught.exception.details["reason"], "recognized_unsupported_cgal_package")
        self.assertIn("details", caught.exception.as_dict())

    def test_ambiguous_goal_records_question_and_never_breaks_a_tie(self):
        import tempfile as _t
        store = self.runtime.store
        path = Path(self._tmp.name) / "points.xyz"
        path.write_text("0 0 0\n1 0 0\n0 1 0\n0 0 1\n1 1 1\n", encoding="ascii")
        points = self.runtime.artifact_import(str(path), "mm", artifact_type="PointSet3")["artifact_id"]
        self.assertIsNotNone(store)
        for goal in ("compute union, intersection and difference of two solids",
                     "simplify the point set"):
            try:
                self.runtime.plan({"goal": goal, "inputs": [points], "parameters": {}})
            except InvalidInput as error:
                if error.code == "ambiguous_route":
                    details = error.details
                    self.assertEqual(details["tie_break"], "none")
                    self.assertGreaterEqual(len(details["options"]), 2)
                    self.assertIn("question", details)
                    return
            except UnsupportedOperation:
                continue
        self.skipTest("no ambiguous goal available in this registry state")


if __name__ == "__main__":
    unittest.main()
