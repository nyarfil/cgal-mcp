import asyncio
import pathlib
import tempfile
import unittest

import numpy as np
import trimesh

from cgal_mcp.file_bridge import FileBridgeRejected, simplify_file, stl_to_off
from cgal_mcp.runtime import parse_off


TRI = b"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n"
PARAMETERS = {"edge_ratio": 0.5, "tolerance": 0.1, "error_bound": 0.01}


class RejectedRuntime:
    def __init__(self):
        self.tasks = {}

    def register(self, content, unit):
        return {"asset_id": "source", "sha256": "source-hash"}

    def plan(self, asset_id, parameters):
        return {"plan_id": "plan"}

    def execute(self, plan_id):
        self.tasks["job"] = asyncio.create_task(asyncio.sleep(0))
        return {"job_id": "job"}

    def status(self, job_id):
        return {"job_id": job_id, "state": "rejected", "verification": {"verdict": "fail"}}


class AcceptedThenRejectedExportRuntime:
    """Accept simplification, then reject the post-export distance check."""
    def __init__(self, export_verdict):
        self.export_verdict = export_verdict
        self.tasks = {}
        self.next_asset = 0
        self.next_job = 0
        self.jobs = {}

    def register(self, content, unit):
        self.next_asset += 1
        return {"asset_id": f"asset-{self.next_asset}", "sha256": f"hash-{self.next_asset}"}

    def plan(self, asset_id, parameters):
        return {"plan_id": "simplify"}

    def plan_distance(self, asset_a, asset_b, parameters):
        return {"plan_id": "export-distance"}

    def execute(self, plan_id):
        self.next_job += 1
        job_id = f"job-{self.next_job}"
        self.tasks[job_id] = asyncio.create_task(asyncio.sleep(0))
        if plan_id == "simplify":
            self.jobs[job_id] = {
                "job_id": job_id, "state": "succeeded", "computation": {"ok": True},
                "verification": {"verdict": "pass"}, "artifact": {"asset_id": "candidate"},
            }
        else:
            self.jobs[job_id] = {
                "job_id": job_id, "state": "rejected",
                "verification": {"verdict": self.export_verdict},
            }
        return {"job_id": job_id}

    def status(self, job_id):
        return self.jobs[job_id]

    def artifact(self, asset_id):
        self.assert_candidate(asset_id)
        return {"off": TRI.decode("utf-8")}

    @staticmethod
    def assert_candidate(asset_id):
        if asset_id != "candidate":
            raise AssertionError("Only the accepted candidate may be fetched")


class FileBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)

    async def test_output_guards_reject_existing_and_source_path(self):
        source = self.root / "source.off"
        source.write_bytes(TRI)
        existing = self.root / "existing.off"
        existing.write_bytes(b"do not overwrite")
        runtime = RejectedRuntime()
        with self.assertRaises(FileExistsError):
            await simplify_file(source, existing, "mm", PARAMETERS, runtime)
        with self.assertRaises(ValueError):
            await simplify_file(source, source, "mm", PARAMETERS, runtime)
        self.assertEqual(existing.read_bytes(), b"do not overwrite")

    def test_stl_triangle_soup_deduplicates_only_identical_vertices(self):
        vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                             [0.0000001, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
        mesh = trimesh.Trimesh(vertices=vertices, faces=[[0, 1, 2], [3, 4, 5]], process=False)
        info = parse_off(stl_to_off(mesh.export(file_type="stl")))
        # The shared point is joined, while the nearby 1e-7 point remains a
        # separate vertex: file ingestion applies no tolerance or rounding.
        self.assertEqual(info["vertices"], 5)
        self.assertEqual(info["faces"], 2)

    async def test_rejected_runtime_never_publishes_output(self):
        source = self.root / "source.off"
        output = self.root / "result.off"
        source.write_bytes(TRI)
        with self.assertRaises(FileBridgeRejected):
            await simplify_file(source, output, "mm", PARAMETERS, RejectedRuntime())
        self.assertFalse(output.exists())

    async def test_failed_or_indeterminate_export_verification_never_publishes_stl(self):
        source = self.root / "source.off"
        source.write_bytes(TRI)
        for verdict in ("fail", "indeterminate"):
            with self.subTest(verdict=verdict):
                output = self.root / f"result-{verdict}.stl"
                with self.assertRaises(FileBridgeRejected):
                    await simplify_file(
                        source, output, "mm", PARAMETERS,
                        AcceptedThenRejectedExportRuntime(verdict),
                    )
                self.assertFalse(output.exists())
                self.assertEqual(source.read_bytes(), TRI)


if __name__ == "__main__":
    unittest.main()
