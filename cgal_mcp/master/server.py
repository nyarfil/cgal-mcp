"""Twelve stable MCP tools over the data-driven Master runtime."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from .runtime import MasterRuntime, default_runtime


def create_server(runtime: MasterRuntime | None = None) -> MCPServer:
    active = runtime or default_runtime()
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
                       instructions="Discover registered operations, plan typed DAGs, execute isolated workers, and inspect validated immutable artifacts.",
                       lifespan=lifespan)

    @server.tool(name="cgal_capabilities_search")
    def capabilities_search(query: str, artifact_ids: list[str] | None = None,
                            constraints: dict[str, Any] | None = None,
                            limit: int = 8) -> dict[str, Any]:
        """Search the operation registry with type, status, dependency, kernel and license gates."""
        return active.capabilities_search(query, artifact_ids, constraints, limit)

    @server.tool(name="cgal_capabilities_describe")
    def capabilities_describe(operation_id: str) -> dict[str, Any]:
        """Return one complete operation definition and its implementation status."""
        return active.capabilities_describe(operation_id)

    @server.tool(name="cgal_plan")
    def plan(request: dict[str, Any]) -> dict[str, Any]:
        """Persist an immutable typed plan. Direct requests should name operation_id, inputs and parameters."""
        return active.plan(request)

    @server.tool(name="cgal_execute")
    async def execute(plan_id: str, execution: dict[str, Any] | None = None) -> dict[str, Any]:
        """Queue an immutable plan and immediately return its persistent job identity."""
        options = execution or {}
        return await active.execute(plan_id, wall_time_ms=options.get("wall_time_ms"),
                                    memory_mb=options.get("memory_mb"))

    @server.tool(name="cgal_validate")
    def validate(artifact_id: str, against: str,
                 operation_id: str = "hull.validate.convex_enclosure",
                 parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a validator plan for a candidate artifact against its source artifact."""
        return active.validate(artifact_id, against, operation_id, parameters)

    @server.tool(name="cgal_artifact_inspect")
    def artifact_inspect(artifact_id: str) -> dict[str, Any]:
        """Inspect immutable type, unit, syntax and geometry-health metadata."""
        return active.artifact_inspect(artifact_id)

    @server.tool(name="cgal_docs_search")
    def docs_search(query: str, limit: int = 10) -> dict[str, Any]:
        """Search generated, pinned CGAL package/docs/source catalog records."""
        return active.docs_search(query, limit)

    @server.tool(name="cgal_system_health")
    async def system_health() -> dict[str, Any]:
        """Report registry, artifact store, worker build and enforced resource-limit state."""
        return await active.system_health()

    @server.tool(name="cgal_artifact_import")
    def artifact_import(path: str, unit: str, format: str | None = None,
                        artifact_type: str | None = None) -> dict[str, Any]:
        """Copy at most 512 MiB into immutable storage and parse syntax without geometry repair."""
        return active.artifact_import(path, unit, format, artifact_type)

    @server.tool(name="cgal_artifact_export")
    def artifact_export(artifact_id: str, path: str) -> dict[str, Any]:
        """Export exact stored bytes to a new path; existing destinations are refused."""
        return active.artifact_export(artifact_id, path)

    @server.tool(name="cgal_job_status")
    def job_status(job_id: str) -> dict[str, Any]:
        """Read persistent execution and validation status for an asynchronous job."""
        return active.job_status(job_id)

    @server.tool(name="cgal_job_cancel")
    async def job_cancel(job_id: str) -> dict[str, Any]:
        """Cancel a queued or running worker job and persist the terminal state."""
        return await active.job_cancel(job_id)

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
