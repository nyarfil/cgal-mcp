"""Persistent worker pool (session protocol 1) and validated result cache."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cgal_mcp.master.result_cache import ResultCache
from cgal_mcp.master.supervisor import PersistentPolicy

REPO = Path(__file__).resolve().parents[1]
WORKER = REPO / "build-master/Release/cgal-master-worker.exe"


def _outputs(directory: Path, content: bytes = b"OFF\n0 0 0\n") -> list[dict]:
    path = directory / "result.off"
    path.write_bytes(content)
    return [{"slot": "geometry", "type": "TriangleSurfaceMesh", "format": "off", "unit": "mm",
             "path": str(path)}]


class ResultCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cache = ResultCache(self.root / "cache", registry_revision="r1")
        self.key = "a" * 64
        work = self.root / "work"; work.mkdir()
        self.cache.store(self.key, worker_sha256="w1", operation="op", outputs=_outputs(work),
                         metrics={"m": 1}, diagnostics=[], verdicts=[{"operation": "v", "status": "pass"}])

    def tearDown(self):
        self._tmp.cleanup()

    def lookup(self, worker="w1"):
        destination = self.root / f"dest{len(list(self.root.glob('dest*')))}"
        destination.mkdir()
        return self.cache.lookup(self.key, worker, destination), destination

    def test_hit_copies_verified_outputs_and_keeps_verdicts(self):
        body, destination = self.lookup()
        self.assertIsNotNone(body)
        self.assertEqual((destination / "result.off").read_bytes(), b"OFF\n0 0 0\n")
        self.assertEqual(body["validator_verdicts"][0]["status"], "pass")
        self.assertEqual(self.cache.stats["hits"], 1)

    def test_tampered_entry_is_a_miss_and_dropped(self):
        entry = self.cache.entries / f"{self.key}.json"
        data = json.loads(entry.read_text(encoding="utf-8"))
        data["body"]["metrics"] = {"forged": True}
        entry.write_text(json.dumps(data), encoding="utf-8")
        body, _ = self.lookup()
        self.assertIsNone(body)
        self.assertFalse(entry.exists())
        self.assertEqual(self.cache.stats["rejected_tampered"], 1)

    def test_tampered_blob_is_a_miss_and_leaves_no_output(self):
        blob = next(self.cache.blobs.iterdir())
        blob.write_bytes(b"corrupt")
        body, destination = self.lookup()
        self.assertIsNone(body)
        self.assertFalse((destination / "result.off").exists())

    def test_worker_or_registry_change_never_hits(self):
        body, _ = self.lookup(worker="w2")
        self.assertIsNone(body)
        work = self.root / "w2"; work.mkdir()
        self.cache.store(self.key, worker_sha256="w1", operation="op", outputs=_outputs(work),
                         metrics={}, diagnostics=[], verdicts=[])
        reopened = ResultCache(self.cache.root, registry_revision="r2")
        self.assertEqual(reopened.usage(), (0, 0))
        self.assertEqual(reopened.stats["rejected_stale"], 1)

    def test_key_binds_operation_parameters_inputs_registry_and_worker(self):
        operation = {"id": "op", "revision": "1"}
        step = {"kernel": "epeck", "parameters": {"a": 1}}
        inputs = [{"type": "PointSet3", "unit": "mm", "format": "xyz", "sha256": "0" * 64}]
        base = self.cache.key(operation=operation, step=step, inputs=inputs, worker_sha256="w", cgal_version="6.2.1")
        variants = [
            self.cache.key(operation={"id": "op", "revision": "2"}, step=step, inputs=inputs, worker_sha256="w", cgal_version="6.2.1"),
            self.cache.key(operation=operation, step={**step, "parameters": {"a": 2}}, inputs=inputs, worker_sha256="w", cgal_version="6.2.1"),
            self.cache.key(operation=operation, step=step, inputs=[{**inputs[0], "unit": "m"}], worker_sha256="w", cgal_version="6.2.1"),
            self.cache.key(operation=operation, step=step, inputs=inputs, worker_sha256="x", cgal_version="6.2.1"),
            ResultCache(self.root / "other", registry_revision="r9").key(
                operation=operation, step=step, inputs=inputs, worker_sha256="w", cgal_version="6.2.1"),
        ]
        self.assertEqual(len({base, *variants}), 6)

    def test_eviction_respects_the_entry_bound(self):
        bounded = ResultCache(self.root / "bounded", registry_revision="r1", max_entries=2)
        for index in range(3):
            work = self.root / f"e{index}"; work.mkdir()
            bounded.store(f"{index:064d}", worker_sha256="w", operation="op",
                          outputs=_outputs(work, f"OFF {index}\n".encode()), metrics={}, diagnostics=[], verdicts=[])
        self.assertEqual(bounded.usage()[0], 2)
        self.assertEqual(bounded.stats["evicted"], 1)
        self.assertEqual(len(list(bounded.blobs.iterdir())), 2)


class PersistentPolicyTests(unittest.TestCase):
    def test_default_is_one_shot_and_environment_is_validated(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CGAL_MASTER_PERSISTENT_WORKERS", None)
            self.assertIsNone(PersistentPolicy.from_environment(2))
        with patch.dict(os.environ, {"CGAL_MASTER_PERSISTENT_WORKERS": "1"}):
            self.assertEqual(PersistentPolicy.from_environment(3).max_idle_workers, 3)
        with patch.dict(os.environ, {"CGAL_MASTER_PERSISTENT_WORKERS": "yes"}):
            with self.assertRaises(ValueError):
                PersistentPolicy.from_environment(2)
        with self.assertRaises(ValueError):
            PersistentPolicy(max_jobs_per_worker=0)


@unittest.skipUnless(WORKER.is_file(), "native worker is not built")
class PersistentWorkerLiveTests(unittest.TestCase):
    def test_session_protocol_ping_and_shutdown(self):
        lines = (b'{"control":"ping","request_id":"p1"}\n{"control":"ping","request_id":"p2"}\n'
                 b'{"control":"shutdown"}\n{"control":"ping","request_id":"never"}\n')
        done = subprocess.run([str(WORKER), "--serve"], input=lines, capture_output=True, timeout=60)
        replies = [json.loads(row) for row in done.stdout.splitlines()]
        self.assertEqual(done.returncode, 0)
        self.assertEqual([r["request_id"] for r in replies], ["p1", "p2"])
        self.assertTrue(all(r["status"] == "pong" and r["session_protocol"] == 1 for r in replies))

    def test_one_shot_mode_still_rejects_multiple_requests(self):
        request = b'{"protocol":1,"request_id":"a"}\n{"protocol":1,"request_id":"b"}\n'
        done = subprocess.run([str(WORKER)], input=request, capture_output=True, timeout=60)
        self.assertIn(b"MULTIPLE_REQUESTS", done.stdout)

    def test_runtime_reuses_one_process_and_cache_hits_revalidate(self):
        from scripts import measure_master_robustness as rob
        from cgal_mcp.master.runtime import MasterRuntime

        async def scenario(root: Path):
            runtime = MasterRuntime(root / "store", worker=WORKER, persistent_workers=True, result_cache=True)
            try:
                imported = rob._import_inputs(runtime, root, [(rob._random_xyz(300, 5, cube=True), "xyz", "PointSet3", "mm")])
                plan = rob._plan(runtime, "hull.convex_3", imported, {})
                details = [await rob._run_plan(runtime, plan["plan_id"]) for _ in range(3)]
                health = await runtime.system_health()
                await runtime.supervisor.shutdown()
                return details, health
            finally:
                runtime.close()

        with tempfile.TemporaryDirectory() as directory:
            details, health = asyncio.run(scenario(Path(directory)))
        self.assertTrue(all(d["state"] == "succeeded" and d["validation_status"] == "passed" for d in details))
        self.assertEqual(len({tuple(o["sha256"] for o in d["outputs"]) for d in details}), 1)
        self.assertEqual(health["worker_pool"]["mode"], "persistent")
        self.assertEqual(health["worker_pool"]["started"], 1)
        self.assertGreater(health["worker_pool"]["reused"], 0)
        self.assertEqual(health["result_cache"]["hits"], 2)


if __name__ == "__main__":
    unittest.main()
