"""Experimental execution of caller-supplied CGAL C++ (opt-in, results are UNVERIFIED).

Registered operations run a compiled, reviewed handler and publish geometry only after a
mandatory validator passed. This module is the explicit exception the project owner approved:
a caller hands in one C++ translation unit, the server compiles it against the pinned CGAL
headers and runs it in a separate process with resource limits. Nothing checks the result.

What the isolation is, and is not:

- It is a separate process in its own working directory with a wall-clock limit, an address
  space limit, a file size limit, a scrubbed environment and no inherited stdin. On POSIX the
  process leads its own session, which is killed as a whole on timeout and after exit, and on
  Linux it dies with the server. On Windows it runs in a kill-on-close Job with a memory limit.
- It is NOT a security sandbox. The program runs with the rights of the server's user and can
  read and write whatever that user can, and it can use the network. Enable it only on a
  machine and for callers you trust.

Every artifact created here carries ``producer.kind == "experimental_unverified"`` and is
reported with ``verification: "unverified"``. The mode is off unless
``CGAL_MASTER_EXPERIMENTAL=1`` is set and a compile command is available.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .errors import InvalidInput, MasterError
from .supervisor import _assign_windows_job, _close_windows_job, _kill_posix_group, _posix_limit

PRODUCER_KIND = "experimental_unverified"
MAX_SOURCE_BYTES = 256 * 1024
MAX_INPUTS = 8
MAX_OUTPUTS = 8
MAX_LOG_BYTES = 64 * 1024
MAX_OUTPUT_FILE_BYTES = 512 * 1024 * 1024
DEFAULT_COMPILE_SECONDS = 600
NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,31}")
OUTPUT_RE = re.compile(r"[a-z][a-z0-9_]{0,31}\.(off|xyz|ply|json)")
WARNING = ("UNVERIFIED: produced by caller-supplied C++ in experimental mode. No registered handler and "
           "no validator checked this result; treat every number and every mesh as unchecked.")


def _tail(data: bytes) -> str:
    text = data[-MAX_LOG_BYTES:].decode("utf-8", "replace")
    return text


class ExperimentalRunner:
    """Compile and run one C++ translation unit; import its declared outputs as unverified artifacts."""

    def __init__(self, store: Any, *, compile_command: list[str], max_memory_mb: int,
                 max_wall_time_ms: int, compile_seconds: int = DEFAULT_COMPILE_SECONDS):
        if (not compile_command or not all(isinstance(item, str) and item for item in compile_command)
                or not any("{source}" in item for item in compile_command)
                or not any("{output}" in item for item in compile_command)):
            raise ValueError("Experimental compile command must be a list containing {source} and {output}")
        self.store = store
        self.compile_command = list(compile_command)
        self.max_memory_mb = max_memory_mb
        self.max_wall_time_ms = max_wall_time_ms
        self.compile_seconds = compile_seconds

    # ------------------------------------------------------------------ configuration

    @staticmethod
    def default_compile_command() -> list[str] | None:
        """g++/clang++ command built from CGAL_MASTER_EXPERIMENTAL_INCLUDE (POSIX only)."""
        if os.name == "nt":
            return None
        compiler = os.environ.get("CGAL_MASTER_EXPERIMENTAL_CXX") or shutil.which("g++") or shutil.which("clang++")
        includes = [item for item in os.environ.get("CGAL_MASTER_EXPERIMENTAL_INCLUDE", "").split(os.pathsep) if item]
        if not compiler or not includes:
            return None
        command = [compiler, "-std=c++17", "-O2", "-frounding-math"]
        command += [f"-I{item}" for item in includes]
        if any((Path(item) / "Eigen" / "Core").is_file() for item in includes):
            command.append("-DCGAL_EIGEN3_ENABLED")  # many CGAL packages need Eigen for their solvers
        command += ["{source}", "-o", "{output}", "-lgmp", "-lmpfr"]
        return command

    @classmethod
    def from_environment(cls, store: Any, *, max_memory_mb: int, max_wall_time_ms: int) -> "ExperimentalRunner | None":
        raw = os.environ.get("CGAL_MASTER_EXPERIMENTAL", "0").strip()
        if raw not in {"0", "1"}:
            raise ValueError("CGAL_MASTER_EXPERIMENTAL must be 0 or 1")
        if raw != "1":
            return None
        configured = os.environ.get("CGAL_MASTER_EXPERIMENTAL_COMPILE")
        if configured:
            try:
                command = json.loads(configured)
            except ValueError as exc:
                raise ValueError("CGAL_MASTER_EXPERIMENTAL_COMPILE must be a JSON array of strings") from exc
        else:
            command = cls.default_compile_command()
        if not command:
            raise ValueError("CGAL_MASTER_EXPERIMENTAL=1 needs CGAL_MASTER_EXPERIMENTAL_COMPILE (JSON array with "
                             "{source} and {output}) or, on POSIX, CGAL_MASTER_EXPERIMENTAL_INCLUDE")
        return cls(store, compile_command=command, max_memory_mb=max_memory_mb,
                   max_wall_time_ms=max_wall_time_ms)

    def describe(self) -> dict[str, Any]:
        return {"enabled": True, "compiler": self.compile_command[0], "result_verification": "none",
                "isolation": "separate process, wall-clock/memory/file-size limits, scrubbed environment; "
                             "not a security sandbox",
                "limits": {"source_bytes": MAX_SOURCE_BYTES, "inputs": MAX_INPUTS, "outputs": MAX_OUTPUTS,
                           "memory_mb": self.max_memory_mb, "wall_time_ms": self.max_wall_time_ms,
                           "compile_seconds": self.compile_seconds}}

    # ------------------------------------------------------------------ request checks

    def _check(self, source: Any, inputs: Any, outputs: Any, wall_time_ms: Any, memory_mb: Any) -> tuple[int, int]:
        if not isinstance(source, str) or not source.strip():
            raise InvalidInput("experimental_source", "source must be the text of one C++ translation unit")
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise InvalidInput("experimental_source", f"source exceeds {MAX_SOURCE_BYTES} bytes")
        if "\x00" in source:
            raise InvalidInput("experimental_source", "source contains a NUL character")
        if (not isinstance(inputs, dict) or len(inputs) > MAX_INPUTS
                or not all(isinstance(k, str) and NAME_RE.fullmatch(k) and isinstance(v, str) for k, v in inputs.items())):
            raise InvalidInput("experimental_inputs", "inputs must map up to 8 lower-case names to artifact ids")
        if (not isinstance(outputs, list) or not 1 <= len(outputs) <= MAX_OUTPUTS
                or not all(isinstance(item, dict) and set(item) == {"file", "artifact_type", "unit"}
                           and isinstance(item["file"], str) and OUTPUT_RE.fullmatch(item["file"])
                           and isinstance(item["artifact_type"], str) and isinstance(item["unit"], str)
                           for item in outputs)
                or len({item["file"] for item in outputs}) != len(outputs)):
            raise InvalidInput("experimental_outputs",
                               "outputs must list 1 to 8 distinct {file, artifact_type, unit}; file is "
                               "lower-case with extension off, xyz, ply or json")
        wall = self.max_wall_time_ms if wall_time_ms is None else wall_time_ms
        memory = self.max_memory_mb if memory_mb is None else memory_mb
        if (type(wall) is not int or type(memory) is not int or not 1000 <= wall <= self.max_wall_time_ms
                or not 64 <= memory <= self.max_memory_mb):
            raise InvalidInput("experimental_limits", "wall_time_ms or memory_mb is outside the configured limits")
        return wall, memory

    # ------------------------------------------------------------------ execution

    def run(self, source: str, inputs: dict[str, str] | None, outputs: list[dict[str, str]],
            *, wall_time_ms: int | None = None, memory_mb: int | None = None,
            note: str | None = None) -> dict[str, Any]:
        inputs = {} if inputs is None else inputs
        wall, memory = self._check(source, inputs, outputs, wall_time_ms, memory_mb)
        if note is not None and (not isinstance(note, str) or len(note) > 500):
            raise InvalidInput("experimental_note", "note must be a string of at most 500 characters")
        source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        base: dict[str, Any] = {"verification": "unverified", "warning": WARNING, "source_sha256": source_sha256,
                                "outputs": [], "limits": {"wall_time_ms": wall, "memory_mb": memory}}
        # Resolve the inputs first: an unknown artifact is refused before anything is compiled.
        resolved = {name: self.store.inspect(artifact_id) for name, artifact_id in inputs.items()}
        root = Path(tempfile.mkdtemp(prefix="experimental-", dir=self.store.staging_root))
        try:
            source_path = root / "main.cpp"
            source_path.write_text(source, encoding="utf-8", newline="\n")
            input_dir, output_dir = root / "in", root / "out"
            input_dir.mkdir()
            output_dir.mkdir()
            input_paths = {}
            for name, inspection in resolved.items():
                target = input_dir / f"{name}.{inspection['format']}"
                shutil.copyfile(self.store.managed_path(inspection["artifact_id"]), target)
                input_paths[name] = str(target)
            binary = root / ("program.exe" if os.name == "nt" else "program")
            command = [item.replace("{source}", str(source_path)).replace("{output}", str(binary))
                       for item in self.compile_command]
            began = time.perf_counter()
            try:
                compiled = subprocess.run(command, cwd=root, stdin=subprocess.DEVNULL, capture_output=True,
                                          timeout=self.compile_seconds)
            except subprocess.TimeoutExpired:
                return {**base, "status": "compile_timeout", "compile_seconds": self.compile_seconds}
            except OSError as exc:
                raise MasterError("experimental_compiler", f"The experimental compiler cannot be started: {exc}",
                                  "unsupported_adapter") from exc
            base["compile_seconds"] = round(time.perf_counter() - began, 3)
            if compiled.returncode != 0 or not binary.is_file():
                return {**base, "status": "compile_failed", "compiler_exit_code": compiled.returncode,
                        "compiler_output": _tail(compiled.stderr + compiled.stdout)}
            status, detail = self._execute(binary, root, input_dir, output_dir, wall, memory)
            base.update(detail)
            if status != "completed":
                return {**base, "status": status}
            producer = {"kind": PRODUCER_KIND, "verified": False, "source_sha256": source_sha256,
                        "inputs": {name: item["sha256"] for name, item in resolved.items()},
                        "note": note or ""}
            imported, problems = [], []
            for item in outputs:
                path = output_dir / item["file"]
                if not path.is_file() or path.is_symlink():
                    problems.append({"file": item["file"], "problem": "not written by the program"})
                    continue
                if path.stat().st_size > MAX_OUTPUT_FILE_BYTES:
                    problems.append({"file": item["file"], "problem": "larger than the output limit"})
                    continue
                try:
                    artifact = self.store.import_file(path, item["unit"], artifact_type=item["artifact_type"],
                                                      producer={**producer, "file": item["file"]})
                except InvalidInput as exc:
                    problems.append({"file": item["file"], "problem": f"{exc.code}: {exc}"})
                    continue
                imported.append({"file": item["file"], "artifact_id": artifact["artifact_id"],
                                 "type": artifact["type"], "unit": artifact["unit"], "sha256": artifact["sha256"],
                                 "verification": "unverified"})
            return {**base, "status": "completed" if not problems else "completed_with_missing_outputs",
                    "outputs": imported, "output_problems": problems, "input_files": sorted(input_paths)}
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def _execute(self, binary: Path, root: Path, input_dir: Path, output_dir: Path,
                 wall_ms: int, memory_mb: int) -> tuple[str, dict[str, Any]]:
        environment = {"CGAL_IN": str(input_dir), "CGAL_OUT": str(output_dir), "LC_ALL": "C"}
        for key in ("SystemRoot", "PATH", "TEMP", "TMP"):  # needed to start a process on Windows
            if os.name == "nt" and key in os.environ:
                environment[key] = os.environ[key]
        kwargs: dict[str, Any] = {}
        if os.name != "nt":
            limit = _posix_limit(memory_mb)

            def setup() -> None:
                import resource
                limit()
                resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_FILE_BYTES, MAX_OUTPUT_FILE_BYTES))
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            kwargs.update(preexec_fn=setup, start_new_session=True)
        began = time.perf_counter()
        process = subprocess.Popen([str(binary)], cwd=root, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        job_handle = None
        if os.name == "nt":
            job_handle, mode = _assign_windows_job(process.pid, memory_mb)
            if job_handle is None:
                process.kill()
                process.wait()
                raise MasterError("experimental_memory_limit",
                                  f"The memory limit could not be applied to the experimental process: {mode}",
                                  "resource_limit")
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=wall_ms / 1000)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_posix_group(process.pid)
            process.kill()
            _close_windows_job(job_handle)
            job_handle = None
            stdout, stderr = process.communicate()
        finally:
            _close_windows_job(job_handle)
            _kill_posix_group(process.pid)
        detail = {"run_seconds": round(time.perf_counter() - began, 3), "exit_code": process.returncode,
                  "stdout": _tail(stdout), "stderr": _tail(stderr)}
        if timed_out:
            return "run_timeout", detail
        if process.returncode != 0:
            return "run_failed", detail
        return "completed", detail


def verification_of(inspection: dict[str, Any]) -> str:
    """How an artifact came to exist, as far as checking is concerned."""
    kind = inspection.get("producer", {}).get("kind")
    if kind == PRODUCER_KIND:
        return "unverified"
    if kind == "file_import":
        return "imported_not_checked"
    return "validated_operation_output"


__all__ = ["ExperimentalRunner", "PRODUCER_KIND", "WARNING", "verification_of"]
