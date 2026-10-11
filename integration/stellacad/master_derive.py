"""StellaCAD adapter for the native CGAL Master MCP: derived artifacts only.

Run it with the CGAL repository's venv (it needs `mcp`, `trimesh` and `cgal_mcp`):
  E:/aiwork/cgal-mcp/.venv/Scripts/python.exe integration/cgal/master_derive.py simplify SRC.stl OUT.off --unit mm

The server is started exactly as registered in the project `.mcp.json` entry `cgal-mcp`.
Guarantees (enforced here, not by convention):
  * the source file is never written; its SHA-256 is re-checked after the run;
  * the output and its `<output>.provenance.json` are NEW files (existing paths are refused);
  * nothing is published unless the job succeeded AND every mandatory validator passed;
  * the unit is explicit (mm/cm/m); STL/OBJ/PLY are only exactly welded (no repair/remesh) to OFF first.
This is a derived-mesh bridge, not CADHost.apply_mesh_atomic: native B-rep/Undo replacement is not done.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "stellacad.cgal_master_derivation/1"
UNITS = ("mm", "cm", "m")
SIMPLIFY_OPERATION = "mesh.simplify.edge_collapse"
DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / ".mcp.json"


class DerivationRefused(RuntimeError):
    """The derivation was not published; `detail` holds the server's verdict."""

    def __init__(self, message: str, detail: Any = None):
        super().__init__(message)
        self.detail = detail


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def server_parameters(config: Path = DEFAULT_CONFIG, name: str = "cgal-mcp",
                      data_dir: Path | None = None):
    from mcp import StdioServerParameters
    entry = json.loads(config.read_text(encoding="utf-8-sig"))["mcpServers"][name]
    env = {**os.environ, **entry.get("env", {})}
    if data_dir is not None:
        env["CGAL_MASTER_DATA"] = str(data_dir)
    return StdioServerParameters(command=entry["command"], args=entry.get("args", []), env=env)


