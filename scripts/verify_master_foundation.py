"""Run the actual first Master slice and write portable, measured evidence."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cgal_mcp.master.runtime import MasterRuntime


async def verify() -> dict:
    fixture = REPO / "tests/fixtures/master/cube_with_interior.xyz"
    source_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="cgal-master-acceptance-") as folder:
        root = Path(folder)
        runtime = MasterRuntime(root / "store")
        try:
            imported = runtime.artifact_import(str(fixture), "mm")
            artifact_id = imported["artifact_id"]
            plan = runtime.plan({"operation_id": "hull.convex_3", "inputs": [artifact_id]})
            assert any(s["operation"] == "hull.validate.convex_enclosure" for s in plan["steps"])
            job = await runtime.execute(plan["plan_id"])
            deadline = asyncio.get_running_loop().time() + 60
            while True:
                result = runtime.job_status(job["job_id"])
                if result["state"] not in ("queued", "running"):
                    break
                if asyncio.get_running_loop().time() > deadline:
                    await runtime.job_cancel(job["job_id"])
                    raise TimeoutError("Foundation acceptance exceeded 60 seconds")
                await asyncio.sleep(0.05)
            assert result["state"] == "succeeded", result
            assert result["execution_status"] == "succeeded", result
            assert result["validation_status"] == "passed", result
            outputs = result["outputs"]
            assert len(outputs) == 1 and outputs[0]["type"] == "TriangleSurfaceMesh", outputs
            output = runtime.artifact_inspect(outputs[0]["artifact_id"])
            assert output["unit"] == "mm", output
            health = await runtime.system_health()
            manifest = await runtime.supervisor.manifest("hull.convex_3")
            assert manifest["actual_cgal_version"] == "6.2.1", manifest
            assert manifest["build"]["source_kind"] == "official_release", manifest
            assert hashlib.sha256(fixture.read_bytes()).hexdigest() == source_hash
            stored_hash = output["sha256"]
            output_id = output["artifact_id"]
            validation = result["validation"]
            resource_mode = runtime.supervisor.resource_limit_mode
            assert resource_mode in ("windows_job_object", "posix_rlimit_as"), resource_mode
        finally:
            runtime.close()
        reopened = MasterRuntime(root / "store")
        try:
            assert reopened.artifact_inspect(artifact_id)["sha256"] == source_hash
            restored = reopened.artifact_inspect(output_id)
            assert restored["sha256"] == stored_hash
            assert reopened.job_status(job["job_id"])["state"] == "succeeded"
            assert reopened.store.get_plan(plan["plan_id"])["plan_id"] == plan["plan_id"]
        finally:
            reopened.close()
    # Do not publish host filesystem paths, job IDs, timestamps or user geometry.
    return {
        "schema_version": 1, "generator": "master-foundation-acceptance", "status": "pass",
        "scope": "first_generic_hull_slice", "standalone_accepted": False,
        "requirements": [],
        "fixture": {"path": "tests/fixtures/master/cube_with_interior.xyz", "sha256": source_hash},
        "worker_manifest": manifest,
        "worker_manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
        "input_hashes": [source_hash], "output_hashes": [stored_hash],
        "operations": [s["operation"] for s in plan["steps"]],
        "validation_reports": [v["report"] for v in validation],
        "checks": {"automatic_validator": True, "input_unchanged": True,
                   "artifact_plan_job_persistence": True, "required_resource_limit": resource_mode},
        "coverage_note": "This slice does not complete the combined 2D/3D hull requirement or any major family.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(verify())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Master real hull, mandatory validation and persistence: PASS")


if __name__ == "__main__":
    main()
