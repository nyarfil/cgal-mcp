"""Inputs above the former validator bounds (400 faces for distances, 64 / 32 points for the
minimum circle / sphere, 400 points for spacing, 2,000 faces for subdivision).

The validators still take the minimum over every triangle or point; a conservative box hierarchy
selects the candidates. These tests drive the native worker (skipped when it is not built) with
inputs the former all-pairs loops refused, and check that tampered reports are still rejected.
"""
from __future__ import annotations

import json
import math
import random
import unittest
from pathlib import Path

from cgal_mcp.master.registry import OperationRegistry
from tests.test_master_boolean_rounded import WORKER, WorkerCase, artifact, write_off
from tests.test_master_client_limits import uv_sphere


def mm(value: float) -> dict:
    return {"value": value, "unit": "mm"}


def typed(path: Path, type_: str, format_: str) -> dict:
    return dict(artifact(path, path.stem), type=type_, format=format_, unit="none" if type_.endswith("Report") else "mm")


@unittest.skipUnless(WORKER.is_file(), "native master worker is not built")
class RaisedLimitTests(WorkerCase):
    def sphere(self, name: str, lat: int, lon: int, radius: float, shift=(0.0, 0.0, 0.0)) -> dict:
        vertices, faces = uv_sphere(lat, lon)
        path = self.root / name
        write_off(path, [tuple(radius * c + s for c, s in zip(v, shift)) for v in vertices], faces)
        self.assertGreater(len(faces), 400)
        return artifact(path, name)

    def points3(self, name: str, points) -> dict:
        path = self.root / name
        path.write_text("".join(f"{x!r} {y!r} {z!r}\n" for x, y, z in points), encoding="ascii", newline="\n")
        return typed(path, "PointSet3", "xyz")

    def report_of(self, produced: dict) -> dict:
        output = produced["outputs"][0]
        return typed(Path(output["path"]), output["type"], output["format"])

    def tampered(self, report: dict, name: str, change) -> dict:
        data = json.loads(Path(report["path"]).read_text("utf-8"))
        change(data["results"])
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8", newline="\n")
        return typed(path, report["type"], "json")

    def rejected(self, validator, inputs, parameters) -> str:
        response = self.call(validator, inputs, parameters)
        self.assertEqual(response["status"], "error", response)
        self.assertEqual(response["error"]["class"], "VALIDATION_FAILED", response["error"])
        return response["error"]["code"]

    def test_hausdorff_reports_on_meshes_of_thousands_of_faces(self):
        first = self.sphere("first.off", 24, 48, 10.05)
        second = self.sphere("second.off", 25, 46, 10.0, (0.3, 0.1, 0.0))
        sampling = {"method": "grid", "grid_spacing": mm(0.9), "include_vertices": True}
        for operation, parameters in (("mesh.distance.hausdorff_bounded", {"error_bound": mm(0.01)}),
                                      ("mesh.distance.hausdorff_approximate", {"sampling": sampling}),
                                      ("mesh.distance.hausdorff_approximate_symmetric", {"sampling": sampling})):
            with self.subTest(operation=operation):
                produced = self.ok(operation, [first, second], parameters)
                report = self.report_of(produced)
                self.ok("mesh.validate.hausdorff_report", [report, first, second], parameters)
                wrong = self.tampered(report, f"wrong-{operation}.json",
                                      lambda results: results.__setitem__("distance", results["distance"] * 1.5))
                self.assertIn("DISTANCE", self.rejected("mesh.validate.hausdorff_report", [wrong, first, second], parameters))

    def test_point_to_mesh_distances_and_samples(self):
        mesh = self.sphere("mesh.off", 24, 48, 10.0)
        rnd = random.Random(5)
        points = self.points3("cloud.xyz", [(rnd.uniform(-12, 12), rnd.uniform(-12, 12), rnd.uniform(-12, 12))
                                            for _ in range(3000)])
        produced = self.ok("mesh.distance.max_to_mesh", [points, mesh], {})
        report = self.report_of(produced)
        self.ok("mesh.validate.max_distance_to_mesh", [report, points, mesh], {})
        wrong = self.tampered(report, "wrong-max.json",
                              lambda results: results.__setitem__("distance", results["distance"] * (1 + 1e-6)))
        self.assertEqual(self.rejected("mesh.validate.max_distance_to_mesh", [wrong, points, mesh], {}), "DISTANCE_MISMATCH")
        precision = {"precision": mm(0.01)}
        produced = self.ok("mesh.distance.max_to_points", [mesh, points], precision)
        self.ok("mesh.validate.max_distance_to_points", [self.report_of(produced), mesh, points], precision)
        sampling = {"sampling": {"method": "grid", "grid_spacing": mm(0.4), "include_vertices": True}}
        produced = self.ok("mesh.distance.sample_points", [mesh], sampling)
        report = self.report_of(produced)
        self.ok("mesh.validate.distance_samples", [report, mesh], sampling)

        def lift(results):
            results["points"][-1][2] += 0.01
        off = self.tampered(report, "wrong-samples.json", lift)
        self.assertEqual(self.rejected("mesh.validate.distance_samples", [off, mesh], sampling), "SAMPLE_OFF_SURFACE")

    def test_minimum_sphere_and_spacing_of_thousands_of_points(self):
        rnd = random.Random(8)
        cloud = [(rnd.gauss(0, 5), rnd.gauss(0, 5), rnd.gauss(0, 5)) for _ in range(5000)]
        points = self.points3("gauss.xyz", cloud)
        for radius in (0.0, 0.5):
            parameters = {"radius": mm(radius)}
            produced = self.ok("shape.bounding.sphere", [points], parameters)
            report = self.report_of(produced)
            self.ok("shape.validate.min_sphere", [report, points], parameters)
            larger = self.tampered(report, f"larger-{radius}.json",
                                   lambda results: results["radius"].__setitem__("value", results["radius"]["value"] * 1.001))
            self.assertEqual(self.rejected("shape.validate.min_sphere", [larger, points], parameters), "RADIUS_MISMATCH")
        # Many cospherical points with repeated extreme points: the minimum ball is still unique.
        on_sphere = []
        for _ in range(3000):
            angle, height = rnd.uniform(0, 2 * math.pi), rnd.uniform(-1, 1)
            ring = math.sqrt(1 - height * height)
            on_sphere.append((4 * ring * math.cos(angle), 4 * ring * math.sin(angle), 4 * height))
        on_sphere += [(4, 0, 0), (-4, 0, 0), (0, 4, 0), (0, -4, 0), (0, 0, 4), (0, 0, -4)] * 2
        cospherical = self.points3("cospherical.xyz", on_sphere)
        produced = self.ok("shape.bounding.sphere", [cospherical], {"radius": mm(0.0)})
        self.assertAlmostEqual(produced["metrics"]["radius"], 4.0, places=9)
        self.ok("shape.validate.min_sphere", [self.report_of(produced), cospherical], {"radius": mm(0.0)})

        neighbors = {"neighbors": 6}
        produced = self.ok("pointset.spacing.average", [points], neighbors)
        report = self.report_of(produced)
        self.ok("pointset.validate.average_spacing", [report, points], neighbors)
        wrong = self.tampered(report, "wrong-spacing.json", lambda results: results["average_spacing"].__setitem__(
            "value", results["average_spacing"]["value"] * (1 + 1e-6)))
        self.assertEqual(self.rejected("pointset.validate.average_spacing", [wrong, points], neighbors),
                         "AVERAGE_SPACING_MISMATCH")

    def test_minimum_circle_of_thousands_of_points(self):
        rnd = random.Random(2)
        path = self.root / "planar.json"
        path.write_text(json.dumps({"points": [[rnd.uniform(-9, 9), rnd.uniform(-9, 9)] for _ in range(4000)]}),
                        encoding="utf-8", newline="\n")
        points = typed(path, "PointSet2", "json")
        produced = self.ok("shape.bounding.circle", [points], {})
        self.ok("shape.validate.min_circle", [self.report_of(produced), points], {})

    def test_subdivision_of_a_mesh_above_the_former_bound(self):
        mesh = self.sphere("coarse.off", 40, 60, 10.0)
        for operation, validator in (("mesh.subdivide.loop", "mesh.validate.loop"),
                                     ("mesh.subdivide.catmull_clark", "mesh.validate.catmull_clark")):
            produced = self.ok(operation, [mesh], {"steps": 1})
            output = produced["outputs"][0]
            candidate = dict(artifact(Path(output["path"]), "candidate"), type=output["type"])
            self.ok(validator, [candidate, mesh], {"steps": 1})


