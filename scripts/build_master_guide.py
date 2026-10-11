"""Regenerate the AI-facing guide snapshot (bundle + readable docs).

    .venv/Scripts/python.exe scripts/build_master_guide.py          # write
    .venv/Scripts/python.exe scripts/build_master_guide.py --check  # exit 1 when stale

The bundle (cgal_mcp/master/guide/guide.json) is what the MCP server serves; the
Markdown files under docs/master/guide/ are readable renderings of the same data.
Both are deterministic functions of operations.json, search_data.json, the package
catalog, docs/master/workflows.json and the replay contracts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cgal_mcp.master import guide_build  # noqa: E402

BUNDLE = REPO / "cgal_mcp/master/guide/guide.json"
DOCS = REPO / "docs/master/guide"


def expected(root: Path = REPO) -> dict[Path, str]:
    text = guide_build.render_bundle(root)
    bundle = json.loads(text)
    files = {BUNDLE: text}
    for name, content in guide_build.doc_files(bundle).items():
        files[DOCS / name] = content
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for path, content in expected().items():
        current = path.read_bytes().decode("utf-8") if path.is_file() else None
        if current != content:
            stale.append(path)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8", newline="\n") as stream:
                    stream.write(content)
    if args.check and stale:
        print("stale: " + ", ".join(str(p.relative_to(REPO)) for p in stale))
        return 1
    print("guide up to date" if args.check else f"wrote {len(stale)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
