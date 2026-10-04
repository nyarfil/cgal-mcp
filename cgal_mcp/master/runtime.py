"""Generic Master facade: routing, planning, jobs, validation and artifacts."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .errors import InvalidInput, MasterError, WorkerFailure
from .planner import PlanBuilder
from .registry import OperationRegistry
from .store import ArtifactStore
from .supervisor import DEFAULT_MEMORY_MB, WorkerSupervisor, default_worker_path
from .util import digest_file, within


MAX_VALIDATION_REPORT_BYTES = 2 * 1024 * 1024


def _load_validation_report(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_VALIDATION_REPORT_BYTES:
            raise WorkerFailure("validation_report_too_large",
                                "Validation report exceeds 2 MiB",
                                "validation_failure", False)
        with path.open("rb") as stream:
            encoded = stream.read(MAX_VALIDATION_REPORT_BYTES + 1)
        if len(encoded) > MAX_VALIDATION_REPORT_BYTES:
            raise WorkerFailure("validation_report_too_large",
                                "Validation report exceeds 2 MiB",
                                "validation_failure", False)
        value = json.loads(encoded.decode("utf-8"))
    except WorkerFailure:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerFailure("validation_report_malformed", str(exc),
                            "validation_failure", False) from exc
    if not isinstance(value, dict):
        raise WorkerFailure("validation_report_malformed",
                            "Validation report must be a JSON object",
                            "validation_failure", False)
    return value


def _catalog_path(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    configured = os.environ.get("CGAL_MASTER_CATALOG")
    if configured:
        return Path(configured).resolve()
    candidates = [Path(__file__).with_name("catalog"),
                  Path(__file__).resolve().parents[2] / "catalog",
                  Path("catalog").resolve()]
    return next((candidate for candidate in candidates
                 if (candidate / "baseline.json").is_file()
                 and (candidate / "docs_index.jsonl").is_file()), candidates[0])


def _docs_index_path(explicit: Path | None, catalog_root: Path) -> Path | None:
    if explicit is not None:
        return explicit.resolve()
    configured = os.environ.get("CGAL_MASTER_DOCS_INDEX")
    if configured:
        return Path(configured).resolve()
    candidates = [catalog_root / "docs_index.sqlite",
                  Path(__file__).resolve().parents[2] / "work" / "master-docs-index.sqlite"]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


class MasterRuntime:
    def __init__(self, root: Path, *, operations: Path | list[Path] | None = None,
                 worker: Path | None = None, concurrency: int = 2,
                 require_memory_limit: bool = True, catalog_root: Path | None = None,
                 allowed_file_roots: list[Path] | None = None,
                 docs_index: Path | None = None):
        if type(concurrency) is not int or not 1 <= concurrency <= 2:
            raise ValueError("Master worker concurrency must be 1 or 2")
        self.registry = OperationRegistry(operations)
        self.store = ArtifactStore(root)
        self.planner = PlanBuilder(self.registry, self.store)
        self.supervisor = WorkerSupervisor(self.registry, worker or default_worker_path(),
                                           require_memory_limit=require_memory_limit)
        self.catalog_root = _catalog_path(catalog_root)
        self.docs_index = _docs_index_path(docs_index, self.catalog_root)
        self.allowed_file_roots = (None if allowed_file_roots is None else
                                   tuple(path.resolve() for path in allowed_file_roots))
        self.semaphore = asyncio.Semaphore(concurrency)
        self.concurrency = concurrency
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.started = time.time()

    def close(self) -> None:
        if any(not task.done() for task in self.tasks.values()):
            raise RuntimeError("Cannot close MasterRuntime while jobs are running")
        self.store.close()
        self.registry.close()

    def capabilities_search(self, query: str, artifact_ids: list[str] | None = None,
                            constraints: dict[str, Any] | None = None,
                            limit: int = 8) -> dict[str, Any]:
        constraints = constraints or {}
        input_types = None
        if artifact_ids:
            input_types = [self.store.inspect(artifact_id)["type"] for artifact_id in artifact_ids]
        return self.registry.search(query, input_types=input_types,
            status=constraints.get("status"), dependencies=constraints.get("dependencies"),
            kernel=constraints.get("kernel"), allowed_licenses=constraints.get("allowed_licenses"), limit=limit)

    def capabilities_describe(self, operation_id: str) -> dict[str, Any]:
        operation = self.registry.get(operation_id)
        return {**operation, "registry_revision": self.registry.revision,
                "executable": operation["status"] in {"IMPLEMENTED", "VALIDATED"}}

    def plan(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.planner.build(request)

    async def execute(self, plan_id: str, *, wall_time_ms: int = 120000,
                      memory_mb: int = DEFAULT_MEMORY_MB) -> dict[str, Any]:
        plan = self.store.get_plan(plan_id)
        if plan["registry_revision"] != self.registry.revision:
            raise InvalidInput("stale_plan_registry", "Plan registry revision no longer matches")
        if not 1 <= wall_time_ms <= 86_400_000 or not 64 <= memory_mb <= DEFAULT_MEMORY_MB:
            raise InvalidInput("execution_limits", "Execution limits are outside allowed bounds")
        job_id = "job_" + uuid.uuid4().hex
        job = self.store.create_job(job_id, plan_id)
        task = asyncio.create_task(self._run(job_id, plan, wall_time_ms, memory_mb),
                                   name=f"cgal-master-{job_id}")
        self.tasks[job_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(job_id, None))
        return job

    async def _run(self, job_id: str, plan: dict[str, Any], wall_time_ms: int,
                   memory_mb: int) -> None:
        staging = self.store.staging_root / job_id
        produced: dict[tuple[str, str], dict[str, Any]] = {}
        transforms: list[dict[str, Any]] = []
        validation_reports: list[dict[str, Any]] = []
        current_role = "pending"
        try:
            staging.mkdir(parents=True, exist_ok=False)
            async with self.semaphore:
                self.store.update_job(job_id, state="running", execution_status="running",
                                      validation_status="pending")
                for step in plan["steps"]:
                    current_role = step.get("role", "transform")
                    operation = self.registry.get(step["operation"], executable=True)
                    if operation["revision"] != step["revision"]:
                        raise InvalidInput("stale_plan_operation", f"Revision changed for {operation['id']}")
                    step_dir = staging / step["id"]
                    step_dir.mkdir()
                    inputs = self._resolve_inputs(step, produced)
                    self._recheck_inputs(inputs)
                    request_id = uuid.uuid4().hex
                    request = {"protocol": 1, "request_id": request_id,
                        "operation": operation["id"], "inputs": inputs,
                        "parameters": step["parameters"], "output_dir": str(step_dir.resolve()),
                        "kernel": step["kernel"],
                        "limits": {"wall_time_ms": wall_time_ms, "memory_mb": memory_mb}}
                    response, evidence = await self.supervisor.execute(request, step_dir)
                    self._recheck_inputs(inputs)
                    for output in response["outputs"]:
                        descriptor = {"artifact_id": f"candidate:{step['id']}:{output['slot']}",
                            "type": output["type"], "unit": output.get("unit", inputs[0]["unit"] if inputs else "none"),
                            "format": output["format"], "path": str(Path(output["path"]).resolve()),
                            "sha256": digest_file(Path(output["path"])),
                            "step": step["id"], "slot": output["slot"]}
                        produced[(step["id"], output["slot"])] = descriptor
                    step_result = {"step_id": step["id"], "operation": operation["id"],
                                   "metrics": response.get("metrics", {}),
                                   "diagnostics": response.get("diagnostics", []), "build": evidence["manifest"]}
                    if step.get("role") == "validator":
                        report_descriptor = produced[(step["id"], operation["io"]["outputs"][0]["slot"])]
                        report = _load_validation_report(Path(report_descriptor["path"]))
                        required_checks = operation["validation"].get("required_report_checks", {})
                        missing_or_failed = {key: expected for key, expected in required_checks.items()
                                             if report.get(key) != expected}
                        if report.get("status") != "pass" or missing_or_failed:
                            validation_reports.append({**step_result, "report": report})
                            message = ("Mandatory validator rejected candidate" if not missing_or_failed else
                                       "Validation report omitted or failed required checks: " +
                                       ", ".join(sorted(missing_or_failed)))
                            raise WorkerFailure("validation_failed", message,
                                                "validation_failure", False)
                        validation_reports.append({**step_result, "report": report})
                    else:
                        transforms.append({**step_result, "step": step, "inputs": inputs,
                                           "outputs": response["outputs"]})
                artifacts: list[dict[str, Any]] = []
                for transform in transforms:
                    step = transform["step"]
                    operation = self.registry.get(step["operation"])
                    required_validators = set(operation["validation"]["validators"])
                    passed = {item["operation"] for item in validation_reports
                              if next((candidate.get("validates") for candidate in plan["steps"]
                                       if candidate["id"] == item["step_id"]), None) == step["id"]}
                    if required_validators - passed:
                        raise WorkerFailure("validator_not_run", f"Validators did not pass for {operation['id']}",
                                            "validation_failure", False)
                    input_hashes = [item["sha256"] for item in transform["inputs"]]
                    for output_spec in operation["io"]["outputs"]:
                        descriptor = produced[(step["id"], output_spec["slot"])]
                        artifact = self.store.prepare_worker_output(Path(descriptor["path"]), descriptor["unit"],
                            descriptor["format"], descriptor["type"],
                            {"kind": "worker", "job_id": job_id, "operation": operation["id"]},
                            {"job_id": job_id, "operation_id": operation["id"],
                             "input_hashes": input_hashes, "parameters": step["parameters"],
                             "build": transform["build"]})
                        artifacts.append(artifact)
                self.store.complete_job_success(job_id, artifacts, validation_reports)
        except asyncio.CancelledError:
            self.store.update_job(job_id, state="cancelled", execution_status="cancelled",
                                  validation_status="not_run")
            self._quarantine(staging, job_id)
            raise
        except MasterError as exc:
            validation_failed = exc.failure_class == "validation_failure" and current_role == "validator"
            self.store.update_job(job_id, state="rejected" if validation_failed else "failed",
                execution_status="succeeded" if validation_failed else "failed",
                validation_status="failed" if validation_failed else "not_run",
                detail={"error": exc.as_dict(), "validation": validation_reports})
            self._quarantine(staging, job_id)
        except Exception as exc:
            error = MasterError("internal_failure", str(exc), "internal", False)
            self.store.update_job(job_id, state="failed", execution_status="failed",
                                  validation_status="not_run", detail={"error": error.as_dict()})
            self._quarantine(staging, job_id)
        else:
            shutil.rmtree(staging, ignore_errors=True)

    def _resolve_inputs(self, step: dict[str, Any],
                        produced: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
        operation = self.registry.get(step["operation"])
        result: list[dict[str, Any]] = []
        for spec in operation["io"]["inputs"]:
            binding = step["inputs"][spec["slot"]]
            if "artifact_id" in binding:
                artifact = self.store.inspect(binding["artifact_id"])
                result.append({"artifact_id": artifact["artifact_id"], "type": artifact["type"],
                               "unit": artifact["unit"], "format": artifact["format"],
                               "path": str(self.store.managed_path(artifact["artifact_id"])),
                               "sha256": artifact["sha256"]})
            else:
                descriptor = produced.get((binding["step"], binding["slot"]))
                if descriptor is None:
                    raise InvalidInput("missing_step_output", f"Missing output from {binding['step']}")
                result.append({key: descriptor[key] for key in
                               ("artifact_id", "type", "unit", "format", "path", "sha256")})
        return result

    @staticmethod
    def _recheck_inputs(inputs: list[dict[str, Any]]) -> None:
        for item in inputs:
            path = Path(item["path"])
            if not path.is_file() or digest_file(path) != item["sha256"]:
                raise InvalidInput("input_hash_changed", f"Input changed during execution: {item['artifact_id']}")

    def _quarantine(self, staging: Path, job_id: str) -> None:
        if not staging.exists():
            return
        target = self.store.quarantine_root / job_id
        if target.exists():
            shutil.rmtree(staging, ignore_errors=True)
        else:
            os.replace(staging, target)

    def validate(self, artifact_id: str, against: str,
                 operation_id: str = "hull.validate.convex_enclosure",
                 parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.plan({"steps": [{"id": "validate", "operation": operation_id,
            "inputs": {"geometry": artifact_id, "source": against},
            "parameters": parameters or {}}]})

    def artifact_inspect(self, artifact_id: str) -> dict[str, Any]:
        return self.store.inspect(artifact_id)

    def artifact_import(self, path: str, unit: str, format: str | None = None,
                        artifact_type: str | None = None) -> dict[str, Any]:
        source = Path(path).expanduser().resolve(strict=True)
        self._file_gate(source)
        return self.store.import_file(source, unit, format_name=format, artifact_type=artifact_type)

    def artifact_export(self, artifact_id: str, path: str) -> dict[str, Any]:
        destination = Path(path).expanduser().resolve(strict=False)
        self._file_gate(destination)
        return self.store.export_file(artifact_id, destination)

    def _file_gate(self, path: Path) -> None:
        if self.allowed_file_roots is not None and not any(within(path, root) for root in self.allowed_file_roots):
            raise InvalidInput("file_access_denied", "Path is outside configured CGAL Master file roots")

    def docs_search(self, query: str, limit: int = 10) -> dict[str, Any]:
        if not query.strip() or not 1 <= limit <= 100:
            raise InvalidInput("docs_search", "Query and limit are invalid")
        if self.docs_index is not None:
            return self._docs_sqlite_search(query, limit)
        roots = [self.catalog_root]
        records: list[dict[str, Any]] = []
        terms = query.lower().split()
        index_available = (self.catalog_root / "baseline.json").is_file() and (self.catalog_root / "docs_index.jsonl").is_file()
        if not index_available:
            return {"query": query, "index_scope": "unavailable", "index_available": False,
                    "results": [], "legacy_api_index_used": False}
        for root in roots:
            if not root.is_dir():
                continue
            jsonl = root / "docs_index.jsonl"
            if jsonl.is_file():
                try:
                    with jsonl.open("r", encoding="utf-8") as stream:
                        for line in stream:
                            value = json.loads(line)
                            text = json.dumps(value, ensure_ascii=False).lower()
                            score = sum(text.count(term) for term in terms)
                            if score:
                                records.append({"title": value.get("title", value.get("package", "")),
                                    "source": jsonl.name, "score": score,
                                    "package": value.get("package"), "kind": value.get("kind"),
                                    "docs_url": value.get("docs_url"),
                                    "identifiers": value.get("identifiers", [])[:25],
                                    "source_snippets": value.get("source_snippets", [])})
                except (OSError, json.JSONDecodeError):
                    pass
            for path in sorted(root.glob("*.json")):
                if path.name == "operations.json":
                    continue
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                self._collect_docs(value, path.name, terms, records)
        records.sort(key=lambda item: (-item["score"], item["source"], item["title"]))
        for record in records:
            record.update({"scope": "reference", "executable": False})
        return {"query": query, "index_scope": "pinned_generated_catalog", "index_available": True,
                "results": records[:limit], "legacy_api_index_used": False}

    def _docs_sqlite_metadata(self) -> dict[str, Any]:
        assert self.docs_index is not None
        if not self.docs_index.is_file():
            raise InvalidInput("docs_index_missing", "Configured docs index does not exist")
        try:
            connection = sqlite3.connect(f"file:{self.docs_index.as_posix()}?mode=ro&immutable=1", uri=True)
            try:
                metadata = {key: json.loads(value) for key, value in connection.execute("SELECT key,value FROM metadata")}
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                connection.close()
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise InvalidInput("docs_index_schema", f"Docs index is unreadable: {exc}") from exc
        if metadata.get("schema_version") != 1 or metadata.get("fts_tokenizer") != "trigram":
            raise InvalidInput("docs_index_schema", "Docs index schema/tokenizer is unsupported")
        if self.registry.cgal_versions and metadata.get("cgal_version") not in self.registry.cgal_versions:
            raise InvalidInput("docs_index_version", "Docs index CGAL version disagrees with registry")
        baseline_path = self.catalog_root / "baseline.json"
        if baseline_path.is_file():
            try:
                baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise InvalidInput("docs_index_catalog", "Catalog baseline is unreadable") from exc
            if (metadata.get("catalog_version") != baseline.get("catalog_version")
                    or metadata.get("package_count") != baseline.get("package_count")):
                raise InvalidInput("docs_index_catalog", "Docs index metadata disagrees with catalog baseline")
        if not {"metadata", "documents", "documents_fts"}.issubset(tables):
            raise InvalidInput("docs_index_schema", "Docs index tables are incomplete")
        provenance = metadata.get("provenance")
        if not isinstance(provenance, dict) or provenance.get("mode") != "official":
            raise InvalidInput("docs_index_provenance", "Docs index lacks official pinned provenance")
        return metadata

    def _docs_sqlite_search(self, query: str, limit: int) -> dict[str, Any]:
        metadata = self._docs_sqlite_metadata()
        assert self.docs_index is not None
        phrase = '"' + query.replace('"', '""') + '"'
        try:
            connection = sqlite3.connect(f"file:{self.docs_index.as_posix()}?mode=ro&immutable=1", uri=True)
            try:
                rows = connection.execute("""SELECT d.kind,d.package_id,d.status,d.title,d.source_path,
                    d.source_sha256,snippet(documents_fts,2,'[',']','…',14),bm25(documents_fts)
                    FROM documents_fts JOIN documents d ON d.id=documents_fts.rowid
                    WHERE documents_fts MATCH ? ORDER BY bm25(documents_fts) LIMIT ?""",
                    (phrase, limit)).fetchall()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise InvalidInput("docs_index_query", f"Docs index query failed: {exc}") from exc
        fields = ("kind", "package", "status", "title", "source_path", "source_sha256", "snippet", "rank")
        results = [dict(zip(fields, row)) for row in rows]
        for result in results:
            result.update({"scope": "reference", "executable": False})
        return {"query": query, "index_scope": "pinned_generated_catalog", "index_available": True,
                "index_backend": "sqlite-fts5-trigram", "catalog_version": metadata["catalog_version"],
                "cgal_version": metadata["cgal_version"],
                "results": results, "legacy_api_index_used": False}

    @classmethod
    def _collect_docs(cls, value: Any, source: str, terms: list[str],
                      records: list[dict[str, Any]], prefix: str = "") -> None:
        if isinstance(value, dict):
            title = str(value.get("name") or value.get("id") or value.get("title") or prefix)
            text = json.dumps(value, ensure_ascii=False).lower()
            score = sum(text.count(term) for term in terms)
            if score:
                records.append({"title": title, "source": source, "score": score,
                                "package": value.get("package") or value.get("id"),
                                "references": value.get("sources") or value.get("docs") or []})
            for key, item in value.items():
                if isinstance(item, (dict, list)):
                    cls._collect_docs(item, source, terms, records, str(key))
        elif isinstance(value, list):
            for item in value:
                cls._collect_docs(item, source, terms, records, prefix)

    async def system_health(self) -> dict[str, Any]:
        worker: dict[str, Any]
        executable_operations = [operation_id for operation_id, operation in self.registry.operations.items()
                                 if operation["status"] in {"IMPLEMENTED", "VALIDATED"}]
        try:
            manifest = None
            verified_operations: list[str] = []
            for operation_id in executable_operations:
                manifest = await self.supervisor.manifest(operation_id)
                verified_operations.append(operation_id)
            worker = {"available": True, "manifest": manifest,
                      "verified_operations": verified_operations,
                      "resource_limit_mode": self.supervisor.resource_limit_mode}
        except MasterError as exc:
            worker = {"available": False, "error": exc.as_dict(),
                      "resource_limit_mode": self.supervisor.resource_limit_mode}
        catalog: dict[str, Any] = {"available": False}
        baseline = self.catalog_root / "baseline.json"
        if baseline.is_file():
            try:
                data = json.loads(baseline.read_text(encoding="utf-8"))
                catalog = {"available": True, "version": data.get("catalog_version"),
                           "cgal_version": data.get("cgal_version"), "coverage": data.get("coverage"),
                           "package_count": data.get("package_count")}
            except (OSError, json.JSONDecodeError):
                catalog = {"available": False, "error": "catalog/baseline.json is invalid"}
        docs_index_health: dict[str, Any] = {"available": False, "backend": "jsonl-fallback"}
        if self.docs_index is not None:
            try:
                metadata = self._docs_sqlite_metadata()
                docs_index_health = {"available": True, "backend": "sqlite-fts5-trigram",
                                     "catalog_version": metadata.get("catalog_version"),
                                     "cgal_version": metadata.get("cgal_version")}
            except InvalidInput as exc:
                docs_index_health = {"available": False, "backend": "sqlite-fts5-trigram",
                                     "error": exc.as_dict()}
        healthy = worker["available"] and catalog.get("available", False)
        if self.docs_index is not None:
            healthy = healthy and docs_index_health["available"]
        return {"status": "ok" if healthy else "degraded",
                "uptime_s": time.time() - self.started, "registry_revision": self.registry.revision,
                "registry_sources": [path.name for path in self.registry.paths],
                "cgal_versions": sorted(self.registry.cgal_versions),
                "operation_counts": {status: sum(op["status"] == status for op in self.registry.operations.values())
                                     for status in sorted({op["status"] for op in self.registry.operations.values()})},
                "store": self.store.counts(), "worker": worker, "catalog": catalog,
                "docs_index": docs_index_health,
                "file_access": {"mode": "local_unrestricted" if self.allowed_file_roots is None else "allowlist",
                                "root_count": None if self.allowed_file_roots is None else len(self.allowed_file_roots)},
                "concurrency": self.concurrency, "max_import_bytes": 512 * 1024 * 1024}

    def job_status(self, job_id: str) -> dict[str, Any]:
        return self.store.get_job(job_id)

    async def job_cancel(self, job_id: str) -> dict[str, Any]:
        state = self.store.get_job(job_id)
        if state["state"] in {"succeeded", "failed", "rejected", "cancelled"}:
            return state
        task = self.tasks.get(job_id)
        if task is None:
            return self.store.update_job(job_id, state="failed", execution_status="interrupted",
                                         validation_status="not_run")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        current = self.store.get_job(job_id)
        if current["state"] not in {"succeeded", "failed", "rejected", "cancelled"}:
            current = self.store.update_job(job_id, state="cancelled",
                                            execution_status="cancelled", validation_status="not_run")
        return current


def default_runtime(*, allowed_file_roots: list[Path] | None = None) -> MasterRuntime:
    return MasterRuntime(Path(os.environ.get("CGAL_MASTER_DATA", "work/cgal-master-data")),
                         allowed_file_roots=allowed_file_roots)
