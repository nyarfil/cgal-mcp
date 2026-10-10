"""Isolated JSONL worker supervision with explicit resource-limit evidence."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from .errors import InvalidInput, WorkerFailure
from .registry import OperationRegistry
from .resources import DEFAULT_MEMORY_MB
from .util import canonical_json, digest_file, within


MAX_PROTOCOL_BYTES = 2 * 1024 * 1024
WORKER_CLASS_MAP = {
    "INVALID_INPUT": "invalid_input", "PRECONDITION_FAILED": "unmet_precondition",
    "UNMET_PRECONDITION": "unmet_precondition", "UNSUPPORTED_ADAPTER": "unsupported_adapter",
    "CGAL_ASSERTION": "cgal_precondition", "CGAL_EXCEPTION": "cgal_exception",
    "NUMERIC_FAILURE": "numeric_failure", "TIMEOUT": "timeout",
    "WORKER_CRASH": "worker_crash", "RESOURCE_LIMIT": "resource_limit",
    "VALIDATION_FAILED": "validation_failure", "PROTOCOL_ERROR": "worker_protocol",
    "IO_FAILURE": "worker_io",
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
                 *, require_memory_limit: bool = True,
                 max_memory_mb: int = DEFAULT_MEMORY_MB,
                 persistent: "PersistentPolicy | None" = None):
        if type(max_memory_mb) is not int or not 64 <= max_memory_mb <= 1_048_576:
            raise ValueError("Worker memory ceiling is invalid")
        self.persistent = persistent
        self._idle: list[_SessionWorker] = []
        self._busy: set[_SessionWorker] = set()
        self._reapers: set[asyncio.Task[None]] = set()
        self.pool_stats = {"started": 0, "reused": 0, "recycled": {}}
        self.registry = registry
        self.executable = (executable or default_worker_path()).resolve()
        self._manifest: dict[str, Any] | None = None
        self._manifest_stamp: tuple[int, int, str] | None = None
        self.require_memory_limit = require_memory_limit
        self.max_memory_mb = max_memory_mb
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

    def _limits(self, request: dict[str, Any]) -> tuple[int, int]:
        limits = request.get("limits", {})
        wall_ms = int(limits.get("wall_time_ms", 120000))
        memory_mb = int(limits.get("memory_mb", DEFAULT_MEMORY_MB))
        if not 1 <= wall_ms <= 86_400_000 or not 64 <= memory_mb <= self.max_memory_mb:
            raise InvalidInput("worker_limits", "Worker limits are outside allowed bounds")
        return wall_ms, memory_mb

    async def execute(self, request: dict[str, Any], output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.persistent is not None:
            return await self._execute_persistent(request, output_dir)
        operation = request["operation"]
        manifest = await self.manifest(operation)
        wall_ms, memory_mb = self._limits(request)
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
            # Kill-on-close reaps grandchildren that inherited the pipes; otherwise the
            # waits below would block on pipe EOF forever and the timeout would not be enforced.
            process.kill(); _close_windows_job(job_handle); job_handle = None
            await process.wait()
            await asyncio.gather(stdout_task, stderr_task)
            raise WorkerFailure("worker_timeout", f"Worker exceeded {wall_ms} ms", "timeout", True) from exc
        except asyncio.CancelledError:
            process.kill(); _close_windows_job(job_handle); job_handle = None
            await process.wait()
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
        self.check_response(request, response, output_dir)
        return response, {"manifest": manifest, "diagnostics": diagnostics}

    def check_response(self, request: dict[str, Any], response: Any, output_dir: Path) -> None:
        """Shared response contract for one-shot and persistent workers (raises on violation)."""
        operation = request["operation"]
        if not isinstance(response, dict):
            raise WorkerFailure("worker_response_schema", "Worker response is not an object", "worker_protocol", False)
        if response.get("protocol") != 1 or response.get("request_id") != request["request_id"]:
            raise WorkerFailure("worker_response_identity", "Worker response protocol/request_id mismatch", "worker_protocol", False)
        if response.get("status") == "error":
            error = response.get("error", {})
            original_class = str(error.get("class", "WORKER_ERROR"))
            code = str(error.get("code", "worker_error"))
            if original_class.upper() == "RESOURCE_LIMIT" and code == "MEMORY_LIMIT":
                code = "memory_limit"  # same code as the Job Object / OS-status detection path
            failure = WorkerFailure(code, str(error.get("message", "Worker failed")),
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

    # ------------------------------------------------------------------ persistent workers

    async def _spawn_session(self, memory_mb: int, stamp: str) -> "_SessionWorker":
        kwargs: dict[str, Any] = {}
        if os.name != "nt":
            kwargs["preexec_fn"] = _posix_limit(memory_mb)
        try:
            process = await asyncio.create_subprocess_exec(*_command(self.executable, "--serve"),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=MAX_PROTOCOL_BYTES + 2, **kwargs)
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
        worker = _SessionWorker(process, job_handle, memory_mb, stamp)
        self.pool_stats["started"] += 1
        try:
            await worker.ping(SESSION_PING_TIMEOUT_S)
        except _SessionBroken as exc:
            await worker.terminate()
            raise WorkerFailure("worker_session_unsupported",
                                f"Worker did not answer the session health check: {exc}",
                                "worker_protocol", False) from exc
        return worker

    async def _acquire(self, memory_mb: int, stamp: str) -> "_SessionWorker":
        policy = self.persistent
        assert policy is not None
        for worker in [w for w in self._idle if w.stamp != stamp]:
            await self._retire(worker, "executable_changed")
        while True:
            worker = next((w for w in self._idle if w.memory_mb == memory_mb), None)
            if worker is None:
                return await self._spawn_session(memory_mb, stamp)
            self._idle.remove(worker)
            worker.idle_token += 1
            reason = worker.retire_reason(policy)
            if reason is None:
                try:
                    await worker.ping(SESSION_PING_TIMEOUT_S)
                except _SessionBroken:
                    reason = "health_check_failed"
                except BaseException:  # cancelled while checking: never leak the process
                    worker.kill_now()
                    raise
            if reason is None:
                self.pool_stats["reused"] += 1
                return worker
            await self._retire(worker, reason)

    async def _retire(self, worker: "_SessionWorker", reason: str) -> None:
        self._busy.discard(worker)
        if worker in self._idle:
            self._idle.remove(worker)
        recycled = self.pool_stats["recycled"]
        recycled[reason] = recycled.get(reason, 0) + 1
        await worker.terminate()

    def _release(self, worker: "_SessionWorker") -> str | None:
        policy = self.persistent
        assert policy is not None
        self._busy.discard(worker)
        reason = worker.retire_reason(policy)
        if reason is None and len(self._idle) >= policy.max_idle_workers:
            reason = "pool_full"
        if reason is not None:
            return reason
        worker.idle_since = asyncio.get_running_loop().time()
        worker.idle_token += 1
        self._idle.append(worker)
        task = asyncio.create_task(self._reap_when_idle(worker, worker.idle_token))
        self._reapers.add(task)
        task.add_done_callback(self._reapers.discard)
        return None

    async def _reap_when_idle(self, worker: "_SessionWorker", token: int) -> None:
        policy = self.persistent
        assert policy is not None
        await asyncio.sleep(policy.idle_timeout_s)
        if worker in self._idle and worker.idle_token == token:
            await self._retire(worker, "idle_timeout")

    async def shutdown(self) -> None:
        """Terminate every persistent worker (idle or busy) and cancel idle reapers."""
        for task in list(self._reapers):
            task.cancel()
        for worker in list(self._idle) + list(self._busy):
            await self._retire(worker, "shutdown")

    def kill_all_sync(self) -> None:
        """Last-resort synchronous cleanup: kill-on-close Job Objects reap the processes."""
        for task in list(self._reapers):
            task.cancel()
        for worker in list(self._idle) + list(self._busy):
            worker.kill_now()
        self._idle.clear(); self._busy.clear()

    def pool_status(self) -> dict[str, Any]:
        policy = self.persistent
        return {"mode": "persistent" if policy else "one_shot",
                "policy": policy.as_dict() if policy else None,
                "idle_workers": len(self._idle), "busy_workers": len(self._busy),
                "started": self.pool_stats["started"], "reused": self.pool_stats["reused"],
                "recycled": dict(sorted(self.pool_stats["recycled"].items()))}

    async def _execute_persistent(self, request: dict[str, Any],
                                  output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        operation = request["operation"]
        manifest = await self.manifest(operation)
        wall_ms, memory_mb = self._limits(request)
        stamp = manifest["supervisor_executable_sha256"]
        worker = await self._acquire(memory_mb, stamp)
        self._busy.add(worker)
        worker.begin_job()
        try:
            try:
                line = await asyncio.wait_for(worker.roundtrip(canonical_json(request) + b"\n"),
                                              wall_ms / 1000)
            except asyncio.TimeoutError as exc:
                await self._retire(worker, "timeout")
                raise WorkerFailure("worker_timeout", f"Worker exceeded {wall_ms} ms", "timeout", True) from exc
            except _SessionOverflow as exc:
                await self._retire(worker, "protocol_violation")
                raise WorkerFailure("worker_stdout_limit", "Worker stdout exceeded 2 MiB",
                                    "worker_protocol", False) from exc
            except _SessionBroken as exc:
                await self._retire(worker, "crash")
                stderr = worker.stderr_text()
                code = worker.process.returncode
                windows_memory_statuses = {-1073741801, -1073741670, -1073741523,
                                           3221225495, 3221225626, 3221225773}
                memory_evidence = any(marker in stderr.lower() for marker in
                                      ("memoryerror", "bad_alloc", "cannot allocate memory", "not enough memory"))
                limited = (os.name == "nt" and code in windows_memory_statuses) or memory_evidence
                raise WorkerFailure("memory_limit" if limited else "worker_crash",
                                    f"Worker exited {code}: {stderr[:4096]}",
                                    "resource_limit" if limited else "worker_crash", True) from exc
            diagnostics = {"returncode": None, "stderr": worker.stderr_text(),
                           "stderr_truncated": worker.stderr_truncated,
                           "resource_limit_mode": self.resource_limit_mode,
                           "worker_mode": "persistent", "worker_pid": worker.process.pid,
                           "worker_job_index": worker.jobs}
            try:
                response = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                await self._retire(worker, "protocol_violation")
                raise WorkerFailure("worker_response_malformed", str(exc), "worker_protocol", False) from exc
            if not isinstance(response, dict) or response.get("status") == "error":
                # An error response may leave native state untrusted: never reuse that process.
                await self._retire(worker, "error_response")
            try:
                self.check_response(request, response, output_dir)
            except WorkerFailure:
                if worker in self._busy:
                    await self._retire(worker, "protocol_violation")
                raise
            # Post-job health check: trailing output or a dead process fails the job, as a
            # one-shot worker writing extra lines would.
            try:
                await worker.ping(SESSION_PING_TIMEOUT_S)
            except _SessionBroken as exc:
                await self._retire(worker, "post_job_health_check_failed")
                raise WorkerFailure("worker_response_malformed",
                                    f"Worker failed its post-job health check: {exc}",
                                    "worker_protocol", False) from exc
            worker.private_bytes = _private_bytes(worker.process.pid)
            reason = self._release(worker)
            if reason is not None:
                await self._retire(worker, reason)
            return response, {"manifest": manifest, "diagnostics": diagnostics}
        except asyncio.CancelledError:
            await self._retire(worker, "cancelled")
            raise
        finally:
            if worker in self._busy:  # any unexpected exception: never reuse the process
                await self._retire(worker, "unexpected")


SESSION_PING_TIMEOUT_S = 10.0


class _SessionBroken(Exception):
    pass


class _SessionOverflow(_SessionBroken):
    pass


class PersistentPolicy:
    """Bounded reuse of `--serve` worker processes (session protocol 1)."""

    def __init__(self, *, max_jobs_per_worker: int = 64, max_lifetime_s: float = 600.0,
                 idle_timeout_s: float = 30.0, max_idle_workers: int = 2,
                 recycle_private_fraction: float = 0.25):
        if not (1 <= max_jobs_per_worker <= 100_000 and 0 < max_lifetime_s <= 86_400
                and 0 < idle_timeout_s <= 3_600 and 1 <= max_idle_workers <= 64
                and 0 < recycle_private_fraction <= 1):
            raise ValueError("Persistent worker policy is invalid")
        self.max_jobs_per_worker = max_jobs_per_worker
        self.max_lifetime_s = max_lifetime_s
        self.idle_timeout_s = idle_timeout_s
        self.max_idle_workers = max_idle_workers
        self.recycle_private_fraction = recycle_private_fraction

    def as_dict(self) -> dict[str, Any]:
        return {"session_protocol": 1, "max_jobs_per_worker": self.max_jobs_per_worker,
                "max_lifetime_s": self.max_lifetime_s, "idle_timeout_s": self.idle_timeout_s,
                "max_idle_workers": self.max_idle_workers,
                "recycle_private_fraction": self.recycle_private_fraction}

    @classmethod
    def from_environment(cls, concurrency: int) -> "PersistentPolicy | None":
        raw = os.environ.get("CGAL_MASTER_PERSISTENT_WORKERS", "0").strip()
        if raw not in {"0", "1"}:
            raise ValueError("CGAL_MASTER_PERSISTENT_WORKERS must be 0 or 1")
        return cls(max_idle_workers=concurrency) if raw == "1" else None


def _private_bytes(pid: int) -> int | None:
    """Current private (committed) bytes of a process; None when unavailable."""
    if os.name != "nt":
        try:
            with open(f"/proc/{pid}/status", encoding="ascii") as handle:
                for row in handle:
                    if row.startswith("VmRSS:"):
                        return int(row.split()[1]) * 1024
        except (OSError, ValueError):
            return None
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    class COUNTERS(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]
    kernel32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(COUNTERS), ctypes.c_uint32]
    kernel32.K32GetProcessMemoryInfo.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x1000 | 0x0010, False, pid)
    if not handle:
        return None
    try:
        counters = COUNTERS(); counters.cb = ctypes.sizeof(COUNTERS)
        if not kernel32.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return int(counters.PrivateUsage)
    finally:
        kernel32.CloseHandle(handle)


class _SessionWorker:
    def __init__(self, process: asyncio.subprocess.Process, job_handle: int | None,
                 memory_mb: int, stamp: str):
        self.process = process
        self.job_handle = job_handle
        self.memory_mb = memory_mb
        self.stamp = stamp
        self.started = asyncio.get_running_loop().time()
        self.idle_since = self.started
        self.idle_token = 0
        self.jobs = 0
        self.private_bytes: int | None = None
        self._stderr = bytearray()
        self.stderr_truncated = False
        assert process.stderr is not None
        self._stderr_task = asyncio.create_task(self._drain_stderr(process.stderr))

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                return
            room = MAX_PROTOCOL_BYTES - len(self._stderr)
            if room > 0:
                self._stderr += chunk[:room]
            if len(chunk) > max(room, 0):
                self.stderr_truncated = True

    def begin_job(self) -> None:
        self.jobs += 1
        self._stderr.clear()
        self.stderr_truncated = False

    def stderr_text(self) -> str:
        return bytes(self._stderr).decode("utf-8", "replace")

    def retire_reason(self, policy: PersistentPolicy) -> str | None:
        if self.process.returncode is not None:
            return "exited"
        if self.jobs >= policy.max_jobs_per_worker:
            return "job_count"
        if asyncio.get_running_loop().time() - self.started >= policy.max_lifetime_s:
            return "lifetime"
        if (self.private_bytes is None or
                self.private_bytes > policy.recycle_private_fraction * self.memory_mb * 1024 * 1024):
            return "memory_residue"
        return None

    async def _readline(self) -> bytes:
        assert self.process.stdout is not None
        try:
            line = await self.process.stdout.readuntil(b"\n")
        except asyncio.LimitOverrunError as exc:
            raise _SessionOverflow("response exceeds the protocol bound") from exc
        except asyncio.IncompleteReadError as exc:
            raise _SessionBroken("worker closed its output") from exc
        if len(line) > MAX_PROTOCOL_BYTES:
            raise _SessionOverflow("response exceeds the protocol bound")
        return line

    async def roundtrip(self, payload: bytes) -> bytes:
        if self.process.returncode is not None or self.process.stdin is None:
            raise _SessionBroken("worker is not running")
        try:
            self.process.stdin.write(payload)
            await self.process.stdin.drain()
        except (ConnectionError, OSError) as exc:
            raise _SessionBroken(f"worker input closed: {exc}") from exc
        return await self._readline()

    async def ping(self, timeout_s: float) -> None:
        nonce = "ping-" + uuid.uuid4().hex
        try:
            line = await asyncio.wait_for(
                self.roundtrip(canonical_json({"control": "ping", "request_id": nonce}) + b"\n"), timeout_s)
            reply = json.loads(line.decode("utf-8"))
        except asyncio.TimeoutError as exc:
            raise _SessionBroken("health check timed out") from exc
        except (UnicodeDecodeError, ValueError) as exc:
            raise _SessionBroken("health check reply is malformed") from exc
        if (not isinstance(reply, dict) or reply.get("status") != "pong" or reply.get("request_id") != nonce
                or reply.get("protocol") != 1 or reply.get("session_protocol") != 1):
            raise _SessionBroken("health check reply does not match")

    def kill_now(self) -> None:
        if self.process.returncode is None:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass
        _close_windows_job(self.job_handle); self.job_handle = None

    async def terminate(self) -> None:
        # Close the kill-on-close Job first so grandchildren holding the pipes die too.
        self.kill_now()
        try:
            await asyncio.wait_for(self.process.wait(), 30)
        except asyncio.TimeoutError:
            pass
        try:
            await asyncio.wait_for(self._stderr_task, 5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._stderr_task.cancel()
