"""Official MCP client -> Wave D meshing/remeshing operations -> independent validators."""

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
WAVE_D = ROOT / "tests" / "fixtures" / "master" / "wave_d"
TSM = "TriangleSurfaceMesh"


def length(value: float, unit: str) -> dict:
    return {"value": value, "unit": unit}


# operation -> (validator, fixture, artifact type, parameters(unit) -> dict)
CASES = {
    "mesh.triangulate.faces": ("mesh.validate.triangulated_faces", WAVE_D / "l_prism.off",
                               "PolygonSoup3", lambda u: {"method": "triangulate_face"}),
    "mesh.refine.local": ("mesh.validate.refinement", WAVE_D / "hexadecagon_fan.off", TSM,
                          lambda u: {"density_control_factor": 1.4142135623730951,
                                     "max_deviation": length(0.01, u)}),
    "mesh.remesh.isotropic": ("mesh.validate.isotropic_remesh", WAVE_D / "square_fan.off", TSM,
                              lambda u: {"target_edge_length": length(0.5, u),
                                         "number_of_iterations": 3,
                                         "max_deviation": length(0.01, u)}),
    "mesh.remesh.split_long_edges": ("mesh.validate.split_long_edges",
                                     WAVE_D / "square_two_triangles.off", TSM,
                                     lambda u: {"max_length": length(1.0, u)}),
    "mesh.smooth.tangential_relaxation": ("mesh.validate.tangential_relaxation",
                                          WAVE_D / "grid3_displaced.off", TSM,
                                          lambda u: {"max_deviation": length(0.01, u)}),
    "mesh.smooth.shape": ("mesh.validate.shape_smoothing", WAVE_D / "icosphere2_noisy.off", TSM,
                          lambda u: {"time_step": 0.01, "preserve_volume": True,
                                     "max_deviation": length(0.2, u)}),
    "mesh.remesh.adaptive": ("mesh.validate.adaptive_remesh", WAVE_D / "ellipsoid_3_1_1.off", TSM,
                             lambda u: {"tolerance": length(0.005, u),
                                        "min_edge_length": length(0.1, u),
                                        "max_edge_length": length(0.6, u),
                                        "mode": "split_long_edges",
                                        "max_deviation": length(0.05, u)}),
}


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode not in {"auto", "legacy"}:
        raise SystemExit("mode must be auto or legacy")
    executable = worker_path()
    if not executable.is_file():
        raise SystemExit(f"Master worker is missing: {executable}")

    with tempfile.TemporaryDirectory(prefix="master-wave-d-") as folder:
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
            for index, (operation, (validator, fixture, artifact_type, parameters)) in enumerate(
                    CASES.items()):
                unit = ("mm", "cm", "m")[index % 3]
                source = await call("cgal_artifact_import", {
                    "path": str(fixture), "unit": unit, "artifact_type": artifact_type})
                assert source["type"] == artifact_type, source
                sources[operation] = source
                plan = await call("cgal_plan", {"request": {
                    "operation_id": operation, "inputs": [source["artifact_id"]],
                    "parameters": parameters(unit)}})
                assert [step["operation"] for step in plan["steps"]] == [operation, validator], plan
                transform, validation = plan["steps"]
                assert validation["inputs"]["candidate"]["step"] == transform["id"]
                queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
                status = await wait_job(queued["job_id"])
                assert status["state"] == "succeeded", status
                assert status["validation_status"] == "passed", status
                assert [item["operation"] for item in status["validation"]] == [validator]
                report = status["validation"][0]["report"]
                assert report["status"] == "pass" and report["passed"] is True, report
                assert report["validator"] == validator and all(report["checks"].values()), report
                assert len(status["outputs"]) == 1, status
                output = await call("cgal_artifact_inspect", {
                    "artifact_id": status["outputs"][0]["artifact_id"]})
                assert output["type"] == TSM and output["format"] == "off", output
                assert output["unit"] == unit, output
                outputs[operation] = output
                again = await call("cgal_artifact_inspect", {"artifact_id": source["artifact_id"]})
                assert again["sha256"] == source["sha256"]

            # TypedLength parameters given in another unit are normalized to the artifact unit.
            source = await call("cgal_artifact_import", {
                "path": str(WAVE_D / "square_two_triangles.off"), "unit": "cm",
                "artifact_type": TSM})
            plan = await call("cgal_plan", {"request": {
                "operation_id": "mesh.remesh.split_long_edges", "inputs": [source["artifact_id"]],
                "parameters": {"max_length": length(10.0, "mm")}}})
            assert plan["steps"][0]["parameters"]["max_length"] == length(1.0, "cm"), plan
            assert plan["steps"][1]["parameters"]["max_length"] == length(1.0, "cm"), plan
            status = await wait_job((await call("cgal_execute", {"plan_id": plan["plan_id"]}))["job_id"])
            assert status["state"] == "succeeded", status
            assert status["validation"][0]["report"]["longest_subdivided_piece"] <= 1.0 + 1e-12

            # A tampered candidate is rejected by the mandatory independent validator.
            operation = "mesh.smooth.tangential_relaxation"
            validator, _, _, parameters = CASES[operation]
            exported = root / "relaxed.off"
            await call("cgal_artifact_export", {
                "artifact_id": outputs[operation]["artifact_id"], "path": str(exported)})
            lines = [line for line in exported.read_text(encoding="ascii").splitlines() if line.strip()]
            lines[2] = "-0.25 0 0"  # move a fixed boundary vertex
            exported.write_text("\n".join(lines) + "\n", encoding="ascii")
            unit = sources[operation]["unit"]
            candidate = await call("cgal_artifact_import", {
                "path": str(exported), "unit": unit, "artifact_type": TSM})
            plan = await call("cgal_plan", {"request": {"steps": [{
                "id": "validate", "operation": validator,
                "inputs": {"candidate": candidate["artifact_id"],
                           "source": sources[operation]["artifact_id"]},
                "parameters": parameters(unit)}]}})
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            rejected = await wait_job(queued["job_id"])
            assert rejected["state"] in {"rejected", "failed"}, rejected
            assert not rejected.get("outputs"), rejected

            print(f"CGAL Master Wave D MCP ({mode}) + 7 independent validators: PASS")


if __name__ == "__main__":
    asyncio.run(main())
