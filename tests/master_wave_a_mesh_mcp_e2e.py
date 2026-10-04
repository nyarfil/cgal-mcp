"""Official MCP client -> bounded mesh analyses -> dedicated validators."""

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


VALIDATORS = {
    "mesh.inspect.pmp": "mesh.validate.pmp_inspection_report",
    "mesh.analysis.connected_components":
        "mesh.validate.connected_components_report",
    "mesh.analysis.normals": "mesh.validate.normals_report",
    "mesh.analysis.measures": "mesh.validate.measures_report",
    "mesh.analysis.sharp_features": "mesh.validate.sharp_features_report",
    "mesh.analysis.self_intersections":
        "mesh.validate.self_intersections_report",
}


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


def write_off(path: Path, points: list[tuple[float, float, float]],
              faces: list[tuple[int, ...]]) -> None:
    lines = ["OFF", f"{len(points)} {len(faces)} 0"]
    lines.extend(f"{x:.17g} {y:.17g} {z:.17g}" for x, y, z in points)
    lines.extend(f"{len(face)} " + " ".join(map(str, face)) for face in faces)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode not in {"auto", "legacy"}:
        raise SystemExit("mode must be auto or legacy")
    executable = worker_path()
    if not executable.is_file():
        raise SystemExit(f"Master worker is missing: {executable}")

    with tempfile.TemporaryDirectory(prefix="master-wave-a-mesh-") as folder:
        root = Path(folder)
        mesh = root / "tetra.off"
        write_tetra(mesh)
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
            source = await call("cgal_artifact_import", {
                "path": str(mesh), "unit": "cm",
                "artifact_type": "TriangleSurfaceMesh"})

            reports: dict[str, tuple[dict, dict, dict]] = {}
            for index, (operation, validator) in enumerate(VALIDATORS.items()):
                parameters = ({"angle": {"value": math.pi / 3, "unit": "rad"}}
                              if operation == "mesh.analysis.sharp_features" else {})
                plan = await call("cgal_plan", {"request": {
                    "operation_id": operation,
                    "inputs": [source["artifact_id"]],
                    "parameters": parameters}})
                assert [step["operation"] for step in plan["steps"]] == [
                    operation, validator], plan
                analysis, validation = plan["steps"]
                assert analysis["role"] == "analysis"
                assert analysis["outputs"][0] == {
                    "slot": "analysis", "type": "GeometryAnalysisReport",
                    "format": "json", "unit": "none"}
                assert validation["inputs"]["candidate"]["step"] == analysis["id"]
                assert validation["inputs"]["source"]["artifact_id"] == source["artifact_id"]
                if operation == "mesh.analysis.sharp_features":
                    assert math.isclose(analysis["parameters"]["angle"]["value"], 60.0)
                    assert analysis["parameters"]["angle"]["unit"] == "deg"
                    assert validation["parameters"] == analysis["parameters"]
                    assert validation["parameter_normalization"][0]["bound_from"] == "angle"

                queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
                status = await wait_job(queued["job_id"])
                assert status["state"] == "succeeded", status
                assert status["execution_status"] == "succeeded", status
                assert status["validation_status"] == "passed", status
                assert [item["operation"] for item in status["validation"]] == [validator]
                validation_report = status["validation"][0]["report"]
                assert validation_report["status"] == "pass"
                assert validation_report["passed"] is True
                assert validation_report["validator_id"] == validator
                assert all(validation_report["checks"].values())
                assert len(status["outputs"]) == 1

                artifact = await call("cgal_artifact_inspect", {
                    "artifact_id": status["outputs"][0]["artifact_id"]})
                assert (artifact["type"], artifact["format"], artifact["unit"]) == (
                    "GeometryAnalysisReport", "json", "none")
                assert artifact["size"] <= 16 * 1024 * 1024
                exported = root / f"report-{index}.json"
                await call("cgal_artifact_export", {
                    "artifact_id": artifact["artifact_id"], "path": str(exported)})
                report = json.loads(exported.read_text(encoding="utf-8"))
                assert report["schema_version"] == 1
                assert report["source"]["artifact_id"] == source["artifact_id"]
                assert report["source"]["sha256"] == source["sha256"]
                assert report["source"]["unit"] == "cm"
                reports[operation] = (plan, artifact, report)

            assert reports["mesh.inspect.pmp"][2]["results"]["polygon_mesh_valid"] is True
            components = reports["mesh.analysis.connected_components"][2]["results"]
            assert components["component_count"] == 1
            assert components["count_unit"] == "count"
            normals = reports["mesh.analysis.normals"][2]["results"]
            assert len(normals["face_normals"]) == 4
            assert len(normals["vertex_normals"]) == 4
            assert len(normals["corner_normals"]) == 12
            assert all(item["normal"]["unit"] == "none"
                       for item in normals["face_normals"])
            measures = reports["mesh.analysis.measures"][2]["results"]
            assert measures["surface_area"]["unit"] == "cm^2"
            assert measures["signed_volume"]["unit"] == "cm^3"
            assert measures["volume_centroid"]["unit"] == "cm"
            sharp = reports["mesh.analysis.sharp_features"][2]["results"]
            assert sharp["angle"]["unit"] == "deg"
            assert math.isclose(sharp["angle"]["value"], 60.0,
                                rel_tol=0, abs_tol=1e-12)
            intersections = reports["mesh.analysis.self_intersections"][2]["results"]
            assert intersections["available"] is True
            assert intersections["pair_limit"] == 10000
            assert intersections["intersection_pair_count"] == 0

            async def execute_extra(operation: str, artifact_id: str,
                                    parameters: dict | None = None) -> dict:
                validator = VALIDATORS[operation]
                plan = await call("cgal_plan", {"request": {
                    "operation_id": operation, "inputs": [artifact_id],
                    "parameters": parameters or {}}})
                assert [step["operation"] for step in plan["steps"]] == [
                    operation, validator], plan
                queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
                status = await wait_job(queued["job_id"])
                assert status["state"] == "succeeded", status
                assert status["validation_status"] == "passed", status
                destination = root / (operation.replace(".", "-") + "-" +
                                      artifact_id[-8:] + ".json")
                await call("cgal_artifact_export", {
                    "artifact_id": status["outputs"][0]["artifact_id"],
                    "path": str(destination)})
                return json.loads(destination.read_text(encoding="utf-8"))

            # PMP inspection is the sole analysis that honestly accepts raw
            # polygon soups.  Other analyses retain TriangleSurfaceMesh gates.
            soup_fixtures = {
                "degenerate.off": (
                    [(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1, 2)]),
                "quad.off": (
                    [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                    [(0, 1, 2, 3)]),
                "same-direction-edge.off": (
                    [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0)],
                    [(0, 1, 2), (0, 1, 3)]),
            }
            for name, (points, faces) in soup_fixtures.items():
                path = root / name
                write_off(path, points, faces)
                soup = await call("cgal_artifact_import", {
                    "path": str(path), "unit": "mm"})
                assert soup["type"] == "PolygonSoup3", soup
                inspection = await execute_extra("mesh.inspect.pmp", soup["artifact_id"])
                assert inspection["source"]["type"] == "PolygonSoup3"
                assert inspection["analysis_kind"] == "pmp_inspection"

            nonmanifold_path = root / "nonmanifold.off"
            write_off(nonmanifold_path,
                      [(0, 0, 0), (1, 0, 0), (0, 1, 0),
                       (-1, 0, 0), (0, -1, 0)],
                      [(0, 1, 2), (0, 3, 4)])
            nonmanifold = await call("cgal_artifact_import", {
                "path": str(nonmanifold_path), "unit": "mm"})
            assert nonmanifold["type"] == "TriangleSurfaceMesh", nonmanifold
            inspected_nonmanifold = await execute_extra(
                "mesh.inspect.pmp", nonmanifold["artifact_id"])
            assert inspected_nonmanifold["mesh_summary"][
                "surface_mesh_constructible"] is True
            assert inspected_nonmanifold["results"]["non_manifold_vertex_count"] == 1

            tiny_path = root / "tiny.off"
            tiny_scale = 1e-200
            tiny_points = [(0, 0, 0), (tiny_scale, 0, 0),
                           (0, tiny_scale, 0), (0, 0, tiny_scale)]
            tetra_faces = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]
            write_off(tiny_path, tiny_points, tetra_faces)
            tiny = await call("cgal_artifact_import", {
                "path": str(tiny_path), "unit": "mm"})
            assert tiny["type"] == "TriangleSurfaceMesh", tiny
            tiny_normals = await execute_extra(
                "mesh.analysis.normals", tiny["artifact_id"])
            assert all(item["normal"]["is_unit"]
                       for item in tiny_normals["results"]["face_normals"])
            tiny_measures = await execute_extra(
                "mesh.analysis.measures", tiny["artifact_id"])
            assert tiny_measures["results"]["surface_area"]["available"] is False
            assert tiny_measures["results"]["surface_area"]["reason"] == \
                "BINARY64_RESULT_NOT_REPRESENTABLE"

            # Two coincident outward shells are edge-manifold but geometrically
            # self-intersecting.  Volume and centroid must remain unavailable.
            overlap_path = root / "coincident-shells.off"
            base_points = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
            write_off(overlap_path, base_points + base_points,
                      tetra_faces + [tuple(index + 4 for index in face)
                                     for face in tetra_faces])
            overlap = await call("cgal_artifact_import", {
                "path": str(overlap_path), "unit": "cm"})
            assert overlap["type"] == "TriangleSurfaceMesh", overlap
            overlap_measures = await execute_extra(
                "mesh.analysis.measures", overlap["artifact_id"])
            for field in ("signed_volume", "absolute_volume", "volume_centroid"):
                assert overlap_measures["results"][field]["available"] is False
                assert overlap_measures["results"][field]["reason"] == \
                    "SELF_INTERSECTING_MESH"
            overlap_intersections = await execute_extra(
                "mesh.analysis.self_intersections", overlap["artifact_id"])
            assert overlap_intersections["results"]["does_self_intersect"] is True
            assert overlap_intersections["results"]["intersection_pair_count"] > 0

            # A syntactically valid but modified report remains quarantined behind
            # its dedicated validator and never becomes a worker-produced output.
            normals_path = root / "tampered-normals.json"
            tampered = json.loads(json.dumps(reports["mesh.analysis.normals"][2]))
            tampered["results"]["face_normals"][0]["normal"]["value"] = [1, 0, 0]
            normals_path.write_text(json.dumps(tampered), encoding="utf-8")
            candidate = await call("cgal_artifact_import", {
                "path": str(normals_path), "unit": "none",
                "artifact_type": "GeometryAnalysisReport"})
            rejected_plan = await call("cgal_plan", {"request": {"steps": [{
                "id": "validate", "operation": "mesh.validate.normals_report",
                "inputs": {"candidate": candidate["artifact_id"],
                           "source": source["artifact_id"]},
                "parameters": {}}]}})
            rejected_job = await call("cgal_execute", {
                "plan_id": rejected_plan["plan_id"]})
            rejected = await wait_job(rejected_job["job_id"])
            assert rejected["state"] in {"rejected", "failed"}, rejected
            assert rejected["validation_status"] in {"failed", "not_run"}, rejected
            assert not rejected.get("outputs"), rejected

            print(f"CGAL Master Wave A mesh MCP ({mode}) + 6 dedicated validators: PASS")


if __name__ == "__main__":
    asyncio.run(main())
