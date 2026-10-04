"""MCP transport for the capability catalog; no geometry execution advertised."""
from mcp.server import MCPServer
from cgal_mcp.catalog import discover, describe

mcp = MCPServer("CGAL MCP")

@mcp.tool()
def discover_capabilities(query: str, limit: int = 5) -> list[dict]:
    """Search capabilities. Planned results cannot be executed."""
    return discover(query, limit)

@mcp.tool()
def describe_capability(capability_id: str) -> dict:
    """Load one capability's full definition and implementation state."""
    return describe(capability_id)

@mcp.resource("cgal://capability/{capability_id}")
def capability_definition(capability_id: str) -> str:
    """Read an on-demand capability definition."""
    import json
    return json.dumps(describe(capability_id), ensure_ascii=False)

if __name__ == '__main__':
    mcp.run(transport='stdio')
