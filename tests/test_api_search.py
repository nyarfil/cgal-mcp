import json, unittest
from pathlib import Path
from cgal_mcp.api_search import search_api

class APISearchTests(unittest.TestCase):
    def test_pinned_index_has_at_least_100_real_headers(self):
        entries=json.loads(Path("cgal_mcp/api_index.json").read_text())["entries"]
        self.assertGreaterEqual(len(entries),100)
        self.assertEqual(len(entries),len({e["id"] for e in entries}))
        self.assertTrue(all(not e["executable"] and "/v6.2.1/" in e["source"] for e in entries))
    def test_long_tail_search(self):
        self.assertTrue(any("Fuzzy_sphere" in e["name"] for e in search_api("Fuzzy sphere")))
    def test_unknown_search(self):
        self.assertEqual(search_api("zzunknownzz"),[])
