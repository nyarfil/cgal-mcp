"""Rounded clip / split / corefine / autorefine for meshes in general position.

The exact operations publish only results whose coordinates are binary64 values, so a plane
through a sphere is refused. These tests drive the native worker through its JSON protocol
(skipped when no worker is built) and check the registry entries.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from cgal_mcp.master.registry import OperationRegistry
from tests.test_master_boolean_rounded import FIXTURES, WORKER, WorkerCase, artifact, read_off, write_off

PLANE = {"normal": [0.3, 0.2, 1.0], "offset": {"value": 1.25, "unit": "mm"}}
CASES = (
    ("mesh.clip.plane_rounded", "mesh.validate.clip_rounded", "mesh.clip.plane", ("a",), dict(PLANE, clip_volume=True)),
    ("mesh.clip.plane_rounded", "mesh.validate.clip_rounded", "mesh.clip.plane", ("a",), dict(PLANE, clip_volume=False)),
    ("mesh.split.plane_rounded", "mesh.validate.split_rounded", "mesh.split.plane", ("a",), PLANE),
    ("mesh.corefine_rounded", "mesh.validate.corefine_rounded", "mesh.corefine", ("a", "b"), {}),
    ("mesh.autorefine_rounded", "mesh.validate.autorefine_rounded", "mesh.autorefine", ("both",), {}),
)
CHECKS = ("candidate_is_valid_mesh", "element_counts_match_reference", "border_matches_reference",
          "no_degenerate_face", "self_intersection_free_like_reference",
          "candidate_vertices_within_tolerance_of_reference_surface",
          "reference_vertices_within_tolerance_of_candidate_surface", "volume_within_tolerance_when_closed")


@unittest.skipUnless(WORKER.is_file(), "native master worker is not built")
class RoundedMeshTests(WorkerCase):
    def sources(self, names):
        files = {"a": "sphere_general_a.off", "b": "sphere_general_b.off",
                 "both": "spheres_general_intersecting.off"}
        return [artifact(FIXTURES / files[name], name) for name in names]

    def test_exact_operations_refuse_and_rounded_ones_pass_validation(self):
        for operation, validator, exact, names, parameters in CASES:
            with self.subTest(operation=operation, parameters=parameters):
                inputs = self.sources(names)
                refusal = self.call(exact, inputs, parameters)
                self.assertEqual(refusal["error"]["code"], "OUTPUT_NOT_REPRESENTABLE")
                self.assertEqual(refusal["error"]["suggested_operations"], [operation])
                produced = self.ok(operation, inputs, parameters)
                candidate = artifact(Path(produced["outputs"][0]["path"]), "candidate")
                validated = self.ok(validator, [candidate] + inputs, parameters)
                report = json.loads(Path(validated["outputs"][0]["path"]).read_text("utf-8"))
                self.assertEqual(report["status"], "pass")
                self.assertEqual(report["comparison"], "tolerance")
                for check in CHECKS:
                    self.assertIs(report["checks"][check], True, check)
                # 2^-40 times the power of two above the largest source coordinate.
                largest = max(abs(c) for item in inputs for v in read_off(Path(item["path"]))[0] for c in v)
                scale = 1.0
                while scale <= largest:
                    scale *= 2.0
                self.assertEqual(report["tolerance"], scale * 2.0 ** -40)
                self.assertLess(report["max_candidate_vertex_distance"], report["tolerance"])
                self.assertLess(report["max_reference_vertex_distance"], report["tolerance"])

    def test_volume_clip_is_closed_and_surface_clip_is_open(self):
        inputs = self.sources(("a",))
        closed = self.ok("mesh.clip.plane_rounded", inputs, dict(PLANE, clip_volume=True))
        opened = self.ok("mesh.clip.plane_rounded", inputs, dict(PLANE, clip_volume=False))
        self.assertEqual(closed["metrics"]["border_halfedge_count"], 0)
        self.assertGreater(opened["metrics"]["border_halfedge_count"], 0)
        # No vertex of the clipped mesh lies on the removed side beyond the rounding tolerance.
        vertices, _ = read_off(Path(closed["outputs"][0]["path"]))
        normal, offset = PLANE["normal"], PLANE["offset"]["value"]
        self.assertLess(max(sum(n * c for n, c in zip(normal, v)) - offset for v in vertices), 1e-9)

    def test_validator_rejects_tampering_a_source_and_other_parameters(self):
        inputs = self.sources(("a",))
        parameters = dict(PLANE, clip_volume=True)
        produced = self.ok("mesh.clip.plane_rounded", inputs, parameters)
        candidate = artifact(Path(produced["outputs"][0]["path"]), "candidate")
        self.refused("mesh.validate.clip_rounded", [inputs[0]] + inputs, parameters, "ROUNDED_COUNT_MISMATCH")
        self.refused("mesh.validate.clip_rounded", [candidate] + inputs, dict(parameters, clip_volume=False),
                     "ROUNDED_COUNT_MISMATCH")
        vertices, faces = read_off(Path(candidate["path"]))
        for delta in (1e-3, 1e-6, 1e-9):
            moved = list(vertices)
            x, y, z = moved[30]
            moved[30] = (x + delta, y, z)
            path = self.root / f"clip-tampered-{delta}.off"
            write_off(path, moved, faces)
            response = self.call("mesh.validate.clip_rounded", [artifact(path, "t")] + inputs, parameters)
            self.assertEqual(response["status"], "error", delta)
            self.assertEqual(response["error"]["class"], "VALIDATION_FAILED", delta)
        path = self.root / "clip-missing-face.off"
        write_off(path, vertices, faces[:-1])
        response = self.call("mesh.validate.clip_rounded", [artifact(path, "t")] + inputs, parameters)
        self.assertEqual(response["error"]["class"], "VALIDATION_FAILED")


class RoundedMeshRegistryTests(unittest.TestCase):
    def test_rounded_operations_are_implemented_fallbacks_with_mandatory_validators(self):
        registry = OperationRegistry()
        for operation, validator, exact, _names, _parameters in CASES:
            entry = registry.get(operation, executable=True)
            self.assertEqual(entry["status"], "IMPLEMENTED", operation)
            self.assertEqual(entry["fallback_for"], [exact])
            self.assertEqual(entry["validation"]["validators"], [validator])
            self.assertIs(entry["validation"]["required"], True)
            self.assertEqual(registry.get(validator, executable=True)["validation"]["validates"], operation)

    def test_plain_goals_route_to_the_exact_operation_and_explicit_ones_reach_the_fallback(self):
        registry = OperationRegistry()
        plain = registry.search("clip a mesh with a plane", limit=5)
        self.assertEqual(plain["query_analysis"]["recommended_operation"], "mesh.clip.plane")
        fallback = next(c for c in plain["candidates"] if c["operation_id"] == "mesh.clip.plane_rounded")
        self.assertIs(fallback["route_supported"], False)
        explicit = registry.search("rounded plane clip of a sphere", limit=5)
        self.assertEqual(explicit["candidates"][0]["operation_id"], "mesh.clip.plane_rounded")
        self.assertIs(explicit["candidates"][0]["route_supported"], True)


if __name__ == "__main__":
    unittest.main()
