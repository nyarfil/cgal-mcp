import unittest
from cgal_mcp.catalog import CATALOG, discover, describe, require_executable

class CatalogTests(unittest.TestCase):
    def test_japanese_alias(self):
        self.assertEqual(discover("軽量化")[0]["id"], "mesh.simplify")

    def test_exact_specific_capability(self):
        self.assertEqual(discover("mesh.simplify.plane_line")[0]["id"],
                         "mesh.simplify.plane_line")

    def test_definition_is_not_loaded_into_search(self):
        self.assertNotIn("preconditions", discover("hausdorff")[0])
        self.assertIn("preconditions", describe("mesh.hausdorff"))

    def test_unknown_goal_does_not_select_arbitrary_tool(self):
        self.assertEqual(discover("unrelated_operation_zz"), [])

    def test_no_planned_tool_is_executable(self):
        self.assertEqual(discover("軽量化", implemented_only=True), [])
        for item in CATALOG:
            with self.assertRaises(NotImplementedError):
                require_executable(item.id)

    def test_unknown_id(self):
        with self.assertRaises(KeyError):
            describe("does.not.exist")

    def test_limits_and_empty_input(self):
        for limit in (0, 21, True, 2.5):
            with self.assertRaises(ValueError):
                discover("mesh", limit=limit)
        with self.assertRaises(ValueError):
            discover(" ")

    def test_unique_ids_and_deterministic_search(self):
        self.assertEqual(len(CATALOG), len({item.id for item in CATALOG}))
        self.assertEqual(discover("mesh"), discover("mesh"))

if __name__ == "__main__":
    unittest.main()
