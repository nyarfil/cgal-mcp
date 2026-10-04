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
