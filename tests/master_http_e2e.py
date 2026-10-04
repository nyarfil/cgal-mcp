"""Actual Streamable HTTP MCP client and worker calculation on loopback."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import tempfile

from mcp import Client
from cgal_mcp.master.supervisor import _assign_windows_job, _close_windows_job

from tests.master_mcp_e2e import worker_path


async def verify(mode: str) -> None:
    worker = worker_path()
    if not worker.is_file():
        raise RuntimeError(f"Master worker missing: {worker}")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="master-http-e2e-") as folder:
        root = Path(folder)
        points = root / "points.xyz"
        points.write_text("0 0 0\n1 0 0\n0 1 0\n0 0 1\n0.2 0.2 0.2\n", encoding="utf-8")
        with (root / "server.log").open("wb") as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "cgal_mcp.master.server", "streamable-http",
                "--host", "127.0.0.1", "--port", str(port),
                env={**os.environ, "CGAL_MASTER_DATA": str(root / "store"),
                     "CGAL_MASTER_WORKER": str(worker), "CGAL_MASTER_FILE_ROOTS": str(root)}, stdout=log, stderr=log)
            owned_job = None
            try:
                if os.name == "nt":
                    owned_job, resource_mode = _assign_windows_job(process.pid, 4096)
                    assert owned_job is not None, resource_mode
                deadline = asyncio.get_running_loop().time() + 15
                while True:
                    if process.returncode is not None:
                        raise RuntimeError((root / "server.log").read_text(errors="replace"))
                    try:
                        _, writer = await asyncio.open_connection("127.0.0.1", port)
                        writer.close()
                        await writer.wait_closed()
                        break
                    except OSError:
                        if asyncio.get_running_loop().time() > deadline:
                            raise TimeoutError("HTTP server did not become available")
                        await asyncio.sleep(0.1)
                async with Client(f"http://127.0.0.1:{port}/mcp", mode=mode) as client:
                    async def call(name: str, arguments: dict) -> dict:
                        result = await client.call_tool(name, arguments)
                        assert not result.is_error, result
                        return result.structured_content if result.structured_content is not None else json.loads(
                            "".join(block.text for block in result.content if hasattr(block, "text")))

                    assert len((await client.list_tools()).tools) == 12
                    source = await call("cgal_artifact_import", {"path": str(points), "unit": "mm"})
                    plan = await call("cgal_plan", {"request": {"operation_id": "hull.convex_3",
                                                              "inputs": [source["artifact_id"]]}})
                    job = await call("cgal_execute", {"plan_id": plan["plan_id"]})
                    deadline = asyncio.get_running_loop().time() + 60
                    while True:
                        status = await call("cgal_job_status", {"job_id": job["job_id"]})
                        if status["state"] not in {"queued", "running"}:
                            break
                        if asyncio.get_running_loop().time() > deadline:
                            await call("cgal_job_cancel", {"job_id": job["job_id"]})
                            raise TimeoutError("HTTP hull job exceeded its test deadline")
                        await asyncio.sleep(0.05)
                    assert status["state"] == "succeeded", status
                    assert status["validation_status"] == "passed", status
                    assert status["validation"][0]["report"]["all_original_points_enclosed"] is True
                    artifact = await call("cgal_artifact_inspect", {
                        "artifact_id": status["outputs"][0]["artifact_id"]})
                    assert artifact["unit"] == "mm" and artifact["type"] == "TriangleSurfaceMesh"
            finally:
                _close_windows_job(owned_job)
                if process.returncode is None:
                    if os.name != "nt" or owned_job is None:
                        process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                if os.name == "nt":
                    # Windows interpreter-launcher descendants release file handles
                    # shortly after the owned Job Object has terminated the tree.
                    await asyncio.sleep(0.1)
    print(f"Master Streamable HTTP ({mode}) + actual hull and validator: PASS")


if __name__ == "__main__":
    selected = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if selected not in {"auto", "legacy"}:
        raise SystemExit("mode must be auto or legacy")
    asyncio.run(verify(selected))
