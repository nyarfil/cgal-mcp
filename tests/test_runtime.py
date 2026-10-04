import asyncio, pathlib, tempfile, unittest
from cgal_mcp.runtime import Runtime,parse_off

TRI="OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n"
PARAM={"edge_ratio":0.5,"tolerance":0.1,"error_bound":0.01}

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime=Runtime(pathlib.Path(self.temp.name),pathlib.Path("/missing-worker"),
                             pathlib.Path("/missing-distance"))
    def test_validation_and_hashes(self):
        a=self.runtime.register(TRI,"mm")
        self.assertEqual(a["asset_id"],self.runtime.register(TRI,"mm")["asset_id"])
        self.assertNotEqual(a["asset_id"],self.runtime.register(TRI,"m")["asset_id"])
        p=self.runtime.plan(a["asset_id"],PARAM)
        p["parameters"]["edge_ratio"]=0.9
        self.assertEqual(self.runtime.plans[p["plan_id"]]["parameters"]["edge_ratio"],0.5)
        for invalid in ({**PARAM,"extra":1},{**PARAM,"edge_ratio":-1},
                        {**PARAM,"error_bound":1},{**PARAM,"constrained_edges":[[0,99]]}):
            with self.assertRaises(ValueError): self.runtime.plan(a["asset_id"],invalid)
    def test_invalid_meshes(self):
        for mesh in (TRI.replace("0 0 0","nan 0 0"),TRI.replace("3 0 1 2","3 0 0 2"),
                     TRI.replace("0 1 0","2 0 0"),TRI+"oops"):
            with self.assertRaises(ValueError): parse_off(mesh)

    def test_asset_round_trip_preserves_exact_newline_bytes(self):
        import hashlib
        for content in (TRI, TRI.replace("\n", "\r\n")):
            with self.subTest(content=repr(content)):
                asset=self.runtime.register(content,"mm")
                stored=pathlib.Path(self.runtime.assets[asset["asset_id"]]["path"])
                self.assertEqual(stored.read_bytes(),content.encode("utf-8"))
                artifact=self.runtime.artifact(asset["asset_id"])
                self.assertEqual(artifact["off"],content)
                self.assertEqual(hashlib.sha256(artifact["off"].encode()).hexdigest(),asset["sha256"])
                self.runtime.plan(asset["asset_id"],PARAM)
    def test_stale_asset_and_unknown_id(self):
        a=self.runtime.register(TRI,"mm")
        pathlib.Path(self.runtime.assets[a["asset_id"]]["path"]).write_text("changed")
        with self.assertRaises(ValueError): self.runtime.plan(a["asset_id"],PARAM)
        with self.assertRaises(KeyError): self.runtime.status("../../etc/passwd")
    async def test_missing_worker_is_failed_not_success(self):
        a=self.runtime.register(TRI,"mm");p=self.runtime.plan(a["asset_id"],PARAM)
        j=self.runtime.execute(p["plan_id"])
        await self.runtime.tasks[j["job_id"]]
        self.assertEqual(self.runtime.status(j["job_id"])["state"],"failed")
    async def test_queued_cancel(self):
        a=self.runtime.register(TRI,"mm");p=self.runtime.plan(a["asset_id"],PARAM)
        j=self.runtime.execute(p["plan_id"])
        self.assertEqual((await self.runtime.cancel(j["job_id"]))["state"],"cancelled")

    async def test_timeout_and_running_cancel_stop_process(self):
        import sys
        from unittest.mock import patch
        root=pathlib.Path(self.temp.name);script=root/"slow-worker";pidfile=root/"pid"
        script.write_text("#!/usr/bin/env python3\nimport os,time,pathlib\n"+
                          "pathlib.Path("+repr(str(pidfile))+").write_text(str(os.getpid()))\n"+
                          "time.sleep(30)\n")
        script.chmod(0o700);self.runtime.worker=script;self.runtime.timeout=2
        # Launch this Python fixture with an interpreter on both POSIX and Windows.
        # Keep real subprocesses/pipes so timeout and cancellation exercise _call.
        launch=asyncio.create_subprocess_exec
        processes=[]
        async def launch_fixture(executable, *args, **kwargs):
            proc=await launch(sys.executable, executable, *args, **kwargs)
            processes.append(proc)
            return proc
        patcher=patch("cgal_mcp.runtime.asyncio.create_subprocess_exec",side_effect=launch_fixture)
        patcher.start();self.addCleanup(patcher.stop)
        a=self.runtime.register(TRI,"mm");p=self.runtime.plan(a["asset_id"],PARAM)
        job=self.runtime.execute(p["plan_id"]);await self.runtime.tasks[job["job_id"]]
        self.assertEqual(self.runtime.status(job["job_id"])["state"],"timed_out")
        self.assertTrue(pidfile.exists())
        self.assertIsNotNone(processes[-1].returncode)
        pidfile.unlink(missing_ok=True);self.runtime.timeout=60
        job=self.runtime.execute(p["plan_id"])
        for _ in range(100):
            if pidfile.exists():break
            await asyncio.sleep(0.01)
        self.assertTrue(pidfile.exists())
        await self.runtime.cancel(job["job_id"])
        self.assertEqual(self.runtime.status(job["job_id"])["state"],"cancelled")
        self.assertIsNotNone(processes[-1].returncode)

    def test_distance_plan_requires_matching_units(self):
        a=self.runtime.register(TRI,"mm");b=self.runtime.register(TRI,"m")
        with self.assertRaises(ValueError):
            self.runtime.plan_distance(a["asset_id"],b["asset_id"],{"tolerance":0.1,"error_bound":0.01})
        p=self.runtime.plan_distance(a["asset_id"],a["asset_id"],{"tolerance":0.1,"error_bound":0.01})
        self.assertEqual(p["operation"],"hausdorff")
