"""Production search regression cases independent of the acceptance corpus."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cgal_mcp.master.registry import OperationRegistry
from cgal_mcp.master.runtime import MasterRuntime
from cgal_mcp.master.errors import InvalidInput, UnsupportedOperation


ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = ["IMPLEMENTED", "VALIDATED"]


class ProductionOperationSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = OperationRegistry()

    def tearDown(self) -> None:
        self.registry.close()

    def search(self, query: str, input_types: list[str], **kwargs):
        return self.registry.search(
            query, input_types=input_types, status=EXECUTABLE, limit=8, **kwargs)

    def assert_route(self, query: str, input_types: list[str], operation: str) -> None:
        result = self.search(query, input_types)
        self.assertTrue(result["query_analysis"]["automatic_route_supported"], result)
        self.assertEqual(result["query_analysis"]["routing_confidence"], "high", result)
        self.assertEqual(result["query_analysis"]["recommended_operation"], operation, result)
        self.assertEqual(result["candidates"][0]["operation_id"], operation, result)
        self.assertTrue(result["candidates"][0]["route_supported"], result)
        self.assertFalse(result["candidates"][0]["uncovered_primary_concepts"], result)

    def test_unseen_bilingual_paraphrases_distinguish_registered_methods(self):
        self.assert_route("スキャン点群から孤立した測定点を除きたい", ["PointSet3"],
                          "pointset.remove_outliers")
        self.assert_route("面どうしが自分自身を貫く組を調べる", ["TriangleSurfaceMesh"],
                          "mesh.analysis.self_intersections")
        self.assert_route("点群の法線を主成分分析で推定", ["PointSet3"],
                          "pointset.normals.estimate")
        self.assert_route("最小全域木で点群法線の符号を揃える", ["PointSet3Normals"],
                          "pointset.normals.orient_mst")
        self.assert_route("局所ジェット曲面で点の座標を滑らかにする", ["PointSet3"],
                          "pointset.smooth.jet")
        self.assert_route("三角形メッシュの辺を縮約して軽量メッシュを作る",
                          ["TriangleSurfaceMesh"], "mesh.simplify.edge_collapse")
        self.assert_route("点群の近傍から単位法線を推定する", ["PointSet3"],
                          "pointset.normals.estimate")
        self.assert_route("Find every pair of faces where the surface crosses itself",
                          ["TriangleSurfaceMesh"],
                          "mesh.analysis.self_intersections")
        self.assert_route("Keep only the overlapping volume of these two solids",
                          ["TriangleSurfaceMesh", "TriangleSurfaceMesh"],
                          "mesh.boolean.intersection")

    def test_typed_and_policy_gates_remain_hard(self):
        wrong_type = self.search("compute face normals", ["PointSet3"])
        self.assertFalse(wrong_type["query_analysis"]["automatic_route_supported"],
                         wrong_type)
        self.assertNotIn("mesh.analysis.normals",
                         {item["operation_id"] for item in wrong_type["candidates"]})
        wrong_entity = self.search("estimate point cloud normals",
                                   ["TriangleSurfaceMesh"])
        self.assertFalse(wrong_entity["query_analysis"]["automatic_route_supported"],
                         wrong_entity)
        self.assertNotIn("pointset.normals.estimate",
                         {item["operation_id"] for item in wrong_entity["candidates"]})
        kernel = self.registry.search(
            "estimate PCA normals", input_types=["PointSet3"], status=EXECUTABLE,
            kernel="exact_constructions")
        self.assertFalse(kernel["query_analysis"]["automatic_route_supported"])
        dependency = self.registry.search(
            "estimate PCA normals", input_types=["PointSet3"], status=EXECUTABLE,
            dependencies=["Surface_mesh"])
        self.assertEqual(dependency["candidates"], [])
        license_blocked = self.registry.search(
            "estimate PCA normals", input_types=["PointSet3"], status=EXECUTABLE,
            allowed_licenses=["MIT"])
        self.assertEqual(license_blocked["candidates"], [])

    def test_unsupported_specific_and_multioperation_goals_signal_fail_closed(self):
        cases = [
            ("Poisson reconstruction from oriented samples", ["PointSet3Normals"]),
            ("straight skeleton of this polygon", ["Polygon2"]),
            ("alpha wrap this triangle surface", ["TriangleSurfaceMesh"]),
            ("remove outliers and then estimate normals", ["PointSet3"]),
            ("create a 2D convex hull", ["PointSet3"]),
            ("two-dimensional convex hull", ["PointSet3"]),
            ("2-D convex hull", ["PointSet3"]),
            ("二次元の点から凸包を作る", ["PointSet3"]),
            ("2次元の凸包を作る", ["PointSet3"]),
            ("remove noise and estimate normals", ["PointSet3"]),
            ("denoise the point cloud and estimate normals", ["PointSet3"]),
            ("clean noisy points then estimate normals", ["PointSet3"]),
            ("cleanup the point cloud and estimate normals", ["PointSet3"]),
            ("clean up the point cloud and estimate normals", ["PointSet3"]),
            ("点群のノイズを除去して法線を推定", ["PointSet3"]),
            ("split non-manifold neighborhoods into repairable shells",
             ["TriangleSurfaceMesh"]),
            ("clip a surface against a box and label the cut boundary",
             ["TriangleSurfaceMesh"]),
            ("simplify with protected edge constraints", ["TriangleSurfaceMesh"]),
            ("simplify inside an external geometric envelope",
             ["TriangleSurfaceMesh"]),
            ("simplify using Fast Envelope", ["TriangleSurfaceMesh"]),
            ("reject collapses by bounded normal rotation",
             ["TriangleSurfaceMesh"]),
            ("segment the shape with a shape diameter field",
             ["TriangleSurfaceMesh"]),
            ("florble the totally unrelated nonsense", ["PointSet3"]),
        ]
        for query, input_types in cases:
            with self.subTest(query=query):
                result = self.search(query, input_types)
                self.assertFalse(result["query_analysis"]["automatic_route_supported"],
                                 result)
                self.assertIsNone(result["query_analysis"]["recommended_operation"])
                self.assertFalse(any(item["route_supported"]
                                     for item in result["candidates"]), result)

    def test_named_method_exposes_required_parameter_value(self):
        pca = self.search("estimate point normals with PCA", ["PointSet3"])
        self.assertEqual(pca["query_analysis"]["required_parameters"],
                         {"method": "pca"})
        self.assertEqual(pca["candidates"][0]["required_parameters"],
                         {"method": "pca"})

    def test_generic_point_reduction_discovers_variants_without_guessing_policy(self):
        result = self.search(
            "Downsample a dense scan while retaining representative spatial coverage",
            ["PointSet3"])
        returned = {item["operation_id"] for item in result["candidates"][:3]}
        self.assertTrue(
            {"pointset.simplify.grid", "pointset.simplify.hierarchy"} & returned,
            result)
        self.assertFalse(result["query_analysis"]["automatic_route_supported"],
                         result)
        self.assertEqual(result["query_analysis"]["routing_confidence"],
                         "ambiguous", result)

    def test_explicit_validation_language_does_not_route_to_transform(self):
        result = self.search("validate that this point cloud is healthy", ["PointSet3"])
        self.assertEqual(result["query_analysis"]["recommended_operation"],
                         "pointset.validate.basic", result)
        transform = self.search("estimate normals for this point cloud", ["PointSet3"])
        self.assertEqual(transform["query_analysis"]["recommended_operation"],
                         "pointset.normals.estimate", transform)

    def test_goal_planner_uses_high_confidence_evidence_and_rejects_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = MasterRuntime(Path(directory), require_memory_limit=False)
            try:
                points = runtime.artifact_import(
                    str(ROOT / "tests/fixtures/master/cube_with_interior.xyz"), "mm")
                mesh = runtime.artifact_import(
                    str(ROOT / "tests/fixtures/master/wave_a_boolean/cube_a.off"), "mm")
                supported = runtime.plan({
                    "goal": "estimate point normals by principal component analysis",
                    "inputs": [points["artifact_id"]],
                    "parameters": {"method": "pca", "neighbors": 4},
                })
                self.assertEqual(supported["route"]["selected"],
                                 "pointset.normals.estimate")
                self.assertEqual(supported["route"]["query_analysis"][
                    "routing_confidence"], "high")

                rejected = [
                    ("compute face normals", [points["artifact_id"]]),
                    ("estimate point cloud normals", [mesh["artifact_id"]]),
                    ("Poisson reconstruction from this scan", [points["artifact_id"]]),
                    ("remove outliers and estimate normals", [points["artifact_id"]]),
                    ("create a 2D convex hull", [points["artifact_id"]]),
                    ("two dimensional convex hull", [points["artifact_id"]]),
                    ("cleanup the point cloud and estimate normals",
                     [points["artifact_id"]]),
                    ("点群のノイズを除去して法線を推定", [points["artifact_id"]]),
                ]
                for goal, inputs in rejected:
                    with self.subTest(goal=goal), self.assertRaises(UnsupportedOperation):
                        runtime.plan({"goal": goal, "inputs": inputs, "parameters": {}})
            finally:
                runtime.close()


class ProductionDocsSearchTests(unittest.TestCase):
    def runtime(self, docs_index: Path | None) -> MasterRuntime:
        runtime = MasterRuntime.__new__(MasterRuntime)
        runtime.catalog_root = ROOT / "catalog"
        runtime.docs_index = docs_index
        runtime.registry = SimpleNamespace(cgal_versions={"6.2.1"})
        return runtime

    def assert_reference_only(self, result: dict) -> None:
        self.assertTrue(result["results"], result)
        self.assertTrue(all(item["scope"] == "reference"
                            and item["executable"] is False
                            for item in result["results"]), result)

    def test_canonical_jsonl_fallback_is_bilingual_and_package_relevant(self):
        runtime = self.runtime(None)
        cases = [
            ("点群をポアソン法で曲面に再構成",
             "Poisson_surface_reconstruction_3"),
            ("ストレートスケルトンで内側の輪郭を作る", "Straight_skeleton_2"),
            ("alpha wrapping surface", "Alpha_wrap_3"),
        ]
        for query, expected_package in cases:
            with self.subTest(query=query):
                result = runtime.docs_search(query, 10)
                self.assert_reference_only(result)
                self.assertIn(expected_package,
                              {item["package"] for item in result["results"]})
                self.assertEqual(result["index_scope"], "pinned_generated_catalog")

    def test_full_sqlite_uses_safe_or_query_and_diverse_references(self):
        database = ROOT / "work" / "master-docs-index.sqlite"
        if not database.is_file():
            self.skipTest("verified full documentation index is not available")
        runtime = self.runtime(database)
        cases = [
            ("minimum spanning tree normal orientation", "Point_set_processing_3"),
            ("principal component point normal estimation", "Point_set_processing_3"),
            ("jet fitting point smoothing", "Point_set_processing_3"),
            ("self crossing mesh faces", "Polygon_mesh_processing"),
            ("straight skeleton polygon offset", "Straight_skeleton_2"),
        ]
        for query, expected_package in cases:
            with self.subTest(query=query):
                result = runtime.docs_search(query, 12)
                self.assert_reference_only(result)
                self.assertEqual(result["index_backend"], "sqlite-fts5-trigram")
                self.assertIn(expected_package,
                              {item["package"] for item in result["results"]}, result)
                packages = [item["package"] for item in result["results"]]
                self.assertGreaterEqual(len(set(packages)), min(2, len(packages)))

        # User text is always bound as a quoted FTS expression, never parsed as
        # an operator supplied by the caller.
        injected = runtime.docs_search('"normals" OR NEAR(secret token)', 5)
        self.assertTrue(all(item["scope"] == "reference" for item in injected["results"]))

    def test_no_geometry_terms_returns_no_reference_guess(self):
        runtime = self.runtime(None)
        result = runtime.docs_search("which capability would be best please", 10)
        self.assertEqual(result["results"], [])

    def test_malformed_or_truncated_jsonl_fallback_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory)
            for name in ("baseline.json", "packages.json"):
                (catalog / name).write_bytes((ROOT / "catalog" / name).read_bytes())
            runtime = self.runtime(None)
            runtime.catalog_root = catalog

            (catalog / "docs_index.jsonl").write_text("{broken\n", encoding="utf-8")
            with self.assertRaisesRegex(InvalidInput, "fallback documentation catalog"):
                runtime.docs_search("convex hull", 5)

            first = (ROOT / "catalog/docs_index.jsonl").read_text(
                encoding="utf-8").splitlines()[0]
            (catalog / "docs_index.jsonl").write_text(first + "\n", encoding="utf-8")
            with self.assertRaisesRegex(InvalidInput, "truncated"):
                runtime.docs_search("convex hull", 5)


if __name__ == "__main__":
    unittest.main()