class RaisedLimitRegistryTests(unittest.TestCase):
    def test_registry_states_the_raised_bounds(self):
        registry = OperationRegistry()
        expected = {"mesh.distance.hausdorff_bounded": ("maximum_faces", 200000),
                    "mesh.distance.max_to_mesh": ("maximum_faces", 200000),
                    "mesh.distance.symmetric_hausdorff": ("maximum_faces", 200000),
                    "mesh.subdivide.loop": ("maximum_faces", 250000),
                    "mesh.remesh.isotropic": ("maximum_faces", 200000),
                    "mesh.parameterize": ("maximum_faces", 20000),
                    "mesh.skeletonize.mean_curvature": ("maximum_faces", 10000),
                    "mesh.segment.sdf": ("maximum_faces", 3000),
                    "shape.bounding.circle": ("maximum_vertices", 200000),
                    "shape.bounding.sphere": ("maximum_vertices", 200000),
                    "pointset.spacing.average": ("maximum_vertices", 200000),
                    # Unchanged: the validators of these are not near-linear.
                    "mesh.decompose.approx_convex": ("maximum_faces", 2000),
                    "mesh.path.shortest": ("maximum_faces", 64)}
        for operation, (key, value) in expected.items():
            bound = next(c for c in registry.get(operation)["preconditions"] if c["id"] == "bounded_input")
            self.assertEqual(bound[key], value, operation)




