"""Actual planner routing regressions with valid immutable geometry inputs."""
from pathlib import Path
import tempfile
import unittest

from cgal_mcp.master.errors import InvalidInput, UnsupportedOperation
from cgal_mcp.master.runtime import MasterRuntime


class GoalRoutingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="cgal-goal-route-")
        root = Path(self.folder.name)
        self.runtime = MasterRuntime(root / "store", require_memory_limit=False)
        points = root / "points.xyz"
        points.write_text("0 0 0\n1 0 0\n0 1 0\n0 0 1\n1 1 1\n", encoding="ascii")
        self.points = self.runtime.artifact_import(str(points), "mm")["artifact_id"]

    def tearDown(self):
        self.runtime.close()
        self.folder.cleanup()

    def test_bilingual_hull_goal_requires_validation_and_preserves_route_evidence(self):
        for goal in ("この点群を包む3D凸包を作る", "construct the 3D convex hull of these samples"):
            with self.subTest(goal=goal):
                plan = self.runtime.plan({"goal": goal, "inputs": [self.points]})
                self.assertEqual(plan["route"]["mode"], "registry_route")
                self.assertEqual(plan["route"]["selected"], "hull.convex_3")
                self.assertEqual(plan["route"]["query_analysis"]["routing_confidence"], "high")
                self.assertEqual([step["operation"] for step in plan["steps"]],
                                 ["hull.convex_3", "hull.validate.convex_enclosure"])

    def test_unknown_reconstruction_dimension_and_multioperation_fail_at_route(self):
        for goal in ("reconstruct using Poisson from these samples",
                     "make a 2D convex hull of this point cloud",
                     "remove outliers and then estimate normals",
                     "florble these samples into invisible metadata"):
            with self.subTest(goal=goal):
                with self.assertRaises(UnsupportedOperation) as caught:
                    self.runtime.plan({"goal": goal, "inputs": [self.points]})
                self.assertEqual(caught.exception.code, "unsupported_operation")

    def test_explicit_operation_remains_available_for_an_ambiguous_goal(self):
        # Routing confidence gates free text; they never hide a registered
        # explicit operation or permit skipping its mandatory validator.
        plan = self.runtime.plan({"operation_id": "hull.convex_3", "inputs": [self.points]})
        self.assertEqual(plan["route"]["mode"], "explicit")
        self.assertEqual(len(plan["steps"]), 2)
        with self.assertRaises(InvalidInput) as caught:
            self.runtime.plan({"operation_id": "hull.convex_3", "inputs": [self.points],
                               "policy": {"kernel": "inexact"}})
        self.assertEqual(caught.exception.code, "kernel_unsupported")

    def test_requested_pca_method_is_not_silently_replaced_with_jet(self):
        request = {"goal": "estimate PCA normals", "inputs": [self.points],
                   "parameters": {"method": "jet", "neighbors": 3, "degree_fitting": 1}}
        with self.assertRaises(InvalidInput) as caught:
            self.runtime.plan(request)
        self.assertEqual(caught.exception.code, "route_parameter_conflict")
        request["parameters"] = {"method": "pca", "neighbors": 3}
        plan = self.runtime.plan(request)
        self.assertEqual(plan["route"]["selected"], "pointset.normals.estimate")
        self.assertEqual(plan["steps"][0]["parameters"]["method"], "pca")
        request["parameters"] = {"neighbors": 3}
        with self.assertRaises(InvalidInput) as caught:
            self.runtime.plan(request)
        self.assertEqual(caught.exception.code, "route_parameter_missing")


if __name__ == "__main__":
    unittest.main()
