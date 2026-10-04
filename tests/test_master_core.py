import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cgal_mcp.master.errors import InvalidInput, PreconditionFailure, UnsupportedOperation, WorkerFailure
from cgal_mcp.master.formats import inspect_bytes
from cgal_mcp.master.planner import _acyclic
from cgal_mcp.master.registry import OperationRegistry
from cgal_mcp.master.runtime import MasterRuntime
from cgal_mcp.master.server import create_server
from cgal_mcp.master.store import ArtifactStore
from cgal_mcp.master.util import normalize_quantities


POINTS = b"0 0 0\n1 0 0\n0 1 0\n0 0 1\n0.2 0.2 0.2\n"
TETRA = """OFF
4 4 0
0 0 0
1 0 0
0 1 0
0 0 1
3 0 2 1
3 0 1 3
3 1 2 3
3 2 0 3
"""


def make_worker(directory: Path, mode: str = "ok") -> Path:
    worker = directory / f"worker_{mode}.py"
    source = f'''import json, pathlib, sys, time
manifest={{"protocol":1,"actual_cgal_version":"6.2.1","build":{{"actual_cgal_version":"6.2.1","source_kind":"official_release","source_sha256":"b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf","test_stub":True}},"operations":[
{{"id":"hull.convex_3","revision":1,"input_types":["PointSet3"],"output_type":"TriangleSurfaceMesh","role":"transform","supported_kernels":["exact_constructions","package_recommended"]}},
{{"id":"hull.validate.convex_enclosure","revision":1,"input_types":["TriangleSurfaceMesh","PointSet3"],"output_type":"ValidationReport","role":"validator","supported_kernels":["exact_constructions","package_recommended"]}}]}}
if {mode!r} == "manifest_wrong": manifest["operations"][0]["revision"]=2
if "--manifest" in sys.argv:
    print(json.dumps(manifest)); raise SystemExit(0)
request=json.loads(sys.stdin.readline())
mode={mode!r}
if mode == "slow": time.sleep(30)
if mode == "oom": bytearray(512 * 1024 * 1024)
if mode == "validator_error" and request["operation"] == "hull.validate.convex_enclosure":
    print(json.dumps({{"protocol":1,"request_id":request["request_id"],"status":"error","outputs":[],"error":{{"class":"VALIDATION_FAILED","code":"outside","message":"point outside","recoverable":False,"suggested_operations":[]}}}})); raise SystemExit(0)
output=pathlib.Path(request["output_dir"])
if request["operation"] == "hull.convex_3":
    path=output/"hull.off"; path.write_text({TETRA!r},encoding="utf-8")
    unit="m" if mode == "wrong_unit" else request["inputs"][0]["unit"]
    outputs=[] if mode == "malformed" else [{{"slot":"geometry","type":"TriangleSurfaceMesh","unit":unit,"format":"off","path":str(path.resolve())}}]
else:
    report={{"status":"pass","valid":True,"triangulated":True,"closed":True,"outward_oriented":True,"positive_volume":True,"strongly_convex":True,"all_original_points_enclosed":True}}
    if mode == "incomplete": report={{"status":"pass"}}
    if mode == "huge_report": report["padding"]="x" * (3 * 1024 * 1024)
    path=output/"validation.json"; path.write_text(json.dumps(report),encoding="utf-8")
    outputs=[{{"slot":"validation","type":"ValidationReport","unit":"none","format":"json","path":str(path.resolve())}}]
print(json.dumps({{"protocol":1,"request_id":request["request_id"],"status":"ok","outputs":outputs,"metrics":{{}},"diagnostics":[]}}))
'''
    worker.write_text(source, encoding="utf-8")
    return worker


