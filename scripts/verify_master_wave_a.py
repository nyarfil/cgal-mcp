"""Replay the synthetic Wave A milestone; this is not full v1 acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(worker: Path) -> dict:
    worker = worker.resolve(strict=True)
    manifest = json.loads(subprocess.run([str(worker), "--manifest"],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=30).stdout)
    assert manifest["actual_cgal_version"] == "6.2.1"
    assert manifest["build"]["source_kind"] == "official_release"
    operations = ["mesh.simplify.edge_collapse", "mesh.validate.simplification_integrity",
                  "mesh.distance.symmetric_hausdorff"]
    assert set(operations) <= {operation["id"] for operation in manifest["operations"]}
    commands = [
        (["tests/master_wave_a_cases.py", str(worker)], "tests/master_wave_a_cases.py"),
        (["-m", "tests.master_wave_a_mcp_e2e", "auto"], "tests/master_wave_a_mcp_e2e.py"),
        (["-m", "tests.master_wave_a_mcp_e2e", "legacy"], "tests/master_wave_a_mcp_e2e.py"),
    ]
    results = []
    for arguments, test in commands:
        result = subprocess.run([sys.executable, *arguments], cwd=REPO,
            env={**os.environ, "CGAL_MASTER_WORKER": str(worker)},
            check=True, capture_output=True, text=True, encoding="utf-8", timeout=600)
        assert "PASS" in result.stdout, result.stdout
        results.append({"test": test, "sha256": digest(REPO / test),
                        "mode": arguments[-1] if arguments[0] == "-m" else "worker",
                        "exit_code": result.returncode, "status": "pass"})
        print(result.stdout.strip())
    return {
        "schema_version": 1, "generator": "master-wave-a-milestone",
        "generator_sha256": digest(Path(__file__)), "status": "pass",
        "scope": "mesh_simplification_policies_and_dual_validation",
        "standalone_accepted": False, "requirements": [], "operations": operations,
        "worker_sha256": digest(worker), "worker_manifest": manifest,
        "worker_manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
        "operation_catalog_sha256": digest(REPO / "catalog/operations_wave_a.json"),
        "policy_catalog_sha256": digest(REPO / "cgal_mcp/master/policies.json"),
        "tests": results,
        "coverage_note": "Only the enumerated policies and adapters were replayed. "
            "The 80 major requirements and standalone acceptance remain incomplete. "
            "FastEnvelope is blocked by its separate external dependency.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.worker)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())


if __name__ == "__main__":
    main()
