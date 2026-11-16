"""Experimental execution of caller-supplied C++: opt-in, resource limited, results unverified."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from cgal_mcp.master.errors import InvalidInput, MasterError
from cgal_mcp.master.experimental import ExperimentalRunner, WARNING
from cgal_mcp.master.runtime import MasterRuntime

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests/fixtures/master/wave_a_boolean/sphere_general_a.off"
OUTPUT = [{"file": "result.off", "artifact_type": "TriangleSurfaceMesh", "unit": "mm"}]
COMPILER = None if os.name == "nt" else (shutil.which("g++") or shutil.which("clang++"))

# No CGAL header: the copy-and-scale program only needs a C++17 compiler.
SCALE = r'''
#include <cstdlib>
#include <fstream>
#include <string>
int main() {
  const std::string in = std::getenv("CGAL_IN"), out = std::getenv("CGAL_OUT");
  std::ifstream source(in + "/mesh.off");
  std::ofstream target(out + "/result.off");
  std::string header;
  std::size_t vertices = 0, faces = 0, edges = 0;
  source >> header >> vertices >> faces >> edges;
  target.precision(17);
  target << header << "\n" << vertices << " " << faces << " 0\n";
  for (std::size_t i = 0; i < vertices; ++i) {
    double x, y, z;
    source >> x >> y >> z;
    target << 2 * x << " " << 2 * y << " " << 2 * z << "\n";
  }
  for (std::size_t i = 0; i < faces; ++i) {
    std::size_t n, a, b, c;
    source >> n >> a >> b >> c;
    target << "3 " << a << " " << b << " " << c << "\n";
  }
  return source && target ? 0 : 2;
}
'''


class ExperimentalDisabledTests(unittest.TestCase):
    def test_off_by_default_and_refused_with_a_typed_error(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = MasterRuntime(Path(directory) / "store", require_memory_limit=False, experimental=False)
            try:
                self.assertIsNone(runtime.experimental)
                with self.assertRaises(MasterError) as raised:
                    runtime.experimental_run("int main(){}", {}, OUTPUT)
                self.assertEqual(raised.exception.code, "experimental_disabled")
                self.assertEqual(raised.exception.failure_class, "unsupported_adapter")
            finally:
                runtime.close()

    def test_environment_switch_needs_a_compile_command(self):
        saved = {key: os.environ.pop(key, None) for key in
                 ("CGAL_MASTER_EXPERIMENTAL", "CGAL_MASTER_EXPERIMENTAL_COMPILE", "CGAL_MASTER_EXPERIMENTAL_INCLUDE")}
        try:
            self.assertIsNone(ExperimentalRunner.from_environment(None, max_memory_mb=512, max_wall_time_ms=1000))
            os.environ["CGAL_MASTER_EXPERIMENTAL"] = "1"
            with self.assertRaises(ValueError):
                ExperimentalRunner.from_environment(None, max_memory_mb=512, max_wall_time_ms=1000)
            os.environ["CGAL_MASTER_EXPERIMENTAL_COMPILE"] = '["cxx", "{source}", "-o", "{output}"]'
            runner = ExperimentalRunner.from_environment(None, max_memory_mb=512, max_wall_time_ms=1000)
            self.assertEqual(runner.describe()["result_verification"], "none")
            os.environ["CGAL_MASTER_EXPERIMENTAL_COMPILE"] = '["cxx", "{source}"]'
            with self.assertRaises(ValueError):
                ExperimentalRunner.from_environment(None, max_memory_mb=512, max_wall_time_ms=1000)
        finally:
            for key, value in saved.items():
                os.environ.pop(key, None)
                if value is not None:
                    os.environ[key] = value


@unittest.skipUnless(COMPILER, "no POSIX C++ compiler for the experimental mode")
class ExperimentalRunTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = MasterRuntime(Path(self.directory.name) / "store", require_memory_limit=False,
                                     experimental=False)
        self.runtime.experimental = ExperimentalRunner(
            self.runtime.store, compile_command=[COMPILER, "-std=c++17", "-O1", "{source}", "-o", "{output}"],
            max_memory_mb=1024, max_wall_time_ms=60000)
        self.mesh = self.runtime.artifact_import(str(FIXTURE), "mm", artifact_type="TriangleSurfaceMesh")

    def tearDown(self):
        self.runtime.close()
        self.directory.cleanup()

    def run_source(self, source, **kwargs):
        return self.runtime.experimental_run(source, kwargs.pop("inputs", {"mesh": self.mesh["artifact_id"]}),
                                             kwargs.pop("outputs", OUTPUT), kwargs.pop("execution", None))

    def test_output_is_imported_as_an_unverified_artifact(self):
        result = self.run_source(SCALE)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["verification"], "unverified")
        self.assertEqual(result["warning"], WARNING)
        output = result["outputs"][0]
        inspection = self.runtime.artifact_inspect(output["artifact_id"])
        self.assertEqual(inspection["verification"], "unverified")
        self.assertEqual(inspection["producer"]["kind"], "experimental_unverified")
        self.assertIs(inspection["producer"]["verified"], False)
        self.assertEqual(inspection["producer"]["inputs"], {"mesh": self.mesh["sha256"]})
        self.assertEqual(inspection["metadata"]["faces"], self.mesh["metadata"]["faces"])
        self.assertAlmostEqual(inspection["metadata"]["bounds"][0][1], 20.0, places=6)
        # The source artifact is untouched and is not reported as unverified.
        self.assertEqual(self.runtime.artifact_inspect(self.mesh["artifact_id"])["verification"], "imported_not_checked")
        self.assertEqual(list(self.runtime.store.staging_root.iterdir()), [])

    def test_compile_failure_run_failure_and_timeout_publish_nothing(self):
        before = self.runtime.store.counts()["artifacts"]
        failed = self.run_source("int main() { return 1 }")
        self.assertEqual(failed["status"], "compile_failed")
        self.assertIn("error", failed["compiler_output"])
        crashed = self.run_source("int main() { return 3; }")
        self.assertEqual((crashed["status"], crashed["exit_code"]), ("run_failed", 3))
        hung = self.run_source("int main() { for (;;) {} }", execution={"wall_time_ms": 1500})
        self.assertEqual(hung["status"], "run_timeout")
        self.assertLess(hung["run_seconds"], 10)
        for result in (failed, crashed, hung):
            self.assertEqual(result["outputs"], [])
        self.assertEqual(self.runtime.store.counts()["artifacts"], before)
        self.assertEqual(list(self.runtime.store.staging_root.iterdir()), [])

    def test_missing_or_malformed_output_is_reported_not_imported(self):
        missing = self.run_source("int main() { return 0; }")
        self.assertEqual(missing["status"], "completed_with_missing_outputs")
        self.assertEqual(missing["output_problems"][0]["problem"], "not written by the program")
        garbage = self.run_source('#include <cstdlib>\n#include <fstream>\n#include <string>\nint main() { '
                                  'std::ofstream(std::string(std::getenv("CGAL_OUT")) + "/result.off") << "not a mesh"; }')
        self.assertEqual(garbage["status"], "completed_with_missing_outputs")
        self.assertEqual(garbage["outputs"], [])

    def test_memory_limit_stops_the_program(self):
        greedy = ('#include <cstdlib>\n#include <cstring>\nint main() { for (;;) { void* p = std::malloc(64u << 20); '
                  'if (!p) return 7; std::memset(p, 1, 64u << 20); } }')
        result = self.run_source(greedy, execution={"memory_mb": 128, "wall_time_ms": 20000})
        self.assertEqual(result["status"], "run_failed", result)
        self.assertEqual(result["outputs"], [])

    def test_malformed_requests_are_refused_before_compiling(self):
        for arguments in (
                {"source": ""}, {"source": SCALE, "inputs": {"Bad Name": self.mesh["artifact_id"]}},
                {"source": SCALE, "outputs": [{"file": "../x.off", "artifact_type": "TriangleSurfaceMesh", "unit": "mm"}]},
                {"source": SCALE, "outputs": [{"file": "x.exe", "artifact_type": "TriangleSurfaceMesh", "unit": "mm"}]},
                {"source": SCALE, "outputs": []},
                {"source": SCALE, "execution": {"wall_time_ms": 10 ** 9}},
                {"source": SCALE, "execution": {"network": True}}):
            with self.subTest(arguments=str(arguments)[:60]):
                with self.assertRaises(InvalidInput):
                    self.runtime.experimental_run(arguments["source"],
                                                  arguments.get("inputs", {"mesh": self.mesh["artifact_id"]}),
                                                  arguments.get("outputs", OUTPUT), arguments.get("execution"))
        with self.assertRaises(InvalidInput):
            self.run_source(SCALE, inputs={"mesh": "art_unknown"})


if __name__ == "__main__":
    unittest.main()