def make_wave_worker(directory: Path, mode: str = "pass") -> Path:
    document = json.loads(Path("cgal_mcp/master/operations.json").read_text(encoding="utf-8"))
    operations = []
    for operation in document["operations"]:
        actual = {"id": operation["id"], "revision": operation["revision"],
                  "input_types": [item["types"][0] for item in operation["io"]["inputs"]],
                  "output_type": operation["io"]["outputs"][0]["type"],
                  "role": operation["role"], "supported_kernels": operation["kernel"]["supported"]}
        contract = operation.get("worker_manifest", {})
        if contract:
            actual.update({"effective_kernel": contract["effective_kernel"],
                           "dependencies": operation["dependencies"],
                           "info": dict(contract["info"])})
            bindings = {validator: {target: binding["parameter"]
                                    for target, binding in recipe.get("parameters", {}).items()}
                        for validator, recipe in operation["validation"].get("bindings", {}).items()
                        if recipe.get("parameters")}
            if bindings:
                actual["info"]["validator_parameter_bindings"] = bindings
        operations.append(actual)
    manifest = {"protocol": 1, "actual_cgal_version": "6.2.1",
        "build": {"source_kind": "official_release",
                  "source_sha256": "b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf",
                  "test_stub": True}, "operations": operations}
    worker = directory / f"wave_worker_{mode}.py"
    source = f'''import json, pathlib, shutil, sys
manifest={manifest!r}
if "--manifest" in sys.argv:
 print(json.dumps(manifest)); raise SystemExit(0)
request=json.loads(sys.stdin.readline()); operation=request["operation"]; mode={mode!r}
output=pathlib.Path(request["output_dir"])
if operation == "mesh.simplify.edge_collapse":
 path=output/"geometry.off"; shutil.copyfile(request["inputs"][0]["path"],path)
 outputs=[{{"slot":"geometry","type":"TriangleSurfaceMesh","unit":request["inputs"][0]["unit"],"format":"off","path":str(path.resolve())}}]
 metrics={{"edges_removed":1}}
elif operation == "mesh.validate.simplification_integrity":
 if mode == "integrity_fail":
  print(json.dumps({{"protocol":1,"request_id":request["request_id"],"status":"error","outputs":[],"error":{{"class":"VALIDATION_FAILED","code":"PROTECTED_EDGE_CHANGED","message":"changed","recoverable":False,"suggested_operations":[]}}}})); raise SystemExit(0)
 report={{"status":"pass","valid":True,"triangulated":True,"self_intersection":False,"closedness_preserved":True,"component_topology_preserved":True,"protected_edges_preserved":True,"open_surface_winding_preserved":True}}
 path=output/"validation.json"; path.write_text(json.dumps(report))
 outputs=[{{"slot":"validation","type":"ValidationReport","unit":"none","format":"json","path":str(path.resolve())}}]; metrics=report
elif operation == "mesh.distance.symmetric_hausdorff":
 verdict="indeterminate" if mode == "indeterminate" else "pass"
 report={{"status":"pass" if verdict == "pass" else "fail","valid":verdict == "pass","verdict":verdict}}
 path=output/"validation.json"; path.write_text(json.dumps(report))
 outputs=[{{"slot":"validation","type":"ValidationReport","unit":"none","format":"json","path":str(path.resolve())}}]; metrics=report
else:
 raise SystemExit(2)
print(json.dumps({{"protocol":1,"request_id":request["request_id"],"status":"ok","outputs":outputs,"metrics":metrics,"diagnostics":[]}}))
'''
    worker.write_text(source, encoding="utf-8")
    return worker


class MasterCoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.points = self.root / "points.xyz"
        self.points.write_bytes(POINTS)
        self.resources = []

    def tearDown(self):
        for resource in reversed(self.resources):
            resource.close()
        self.temporary.cleanup()

    def runtime(self, mode: str = "ok") -> MasterRuntime:
        runtime = MasterRuntime(self.root / f"data-{mode}", worker=make_worker(self.root, mode),
                                require_memory_limit=False)
        self.resources.append(runtime)
        return runtime

    def test_registry_schema_and_search_hard_gates(self):
        registry = OperationRegistry()
        self.resources.append(registry)
        operation = registry.get("hull.convex_3")
        self.assertEqual(operation["revision"], 1)
        self.assertEqual(operation["status"], "VALIDATED")
        self.assertEqual(operation["sources"][0]["identifier"], "Convex_hull_3")
        found = registry.search("3d convex hull", input_types=["PointSet3"],
                                kernel="package_recommended", limit=2)
        self.assertEqual(found["candidates"][0]["operation_id"], "hull.convex_3")
        self.assertIn("FTS5 registry index matched", found["candidates"][0]["why"])
        blocked = registry.search("3d convex hull", input_types=["Polygon2"], limit=2)
        self.assertEqual(blocked["candidates"], [])

    def test_registry_rejects_malformed_output_at_load(self):
        source = Path("cgal_mcp/master/operations.json")
        document = json.loads(source.read_text(encoding="utf-8"))
        del document["operations"][0]["io"]["outputs"][0]["slot"]
        malformed = self.root / "operations.json"
        malformed.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(InvalidInput, "Invalid/duplicate output"):
            OperationRegistry(malformed)

    def test_import_preserves_source_bytes_and_persists(self):
        store = ArtifactStore(self.root / "store")
        artifact = store.import_file(self.points, "cm")
        self.assertEqual(artifact["type"], "PointSet3")
        self.assertEqual(store.managed_path(artifact["artifact_id"]).read_bytes(), POINTS)
        store.close()
        reopened = ArtifactStore(self.root / "store")
        self.assertEqual(reopened.inspect(artifact["artifact_id"])["sha256"], artifact["sha256"])
        reopened.close()

    def test_artifact_type_controls_unit_policy(self):
        report = self.root / "report.json"; report.write_text('{"status":"pass"}', encoding="utf-8")
        store = ArtifactStore(self.root / "units")
        self.resources.append(store)
        with self.assertRaises(InvalidInput):
            store.import_file(report, "garbage", artifact_type="ValidationReport")
        accepted = store.import_file(report, "none", artifact_type="ValidationReport")
        self.assertEqual(accepted["unit"], "none")
        with self.assertRaises(InvalidInput):
            store.import_file(self.points, "none")

    def test_inspector_response_is_bounded_before_parent_allocation(self):
        report = self.root / "large-report.json"
        report.write_text(json.dumps({"status": "pass", "padding": "x" * (3 * 1024 * 1024)}),
                          encoding="utf-8")
        store = ArtifactStore(self.root / "bounded-inspector")
        self.resources.append(store)
        with self.assertRaisesRegex(WorkerFailure, "exceeded 2 MiB"):
            store.import_file(report, "none", artifact_type="ValidationReport")

    def test_syntax_and_geometry_health_are_separate(self):
        defective = b"OFF\n4 2 0\n0 0 0\n1 0 0\n0 1 0\n0 0 1\n3 0 1 2\n3 0 1 2\n"
        result = inspect_bytes(defective, "off")
        self.assertEqual(result.geometry_type, "PolygonSoup3")
        self.assertEqual(result.metadata["duplicate_faces"], 1)
        self.assertEqual(result.properties["self_intersections"], "unknown")

    def test_plan_hash_units_and_validator_injection(self):
        runtime = self.runtime()
        artifact = runtime.artifact_import(str(self.points), "mm")
        request = {"operation_id": "hull.convex_3", "inputs": {"points": artifact["artifact_id"]}, "parameters": {}}
        first = runtime.plan(request)
        second = runtime.plan(request)
        self.assertEqual(first["plan_id"], second["plan_id"])
        self.assertEqual([step["operation"] for step in first["steps"]],
                         ["hull.convex_3", "hull.validate.convex_enclosure"])
        self.assertEqual(first["steps"][1]["inputs"]["source"]["sha256"], artifact["sha256"])
        length = normalize_quantities({"tolerance": {"value": 2, "unit": "cm"}}, "mm")
        self.assertEqual(length["tolerance"]["value"], 20.0)
        angle = normalize_quantities({"angle": {"value": 180, "unit": "deg"}}, "mm")
        self.assertAlmostEqual(angle["angle"]["value"], 3.141592653589793)
        for invalid in (True, float("nan"), float("inf")):
            with self.assertRaisesRegex(ValueError, "finite number"):
                normalize_quantities({"length": {"value": invalid, "unit": "cm"}}, "mm")

    def test_wave_a_policy_registry_units_and_dual_validator_bindings(self):
        mesh = self.root / "mesh.off"; mesh.write_text(TETRA, encoding="ascii")
        runtime = self.runtime()
        artifact = runtime.artifact_import(str(mesh), "mm")
        plan = runtime.plan({"operation_id": "mesh.simplify.edge_collapse",
            "inputs": [artifact["artifact_id"]], "parameters": {
                "stop": {"kind": "edge_length", "value": {"value": 0.1, "unit": "cm"}},
                "policy": "lindstrom_turk",
                "max_symmetric_deviation": {"value": 0.002, "unit": "m"},
                "hausdorff_error_bound": {"value": 0.01, "unit": "cm"}}})
        self.assertEqual([step["operation"] for step in plan["steps"]], [
            "mesh.simplify.edge_collapse", "mesh.validate.simplification_integrity",
            "mesh.distance.symmetric_hausdorff"])
        transform, integrity, hausdorff = plan["steps"]
        self.assertEqual(transform["parameters"]["stop"]["value"], {"value": 1.0, "unit": "mm"})
        self.assertEqual(transform["parameters"]["max_symmetric_deviation"], {"value": 2.0, "unit": "mm"})
        self.assertEqual(transform["parameters"]["hausdorff_error_bound"], {"value": 0.1, "unit": "mm"})
        self.assertEqual([item["path"] for item in transform["parameter_normalization"]],
                         ["stop.value", "max_symmetric_deviation", "hausdorff_error_bound"])
        self.assertEqual(integrity["parameters"], {"preserve_border": True, "constrained_edges": []})
        self.assertEqual(hausdorff["parameters"], {
            "tolerance": {"value": 2.0, "unit": "mm"},
            "error_bound": {"value": 0.1, "unit": "mm"}})
        self.assertEqual({item["bound_from"] for item in hausdorff["parameter_normalization"]},
                         {"max_symmetric_deviation", "hausdorff_error_bound"})
        self.assertEqual({item["group"] for item in transform["policies"]},
                         {"cost_placement", "stop_predicate", "wrapper"})
        described = runtime.capabilities_describe("mesh.simplify.edge_collapse")
        self.assertNotIn("policy_inventory", described)
        self.assertEqual(len(described["policies"]), 17)
        self.assertEqual(sum(item["status"] == "BLOCKED" for item in described["policies"]), 1)

    def test_wave_a_validator_parameters_cannot_be_omitted_or_rebound(self):
        mesh = self.root / "mesh.off"; mesh.write_text(TETRA, encoding="ascii")
        runtime = self.runtime()
        artifact = runtime.artifact_import(str(mesh), "mm")
        base = {"stop": {"kind": "edge_ratio", "value": 0.8},
                "policy": "gh_plane", "max_symmetric_deviation": {"value": 1, "unit": "mm"},
                "hausdorff_error_bound": {"value": 0.01, "unit": "mm"}}
        missing = dict(base); missing.pop("max_symmetric_deviation")
        with self.assertRaisesRegex(InvalidInput, "lacks"):
            runtime.plan({"operation_id": "mesh.simplify.edge_collapse",
                          "inputs": [artifact["artifact_id"]], "parameters": missing})
        steps = [
            {"id": "simplify", "operation": "mesh.simplify.edge_collapse",
             "inputs": {"geometry": artifact["artifact_id"]}, "parameters": base},
            {"id": "integrity", "operation": "mesh.validate.simplification_integrity",
             "inputs": {"candidate": {"step": "simplify", "slot": "geometry"},
                        "source": artifact["artifact_id"]},
             "parameters": {"preserve_border": True, "constrained_edges": []},
             "validates": "simplify"},
            {"id": "distance", "operation": "mesh.distance.symmetric_hausdorff",
             "inputs": {"reference": artifact["artifact_id"],
                        "candidate": {"step": "simplify", "slot": "geometry"}},
             "parameters": {"tolerance": {"value": 99, "unit": "mm"},
                            "error_bound": {"value": 0.01, "unit": "mm"}},
             "validates": "simplify"}]
        with self.assertRaisesRegex(InvalidInput, "does not bind exactly"):
            runtime.plan({"steps": steps})
        bad = dict(base); bad["max_symmetric_deviation"] = {
            "value": 1, "unit": "mm", "spoofed_history": []}
        with self.assertRaisesRegex(InvalidInput, "only finite value and unit"):
            runtime.plan({"operation_id": "mesh.simplify.edge_collapse",
                          "inputs": [artifact["artifact_id"]], "parameters": bad})
        overflow = dict(base); overflow["max_symmetric_deviation"] = {
            "value": 1e308, "unit": "m"}
        with self.assertRaisesRegex(InvalidInput, "non-finite"):
            runtime.plan({"operation_id": "mesh.simplify.edge_collapse",
                          "inputs": [artifact["artifact_id"]], "parameters": overflow})
        metre_artifact = runtime.artifact_import(str(mesh), "m")
        underflow = dict(base); underflow["hausdorff_error_bound"] = {
            "value": 5e-324, "unit": "mm"}
        with self.assertRaisesRegex(InvalidInput, "must exceed"):
            runtime.plan({"operation_id": "mesh.simplify.edge_collapse",
                          "inputs": [metre_artifact["artifact_id"]], "parameters": underflow})

    def test_wave_a_manifest_metadata_and_bindings_are_gated(self):
        registry = OperationRegistry(); self.resources.append(registry)
        operation = registry.get("mesh.simplify.edge_collapse")
        contract = operation["worker_manifest"]
        info = dict(contract["info"])
        info["validator_parameter_bindings"] = {
            validator: {target: binding["parameter"]
                        for target, binding in recipe["parameters"].items()}
            for validator, recipe in operation["validation"]["bindings"].items()}
        actual = {"id": operation["id"], "revision": 1, "input_types": ["TriangleSurfaceMesh"],
                  "output_type": "TriangleSurfaceMesh", "role": "transform",
                  "supported_kernels": ["package_recommended"],
                  "effective_kernel": contract["effective_kernel"],
                  "dependencies": operation["dependencies"], "info": info}
        manifest = {"protocol": 1, "actual_cgal_version": "6.2.1",
                    "build": {"source_kind": "official_release",
                              "source_sha256": "b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf"},
                    "operations": [actual]}
        registry.verify_manifest(manifest, operation["id"])
        bad = json.loads(json.dumps(manifest))
        bad["operations"][0]["info"]["policies"].remove("gh_plane")
        with self.assertRaisesRegex(InvalidInput, "metadata disagrees"):
            registry.verify_manifest(bad, operation["id"])
        bad = json.loads(json.dumps(manifest))
        bad["operations"][0]["info"]["validator_parameter_bindings"][
            "mesh.distance.symmetric_hausdorff"]["tolerance"] = "hausdorff_error_bound"
        with self.assertRaisesRegex(InvalidInput, "bindings disagree"):
            registry.verify_manifest(bad, operation["id"])

    def test_wave_a_publication_requires_both_validator_passes(self):
        async def run(mode: str) -> tuple[MasterRuntime, dict]:
            mesh = self.root / f"mesh-{mode}.off"; mesh.write_text(TETRA, encoding="ascii")
            runtime = MasterRuntime(self.root / f"wave-{mode}",
                worker=make_wave_worker(self.root, mode), require_memory_limit=False)
            self.resources.append(runtime)
            artifact = runtime.artifact_import(str(mesh), "mm")
            plan = runtime.plan({"operation_id": "mesh.simplify.edge_collapse",
                "inputs": [artifact["artifact_id"]], "parameters": {
                    "stop": {"kind": "edge_ratio", "value": 0.8}, "policy": "lindstrom_turk",
                    "max_symmetric_deviation": {"value": 2, "unit": "mm"},
                    "hausdorff_error_bound": {"value": 0.01, "unit": "mm"}}})
            self.assertEqual(len([step for step in plan["steps"] if step["role"] == "validator"]), 2)
            queued = await runtime.execute(plan["plan_id"])
            await runtime.tasks[queued["job_id"]]
            return runtime, runtime.job_status(queued["job_id"])
        async def scenario():
            passed_runtime, passed = await run("pass")
            self.assertEqual((passed["state"], passed["validation_status"]), ("succeeded", "passed"))
            self.assertEqual(len(passed["validation"]), 2)
            self.assertEqual(passed_runtime.store.counts()["artifacts"], 2)
            for mode in ("integrity_fail", "indeterminate"):
                failed_runtime, failed = await run(mode)
                self.assertEqual((failed["state"], failed["execution_status"], failed["validation_status"]),
                                 ("rejected", "succeeded", "failed"))
                self.assertEqual(failed_runtime.store.counts()["artifacts"], 1)
                self.assertFalse(failed.get("outputs"))
        asyncio.run(scenario())

    def test_unknown_operation_is_rejected_before_worker(self):
        runtime = MasterRuntime(self.root / "unknown", worker=self.root / "does-not-exist.exe",
                                require_memory_limit=False)
        self.resources.append(runtime)
        artifact = runtime.artifact_import(str(self.points), "mm")
        with self.assertRaises(UnsupportedOperation):
            runtime.plan({"operation_id": "invented.dynamic_cpp", "inputs": [artifact["artifact_id"]]})
        self.assertEqual(runtime.store.counts()["jobs"], 0)

    def test_explicit_plan_applies_dependency_kernel_and_license_gates(self):
        runtime = self.runtime()
        artifact = runtime.artifact_import(str(self.points), "mm")
        base = {"operation_id": "hull.convex_3", "inputs": [artifact["artifact_id"]], "parameters": {}}
        with self.assertRaises(InvalidInput):
            runtime.plan({**base, "policy": {"kernel": "inexact"}})
        with self.assertRaisesRegex(PreconditionFailure, "Dependencies are unavailable"):
            runtime.plan({**base, "policy": {"dependencies": ["Convex_hull_3"]}})
        with self.assertRaisesRegex(PreconditionFailure, "License policy excludes"):
            runtime.plan({**base, "policy": {"allowed_licenses": ["MIT"]}})
        explicit = {"steps": [{"id": "make", "operation": "hull.convex_3",
                    "inputs": {"points": artifact["artifact_id"]}, "parameters": {}}]}
        with self.assertRaisesRegex(PreconditionFailure, "License policy excludes"):
            runtime.plan({**explicit, "policy": {"allowed_licenses": ["MIT"]}})
        with self.assertRaisesRegex(PreconditionFailure, "Dependencies are unavailable"):
            runtime.plan({**explicit, "policy": {"dependencies": []}})

    def test_cycle_rejected(self):
        steps = [
            {"id": "a", "inputs": {"x": {"step": "b", "slot": "geometry"}}},
            {"id": "b", "inputs": {"x": {"step": "a", "slot": "geometry"}}},
        ]
        with self.assertRaises(InvalidInput):
            _acyclic(steps)

    def test_explicit_dag_cannot_fake_or_rebind_required_validator(self):
        runtime = self.runtime()
        source = runtime.artifact_import(str(self.points), "mm")
        mesh_path = self.root / "existing.off"; mesh_path.write_text(TETRA, encoding="utf-8")
        unrelated_mesh = runtime.artifact_import(str(mesh_path), "mm", artifact_type="TriangleSurfaceMesh")
        other_points_path = self.root / "other.xyz"; other_points_path.write_bytes(POINTS.replace(b"0.2", b"0.3"))
        other_source = runtime.artifact_import(str(other_points_path), "mm")
        transform = {"id": "make", "operation": "hull.convex_3",
                     "inputs": {"points": source["artifact_id"]}, "parameters": {}}
        fake = {"id": "check", "operation": "hull.validate.convex_enclosure", "validates": "make",
                "inputs": {"geometry": unrelated_mesh["artifact_id"], "source": source["artifact_id"]},
                "parameters": {}}
        with self.assertRaisesRegex(InvalidInput, "does not bind exactly"):
            runtime.plan({"steps": [transform, fake]})
        wrong_source = {**fake, "inputs": {"geometry": {"step": "make", "slot": "geometry"},
                                            "source": other_source["artifact_id"]}}
        with self.assertRaisesRegex(InvalidInput, "does not bind exactly"):
            runtime.plan({"steps": [transform, wrong_source]})

    def test_explicit_dag_uses_parameter_schema_and_exact_validator_once(self):
        runtime = self.runtime()
        source = runtime.artifact_import(str(self.points), "mm")
        with self.assertRaisesRegex(InvalidInput, "Unknown parameters"):
            runtime.plan({"steps": [{"id": "make", "operation": "hull.convex_3",
                "inputs": {"points": source["artifact_id"]}, "parameters": {"bogus": 1}}]})
        plan = runtime.plan({"steps": [
            {"id": "make", "operation": "hull.convex_3",
             "inputs": {"points": source["artifact_id"]}, "parameters": {}},
            {"id": "check", "operation": "hull.validate.convex_enclosure", "validates": "make",
             "inputs": {"geometry": {"step": "make", "slot": "geometry"},
                        "source": source["artifact_id"]}, "parameters": {}}
        ]})
        self.assertEqual([step["id"] for step in plan["steps"]], ["make", "check"])

    def test_success_requires_validator_then_publishes(self):
        async def scenario():
            runtime = self.runtime()
            source = runtime.artifact_import(str(self.points), "mm")
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]], "parameters": {}})
            queued = await runtime.execute(plan["plan_id"])
            await runtime.tasks[queued["job_id"]]
            status = runtime.job_status(queued["job_id"])
            self.assertEqual(status["state"], "succeeded")
            self.assertEqual(status["execution_status"], "succeeded")
            self.assertEqual(status["validation_status"], "passed")
            self.assertEqual(len(status["outputs"]), 1)
            self.assertEqual(status["outputs"][0]["type"], "TriangleSurfaceMesh")
            self.assertEqual(runtime.store.counts()["provenance"], 1)
        asyncio.run(scenario())

    def test_same_output_bytes_keep_distinct_artifact_lineage(self):
        async def scenario():
            runtime = self.runtime()
            source = runtime.artifact_import(str(self.points), "mm")
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]], "parameters": {}})
            statuses = []
            for _ in range(2):
                queued = await runtime.execute(plan["plan_id"])
                await runtime.tasks[queued["job_id"]]
                statuses.append(runtime.job_status(queued["job_id"]))
            first, second = (status["outputs"][0] for status in statuses)
            self.assertNotEqual(first["artifact_id"], second["artifact_id"])
            self.assertEqual(first["sha256"], second["sha256"])
            for status, output in zip(statuses, (first, second)):
                inspected = runtime.artifact_inspect(output["artifact_id"])
                self.assertEqual(inspected["producer"]["job_id"], status["job_id"])
                self.assertEqual(inspected["provenance"][0]["job_id"], status["job_id"])
            self.assertEqual(runtime.store.counts()["blobs"], 2)  # source + deduplicated hull bytes
            self.assertEqual(runtime.store.counts()["artifacts"], 3)
        asyncio.run(scenario())

    def test_terminal_job_failure_rolls_back_artifact_and_provenance(self):
        async def scenario():
            runtime = self.runtime()
            source = runtime.artifact_import(str(self.points), "mm")
            with runtime.store._lock:
                runtime.store._db.execute("""CREATE TRIGGER reject_success BEFORE UPDATE OF state ON jobs
                    WHEN NEW.state='succeeded' BEGIN SELECT RAISE(ABORT, 'injected terminal failure'); END""")
                runtime.store._db.commit()
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]], "parameters": {}})
            queued = await runtime.execute(plan["plan_id"])
            await runtime.tasks[queued["job_id"]]
            status = runtime.job_status(queued["job_id"])
            self.assertEqual(status["state"], "failed")
            self.assertEqual(runtime.store.counts()["artifacts"], 1)
            self.assertEqual(runtime.store.counts()["provenance"], 0)
            self.assertEqual(runtime.store.counts()["blobs"], 1)
        asyncio.run(scenario())

    def test_malformed_output_is_quarantined_and_not_published(self):
        async def scenario():
            runtime = self.runtime("malformed")
            source = runtime.artifact_import(str(self.points), "mm")
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]], "parameters": {}})
            queued = await runtime.execute(plan["plan_id"])
            await runtime.tasks[queued["job_id"]]
            status = runtime.job_status(queued["job_id"])
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["error"]["class"], "worker_protocol")
            self.assertTrue((runtime.store.quarantine_root / queued["job_id"]).is_dir())
            self.assertEqual(runtime.store.counts()["artifacts"], 1)
        asyncio.run(scenario())

    def test_manifest_registry_mismatch_is_rejected_before_dispatch(self):
        async def scenario():
            runtime = self.runtime("manifest_wrong")
            source = runtime.artifact_import(str(self.points), "mm")
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]], "parameters": {}})
            queued = await runtime.execute(plan["plan_id"])
            await runtime.tasks[queued["job_id"]]
            status = runtime.job_status(queued["job_id"])
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["error"]["code"], "manifest_registry_mismatch")
            self.assertEqual(runtime.store.counts()["artifacts"], 1)
        asyncio.run(scenario())

    def test_worker_cannot_change_declared_output_unit(self):
        async def scenario():
            runtime = self.runtime("wrong_unit")
            source = runtime.artifact_import(str(self.points), "mm")
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]], "parameters": {}})
            queued = await runtime.execute(plan["plan_id"])
            await runtime.tasks[queued["job_id"]]
            status = runtime.job_status(queued["job_id"])
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["error"]["code"], "worker_output_unit")
            self.assertEqual(runtime.store.counts()["artifacts"], 1)
        asyncio.run(scenario())

    def test_enforced_memory_failure_has_resource_limit_taxonomy(self):
        async def scenario():
            runtime = MasterRuntime(self.root / "data-oom", worker=make_worker(self.root, "oom"),
                                    require_memory_limit=True)
            self.resources.append(runtime)
            source = runtime.artifact_import(str(self.points), "mm")
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]], "parameters": {}})
            queued = await runtime.execute(plan["plan_id"], memory_mb=64)
            await runtime.tasks[queued["job_id"]]
            status = runtime.job_status(queued["job_id"])
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["error"]["class"], "resource_limit")
            self.assertEqual(status["error"]["code"], "memory_limit")
        asyncio.run(scenario())

    def test_worker_validation_error_class_is_normalized_and_preserved(self):
        async def scenario():
            runtime = self.runtime("validator_error")
            source = runtime.artifact_import(str(self.points), "mm")
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]], "parameters": {}})
            queued = await runtime.execute(plan["plan_id"])
            await runtime.tasks[queued["job_id"]]
            status = runtime.job_status(queued["job_id"])
            self.assertEqual(status["state"], "rejected")
            self.assertEqual(status["execution_status"], "succeeded")
            self.assertEqual(status["validation_status"], "failed")
            self.assertEqual(status["error"]["class"], "validation_failure")
            self.assertEqual(status["error"]["source_class"], "VALIDATION_FAILED")
        asyncio.run(scenario())

    def test_incomplete_validator_report_rejects_computed_geometry(self):
        async def scenario():
            runtime = self.runtime("incomplete")
            source = runtime.artifact_import(str(self.points), "mm")
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]], "parameters": {}})
            queued = await runtime.execute(plan["plan_id"])
            await runtime.tasks[queued["job_id"]]
            status = runtime.job_status(queued["job_id"])
            self.assertEqual(status["state"], "rejected")
            self.assertEqual(status["execution_status"], "succeeded")
            self.assertEqual(status["validation_status"], "failed")
            self.assertIn("required checks", status["error"]["message"])
            self.assertEqual(runtime.store.counts()["artifacts"], 1)
        asyncio.run(scenario())

    def test_validation_report_is_bounded_before_json_parse(self):
        async def scenario():
            runtime = self.runtime("huge_report")
            source = runtime.artifact_import(str(self.points), "mm")
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]]})
            queued = await runtime.execute(plan["plan_id"])
            await asyncio.wait_for(runtime.tasks[queued["job_id"]], timeout=10)
            status = runtime.job_status(queued["job_id"])
            self.assertEqual(status["state"], "rejected")
            self.assertEqual(status["error"]["code"], "validation_report_too_large")
            self.assertEqual(status["execution_status"], "succeeded")
            self.assertEqual(status["validation_status"], "failed")
        asyncio.run(scenario())

    def test_cancel_persists_terminal_state(self):
        async def scenario():
            runtime = self.runtime("slow")
            source = runtime.artifact_import(str(self.points), "mm")
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]], "parameters": {}})
            queued = await runtime.execute(plan["plan_id"])
            await asyncio.sleep(0.15)
            status = await runtime.job_cancel(queued["job_id"])
            self.assertEqual(status["state"], "cancelled")
            self.assertEqual(status["execution_status"], "cancelled")
        asyncio.run(scenario())

    def test_immediate_queued_cancel_cannot_strand_pending_job(self):
        async def scenario():
            runtime = self.runtime("slow")
            source = runtime.artifact_import(str(self.points), "mm")
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [source["artifact_id"]], "parameters": {}})
            for _ in range(5):
                queued = await runtime.execute(plan["plan_id"])
                status = await runtime.job_cancel(queued["job_id"])
                self.assertEqual(status["state"], "cancelled")
                self.assertEqual(status["execution_status"], "cancelled")
        asyncio.run(scenario())

    def test_restart_marks_inflight_failed_without_repeating(self):
        store = ArtifactStore(self.root / "recovery")
        plan = {"plan_id": "plan_test", "immutable": True}
        store.persist_plan(plan)
        store.create_job("job_test", "plan_test")
        staging = store.staging_root / "job_test"; staging.mkdir(); (staging / "candidate.bin").write_bytes(b"candidate")
        store.close()
        recovered = ArtifactStore(self.root / "recovery")
        status = recovered.get_job("job_test")
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["execution_status"], "interrupted")
        self.assertEqual(status["quarantine"], "job_test")
        self.assertNotIn(str(recovered.root), json.dumps(status))
        self.assertFalse(staging.exists())
        self.assertTrue((recovered.quarantine_root / "job_test" / "candidate.bin").is_file())
        recovered.close()

    def test_export_is_exclusive(self):
        runtime = self.runtime()
        artifact = runtime.artifact_import(str(self.points), "m")
        destination = self.root / "export.xyz"
        runtime.artifact_export(artifact["artifact_id"], str(destination))
        self.assertEqual(destination.read_bytes(), POINTS)
        with self.assertRaises(FileExistsError):
            runtime.artifact_export(artifact["artifact_id"], str(destination))

    def test_file_root_allowlist_gates_http_style_access(self):
        allowed = self.root / "allowed"; allowed.mkdir()
        inside = allowed / "inside.xyz"; inside.write_bytes(POINTS)
        runtime = MasterRuntime(self.root / "gated-data", worker=make_worker(self.root),
                                require_memory_limit=False, allowed_file_roots=[allowed])
        self.resources.append(runtime)
        with self.assertRaisesRegex(InvalidInput, "outside configured"):
            runtime.artifact_import(str(self.points), "mm")
        artifact = runtime.artifact_import(str(inside), "mm")
        with self.assertRaisesRegex(InvalidInput, "outside configured"):
            runtime.artifact_export(artifact["artifact_id"], str(self.root / "outside.xyz"))

    def test_mcp_has_exact_public_tool_surface(self):
        async def scenario():
            tools = await create_server(self.runtime()).list_tools()
            self.assertEqual({tool.name for tool in tools}, {
                "cgal_capabilities_search", "cgal_capabilities_describe", "cgal_plan",
                "cgal_execute", "cgal_validate", "cgal_artifact_inspect", "cgal_docs_search",
                "cgal_system_health", "cgal_artifact_import", "cgal_artifact_export",
                "cgal_job_status", "cgal_job_cancel"})
        asyncio.run(scenario())

    def test_health_reports_configured_concurrency_without_absolute_roots(self):
        async def scenario():
            runtime = MasterRuntime(self.root / "health", worker=make_worker(self.root),
                                    concurrency=1, require_memory_limit=False)
            self.resources.append(runtime)
            health = await runtime.system_health()
            self.assertEqual(health["concurrency"], 1)
            self.assertNotIn("registry_paths", health)
            self.assertNotIn("roots", health["file_access"])
        asyncio.run(scenario())

    def test_docs_search_uses_generated_pinned_catalog(self):
        runtime = self.runtime()
        result = runtime.docs_search("convex hull", 5)
        self.assertFalse(result["legacy_api_index_used"])
        self.assertEqual(result["index_scope"], "pinned_generated_catalog")
        self.assertTrue(result["results"])
        self.assertTrue(all(item["scope"] == "reference" and item["executable"] is False
                            for item in result["results"]))
        if result.get("index_backend"):
            self.assertEqual(result["index_backend"], "sqlite-fts5-trigram")
        else:
            self.assertTrue(any(item["source"] == "docs_index.jsonl" for item in result["results"]))
        runtime.docs_index = None
        fallback = runtime.docs_search("convex hull", 5)
        self.assertTrue(fallback["results"])
        self.assertTrue(all(item["scope"] == "reference" and item["executable"] is False
                            for item in fallback["results"]))

    def test_docs_sqlite_metadata_mismatch_fails_closed(self):
        database = self.root / "bad-index.sqlite"
        connection = sqlite3.connect(database)
        connection.executescript("""CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE documents(id INTEGER PRIMARY KEY,kind TEXT,package_id TEXT,status TEXT,title TEXT,source_path TEXT,source_sha256 TEXT,aliases TEXT,content TEXT);
            CREATE VIRTUAL TABLE documents_fts USING fts5(title,aliases,content,tokenize='trigram');""")
        metadata = {"schema_version": 1, "cgal_version": "0.0", "catalog_version": "wrong",
                    "package_count": 0, "fts_tokenizer": "trigram", "provenance": {"mode": "official"}}
        connection.executemany("INSERT INTO metadata VALUES(?,?)",
                               [(key, json.dumps(value)) for key, value in metadata.items()])
        connection.commit(); connection.close()
        runtime = MasterRuntime(self.root / "bad-docs", worker=make_worker(self.root),
                                require_memory_limit=False, docs_index=database)
        self.resources.append(runtime)
        with self.assertRaisesRegex(InvalidInput, "version disagrees"):
            runtime.docs_search("convex hull")


if __name__ == "__main__":
    unittest.main()
