"""First-contact evaluation: can an agent with zero repository knowledge use the Master MCP?

Phase A drives the real MCP server over stdio with a deterministic scripted client that
may use ONLY what a new agent sees: the server ``instructions``, the ``cgal_get_guide`` tool,
the guide resources/prompts and the twelve ordinary tools. For each natural-language user
request it (1) reads the recipe index, (2) picks a recipe by lexical overlap, (3) reads the
recipe and the operation cards, (4) imports the fixtures the recipe names, (5) sends the
plan request the recipe contains, (6) executes, polls and checks job state and validators.
Phase B executes every per-operation example call printed on the operation cards against the
real worker. The scripted client is NOT a language model: it shows that the guide text is
sufficient and unambiguous for a mechanical reader, not how any particular LLM behaves.

Evidence: docs/master/evidence/first-contact.json (informational; never a standalone gate).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from mcp import Client, StdioServerParameters  # noqa: E402

from cgal_mcp.master.errors import MasterError  # noqa: E402
from cgal_mcp.master.runtime import MasterRuntime  # noqa: E402

EVIDENCE_PATH = "docs/master/evidence/first-contact.json"
GENERATOR = "master-first-contact"
GUIDE_BUNDLE = "cgal_mcp/master/guide/guide.json"

# (expected recipe id, language, request as an end user would write it)
REQUESTS: list[tuple[str, str, str]] = [
    ("wf01-soup-orient-loop-inspect", "en", "My scan is a pile of loose triangles and some face the wrong way. Turn them the right way round, make it smoother with one subdivision pass and tell me whether the mesh is healthy."),
    ("wf02-fillholes-loop-measures", "en", "There is a small hole in my mesh. Close it, subdivide once and give me the area and volume."),
    ("wf03-stitch-components", "en", "The seam of my model is duplicated. Stitch the borders together and count how many separate pieces there are."),
    ("wf04-degenerate-remove-selfintersect", "en", "Remove zero-area degenerate triangles from my model and then check that it does not intersect itself."),
    ("wf05-dirtysoup-clean-orient-measure", "en", "I have a dirty polygon soup with duplicates. Clean it, orient it consistently and measure it."),
    ("wf06-remesh-simplify-hausdorff-join", "en", "Remesh my sphere to uniform edges, also make a lighter version, and compare them by Hausdorff distance."),
    ("wf07-smooth-remesh-simplify", "en", "My sphere scan is noisy. Smooth it, remesh it evenly and then reduce the triangle count."),
    ("wf08-refine-measure", "en", "Refine the triangles locally around part of my mesh and measure the result."),
    ("wf09-union-keeplargest-loop", "en", "Merge two overlapping cubes into one solid, keep only the largest piece and subdivide it."),
    ("wf10-difference-measures", "en", "Cut one cube out of another cube and tell me the volume that is left."),
    ("wf12-clip-measures", "en", "Cut my cube with a plane and measure what remains."),
    ("wf13-corefine-components", "en", "Corefine two tetrahedra so that they share their intersection curve, then analyse the components."),
    ("wf14-catmull-triangulate-measure", "en", "Apply Catmull-Clark subdivision, convert the quads back to triangles and measure."),
    ("wf15-points-alphawrap-remesh-measures", "en", "I have a point cloud. Wrap a watertight surface around it with alpha wrapping, remesh it and measure."),
    ("wf16-poisson-remesh-inspect", "en", "Build a surface from oriented points with Poisson reconstruction, remesh it and check its health."),
    ("wf17-outliers-grid-afsr-measures", "en", "Remove outliers from my scan points, thin them on a grid, reconstruct with advancing front and measure the mesh."),
    ("wf19-hull3-loop-measures", "en", "Wrap a 3D convex hull around my points, subdivide it once and measure it."),
    ("wf20-outlier-normals-orient", "en", "Throw away outliers in a point set, estimate normals and orient them consistently."),
    ("wf21-random-delaunay3", "en", "Randomly thin my points and build a 3D Delaunay triangulation."),
    ("wf24-grid-maxdistance-join", "en", "Thin my point cloud on a grid and report the maximum distance to a reference mesh."),
    ("wf25-random-bbox", "en", "Randomly thin a point cloud and compute its 3D bounding box."),
    ("wf26-remesh-slice", "en", "Remesh the model evenly, then slice it with a plane to get the cross-section."),
    ("wf27-hull2-polygon-boolean", "en", "Take the 2D convex hull of some points and combine it with a polygon by boolean union."),
    ("wf28-hull2-minkowski", "en", "Make the 2D convex hull of my points and compute the Minkowski sum with another polygon."),
    ("wf29-hull2-barycentric", "en", "Compute the 2D hull of my points and the barycentric coordinates of query points inside it."),
    ("wf30-surface-generate-remesh-measures", "en", "Generate a surface mesh from an implicit function, remesh it and measure."),
    ("wf34-clip-loop-inspect", "en", "Clip the cube with a plane, subdivide it and run a health inspection."),
    ("wf35-simplify-loop-inspect", "en", "Simplify my mesh to fewer faces, then subdivide it and inspect it."),
    ("wf39-hull2-arrangement-overlay", "en", "Overlay the 2D hull of my points with a polygon as an arrangement."),
    ("wf40-outliers-grid-delaunay3", "en", "Clean outliers, thin on a grid, then compute a 3D Delaunay triangulation."),
    ("wf18-jet-alphawrap-components", "ja", "ノイズのある点群をjet平滑化して、alpha wrappingで面にし、連結成分を調べたい。"),
    ("wf31-unit-propagation-cm", "ja", "cm単位のメッシュを、mm指定のパラメータでリメッシュして軽量化し、測定したい。"),
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------- text helpers
def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z0-9]+", text.lower())
    result = []
    for word in words:
        for suffix in ("ing", "ed", "es", "s"):
            if len(word) > len(suffix) + 3 and word.endswith(suffix):
                word = word[:-len(suffix)]
                break
        if len(word) >= 3:
            result.append(word)
    for run in re.findall(r"[^\x00-\x7f]+", text):
        result += [run[i:i + 2] for i in range(len(run) - 1)]
    return result


def parse_recipe_index(text: str) -> list[dict]:
    recipes: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        match = re.match(r"- (wf[0-9a-z\-]+): (.*)", line)
        if match:
            current = {"id": match.group(1), "heading": match.group(2), "other": "", "ops": "", "keywords": ""}
            recipes.append(current)
        elif current and line.startswith("  EN:") or current and line.startswith("  JA:"):
            current["other"] = line[5:].strip()
        elif current and line.startswith("  ops:"):
            current["ops"] = line[6:].strip()
        elif current and line.startswith("  keywords:"):
            current["keywords"] = line[11:].strip()
        elif line.startswith("## Expected refusals"):
            break
    return recipes


def pick_recipe(request: str, recipes: list[dict]) -> str:
    docs = [set(tokens(" ".join([r["heading"], r["other"], r["ops"].replace(".", " ").replace("_", " "), r["keywords"]])))
            for r in recipes]
    n = len(docs)
    df: dict[str, int] = {}
    for doc in docs:
        for token in doc:
            df[token] = df.get(token, 0) + 1
    query = set(tokens(request))
    best, best_score = recipes[0]["id"], -1.0
    for recipe, doc in zip(recipes, docs):
        score = sum(math.log(1 + n / df[t]) for t in query if t in doc)
        if score > best_score + 1e-12:
            best, best_score = recipe["id"], score
    return best


def parse_recipe_body(text: str) -> tuple[dict[str, dict], dict]:
    imports: dict[str, dict] = {}
    for match in re.finditer(r"^- \$([A-Za-z0-9_]+): cgal_artifact_import (\{.*\})$", text, re.M):
        imports[match.group(1)] = json.loads(match.group(2))
    block = re.search(r"```json\n(.*?)\n```", text, re.S)
    assert block, "recipe has no plan request block"
    request = json.loads(block.group(1))["request"]
    execution = re.search(r"^Execute with execution=(\{.*\})$", text, re.M)
    return imports, {"request": request, "execution": json.loads(execution.group(1)) if execution else None}


def substitute(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str) and value.startswith("$") and value[1:] in mapping:
        return mapping[value[1:]]
    if isinstance(value, dict):
        return {k: substitute(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, mapping) for v in value]
    return value


def result_json(result: Any) -> dict:
    assert not result.is_error, result
    if result.structured_content is not None:
        return result.structured_content
    return json.loads("".join(block.text for block in result.content if hasattr(block, "text")))


# ----------------------------------------------------------------------------- phase A
async def phase_a(worker: Path, data_dir: Path) -> dict:
    connection = StdioServerParameters(
        command=sys.executable, args=["-m", "cgal_mcp.master.server", "stdio"], cwd=str(REPO),
        env={**os.environ, "CGAL_MASTER_DATA": str(data_dir), "CGAL_MASTER_WORKER": str(worker),
             "PYTHONPATH": str(REPO)})
    cases = []
    async with Client(connection, mode="auto") as client:
        calls = {"count": 0}

        async def call(name: str, arguments: dict) -> dict:
            calls["count"] += 1
            return result_json(await client.call_tool(name, arguments))

        instructions = client.instructions or ""
        tool_names = sorted(tool.name for tool in (await client.list_tools()).tools)
        resources = [str(r.uri) for r in (await client.list_resources()).resources]
        templates = [t.uri_template for t in (await client.list_resource_templates()).resource_templates]
        prompts = sorted(p.name for p in (await client.list_prompts()).prompts)
        assert "cgal_get_guide" in instructions and "CALL ORDER" in instructions
        start = await call("cgal_get_guide", {"topic": "start"})
        assert "cgal_plan" in start["text"]
        index_en = parse_recipe_index((await call("cgal_get_guide", {"topic": "recipes"}))["text"])
        index_ja = parse_recipe_index((await call("cgal_get_guide", {"topic": "recipes", "lang": "ja"}))["text"])
        # A resource-capable host reads the same text; prove both routes agree.
        resource_text = (await client.read_resource("cgal://guide/recipes")).contents[0].text
        assert resource_text == (await call("cgal_get_guide", {"topic": "recipes"}))["text"]
        for expected, lang, request in REQUESTS:
            case: dict[str, Any] = {"request": request, "language": lang, "expected_recipe": expected}
            index = index_ja if lang == "ja" else index_en
            before = calls["count"]
            chosen = pick_recipe(request, index)
            case["selected_recipe"] = chosen
            case["recipe_match"] = chosen == expected
            search = await call("cgal_capabilities_search", {"query": request, "limit": 8})
            body = (await call("cgal_get_guide", {"topic": f"recipe:{chosen}"}))["text"]
            imports, plan_spec = parse_recipe_body(body)
            ops = [step["operation"] for step in plan_spec["request"]["steps"]]
            case["operations"] = ops
            found = {c["operation_id"] for c in search["candidates"]}
            case["search_hit"] = bool(found & set(ops))
            for op in dict.fromkeys(ops):
                card = (await call("cgal_get_guide", {"topic": f"op:{op}"}))["text"]
                assert "## Parameters" in card and "## Example" in card, op
            mapping: dict[str, str] = {}
            for name, spec in imports.items():
                path = REPO / spec["path"]
                imported = await call("cgal_artifact_import", {**spec, "path": str(path)})
                mapping[name] = imported["artifact_id"]
            plan = await call("cgal_plan", {"request": substitute(plan_spec["request"], mapping)})
            options = plan_spec["execution"]
            queued = await call("cgal_execute", {"plan_id": plan["plan_id"], **({"execution": options} if options else {})})
            status: dict = {}
            for _ in range(1200):
                status = await call("cgal_job_status", {"job_id": queued["job_id"]})
                if status["state"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.1)
            case["state"] = status["state"]
            case["validators"] = [entry["report"].get("status") for entry in status.get("validation", [])]
            case["outputs"] = [{"type": o["type"], "unit": o["unit"]} for o in status.get("outputs", [])]
            case["tool_calls"] = calls["count"] - before
            case["executed_ok"] = (status["state"] == "succeeded"
                                   and all(v == "pass" for v in case["validators"]))
            cases.append(case)
        # prompts: render one to prove they resolve from a client
        prompt = await client.get_prompt("start_here", {"request": "make my mesh lighter"})
        prompt_ok = "cgal_get_guide" in prompt.messages[0].content.text
    return {"instructions_words": len(instructions.split()), "tools": tool_names, "resources": sorted(resources),
            "resource_templates": sorted(templates), "prompts": prompts, "prompt_renders": prompt_ok,
            "cases": cases}


# ----------------------------------------------------------------------------- phase B
async def phase_b(worker: Path, data_dir: Path) -> dict:
    bundle = json.loads((REPO / GUIDE_BUNDLE).read_text(encoding="utf-8"))
    runtime = MasterRuntime(data_dir, worker=worker, require_memory_limit=False)
    results: dict[str, str] = {}
    try:
        for oid, example in sorted(bundle["examples"].items()):
            mapping: dict[str, str] = {}
            try:
                for item in example["imports"]:
                    imported = runtime.artifact_import(str(REPO / item["path"]), item["unit"],
                                                       artifact_type=item["artifact_type"])
                    mapping[item["name"]] = imported["artifact_id"]
                plan = runtime.plan(substitute(example["plan_request"], mapping))
                job = await runtime.execute(plan["plan_id"])
                await runtime.tasks[job["job_id"]]
                detail = runtime.store.get_job(job["job_id"])
                ok = detail["state"] == "succeeded" and all(
                    entry["report"].get("status") == "pass" for entry in detail.get("validation", []))
                results[oid] = "succeeded" if ok else f"{detail['state']}:{(detail.get('error') or {}).get('code')}"
            except MasterError as exc:
                results[oid] = f"refused:{exc.code}"
    finally:
        runtime.close()
    return {"examples": results}


# ----------------------------------------------------------------------------- driver
def measure(worker: Path, skip_a: bool = False, skip_b: bool = False, only_b: list[str] | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="first-contact-") as temporary:
        base = Path(temporary)
        a = {} if skip_a else asyncio.run(phase_a(worker, base / "a"))
        b = {} if skip_b else asyncio.run(phase_b(worker, base / "b"))
    cases = a.get("cases", [])
    examples = b.get("examples", {})
    bundle_sha = sha256_file(REPO / GUIDE_BUNDLE)
    bundle = json.loads((REPO / GUIDE_BUNDLE).read_text(encoding="utf-8"))
    summary = {
        "requests": len(cases),
        "recipe_match": sum(1 for c in cases if c["recipe_match"]),
        "search_hit": sum(1 for c in cases if c["search_hit"]),
        "executed_ok": sum(1 for c in cases if c["executed_ok"]),
        "examples_total": len(examples),
        "examples_succeeded": sum(1 for v in examples.values() if v == "succeeded"),
        "operations_in_guide": bundle["counts"]["operations"],
    }
    return {"generator": GENERATOR, "schema_version": 1,
            "informational": True, "gating": False,
            "note": ("Deterministic scripted client, not a language model: it shows the guide is sufficient for a mechanical "
                     "reader. This evidence is informational and is not a standalone acceptance gate."),
            "bindings": {"guide_bundle_sha256": bundle_sha,
                         "instructions_sha256": hashlib.sha256(bundle["topics"]["en"]["instructions"].encode("utf-8")).hexdigest(),
                         "operations_sha256": sha256_file(REPO / "cgal_mcp/master/operations.json"),
                         "workflows_sha256": sha256_file(REPO / "docs/master/workflows.json"),
                         "harness_sha256": sha256_file(Path(__file__)),
                         "worker_sha256": sha256_file(worker)},
            "summary": summary, "surface": {k: a.get(k) for k in (
                "instructions_words", "tools", "resources", "resource_templates", "prompts", "prompt_renders")},
            "cases": cases, "examples": examples}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path, default=REPO / "build-master/Release/cgal-master-worker.exe")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-examples", action="store_true")
    parser.add_argument("--skip-agent", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    evidence = measure(args.worker, args.skip_agent, args.skip_examples)
    if args.summary or not args.output:
        print(json.dumps(evidence["summary"], indent=1))
        for case in evidence["cases"]:
            if not (case["recipe_match"] and case["executed_ok"]):
                print("PROBLEM", case["expected_recipe"], case["selected_recipe"], case["state"], case["validators"])
        for oid, outcome in evidence["examples"].items():
            if outcome != "succeeded":
                print("EXAMPLE", oid, outcome)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=1, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
