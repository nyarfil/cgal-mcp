"""Official MCP client -> PMP Booleans -> exact-bound mandatory validators."""

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
    "union": "mesh.validate.boolean_union",
    "intersection": "mesh.validate.boolean_intersection",
    "difference": "mesh.validate.boolean_difference",
}


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode not in {"auto", "legacy"}:
        raise SystemExit("mode must be auto or legacy")
    executable = worker_path()
    if not executable.is_file():
        raise SystemExit(f"Master worker is missing: {executable}")
    fixtures = Path("tests/fixtures/master/wave_a_boolean").resolve()

    with tempfile.TemporaryDirectory(prefix="master-wave-a-boolean-") as folder:
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
                for _ in range(1600):
                    status = await call("cgal_job_status", {"job_id": job_id})
                    if status["state"] not in {"queued", "running"}:
                        return status
                    await asyncio.sleep(0.05)
                raise AssertionError(f"job did not finish: {job_id}")

            async def import_mesh(name: str, unit: str = "cm") -> dict:
                return await call("cgal_artifact_import", {
                    "path": str(fixtures / name), "unit": unit,
                    "artifact_type": "TriangleSurfaceMesh"})

            async def execute(kind: str, source_a: dict, source_b: dict,
                              *, kernel: str | None = None) -> tuple[dict, dict, dict]:
                request = {"operation_id": f"mesh.boolean.{kind}",
                    "inputs": {"source_a": source_a["artifact_id"],
                               "source_b": source_b["artifact_id"]},
                    "parameters": {"operation": kind}}
                if kernel:
                    request["kernel"] = kernel
                plan = await call("cgal_plan", {"request": request})
                validator = VALIDATORS[kind]
                assert [step["operation"] for step in plan["steps"]] == [
                    f"mesh.boolean.{kind}", validator], plan
                transform, validation = plan["steps"]
                assert validation["validates"] == transform["id"]
                assert validation["inputs"]["candidate"]["step"] == transform["id"]
                assert validation["inputs"]["source_a"]["artifact_id"] == \
                    source_a["artifact_id"]
                assert validation["inputs"]["source_b"]["artifact_id"] == \
                    source_b["artifact_id"]
                assert validation["parameters"] == {"operation": kind}
                queued = await call("cgal_execute", {"plan_id": plan["plan_id"]})
                status = await wait_job(queued["job_id"])
                assert status["state"] == "succeeded", status
                assert status["execution_status"] == "succeeded", status
                assert status["validation_status"] == "passed", status
                assert len(status["validation"]) == 1
                report = status["validation"][0]["report"]
                assert report["status"] == "pass" and report["passed"] is True
                assert report["validator_id"] == validator
                assert report["operation"] == kind
                required_checks = {
                    "topology_valid", "closed_or_canonical_empty",
                    "volume_boundary_orientation_valid", "self_intersection_free",
                    "operation_parameter_bound", "result_status_matches_reference",
                    "exact_volume_matches_reference", "mutual_exact_difference_empty",
                    "operation_classification_matches",
                }
                assert all(report["checks"].get(name) is True
                           for name in required_checks), report
                assert report["bindings"]["source_a_sha256"] == source_a["sha256"]
                assert report["bindings"]["source_b_sha256"] == source_b["sha256"]
                assert len(status["outputs"]) == 1
                artifact = await call("cgal_artifact_inspect", {
                    "artifact_id": status["outputs"][0]["artifact_id"]})
                assert (artifact["type"], artifact["format"], artifact["unit"]) == (
                    "TriangleSurfaceMesh", "off", source_a["unit"])
                return plan, status, artifact

            assert len((await client.list_tools()).tools) == 12
            source_a = await import_mesh("cube_a.off")
            overlap = await import_mesh("cube_overlap.off")
            disjoint = await import_mesh("cube_disjoint.off")
            identical = await import_mesh("cube_identical.off")

            for kind in ("union", "intersection", "difference"):
                _, _, artifact = await execute(kind, source_a, overlap)
                assert artifact["metadata"]["faces"] > 0
                assert artifact["properties"]["closed"] is True

            _, empty_intersection_status, empty_intersection = await execute(
                "intersection", source_a, disjoint)
            assert empty_intersection["metadata"]["vertices"] == 0
            assert empty_intersection["metadata"]["faces"] == 0
            assert empty_intersection_status["validation"][0]["report"][
                "checks"]["closed_or_canonical_empty"] is True

            _, _, empty_difference = await execute(
                "difference", source_a, identical)
            assert empty_difference["metadata"]["vertices"] == 0
            assert empty_difference["metadata"]["faces"] == 0
            _, _, disjoint_difference = await execute(
                "difference", source_a, disjoint, kernel="exact_constructions")
            assert disjoint_difference["metadata"]["faces"] > 0

            # Mixed units are rejected by the immutable planner before dispatch.
            overlap_m = await import_mesh("cube_overlap.off", "m")
            mixed = await client.call_tool("cgal_plan", {"request": {
                "operation_id": "mesh.boolean.union",
                "inputs": [source_a["artifact_id"], overlap_m["artifact_id"]],
                "parameters": {"operation": "union"}}})
            assert mixed.is_error, mixed

            # Open volume sources plan with a recorded worker precondition, then
            # fail before any candidate or artifact can be published.
            open_mesh = await import_mesh("open_cube.off")
            open_plan = await call("cgal_plan", {"request": {
                "operation_id": "mesh.boolean.union",
                "inputs": [open_mesh["artifact_id"], disjoint["artifact_id"]],
                "parameters": {"operation": "union"}}})
            open_job = await call("cgal_execute", {"plan_id": open_plan["plan_id"]})
            open_status = await wait_job(open_job["job_id"])
            assert open_status["state"] == "failed", open_status
            assert not open_status.get("outputs"), open_status

            # An exact EPECK construction that cannot be represented losslessly
            # in binary64 OFF fails closed with no staged artifact publication.
            skew = await import_mesh("skew_tetra.off", "mm")
            fraction = await import_mesh("fraction_cut_cube.off", "mm")
            precision_plan = await call("cgal_plan", {"request": {
                "operation_id": "mesh.boolean.intersection",
                "inputs": [skew["artifact_id"], fraction["artifact_id"]],
                "parameters": {"operation": "intersection"}}})
            precision_job = await call("cgal_execute", {
                "plan_id": precision_plan["plan_id"]})
            precision_status = await wait_job(precision_job["job_id"])
            assert precision_status["state"] == "failed", precision_status
            assert precision_status["error"]["code"] == "OUTPUT_BINARY64_LOSS"
            assert not precision_status.get("outputs"), precision_status

            # A tampered but syntactically healthy candidate cannot be attached
            # to a different location while retaining the original set meaning.
            _, union_status, union_artifact = await execute("union", source_a, overlap)
            exported = root / "union.off"
            await call("cgal_artifact_export", {
                "artifact_id": union_artifact["artifact_id"], "path": str(exported)})
            tokens = exported.read_text(encoding="ascii").split()
            vertex_count = int(tokens[1])
            cursor = 4
            for _ in range(vertex_count):
                tokens[cursor] = f"{float(tokens[cursor]) + 10:.17g}"
                cursor += 3
            tampered_path = root / "tampered.off"
            # Reconstruct whitespace-free valid OFF token lines; OFF is a token format.
            tampered_path.write_text(" ".join(tokens) + "\n", encoding="ascii")
            tampered = await call("cgal_artifact_import", {
                "path": str(tampered_path), "unit": "cm",
                "artifact_type": "TriangleSurfaceMesh"})
            tampered_plan = await call("cgal_plan", {"request": {"steps": [{
                "id": "validate", "operation": "mesh.validate.boolean_union",
                "inputs": {"candidate": tampered["artifact_id"],
                           "source_a": source_a["artifact_id"],
                           "source_b": overlap["artifact_id"]},
                "parameters": {"operation": "union"}}]}})
            tampered_job = await call("cgal_execute", {
                "plan_id": tampered_plan["plan_id"]})
            tampered_status = await wait_job(tampered_job["job_id"])
            assert tampered_status["state"] in {"rejected", "failed"}, tampered_status
            assert not tampered_status.get("outputs"), tampered_status

            after_a = await call("cgal_artifact_inspect", {
                "artifact_id": source_a["artifact_id"]})
            assert after_a["sha256"] == source_a["sha256"]
            assert union_status["outputs"][0]["unit"] == "cm"
            print(f"CGAL Master Wave A Boolean MCP ({mode}) + exact validators: PASS")


if __name__ == "__main__":
    asyncio.run(main())
