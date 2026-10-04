"""Official MCP client -> Wave A simplification -> both mandatory validators."""

from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import sys
import tempfile

from mcp import Client, StdioServerParameters

from tests.master_mcp_e2e import worker_path


def sphere_fixture(subdivisions: int = 2) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    vertices = [(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)]
    faces = [(0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
             (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)]
    for _ in range(subdivisions):
        cache: dict[tuple[int, int], int] = {}
        def midpoint(first: int, second: int) -> int:
            key = tuple(sorted((first, second)))
            if key not in cache:
                point = tuple((vertices[first][axis] + vertices[second][axis]) * 0.5
                              for axis in range(3))
                length = math.sqrt(sum(value * value for value in point))
                vertices.append(tuple(value / length for value in point))
                cache[key] = len(vertices) - 1
            return cache[key]
        refined = []
        for a, b, c in faces:
            ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
            refined.extend(((a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)))
        faces = refined
    return vertices, faces


def write_off(path: Path) -> None:
    vertices, faces = sphere_fixture()
    lines = ["OFF", f"{len(vertices)} {len(faces)} 0"]
    lines.extend(f"{x:.17g} {y:.17g} {z:.17g}" for x, y, z in vertices)
    lines.extend(f"3 {a} {b} {c}" for a, b, c in faces)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode not in {"auto", "legacy"}:
        raise SystemExit("mode must be auto or legacy")
    executable = worker_path()
    if not executable.is_file():
        raise SystemExit(f"Master worker is missing: {executable}")
    with tempfile.TemporaryDirectory(prefix="master-wave-a-") as folder:
        root = Path(folder); mesh = root / "sphere.off"; write_off(mesh)
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

            source = await call("cgal_artifact_import", {
                "path": str(mesh), "unit": "mm", "artifact_type": "TriangleSurfaceMesh"})
            request = {"operation_id": "mesh.simplify.edge_collapse",
                "inputs": [source["artifact_id"]], "parameters": {
                    "stop": {"kind": "edge_ratio", "value": 0.85},
                    "policy": "gh_plane_line", "preserve_border": True,
                    "bounded_distance": {"value": 0.025, "unit": "cm"},
                    "bounded_normal_change": True,
                    "polyhedral_envelope": {"value": 0.025, "unit": "cm"},
                    "max_symmetric_deviation": {"value": 0.2, "unit": "cm"},
                    "hausdorff_error_bound": {"value": 0.01, "unit": "mm"}}}
            plan = await call("cgal_plan", {"request": request})
            assert [step["operation"] for step in plan["steps"]] == [
                "mesh.simplify.edge_collapse", "mesh.validate.simplification_integrity",
                "mesh.distance.symmetric_hausdorff"], plan
            assert plan["steps"][2]["parameters"]["tolerance"] == {"value": 2.0, "unit": "mm"}
            assert {item["group"] for item in plan["steps"][0]["policies"]} == {
                "cost_placement", "stop_predicate", "wrapper", "filter"}
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            for _ in range(1200):
                status = await call("cgal_job_status", {"job_id": queued["job_id"]})
                if status["state"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.1)
            assert status["state"] == "succeeded", status
            assert status["validation_status"] == "passed" and len(status["validation"]) == 2, status
            reports = {item["operation"]: item["report"] for item in status["validation"]}
            assert reports["mesh.validate.simplification_integrity"]["protected_edges_preserved"] is True
            assert reports["mesh.distance.symmetric_hausdorff"]["verdict"] == "pass"
            artifact = await call("cgal_artifact_inspect", {
                "artifact_id": status["outputs"][0]["artifact_id"]})
            assert artifact["type"] == "TriangleSurfaceMesh" and artifact["unit"] == "mm"
            normalization = artifact["provenance"][0]["parameters"]["normalization"]
            assert any(item["path"] == "max_symmetric_deviation" for item in normalization)
            print(f"CGAL Master Wave A MCP ({mode}) + dual mandatory validation: PASS")


if __name__ == "__main__":
    asyncio.run(main())
