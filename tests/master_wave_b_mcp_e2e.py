"""Official MCP client -> Wave B point-set operations -> mandatory validators."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import Client, StdioServerParameters

from tests.master_mcp_e2e import worker_path


SPECIFIC_VALIDATOR = {
    "pointset.remove_outliers": "pointset.validate.subset",
    "pointset.simplify.grid": "pointset.validate.subset",
    "pointset.simplify.random": "pointset.validate.subset",
    "pointset.simplify.hierarchy": "pointset.validate.subset",
    "pointset.smooth.jet": "pointset.validate.smoothed",
    "pointset.normals.estimate": "pointset.validate.normals_estimated",
    "pointset.normals.orient_mst": "pointset.validate.normals_oriented",
}


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode not in {"auto", "legacy"}:
        raise SystemExit("mode must be auto or legacy")
    executable = worker_path()
    if not executable.is_file():
        raise SystemExit(f"Master worker is missing: {executable}")
    fixtures = Path("tests/fixtures/master/wave_b").resolve()
    with tempfile.TemporaryDirectory(prefix="master-wave-b-") as folder:
        root = Path(folder)
        connection = StdioServerParameters(command=sys.executable,
            args=["-m", "cgal_mcp.master.server", "stdio"],
            env={**os.environ, "CGAL_MASTER_DATA": str(root / "data"),
                 "CGAL_MASTER_WORKER": str(executable)})
        async with Client(connection, mode=mode) as client:
            async def call(name: str, arguments: dict) -> dict:
                result = await client.call_tool(name, arguments)
                assert not result.is_error, result
                return (result.structured_content if result.structured_content is not None else
                        json.loads("".join(block.text for block in result.content
                                           if hasattr(block, "text"))))

            assert len((await client.list_tools()).tools) == 12
            source = await call("cgal_artifact_import", {
                "path": str(fixtures / "noisy_plane_with_outlier.xyz"),
                "unit": "cm", "artifact_type": "PointSet3"})

            async def execute(operation: str, artifact_id: str, parameters: dict) -> tuple[dict, dict]:
                plan = await call("cgal_plan", {"request": {
                    "operation_id": operation, "inputs": [artifact_id], "parameters": parameters}})
                assert [step["operation"] for step in plan["steps"]] == [
                    operation, "pointset.validate.basic", SPECIFIC_VALIDATOR[operation]], plan
                queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
                for _ in range(1200):
                    status = await call("cgal_job_status", {"job_id": queued["job_id"]})
                    if status["state"] not in {"queued", "running"}:
                        break
                    await asyncio.sleep(0.05)
                assert status["state"] == "succeeded", status
                assert status["validation_status"] == "passed", status
                assert {item["operation"] for item in status["validation"]} == {
                    "pointset.validate.basic", SPECIFIC_VALIDATOR[operation]}, status
                return plan, status

            async def wait_job(job_id: str) -> dict:
                for _ in range(1200):
                    status = await call("cgal_job_status", {"job_id": job_id})
                    if status["state"] not in {"queued", "running"}:
                        return status
                    await asyncio.sleep(0.05)
                raise AssertionError(f"job did not finish: {job_id}")

            _, outliers = await execute("pointset.remove_outliers", source["artifact_id"], {
                "neighbors": 8, "threshold_percent": 10,
                "threshold_distance": {"value": 30, "unit": "mm"}})
            grid_plan, grid = await execute("pointset.simplify.grid", source["artifact_id"], {
                "cell_size": {"value": 15, "unit": "mm"}, "min_points_per_cell": 1})
            assert grid_plan["steps"][0]["parameters"]["cell_size"] == {"value": 1.5, "unit": "cm"}
            _, hierarchy = await execute("pointset.simplify.hierarchy", source["artifact_id"], {
                "cluster_size": 4, "maximum_variation": 0.2})
            _, smoothed = await execute("pointset.smooth.jet", source["artifact_id"], {
                "neighbors": 8, "degree_fitting": 2, "degree_monge": 2})
            _, random_one = await execute("pointset.simplify.random", source["artifact_id"], {
                "removed_percentage": 40, "seed": 12345})
            _, random_two = await execute("pointset.simplify.random", source["artifact_id"], {
                "removed_percentage": 40, "seed": 12345})
            assert random_one["outputs"][0]["sha256"] == random_two["outputs"][0]["sha256"]

            _, pca = await execute("pointset.normals.estimate", outliers["outputs"][0]["artifact_id"], {
                "method": "pca", "neighbors": 8})
            _, jet = await execute("pointset.normals.estimate", outliers["outputs"][0]["artifact_id"], {
                "method": "jet", "neighbors": 8, "degree_fitting": 2})
            jet_artifact = await call("cgal_artifact_inspect", {
                "artifact_id": jet["outputs"][0]["artifact_id"]})
            assert jet_artifact["type"] == "PointSet3Normals" and jet_artifact["format"] == "ply"
            assert jet_artifact["unit"] == "cm" and jet_artifact["properties"]["normals_nonzero"] is True
            export_path = root / "jet-normals.ply"
            exported = await call("cgal_artifact_export", {
                "artifact_id": jet_artifact["artifact_id"], "path": str(export_path)})
            assert hashlib.sha256(export_path.read_bytes()).hexdigest() == exported["sha256"]

            alternating = await call("cgal_artifact_import", {
                "path": str(fixtures / "plane_normals_alternating.ply"),
                "unit": "mm", "artifact_type": "PointSet3Normals"})
            _, oriented = await execute("pointset.normals.orient_mst", alternating["artifact_id"], {
                "neighbors": 4, "drop_unoriented": False})
            oriented_artifact = await call("cgal_artifact_inspect", {
                "artifact_id": oriented["outputs"][0]["artifact_id"]})
            assert oriented_artifact["type"] == "PointSet3Normals"

            workflow_request = {"steps": [
                {"id": "outliers", "operation": "pointset.remove_outliers",
                 "inputs": {"points": source["artifact_id"]},
                 "parameters": {"neighbors": 8, "threshold_percent": 10,
                                "threshold_distance": {"value": 30, "unit": "mm"}}},
                {"id": "estimate", "operation": "pointset.normals.estimate",
                 "inputs": {"points": {"step": "outliers", "slot": "points"}},
                 "parameters": {"method": "pca", "neighbors": 8}},
                {"id": "orient", "operation": "pointset.normals.orient_mst",
                 "inputs": {"points": {"step": "estimate", "slot": "points"}},
                 "parameters": {"neighbors": 8, "drop_unoriented": False}},
            ]}
            workflow_plan = await call("cgal_plan", {"request": workflow_request})
            assert len(workflow_plan["steps"]) == 9, workflow_plan
            assert workflow_plan["steps"][3]["deferred_preconditions"]["parameters"], workflow_plan
            assert workflow_plan["steps"][6]["deferred_preconditions"]["artifact_properties"], workflow_plan
            workflow_job = await call("cgal_execute", {"plan_id": workflow_plan["plan_id"]})
            workflow_status = await wait_job(workflow_job["job_id"])
            assert workflow_status["state"] == "succeeded", workflow_status
            assert len(workflow_status["outputs"]) == 3, workflow_status
            assert len(workflow_status["validation"]) == 6, workflow_status

            too_many_neighbors = json.loads(json.dumps(workflow_request))
            too_many_neighbors["steps"][1]["parameters"]["neighbors"] = 25
            rejected_plan = await call("cgal_plan", {"request": too_many_neighbors})
            rejected_job = await call("cgal_execute", {"plan_id": rejected_plan["plan_id"]})
            rejected_status = await wait_job(rejected_job["job_id"])
            assert rejected_status["state"] == "failed", rejected_status
            assert not rejected_status.get("outputs")
            assert rejected_status["error"]["class"] == "unmet_precondition", rejected_status

            for result in (grid, hierarchy, smoothed, pca):
                inspected = await call("cgal_artifact_inspect", {
                    "artifact_id": result["outputs"][0]["artifact_id"]})
                assert inspected["unit"] in {"cm", "mm"}
            print(f"CGAL Master Wave B MCP ({mode}) + 7 transforms + validated DAG preconditions: PASS")


if __name__ == "__main__":
    asyncio.run(main())
