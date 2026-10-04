"""Private, resource-limited syntax inspection process.

The parent assigns the process to the same hard resource-control mechanism used
for CGAL workers before sending this single JSON request.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .errors import MasterError
from .formats import inspect_bytes


def main() -> None:
    try:
        request = json.loads(sys.stdin.buffer.readline())
        path = Path(request["path"]).resolve(strict=True)
        maximum = int(request["maximum_bytes"])
        if path.stat().st_size > maximum:
            raise ValueError("inspection input exceeds its byte limit")
        inspection = inspect_bytes(path.read_bytes(), request["format"], request.get("type"))
        result = {"status": "ok", "inspection": {
            "geometry_type": inspection.geometry_type, "format": inspection.format,
            "properties": inspection.properties, "metadata": inspection.metadata}}
    except MasterError as exc:
        result = {"status": "error", "error": exc.as_dict()}
    except MemoryError:
        result = {"status": "error", "error": {"class": "resource_limit",
            "code": "inspection_memory_limit", "message": "Geometry inspection exceeded its memory limit",
            "recoverable": False, "suggested_operations": []}}
    except Exception as exc:
        result = {"status": "error", "error": {"class": "invalid_input",
            "code": "inspection_failed", "message": str(exc),
            "recoverable": False, "suggested_operations": []}}
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
