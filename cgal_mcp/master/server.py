"""Stable MCP tools, generated guide resources and prompts over the Master runtime."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import functools
import inspect
import json
import os
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .errors import MasterError
from .guide import Guide, STATIC_TOPICS
from .runtime import MasterRuntime, default_runtime

RESOURCE_DESCRIPTIONS = {
    "start": "Quickstart: find, import, plan, execute, read results",
    "families": "All families with their operations, typical uses and input/output types",
    "recipes": "Verified workflows: if the user wants X, do these steps",
    "errors": "Error and refusal codes with remedies; job states",
    "glossary": "Terms, artifact types, units and coordinate conventions",
    "limits-and-status": "Honest coverage: limits, validated/cataloged/excluded packages with reasons",
}


def _register_guide_resources(server: MCPServer, guide: Guide, lang: str) -> None:
    prefix = "cgal://guide/" if lang == "en" else "cgal://guide/ja/"
    tag = "" if lang == "en" else "-ja"
    suffix = "" if lang == "en" else " (Japanese)"
    def static_reader(topic: str):
        def reader() -> str:
            return guide.get(topic, lang)
        return reader

    for topic in STATIC_TOPICS:
        server.resource(prefix + topic, name=f"guide-{topic}{tag}",
                        description=RESOURCE_DESCRIPTIONS[topic] + suffix,
                        mime_type="text/markdown")(static_reader(topic))

    def op_reader(operation_id: str) -> str:
        return guide.get(f"op:{operation_id}", lang)

    def recipe_reader(workflow_id: str) -> str:
        return guide.get(f"recipe:{workflow_id}", lang)

    def family_reader(family_id: str) -> str:
        return guide.get(f"family:{family_id}", lang)

    server.resource(prefix + "op/{operation_id}", name=f"guide-op{tag}",
                    description="Complete card for one operation" + suffix, mime_type="text/markdown")(op_reader)
    server.resource(prefix + "recipe/{workflow_id}", name=f"guide-recipe{tag}",
                    description="One verified recipe with its plan request" + suffix,
                    mime_type="text/markdown")(recipe_reader)
    server.resource(prefix + "family/{family_id}", name=f"guide-family{tag}",
                    description="One family with its operations" + suffix, mime_type="text/markdown")(family_reader)


def _register_prompts(server: MCPServer, guide: Guide) -> None:
    def text(name: str, lang: str, **arguments: Any) -> str:
        return guide.render_prompt(name, lang, **arguments)

    @server.prompt(name="start_here", description="Guided start for any geometry request")
    def start_here(request: str, lang: str = "en") -> str:
        return text("start_here", lang, request=request)

    @server.prompt(name="repair_and_simplify_mesh",
                   description="Inspect, repair and simplify a triangle mesh with validation")
    def repair_and_simplify_mesh(mesh_path: str, unit: str, target_ratio: str = "0.5", lang: str = "en") -> str:
        return text("repair_and_simplify_mesh", lang, mesh_path=mesh_path, unit=unit, target_ratio=target_ratio)

    @server.prompt(name="reconstruct_surface_from_points",
                   description="Clean a point cloud and reconstruct a surface")
    def reconstruct_surface_from_points(points_path: str, unit: str, lang: str = "en") -> str:
        return text("reconstruct_surface_from_points", lang, points_path=points_path, unit=unit)

    @server.prompt(name="validate_geometry", description="Check whether a geometry file is sound and report why not")
    def validate_geometry(path: str, unit: str, artifact_type: str = "TriangleSurfaceMesh",
                          lang: str = "en") -> str:
        return text("validate_geometry", lang, path=path, unit=unit, artifact_type=artifact_type)

    @server.prompt(name="compare_meshes", description="Measure the deviation between two meshes")
    def compare_meshes(reference_path: str, candidate_path: str, unit: str, lang: str = "en") -> str:
        return text("compare_meshes", lang, reference_path=reference_path,
                    candidate_path=candidate_path, unit=unit)

    @server.prompt(name="2d_boolean_offset", description="2D polygon boolean, offset and Minkowski work")
    def boolean_offset_2d(polygon_path: str, unit: str, offset: str = "", lang: str = "en") -> str:
        return text("2d_boolean_offset", lang, polygon_path=polygon_path, unit=unit, offset=offset)

    @server.prompt(name="choose_operation", description="Pick the right operation for a goal, with honest refusal")
    def choose_operation(goal: str, lang: str = "en") -> str:
        return text("choose_operation", lang, goal=goal)


def _structured_errors(function):
    """Return typed refusals ({class, code, message, ...}) to the client.

    Without this the SDK reduces every MasterError to the opaque text
    "Error executing tool <name>", so an agent cannot read the code or remedy.
    """
    def refuse(error: MasterError):
        return ToolError(json.dumps(error.as_dict(), ensure_ascii=False))

    if inspect.iscoroutinefunction(function):
        @functools.wraps(function)
        async def wrapper(*args, **kwargs):
            try:
                return await function(*args, **kwargs)
            except MasterError as error:
                raise refuse(error) from error
    else:
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except MasterError as error:
                raise refuse(error) from error
    return wrapper


def create_server(runtime: MasterRuntime | None = None) -> MCPServer:
    active = runtime or default_runtime()
    guide = Guide()

    def tool(name: str):
        register = server.tool(name=name)
        return lambda function: register(_structured_errors(function))

    @asynccontextmanager
    async def lifespan(_: MCPServer):
        try:
            yield {}
        finally:
            # MCPServer owns the runtime for the lifetime of every transport.
            # Closing it releases SQLite WAL/file handles before the process
            # exits, which is observable on Windows and important for embedders.
            active.close()

    server = MCPServer("CGAL Master MCP", version="0.2-foundation",
                       instructions=guide.instructions("en"),
                       lifespan=lifespan)

    @tool(name="cgal_get_guide")
    def get_guide(topic: str = "start", lang: str = "en") -> dict[str, Any]:
        """CALL THIS FIRST. Built-in guide (markdown, generated from the live registry). topic: 'start' quickstart; 'recipes' verified if-the-user-wants-X workflows ('recipe:<id>' for one); 'op:<operation_id>' complete card with parameters, units, limits and a runnable example; 'families', 'errors', 'glossary', 'limits-and-status', 'index'. lang: 'en' or 'ja'. Same content as resources cgal://guide/..."""
        return guide.get_tool_result(topic, lang)

    # search/plan use the registry's in-memory SQLite index, created on the main thread;
    # these two tools run on the event-loop thread (async) instead of a worker thread.
    @tool(name="cgal_capabilities_search")
    async def capabilities_search(query: str, artifact_ids: list[str] | None = None,
                            constraints: dict[str, Any] | None = None,
                            limit: int = 8) -> dict[str, Any]:
        """Step 1 of discovery: rank registered operations for a goal in plain words (English or Japanese). Read candidates (operation_id, status, why, input_types, output_types) and query_analysis; abstained=true or unsupported_cgal_packages means nothing executable fits, so say so. Then read cgal_get_guide topic 'op:<operation_id>'. artifact_ids narrows by input types; constraints may hold status, dependencies, kernel, allowed_licenses."""
        return active.capabilities_search(query, artifact_ids, constraints, limit)

    @tool(name="cgal_capabilities_describe")
    def capabilities_describe(operation_id: str) -> dict[str, Any]:
        """Raw registry definition of one operation (schemas, preconditions, validators, sources) and whether it is executable. For a readable card with an example use cgal_get_guide topic 'op:<operation_id>'."""
        return active.capabilities_describe(operation_id)

    @tool(name="cgal_plan")
    async def plan(request: dict[str, Any]) -> dict[str, Any]:
        """Build an immutable typed plan; nothing runs yet. Single operation: {"operation_id", "inputs": {<slot>: <artifact_id>}, "parameters": {...}}. Pipeline: {"steps": [{"id", "operation", "inputs", "parameters"}]} where an input may be {"step", "slot"}; optional "rules", "policy", "alternatives" (declared fallbacks). A "goal" string routes only when exactly one operation clearly fits; otherwise ambiguous_route returns options to put to the user. Mandatory validators are inserted automatically. Returns plan_id and an estimate."""
        return active.plan(request)

    @tool(name="cgal_execute")
    async def execute(plan_id: str, execution: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a plan asynchronously and return job_id at once; then poll cgal_job_status. Optional execution={"wall_time_ms", "memory_mb"} must stay within the limits cgal_system_health reports."""
        options = execution or {}
        return await active.execute(plan_id, wall_time_ms=options.get("wall_time_ms"),
                                    memory_mb=options.get("memory_mb"))

    @tool(name="cgal_validate")
    def validate(artifact_id: str, against: str,
                 operation_id: str = "hull.validate.convex_enclosure",
                 parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Plan a standalone re-check of an existing candidate artifact against its source artifact (default validator hull.validate.convex_enclosure; pass operation_id for another validator). Run the returned plan_id with cgal_execute."""
        return active.validate(artifact_id, against, operation_id, parameters)

    @tool(name="cgal_artifact_inspect")
    def artifact_inspect(artifact_id: str) -> dict[str, Any]:
        """Read an artifact's immutable type, unit, size, sha256, geometry properties (counts, health) and provenance. Use it to check an import before planning."""
        return active.artifact_inspect(artifact_id)

    @tool(name="cgal_docs_search")
    def docs_search(query: str, limit: int = 10) -> dict[str, Any]:
        """Search the pinned CGAL 6.2.1 documentation/header index. Hits are information only, never executable operations; use cgal_capabilities_search to find something to run."""
        return active.docs_search(query, limit)

    @tool(name="cgal_system_health")
    async def system_health() -> dict[str, Any]:
        """Report registry revision, artifact-store state, native worker build and the enforced resource limits (concurrency, memory, wall time). Call it on worker_* or manifest_* errors and before choosing execution limits."""
        return await active.system_health()

    @tool(name="cgal_artifact_import")
    def artifact_import(path: str, unit: str, format: str | None = None,
                        artifact_type: str | None = None) -> dict[str, Any]:
        """Import a file readable by the server (off, obj, ply, stl, xyz, json; at most 512 MiB) as an immutable artifact. unit is mandatory: mm, cm or m ('none' for reports and unitless types). Pass artifact_type (for example TriangleSurfaceMesh, PointSet3, Polygon2) when the extension is ambiguous. Parsed only, never repaired. Returns artifact_id."""
        return active.artifact_import(path, unit, format, artifact_type)

    @tool(name="cgal_artifact_export")
    def artifact_export(artifact_id: str, path: str) -> dict[str, Any]:
        """Write an artifact's exact bytes to a NEW path on the server host; existing files are refused and HTTP deployments restrict the allowed roots."""
        return active.artifact_export(artifact_id, path)

    @tool(name="cgal_job_status")
    def job_status(job_id: str) -> dict[str, Any]:
        """Poll a job. state: queued, running, succeeded, rejected (a validator refused the result), failed or cancelled. On succeeded read outputs (artifact_id, type, unit, properties) and validation[].report; on rejected or failed read error {class, code, message}."""
        return active.job_status(job_id)

    @tool(name="cgal_job_cancel")
    async def job_cancel(job_id: str) -> dict[str, Any]:
        """Cancel a queued or running job. Unverified output is never published."""
        return await active.job_cancel(job_id)

    for lang in ("en", "ja"):
        _register_guide_resources(server, guide, lang)
    _register_prompts(server, guide)
    return server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CGAL Master MCP")
    parser.add_argument("transport", nargs="?", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--path", default="/mcp")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.transport == "stdio":
        server = create_server()
        server.run(transport="stdio")
    else:
        configured_roots = os.environ.get("CGAL_MASTER_FILE_ROOTS", "")
        roots = [Path(item) for item in configured_roots.split(os.pathsep) if item]
        server = create_server(default_runtime(allowed_file_roots=roots))
        server.run(transport="streamable-http", host=args.host, port=args.port,
                   streamable_http_path=args.path)


if __name__ == "__main__":
    main()