@unittest.skipUnless(WORKER.is_file(), "native master worker is not built")
class FeatureProtectionTests(WorkerCase):
    """mesh.remesh.isotropic with protect_feature_angle_degrees keeps sharp edges as mesh edges."""

    def cube(self) -> dict:
        vertices = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10)]
        faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7),
                 (2, 7, 6), (3, 0, 4), (3, 4, 7)]
        path = self.root / "cube10.off"
        write_off(path, vertices, faces)
        return artifact(path, "source")

    def remesh(self, source: dict, parameters: dict) -> dict:
        produced = self.ok("mesh.remesh.isotropic", [source], parameters)
        return produced, artifact(Path(produced["outputs"][0]["path"]), "candidate")

    def test_protected_cube_keeps_its_edges_and_the_plain_one_does_not(self):
        source = self.cube()
        base = {"target_edge_length": mm(1.0), "number_of_iterations": 3, "number_of_relaxation_steps": 2}
        tight = dict(base, max_deviation=mm(0.05), protect_feature_angle_degrees=60.0)
        produced, protected = self.remesh(source, tight)
        self.assertEqual(produced["metrics"]["feature_protection"], {"angle_degrees": 60.0, "constrained_input_edges": 12})
        checked = {key: tight[key] for key in ("target_edge_length", "max_deviation", "protect_feature_angle_degrees")}
        validated = self.ok("mesh.validate.isotropic_remesh", [protected, source], checked)
        report = json.loads(Path(validated["outputs"][0]["path"]).read_text("utf-8"))
        self.assertEqual(report["status"], "pass")
        self.assertIs(report["checks"]["source_sharp_edges_on_candidate_edges"], True)

        # Without protection the corners are rounded: the same tight deviation is not met ...
        loose = dict(base, max_deviation=mm(0.05))
        _, plain = self.remesh(source, loose)
        refused = self.call("mesh.validate.isotropic_remesh", [plain, source],
                            {"target_edge_length": mm(1.0), "max_deviation": mm(0.05)})
        self.assertEqual(refused["error"]["code"], "HAUSDORFF_WITHIN_MAX_DEVIATION_FAILED")
        # ... and with a deviation that accepts the rounded surface, the feature check still rejects
        # a plain remesh presented as a feature-preserving one.
        claimed = self.call("mesh.validate.isotropic_remesh", [plain, source],
                            {"target_edge_length": mm(1.0), "max_deviation": mm(1.0),
                             "protect_feature_angle_degrees": 60.0})
        self.assertEqual(claimed["status"], "error", claimed)
        self.assertEqual(claimed["error"]["code"], "SOURCE_SHARP_EDGES_ON_CANDIDATE_EDGES_FAILED")
        accepted = self.ok("mesh.validate.isotropic_remesh", [plain, source],
                           {"target_edge_length": mm(1.0), "max_deviation": mm(1.0)})
        self.assertEqual(json.loads(Path(accepted["outputs"][0]["path"]).read_text("utf-8"))["status"], "pass")

    def test_angle_is_validated_and_bound_to_the_validator(self):
        source = self.cube()
        parameters = {"target_edge_length": mm(1.0), "number_of_iterations": 1, "number_of_relaxation_steps": 1,
                      "max_deviation": mm(0.05)}
        for bad in (0.0, 181.0, "sharp"):
            response = self.call("mesh.remesh.isotropic", [source], dict(parameters, protect_feature_angle_degrees=bad))
            self.assertEqual(response["status"], "error", bad)
            self.assertEqual(response["error"]["class"], "INVALID_REQUEST", bad)
        operation = OperationRegistry().get("mesh.remesh.isotropic")
        self.assertNotIn("protect_feature_angle_degrees", operation["parameters"]["required"])
        binding = operation["validation"]["bindings"]["mesh.validate.isotropic_remesh"]["parameters"]
        self.assertEqual(binding["protect_feature_angle_degrees"],
                         {"parameter": "protect_feature_angle_degrees", "optional": True})


if __name__ == "__main__":
    unittest.main()
