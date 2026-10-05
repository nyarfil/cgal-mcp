"""Replay CGAL Master spatial AABB analyses and mandatory replay validators."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "catalog" / "operations_spatial.json"
EXPECTED = {
    "spatial.aabb.closest_point",
    "spatial.validate.aabb_closest_point",
    "spatial.aabb.segment_candidates",
    "spatial.validate.aabb_segment_candidates",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_case(worker: Path, arguments: list[str], source: str,
             mode: str) -> dict:
    try:
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
    except subprocess.CalledProcessError as error:
        print(error.stdout or "", end="", file=sys.stderr)
        print(error.stderr or "", end="", file=sys.stderr)
        raise
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
        [str(worker), "--manifest"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    ).stdout)
    assert manifest["actual_cgal_version"] == "6.2.1"
    assert manifest["build"]["source_kind"] == "official_release"

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    operations = {item["id"]: item for item in catalog["operations"]}
    assert set(operations) == EXPECTED
    assert all(item["status"] in {"IMPLEMENTED", "VALIDATED"}
               for item in operations.values())
    manifest_operations = {item["id"]: item for item in manifest["operations"]}
    assert EXPECTED <= set(manifest_operations)

    for operation_id in EXPECTED:
        item = operations[operation_id]
        actual = manifest_operations[operation_id]
        contract = item["worker_manifest"]
        assert actual["revision"] == item["revision"]
        assert actual["role"] == item["role"]
        assert set(actual["dependencies"]) == set(item["dependencies"])
        assert actual["effective_kernel"] == contract["effective_kernel"]
        for key, value in contract["info"].items():
            assert actual["info"].get(key) == value, (
                operation_id, key, actual["info"].get(key), value)

    results = [
        run_case(
            worker,
            ["tests/master_spatial_aabb_cases.py", str(worker)],
            "tests/master_spatial_aabb_cases.py",
            "worker",
        ),
        run_case(
            worker,
            ["-m", "tests.master_spatial_aabb_mcp_e2e", "auto"],
            "tests/master_spatial_aabb_mcp_e2e.py",
            "auto",
        ),
        run_case(
            worker,
            ["-m", "tests.master_spatial_aabb_mcp_e2e", "legacy"],
            "tests/master_spatial_aabb_mcp_e2e.py",
            "legacy",
        ),
    ]
    assert digest(worker) == worker_hash, "Worker changed during spatial replay"

    return {
        "schema_version": 1,
        "generator": "master-spatial-aabb-acceptance",
        "status": "pass",
        "generator_sha256": digest(Path(__file__)),
        "scope": (
            "AABB closest-point distance and segment intersection candidate "
            "queries with mandatory independent replay validators"
        ),
        "standalone_accepted": False,
        "requirements": [],
        "operations": sorted(EXPECTED),
        "worker_sha256": worker_hash,
        "worker_manifest": manifest,
        "worker_manifest_sha256": hashlib.sha256(
            json.dumps(
                manifest, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest(),
        "operation_catalog_sha256": digest(CATALOG),
        "tests": results,
        "coverage_note": (
            "This validates the current AABB_tree closest-point and bounded "
            "segment primitive-candidate slice only. It does not complete "
            "Spatial Query 7.2, AABB Tree as a whole, or standalone acceptance."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.worker)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(
        (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    )


if __name__ == "__main__":
    main()
