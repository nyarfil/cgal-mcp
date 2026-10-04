import pathlib,tempfile,unittest
from cgal_mcp.runtime import Runtime
from cgal_mcp.stellacad import Snapshot,StellaCADAdapter
from test_runtime import TRI,PARAM

class Host:
    def __init__(self):self.value=Snapshot("object","rev1",TRI,"mm");self.applied=False
    def snapshot(self,object_id):return self.value
    def apply_mesh_atomic(self,object_id,expected_revision,off,unit,metadata):
        if self.value.revision!=expected_revision:raise ValueError("Stale revision")
        self.applied=True;self.value=Snapshot(object_id,"rev2",off,unit)

class AdapterTests(unittest.TestCase):
    def test_apply_guard_and_undo_host_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=Runtime(pathlib.Path(folder),pathlib.Path("/missing"),pathlib.Path("/missing"))
            host=Host();adapter=StellaCADAdapter(host,rt);plan=adapter.prepare("object",PARAM)
            asset=rt.register(TRI,"mm")
            rt.jobs["job"]={"state":"succeeded","plan":plan,
                            "verification":{"verdict":"pass"},"artifact":asset}
            host.value=Snapshot("object","changed",TRI,"mm")
            with self.assertRaises(ValueError):adapter.apply("job")
            self.assertFalse(host.applied)
            host.value=Snapshot("object","rev1",TRI,"mm")
            adapter.apply("job");self.assertTrue(host.applied)
            with self.assertRaises(ValueError):adapter.apply("job")

    def test_identical_objects_do_not_share_apply_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            rt=Runtime(pathlib.Path(folder),pathlib.Path("/missing"),pathlib.Path("/missing"))
            host=Host();adapter=StellaCADAdapter(host,rt)
            first=adapter.prepare("object",PARAM)
            host.value=Snapshot("other","rev1",TRI,"mm")
            second=adapter.prepare("other",PARAM)
            self.assertNotEqual(first["plan_id"],second["plan_id"])
            self.assertEqual(adapter.bindings[first["plan_id"]].object_id,"object")
            self.assertEqual(adapter.bindings[second["plan_id"]].object_id,"other")
