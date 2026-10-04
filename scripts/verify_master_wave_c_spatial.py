"""Replay Spatial Query 7.2 native and MCP acceptance without self-certifying VALIDATED."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
OPS = {
    "spatial.aabb.closest_point",
    "spatial.kdtree.range",
    "spatial.nearest_neighbors",
    "spatial.intersection_candidates",
    "spatial.bounding_box",
    "spatial.validate.aabb_closest_point",
    "spatial.validate.kdtree_range",
    "spatial.validate.nearest_neighbors",
    "spatial.validate.intersection_candidates",
    "spatial.validate.bounding_box",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_case(arguments: list[str], source: str, mode: str, worker: Path) -> dict:
    process = subprocess.run(
        [sys.executable, *arguments],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        env={**os.environ, "CGAL_MASTER_WORKER": str(worker)},
    )
    assert "PASS" in process.stdout, process.stdout
    print(process.stdout.strip(), flush=True)
    return {
        "test": source,
        "source_sha256": digest(REPO / source),
        "mode": mode,
        "exit_code": process.returncode,
        "status": "pass",
    }


def verify(worker: Path) -> dict:
    worker = worker.resolve(strict=True)
    worker_hash = digest(worker)
    manifest = json.loads(subprocess.run(
        [str(worker), "--manifest"], check=True, capture_output=True,
        text=True, encoding="utf-8", timeout=30).stdout)
    assert manifest["actual_cgal_version"] == "6.2.1"
    assert manifest["build"]["source_kind"] == "official_release"
    declared = {item["id"] for item in manifest["operations"]}
    assert OPS <= declared

    catalog_path = REPO / "catalog" / "operations_wave_c_spatial.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_ops = {item["id"]: item for item in catalog["operations"]}
    assert set(catalog_ops) == OPS
    assert {item["status"] for item in catalog_ops.values()} <= {
        "IMPLEMENTED", "VALIDATED"}
    assert all(item["status"] != "VALIDATED" or item.get("evidence", {}).get("tests")
               for item in catalog_ops.values())

    tests = [
        run_case(["tests/master_wave_c_spatial_cases.py", str(worker)],
                 "tests/master_wave_c_spatial_cases.py", "worker", worker),
        run_case(["-m", "tests.master_wave_c_spatial_mcp_e2e", "auto"],
                 "tests/master_wave_c_spatial_mcp_e2e.py", "auto", worker),
        run_case(["-m", "tests.master_wave_c_spatial_mcp_e2e", "legacy"],
                 "tests/master_wave_c_spatial_mcp_e2e.py", "legacy", worker),
    ]
    assert digest(worker) == worker_hash, "Worker changed during Spatial replay"
    return {
        "schema_version": 1,
        "generator": "master-wave-c-spatial",
        "status": "pass",
        "generator_sha256": digest(Path(__file__)),
        "scope": "major_7_2_spatial_query_implemented_acceptance",
        "standalone_accepted": False,
        "requirements": [],
        "operations": sorted(OPS),
        "worker_sha256": worker_hash,
        "worker_manifest": manifest,
        "worker_manifest_sha256": hashlib.sha256(json.dumps(
            manifest, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode()).hexdigest(),
        "operation_catalog_sha256": digest(catalog_path),
        "tests": tests,
        "coverage_note": (
            "This report proves the branch implementation path only. "
            "Major 7.2 is not promoted to formal requirement acceptance until "
            "the catalog is separately reviewed and changed to VALIDATED."),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.worker)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")


if __name__ == "__main__":
    main()
