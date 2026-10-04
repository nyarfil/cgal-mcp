"""StellaCAD's CGAL sidecar: core MCP plus immutable derived-file export."""
from typing import Any
from cgal_mcp import server
from cgal_mcp.file_bridge import simplify_file
from mcp.server.mcpserver.exceptions import ToolError


@server.mcp.tool()
async def stella_cgal_simplify_file(input_path: str, output_path: str, unit: str,
                                   parameters: dict[str, Any]) -> dict[str, Any]:
    """Simplify an OFF/STL file into a NEW OFF/STL file after Hausdorff verification.

    Unit must be explicit (mm/cm/m). parameters require edge_ratio, tolerance,
    error_bound, and optionally envelope/preserve_border/constrained_edges.
    Source CAD and existing output files are never overwritten. This produces
    a derived mesh, not a replacement B-rep or a native CAD Undo transaction.
    """
    try:
        return await simplify_file(input_path, output_path, unit, parameters, server.runtime())
    except (ValueError,OSError,RuntimeError) as exc:
        raise ToolError(str(exc)) from exc


if __name__ == "__main__":
    server.main()
