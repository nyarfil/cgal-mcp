"""Bundle the versioned package snapshot for installations outside the checkout."""
from __future__ import annotations

import argparse
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
FILES = ("baseline.json", "packages.json", "docs_index.jsonl")


def synchronize(check_only: bool = False) -> None:
    destination = REPO / "cgal_mcp/master/catalog"
    for name in FILES:
        source = REPO / "catalog" / name
        target = destination / name
        content = source.read_bytes()
        if check_only:
            if not target.is_file() or target.read_bytes() != content:
                raise ValueError(f"Bundled catalog differs from canonical snapshot: {name}")
        else:
            destination.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    synchronize(options.check)
    print("Bundled Master package snapshot: " + ("MATCH" if options.check else "UPDATED"))
