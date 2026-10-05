"""Official MCP client -> capability selection -> AABB query -> mandatory validator."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import Client, StdioServerParameters

from tests.master_mcp_e2e import worker_path


ANALYSIS = "spatial.aabb.closest_point"
VALIDATOR = "spatial.validate.aabb_closest_point"


def write_square(path: Path) -> None:
    path.write_text(
        "OFF\n4 2 0\n"
        "0 0 0\n1 0 0\n1 1 0\n0 1 0\n"
        "3 0 1 2\n3 0 2 3\n",
        encoding="ascii",
    )


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode not in {"auto", "legacy"}:
        raise SystemExit("mode must be auto or legacy")
    executable = worker_path()
    if not executable.is_file():
        raise SystemExit(f"Master worker is missing: {executable}")

    with tempfile.TemporaryDirectory(prefix="master-spatial-aabb-") as folder:
        root = Path(folder)
        mesh = root / "square.off"
        write_square(mesh)
        connection = StdioServerParameters(
            command=sys.executable,
            args=["-m", "cgal_mcp.master.server", "stdio"],
            env={**os.environ, "CGAL_MASTER_DATA": str(root / "data"),
                 "CGAL_MASTER_WORKER": str(executable)},
        )
        async with Client(connection, mode=mode) as client:
            async def call(name: str, arguments: dict) -> dict:
                result = await client.call_tool(name, arguments)
                assert not result.is_error, result
                if result.structured_content is not None:
                    return result.structured_content
                return json.loads("".join(
                    block.text for block in result.content
                    if hasattr(block, "text")))

            async def wait_job(job_id: str) -> dict:
                for _ in range(1200):
                    status = await call("cgal_job_status", {"job_id": job_id})
                    if status["state"] not in {"queued", "running"}:
                        return status
                    await asyncio.sleep(0.05)
                raise AssertionError(f"job did not finish: {job_id}")

            assert len((await client.list_tools()).tools) == 12
            source = await call("cgal_artifact_import", {
                "path": str(mesh),
                "unit": "cm",
                "artifact_type": "TriangleSurfaceMesh",
            })

            search = await call("cgal_capabilities_search", {
                "query": "point to mesh distance closest point",
                "artifact_ids": [source["artifact_id"]],
                "constraints": {"kernel": "package_recommended"},
                "limit": 5,
            })
            candidates = [item["operation_id"] for item in search["candidates"]]
            assert ANALYSIS in candidates, search

            japanese = await call("cgal_capabilities_search", {
                "query": "メッシュまでの距離 最近傍点",
                "artifact_ids": [source["artifact_id"]],
                "limit": 5,
            })
            assert ANALYSIS in [item["operation_id"]
                                for item in japanese["candidates"]], japanese

            described = await call("cgal_capabilities_describe", {
                "operation_id": ANALYSIS})
            assert described["status"] in {"IMPLEMENTED", "VALIDATED"}
            assert described["executable"] is True
            assert described["package"] == "AABB_tree"
            assert described["validation"]["validators"] == [VALIDATOR]

            query = {"value": [7.5, 2.5, 20.0], "unit": "mm"}
            plan = await call("cgal_plan", {"request": {
                "operation_id": ANALYSIS,
                "inputs": {"mesh": source["artifact_id"]},
                "parameters": {"query": query},
            }})
            assert [step["operation"] for step in plan["steps"]] == [
                ANALYSIS, VALIDATOR], plan
            transform, validation = plan["steps"]
            assert validation["validates"] == transform["id"]
            assert validation["inputs"]["candidate"]["step"] == transform["id"]
            assert validation["inputs"]["source"]["artifact_id"] ==                 source["artifact_id"]
            assert validation["parameters"] == {"query": query}

            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            status = await wait_job(queued["job_id"])
            assert status["state"] == "succeeded", status
            assert status["execution_status"] == "succeeded", status
            assert status["validation_status"] == "passed", status
            assert len(status["validation"]) == 1
            report = status["validation"][0]["report"]
            assert report["validator_id"] == VALIDATOR
            assert report["validates"] == ANALYSIS
            assert report["passed"] is True
            assert all(report["checks"].values()), report
            assert len(status["outputs"]) == 1

            analysis_artifact = await call("cgal_artifact_inspect", {
                "artifact_id": status["outputs"][0]["artifact_id"]})
            assert (analysis_artifact["type"], analysis_artifact["format"],
                    analysis_artifact["unit"]) == (
                        "GeometryAnalysisReport", "json", "none")

            exported = root / "analysis.json"
            await call("cgal_artifact_export", {
                "artifact_id": analysis_artifact["artifact_id"],
                "path": str(exported),
            })
            analysis_report = json.loads(exported.read_text(encoding="utf-8"))
            assert analysis_report["query"] == {
                "value": [0.75, 0.25, 2.0], "unit": "cm"}
            assert analysis_report["results"]["closest_point"] == {
                "value": [0.75, 0.25, 0.0], "unit": "cm"}
            assert analysis_report["results"]["distance"] == {
                "value": 2.0, "unit": "cm"}
            assert analysis_report["results"]["squared_distance"] == {
                "value": 4.0, "unit": "cm^2"}
            assert analysis_report["results"]["closest_face_index"] == 0

            # A syntactically valid but modified report must fail the separate
            # replay validator and must never become a published output.
            analysis_report["results"]["distance"]["value"] = 3.0
            tampered_path = root / "tampered.json"
            tampered_path.write_text(
                json.dumps(analysis_report) + "\n", encoding="utf-8")
            tampered = await call("cgal_artifact_import", {
                "path": str(tampered_path),
                "unit": "none",
                "artifact_type": "GeometryAnalysisReport",
            })
            tampered_plan = await call("cgal_plan", {"request": {"steps": [{
                "id": "validate",
                "operation": VALIDATOR,
                "inputs": {
                    "candidate": tampered["artifact_id"],
                    "source": source["artifact_id"],
                },
                "parameters": {"query": query},
            }]}})
            tampered_job = await call("cgal_execute", {
                "plan_id": tampered_plan["plan_id"]})
            tampered_status = await wait_job(tampered_job["job_id"])
            assert tampered_status["state"] in {"rejected", "failed"},                 tampered_status
            assert not tampered_status.get("outputs"), tampered_status

            after = await call("cgal_artifact_inspect", {
                "artifact_id": source["artifact_id"]})
            assert after["sha256"] == source["sha256"]

            print(
                f"CGAL Master Spatial AABB MCP ({mode}) + search + "
                "mandatory replay validator: PASS")


if __name__ == "__main__":
    asyncio.run(main())
