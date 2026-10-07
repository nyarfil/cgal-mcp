"""Official MCP client -> bounded mesh repairs -> dedicated replay validators."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import Client, StdioServerParameters

from tests.master_mcp_e2e import worker_path
from tests.master_wave_a_repair_cases import CASES, FIXTURES


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode not in {"auto", "legacy"}:
        raise SystemExit("mode must be auto or legacy")
    executable = worker_path()
    if not executable.is_file():
        raise SystemExit(f"Master worker is missing: {executable}")

    with tempfile.TemporaryDirectory(prefix="master-wave-a-repair-") as folder:
        root = Path(folder)
        connection = StdioServerParameters(
            command=sys.executable,
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

            async def wait_job(job_id: str) -> dict:
                for _ in range(2400):
                    status = await call("cgal_job_status", {"job_id": job_id})
                    if status["state"] not in {"queued", "running"}:
                        return status
                    await asyncio.sleep(0.05)
                raise AssertionError(f"job did not finish: {job_id}")

            sources: dict[str, dict] = {}
            for index, (operation, (validator, fixture, source_type, parameters)) in enumerate(CASES.items()):
                unit = ("mm", "cm", "m")[index % 3]
                source = await call("cgal_artifact_import", {
                    "path": str(FIXTURES / fixture), "unit": unit,
                    "artifact_type": source_type})
                assert source["type"] == source_type, source
                sources[operation] = source
                plan = await call("cgal_plan", {"request": {
                    "operation_id": operation, "inputs": [source["artifact_id"]],
                    "parameters": parameters}})
                assert [step["operation"] for step in plan["steps"]] == [
                    operation, validator], plan
                repair, validation = plan["steps"]
                assert repair["role"] == "transform"
                assert validation["inputs"]["candidate"]["step"] == repair["id"]
                assert validation["inputs"]["source"]["artifact_id"] == source["artifact_id"]

                queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
                status = await wait_job(queued["job_id"])
                assert status["state"] == "succeeded", status
                assert status["execution_status"] == "succeeded", status
                assert status["validation_status"] == "passed", status
                assert [item["operation"] for item in status["validation"]] == [validator]
                report = status["validation"][0]["report"]
                assert report["status"] == "pass" and report["passed"] is True, report
                assert report["validator_id"] == validator
                assert all(report["checks"].values()), report["checks"]
                assert len(status["outputs"]) == 1, status
                output = await call("cgal_artifact_inspect", {
                    "artifact_id": status["outputs"][0]["artifact_id"]})
                assert output["format"] == "off" and output["unit"] == unit, output
                assert output["artifact_id"] != source["artifact_id"]
                # Source artifact is immutable.
                again = await call("cgal_artifact_inspect", {"artifact_id": source["artifact_id"]})
                assert again["sha256"] == source["sha256"]

            # A tampered candidate is quarantined behind its dedicated validator.
            operation = "mesh.repair.fill_holes"
            validator, _, _, parameters = CASES[operation]
            plan = await call("cgal_plan", {"request": {
                "operation_id": operation,
                "inputs": [sources[operation]["artifact_id"]], "parameters": parameters}})
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            status = await wait_job(queued["job_id"])
            exported = root / "candidate.off"
            await call("cgal_artifact_export", {
                "artifact_id": status["outputs"][0]["artifact_id"], "path": str(exported)})
            text = exported.read_text(encoding="ascii")
            assert "0 0 0" in text
            exported.write_text(text.replace("0 0 0", "0.125 0 0", 1), encoding="ascii")
            candidate = await call("cgal_artifact_import", {
                "path": str(exported), "unit": sources[operation]["unit"],
                "artifact_type": "TriangleSurfaceMesh"})
            rejected_plan = await call("cgal_plan", {"request": {"steps": [{
                "id": "validate", "operation": validator,
                "inputs": {"candidate": candidate["artifact_id"],
                           "source": sources[operation]["artifact_id"]},
                "parameters": parameters}]}})
            rejected_job = await call("cgal_execute", {"plan_id": rejected_plan["plan_id"]})
            rejected = await wait_job(rejected_job["job_id"])
            assert rejected["state"] in {"rejected", "failed"}, rejected
            assert not rejected.get("outputs"), rejected

            print(f"CGAL Master Wave A repair MCP ({mode}) + 6 dedicated validators: PASS")


if __name__ == "__main__":
    asyncio.run(main())
