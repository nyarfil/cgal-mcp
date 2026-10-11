# Provisional StellaCAD sidecar

This directory preserves the installed v0.1 sidecar source and connection test.
It is a provisional integration of one mesh capability, not CGAL Master acceptance.
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
