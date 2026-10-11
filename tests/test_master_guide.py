"""The AI-facing guide is generated from the registry; these tests fail when it drifts."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import build_master_guide  # noqa: E402
from cgal_mcp.master import guide_build  # noqa: E402
from cgal_mcp.master.errors import InvalidInput  # noqa: E402
from cgal_mcp.master.guide import Guide  # noqa: E402
from cgal_mcp.master.runtime import MasterRuntime  # noqa: E402
from cgal_mcp.master.server import create_server  # noqa: E402

WORKER = REPO / "build-master/Release/cgal-master-worker.exe"
BUNDLE = REPO / "cgal_mcp/master/guide/guide.json"
SECTIONS = ("Purpose", "Inputs", "Outputs", "Parameters", "Validation", "Limits", "Failure codes",
            "Example", "Provenance")


def substitute(value, mapping):
    if isinstance(value, str) and value.startswith("$") and value[1:] in mapping:
        return mapping[value[1:]]
    if isinstance(value, dict):
        return {k: substitute(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, mapping) for v in value]
    return value


class GuideSnapshotTests(unittest.TestCase):
    def test_snapshot_is_fresh(self):
        for path, content in build_master_guide.expected().items():
            self.assertTrue(path.exists(), path)
            self.assertEqual(path.read_text(encoding="utf-8"), content,
                             f"{path} is stale: run scripts/build_master_guide.py")

    def test_no_local_paths_or_secrets(self):
        text = BUNDLE.read_text(encoding="utf-8")
        for pattern in (r"[A-Za-z]:\\\\", r"[A-Za-z]:/(?:Users|aiwork)", r"/Users/", r"/home/"):
            self.assertIsNone(re.search(pattern, text), pattern)


class GuideContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guide = Guide()
        cls.bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
        cls.src = guide_build.Sources(REPO)

    def test_every_operation_has_complete_card_in_both_languages(self):
        ops = self.guide.operation_ids()
        self.assertEqual(len(ops), self.bundle["counts"]["operations"])
        for lang in ("en", "ja"):
            for oid in ops:
                card = self.guide.get(f"op:{oid}", lang)
                self.assertIn(oid, card)
                if lang == "en":
                    for section in SECTIONS:
                        self.assertRegex(card, rf"(?m)^## {section}\b", f"{oid} lacks {section}")
                self.assertGreater(len(card.strip().splitlines()), 8, oid)

    def test_every_executable_non_validator_operation_has_example(self):
        for op in self.src.ops.values():
            oid = op["id"]
            if op.get("role") == "validator":
                continue
            self.assertIn(oid, self.bundle["examples"], oid)

    def test_recipe_steps_reference_real_operations_and_fixtures(self):
        ops = set(self.guide.operation_ids())
        workflows = json.loads((REPO / "docs/master/workflows.json").read_text(encoding="utf-8"))
        items = workflows if isinstance(workflows, list) else workflows.get("workflows", [])
        self.assertTrue(items)
        for rid in self.guide.recipe_ids():
            body = self.guide.get(f"recipe:{rid}", "en")
            self.assertTrue(body.strip(), rid)
            if rid.startswith("neg"):
                continue  # negative workflows deliberately name unregistered operations
            for match in re.finditer(r"cgal_artifact_import (\{.*\})", body):
                spec = json.loads(match.group(1))
                self.assertTrue((REPO / spec["path"]).exists(), spec["path"])
            block = re.search(r"```json\n(.*?)\n```", body, re.S)
            if block:
                request = json.loads(block.group(1))["request"]
                for step in request.get("steps", []):
                    self.assertIn(step["operation"], ops, rid)

    def test_example_fixtures_exist_and_requests_name_real_ops(self):
        ops = set(self.guide.operation_ids())
        for oid, example in self.bundle["examples"].items():
            for item in example["imports"]:
                self.assertTrue((REPO / item["path"]).exists(), item["path"])
            request = example["plan_request"]
            names = [request["operation_id"]] if "operation_id" in request else [
                s["operation"] for s in request["steps"]]
            for name in names:
                self.assertIn(name, ops, oid)

    def test_error_codes_all_covered_by_groups(self):
        groups = guide_build.collect_error_groups(self.src)
        listed = {code for codes in groups.values() for code in codes}
        self.assertEqual(len(listed), self.bundle["counts"]["error_codes"])
        page = self.guide.get("errors", "en")
        for code in list(listed)[:400]:
            self.assertIn(code, page, code)

    def test_instructions_size_and_counts(self):
        text = self.guide.instructions("en")
        words = len(text.split())
        self.assertGreaterEqual(words, 600)
        self.assertLessEqual(words, 900)
        self.assertIn(str(self.bundle["counts"]["operations"]), text)
        self.assertIn("cgal_get_guide", text)

    def test_unknown_topic_is_refused_with_choices(self):
        with self.assertRaises(InvalidInput):
            self.guide.get("nonsense", "en")

    def test_prompts_reference_real_ops_and_recipes(self):
        ops, recipes = set(self.guide.operation_ids()), set(self.guide.recipe_ids())
        for name, prompt in self.bundle["prompts"].items():
            blob = json.dumps(prompt, ensure_ascii=False)
            for oid in re.findall(r"\b(?:mesh|hull|pointset|reconstruction|polygon|triangulation|spatial|shape|kernel|arrangement|optimization)\.[a-z0-9_.]*[a-z0-9_]", blob):
                self.assertIn(oid, ops, f"{name}: {oid}")
            for rid in re.findall(r"\bwf\d\d[a-z0-9\-]*[a-z0-9]", blob):
                self.assertIn(rid, recipes, f"{name}: {rid}")


class GuideServerTests(unittest.TestCase):
    def test_server_surface_and_every_resource_prompt_renders(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as data:
                runtime = MasterRuntime(Path(data), worker=WORKER, require_memory_limit=False)
                try:
                    server = create_server(runtime)
                    self.assertEqual(len(await server.list_tools()), 13)
                    resources = await server.list_resources()
                    self.assertEqual(len(resources), 12)
                    self.assertEqual(len(await server.list_resource_templates()), 6)
                    prompts = await server.list_prompts()
                    self.assertEqual(len(prompts), 7)
                    for resource in resources:
                        content = await server.read_resource(str(resource.uri))
                        self.assertTrue(content[0].content.strip())
                    samples = {
                        "start_here": {"request": "x"},
                        "repair_and_simplify_mesh": {"mesh_path": "a.off", "unit": "mm"},
                        "reconstruct_surface_from_points": {"points_path": "a.xyz", "unit": "mm"},
                        "validate_geometry": {"path": "a.off", "unit": "mm"},
                        "compare_meshes": {"reference_path": "a.off", "candidate_path": "b.off", "unit": "mm"},
                        "2d_boolean_offset": {"polygon_path": "a.json", "unit": "mm"},
                        "choose_operation": {"goal": "x"},
                    }
                    self.assertEqual({p.name for p in prompts}, set(samples))
                    for name, arguments in samples.items():
                        for lang in ("en", "ja"):
                            result = await server.get_prompt(name, {**arguments, "lang": lang})
                            text = result.messages[0].content.text
                            self.assertNotIn("<<", text)
                            self.assertTrue(text.strip())
                    ja = await server.read_resource("cgal://guide/ja/op/hull.convex_3")
                    self.assertTrue(ja[0].content.strip())
                finally:
                    runtime.close()
        asyncio.run(scenario())


@unittest.skipUnless(WORKER.exists(), "native worker not built")
class GuideExamplesExecuteTests(unittest.TestCase):
    def test_sample_examples_execute_and_validate(self):
        bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
        ids = sorted(bundle["examples"])[::12]

        async def scenario():
            with tempfile.TemporaryDirectory() as data:
                runtime = MasterRuntime(Path(data), worker=WORKER, require_memory_limit=False)
                try:
                    for oid in ids:
                        example = bundle["examples"][oid]
                        mapping = {}
                        for item in example["imports"]:
                            imported = runtime.artifact_import(str(REPO / item["path"]), item["unit"],
                                                               artifact_type=item["artifact_type"])
                            mapping[item["name"]] = imported["artifact_id"]
                        plan = runtime.plan(substitute(example["plan_request"], mapping))
                        job = await runtime.execute(plan["plan_id"])
                        await runtime.tasks[job["job_id"]]
                        detail = runtime.store.get_job(job["job_id"])
                        self.assertEqual(detail["state"], "succeeded", oid)
                finally:
                    runtime.close()
        asyncio.run(scenario())


class FirstContactEvidenceTests(unittest.TestCase):
    def test_evidence_bound_to_current_guide_and_informational(self):
        path = REPO / "docs/master/evidence/first-contact.json"
        self.assertTrue(path.exists(), "run scripts/evaluate_first_contact.py --output")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(data["informational"])
        self.assertFalse(data["gating"])
        self.assertEqual(data["bindings"]["guide_bundle_sha256"],
                         hashlib.sha256(BUNDLE.read_bytes()).hexdigest())
        self.assertGreaterEqual(data["summary"]["requests"], 25)
        self.assertEqual(data["summary"]["examples_succeeded"], data["summary"]["examples_total"])
        self.assertEqual(data["summary"]["executed_ok"], data["summary"]["requests"])


if __name__ == "__main__":
    unittest.main()
