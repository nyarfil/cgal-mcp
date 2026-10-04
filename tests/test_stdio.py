import sys,unittest
from mcp import Client,StdioServerParameters
class StdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_modern_and_legacy(self):
        for mode in ("auto","legacy"):
            async with Client(StdioServerParameters(command=sys.executable,
                          args=["-m","cgal_mcp.server"]),mode=mode) as client:
                self.assertEqual(len((await client.list_tools()).tools),10)
                self.assertFalse((await client.call_tool("search_api",{"query":"Fuzzy sphere"})).is_error)
                self.assertTrue((await client.read_resource("cgal://capability/mesh.simplify")).contents)
