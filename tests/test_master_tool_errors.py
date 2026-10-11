import asyncio
import json
import unittest

from mcp.server.mcpserver.exceptions import ToolError

from cgal_mcp.master.errors import InvalidInput
from cgal_mcp.master.server import _structured_errors


class StructuredToolErrors(unittest.TestCase):
    def test_sync_and_async_refusals_carry_code_and_message(self):
        def sync_tool(value: int) -> int:
            raise InvalidInput("type_mismatch", "Expected TriangleSurfaceMesh, parsed PolygonSoup3")

        async def async_tool() -> None:
            raise InvalidInput("input_binding", "slot missing")

        with self.assertRaises(ToolError) as caught:
            _structured_errors(sync_tool)(1)
        payload = json.loads(str(caught.exception))
        self.assertEqual((payload["class"], payload["code"]), ("invalid_input", "type_mismatch"))
        self.assertIn("PolygonSoup3", payload["message"])
        with self.assertRaises(ToolError) as caught:
            asyncio.run(_structured_errors(async_tool)())
        self.assertEqual(json.loads(str(caught.exception))["code"], "input_binding")
        self.assertTrue(asyncio.iscoroutinefunction(_structured_errors(async_tool)))

    def test_success_and_foreign_exceptions_pass_through(self):
        self.assertEqual(_structured_errors(lambda: 7)(), 7)

        def broken():
            raise ZeroDivisionError

        with self.assertRaises(ZeroDivisionError):
            _structured_errors(broken)()


if __name__ == "__main__":
    unittest.main()
