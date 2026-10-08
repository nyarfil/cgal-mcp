"""Official MCP client -> Wave E Mesh_2, Surface_mesher and Mesh_3 operations -> independent validators."""

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

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "master"
DOMAIN = "PolygonWithHoles2"
TRANSFORM = "mesh2.refine.delaunay"
VALIDATOR = "mesh.validate.delaunay_refinement_2"
SURFACE_DOMAIN = "ImplicitSurfaceDomain"
SURFACE_TRANSFORM = "mesh.surface.generate"
SURFACE_VALIDATOR = "mesh.validate.surface_mesh"
VOLUME_TRANSFORM = "mesh.volume.generate"
VOLUME_VALIDATOR = "mesh.validate.volume_mesh"


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

            # --- 7.14.02 Surface_mesher over a typed implicit domain, validated independently ---
            surface_unit = "cm"
            domain = await call("cgal_artifact_import", {
                "path": str(FIXTURES / "wave_e" / "domain_sphere.json"), "unit": surface_unit,
                "artifact_type": SURFACE_DOMAIN})
            assert domain["type"] == SURFACE_DOMAIN, domain
            surface_parameters = {"angle_bound": 25.0, "size_bound": length(0.5, surface_unit),
                                  "distance_bound": length(0.05, surface_unit)}
            plan = await call("cgal_plan", {"request": {
                "operation_id": SURFACE_TRANSFORM, "inputs": [domain["artifact_id"]],
                "parameters": surface_parameters}})
            assert [step["operation"] for step in plan["steps"]] == [SURFACE_TRANSFORM, SURFACE_VALIDATOR], plan
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            status = await wait_job(queued["job_id"])
            assert status["state"] == "succeeded" and status["validation_status"] == "passed", status
            report = status["validation"][0]["report"]
            assert report["status"] == "pass" and report["validator"] == SURFACE_VALIDATOR, report
            assert all(report["checks"].values()) and report["genus"] == 0, report
            assert abs(report["area"]["analytic"] - 16.0 * math.pi) < 1e-9, report["area"]
            assert report["area"]["unit"] == "cm^2" and report["volume"]["unit"] == "cm^3", report
            surface = await call("cgal_artifact_inspect", {"artifact_id": status["outputs"][0]["artifact_id"]})
            assert surface["type"] == "TriangleSurfaceMesh" and surface["format"] == "off", surface
            assert surface["unit"] == surface_unit, surface
            # A globally scaled candidate leaves the analytic sphere and must be rejected.
            exported_surface = root / "sphere.off"
            await call("cgal_artifact_export", {"artifact_id": surface["artifact_id"],
                                                "path": str(exported_surface)})
            tokens = exported_surface.read_text(encoding="ascii").split()
            count = int(tokens[1])
            for position in range(4, 4 + 3 * count):
                tokens[position] = repr(1.001 * float(tokens[position]))
            exported_surface.write_text("\n".join(tokens) + "\n", encoding="ascii")
            scaled = await call("cgal_artifact_import", {
                "path": str(exported_surface), "unit": surface_unit, "artifact_type": "TriangleSurfaceMesh"})
            plan = await call("cgal_plan", {"request": {"steps": [{
                "id": "validate", "operation": SURFACE_VALIDATOR,
                "inputs": {"candidate": scaled["artifact_id"], "source": domain["artifact_id"]},
                "parameters": surface_parameters}]}})
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            rejected = await wait_job(queued["job_id"])
            assert rejected["state"] in {"rejected", "failed"}, rejected
            assert not rejected.get("outputs"), rejected

            # --- 7.14.03 Mesh_3 tetrahedral volume mesh of the same typed domain, validated independently ---
            volume_parameters = {"facet_angle": 25.0, "facet_size": length(0.5, surface_unit),
                                 "facet_distance": length(0.05, surface_unit),
                                 "cell_radius_edge_ratio": 3.0, "cell_size": length(0.6, surface_unit)}
            plan = await call("cgal_plan", {"request": {
                "operation_id": VOLUME_TRANSFORM, "inputs": [domain["artifact_id"]],
                "parameters": volume_parameters}})
            assert [step["operation"] for step in plan["steps"]] == [VOLUME_TRANSFORM, VOLUME_VALIDATOR], plan
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            status = await wait_job(queued["job_id"])
            assert status["state"] == "succeeded" and status["validation_status"] == "passed", status
            report = status["validation"][0]["report"]
            assert report["status"] == "pass" and report["validator"] == VOLUME_VALIDATOR, report
            assert all(report["checks"].values()) and report["genus"] == 0, report
            assert report["euler_characteristic"] == 1 and report["boundary_euler_characteristic"] == 2, report
            assert abs(report["volume"]["analytic"] - 32.0 * math.pi / 3.0) < 1e-9, report["volume"]
            assert report["volume"]["unit"] == "cm^3" and report["boundary_area"]["unit"] == "cm^2", report
            volume = await call("cgal_artifact_inspect", {"artifact_id": status["outputs"][0]["artifact_id"]})
            assert volume["type"] == "TetrahedralMesh" and volume["unit"] == surface_unit, volume
            # A globally scaled candidate leaves the domain and must be rejected.
            exported_volume = root / "ball.json"
            await call("cgal_artifact_export", {"artifact_id": volume["artifact_id"],
                                                "path": str(exported_volume)})
            ball = json.loads(exported_volume.read_text(encoding="utf-8"))
            ball["vertices"] = [[1.001 * c for c in vertex] for vertex in ball["vertices"]]
            exported_volume.write_text(json.dumps(ball), encoding="utf-8")
            scaled_ball = await call("cgal_artifact_import", {
                "path": str(exported_volume), "unit": surface_unit, "artifact_type": "TetrahedralMesh"})
            plan = await call("cgal_plan", {"request": {"steps": [{
                "id": "validate", "operation": VOLUME_VALIDATOR,
                "inputs": {"candidate": scaled_ball["artifact_id"], "source": domain["artifact_id"]},
                "parameters": volume_parameters}]}})
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            rejected = await wait_job(queued["job_id"])
            assert rejected["state"] in {"rejected", "failed"}, rejected
            assert not rejected.get("outputs"), rejected

            # --- 7.14.03 polyhedral domain: a closed oriented cube (OFF) meshed by Polyhedral_mesh_domain_3 ---
            cube = await call("cgal_artifact_import", {
                "path": str(FIXTURES / "wave_e" / "poly_cube.off"), "unit": surface_unit,
                "artifact_type": "TriangleSurfaceMesh"})
            assert cube["type"] == "TriangleSurfaceMesh", cube
            cube_parameters = {"facet_angle": 25.0, "facet_size": length(0.25, surface_unit),
                               "facet_distance": length(0.02, surface_unit),
                               "cell_radius_edge_ratio": 3.0, "cell_size": length(0.3, surface_unit)}
            plan = await call("cgal_plan", {"request": {
                "operation_id": VOLUME_TRANSFORM, "inputs": [cube["artifact_id"]],
                "parameters": cube_parameters}})
            assert [step["operation"] for step in plan["steps"]] == [VOLUME_TRANSFORM, VOLUME_VALIDATOR], plan
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            status = await wait_job(queued["job_id"])
            assert status["state"] == "succeeded" and status["validation_status"] == "passed", status
            report = status["validation"][0]["report"]
            assert report["status"] == "pass" and report["validator"] == VOLUME_VALIDATOR, report
            assert report["domain_kind"] == "polyhedral" and all(report["checks"].values()), report
            assert report["euler_characteristic"] == 1 and report["boundary_euler_characteristic"] == 2, report
            assert abs(report["volume"]["source"] - 1.0) < 1e-12 and report["volume"]["unit"] == "cm^3", report["volume"]
            cube_mesh = await call("cgal_artifact_inspect", {"artifact_id": status["outputs"][0]["artifact_id"]})
            assert cube_mesh["type"] == "TetrahedralMesh" and cube_mesh["unit"] == surface_unit, cube_mesh
            exported_cube = root / "cube_mesh.json"
            await call("cgal_artifact_export", {"artifact_id": cube_mesh["artifact_id"],
                                                "path": str(exported_cube)})
            cube_data = json.loads(exported_cube.read_text(encoding="utf-8"))
            cube_data["vertices"] = [[vertex[0] + 0.05, vertex[1], vertex[2]] for vertex in cube_data["vertices"]]
            exported_cube.write_text(json.dumps(cube_data), encoding="utf-8")
            shifted_cube = await call("cgal_artifact_import", {
                "path": str(exported_cube), "unit": surface_unit, "artifact_type": "TetrahedralMesh"})
            plan = await call("cgal_plan", {"request": {"steps": [{
                "id": "validate", "operation": VOLUME_VALIDATOR,
                "inputs": {"candidate": shifted_cube["artifact_id"], "source": cube["artifact_id"]},
                "parameters": cube_parameters}]}})
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            rejected = await wait_job(queued["job_id"])
            assert rejected["state"] in {"rejected", "failed"}, rejected
            assert not rejected.get("outputs"), rejected
            # An open source surface is refused before any mesh is produced.
            open_cube = await call("cgal_artifact_import", {
                "path": str(FIXTURES / "wave_e" / "poly_cube_open.off"), "unit": surface_unit,
                "artifact_type": "TriangleSurfaceMesh"})
            plan = await call("cgal_plan", {"request": {
                "operation_id": VOLUME_TRANSFORM, "inputs": [open_cube["artifact_id"]],
                "parameters": cube_parameters}})
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            refused = await wait_job(queued["job_id"])
            assert refused["state"] in {"rejected", "failed"}, refused
            assert not refused.get("outputs"), refused

            print(f"CGAL Master Wave E MCP ({mode}) + Mesh_2, Surface_mesher and Mesh_3 independent validators: PASS")


if __name__ == "__main__":
    asyncio.run(main())
