"""Fixed small MCP entrypoints; execution definitions load on demand."""
import os
from pathlib import Path
from typing import Any
from mcp.server import MCPServer
from cgal_mcp.catalog import discover, describe
from cgal_mcp.runtime import Runtime, SimplifyParameters

mcp=MCPServer("CGAL MCP")
_runtime=None

def runtime():
    global _runtime
    if _runtime is None:
        _runtime=Runtime(Path(os.environ.get("CGAL_MCP_DATA","work/cgal-mcp-data")),
            Path(os.environ.get("CGAL_MCP_WORKER","build/cgal-worker")),
            Path(os.environ.get("CGAL_MCP_DISTANCE","build/cgal-distance")))
    return _runtime

@mcp.tool()
def discover_capabilities(query: str, limit: int=5) -> list[dict[str, Any]]:
    """Find capability candidates; inspect their status before choosing."""
    return discover(query,limit)

@mcp.tool()
def describe_capability(capability_id: str) -> dict[str, Any]:
    """Load one full capability definition and execution prerequisites."""
    definition=describe(capability_id)
    definition["implementation"]="worker_available" if capability_id in {
        "mesh.simplify","mesh.simplify.plane_line","mesh.envelope","mesh.constraints","mesh.hausdorff"} else "indexed"
    definition["execution_schema"]=SimplifyParameters.model_json_schema()
    definition["execution_recipe"]="register_mesh → plan_simplification → execute_plan → job_status → get_artifact"
    return definition

@mcp.tool()
def search_api(query: str, limit: int=5) -> list[dict[str, Any]]:
    """Search 102 pinned CGAL headers. Indexed APIs are not executable."""
    from cgal_mcp.api_search import search_api as search
    return search(query,limit)

@mcp.tool()
def register_mesh(off: str, unit: str) -> dict[str, Any]:
    """Register immutable ASCII triangle OFF. Explicit unit: mm, cm or m; maximum 4 MiB."""
    return runtime().register(off,unit)

@mcp.tool()
def plan_simplification(asset_id: str, parameters: dict) -> dict[str, Any]:
    """Validate parameters and constraints; return immutable hashed execution plan.
    parameters require edge_ratio, tolerance, error_bound. Optional envelope,
    preserve_border and constrained_edges use input vertex indices.
    """
    return runtime().plan(asset_id,parameters)

@mcp.tool()
def route_goal(goal: str) -> dict[str, Any]:
    """Rank candidates and report the supported workflow; never silently choose a weak match."""
    candidates=discover(goal,5)
    return {"candidates":candidates,"workflow":"describe_capability → register_mesh → plan_simplification",
            "requires_explicit_parameters":True,"selected":None}

@mcp.tool()
async def execute_plan(plan_id: str) -> dict[str, Any]:
    """Queue a stored validated plan; returns job_id immediately."""
    return runtime().execute(plan_id)

@mcp.tool()
def job_status(job_id: str) -> dict[str, Any]:
    """Return state, calculation, verification, audit and accepted artifact ID."""
    return runtime().status(job_id)

@mcp.tool()
async def cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel queued/running job and stop its subprocess."""
    return await runtime().cancel(job_id)

@mcp.tool()
def get_artifact(asset_id: str) -> dict[str, Any]:
    """Read a registered input or accepted output artifact with unit and SHA-256."""
    return runtime().artifact(asset_id)

@mcp.resource("cgal://capability/{capability_id}")
def capability_definition(capability_id: str) -> str:
    import json
    return json.dumps(describe_capability(capability_id),ensure_ascii=False)

def main():
    mcp.run(transport="stdio")

if __name__=="__main__":
    main()
