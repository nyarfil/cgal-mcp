import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch
from cgal_mcp.runtime import worker_path


class WorkerPathTests(unittest.TestCase):
    def test_override_and_release_build_resolution(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root=pathlib.Path(temporary.name)
        previous=pathlib.Path.cwd()
        os.chdir(root)
        self.addCleanup(os.chdir,previous)
        try:
            with patch.dict(os.environ,{"CGAL_MCP_WORKER":"custom/worker"}):
                self.assertEqual(worker_path("worker"),pathlib.Path("custom/worker"))
            with patch.dict(os.environ,{},clear=True):
                filename="cgal-worker"+(".exe" if os.name=="nt" else "")
                direct=pathlib.Path("build")/filename
                release=direct.parent/"Release"/filename
                self.assertEqual(worker_path("worker"),direct)
                release.parent.mkdir(parents=True)
                release.touch()
                self.assertEqual(worker_path("worker"),release)
                direct.touch()
                self.assertEqual(worker_path("worker"),direct)
        finally:
            os.chdir(previous)
