"""Small definitions are returned by search; full definitions load on demand."""
from dataclasses import dataclass, asdict
import re

@dataclass(frozen=True)
class Capability:
    id: str
    summary: str
    aliases: tuple[str, ...]
    status: str
    preconditions: tuple[str, ...]
    source: str

CATALOG = (
    Capability("mesh.simplify", "Simplify a triangle surface mesh",
        ("simplification", "軽量化", "簡略化"), "planned",
        ("valid_triangle_mesh", "finite_coordinates", "explicit_units"),
        "https://doc.cgal.org/6.2.1/Surface_mesh_simplification/index.html"),
    Capability("mesh.simplify.plane_line", "Garland-Heckbert plane and line policies",
        ("garland", "heckbert", "plane+line"), "planned",
        ("valid_triangle_mesh", "finite_coordinates", "explicit_units"),
        "https://doc.cgal.org/6.2.1/Surface_mesh_simplification/index.html"),
    Capability("mesh.envelope", "Polyhedral envelope placement filter",
        ("envelope", "包絡"), "planned",
        ("valid_triangle_mesh", "positive_tolerance"),
        "https://doc.cgal.org/6.2.1/Surface_mesh_simplification/index.html"),
    Capability("mesh.constraints", "Constrained edges and placement",
        ("constraints", "拘束", "境界保持"), "planned",
        ("valid_triangle_mesh", "valid_constraint_mapping"),
        "https://doc.cgal.org/6.2.1/Surface_mesh_simplification/index.html"),
    Capability("mesh.hausdorff", "Verify bidirectional Hausdorff distance",
        ("hausdorff", "ハウスドルフ", "誤差検証"), "planned",
        ("two_valid_triangle_meshes", "matching_units"),
        "https://doc.cgal.org/6.2.1/Polygon_mesh_processing/index.html"),
)

def describe(capability_id: str) -> dict:
    for capability in CATALOG:
        if capability.id == capability_id:
            return asdict(capability)
    raise KeyError(f"Unknown capability: {capability_id}")

def discover(query: str, limit: int = 5, implemented_only: bool = False) -> list[dict]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be nonempty")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError("limit must be an integer in [1, 20]")
    query = query.strip().casefold()
    tokens = set(re.findall(r"\w+", query))
    results = []
    for capability in CATALOG:
        if implemented_only and capability.status not in ("implemented", "verified"):
            continue
        terms = (capability.id, *capability.aliases)
        exact = any(query == term.casefold() for term in terms)
        aliases = sum(term.casefold() in query for term in terms)
        words = set(re.findall(r"\w+", " ".join((*terms, capability.summary)).casefold()))
        score = 100 * exact + 10 * aliases + len(tokens & words)
        if score:
            results.append({"id": capability.id, "summary": capability.summary,
                            "status": capability.status, "score": score})
    return sorted(results, key=lambda item: (-item["score"], item["id"]))[:limit]

def require_executable(capability_id: str) -> dict:
    definition = describe(capability_id)
    if definition["status"] not in ("implemented", "verified"):
        raise NotImplementedError(f"{capability_id} has no verified worker implementation")
    return definition
