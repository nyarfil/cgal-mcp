"""Official MCP client end-to-end acceptance for Spatial Query family 7.2."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import Client, StdioServerParameters
from tests.master_mcp_e2e import worker_path

VALIDATORS = {
    "spatial.aabb.closest_point": "spatial.validate.aabb_closest_point",
    "spatial.kdtree.range": "spatial.validate.kdtree_range",
    "spatial.nearest_neighbors": "spatial.validate.nearest_neighbors",
    "spatial.intersection_candidates": "spatial.validate.intersection_candidates",
    "spatial.bounding_box": "spatial.validate.bounding_box",
}


def write_xyz(path: Path) -> None:
    path.write_text("0 0 0\n1 0 0\n0 2 0\n0 0 3\n2 2 2\n", encoding="ascii")


def write_tetra(path: Path) -> None:
    path.write_text("""OFF
4 4 0
0 0 0
1 0 0
0 1 0
0 0 1
3 0 2 1
3 0 1 3
3 1 2 3
3 2 0 3
""", encoding="ascii")


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode not in {"auto", "legacy"}:
        raise SystemExit("mode must be auto or legacy")
    executable = worker_path()
    if not executable.is_file():
        raise SystemExit(f"Master worker is missing: {executable}")

    with tempfile.TemporaryDirectory(prefix="master-spatial-") as folder:
        root = Path(folder)
        xyz = root / "points.xyz"
        off = root / "tetra.off"
        write_xyz(xyz)
        write_tetra(off)
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
                for _ in range(1200):
                    status = await call("cgal_job_status", {"job_id": job_id})
                    if status["state"] not in {"queued", "running"}:
                        return status
                    await asyncio.sleep(0.05)
                raise AssertionError(f"job did not finish: {job_id}")

            assert len((await client.list_tools()).tools) == 12
            points = await call("cgal_artifact_import", {
                "path": str(xyz), "unit": "mm", "artifact_type": "PointSet3"})
            mesh = await call("cgal_artifact_import", {
                "path": str(off), "unit": "mm",
                "artifact_type": "TriangleSurfaceMesh"})

            routing = [
                ("メッシュへの最近点", [mesh["artifact_id"]],
                 "spatial.aabb.closest_point"),
                ("点群を半径内で範囲検索", [points["artifact_id"]],
                 "spatial.kdtree.range"),
                ("点群のk近傍 最近傍", [points["artifact_id"]],
                 "spatial.nearest_neighbors"),
                ("線分とメッシュの交差候補", [mesh["artifact_id"]],
                 "spatial.intersection_candidates"),
                ("点群のバウンディングボックス", [points["artifact_id"]],
                 "spatial.bounding_box"),
            ]
            for query, artifacts, expected in routing:
                found = await call("cgal_capabilities_search", {
                    "query": query, "artifact_ids": artifacts, "limit": 5})
                supported = [item["operation_id"] for item in found["candidates"]
                             if item["route_supported"]]
                assert expected in supported, (query, found)

            cases = [
                ("spatial.aabb.closest_point", mesh["artifact_id"],
                 {"query_point": {"value": [2, 0, 0], "unit": "mm"}}),
                ("spatial.kdtree.range", points["artifact_id"],
                 {"center": {"value": [0, 0, 0], "unit": "mm"},
                  "radius": {"value": 1.01, "unit": "mm"}}),
                ("spatial.nearest_neighbors", points["artifact_id"],
                 {"query_point": {"value": [0, 0, 0], "unit": "mm"}, "k": 2}),
                ("spatial.intersection_candidates", mesh["artifact_id"],
                 {"segment_start": {"value": [-1, 0.2, 0.2], "unit": "mm"},
                  "segment_end": {"value": [2, 0.2, 0.2], "unit": "mm"}}),
                ("spatial.bounding_box", points["artifact_id"], {}),
            ]
            reports = {}
            for index, (operation, artifact_id, parameters) in enumerate(cases):
                described = await call("cgal_capabilities_describe", {
                    "operation_id": operation})
                assert described["operation"]["status"] in {"IMPLEMENTED", "VALIDATED"}
                plan = await call("cgal_plan", {"request": {
                    "operation_id": operation,
                    "inputs": [artifact_id],
                    "parameters": parameters}})
                assert [step["operation"] for step in plan["steps"]] == [
                    operation, VALIDATORS[operation]], plan
                assert plan["steps"][1]["role"] == "validator"
                queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
                status = await wait_job(queued["job_id"])
                assert status["state"] == "succeeded", status
                assert status["validation_status"] == "passed", status
                assert len(status["validation"]) == 1
                validation = status["validation"][0]["report"]
                assert validation["validator_id"] == VALIDATORS[operation]
                assert validation["passed"] is True
                assert all(validation["checks"].values())
                assert len(status["outputs"]) == 1
                destination = root / f"spatial-{index}.json"
                await call("cgal_artifact_export", {
                    "artifact_id": status["outputs"][0]["artifact_id"],
                    "path": str(destination)})
                report = json.loads(destination.read_text(encoding="utf-8"))
                assert report["source"]["artifact_id"] == artifact_id
                reports[operation] = report

            assert reports["spatial.aabb.closest_point"]["results"][
                "closest_point"]["value"] == [1.0, 0.0, 0.0]
            assert reports["spatial.kdtree.range"]["results"]["match_count"] == 2
            assert len(reports["spatial.nearest_neighbors"]["results"][
                "neighbors"]) == 2
            assert reports["spatial.intersection_candidates"]["results"][
                "does_intersect"] is True
            assert reports["spatial.bounding_box"]["results"][
                "maximum"]["value"] == [2.0, 2.0, 3.0]

            print(f"CGAL Master Spatial Query MCP ({mode}) 5/5 routes + validators: PASS")


if __name__ == "__main__":
    asyncio.run(main())
