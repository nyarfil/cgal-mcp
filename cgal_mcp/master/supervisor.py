"""Isolated JSONL worker supervision with explicit resource-limit evidence."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import sys
from pathlib import Path
from typing import Any

from .errors import InvalidInput, WorkerFailure
from .registry import OperationRegistry
from .util import canonical_json, digest_file, within


MAX_PROTOCOL_BYTES = 2 * 1024 * 1024
DEFAULT_MEMORY_MB = 4096

WORKER_CLASS_MAP = {
    "INVALID_INPUT": "invalid_input", "PRECONDITION_FAILED": "unmet_precondition",
    "UNMET_PRECONDITION": "unmet_precondition", "UNSUPPORTED_ADAPTER": "unsupported_adapter",
    "CGAL_ASSERTION": "cgal_precondition", "CGAL_EXCEPTION": "cgal_exception",
    "NUMERIC_FAILURE": "numeric_failure", "TIMEOUT": "timeout",
    "WORKER_CRASH": "worker_crash", "RESOURCE_LIMIT": "resource_limit",
    "VALIDATION_FAILED": "validation_failure", "PROTOCOL_ERROR": "worker_protocol",
}


def default_worker_path() -> Path:
    configured = os.environ.get("CGAL_MASTER_WORKER")
    if configured:
        return Path(configured)
    if os.name == "nt":
        return Path("build-master/Release/cgal-master-worker.exe")
    return Path("build-master/cgal-master-worker")


def _command(executable: Path, *arguments: str) -> list[str]:
    if executable.suffix.lower() == ".py":
        return [sys.executable, str(executable), *arguments]
    return [str(executable), *arguments]


def _posix_limit(memory_mb: int):
    def apply() -> None:
        import resource
        maximum = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (maximum, maximum))
    return apply


def _assign_windows_job(pid: int, memory_mb: int) -> tuple[int | None, str]:
    """Assign kill-on-close + process memory limit; return an owned Job handle."""
    if os.name != "nt":
        return None, "posix_rlimit_as"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                  ctypes.c_void_p, ctypes.c_uint32]
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None, f"unsupported:CreateJobObjectW:{ctypes.get_last_error()}"
    # AssignProcessToJobObject requires PROCESS_SET_QUOTA and PROCESS_TERMINATE.
    process = kernel32.OpenProcess(0x0100 | 0x0001 | 0x0400, False, pid)
    if not process:
        kernel32.CloseHandle(job)
        return None, f"unsupported:OpenProcess:{ctypes.get_last_error()}"
    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", ctypes.c_uint32),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_uint32),
                    ("SchedulingClass", ctypes.c_uint32)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                     "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = 0x00002000 | 0x00000100  # kill-on-close, process-memory
    info.ProcessMemoryLimit = memory_mb * 1024 * 1024
    ok = kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    assigned = ok and kernel32.AssignProcessToJobObject(job, process)
    kernel32.CloseHandle(process)
    if not assigned:
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        return None, f"unsupported:AssignProcessToJobObject:{error}"
    return int(job), "windows_job_object"


def _close_windows_job(handle: int | None) -> None:
    if handle and os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.CloseHandle(handle)


async def _read_bounded(stream: asyncio.StreamReader, maximum: int) -> tuple[bytes, bool]:
    parts: list[bytes] = []
    seen = 0
    exceeded = False
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        if seen < maximum:
            remaining = maximum - seen
            parts.append(chunk[:remaining])
        seen += len(chunk)
        exceeded = seen > maximum
    return b"".join(parts), exceeded


class WorkerSupervisor:
    def __init__(self, registry: OperationRegistry, executable: Path | None = None,
                 *, require_memory_limit: bool = True):
        self.registry = registry
        self.executable = (executable or default_worker_path()).resolve()
        self._manifest: dict[str, Any] | None = None
        self._manifest_stamp: tuple[int, int, str] | None = None
        self.require_memory_limit = require_memory_limit
        self.resource_limit_mode = "posix_rlimit_as" if os.name != "nt" else "windows_job_object_pending"

    async def manifest(self, required_operation: str) -> dict[str, Any]:
        if not self.executable.is_file():
            raise WorkerFailure("worker_missing", f"Worker executable not found: {self.executable}",
                                "unsupported_adapter", False)
        stat = self.executable.stat()
        stamp = (stat.st_mtime_ns, stat.st_size, digest_file(self.executable))
        if self._manifest is None or stamp != self._manifest_stamp:
            try:
                process = await asyncio.create_subprocess_exec(*_command(self.executable, "--manifest"),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                assert process.stdout and process.stderr
                stdout_task = asyncio.create_task(_read_bounded(process.stdout, MAX_PROTOCOL_BYTES))
                stderr_task = asyncio.create_task(_read_bounded(process.stderr, MAX_PROTOCOL_BYTES))
                await asyncio.wait_for(process.wait(), 15)
                (stdout, stdout_exceeded), (stderr, stderr_exceeded) = await asyncio.gather(stdout_task, stderr_task)
            except asyncio.TimeoutError as exc:
                process.kill(); await process.wait()
                if 'stdout_task' in locals():
                    await asyncio.gather(stdout_task, stderr_task)
                raise WorkerFailure("manifest_timeout", "Worker --manifest timed out", "timeout", True) from exc
            except asyncio.CancelledError:
                if 'process' in locals() and process.returncode is None:
                    process.kill(); await process.wait()
                if 'stdout_task' in locals():
                    await asyncio.gather(stdout_task, stderr_task)
                raise
            except OSError as exc:
                raise WorkerFailure("manifest_start", str(exc), "worker_crash", True) from exc
            if process.returncode != 0 or stdout_exceeded:
                raise WorkerFailure("manifest_failed", stderr[:4096].decode("utf-8", "replace"), "worker_crash", True)
            try:
                lines = stdout.decode("utf-8").splitlines()
                if len(lines) != 1:
                    raise ValueError("manifest stdout must contain exactly one JSON line")
                self._manifest = json.loads(lines[0])
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise WorkerFailure("manifest_malformed", str(exc), "worker_protocol", False) from exc
            self._manifest_stamp = stamp
        verified = self.registry.verify_manifest(self._manifest, required_operation)
        verified["supervisor_executable_sha256"] = stamp[2]
        return verified

    async def execute(self, request: dict[str, Any], output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        operation = request["operation"]
        manifest = await self.manifest(operation)
        limits = request.get("limits", {})
        wall_ms = int(limits.get("wall_time_ms", 120000))
        memory_mb = int(limits.get("memory_mb", DEFAULT_MEMORY_MB))
        if not 1 <= wall_ms <= 86_400_000 or not 64 <= memory_mb <= DEFAULT_MEMORY_MB:
            raise InvalidInput("worker_limits", "Worker limits are outside allowed bounds")
        kwargs: dict[str, Any] = {}
        if os.name != "nt":
            kwargs["preexec_fn"] = _posix_limit(memory_mb)
        try:
            process = await asyncio.create_subprocess_exec(*_command(self.executable),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, **kwargs)
        except OSError as exc:
            raise WorkerFailure("worker_start", str(exc), "worker_crash", True) from exc
        job_handle: int | None = None
        if os.name == "nt":
            job_handle, mode = _assign_windows_job(process.pid, memory_mb)
            self.resource_limit_mode = mode
            if job_handle is None:
                if self.require_memory_limit:
                    process.kill(); await process.wait()
                    raise WorkerFailure("memory_limit_unavailable", mode, "resource_limit", True)
                self.resource_limit_mode = "unsupported_unenforced_test_mode:" + mode
        assert process.stdin and process.stdout and process.stderr
        stdout_task = asyncio.create_task(_read_bounded(process.stdout, MAX_PROTOCOL_BYTES))
        stderr_task = asyncio.create_task(_read_bounded(process.stderr, MAX_PROTOCOL_BYTES))
        process.stdin.write(canonical_json(request) + b"\n")
        await process.stdin.drain(); process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), wall_ms / 1000)
        except asyncio.TimeoutError as exc:
            process.kill(); await process.wait()
            await asyncio.gather(stdout_task, stderr_task)
            raise WorkerFailure("worker_timeout", f"Worker exceeded {wall_ms} ms", "timeout", True) from exc
        except asyncio.CancelledError:
            process.kill(); await process.wait()
            await asyncio.gather(stdout_task, stderr_task)
            raise
        finally:
            _close_windows_job(job_handle)
        (stdout, stdout_exceeded), (stderr, stderr_exceeded) = await asyncio.gather(stdout_task, stderr_task)
        diagnostics = {"returncode": process.returncode,
                       "stderr": stderr.decode("utf-8", "replace"),
                       "stderr_truncated": stderr_exceeded,
                       "resource_limit_mode": self.resource_limit_mode}
        if stdout_exceeded:
            raise WorkerFailure("worker_stdout_limit", "Worker stdout exceeded 2 MiB", "worker_protocol", False)
        if process.returncode != 0:
            windows_memory_statuses = {-1073741801, -1073741670, -1073741523}
            stderr_lower = diagnostics["stderr"].lower()
            memory_evidence = any(marker in stderr_lower for marker in
                                  ("memoryerror", "bad_alloc", "cannot allocate memory", "not enough memory"))
            resource_limited = ((os.name == "nt" and process.returncode in windows_memory_statuses)
                                or memory_evidence)
            raise WorkerFailure("memory_limit" if resource_limited else "worker_crash",
                                f"Worker exited {process.returncode}: {diagnostics['stderr'][:4096]}",
                                "resource_limit" if resource_limited else "worker_crash", True)
        try:
            lines = stdout.decode("utf-8").splitlines()
            if len(lines) != 1:
                raise ValueError("worker stdout must contain exactly one JSON line")
            response = json.loads(lines[0])
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise WorkerFailure("worker_response_malformed", str(exc), "worker_protocol", False) from exc
        if response.get("protocol") != 1 or response.get("request_id") != request["request_id"]:
            raise WorkerFailure("worker_response_identity", "Worker response protocol/request_id mismatch", "worker_protocol", False)
        if response.get("status") == "error":
            error = response.get("error", {})
            original_class = str(error.get("class", "WORKER_ERROR"))
            failure = WorkerFailure(str(error.get("code", "worker_error")), str(error.get("message", "Worker failed")),
                                    WORKER_CLASS_MAP.get(original_class.upper(), "worker_error"),
                                    bool(error.get("recoverable", False)),
                                    tuple(error.get("suggested_operations", [])))
            failure.source_class = original_class
            raise failure
        if response.get("status") != "ok" or not isinstance(response.get("outputs"), list):
            raise WorkerFailure("worker_response_schema", "Worker response status/outputs are invalid", "worker_protocol", False)
        operation_definition = self.registry.get(operation)
        expected = operation_definition["io"]["outputs"]
        input_by_slot = {spec["slot"]: item for spec, item in
                         zip(operation_definition["io"]["inputs"], request["inputs"])}
        expected_slots = {item["slot"]: item for item in expected}
        actual_slots: set[str] = set()
        for item in response["outputs"]:
            if not isinstance(item, dict) or item.get("slot") not in expected_slots:
                raise WorkerFailure("worker_output_slot", "Worker returned an unknown output slot", "worker_protocol", False)
            specification = expected_slots[item["slot"]]
            if item.get("slot") in actual_slots or item.get("type") != specification["type"] or item.get("format") != specification["format"]:
                raise WorkerFailure("worker_output_schema", "Worker output disagrees with registry", "worker_protocol", False)
            expected_unit = (specification.get("unit") if specification.get("unit") is not None
                             else input_by_slot[specification["unit_from"]]["unit"])
            if item.get("unit") != expected_unit:
                raise WorkerFailure("worker_output_unit", "Worker output unit disagrees with registry", "worker_protocol", False)
            path = Path(str(item.get("path", ""))).resolve(strict=False)
            if not within(path, output_dir) or not path.is_file():
                raise WorkerFailure("worker_output_path", "Worker output path is missing or outside staging", "worker_protocol", False)
            actual_slots.add(item["slot"])
        if actual_slots != set(expected_slots):
            raise WorkerFailure("worker_output_missing", "Worker omitted required outputs", "worker_protocol", False)
        return response, {"manifest": manifest, "diagnostics": diagnostics}
