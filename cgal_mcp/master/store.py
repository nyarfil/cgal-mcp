"""Immutable blob/artifact storage and persistent Master metadata."""

from __future__ import annotations

import json
import os
import subprocess
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .errors import InvalidInput, WorkerFailure
from .formats import Inspection, format_from_path
from .supervisor import _assign_windows_job, _close_windows_job, _posix_limit
from .util import canonical_json, copy_hash_bounded, digest_file, valid_artifact_unit, within


MAX_IMPORT_BYTES = 512 * 1024 * 1024
MAX_ANALYSIS_REPORT_BYTES = 16 * 1024 * 1024
INSPECTION_MEMORY_MB = 1024
MAX_INSPECTION_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_INSPECTION_STDERR_BYTES = 64 * 1024


def _drain_bounded(stream: Any, maximum: int, destination: list[Any],
                   overflow: threading.Event | None = None) -> None:
    chunks: list[bytes] = []
    seen = 0
    while chunk := stream.read(65536):
        if seen < maximum:
            chunks.append(chunk[:maximum - seen])
        seen += len(chunk)
        if seen > maximum and overflow is not None:
            overflow.set()
    destination.extend((b"".join(chunks), seen > maximum))


def _inspect_file_isolated(path: Path, format_name: str,
                           artifact_type: str | None) -> Inspection:
    """Parse untrusted geometry outside the long-lived MCP process."""
    kwargs: dict[str, Any] = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                              "stderr": subprocess.PIPE}
    if os.name != "nt":
        kwargs["preexec_fn"] = _posix_limit(INSPECTION_MEMORY_MB)
    process = subprocess.Popen(
        [sys.executable, "-m", "cgal_mcp.master.format_worker"], **kwargs)
    job_handle: int | None = None
    try:
        if os.name == "nt":
            job_handle, mode = _assign_windows_job(process.pid, INSPECTION_MEMORY_MB)
            if job_handle is None:
                process.kill(); process.wait()
                raise WorkerFailure("inspection_memory_limit_unavailable", mode,
                                    "resource_limit", True)
        maximum_bytes = (MAX_ANALYSIS_REPORT_BYTES if artifact_type == "GeometryAnalysisReport"
                         else MAX_IMPORT_BYTES)
        request = canonical_json({"path": str(path), "format": format_name,
                                  "type": artifact_type,
                                  "maximum_bytes": maximum_bytes}) + b"\n"
        stdout_result: list[Any] = []
        stderr_result: list[Any] = []
        stdout_overflow = threading.Event()
        assert process.stdout and process.stderr and process.stdin
        stdout_thread = threading.Thread(target=_drain_bounded,
            args=(process.stdout, MAX_INSPECTION_RESPONSE_BYTES, stdout_result, stdout_overflow), daemon=True)
        stderr_thread = threading.Thread(target=_drain_bounded,
            args=(process.stderr, MAX_INSPECTION_STDERR_BYTES, stderr_result), daemon=True)
        stdout_thread.start(); stderr_thread.start()
        try:
            process.stdin.write(request); process.stdin.close()
            deadline = time.monotonic() + 120
            while True:
                if stdout_overflow.is_set():
                    process.kill(); process.wait()
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(process.args, 120)
                try:
                    process.wait(timeout=min(0.05, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        except subprocess.TimeoutExpired as exc:
            process.kill(); process.wait()
            raise WorkerFailure("inspection_timeout", "Geometry inspection exceeded 120 seconds",
                                "timeout", True) from exc
        finally:
            stdout_thread.join(); stderr_thread.join()
            process.stdout.close(); process.stderr.close()
    finally:
        _close_windows_job(job_handle)
    stdout, stdout_exceeded = stdout_result
    stderr, _ = stderr_result
    if stdout_exceeded:
        raise WorkerFailure("inspection_protocol_limit", "Geometry inspection response exceeded 2 MiB",
                            "worker_protocol", False)
    if process.returncode != 0:
        message = stderr[:4096].decode("utf-8", "replace")
        raise WorkerFailure("inspection_crash", message or f"Inspector exited {process.returncode}",
                            "resource_limit", True)
    try:
        response = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerFailure("inspection_protocol", "Geometry inspector returned malformed JSON",
                            "worker_protocol", False) from exc
    if response.get("status") == "error":
        error = response.get("error", {})
        if error.get("class") == "invalid_input":
            raise InvalidInput(str(error.get("code", "inspection_failed")),
                               str(error.get("message", "Geometry inspection failed")))
        raise WorkerFailure(str(error.get("code", "inspection_failed")),
                            str(error.get("message", "Geometry inspection failed")),
                            str(error.get("class", "worker_error")),
                            bool(error.get("recoverable", False)))
    try:
        return Inspection(**response["inspection"])
    except (KeyError, TypeError) as exc:
        raise WorkerFailure("inspection_protocol", "Geometry inspector response schema is invalid",
                            "worker_protocol", False) from exc


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.blob_root = self.root / "blobs"
        self.staging_root = self.root / "staging"
        self.quarantine_root = self.root / "quarantine"
        for directory in (self.root, self.blob_root, self.staging_root, self.quarantine_root):
            directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "master.sqlite3"
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._configure()
        self._schema()
        self.recover_interrupted_jobs()
        self.cleanup_orphan_blobs()

    def _configure(self) -> None:
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")

    def _schema(self) -> None:
        self._db.executescript("""
        CREATE TABLE IF NOT EXISTS blobs(
          sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL, relative_path TEXT NOT NULL UNIQUE,
          created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artifacts(
          artifact_id TEXT PRIMARY KEY, blob_sha256 TEXT NOT NULL REFERENCES blobs(sha256),
          geometry_type TEXT NOT NULL, unit TEXT NOT NULL, format TEXT NOT NULL,
          properties_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
          producer_json TEXT NOT NULL, created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plans(
          plan_id TEXT PRIMARY KEY, canonical_json TEXT NOT NULL, created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs(
          job_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id),
          state TEXT NOT NULL, execution_status TEXT NOT NULL, validation_status TEXT NOT NULL,
          detail_json TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provenance(
          id INTEGER PRIMARY KEY AUTOINCREMENT, artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
          job_id TEXT, operation_id TEXT, input_hashes_json TEXT NOT NULL,
          parameters_json TEXT NOT NULL, build_json TEXT NOT NULL, created REAL NOT NULL
        );
        """)
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _blob_path(self, sha256: str) -> Path:
        return self.blob_root / sha256[:2] / sha256[2:]

    def _commit_blob_temp(self, temporary: Path, sha256: str, size: int) -> Path:
        target = self._blob_path(sha256)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            temporary.unlink(missing_ok=True)
            if target.stat().st_size != size:
                raise RuntimeError("Stored blob size disagrees with content hash")
        else:
            os.replace(temporary, target)
        relative = target.relative_to(self.root).as_posix()
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO blobs VALUES(?,?,?,?)",
                             (sha256, size, relative, time.time()))
            self._db.commit()
        return target

    def _insert_artifact(self, sha256: str, size: int, inspection: Any, unit: str,
                         producer: dict[str, Any],
                         provenance: dict[str, Any] | None = None) -> dict[str, Any]:
        if not valid_artifact_unit(inspection.geometry_type, unit):
            raise InvalidInput("artifact_unit", f"Unit {unit!r} is invalid for {inspection.geometry_type}")
        if not all(type(value) is bool or value == "unknown"
                   for value in inspection.properties.values()):
            raise RuntimeError("Artifact properties must be true, false or unknown")
        artifact_id = "art_" + uuid.uuid4().hex
        with self._lock:
            self._db.execute("""
              INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?,?,?,?,?)
            """, (artifact_id, sha256, inspection.geometry_type, unit, inspection.format,
                    json.dumps(inspection.properties, sort_keys=True),
                    json.dumps(inspection.metadata, sort_keys=True),
                    json.dumps(producer, sort_keys=True), time.time()))
            if provenance is not None:
                self._db.execute("INSERT INTO provenance(artifact_id,job_id,operation_id,input_hashes_json,parameters_json,build_json,created) VALUES(?,?,?,?,?,?,?)",
                    (artifact_id, provenance["job_id"], provenance["operation_id"],
                     json.dumps(provenance["input_hashes"]),
                     json.dumps(provenance["parameters"], sort_keys=True),
                     json.dumps(provenance["build"], sort_keys=True), time.time()))
            self._db.commit()
        return self.inspect(artifact_id)

    def import_file(self, source: Path, unit: str, *, format_name: str | None = None,
                    artifact_type: str | None = None,
                    producer: dict[str, Any] | None = None) -> dict[str, Any]:
        source = source.expanduser().resolve(strict=True)
        if not source.is_file():
            raise InvalidInput("import_source", "Import source must be a regular file")
        if not valid_artifact_unit(artifact_type, unit):
            expected = "none" if artifact_type in {"ValidationReport", "GeometryAnalysisReport"} else "mm, cm or m"
            raise InvalidInput("artifact_unit", f"Artifact unit must be {expected}")
        maximum_bytes = (MAX_ANALYSIS_REPORT_BYTES if artifact_type == "GeometryAnalysisReport"
                         else MAX_IMPORT_BYTES)
        selected_format = (format_name or format_from_path(source)).lower().lstrip(".")
        fd, temporary_name = tempfile.mkstemp(prefix="import-", dir=self.staging_root)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with source.open("rb") as input_stream, temporary.open("wb") as output_stream:
                try:
                    sha256, size = copy_hash_bounded(input_stream, output_stream, maximum_bytes)
                except ValueError as exc:
                    raise InvalidInput("import_too_large", str(exc)) from exc
                output_stream.flush(); os.fsync(output_stream.fileno())
            inspection = _inspect_file_isolated(temporary, selected_format, artifact_type)
            self._commit_blob_temp(temporary, sha256, size)
            return self._insert_artifact(sha256, size, inspection, unit,
                                         producer or {"kind": "file_import", "source_name": source.name})
        finally:
            temporary.unlink(missing_ok=True)

    def prepare_worker_output(self, source: Path, unit: str, format_name: str,
                              artifact_type: str, producer: dict[str, Any],
                              provenance: dict[str, Any]) -> dict[str, Any]:
        source = source.resolve(strict=True)
        if not within(source, self.staging_root):
            raise InvalidInput("worker_output_path", "Worker output is outside managed staging")
        maximum_bytes = (MAX_ANALYSIS_REPORT_BYTES if artifact_type == "GeometryAnalysisReport"
                         else MAX_IMPORT_BYTES)
        if source.stat().st_size > maximum_bytes:
            raise InvalidInput("worker_output_too_large", f"Worker output exceeds {maximum_bytes} bytes")
        inspection = _inspect_file_isolated(source, format_name, artifact_type)
        if not valid_artifact_unit(inspection.geometry_type, unit):
            raise InvalidInput("artifact_unit", f"Unit {unit!r} is invalid for {inspection.geometry_type}")
        sha256 = digest_file(source)
        return {"artifact_id": "art_" + uuid.uuid4().hex, "sha256": sha256,
                "size": source.stat().st_size, "type": inspection.geometry_type, "unit": unit,
                "format": inspection.format, "properties": inspection.properties,
                "metadata": inspection.metadata, "producer": producer,
                "provenance": provenance, "immutable": True, "_source_path": str(source)}

    def inspect_worker_candidate(self, source: Path, format_name: str,
                                 artifact_type: str) -> Inspection:
        """Inspect an unpublished worker candidate for typed DAG preconditions."""
        source = source.resolve(strict=True)
        if not within(source, self.staging_root):
            raise InvalidInput("worker_output_path", "Worker output is outside managed staging")
        maximum_bytes = (MAX_ANALYSIS_REPORT_BYTES if artifact_type == "GeometryAnalysisReport"
                         else MAX_IMPORT_BYTES)
        if source.stat().st_size > maximum_bytes:
            raise InvalidInput("worker_output_too_large", f"Worker output exceeds {maximum_bytes} bytes")
        return _inspect_file_isolated(source, format_name, artifact_type)

    def complete_job_success(self, job_id: str, prepared: list[dict[str, Any]],
                             validation: list[dict[str, Any]]) -> dict[str, Any]:
        """Publish all artifacts, provenance and terminal job state in one DB transaction."""
        current = self.get_job(job_id)
        detail = {**current, "state": "succeeded", "execution_status": "succeeded",
                  "validation_status": "passed" if validation else "not_required",
                  "outputs": [{key: value for key, value in item.items()
                               if key not in {"provenance", "_source_path"}}
                              for item in prepared], "validation": validation}
        now = time.time()
        created_blobs: list[Path] = []
        with self._lock:
            try:
                for item in prepared:
                    target = self._blob_path(item["sha256"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        if target.stat().st_size != item["size"] or digest_file(target) != item["sha256"]:
                            raise RuntimeError("Existing blob disagrees with prepared worker output")
                        continue
                    fd, temporary_name = tempfile.mkstemp(prefix="publish-", dir=target.parent)
                    os.close(fd)
                    temporary = Path(temporary_name)
                    try:
                        with Path(item["_source_path"]).open("rb") as source, temporary.open("wb") as output:
                            sha256, size = copy_hash_bounded(source, output, MAX_IMPORT_BYTES)
                            output.flush(); os.fsync(output.fileno())
                        if sha256 != item["sha256"] or size != item["size"]:
                            raise RuntimeError("Prepared output changed before publication")
                        os.replace(temporary, target)
                        created_blobs.append(target)
                    finally:
                        temporary.unlink(missing_ok=True)
                self._db.execute("BEGIN IMMEDIATE")
                for item in prepared:
                    target = self._blob_path(item["sha256"])
                    self._db.execute("INSERT OR IGNORE INTO blobs VALUES(?,?,?,?)",
                                     (item["sha256"], item["size"],
                                      target.relative_to(self.root).as_posix(), now))
                    self._db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?)",
                        (item["artifact_id"], item["sha256"], item["type"], item["unit"], item["format"],
                         json.dumps(item["properties"], sort_keys=True),
                         json.dumps(item["metadata"], sort_keys=True),
                         json.dumps(item["producer"], sort_keys=True), now))
                    provenance = item["provenance"]
                    self._db.execute("INSERT INTO provenance(artifact_id,job_id,operation_id,input_hashes_json,parameters_json,build_json,created) VALUES(?,?,?,?,?,?,?)",
                        (item["artifact_id"], provenance["job_id"], provenance["operation_id"],
                         json.dumps(provenance["input_hashes"]),
                         json.dumps(provenance["parameters"], sort_keys=True),
                         json.dumps(provenance["build"], sort_keys=True), now))
                cursor = self._db.execute("""UPDATE jobs SET state='succeeded',execution_status='succeeded',
                    validation_status=?,detail_json=?,updated=? WHERE job_id=? AND state='running'""",
                    (detail["validation_status"], json.dumps(detail, sort_keys=True), now, job_id))
                if cursor.rowcount != 1:
                    raise RuntimeError("Job left running state before atomic publication")
                self._db.commit()
            except BaseException:
                self._db.rollback()
                for target in created_blobs:
                    target.unlink(missing_ok=True)
                self.cleanup_orphan_blobs()
                raise
        return detail

    def cleanup_orphan_blobs(self) -> int:
        """Remove managed blob rows/files that no typed artifact references after a crash."""
        removed = 0
        with self._lock:
            rows = self._db.execute("""SELECT b.sha256,b.relative_path FROM blobs b
                LEFT JOIN artifacts a ON a.blob_sha256=b.sha256 WHERE a.artifact_id IS NULL""").fetchall()
            for row in rows:
                path = (self.root / row["relative_path"]).resolve(strict=False)
                if within(path, self.blob_root):
                    path.unlink(missing_ok=True)
                self._db.execute("DELETE FROM blobs WHERE sha256=?", (row["sha256"],))
                removed += 1
            known = {row[0] for row in self._db.execute("SELECT relative_path FROM blobs")}
            for path in self.blob_root.glob("*/*"):
                if path.is_file() and path.relative_to(self.root).as_posix() not in known:
                    path.unlink(missing_ok=True); removed += 1
            self._db.commit()
        return removed

    def inspect(self, artifact_id: str, *, verify: bool = True) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute("""
              SELECT a.*, b.size, b.relative_path FROM artifacts a
              JOIN blobs b ON b.sha256=a.blob_sha256 WHERE artifact_id=?
            """, (artifact_id,)).fetchone()
            provenance_rows = self._db.execute("SELECT * FROM provenance WHERE artifact_id=? ORDER BY id",
                                               (artifact_id,)).fetchall()
        if row is None:
            raise InvalidInput("unknown_artifact", f"Unknown artifact: {artifact_id}")
        path = self.root / row["relative_path"]
        if not within(path, self.blob_root):
            raise RuntimeError("Artifact blob path escaped managed root")
        if verify and digest_file(path) != row["blob_sha256"]:
            raise InvalidInput("artifact_hash_changed", f"Immutable artifact bytes changed: {artifact_id}")
        provenance = [{"job_id": item["job_id"], "operation_id": item["operation_id"],
                       "input_hashes": json.loads(item["input_hashes_json"]),
                       "parameters": json.loads(item["parameters_json"]),
                       "build": json.loads(item["build_json"]), "created": item["created"]}
                      for item in provenance_rows]
        return {"artifact_id": artifact_id, "sha256": row["blob_sha256"], "size": row["size"],
                "type": row["geometry_type"], "unit": row["unit"], "format": row["format"],
                "properties": json.loads(row["properties_json"]),
                "metadata": json.loads(row["metadata_json"]),
                "producer": json.loads(row["producer_json"]), "provenance": provenance,
                "immutable": True}

    def managed_path(self, artifact_id: str) -> Path:
        with self._lock:
            row = self._db.execute("""SELECT b.relative_path FROM artifacts a JOIN blobs b
              ON b.sha256=a.blob_sha256 WHERE a.artifact_id=?""", (artifact_id,)).fetchone()
        if row is None:
            raise InvalidInput("unknown_artifact", f"Unknown artifact: {artifact_id}")
        path = (self.root / row[0]).resolve(strict=True)
        if not within(path, self.blob_root):
            raise RuntimeError("Artifact blob path escaped managed root")
        return path

    def export_file(self, artifact_id: str, destination: Path) -> dict[str, Any]:
        artifact = self.inspect(artifact_id)
        source = self.managed_path(artifact_id)
        destination = destination.expanduser().resolve(strict=False)
        if destination.exists():
            raise FileExistsError(f"Export destination already exists: {destination}")
        if not destination.parent.is_dir():
            raise InvalidInput("export_parent", "Export parent directory does not exist")
        try:
            with source.open("rb") as input_stream, destination.open("xb") as output_stream:
                while chunk := input_stream.read(1024 * 1024):
                    output_stream.write(chunk)
                output_stream.flush(); os.fsync(output_stream.fileno())
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return {"artifact_id": artifact_id, "path": str(destination),
                "sha256": artifact["sha256"], "size": source.stat().st_size}

    def persist_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        plan_id = plan["plan_id"]
        encoded = canonical_json(plan).decode("utf-8")
        with self._lock:
            existing = self._db.execute("SELECT canonical_json FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
            if existing and existing[0] != encoded:
                raise RuntimeError("Plan identifier collision")
            self._db.execute("INSERT OR IGNORE INTO plans VALUES(?,?,?)", (plan_id, encoded, time.time()))
            self._db.commit()
        return json.loads(encoded)

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute("SELECT canonical_json FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
        if row is None:
            raise InvalidInput("unknown_plan", f"Unknown plan: {plan_id}")
        return json.loads(row[0])

    def create_job(self, job_id: str, plan_id: str) -> dict[str, Any]:
        now = time.time()
        detail = {"job_id": job_id, "plan_id": plan_id, "state": "queued",
                  "execution_status": "pending", "validation_status": "pending"}
        with self._lock:
            self._db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
                             (job_id, plan_id, "queued", "pending", "pending",
                              json.dumps(detail, sort_keys=True), now, now))
            self._db.commit()
        return detail

    def update_job(self, job_id: str, *, state: str | None = None,
                   execution_status: str | None = None, validation_status: str | None = None,
                   detail: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.get_job(job_id)
        new_detail = {**current, **(detail or {})}
        new_detail.update({"state": state or current["state"],
                           "execution_status": execution_status or current["execution_status"],
                           "validation_status": validation_status or current["validation_status"]})
        with self._lock:
            self._db.execute("""UPDATE jobs SET state=?,execution_status=?,validation_status=?,
              detail_json=?,updated=? WHERE job_id=?""",
              (new_detail["state"], new_detail["execution_status"], new_detail["validation_status"],
               json.dumps(new_detail, sort_keys=True), time.time(), job_id))
            self._db.commit()
        return new_detail

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise InvalidInput("unknown_job", f"Unknown job: {job_id}")
        detail = json.loads(row["detail_json"])
        detail.update({"state": row["state"], "execution_status": row["execution_status"],
                       "validation_status": row["validation_status"]})
        return detail

    def recover_interrupted_jobs(self) -> int:
        with self._lock:
            rows = self._db.execute("SELECT job_id,detail_json FROM jobs WHERE state IN ('queued','running')").fetchall()
            for row in rows:
                detail = json.loads(row["detail_json"])
                staging = self.staging_root / row["job_id"]
                quarantine = self.quarantine_root / row["job_id"]
                quarantine_error = None
                if staging.exists():
                    if quarantine.exists():
                        quarantine = self.quarantine_root / f"{row['job_id']}-recovery-{uuid.uuid4().hex}"
                    try:
                        os.replace(staging, quarantine)
                    except OSError as exc:
                        # Persist a stable diagnostic without exposing the
                        # server's absolute managed-data path through job APIs.
                        quarantine_error = type(exc).__name__
                detail.update({"state": "failed", "execution_status": "interrupted",
                               "validation_status": "not_run",
                               "error": {"class": "worker_crash", "code": "server_restart",
                                         "message": "Job was interrupted by server restart",
                                         "recoverable": True, "suggested_operations": []}})
                if quarantine.exists():
                    detail["quarantine"] = quarantine.name
                if quarantine_error:
                    detail["quarantine_error"] = quarantine_error
                self._db.execute("""UPDATE jobs SET state='failed', execution_status='interrupted',
                  validation_status='not_run',detail_json=?,updated=? WHERE job_id=?""",
                  (json.dumps(detail, sort_keys=True), time.time(), row["job_id"]))
            self._db.commit()
        return len(rows)

    def add_provenance(self, artifact_id: str, job_id: str, operation_id: str,
                       input_hashes: list[str], parameters: dict[str, Any], build: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute("INSERT INTO provenance(artifact_id,job_id,operation_id,input_hashes_json,parameters_json,build_json,created) VALUES(?,?,?,?,?,?,?)",
                             (artifact_id, job_id, operation_id, json.dumps(input_hashes),
                              json.dumps(parameters, sort_keys=True), json.dumps(build, sort_keys=True), time.time()))
            self._db.commit()

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {table: self._db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                    for table in ("blobs", "artifacts", "plans", "jobs", "provenance")}
