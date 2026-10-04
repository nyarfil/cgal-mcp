"""MCP survives controlled worker faults; mock geometry is not CGAL evidence."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import Client, StdioServerParameters
from tests.test_master_core import POINTS, make_worker


FAULTS = {
    "crash": ("import os; os._exit(17)", "worker_crash"),
    "assertion": ('''print(json.dumps({"protocol":1,"request_id":request["request_id"],
        "status":"error","outputs":[],"error":{"class":"CGAL_ASSERTION",
        "code":"CONTROLLED_ASSERTION","message":"controlled fixture assertion",
        "recoverable":False}})); raise SystemExit(0)''', "cgal_precondition"),
    "malformed": ('print("not JSON"); raise SystemExit(0)', "worker_protocol"),
    "wrong_identity": ('''print(json.dumps({"protocol":1,"request_id":"wrong",
        "status":"ok","outputs":[]})); raise SystemExit(0)''', "worker_protocol"),
    "stdout_limit": ('print("x" * (3 * 1024 * 1024)); raise SystemExit(0)', "worker_protocol"),
    "timeout": ('time.sleep(30)', "timeout"),
    "memory": ('bytearray(512 * 1024 * 1024)', "resource_limit"),
}


async def main(mode: str) -> None:
    if mode not in {"auto", "legacy"}:
        raise ValueError("mode must be auto or legacy")
    with tempfile.TemporaryDirectory(prefix="master-fault-fixture-") as directory:
        root = Path(directory)
        points = root / "points.xyz"
        points.write_bytes(POINTS)
        template = make_worker(root).read_text("utf-8")
        worker = root / "controlled_fault_worker.py"
        worker.write_text(template, encoding="utf-8")
        connection = StdioServerParameters(command=sys.executable,
            args=["-m", "cgal_mcp.master.server", "stdio"], env={**os.environ,
                "CGAL_MASTER_WORKER": str(worker), "CGAL_MASTER_DATA": str(root / "data")})
        async with Client(connection, mode=mode) as client:
            async def call(name: str, arguments: dict) -> dict:
                response = await client.call_tool(name, arguments)
                assert not response.is_error, response
                return response.structured_content or json.loads("".join(
                    item.text for item in response.content if hasattr(item, "text")))

            assert len((await client.list_tools()).tools) == 12
            source = await call("cgal_artifact_import", {"path": str(points), "unit": "mm"})
            plan = await call("cgal_plan", {"request": {"operation_id": "hull.convex_3",
                                                      "inputs": [source["artifact_id"]]}})
            async def terminal(job_id: str) -> dict:
                deadline = asyncio.get_running_loop().time() + 20
                while True:
                    state = await call("cgal_job_status", {"job_id": job_id})
                    if state["state"] not in {"queued", "running"}:
                        return state
                    assert asyncio.get_running_loop().time() < deadline, state
                    await asyncio.sleep(.02)

            for name, (injection, category) in FAULTS.items():
                worker.write_text(template.replace("request=json.loads(sys.stdin.readline())",
                    "request=json.loads(sys.stdin.readline())\n" + injection), encoding="utf-8")
                execution = {"memory_mb": 64} if name == "memory" else {}
                if name == "timeout":
                    execution["wall_time_ms"] = 100
                job = await call("cgal_execute", {"plan_id": plan["plan_id"], "execution": execution})
                result = await terminal(job["job_id"])
                assert result["state"] == "failed", (name, result)
                assert result["error"]["class"] == category, (name, result)
                assert not result.get("outputs"), (name, result)
                assert (await call("cgal_artifact_inspect", {
                    "artifact_id": source["artifact_id"]}))["sha256"] == source["sha256"]

                # Same MCP connection, then a successful job after each real fault.
                worker.write_text(template, encoding="utf-8")
                recovered = await call("cgal_execute", {"plan_id": plan["plan_id"]})
                recovered_state = await terminal(recovered["job_id"])
                assert recovered_state["state"] == "succeeded", (name, recovered_state)
                assert recovered_state["validation_status"] == "passed", recovered_state

            worker.write_text(template.replace("request=json.loads(sys.stdin.readline())",
                "request=json.loads(sys.stdin.readline())\ntime.sleep(30)"), encoding="utf-8")
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            await asyncio.sleep(.1)
            start = asyncio.get_running_loop().time()
            await call("cgal_job_cancel", {"job_id": queued["job_id"]})
            cancelled = await terminal(queued["job_id"])
            assert cancelled["state"] == "cancelled", cancelled
            assert not cancelled.get("outputs"), cancelled
            cancel_elapsed = asyncio.get_running_loop().time() - start
            assert cancel_elapsed < 5, cancel_elapsed
            worker.write_text(template, encoding="utf-8")
            recovered = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            assert (await terminal(recovered["job_id"]))["state"] == "succeeded"
            print(f"Master MCP controlled fault isolation ({mode}): 7 fault classes + cancel, "
                  f"successful same-connection recovery after each: PASS; cancel {cancel_elapsed:.3f}s")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "auto"))
