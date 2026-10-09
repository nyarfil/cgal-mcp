"""Every registry operation that the built worker declares must verify against the built manifest."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from cgal_mcp.master.errors import InvalidInput
from cgal_mcp.master.registry import EXECUTABLE_STATUSES, OperationRegistry

WORKER = Path(__file__).resolve().parents[1] / "build-master" / "Release" / "cgal-master-worker.exe"


@unittest.skipUnless(WORKER.exists(), "built master worker is absent")
class BuiltManifestMatchesRegistryTests(unittest.TestCase):
    def test_every_executable_operation_verifies_against_built_manifest(self) -> None:
        manifest = json.loads(subprocess.run([str(WORKER), "--manifest"], text=True, encoding="utf-8",
                                             capture_output=True, timeout=60, check=True).stdout)
        declared = {item["id"] for item in manifest["operations"]}
        registry = OperationRegistry()
        try:
            executable = sorted(operation_id for operation_id, operation in registry.operations.items()
                                if operation["status"] in EXECUTABLE_STATUSES)
            self.assertTrue(executable)
            failures = []
            for operation_id in executable:
                if operation_id not in declared:
                    failures.append((operation_id, "missing_from_worker_manifest"))
                    continue
                try:
                    registry.verify_manifest(manifest, operation_id)
                except InvalidInput as error:
                    failures.append((operation_id, str(error)))
            self.assertEqual(failures, [])
            self.assertEqual(sorted(declared - set(registry.operations)), [])
        finally:
            registry.close()


if __name__ == "__main__":
    unittest.main()
