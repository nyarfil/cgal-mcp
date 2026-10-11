"""Persistent-worker parsed-mesh / AABB-tree reuse (native --serve session cache)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cgal_mcp.master.supervisor import PersistentPolicy

REPO = Path(__file__).resolve().parents[1]
WORKER = REPO / "build-master/Release/cgal-master-worker.exe"


def grid(side: int, bump: float) -> bytes:
    import math
    rows = [f"OFF\n{(side + 1) ** 2} {2 * side * side} 0"]
    for i in range(side + 1):
        for j in range(side + 1):
            rows.append(f"{j} {i} {bump * math.sin(i * 0.37) * math.cos(j * 0.23):.9f}")
    for i in range(side):
        for j in range(side):
            a = i * (side + 1) + j
            rows.append(f"3 {a} {a + 1} {a + side + 2}")
            rows.append(f"3 {a} {a + side + 2} {a + side + 1}")
    return ("\n".join(rows) + "\n").encode("ascii")


def points(count: int, seed: int, side: int) -> bytes:
    import random
    rng = random.Random(seed)
    return "".join(f"{rng.uniform(0, side):.9f} {rng.uniform(0, side):.9f} {rng.uniform(-.5, .5):.9f}\n"
                   for _ in range(count)).encode("ascii")


class Session:
    """Raw session-protocol client for one `--serve` worker."""

    def __init__(self, root: Path, env: dict | None = None, serve: bool = True):
        self.root, self.counter = root, 0
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("CGAL_MASTER_SESSION_CACHE")}
        environment.update(env or {})
        self.process = subprocess.Popen([str(WORKER)] + (["--serve"] if serve else []),
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env=environment)

    def artifact(self, name: str, content: bytes, kind: str, fmt: str, declared: str | None = None) -> dict:
        path = self.root / name
        path.write_bytes(content)
        return {"artifact_id": name.replace(".", "_"), "type": kind, "unit": "mm", "format": fmt,
                "path": str(path), "sha256": declared or hashlib.sha256(content).hexdigest()}

    def request(self, operation: str, inputs: list[dict], parameters: dict | None = None) -> dict:
        self.counter += 1
        output = self.root / f"out{self.counter}"
        output.mkdir()
        body = {"protocol": 1, "request_id": f"r{self.counter}", "operation": operation,
                "kernel": "package_recommended", "inputs": inputs, "parameters": parameters or {},
                "output_dir": str(output), "limits": {"wall_time_ms": 60000, "memory_mb": 1024}}
        self.process.stdin.write((json.dumps(body) + "\n").encode())
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        response["_hashes"] = [hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
                               for item in response.get("outputs", [])]
        return response

    def close(self) -> None:
        self.process.stdin.close()
        self.process.wait(timeout=30)
        self.process.stdout.close()
        self.process.stderr.close()


@unittest.skipUnless(WORKER.is_file(), "native worker is not built")
class GeometryCacheNativeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.sessions: list[Session] = []

    def tearDown(self):
        for session in self.sessions:
            session.close()
        self._tmp.cleanup()

    def session(self, **kwargs) -> Session:
        directory = self.root / f"s{len(self.sessions)}"
        directory.mkdir()
        session = Session(directory, **kwargs)
        self.sessions.append(session)
        return session

    def closest(self, session: Session, mesh: dict, seed: int, side: int = 12) -> dict:
        queries = session.artifact(f"q{session.counter}.xyz", points(25, seed, side), "PointSet3", "xyz")
        return session.request("spatial.aabb.closest_points", [mesh, queries])

    @staticmethod
    def stats(response: dict) -> dict:
        return response["metrics"].get("session_cache", {})

    def test_disabled_by_default_and_in_one_shot_mode(self):
        session = self.session()
        mesh = session.artifact("m.off", grid(12, 0.3), "TriangleSurfaceMesh", "off")
        response = self.closest(session, mesh, 1)
        self.assertEqual(response["status"], "ok")
        self.assertNotIn("session_cache", response["metrics"])
        one_shot = self.session(serve=False)
        mesh2 = one_shot.artifact("m.off", grid(12, 0.3), "TriangleSurfaceMesh", "off")
        queries = one_shot.artifact("q.xyz", points(25, 1, 12), "PointSet3", "xyz")
        body = {"protocol": 1, "request_id": "o1", "operation": "spatial.aabb.closest_points",
                "kernel": "package_recommended", "inputs": [mesh2, queries], "parameters": {},
                "output_dir": str(one_shot.root / "o"), "limits": {"wall_time_ms": 60000, "memory_mb": 1024}}
        (one_shot.root / "o").mkdir()
        out, _ = one_shot.process.communicate(json.dumps(body).encode() + b"\n", timeout=60)
        self.assertNotIn(b"session_cache", out)
        self.assertEqual(json.loads(out)["status"], "ok")

    def test_hit_miss_counters_and_bit_identical_results(self):
        warm = self.session(env={"CGAL_MASTER_SESSION_CACHE_MB": "64"})
        cold = self.session()
        mesh_warm = warm.artifact("m.off", grid(12, 0.3), "TriangleSurfaceMesh", "off")
        mesh_cold = cold.artifact("m.off", grid(12, 0.3), "TriangleSurfaceMesh", "off")
        sequence = []
        for seed in (1, 2, 1, 3):
            a = self.closest(warm, mesh_warm, seed)
            b = self.closest(cold, mesh_cold, seed)
            self.assertEqual(a["status"], "ok", a)
            sequence.append("hit" if self.stats(a)["hits"] else "miss")
            self.assertEqual(a["_hashes"], b["_hashes"], "cached answer differs from the cold answer")
        self.assertEqual(sequence, ["miss", "hit", "hit", "hit"])
        self.assertEqual(self.stats(a)["entries"], 1)

    def test_other_content_hash_is_never_shared(self):
        warm = self.session(env={"CGAL_MASTER_SESSION_CACHE_MB": "64"})
        first = warm.artifact("a.off", grid(12, 0.3), "TriangleSurfaceMesh", "off")
        second = warm.artifact("b.off", grid(12, 0.31), "TriangleSurfaceMesh", "off")
        results = [self.closest(warm, first, 1), self.closest(warm, second, 1), self.closest(warm, first, 1)]
        self.assertEqual([self.stats(r)["misses"] for r in results], [1, 1, 0])
        self.assertNotEqual(results[0]["_hashes"], results[1]["_hashes"])
        self.assertEqual(results[0]["_hashes"], results[2]["_hashes"])

    def test_tampered_file_is_never_served_from_the_cache(self):
        warm = self.session(env={"CGAL_MASTER_SESSION_CACHE_MB": "64"})
        mesh = warm.artifact("m.off", grid(12, 0.3), "TriangleSurfaceMesh", "off")
        self.assertEqual(self.stats(self.closest(warm, mesh, 1))["misses"], 1)
        Path(mesh["path"]).write_bytes(grid(12, 0.5))  # content changed, declared hash is stale
        tampered = self.closest(warm, mesh, 1)
        self.assertEqual(tampered["status"], "error")
        self.assertIn("sha256", tampered["error"]["message"].lower())
        # the rewritten file under its own hash is a different key: a miss, and a different answer
        fresh = dict(mesh, sha256=hashlib.sha256(Path(mesh["path"]).read_bytes()).hexdigest())
        replaced = self.closest(warm, fresh, 1)
        self.assertEqual(replaced["status"], "ok")
        self.assertEqual(self.stats(replaced)["misses"], 1)
        self.assertEqual(self.stats(replaced)["hits"], 0)

    def test_same_bytes_with_other_declared_type_or_format_is_a_miss(self):
        warm = self.session(env={"CGAL_MASTER_SESSION_CACHE_MB": "64"})
        mesh = warm.artifact("m.off", grid(12, 0.3), "TriangleSurfaceMesh", "off")
        self.closest(warm, mesh, 1)
        retyped = dict(mesh, type="PolygonSoup3")
        response = self.closest(warm, retyped, 1)
        self.assertEqual(response["status"], "error")  # the cold-path type check still applies
        self.assertEqual(self.stats(response).get("hits", 0), 0)

    def test_lru_entry_bound_and_byte_budget(self):
        warm = self.session(env={"CGAL_MASTER_SESSION_CACHE_MB": "64", "CGAL_MASTER_SESSION_CACHE_ENTRIES": "2"})
        meshes = [warm.artifact(f"m{i}.off", grid(12, 0.3 + i / 100), "TriangleSurfaceMesh", "off") for i in range(3)]
        for mesh in meshes:
            last = self.closest(warm, mesh, 1)
        self.assertEqual(self.stats(last)["entries"], 2)
        self.assertEqual(self.stats(last)["evictions"], 1)
        again = self.closest(warm, meshes[0], 1)  # evicted first: a miss again, still correct
        self.assertEqual(self.stats(again)["misses"], 1)
        tiny = self.session(env={"CGAL_MASTER_SESSION_CACHE_MB": "1"})
        big = tiny.artifact("big.off", grid(60, 0.3), "TriangleSurfaceMesh", "off")
        response = self.closest(tiny, big, 1, side=60)
        self.assertEqual(response["status"], "ok")
        self.assertEqual(self.stats(response)["oversize_skipped"], 1)
        self.assertEqual(self.stats(response)["entries"], 0)

    def test_locate_strategies_and_operations_never_share_an_entry(self):
        cold = self.session()
        pts = points(10, 4, 10)
        rays = json.dumps({"rays": [{"origin": [3.5, 4.5, 3], "direction": [0.01, 0.02, -1]}]}).encode()
        locate = ("mesh.location.locate", "p.xyz", pts, "PointSet3", "xyz")
        for first, second in (("locate", "locate_with_AABB_tree"), ("locate_with_AABB_tree", "locate")):
            warm = self.session(env={"CGAL_MASTER_SESSION_CACHE_MB": "64"})
            order = [first, second, first, second, "locate_with_AABB_tree"]
            hits = []
            for strategy in order:
                for session in (warm, cold):
                    mesh = session.artifact("m.off", grid(10, 0.3), "TriangleSurfaceMesh", "off")
                    q = session.artifact(locate[1], locate[2], locate[3], locate[4])
                    answer = session.request(locate[0], [mesh, q], {"strategy": strategy})
                    self.assertEqual(answer["status"], "ok", answer)
                    if session is warm:
                        warm_answer = answer
                self.assertEqual(warm_answer["_hashes"], answer["_hashes"], strategy)
                info = self.stats(warm_answer)
                hits.append("hit" if info.get("hits") else "miss" if info.get("misses") else "none")
            expected = ["none", "miss", "none", "hit", "hit"] if first == "locate" else                 ["miss", "none", "hit", "none", "hit"]
            self.assertEqual(hits, expected)
        # a second operation on the same mesh is a miss and still equals the cold answer
        warm = self.session(env={"CGAL_MASTER_SESSION_CACHE_MB": "64"})
        for operation, query in (("spatial.aabb.closest_points", ("q.xyz", pts, "PointSet3", "xyz")),
                                 ("spatial.aabb.ray_first_hits", ("r.json", rays, "RayBatch3", "json")),
                                 ("spatial.aabb.intersections", ("r.json", rays, "RayBatch3", "json"))):
            answers = []
            for session in (warm, cold):
                mesh = session.artifact("m.off", grid(10, 0.3), "TriangleSurfaceMesh", "off")
                answers.append(session.request(operation, [mesh, session.artifact(*query)]))
            self.assertEqual(self.stats(answers[0])["misses"], 1, operation)
            self.assertEqual(answers[0]["_hashes"], answers[1]["_hashes"], operation)

    def test_intersections_locate_and_hausdorff_hits_match_cold(self):
        warm = self.session(env={"CGAL_MASTER_SESSION_CACHE_MB": "64"})
        cold = self.session()
        rays = json.dumps({"rays": [{"origin": [3.5, 4.5, 3], "direction": [0.01, 0.02, -1]},
                                    {"origin": [6.2, 2.1, 3], "direction": [0, 0, -1]}]}).encode()
        for operation, parameters, query in (
                ("spatial.aabb.ray_first_hits", {}, ("rays.json", rays, "RayBatch3", "json")),
                ("spatial.aabb.intersections", {}, ("rays.json", rays, "RayBatch3", "json")),
                ("mesh.location.locate", {"strategy": "locate_with_AABB_tree"},
                 ("p.xyz", points(10, 4, 10), "PointSet3", "xyz"))):
            answers = []
            for session in (warm, cold, warm):
                mesh = session.artifact("m.off", grid(10, 0.3), "TriangleSurfaceMesh", "off")
                q = session.artifact(*query)
                answers.append(session.request(operation, [mesh, q], parameters))
            self.assertTrue(all(a["status"] == "ok" for a in answers), answers)
            self.assertEqual(answers[0]["_hashes"], answers[1]["_hashes"], operation)
            self.assertEqual(answers[2]["_hashes"], answers[1]["_hashes"], operation)
            self.assertEqual(self.stats(answers[0])["misses"], 1, operation)
            self.assertEqual(self.stats(answers[2])["hits"], 1, operation)
        params = {"tolerance": {"value": 2.0, "unit": "mm"}, "error_bound": {"value": 0.05, "unit": "mm"}}
        outs = []
        for session in (warm, cold, warm):
            a = session.artifact("a.off", grid(6, 0.3), "TriangleSurfaceMesh", "off")
            b = session.artifact("b.off", grid(6, 0.33), "TriangleSurfaceMesh", "off")
            outs.append(session.request("mesh.distance.symmetric_hausdorff", [a, b], params))
        self.assertTrue(all(o["status"] == "ok" for o in outs), outs)
        self.assertEqual(outs[0]["metrics"].get("distance_estimate"), outs[1]["metrics"].get("distance_estimate"))
        self.assertEqual(outs[2]["metrics"]["distance_estimate"], outs[1]["metrics"]["distance_estimate"])
        self.assertEqual(self.stats(outs[2])["hits"], 2)


class GeometryCachePolicyTests(unittest.TestCase):
    def test_default_off_and_requires_persistent_workers(self):
        self.assertFalse(PersistentPolicy().session_cache)
        self.assertEqual(PersistentPolicy().cache_budget_bytes(1024), 0)
        with patch.dict(os.environ, {"CGAL_MASTER_SESSION_CACHE": "1"}):
            os.environ.pop("CGAL_MASTER_PERSISTENT_WORKERS", None)
            self.assertIsNone(PersistentPolicy.from_environment(2))  # persistent mode is off
        with patch.dict(os.environ, {"CGAL_MASTER_SESSION_CACHE": "1", "CGAL_MASTER_PERSISTENT_WORKERS": "1"}):
            policy = PersistentPolicy.from_environment(2)
            self.assertTrue(policy.session_cache)
            self.assertEqual(policy.cache_budget_bytes(1000), 100 * 1024 * 1024)
        with patch.dict(os.environ, {"CGAL_MASTER_SESSION_CACHE": "2", "CGAL_MASTER_PERSISTENT_WORKERS": "1"}):
            with self.assertRaises(ValueError):
                PersistentPolicy.from_environment(2)
        for bad in ({"session_cache_fraction": 0.9}, {"session_cache_entries": 0}, {"session_cache": 1}):
            with self.assertRaises(ValueError):
                PersistentPolicy(**bad)


if __name__ == "__main__":
    unittest.main()
