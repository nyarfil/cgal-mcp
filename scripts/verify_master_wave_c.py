"""Replay twelve Wave C 2D, triangulation and spatial operations and their mandatory independent validators."""
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
    worker_hash = digest(worker)
    manifest = json.loads(subprocess.run([str(worker), "--manifest"], check=True,
        capture_output=True, text=True, encoding="utf-8", timeout=30).stdout)
    assert manifest["actual_cgal_version"] == "6.2.1"
    assert manifest["build"]["source_kind"] == "official_release"
    catalog = json.loads((REPO / "catalog/operations_wave_c.json").read_text("utf-8"))
    operations = sorted(operation["id"] for operation in catalog["operations"])
    assert len(operations) == 23
    assert all(operation["status"] == "VALIDATED" for operation in catalog["operations"])
    assert set(operations) <= {operation["id"] for operation in manifest["operations"]}
    results = []
    for arguments, source, mode in (
        (["tests/master_wave_c_cases.py", str(worker)], "tests/master_wave_c_cases.py", "worker"),
        (["-m", "tests.master_wave_c_mcp_e2e", "auto"], "tests/master_wave_c_mcp_e2e.py", "auto"),
        (["-m", "tests.master_wave_c_mcp_e2e", "legacy"], "tests/master_wave_c_mcp_e2e.py", "legacy"),
    ):
        try:
            process = subprocess.run([sys.executable, *arguments], cwd=REPO, check=True,
                capture_output=True, text=True, encoding="utf-8", timeout=600,
                env={**os.environ, "CGAL_MASTER_WORKER": str(worker)})
        except subprocess.CalledProcessError as error:
            print(error.stdout or "", end="", file=sys.stderr)
            print(error.stderr or "", end="", file=sys.stderr)
            raise
        assert "PASS" in process.stdout, process.stdout
        print(process.stdout.strip(), flush=True)
        results.append({"test": source, "source_sha256": digest(REPO / source),
                        "mode": mode, "exit_code": process.returncode, "status": "pass"})
    assert digest(worker) == worker_hash, "Worker changed during replay"
    return {"schema_version": 1, "generator": "master-wave-c-milestone", "status": "pass",
        "generator_sha256": digest(Path(__file__)), "scope": "twelve_wave_c_operations_and_eleven_independent_validators",
        "standalone_accepted": False, "requirements": [], "operations": operations,
        "worker_sha256": worker_hash, "worker_manifest": manifest,
        "worker_manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
        "operation_catalog_sha256": digest(REPO / "catalog/operations_wave_c.json"), "tests": results,
        "coverage_note": "Only these twelve bounded Wave C operations (2D convex hull, polygon properties/containment, 2D/constrained/3D Delaunay, kd-tree k-NN and radius search, Bbox_2/Bbox_3, AABB closest points and ray first hits) and their eleven independent validators were replayed. Regular/periodic/Voronoi, arrangements, polygon Boolean/offset/skeleton, alpha shapes, wrapping and other spatial families remain incomplete."}


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
