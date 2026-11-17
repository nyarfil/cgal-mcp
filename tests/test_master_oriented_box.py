"""shape.bounding.oriented_box (CGAL Optimal_bounding_box) and its independent validator.

The validator decides that the report is a rectangular box, contains every point and touches the
point set on all six faces. It does not decide that no other orientation gives a smaller box.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from cgal_mcp.master.registry import OperationRegistry
from tests.test_master_boolean_rounded import REPO, WORKER, WorkerCase, artifact

FIXTURE = REPO / "tests/fixtures/master/batch2/rotated_box_points.xyz"
SEED = {"random_seed": 1}


def typed(path: Path, type_: str, format_: str, unit: str = "mm") -> dict:
    return dict(artifact(path, path.stem), type=type_, format=format_, unit=unit)


@unittest.skipUnless(WORKER.is_file(), "native master worker is not built")
class OrientedBoxTests(WorkerCase):
    def setUp(self):
        self.points = typed(FIXTURE, "PointSet3", "xyz")

    def produce(self, points=None, parameters=None):
        produced = self.ok("shape.bounding.oriented_box", [points or self.points], parameters or SEED)
        output = produced["outputs"][0]
        return produced, typed(Path(output["path"]), output["type"], output["format"], "none")

    def altered(self, report: dict, name: str, change) -> dict:
        data = json.loads(Path(report["path"]).read_text("utf-8"))
        change(data["results"])
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
        return typed(path, "GeometryQueryReport", "json", "none")

    def code(self, report: dict, parameters=None) -> str:
        response = self.call("shape.validate.oriented_box", [report, self.points], parameters or SEED)
        self.assertEqual(response["status"], "error", response)
        self.assertEqual(response["error"]["class"], "VALIDATION_FAILED", response["error"])
        return response["error"]["code"]

    def test_rotated_box_is_recovered_and_validated(self):
        produced, report = self.produce()
        # The fixture is a 6 x 3 x 1 box rotated about two axes; its axis-aligned box is far larger.
        self.assertEqual([round(v, 6) for v in sorted(produced["metrics"]["extents"])], [1.0, 3.0, 6.0])
        self.assertAlmostEqual(produced["metrics"]["volume"], 18.0, places=6)
        validated = self.ok("shape.validate.oriented_box", [report, self.points], SEED)
        body = json.loads(Path(validated["outputs"][0]["path"]).read_text("utf-8"))
        self.assertEqual(body["status"], "pass")
        for check in ("edges_orthogonal", "corners_form_a_box", "all_points_inside", "every_face_touches_a_point",
                      "extents_and_volume_match_corners", "parameters_match", "source_matches"):
            self.assertIs(body["checks"][check], True, check)
        self.assertGreater(body["axis_aligned_box_volume"], 2 * body["volume"])
        self.assertIn("not_decided", body)

    def test_same_seed_repeats_and_another_seed_still_validates(self):
        first, _ = self.produce()
        second, _ = self.produce()
        self.assertEqual(first["metrics"], second["metrics"])
        other = {"random_seed": 77}
        _, report = self.produce(parameters=other)
        self.ok("shape.validate.oriented_box", [report, self.points], other)
        # A report is bound to the seed it was made with.
        self.assertEqual(self.code(report, SEED), "PARAMETER_MISMATCH")

    def test_altered_reports_are_rejected(self):
        _, report = self.produce()

        def scale(factor):
            def change(results):
                corners = results["corners"]
                centre = [sum(c[k] for c in corners) / 8 for k in range(3)]
                results["corners"] = [[centre[k] + (c[k] - centre[k]) * factor for k in range(3)] for c in corners]
                results["extents"] = [e * factor for e in results["extents"]]
                results["volume"] *= factor ** 3
            return change

        def skew(results):
            results["corners"][7][0] += 0.01

        def shear(results):
            # Slide the top face: still eight consistent corners of a parallelepiped, no longer a box.
            for index in (4, 5, 6, 7):
                results["corners"][index][0] += 0.2

        self.assertEqual(self.code(self.altered(report, "larger.json", scale(1.01))), "BOX_NOT_TIGHT")
        self.assertEqual(self.code(self.altered(report, "smaller.json", scale(0.99))), "POINT_OUTSIDE_BOX")
        self.assertEqual(self.code(self.altered(report, "skew.json", skew)), "BOX_CORNERS_INCONSISTENT")
        self.assertEqual(self.code(self.altered(report, "shear.json", shear)), "BOX_NOT_RECTANGULAR")
        self.assertEqual(self.code(self.altered(report, "volume.json",
                                                lambda results: results.__setitem__("volume", results["volume"] * 1.001))),
                         "VOLUME_MISMATCH")

    def test_degenerate_inputs_are_refused(self):
        flat = self.root / "flat.xyz"
        flat.write_text("0 0 0\n1 0 0\n0 1 0\n1 1 0\n0.5 0.5 0\n", encoding="ascii", newline="\n")
        few = self.root / "few.xyz"
        few.write_text("0 0 0\n1 0 0\n0 1 0\n", encoding="ascii", newline="\n")
        self.refused("shape.bounding.oriented_box", [typed(flat, "PointSet3", "xyz")], SEED, "DEGENERATE_POINT_SET")
        self.refused("shape.bounding.oriented_box", [typed(few, "PointSet3", "xyz")], SEED, "POINT_SET_TOO_SMALL")
        self.refused("shape.bounding.oriented_box", [self.points], {}, "MISSING_PARAMETER")


class OrientedBoxRegistryTests(unittest.TestCase):
    def test_registered_as_implemented_with_a_mandatory_validator(self):
        registry = OperationRegistry()
        operation = registry.get("shape.bounding.oriented_box", executable=True)
        self.assertEqual((operation["status"], operation["package"]), ("IMPLEMENTED", "Optimal_bounding_box"))
        self.assertEqual(operation["validation"]["validators"], ["shape.validate.oriented_box"])
        self.assertIs(operation["validation"]["required"], True)
        self.assertIn("not a certified minimum", operation["summary"])
        validator = registry.get("shape.validate.oriented_box", executable=True)
        self.assertEqual(validator["validation"]["validates"], "shape.bounding.oriented_box")

    def test_search_finds_it_and_the_package_is_no_longer_refused(self):
        registry = OperationRegistry()
        for query in ("oriented bounding box of a point cloud", "点群の有向境界ボックス"):
            found = registry.search(query, limit=5)
            self.assertEqual(found["candidates"][0]["operation_id"], "shape.bounding.oriented_box", query)
        packages = json.loads((REPO / "catalog/packages.json").read_text("utf-8"))["packages"]
        package = next(p for p in packages if p["id"] == "Optimal_bounding_box")
        self.assertEqual((package["status"], package["reason_code"]),
                         ("IMPLEMENTED", "has_implemented_unvalidated_operations"))
        self.assertEqual(package["coverage"]["operations"]["validated"], 0)
        self.assertEqual(package["coverage"]["operations"]["implemented"], 2)


if __name__ == "__main__":
    unittest.main()
