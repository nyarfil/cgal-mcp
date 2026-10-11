"""Exercise the project-registered `cgal-mcp` (CGAL Master; the v0.1 sidecar is retired) as an MCP client.

  E:/aiwork/cgal-mcp/.venv/Scripts/python.exe integration/cgal/verify_master_connection.py --output-dir <NEW dir>

Reads `.mcp.json` exactly as a host would, starts the server over stdio, then:
initialize -> list tools/resources/prompts -> read cgal://guide/start -> cgal_get_guide ->
real simplification of the StellaCAD fixture (explicit unit, mandatory validators, provenance) ->
an over-bound input is refused with a typed error.
"""
import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import master_derive as md  # noqa: E402
from mcp import Client  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "stella_icosphere_r10mm_320f.stl"
OVER_BOUND = next(iter(sorted(md.DEFAULT_CONFIG.parent.glob(
    "cadmcp-all-in-one-2026-09-17/01_CURRENT/examples/real-reference-output/shaft/model.stl"))), None)


async def master(out: Path) -> dict:
    report = {}
    async with Client(md.server_parameters(), mode="auto") as client:
        info = client.server_info
        tools = [t.name for t in (await client.list_tools()).tools]
        resources = [str(r.uri) for r in (await client.list_resources()).resources]
        prompts = [p.name for p in (await client.list_prompts()).prompts]
        start = await client.read_resource("cgal://guide/start")
        text = "".join(getattr(c, "text", "") for c in start.contents)
        assert "Quickstart" in text, text[:200]
        guide = await md.call(client, "cgal_get_guide", {"topic": "op:mesh.simplify.edge_collapse"})
        assert "mesh.validate.simplification_integrity" in guide["text"]
        health = await md.call(client, "cgal_system_health", {})
        assert health["worker"]["available"] is True, health
        assert health["worker_pool"]["enabled"] is False if "enabled" in health.get("worker_pool", {}) else True
        report["handshake"] = {"server": getattr(info, "name", None), "tools": tools, "resources": resources,
                               "prompts": prompts, "guide_start_chars": len(text),
                               "registry_revision": health["registry_revision"],
                               "worker_pool": health["worker_pool"], "result_cache": health["result_cache"]}
        assert "cgal_get_guide" in tools and "cgal://guide/start" in resources
        refusals = []
        if OVER_BOUND is not None:
            try:
                await md.derive_simplified(client, OVER_BOUND, out / "shaft_refused.off", "mm",
                                           face_ratio=0.5, error_bound=0.05, max_deviation=1.0)
                raise AssertionError("over-bound input was not refused")
            except md.DerivationRefused as refusal:
                refusals.append({"input": OVER_BOUND.name + " (500 faces)", "refused": str(refusal)[:600]})
            assert not (out / "shaft_refused.off").exists()
        report["refusals"] = refusals
    # Separate session through the config-level entry point (group-unwrapping helper).
    source = out / FIXTURE.name
    source.write_bytes(FIXTURE.read_bytes())
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    derived = await md.derive_via_config(source, out / "stella_icosphere_simplified.off", "mm",
                                         face_ratio=0.5, error_bound=0.05, max_deviation=1.0)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    report["derivation"] = json.loads(Path(derived["provenance_path"]).read_text(encoding="utf-8"))
    return report


async def main(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    report = {"config": str(md.DEFAULT_CONFIG), "master": await master(out)}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", required=True, type=Path)
    result = asyncio.run(main(parser.parse_args().output_dir.resolve()))
    d = result["master"]["derivation"]
    print("master tools:", len(result["master"]["handshake"]["tools"]), "resources:",
          len(result["master"]["handshake"]["resources"]), "prompts:", len(result["master"]["handshake"]["prompts"]))
    print("derived faces", d["output"]["source_faces"], "->", d["output"]["faces"], d["validation_status"],
          [v["verdict"] for v in d["validators"]])
    print("refusals:", len(result["master"]["refusals"]))
