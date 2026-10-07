"""Official MCP client -> Wave C 2D/triangulation/spatial operations -> independent validators."""

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
WAVE_C = ROOT / "tests" / "fixtures" / "master" / "wave_c"
BOOLEAN = ROOT / "tests" / "fixtures" / "master" / "wave_a_boolean"
RADIUS = {"radius": {"value": 0.5, "unit": "mm"}}

# operation -> (validator, [(fixture, artifact type)], parameters, expected output type)
CASES = {
    "hull.convex_2": ("hull.validate.convex_enclosure_2",
                      [(WAVE_C / "planar_points.json", "PointSet2")], {}, "Polygon2"),
    "polygon.analysis.properties": ("polygon.validate.properties_report",
                      [(WAVE_C / "polygon_with_hole.json", "PolygonWithHoles2")], {},
                      "Polygon2AnalysisReport"),
    "polygon.query.containment": ("polygon.validate.containment_report",
                      [(WAVE_C / "polygon_with_hole.json", "PolygonWithHoles2"),
                       (WAVE_C / "containment_queries.json", "PointSet2")], {},
                      "Polygon2AnalysisReport"),
    "triangulation.delaunay_2": ("triangulation.validate.delaunay_2",
                      [(WAVE_C / "planar_points.json", "PointSet2")], {}, "Triangulation2"),
    "triangulation.constrained_2": ("triangulation.validate.constrained_2",
                      [(WAVE_C / "constraint_graph.json", "SegmentGraph2")],
                      {"delaunay": True}, "Triangulation2"),
    "triangulation.delaunay_3": ("triangulation.validate.delaunay_3",
                      [(WAVE_C / "cloud_points.xyz", "PointSet3")], {}, "Triangulation3"),
    "spatial.knn_3": ("spatial.validate.knn_report",
                      [(WAVE_C / "cloud_points.xyz", "PointSet3"),
                       (WAVE_C / "query_points.xyz", "PointSet3")],
                      {"k": 5, "search": "orthogonal"}, "SpatialQueryReport"),
    "spatial.range_search_3": ("spatial.validate.range_report",
                      [(WAVE_C / "cloud_points.xyz", "PointSet3"),
                       (WAVE_C / "query_points.xyz", "PointSet3")], RADIUS, "SpatialQueryReport"),
    "spatial.bbox_2": ("spatial.validate.bbox_report",
                      [(WAVE_C / "planar_points.json", "PointSet2")], {}, "SpatialQueryReport"),
    "spatial.bbox_3": ("spatial.validate.bbox_report",
                      [(BOOLEAN / "cube_a.off", "TriangleSurfaceMesh")], {}, "SpatialQueryReport"),
    "spatial.aabb.closest_points": ("spatial.validate.closest_points_report",
                      [(BOOLEAN / "cube_a.off", "TriangleSurfaceMesh"),
                       (WAVE_C / "mesh_queries.xyz", "PointSet3")], {}, "SpatialQueryReport"),
    "spatial.aabb.ray_first_hits": ("spatial.validate.ray_hits_report",
                      [(BOOLEAN / "cube_a.off", "TriangleSurfaceMesh"),
                       (WAVE_C / "cube_rays.json", "RayBatch3")], {}, "SpatialQueryReport"),
}


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode not in {"auto", "legacy"}:
        raise SystemExit("mode must be auto or legacy")
    executable = worker_path()
    if not executable.is_file():
        raise SystemExit(f"Master worker is missing: {executable}")

    with tempfile.TemporaryDirectory(prefix="master-wave-c-") as folder:
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
            sources: dict[str, list[dict]] = {}
            for index, (operation, (validator, fixtures, parameters, output_type)) in enumerate(
                    CASES.items()):
                unit = ("mm", "cm", "m")[index % 3]
                imported = []
                for path, artifact_type in fixtures:
                    artifact = await call("cgal_artifact_import", {
                        "path": str(path), "unit": unit, "artifact_type": artifact_type})
                    assert artifact["type"] == artifact_type, artifact
                    imported.append(artifact)
                sources[operation] = imported
                plan = await call("cgal_plan", {"request": {
                    "operation_id": operation,
                    "inputs": [item["artifact_id"] for item in imported],
                    "parameters": parameters}})
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
                assert output["type"] == output_type and output["format"] == "json", output
                expected_unit = "none" if output_type.endswith("Report") else unit
                assert output["unit"] == expected_unit, output
                outputs[operation] = output
                for artifact in imported:
                    again = await call("cgal_artifact_inspect", {"artifact_id": artifact["artifact_id"]})
                    assert again["sha256"] == artifact["sha256"]

            # A tampered analysis report is rejected behind its mandatory independent validator.
            operation = "spatial.knn_3"
            validator, _, parameters, _ = CASES[operation]
            exported = root / "knn.json"
            await call("cgal_artifact_export", {
                "artifact_id": outputs[operation]["artifact_id"], "path": str(exported)})
            report = json.loads(exported.read_text(encoding="utf-8"))
            neighbors = report["results"][0]["neighbors"]
            neighbors[0]["index"], neighbors[-1]["index"] = neighbors[-1]["index"], neighbors[0]["index"]
            exported.write_text(json.dumps(report), encoding="utf-8")
            candidate = await call("cgal_artifact_import", {
                "path": str(exported), "unit": "none", "artifact_type": "SpatialQueryReport"})
            points, queries = sources[operation]
            plan = await call("cgal_plan", {"request": {"steps": [{
                "id": "validate", "operation": validator,
                "inputs": {"candidate": candidate["artifact_id"], "points": points["artifact_id"],
                           "queries": queries["artifact_id"]},
                "parameters": parameters}]}})
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
            rejected = await wait_job(queued["job_id"])
            assert rejected["state"] in {"rejected", "failed"}, rejected
            assert not rejected.get("outputs"), rejected

            print(f"CGAL Master Wave C MCP ({mode}) + 11 independent validators: PASS")


if __name__ == "__main__":
    asyncio.run(main())
