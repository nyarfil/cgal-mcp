"""Planning provenance must not vary with host newlines or build evidence."""
import copy
import json
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from build_major_inventory import requirement_description_view
from master_acceptance import extract_requirements


class PlanningProvenanceTests(unittest.TestCase):
    def test_host_newlines_and_execution_bindings_do_not_change_planning_input(self):
        requirements = extract_requirements(REPO)
        encoded = json.dumps(requirements, ensure_ascii=False, indent=2)
        lf = json.loads(encoded)
        crlf = json.loads(encoded.replace("\n", "\r\n"))
        crlf["families"][6]["requirements"][0]["operation_ids"] = ["mesh.simplify.edge_collapse"]
        crlf["families"][6]["requirements"][0]["evidence"] = [{"sha256": "a" * 64}]
        self.assertEqual(requirement_description_view(lf), requirement_description_view(crlf))
        modified = copy.deepcopy(lf)
        modified["families"][6]["requirements"][0]["description"] = "changed scope"
        self.assertNotEqual(requirement_description_view(lf), requirement_description_view(modified))
        modified = copy.deepcopy(lf)
        modified["families"][6]["requirements"][0]["required"] = False
        self.assertNotEqual(requirement_description_view(lf), requirement_description_view(modified))


if __name__ == "__main__":
    unittest.main()
