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

    async def test_router_chooses_exact_capability_and_correct_recipe(self):
        from cgal_mcp.server import route_goal,describe_capability
        self.assertEqual(route_goal("ハウスドルフ")["selected"],"mesh.hausdorff")
        self.assertIn("plan_hausdorff",route_goal("ハウスドルフ")["workflow"])
        self.assertIsNone(route_goal("unrelated_zz")["selected"])
        self.assertNotIn("edge_ratio",describe_capability("mesh.hausdorff")["execution_schema"]["properties"])
