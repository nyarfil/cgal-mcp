"""Test-only fault-injecting worker proxy for the robustness measurement.

This file is never installed or referenced by production code. The Master
supervisor accepts any executable with a worker manifest, so the measurement
points ``CGAL_MASTER_WORKER`` semantics at this script (via ``MasterRuntime(worker=...)``).
The *real* native worker binary is untouched: ``--manifest`` is forwarded verbatim
and, with no fault selected, every request is forwarded byte-for-byte, so manifest
and registry verification is the production path.

A fault is selected only by the environment variable ``CGAL_ROBUST_FAULT`` set by
the measurement harness in its own process. Nothing in the JSONL protocol input
can select a fault. ``CGAL_ROBUST_REAL_WORKER`` names the native worker.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def real_worker() -> list[str]:
    return [os.environ["CGAL_ROBUST_REAL_WORKER"]]


def forward(arguments: list[str], payload: bytes) -> tuple[int, bytes, bytes]:
    done = subprocess.run(real_worker() + arguments, input=payload, capture_output=True)
    return done.returncode, done.stdout, done.stderr


def relay(code: int, out: bytes, err: bytes) -> None:
    sys.stdout.buffer.write(out)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(err)
    sys.stderr.buffer.flush()
    sys.exit(code)


def main() -> None:
    arguments = sys.argv[1:]
    if "--manifest" in arguments:
        relay(*forward(arguments, b""))
    fault = os.environ.get("CGAL_ROBUST_FAULT", "none")
    payload = sys.stdin.buffer.read()
    if fault == "none":
        relay(*forward(arguments, payload))
    try:
        request = json.loads(payload)
    except ValueError:
        request = {}
    request_id = request.get("request_id", "")
    out = sys.stdout.buffer
    if fault == "exit_kill":
        os._exit(137)
    if fault == "abort":
        os.abort()
    if fault == "access_violation":
        ctypes.string_at(0)
    if fault == "hang":
        time.sleep(3600)
    if fault == "hang_with_child":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"])
        Path(os.environ["CGAL_ROBUST_PIDFILE"]).write_text(str(child.pid))
        time.sleep(3600)
    if fault == "hang_partial_output":
        out.write(b'{"protocol":1,"request_id":"' + request_id.encode() + b'","status":"o')
        out.flush()
        time.sleep(3600)
    if fault == "empty_stdout":
        sys.exit(0)
    if fault == "garbage_stdout":
        out.write(b"\xff\xfe\x00 not json at all\n")
        out.flush()
        sys.exit(0)
    if fault == "multi_line_stdout":
        out.write(b'{"protocol":1}\n{"protocol":1}\n')
        out.flush()
        sys.exit(0)
    if fault == "oversized_stdout":
        out.write(b"x" * (3 * 1024 * 1024))
        out.flush()
        sys.exit(0)
    if fault == "stderr_flood_exit":
        sys.stderr.buffer.write(b"E" * (5 * 1024 * 1024))
        sys.stderr.buffer.flush()
        sys.exit(1)
    if fault == "wrong_request_id":
        out.write(json.dumps({"protocol": 1, "request_id": "forged", "status": "ok",
                              "outputs": []}).encode() + b"\n")
        out.flush()
        sys.exit(0)
    if fault == "bad_schema":
        out.write(json.dumps({"protocol": 1, "request_id": request_id, "status": "ok",
                              "outputs": "not-a-list"}).encode() + b"\n")
        out.flush()
        sys.exit(0)
    if fault == "output_path_escape":
        out.write(json.dumps({"protocol": 1, "request_id": request_id, "status": "ok",
                              "outputs": [{"slot": "geometry", "type": "TriangleSurfaceMesh",
                                           "format": "off", "unit": "mm",
                                           "path": os.path.abspath(__file__)}]}).encode() + b"\n")
        out.flush()
        sys.exit(0)
    if fault == "error_response_unknown_class":
        out.write(json.dumps({"protocol": 1, "request_id": request_id, "status": "error",
                              "error": {"class": "SOMETHING_NEW", "code": "x",
                                        "message": "injected", "recoverable": False}}).encode() + b"\n")
        out.flush()
        sys.exit(0)
    if fault in {"truncate_output", "garbage_output"}:
        code, stdout, stderr = forward(arguments, payload)
        try:
            response = json.loads(stdout.decode("utf-8").splitlines()[0])
            for item in response.get("outputs", []):
                path = Path(item["path"])
                data = path.read_bytes()
                if fault == "truncate_output":
                    path.write_bytes(data[: max(1, len(data) // 2)])
                else:
                    path.write_bytes(b"\x00\xff" * 64)
        except (ValueError, KeyError, OSError, IndexError):
            pass
        relay(code, stdout, stderr)
    if fault.startswith("native_"):
        # Feed hostile bytes to the REAL native worker through the same pipe.
        hostile = {
            "native_garbage_request": b"\xff\xfe\x00garbage\n",
            "native_truncated_request": payload[: max(1, len(payload) // 2)],
            "native_empty_request": b"",
            "native_wrong_protocol": json.dumps({**request, "protocol": 99}).encode() + b"\n",
            "native_unknown_operation": json.dumps({**request, "operation": "no.such.operation"}).encode() + b"\n",
            "native_missing_input_file": json.dumps({**request, "inputs": [
                {**item, "path": item.get("path", "") + ".missing"} for item in request.get("inputs", [])]
            }).encode() + b"\n",
            "native_bad_output_dir": json.dumps({**request, "output_dir": "Z:\\no\\such\\dir"}).encode() + b"\n",
        }[fault]
        relay(*forward(arguments, hostile))
    sys.stderr.write(f"unknown fault {fault}\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
