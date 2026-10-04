"""Verify a built wheel outside the checkout with its bundled 126-package catalog."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


CHECK = r'''
import importlib.metadata
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
import cgal_mcp.master.runtime as module
assert Path(module.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
runtime = module.MasterRuntime(Path(sys.argv[2]))
try:
    assert runtime.catalog_root == Path(module.__file__).with_name("catalog")
    packages = json.loads((runtime.catalog_root / "packages.json").read_text(encoding="utf-8"))
    assert len(packages["packages"]) == 126
    result = runtime.docs_search("Convex")
    assert result["index_available"] and result["results"], result
    assert all(r["executable"] is False and r["scope"] == "reference" for r in result["results"])
    assert runtime.registry.get("hull.convex_3")["id"] == "hull.convex_3"
    entrypoints = importlib.metadata.distribution("cgal-mcp").entry_points
    assert any(e.name == "cgal-master-mcp" and e.value == "cgal_mcp.master.server:main" for e in entrypoints)
finally:
    runtime.close()
print("Installed wheel outside checkout + bundled 126 packages: PASS")
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise ValueError("A built wheel file is required")
    with tempfile.TemporaryDirectory(prefix="master-wheel-check-") as folder:
        root = Path(folder)
        target = root / "installed"
        subprocess.run([sys.executable, "-m", "pip", "install", str(wheel), "--no-deps",
                        "--target", str(target)], check=True, capture_output=True)
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("CGAL_MASTER_")}
        subprocess.run([sys.executable, "-I", "-c", CHECK, str(target), str(root / "data")],
                       cwd=root, env=environment, check=True)


if __name__ == "__main__":
    main()
