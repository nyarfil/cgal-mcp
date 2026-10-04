"""Official MCP client -> generic plan -> real CGAL hull -> validator -> artifact."""

import asyncio
import json
import os
import pathlib
import sys
import tempfile

from mcp import Client, StdioServerParameters


def worker_path() -> pathlib.Path:
    configured = os.environ.get("CGAL_MASTER_WORKER")
    if configured:
        return pathlib.Path(configured).resolve()
    direct = pathlib.Path("build-master/cgal-master-worker.exe" if os.name == "nt" else
                          "build-master/cgal-master-worker")
    release = pathlib.Path("build-master/Release/cgal-master-worker.exe")
    return (release if release.is_file() else direct).resolve()


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode not in {"auto", "legacy"}:
        raise SystemExit("mode must be auto or legacy")
    executable = worker_path()
    if not executable.is_file():
        raise SystemExit(f"Master worker is missing: {executable}")
    with tempfile.TemporaryDirectory() as folder:
        root = pathlib.Path(folder)
        points = root / "points.xyz"
        points.write_text("0 0 0\n1 0 0\n0 1 0\n0 0 1\n0.2 0.2 0.2\n", encoding="utf-8")
        connection = StdioServerParameters(command=sys.executable,
            args=["-m", "cgal_mcp.master.server", "stdio"],
            env={**os.environ, "CGAL_MASTER_DATA": str(root / "data"),
                 "CGAL_MASTER_WORKER": str(executable)})
        async with Client(connection, mode=mode) as client:
            async def call(name: str, arguments: dict):
                result = await client.call_tool(name, arguments)
                assert not result.is_error, result
                if result.structured_content is not None:
                    return result.structured_content
                return json.loads("".join(block.text for block in result.content
                                          if hasattr(block, "text")))

            tools = await client.list_tools()
            assert len(tools.tools) == 12, [tool.name for tool in tools.tools]
            source = await call("cgal_artifact_import", {"path": str(points), "unit": "mm"})
            plan = await call("cgal_plan", {"request": {
                "operation_id": "hull.convex_3", "inputs": [source["artifact_id"]],
                "parameters": {}}})
            assert [step["operation"] for step in plan["steps"]] == [
                "hull.convex_3", "hull.validate.convex_enclosure"]
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            for _ in range(600):
                status = await call("cgal_job_status", {"job_id": queued["job_id"]})
                if status["state"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.1)
            assert status["state"] == "succeeded", status
            assert status["execution_status"] == "succeeded", status
            assert status["validation_status"] == "passed", status
            assert status["validation"][0]["report"]["all_original_points_enclosed"] is True
            artifact = await call("cgal_artifact_inspect", {
                "artifact_id": status["outputs"][0]["artifact_id"]})
            assert artifact["type"] == "TriangleSurfaceMesh" and artifact["unit"] == "mm"
            health = await call("cgal_system_health", {})
            assert health["worker"]["available"] is True, health
            if os.name == "nt":
                assert health["worker"]["resource_limit_mode"] == "windows_job_object", health
            print(f"CGAL Master MCP ({mode}) + real hull + mandatory validator + artifact: PASS")


if __name__ == "__main__":
    asyncio.run(main())
