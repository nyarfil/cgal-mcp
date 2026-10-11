# StellaCAD integration files

Since 1.0.0 StellaCAD registers the Master server as `cgal-mcp`. `stella_cgal_mcp.py` and
`verify_connection.py` are the DEPRECATED v0.1 sidecar, preserved for history only; do not register them.
The Master adapter below is a derived-file bridge, not CGAL Master acceptance.
The Master development sequence is defined in `docs/master/SCOPE_CORRECTION_JA.md`.

Copy `stella_cgal_mcp.py` and `verify_connection.py` into the selected StellaCAD
repository's `integration/cgal/` before running `scripts/link_stella.py`.
Use the CGAL repository's dedicated Python environment (`pip install -e '.[mesh]'`).
`CGAL_INTEGRATION_JA.md` records the current Windows deployment and boundaries.
The script registers a new-file OFF/STL tool; it never replaces native CAD sources.

## Master adapter (native `cgal-master` registration)

`master_derive.py`, `test_master_derive.py` and `verify_master_connection.py` are copies of the StellaCAD-side
files (canonical location: StellaCAD `integration/cgal/`, which also holds `fixtures/`). They read the project
`.mcp.json` entry `cgal-master` and publish derived OFF + provenance only after all mandatory validators pass.
