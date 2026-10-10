from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path

from cgal_mcp.master.errors import InvalidInput, PreconditionFailure, UnsupportedOperation

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "evaluate_master_search", REPO / "scripts" / "evaluate_master_search.py")
assert SPEC and SPEC.loader
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


def _context():
    packages=json.loads((REPO/"catalog/packages.json").read_text(encoding="utf-8"))
    requirements=json.loads((REPO/"catalog/major_requirements.json").read_text(encoding="utf-8"))
    inventory=json.loads((REPO/"catalog/major_capability_inventory.json").read_text(encoding="utf-8"))
    operations=json.loads((REPO/"cgal_mcp/master/operations.json").read_text(encoding="utf-8"))
    families, requirement_ids=acceptance._requirements(requirements)
    req_families, req_packages=acceptance._requirement_context(requirements,inventory)
    operation_index=acceptance._operations(operations)
    return (acceptance._package_ids(packages),operation_index,requirement_ids,families,
            req_families,req_packages)


class _RecordingRuntime:
    def __init__(self): self.search_calls=[]; self.plan_calls=0
    def capabilities_search(self, query, artifact_ids=None, constraints=None, limit=3):
        self.search_calls.append((query,artifact_ids,constraints,limit))
        return {"candidates":[{"operation_id":"hull.convex_3"}]}
    def docs_search(self, query, limit):
        return {"results":[{"package":"Kernel_23","scope":"reference","executable":False}]}
    def plan(self, request):
        self.plan_calls+=1
        raise AssertionError("natural intent evaluation must not call plan")


class _GateRuntime:
    def plan(self, request):
        if request["operation_id"] == "invented.dynamic_cpp":
            raise UnsupportedOperation(request["operation_id"])
        policy=request["policy"]
        if "kernel" in policy: raise InvalidInput("kernel_unsupported","unsupported")
        if "dependencies" in policy: raise PreconditionFailure("Dependencies are unavailable")
        if "allowed_licenses" in policy: raise PreconditionFailure("License policy excludes")
        raise AssertionError("unexpected gate")


class _RoutingRuntime:
    def __init__(self, outcomes):
        self.outcomes=outcomes; self.plan_calls=0; self.execute_calls=0
    def capabilities_search(self, query, artifact_ids=None, constraints=None, limit=5):
        if query=="docs":
            return {"candidates":[],"query_analysis":{}}
        selected=("pointset.remove_outliers" if query in {"wrong","hidden"}
                  else "hull.convex_3")
        return {"candidates":[{"operation_id":selected,"route_supported":True,
                               "confidence":"high","uncovered_primary_concepts":[]}],
                "query_analysis":{"recommended_operation":selected,
                                  "routing_confidence":"high",
                                  "automatic_route_supported":True}}
    def plan(self, request):
        self.plan_calls+=1
        outcome=self.outcomes[request["goal"]]
        if isinstance(outcome,Exception): raise outcome
        return {"route":{"mode":"registry_route","selected":outcome}}
    def execute(self, request):
        self.execute_calls+=1
        raise AssertionError("routing acceptance must never execute")


class MasterSearchAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus=json.loads((REPO/"tests/fixtures/master/search_intents.json").read_text(encoding="utf-8"))
        cls.smoke=json.loads((REPO/"tests/fixtures/master/package_discovery_cases.json").read_text(encoding="utf-8"))
        (cls.packages,cls.operation_index,cls.requirements,cls.families,
         cls.req_families,cls.req_packages)=_context()

    def validate(self, corpus, *, full=True):
        return acceptance.validate_corpus(corpus,package_ids=self.packages,
            operation_ids=set(self.operation_index),requirement_ids=self.requirements,
            family_ids=self.families,operation_index=self.operation_index,
            requirement_families=self.req_families,requirement_packages=self.req_packages,
            require_full_count=full)

    def test_checked_in_natural_corpus_is_complete_and_valid(self):
        self.assertEqual(self.validate(self.corpus),[])
        self.assertEqual(len(self.corpus["intents"]),300)
        self.assertEqual({item["family"] for item in self.corpus["intents"]},self.families)
        self.assertEqual({rid for item in self.corpus["intents"] for rid in item["requirement_ids"]},self.requirements)

    def test_named_package_smoke_is_separate_and_complete(self):
        self.assertEqual(acceptance.validate_package_smoke(self.smoke,self.packages),[])
        self.assertEqual(len(self.smoke["cases"]),126)
        self.assertTrue(all(case["query"]==case["expected_package"]
                            for case in self.smoke["cases"]))
        natural=json.dumps(self.corpus["intents"],ensure_ascii=False)
        self.assertNotIn("official reference",natural.casefold())

    def test_routing_probe_types_and_package_expectations_match_tasks(self):
        by_requirement={}
        for item in self.corpus["intents"]:
            by_requirement.setdefault(item["requirement_ids"][0],[]).append(item)
        # Ray-batch goals carry the typed RayBatch3 artifact beside the mesh.
        self.assertTrue(all(item["input_types"] in (["TriangleSurfaceMesh"],
                                                    ["TriangleSurfaceMesh","RayBatch3"])
                            for item in by_requirement["major.7.2.01"]))
        self.assertTrue(all(item["input_types"]==["TriangleSurfaceMesh","RayBatch3"]
                            for item in by_requirement["major.7.2.01"]
                            if item["expected_operations"]==["spatial.aabb.ray_first_hits"]))
        self.assertTrue(all(item["input_types"]==["TriangleSurfaceMesh"]
                            for item in by_requirement["major.7.4.02"]))
        self.assertTrue(all(item["input_types"]==["TriangleSurfaceMesh"]*2
                            for item in by_requirement["major.7.5.02"]))
        self.assertTrue(all(item["expected_packages"]==
                            ["Advancing_front_surface_reconstruction"]
                            for item in by_requirement["major.7.10.02"]))
        malformed=copy.deepcopy(self.corpus)
        hausdorff=next(item for item in malformed["intents"]
                       if item["expected_operations"]==["mesh.distance.symmetric_hausdorff"])
        hausdorff["input_types"]=["TriangleSurfaceMesh"]
        self.assertTrue(any("input_types/arity" in error
                            for error in self.validate(malformed)))

    def test_count_language_and_simplification_cap_are_hard_gates(self):
        malformed=copy.deepcopy(self.corpus); malformed["intents"].pop()
        errors=self.validate(malformed)
        self.assertIn("Corpus must contain exactly 300 intents; found 299",errors)
        self.assertTrue(any(x.startswith("Corpus language split") for x in errors))
        too_many=copy.deepcopy(self.corpus)
        for item in too_many["intents"][:16]:
            item["expected_execution"]="eligible"; item["intent_class"]="simplification"
            item["requirement_ids"]=["major.7.7.01"]; item["family"]="7.7"
            item["expected_operations"]=["hull.convex_3"]; item["input_types"]=["PointSet3"]
        self.assertTrue(any("Total simplification intents" in x for x in self.validate(too_many)))
        mislabeled=copy.deepcopy(self.corpus)
        mislabeled["intents"][0]["intent_class"]="simplification"
        self.assertTrue(any("intent_class disagrees" in x for x in self.validate(mislabeled)))

    def test_serial_templates_and_requirement_package_mismatch_are_rejected(self):
        malformed=copy.deepcopy(self.corpus)
        malformed["intents"][0]["query"]="Find the official package reference (brief 17)."
        malformed["intents"][0]["source_packages"]=["AABB_tree"]
        errors=self.validate(malformed)
        self.assertTrue(any("synthetic serial marker" in x for x in errors))
        self.assertTrue(any("do not match original requirement evidence" in x for x in errors))

        repeated=copy.deepcopy(self.corpus)
        for index,item in enumerate(repeated["intents"][:13]):
            item["language"]="en"
            item["query"]=(
                f"Given a measured mesh sample {index}, please compute an individual "
                f"geometric output value {index + 100} for the model.")
        errors=self.validate(repeated)
        self.assertTrue(any("overuse the same structural skeleton" in x for x in errors))

        scaffold=copy.deepcopy(self.corpus)
        scaffold["intents"][0]["query"]=(
            "Find a suitable method for this geometry task and return the output.")
        self.assertTrue(any("banned task scaffold" in x for x in self.validate(scaffold)))

        near=copy.deepcopy(self.corpus)
        near["intents"][0]["language"]="en"
        near["intents"][0]["query"]=(
            "Compute the symmetric surface deviation between a reference triangle mesh "
            "and a candidate mesh, then return a tolerance report.")
        near["intents"][1]["language"]="en"
        near["intents"][1]["query"]=(
            "Compute the symmetric surface deviation between a reference triangle mesh "
            "and a candidate mesh, then return a verified tolerance report.")
        self.assertTrue(any("near-duplicate tasks" in x for x in self.validate(near)))

    def test_eligible_search_receives_artifact_ids_for_declared_input_types(self):
        corpus={"schema_version":2,"intents":[{
            "id":"one","language":"en","family":"7.13","query":"Build a closed convex envelope around the measured three-dimensional samples.",
            "requirement_ids":["major.7.13.01"],"source_packages":["Convex_hull_3"],
            "expected_execution":"eligible","expected_operations":["hull.convex_3"],
            "expected_packages":["Convex_hull_3"],"input_types":["PointSet3"],"constraints":{},"intent_class":"general"}]}
        runtime=_RecordingRuntime()
        report=acceptance.evaluate(corpus,runtime=runtime,
            operation_index={"hull.convex_3":{"status":"VALIDATED"}},
            artifact_ids_by_type={"PointSet3":"artifact-points"})
        self.assertEqual(runtime.search_calls[0][1],["artifact-points"])
        self.assertEqual(report["eligibility"]["top3_hits"],1)
        self.assertEqual(report["automatic_execution"]["status"],"UNMEASURED")
        self.assertEqual(runtime.plan_calls,0)

    def test_goal_routing_requires_expected_top1_or_explicit_rejection(self):
        intents=[{
            "id":"top1","query":"build hull","expected_execution":"eligible",
            "expected_operations":["hull.convex_3"],"input_types":["PointSet3"],
            "routing_probe":{"status":"measured"}}, {
            "id":"ambiguous","query":"ambiguous","expected_execution":"eligible",
            "expected_operations":["hull.convex_3"],"input_types":["PointSet3"],
            "routing_probe":{"status":"measured"}}, {
            "id":"docs","query":"docs","expected_execution":"documentation_only",
            "expected_operations":[],"input_types":["PointSet3"],
            "routing_probe":{"status":"measured"}}]
        runtime=_RoutingRuntime({
            "build hull":"hull.convex_3",
            "ambiguous":InvalidInput("ambiguous_route","choose an operation"),
            "docs":UnsupportedOperation("docs")})
        operation={"id":"hull.convex_3","status":"VALIDATED",
                   "io":{"inputs":[{"types":["PointSet3"]}]},
                   "parameters":{"type":"object","required":[],"properties":{}}}
        report=acceptance.evaluate_goal_routing(
            {"intents":intents},runtime=runtime,
            operation_index={"hull.convex_3":operation},
            artifact_ids_by_type={"PointSet3":"artifact-points"})
        self.assertTrue(report["passes"])
        self.assertEqual(report["eligible"]["expected_top1"],1)
        self.assertEqual(report["eligible"]["ambiguous_explicit"],1)
        self.assertEqual(report["documentation_only"]["explicitly_rejected"],1)
        self.assertEqual(runtime.plan_calls,3)
        self.assertEqual(runtime.execute_calls,0)

    def test_goal_routing_rejects_wrong_plan_and_post_route_parameter_error(self):
        intents=[{
            "id":"wrong","query":"wrong","expected_execution":"eligible",
            "expected_operations":["hull.convex_3"],"input_types":["PointSet3"],
            "routing_probe":{"status":"measured"}}, {
            "id":"clarify","query":"clarify","expected_execution":"eligible",
            "expected_operations":["hull.convex_3"],"input_types":["PointSet3"],
            "routing_probe":{"status":"measured"}}, {
            "id":"hidden","query":"hidden","expected_execution":"documentation_only",
            "expected_operations":[],"input_types":["PointSet3"],
            "routing_probe":{"status":"measured"}}]
        runtime=_RoutingRuntime({
            "wrong":"pointset.remove_outliers",
            "clarify":InvalidInput("route_parameter_missing","name the method"),
            "hidden":InvalidInput("parameters_required","missing after wrong route")})
        operation={"id":"hull.convex_3","status":"VALIDATED",
                   "io":{"inputs":[{"types":["PointSet3"]}]},
                   "parameters":{"type":"object","required":[],"properties":{}}}
        report=acceptance.evaluate_goal_routing(
            {"intents":intents},runtime=runtime,
            operation_index={"hull.convex_3":operation},
            artifact_ids_by_type={"PointSet3":"artifact-points"})
        self.assertFalse(report["passes"])
        self.assertEqual(report["eligible"]["wrong_executable_route"],1)
        self.assertEqual(report["eligible"]["clarification_required"],1)
        self.assertEqual(report["documentation_only"]["wrong_route_with_post_error"],1)
        hidden=next(case for case in report["cases"] if case["id"]=="hidden")
        self.assertEqual(hidden["actual_error"]["code"],"parameters_required")

    def test_unrepresentable_docs_probe_is_unmeasured_without_planner_call(self):
        runtime=_RoutingRuntime({})
        intent={"id":"polygon","query":"offset a polygon with holes",
                "expected_execution":"documentation_only","expected_operations":[],
                "input_types":["PointSet3"],"routing_probe":{
                    "status":"unmeasured_input_model",
                    "reason":"polygon rings and holes are unavailable"}}
        report=acceptance.evaluate_goal_routing(
            {"intents":[intent]},runtime=runtime,operation_index={},
            artifact_ids_by_type={"PointSet3":"artifact-points"})
        self.assertFalse(report["passes"])
        self.assertEqual(report["documentation_only"]["unmeasured_input_model"],1)
        self.assertEqual(report["actual_planning_coverage"]["planner_calls"],0)
        self.assertEqual(runtime.plan_calls,0)

    def test_unavailable_expected_operation_remains_in_denominator(self):
        corpus={"schema_version":2,"intents":[{
            "id":"missing","language":"en","family":"7.2","query":"Find the nearest sample to each query location in a large spatial data set.",
            "requirement_ids":["major.7.2.03"],"source_packages":["Spatial_searching"],
            "expected_execution":"eligible","expected_operations":["spatial.nearest"],
            "expected_packages":["Spatial_searching"],"input_types":["PointSet3"],"constraints":{},"intent_class":"general"}]}
        class _DocsOnly:
            def docs_search(self,query,limit): return {"results":[]}
        report=acceptance.evaluate(corpus,runtime=_DocsOnly(),
            operation_index={"spatial.nearest":{"status":"CATALOGED"}},
            artifact_ids_by_type={"PointSet3":"artifact-points"})
        self.assertEqual(report["eligibility"]["denominator"],1)
        self.assertEqual(report["eligibility"]["expected_operation_unavailable"],1)
        self.assertEqual(report["eligibility"]["top3_hits"],0)

    def test_planner_gates_use_valid_artifacts_and_exact_error_taxonomy(self):
        report=acceptance.evaluate_planner_gates(self.corpus["planner_gates"],
            runtime=_GateRuntime(),artifact_ids_by_type={"PointSet3":"valid-point-artifact"})
        self.assertTrue(report["passes"])
        self.assertEqual(report["passed"],4)
        self.assertTrue(all(case["used_input_types"]==["PointSet3"] for case in report["cases"]))
        bad=copy.deepcopy(self.corpus["planner_gates"][:1])
        bad[0]["expected_error"]["code"]="wrong_code"
        self.assertFalse(acceptance.evaluate_planner_gates(bad,runtime=_GateRuntime(),
            artifact_ids_by_type={"PointSet3":"valid-point-artifact"})["passes"])

    def test_full_report_is_truthful_about_missing_autoexecution_measurement(self):
        report=acceptance.run()
        self.assertEqual(report["automatic_execution"]["status"],"UNMEASURED")
        self.assertEqual(report["goal_routing"]["automatic_execution"]["status"],"UNMEASURED")
        self.assertEqual(len(report["goal_routing"]["cases"]),300)
        self.assertFalse(report["passes_acceptance"])
        self.assertFalse(report["overall_standalone_ready"])
        self.assertTrue(report["planner_gates"]["passes"])
        self.assertEqual(report["package_discovery_smoke"]["denominator"],126)
        self.assertEqual(report["package_discovery_smoke"]["hits"],126)
        self.assertTrue(report["package_discovery_smoke"]["passes"])


if __name__ == "__main__":
    unittest.main()
