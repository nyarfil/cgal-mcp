"""Official MCP client -> Wave E Mesh_2 refinement -> independent validator."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import Client, StdioServerParameters

from tests.master_mcp_e2e import worker_path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "master"
DOMAIN = "PolygonWithHoles2"
TRANSFORM = "mesh2.refine.delaunay"
VALIDATOR = "mesh.validate.delaunay_refinement_2"


def length(value: float, unit: str) -> dict:
    return {"value": value, "unit": unit}


def parameters(unit: str, size: float = 2.0, aspect: float = 0.125) -> dict:
    return {"aspect_bound": aspect, "size_bound": length(size, unit)}


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode not in {"auto", "legacy"}:
        raise SystemExit("mode must be auto or legacy")
    executable = worker_path()
    if not executable.is_file():
        raise SystemExit(f"Master worker is missing: {executable}")

    with tempfile.TemporaryDirectory(prefix="master-wave-e-") as folder:
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

            outputs: dict[str, dict] = {}
            sources: dict[str, dict] = {}
            fixtures = (("square", FIXTURES / "wave_e" / "square10.json"),
                        ("holed", FIXTURES / "wave_c" / "polygon_with_hole.json"),
                        ("lshape", FIXTURES / "wave_c" / "polygon_l_shape.json"))
            for index, (name, fixture) in enumerate(fixtures):
                unit = ("mm", "cm", "m")[index % 3]
                source = await call("cgal_artifact_import", {
                    "path": str(fixture), "unit": unit, "artifact_type": DOMAIN})
                assert source["type"] == DOMAIN, source
                sources[name] = source
                plan = await call("cgal_plan", {"request": {
                    "operation_id": TRANSFORM, "inputs": [source["artifact_id"]],
                    "parameters": parameters(unit)}})
                assert [step["operation"] for step in plan["steps"]] == [TRANSFORM, VALIDATOR], plan
                transform, validation = plan["steps"]
                assert validation["inputs"]["candidate"]["step"] == transform["id"]
                queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
                status = await wait_job(queued["job_id"])
                assert status["state"] == "succeeded", status
                assert status["validation_status"] == "passed", status
                assert [item["operation"] for item in status["validation"]] == [VALIDATOR]
                report = status["validation"][0]["report"]
                assert report["status"] == "pass" and report["passed"] is True, report
                assert report["validator"] == VALIDATOR and all(report["checks"].values()), report
                assert report["area"]["exact"] == {"square": "100", "holed": "91", "lshape": "7"}[name]
                assert len(status["outputs"]) == 1, status
                output = await call("cgal_artifact_inspect", {
                    "artifact_id": status["outputs"][0]["artifact_id"]})
                assert output["type"] == "Triangulation2" and output["format"] == "json", output
                assert output["unit"] == unit, output
                outputs[name] = output
                again = await call("cgal_artifact_inspect", {"artifact_id": source["artifact_id"]})
                assert again["sha256"] == source["sha256"]

            # TypedLength parameters given in another unit are normalized to the artifact unit.
            plan = await call("cgal_plan", {"request": {
                "operation_id": TRANSFORM, "inputs": [sources["holed"]["artifact_id"]],
                "parameters": {"aspect_bound": 0.125, "size_bound": length(2.0, "m")}}})
            assert plan["steps"][0]["parameters"]["size_bound"] == length(200.0, "cm"), plan

            # A tampered candidate (a boundary vertex moved off its side) is rejected.
            exported = root / "mesh.json"
            await call("cgal_artifact_export", {
                "artifact_id": outputs["square"]["artifact_id"], "path": str(exported)})
            mesh = json.loads(exported.read_text(encoding="utf-8"))
            index = next(i for i, (x, y) in enumerate(mesh["vertices"])
                         if y == 0.0 and 0.0 < x < 10.0)
            mesh["vertices"][index][1] = 0.05
            exported.write_text(json.dumps(mesh), encoding="utf-8")
            unit = sources["square"]["unit"]
            candidate = await call("cgal_artifact_import", {
                "path": str(exported), "unit": unit, "artifact_type": "Triangulation2"})
            plan = await call("cgal_plan", {"request": {"steps": [{
                "id": "validate", "operation": VALIDATOR,
                "inputs": {"candidate": candidate["artifact_id"],
                           "source": sources["square"]["artifact_id"]},
                "parameters": parameters(unit)}]}})
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            rejected = await wait_job(queued["job_id"])
            assert rejected["state"] in {"rejected", "failed"}, rejected
            assert not rejected.get("outputs"), rejected

            print(f"CGAL Master Wave E MCP ({mode}) + Mesh_2 independent validator: PASS")


if __name__ == "__main__":
    asyncio.run(main())
