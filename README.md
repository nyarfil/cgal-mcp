# CGAL Master MCP

A standalone MCP server that discovers, plans, executes and validates
[CGAL](https://www.cgal.org/) geometry operations. Version 1.0.0 makes the Master
server the only supported product (`cgal-mcp`). The earlier v0.1 mesh-simplification
server is deprecated and superseded; it remains in the tree only for compatibility
tests (`cgal-mcp-legacy`).

Japanese: [docs/master/SCOPE_CORRECTION_JA.md](docs/master/SCOPE_CORRECTION_JA.md)
(scope and development order) and the `*_JA.md` files in [docs/master](docs/master).

## What it is

- A small fixed control surface (12 tools) over a data-driven Operation registry.
- Typed, immutable artifacts and plans (DAG), persisted in SQLite.
- Router hard gates, operation-specific validators that are mandatory for mutation,
  worker resource limits, fault isolation (a failed candidate never replaces the input).
- A C++17 worker built against official CGAL 6.2.1.
- Package catalog of all 126 CGAL 6.2.1 packages with source, license evidence and
  status (cataloged / implemented / validated / blocked / excluded kept distinct).
- Optional local full-text index of the version-pinned CGAL docs/headers/examples
  (reference only, never executable).
- Transports: stdio and Streamable HTTP.

## Status (honest)

| Item | State |
|---|---|
| Per-requirement replay validation (reference plan 7.1-7.15) | 80/80 passed (with OpenGR and SCIP built in) |
| Standalone acceptance (`standalone_accepted`) | **false** |
| Search acceptance gate | unmet |
| Host matrix gate (desktop UI tool selection, Cursor live calls) | unmet |
| Performance / AABB gate | unmet |
| Package harvest license review | unmet (some packages need human review) |

Passing 80 requirements does not mean "all of CGAL" is available. Many packages are
cataloged only; see [docs/master/PACKAGE_HARVEST_JA.md](docs/master/PACKAGE_HARVEST_JA.md)
and [docs/master/CAPABILITY_ACCEPTANCE_JA.md](docs/master/CAPABILITY_ACCEPTANCE_JA.md).

Limits worth knowing: `mesh.distance.symmetric_hausdorff` and other operations with an
independent validator accept at most 400 faces (larger inputs are refused before
computing with `PRECONDITION_FAILED`); input meshes are triangle meshes; materials, UVs,
B-rep and face IDs are not preserved; the server is for a trusted local host (no
multi-user auth).

## Install

Requires Python 3.10+, a C++17 compiler, CMake 3.22+.

```sh
git clone https://github.com/nyarfil/cgal-mcp.git
cd cgal-mcp
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e '.[mesh]'
```

Build the worker (CGAL 6.2.1 source; Linux example):

```sh
sudo apt-get install -y libboost-all-dev libgmp-dev libmpfr-dev libeigen3-dev nlohmann-json3-dev
mkdir -p work
curl -fL https://github.com/CGAL/cgal/releases/download/v6.2.1/CGAL-6.2.1.tar.xz -o work/cgal.tar.xz
echo 'b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf  work/cgal.tar.xz' | sha256sum -c -
tar -xf work/cgal.tar.xz -C work
cmake -S worker -B build-master -DCGAL_DIR="$PWD/work/CGAL-6.2.1" -DCMAKE_BUILD_TYPE=Release
cmake --build build-master --target cgal-master-worker --parallel 1
```

Windows (Visual Studio, vcpkg): see [docs/windows.md](docs/windows.md); the local build is
`cmake --build build-master --config Release --target cgal-master-worker --parallel 1`.

Optional dependencies (OpenGR v2023.11, SoPlex 8.0.3 + SCIP 10.0.3; all Apache-2.0):
without them the worker still builds, but `CGAL::OpenGR` registration (7.9.05) and
Polygonal surface reconstruction / PolyFit (7.10.02) return
`UNSUPPORTED` / `OPTIONAL_DEPENDENCY_NOT_BUILT`, and the 80/80 figure applies only to
a worker built with both. Details and hashes:
[docs/master/THIRD_PARTY_DEPENDENCIES_JA.md](docs/master/THIRD_PARTY_DEPENDENCIES_JA.md).

## Register in an MCP host (stdio)

Command `cgal-mcp` (or `python -m cgal_mcp.master.server stdio`). Replace absolute paths.

```json
{
  "command": "/absolute/path/cgal-mcp/.venv/bin/python",
  "args": ["-m", "cgal_mcp.master.server", "stdio"],
  "env": {
    "CGAL_MASTER_WORKER": "/absolute/path/cgal-mcp/build-master/cgal-master-worker",
    "CGAL_MASTER_DATA": "/absolute/path/cgal-mcp/work/master-data",
    "CGAL_MASTER_CATALOG": "/absolute/path/cgal-mcp/catalog",
    "CGAL_MASTER_DOCS_INDEX": "/absolute/path/cgal-mcp/work/master-docs-index.sqlite"
  }
}
```

- Claude Code: put the object under `mcpServers.cgal-mcp` in `.mcp.json` (add `"type": "stdio"`),
  or `claude mcp add`.
- Codex: `[mcp_servers.cgal-mcp]` with `command`, `args` and `[mcp_servers.cgal-mcp.env]` in `~/.codex/config.toml`.
- Cursor: same object under `mcpServers` in `.cursor/mcp.json`.

Optional env: `CGAL_MASTER_PERSISTENT_WORKERS`, `CGAL_MASTER_RESULT_CACHE` (both opt-in),
`CGAL_MASTER_FILE_ROOTS`, `CGAL_MASTER_MAX_MEMORY_MB`, `CGAL_MASTER_MAX_WALL_TIME_MS`.
Streamable HTTP: `cgal-mcp streamable-http --host 127.0.0.1 --port 8000`.
Connection evidence and what is not yet confirmed: [docs/master/HOST_CONNECTION_JA.md](docs/master/HOST_CONNECTION_JA.md).

## First contact

Read the resource `cgal://guide/start` or call `cgal_get_guide` first. The guide lists
the tools, resources, templates and prompts, and the recommended flow:
search capabilities -> describe -> import artifact -> plan -> validate -> execute ->
inspect result -> export. Unknown operations never execute generated C++.

## Verify

```sh
python -m unittest discover -s tests -v
python tests/master_worker_smoke.py build-master/Release/cgal-master-worker.exe   # path per platform
python -m tests.master_mcp_e2e auto
```

## Deprecated: v0.1 server

`cgal_mcp.server` (`cgal-mcp-legacy`) is the former 11-tool mesh-simplification server.
Do not register it for new use. Its tests (`tests.mcp_e2e auto|legacy`,
`tests/worker_smoke.py`) still run to keep the code honest. History:
[docs/status.md](docs/status.md), [docs/validation.md](docs/validation.md).

## License and provenance

CGAL is GPL/commercial per package (this repository has no separate license file yet), so check
the package terms before redistributing a build that bundles CGAL. Per-package license
evidence and review state: [docs/master/PACKAGE_HARVEST_JA.md](docs/master/PACKAGE_HARVEST_JA.md).
Reference documents are preserved unchanged in `docs/master/CGAL_Master_MCP_*.md`.
StellaCAD integration: [docs/stellacad-integration.md](docs/stellacad-integration.md).