async def call(client, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await client.call_tool(tool, arguments)
    if result.is_error:
        text = "".join(block.text for block in result.content if hasattr(block, "text"))
        raise DerivationRefused(f"{tool} refused: {text}", text)
    if result.structured_content is not None:
        return result.structured_content
    return json.loads("".join(block.text for block in result.content if hasattr(block, "text")))


def check_paths(source: Path, output: Path) -> Path:
    """Validate before any server work; return the provenance path."""
    provenance = output.with_name(output.name + ".provenance.json")
    if not source.is_file():
        raise DerivationRefused(f"source is not a file: {source}")
    if output.suffix.lower() != ".off":
        raise DerivationRefused("output must be a new .off file (the artifact's exact bytes)")
    if output.resolve() == source.resolve():
        raise DerivationRefused("output must differ from the source (source CAD is never overwritten)")
    for target in (output, provenance):
        if target.exists():
            raise DerivationRefused(f"refusing to overwrite existing file: {target}")
    return provenance


def prepare_input(source: Path, scratch: Path) -> tuple[Path, dict[str, Any]]:
    """OFF passes through; STL is exactly welded (identical coordinates only) to OFF."""
    if source.suffix.lower() == ".off":
        return source, {"conversion": "none"}
    if source.suffix.lower() != ".stl":
        raise DerivationRefused("input must be .off or .stl")
    from cgal_mcp.file_bridge import stl_to_off
    welded = scratch / (source.stem + ".welded.off")
    welded.write_text(stl_to_off(source.read_bytes()), encoding="ascii")
    return welded, {"conversion": "stl_exact_vertex_weld_to_off", "welded_sha256": sha256_file(welded)}


def build_provenance(*, source: Path, source_sha: str, unit: str, conversion: dict, plan: dict,
                     job: dict, parameters: dict, output: Path, output_sha: str,
                     input_artifact: dict) -> dict[str, Any]:
    artifact = job["outputs"][0]
    validators = [{"operation": item["operation"], "step_id": item["step_id"],
                   "verdict": item["metrics"].get("verdict", item["metrics"].get("status")),
                   "report": item["metrics"]} for item in job["validation"]]
    return {
        "schema": SCHEMA,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "derived_only": True, "source_modified": False,
        "source": {"path": str(source), "sha256": source_sha, "unit": unit, **conversion,
                   "artifact_id": input_artifact["artifact_id"],
                   "artifact_sha256": input_artifact["sha256"]},
        "operations": [SIMPLIFY_OPERATION] + [item["operation"] for item in job["validation"]],
        "parameters": parameters,
        "server": {"name": "cgal-mcp", "registry_revision": plan.get("registry_revision"),
                   "cgal_version": job["validation"][0].get("build", {}).get("actual_cgal_version"),
                   "plan_id": plan["plan_id"], "job_id": job["job_id"]},
        "validation_status": job["validation_status"], "validators": validators,
        "output": {"path": str(output), "sha256": output_sha, "unit": artifact["unit"],
                   "artifact_id": artifact["artifact_id"], "type": artifact["type"],
                   "faces": artifact["metadata"].get("faces"), "vertices": artifact["metadata"].get("vertices"),
                   "source_faces": input_artifact["metadata"].get("faces")},
    }


def accept(job: dict) -> None:
    """Publish only a succeeded job whose mandatory validators all passed."""
    if job.get("state") != "succeeded" or job.get("validation_status") != "passed":
        raise DerivationRefused(f"job not accepted: state={job.get('state')} "
                                f"validation={job.get('validation_status')} error={job.get('error')}", job)
    if not job.get("validation") or not job.get("outputs"):
        raise DerivationRefused("job has no validator report or output", job)
    for item in job["validation"]:
        metrics = item.get("metrics", {})
        if metrics.get("verdict", metrics.get("status")) != "pass":
            raise DerivationRefused(f"validator {item.get('operation')} did not pass", job)


async def derive_simplified(client, source: Path, output: Path, unit: str, *, face_ratio: float,
                            error_bound: float, max_deviation: float, policy: str = "lindstrom_turk",
                            timeout_s: float = 180.0) -> dict[str, Any]:
    if unit not in UNITS:
        raise DerivationRefused(f"unit must be one of {UNITS}; the unit is never guessed")
    source, output = source.resolve(), output.resolve()
    provenance_path = check_paths(source, output)
    source_sha = sha256_file(source)
    parameters = {"hausdorff_error_bound": {"value": error_bound, "unit": unit},
                  "max_symmetric_deviation": {"value": max_deviation, "unit": unit},
                  "policy": policy, "stop": {"kind": "face_ratio", "value": face_ratio}}
    with tempfile.TemporaryDirectory(prefix="stella-cgal-") as scratch:
        prepared, conversion = prepare_input(source, Path(scratch))
        imported = await call(client, "cgal_artifact_import", {"path": str(prepared), "unit": unit})
        plan = await call(client, "cgal_plan", {"request": {
            "operation_id": SIMPLIFY_OPERATION, "inputs": {"geometry": imported["artifact_id"]},
            "parameters": parameters}})
        queued = await call(client, "cgal_execute", {"plan_id": plan["plan_id"]})
        deadline = time.monotonic() + timeout_s
        while True:
            job = await call(client, "cgal_job_status", {"job_id": queued["job_id"]})
            if job["state"] not in ("queued", "running"):
                break
            if time.monotonic() > deadline:
                await call(client, "cgal_job_cancel", {"job_id": queued["job_id"]})
                raise DerivationRefused("job timed out and was cancelled", job)
            await asyncio.sleep(0.25)
    accept(job)
    artifact = job["outputs"][0]
    output.parent.mkdir(parents=True, exist_ok=True)
    await call(client, "cgal_artifact_export", {"artifact_id": artifact["artifact_id"], "path": str(output)})
    output_sha = sha256_file(output)
    if output_sha != artifact["sha256"]:
        output.unlink()
        raise DerivationRefused("exported bytes differ from the validated artifact; output removed")
    if sha256_file(source) != source_sha:
        raise DerivationRefused("source changed during the run")
    record = build_provenance(source=source, source_sha=source_sha, unit=unit, conversion=conversion,
                              plan=plan, job=job, parameters=parameters, output=output,
                              output_sha=output_sha, input_artifact=imported)
    with provenance_path.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    record["provenance_path"] = str(provenance_path)
    return record


async def derive_via_config(source: Path, output: Path, unit: str, *, config: Path = DEFAULT_CONFIG,
                            data_dir: Path | None = None, **options) -> dict[str, Any]:
    """Start the registered cgal-mcp (CGAL Master) server over stdio and derive one mesh."""
    from mcp import Client
    try:
        async with Client(server_parameters(config, data_dir=data_dir), mode="auto") as client:
            return await derive_simplified(client, source, output, unit, **options)
    except BaseExceptionGroup as group:  # the SDK wraps errors raised inside the client context
        refusals = group.subgroup(DerivationRefused)
        while refusals is not None and isinstance(refusals, BaseExceptionGroup):
            refusals = refusals.exceptions[0]
        if refusals is not None:
            raise refusals from None
        raise


async def run(args: argparse.Namespace) -> dict[str, Any]:
    return await derive_via_config(args.source, args.output, args.unit, config=args.config,
                                   data_dir=args.data_dir, face_ratio=args.face_ratio,
                                   error_bound=args.error_bound, max_deviation=args.max_deviation,
                                   policy=args.policy)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    simplify = sub.add_parser("simplify", help="edge-collapse simplification with mandatory validators")
    simplify.add_argument("source", type=Path)
    simplify.add_argument("output", type=Path)
    simplify.add_argument("--unit", required=True, choices=UNITS)
    simplify.add_argument("--face-ratio", type=float, default=0.5)
    simplify.add_argument("--error-bound", type=float, required=True, help="Hausdorff error bound, in --unit")
    simplify.add_argument("--max-deviation", type=float, required=True, help="accepted symmetric Hausdorff, in --unit")
    simplify.add_argument("--policy", default="lindstrom_turk")
    simplify.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    simplify.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        record = asyncio.run(run(args))
    except DerivationRefused as refusal:
        print(f"REFUSED: {refusal}")
        return 2
    print(json.dumps({key: record[key] for key in ("validation_status", "output", "provenance_path")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
