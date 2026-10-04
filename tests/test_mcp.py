import unittest
from mcp import Client
from cgal_mcp.server import mcp

class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_official_client_discovery(self):
        async with Client(mcp) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            self.assertTrue({"discover_capabilities", "describe_capability", "search_api", "execute_plan", "cancel_job"} <= names)
            self.assertLessEqual(len(names), 11)
            result = await client.call_tool("discover_capabilities", {"query": "軽量化"})
            self.assertFalse(result.is_error)
            detail = await client.call_tool("describe_capability",
                                           {"capability_id": "mesh.simplify"})
            self.assertFalse(detail.is_error)
