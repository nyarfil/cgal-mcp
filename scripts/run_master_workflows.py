"""Run the declared multi-operation workflow set through the real Master runtime.

Every workflow in ``docs/master/workflows.json`` is planned by the real
``PlanBuilder`` (explicit typed DAG, mandatory validator injection), executed by
the real supervisor against the native worker, and recorded as deterministic
evidence: declared DAG, input hashes, planned steps, published artifact types,
units and hashes, validator verdicts and the exact failure stage/code for the
negative cases. Nothing here is mocked. The evaluator in
``scripts/master_acceptance.py`` re-derives every verdict from the record.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

SCRIPT_REPO = Path(__file__).resolve().parents[1]
if str(SCRIPT_REPO) not in sys.path:
    sys.path.insert(0, str(SCRIPT_REPO))

from cgal_mcp.master.errors import MasterError  # noqa: E402
from cgal_mcp.master.runtime import MasterRuntime  # noqa: E402

REPO = SCRIPT_REPO
SPEC_PATH = "docs/master/workflows.json"
EVIDENCE_PATH = "docs/master/evidence/workflows.json"
GENERATOR = "master-workflow-evidence"
BINDING_SOURCES = {
    "spec_sha256": SPEC_PATH,
    "operations_sha256": "cgal_mcp/master/operations.json",
    "policies_sha256": "cgal_mcp/master/policies.json",
    "planner_sha256": "cgal_mcp/master/planner.py",
    "runtime_sha256": "cgal_mcp/master/runtime.py",
    "generator_sha256": "scripts/run_master_workflows.py",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def load_spec(root: Path = REPO) -> dict:
    return json.loads((root / SPEC_PATH).read_text(encoding="utf-8"))


def bindings(root: Path = REPO) -> dict[str, str]:
    return {key: sha256_file(root / rel) for key, rel in BINDING_SOURCES.items()}


def _error(exc: MasterError) -> dict:
    return {"class": exc.failure_class, "code": exc.code}


def _resolve_dag(runtime: MasterRuntime, workflow: dict, spec: dict, root: Path,
                 artifacts: dict[str, dict]) -> list[dict]:
    """Substitute declared fixture references with imported artifact ids."""
    steps = []
    for declared in workflow["steps"]:
        step = {key: value for key, value in declared.items() if key != "inputs"}
        step["inputs"] = {}
        for slot, binding in declared["inputs"].items():
            if isinstance(binding, str) and binding.startswith("fixture:"):
                name = binding[len("fixture:"):]
                step["inputs"][slot] = artifacts[name]["artifact_id"]
            else:
                step["inputs"][slot] = binding
        steps.append(step)
    return steps


def _import_fixtures(runtime: MasterRuntime, workflow: dict, spec: dict,
                     root: Path) -> tuple[dict[str, dict], dict | None]:
    artifacts: dict[str, dict] = {}
    for name in workflow.get("fixtures", []):
        fixture = spec["fixtures"][name]
        path = root / fixture["path"]
        if sha256_file(path) != fixture["sha256"]:
            raise RuntimeError(f"Fixture {name} does not match its declared hash")
        try:
            artifacts[name] = runtime.artifact_import(str(path), fixture["unit"],
                                                      artifact_type=fixture["type"])
        except MasterError as exc:
            return artifacts, {"stage": "import", "fixture": name, **_error(exc)}
    return artifacts, None


def _plan_record(plan: dict) -> dict:
    steps = [
        {"id": step["id"], "operation": step["operation"], "role": step["role"],
         "validates": step.get("validates"),
         "inputs": {slot: ({"step": binding["step"], "slot": binding["slot"]}
                           if "step" in binding else {"artifact_sha256": binding["sha256"]})
                    for slot, binding in sorted(step["inputs"].items())},
         "input_types": {slot: binding["type"] for slot, binding in sorted(step["inputs"].items())},
         "input_units": {slot: binding["unit"] for slot, binding in sorted(step["inputs"].items())},
         "output_types": [output["type"] for output in step["outputs"]]}
        for step in plan["steps"]]
    # Plan identifiers embed per-run artifact ids, so the evidence binds the typed step list instead.
    return {"steps": steps, "steps_sha256": canonical_sha(steps)}


async def run_workflow(runtime: MasterRuntime, workflow: dict, spec: dict, root: Path) -> dict:
    record: dict[str, Any] = {
        "id": workflow["id"], "families": workflow["families"],
        "category": workflow["category"], "expect": workflow["expect"],
        "declared_dag": [{"id": step["id"], "operation": step["operation"],
                          "inputs": {slot: binding for slot, binding in sorted(step["inputs"].items())}}
                         for step in workflow["steps"]],
        "fixtures": {name: {"sha256": spec["fixtures"][name]["sha256"],
                            "type": spec["fixtures"][name]["type"],
                            "unit": spec["fixtures"][name]["unit"]}
                     for name in workflow.get("fixtures", [])},
    }
    artifacts, failure = _import_fixtures(runtime, workflow, spec, root)
    if failure:
        record["outcome"] = {"state": "refused", **failure}
        record["store_published_delta"] = 0
        return record
    base_artifacts = runtime.store.counts()["artifacts"]
    try:
        plan = runtime.plan({"steps": _resolve_dag(runtime, workflow, spec, root, artifacts),
                             **({"policy": workflow["policy"]} if "policy" in workflow else {})})
    except MasterError as exc:
        record["outcome"] = {"state": "refused", "stage": "plan", **_error(exc)}
        record["store_published_delta"] = runtime.store.counts()["artifacts"] - base_artifacts
        if os.environ.get("MASTER_WF_DEBUG"):
            print("DEBUG", workflow["id"], exc.message, file=sys.stderr)
        return record
    record["plan"] = _plan_record(plan)
    limits = workflow.get("limits", {})
    try:
        job = await runtime.execute(plan["plan_id"], **limits)
    except MasterError as exc:
        record["outcome"] = {"state": "refused", "stage": "execute_limits", **_error(exc)}
        record["store_published_delta"] = runtime.store.counts()["artifacts"] - base_artifacts
        return record
    await runtime.tasks[job["job_id"]]
    detail = runtime.store.get_job(job["job_id"])
    outcome: dict[str, Any] = {"state": detail["state"],
                               "execution_status": detail["execution_status"],
                               "validation_status": detail["validation_status"]}
    if detail.get("error"):
        outcome["stage"] = "execute"
        outcome.update({"class": detail["error"]["class"], "code": detail["error"]["code"]})
        if os.environ.get("MASTER_WF_DEBUG"):
            print("DEBUG", workflow["id"], detail["error"]["message"], file=sys.stderr)
    record["outcome"] = outcome
    if detail["state"] == "succeeded":
        record["outputs"] = [
            {"type": item["type"], "unit": item["unit"], "format": item["format"],
             "sha256": item["sha256"], "size": item["size"]}
            for item in detail["outputs"]]
    validators = []
    for entry in detail.get("validation", []):
        report = entry["report"]
        validators.append({"step_id": entry["step_id"], "operation": entry["operation"],
                           "status": report.get("status"),
                           "report_sha256": canonical_sha(report)})
    record["validators"] = validators
    record["store_published_delta"] = runtime.store.counts()["artifacts"] - base_artifacts
    return record


def _run_sync(workflows: list[dict], spec: dict, root: Path, worker: Path,
              work_dir: Path) -> list[dict]:
    async def go() -> list[dict]:
        results = []
        for workflow in workflows:
            store = work_dir / f"store-{workflow['id']}"
            if store.exists():
                shutil.rmtree(store)
            runtime = MasterRuntime(store, worker=worker, require_memory_limit=False)
            try:
                results.append(await run_workflow(runtime, workflow, spec, root))
            finally:
                runtime.close()
        return results
    return asyncio.run(go())


def measure(root: Path = REPO, worker: Path | None = None, work_dir: Path | None = None,
            only: list[str] | None = None) -> dict:
    spec = load_spec(root)
    worker = worker or root / "build-master/Release/cgal-master-worker.exe"
    workflows = [w for w in spec["workflows"] if not only or w["id"] in only]
    with tempfile.TemporaryDirectory(prefix="master-workflows-") as temporary:
        base = work_dir or Path(temporary)
        base.mkdir(parents=True, exist_ok=True)
        cases = _run_sync(workflows, spec, root, worker, base)
    return {"generator": GENERATOR, "schema_version": 1, "bindings": bindings(root),
            "worker_sha256": sha256_file(worker), "count": len(cases), "cases": cases}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--only", action="append")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    evidence = measure(REPO, args.worker, args.work_dir, args.only)
    if args.summary:
        for case in evidence["cases"]:
            print(case["id"], case["outcome"], [v["status"] for v in case.get("validators", [])])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=1, sort_keys=True) + "\n",
                               encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
