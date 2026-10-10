"""Generic Master facade: routing, planning, jobs, validation and artifacts."""

from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .errors import InvalidInput, MasterError, PreconditionFailure, WorkerFailure
from .planner import PlanBuilder
from .registry import OperationRegistry
from .package_terms import PACKAGE_REFERENCE_TERMS, package_reference_score
from .search import QueryTerms, fts_expression, lexical_score, parse_query
from .store import ArtifactStore
from .resources import ResourceConfig
from .supervisor import WorkerSupervisor, default_worker_path
from .util import digest_file, within


MAX_VALIDATION_REPORT_BYTES = 2 * 1024 * 1024


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


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
        value = json.loads(encoded.decode("utf-8"), parse_constant=_reject_json_constant)
    except WorkerFailure:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise WorkerFailure("validation_report_malformed", str(exc),
                            "validation_failure", False) from exc
    if not isinstance(value, dict):
        raise WorkerFailure("validation_report_malformed",
                            "Validation report must be a JSON object",
                            "validation_failure", False)
    return value


def _report_value(report: dict[str, Any], path: str) -> tuple[bool, Any]:
    value: Any = report
    for component in path.split("."):
        if not isinstance(value, dict) or component not in value:
            return False, None
        value = value[component]
    return True, value


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
                 policies: Path | None = None,
                 worker: Path | None = None, concurrency: int | None = None,
                 resource_config: ResourceConfig | None = None,
                 require_memory_limit: bool = True, catalog_root: Path | None = None,
                 allowed_file_roots: list[Path] | None = None,
                 docs_index: Path | None = None):
        resources = resource_config or ResourceConfig()
        if concurrency is not None:
            resources = resources.with_concurrency(concurrency)
        self.registry = OperationRegistry(operations, policies=policies)
        self.store = ArtifactStore(root)
        self.planner = PlanBuilder(self.registry, self.store)
        self.supervisor = WorkerSupervisor(self.registry, worker or default_worker_path(),
                                           require_memory_limit=require_memory_limit,
                                           max_memory_mb=resources.max_memory_mb)
        self.catalog_root = _catalog_path(catalog_root)
        self.docs_index = _docs_index_path(docs_index, self.catalog_root)
        self.allowed_file_roots = (None if allowed_file_roots is None else
                                   tuple(path.resolve() for path in allowed_file_roots))
        self.semaphore = asyncio.Semaphore(resources.concurrency)
        self.resources = resources
        self.concurrency = resources.concurrency
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
            kernel=constraints.get("kernel"), allowed_licenses=constraints.get("allowed_licenses"), limit=limit,
            discovery=True)

    def capabilities_describe(self, operation_id: str) -> dict[str, Any]:
        operation = self.registry.get(operation_id)
        return {**operation, "registry_revision": self.registry.revision,
                "policies": self.registry.policies_for(operation_id),
                "executable": operation["status"] in {"IMPLEMENTED", "VALIDATED"}}

    def plan(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.planner.build(request)

    def _default_wall_time(self, plan: dict[str, Any]) -> int:
        return max(
            [self.resources.default_wall_time_ms]
            + [int(self.registry.get(step["operation"]).get(
                "resource_profile", {}).get("default_wall_time_ms",
                                             self.resources.default_wall_time_ms))
               for step in plan["steps"]])

    async def execute(self, plan_id: str, *, wall_time_ms: int | None = None,
                      memory_mb: int | None = None) -> dict[str, Any]:
        plan = self.store.get_plan(plan_id)
        if plan["registry_revision"] != self.registry.revision:
            raise InvalidInput("stale_plan_registry", "Plan registry revision no longer matches")
        if wall_time_ms is None:
            wall_time_ms = self._default_wall_time(plan)
        if memory_mb is None:
            memory_mb = self.resources.default_memory_mb
        if (type(wall_time_ms) is not int or type(memory_mb) is not int
                or not 1 <= wall_time_ms <= self.resources.max_wall_time_ms
                or not 64 <= memory_mb <= self.resources.max_memory_mb):
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
                    self._runtime_preconditions(operation, inputs)
                    self._runtime_parameter_preconditions(operation, inputs, step["parameters"])
                    request_id = uuid.uuid4().hex
                    request = {"protocol": 1, "request_id": request_id,
                        "operation": operation["id"], "inputs": inputs,
                        "parameters": step["parameters"], "output_dir": str(step_dir.resolve()),
                        "kernel": step["kernel"],
                        "limits": {"wall_time_ms": wall_time_ms, "memory_mb": memory_mb}}
                    response, evidence = await self.supervisor.execute(request, step_dir)
                    self._recheck_inputs(inputs)
                    for output in response["outputs"]:
                        inspection = None
                        if output["type"] != "ValidationReport":
                            inspection = self.store.inspect_worker_candidate(
                                Path(output["path"]), output["format"], output["type"])
                        descriptor = {"artifact_id": f"candidate:{step['id']}:{output['slot']}",
                            "type": output["type"], "unit": output.get("unit", inputs[0]["unit"] if inputs else "none"),
                            "format": output["format"], "path": str(Path(output["path"]).resolve()),
                            "sha256": digest_file(Path(output["path"])),
                            "size": Path(output["path"]).stat().st_size,
                            "step": step["id"], "slot": output["slot"]}
                        if inspection is not None:
                            descriptor["properties"] = inspection.properties
                            descriptor["metadata"] = inspection.metadata
                        produced[(step["id"], output["slot"])] = descriptor
                    step_result = {"step_id": step["id"], "operation": operation["id"],
                                   "metrics": response.get("metrics", {}),
                                   "diagnostics": response.get("diagnostics", []), "build": evidence["manifest"]}
                    if step.get("role") == "validator":
                        report_descriptor = produced[(step["id"], operation["io"]["outputs"][0]["slot"])]
                        report = _load_validation_report(Path(report_descriptor["path"]))
                        required_checks = operation["validation"].get("required_report_checks", {})
                        missing_or_failed = {key: expected for key, expected in required_checks.items()
                                             if _report_value(report, key) != (True, expected)}
                        for key in operation["validation"].get("required_report_fields", []):
                            if not _report_value(report, key)[0]:
                                missing_or_failed[key] = "required"
                        for key, minimum in operation["validation"].get("required_report_minimum", {}).items():
                            _, value = _report_value(report, key)
                            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                                    or not math.isfinite(float(value)) or value < minimum):
                                missing_or_failed[key] = {"minimum": minimum}
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
                             "input_hashes": input_hashes,
                             "parameters": {"values": step["parameters"],
                                            "normalization": step.get("parameter_normalization", [])},
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
                               "sha256": artifact["sha256"], "size": artifact["size"],
                               "properties": artifact["properties"],
                               "metadata": artifact["metadata"]})
            else:
                descriptor = produced.get((binding["step"], binding["slot"]))
                if descriptor is None:
                    raise InvalidInput("missing_step_output", f"Missing output from {binding['step']}")
                result.append({key: descriptor[key] for key in
                               ("artifact_id", "type", "unit", "format", "path", "sha256",
                                "size", "properties", "metadata")})
        return result

    @staticmethod
    def _runtime_preconditions(operation: dict[str, Any], inputs: list[dict[str, Any]]) -> None:
        for condition in operation.get("preconditions", []):
            if condition.get("id") == "bounded_input":
                for item in inputs:
                    metadata = item.get("metadata", {})
                    # Mirror the plan-time rule: point sets have no faces, so face
                    # limits constrain only the mesh/soup inputs of a mixed-input
                    # operation and a point set's vertex count is its point count.
                    is_mesh = "faces" in metadata or "vertices" in metadata
                    limits = [("size", "maximum_bytes", item.get("size")),
                              ("vertices", "maximum_vertices",
                               metadata.get("vertices", metadata.get("point_count")))]
                    if is_mesh or not any(k in metadata for k in ("point_count", "bounds")):
                        limits += [("faces", "maximum_faces", metadata.get("faces")),
                                   ("max_face_degree", "maximum_face_degree",
                                    metadata.get("max_face_degree"))]
                    for label, key, actual in limits:
                        if key in condition and (not isinstance(actual, int) or actual > condition[key]):
                            raise PreconditionFailure(
                                f"{operation['id']} requires {label}<={condition[key]}")
                continue
            if "worker_check" in condition:
                continue
            if "bounds" in condition:
                contract = condition["bounds"]
                for item in inputs:
                    bounds = item.get("metadata", {}).get("bounds")
                    if (not isinstance(bounds, list) or not bounds
                            or any(not isinstance(axis, list) or len(axis) != 2
                                   or any(not isinstance(value, (int, float))
                                          or isinstance(value, bool) or not math.isfinite(float(value))
                                          for value in axis) for axis in bounds)):
                        raise PreconditionFailure(f"{operation['id']} requires finite coordinate bounds")
                    maximum = max(abs(float(value)) for axis in bounds for value in axis)
                    span = max(float(axis[1]) - float(axis[0]) for axis in bounds)
                    if (maximum > contract["maximum_absolute_coordinate"]
                            or not math.isfinite(span) or span < contract["minimum_span"]
                            or maximum / span > contract["maximum_translation_to_span_ratio"]):
                        raise PreconditionFailure(
                            f"{operation['id']} coordinates are outside its numeric scale contract")
                continue
            prop = condition.get("property")
            values = [item.get("properties", {}).get(
                prop, item.get("metadata", {}).get(prop, "unknown")) for item in inputs]
            if "equals" in condition and any(value != condition["equals"] for value in values):
                raise PreconditionFailure(
                    f"{operation['id']} requires {prop}={condition['equals']}")
            if "minimum" in condition and any(
                    not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(float(value)) or value < condition["minimum"]
                    for value in values):
                raise PreconditionFailure(
                    f"{operation['id']} requires {prop}>={condition['minimum']}")

    @staticmethod
    def _runtime_parameter_preconditions(operation: dict[str, Any], inputs: list[dict[str, Any]],
                                         parameters: dict[str, Any]) -> None:
        by_slot = {spec["slot"]: value for spec, value in zip(operation["io"]["inputs"], inputs)}
        for condition in operation.get("parameter_preconditions", []):
            value: Any = parameters
            for component in condition["parameter"].split("."):
                if not isinstance(value, dict) or component not in value:
                    raise InvalidInput("parameter_precondition",
                                       f"{operation['id']} lacks parameter {condition['parameter']}")
                value = value[component]
            if "finite_coordinate_ratio_metadata" in condition:
                bounds = by_slot[condition["input"]]["metadata"].get(
                    condition["finite_coordinate_ratio_metadata"])
                maximum = (max(abs(float(item)) for axis in bounds for item in axis)
                           if isinstance(bounds, list) and bounds else math.inf)
                if (not isinstance(value, (int, float)) or isinstance(value, bool)
                        or not math.isfinite(float(value)) or value == 0
                        or not math.isfinite(maximum / float(value))):
                    raise PreconditionFailure(
                        f"{operation['id']} requires finite coordinate-to-{condition['parameter']} ratios")
                continue
            limit = by_slot[condition["input"]]["metadata"].get(condition["less_than_metadata"])
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not isinstance(limit, (int, float)) or isinstance(limit, bool)
                    or value >= limit):
                raise PreconditionFailure(
                    f"{operation['id']} requires {condition['parameter']} < "
                    f"{condition['less_than_metadata']}")

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
        if not isinstance(query, str) or not query.strip() or type(limit) is not int or not 1 <= limit <= 100:
            raise InvalidInput("docs_search", "Query and limit are invalid")
        if self.docs_index is not None:
            return self._docs_sqlite_search(query, limit)
        parsed = parse_query(query)
        records: list[dict[str, Any]] = []
        baseline_path = self.catalog_root / "baseline.json"
        packages_path = self.catalog_root / "packages.json"
        jsonl = self.catalog_root / "docs_index.jsonl"
        index_available = (baseline_path.is_file() and packages_path.is_file()
                           and jsonl.is_file())
        if not index_available:
            return {"query": query, "index_scope": "unavailable", "index_available": False,
                    "results": [], "legacy_api_index_used": False}
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            packages_document = json.loads(packages_path.read_text(encoding="utf-8"))
            expected_count = baseline.get("package_count")
            package_rows = packages_document.get("packages")
            if (baseline.get("schema_version") != 1
                    or not isinstance(expected_count, int) or expected_count <= 0
                    or packages_document.get("schema_version") != 1
                    or packages_document.get("baseline") != baseline.get("catalog_version")
                    or not isinstance(package_rows, list)
                    or len(package_rows) != expected_count):
                raise ValueError("baseline/packages metadata disagree")
            expected_packages = {item.get("id") for item in package_rows
                                 if isinstance(item, dict) and isinstance(item.get("id"), str)}
            if len(expected_packages) != expected_count:
                raise ValueError("packages catalog contains missing or duplicate ids")
            index_rows: list[dict[str, Any]] = []
            with jsonl.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    if not line.strip():
                        raise ValueError(f"blank JSONL record at line {line_number}")
                    value = json.loads(line)
                    if (not isinstance(value, dict) or value.get("kind") != "package"
                            or value.get("status") != "CATALOGED"
                            or not isinstance(value.get("package"), str)
                            or not isinstance(value.get("title"), str)
                            or not isinstance(value.get("docs_url"), str)
                            or f"/{baseline.get('cgal_version')}/" not in value["docs_url"]):
                        raise ValueError(f"invalid package JSONL record at line {line_number}")
                    index_rows.append(value)
            indexed_packages = {value["package"] for value in index_rows}
            if (len(index_rows) != expected_count or len(indexed_packages) != expected_count
                    or indexed_packages != expected_packages):
                raise ValueError("package JSONL is truncated, duplicated, or disagrees with packages.json")
            for value in index_rows:
                title = str(value.get("title", value.get("package", "")))
                package = str(value.get("package") or "")
                identifiers = tuple(str(item) for item in value.get("identifiers", [])[:25])
                title_score, title_shared = lexical_score(
                    parsed, f"{title} {package}", aliases=(title, package))
                identifier_score, identifier_shared = lexical_score(
                    parsed, " ".join(identifiers))
                shared = title_shared | identifier_shared
                score = (3.0 * title_score + 0.25 * identifier_score
                         + package_reference_score(parsed.normalized, package))
                if score <= 0:
                    continue
                records.append({"title": title, "source": jsonl.name,
                                "score": round(score, 6), "package": package,
                                "kind": value.get("kind"),
                                "docs_url": value.get("docs_url"),
                                "identifiers": list(identifiers),
                                "source_snippets": value.get("source_snippets", []),
                                "matched_concepts": sorted(shared)})
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise InvalidInput("docs_catalog_fallback",
                               f"Pinned fallback documentation catalog is invalid: {exc}") from exc
        records.sort(key=lambda item: (-item["score"], item["package"] or "", item["title"]))
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
        parsed = parse_query(query)
        expression = fts_expression(parsed)
        reference_packages = [package for package in PACKAGE_REFERENCE_TERMS
                              if package_reference_score(parsed.normalized, package) > 0]
        if expression is None and not reference_packages:
            return {"query": query, "index_scope": "pinned_generated_catalog",
                    "index_available": True, "index_backend": "sqlite-fts5-trigram",
                    "catalog_version": metadata["catalog_version"],
                    "cgal_version": metadata["cgal_version"], "results": [],
                    "legacy_api_index_used": False}
        candidate_limit = min(max(limit * 40, 200), 2000)
        try:
            connection = sqlite3.connect(f"file:{self.docs_index.as_posix()}?mode=ro&immutable=1", uri=True)
            try:
                rows = []
                if expression is not None:
                    rows = connection.execute("""SELECT d.kind,d.package_id,d.status,d.title,d.source_path,
                        d.source_sha256,d.aliases,
                        snippet(documents_fts,2,'[',']','…',14),
                        bm25(documents_fts,10.0,6.0,0.2)
                        FROM documents_fts JOIN documents d ON d.id=documents_fts.rowid
                        WHERE documents_fts MATCH ?
                        ORDER BY bm25(documents_fts,10.0,6.0,0.2) LIMIT ?""",
                        (expression, candidate_limit)).fetchall()
                if reference_packages:
                    # Package reference vocabulary adds package-level candidates
                    # that language-specific FTS may miss (e.g. Japanese wording).
                    marks = ",".join("?" for _ in reference_packages)
                    rows += connection.execute(f"""SELECT d.kind,d.package_id,d.status,d.title,
                        d.source_path,d.source_sha256,d.aliases,'',0.0
                        FROM documents d WHERE d.kind='package' AND d.package_id IN ({marks})""",
                        reference_packages).fetchall()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise InvalidInput("docs_index_query", f"Docs index query failed: {exc}") from exc
        fields = ("kind", "package", "status", "title", "source_path",
                  "source_sha256", "aliases", "snippet", "fts_rank")
        scored: list[dict[str, Any]] = []
        for row in rows:
            result = dict(zip(fields, row))
            lexical, shared = lexical_score(
                parsed,
                f"{result['title']} {result['package'] or ''} {result['aliases'] or ''}",
                aliases=(str(result["title"]), str(result["package"] or "")))
            rank = abs(float(result.pop("fts_rank")))
            lexical += package_reference_score(parsed.normalized, str(result["package"] or ""))
            result["score"] = round(4.0 * lexical + 8.0 / (1.0 + rank), 6)
            result["matched_concepts"] = sorted(shared)
            result["scope"] = "reference"
            result["executable"] = False
            scored.append(result)
        scored.sort(key=lambda item: (-item["score"], item["package"] or "",
                                      item["kind"], item["title"], item["source_path"]))
        # Prevent a single package's many headers/examples from hiding other
        # relevant packages. One result per package is selected first, then a
        # second pass fills any remaining slots deterministically.
        results: list[dict[str, Any]] = []
        selected: set[int] = set()
        seen_packages: set[str] = set()
        for index, item in enumerate(scored):
            package = str(item["package"] or "")
            if package in seen_packages:
                continue
            results.append(item)
            selected.add(index)
            seen_packages.add(package)
            if len(results) == limit:
                break
        if len(results) < limit:
            for index, item in enumerate(scored):
                if index in selected:
                    continue
                results.append(item)
                if len(results) == limit:
                    break
        return {"query": query, "index_scope": "pinned_generated_catalog", "index_available": True,
                "index_backend": "sqlite-fts5-trigram", "catalog_version": metadata["catalog_version"],
                "cgal_version": metadata["cgal_version"],
                "results": results, "legacy_api_index_used": False}

    @classmethod
    def _collect_docs(cls, value: Any, source: str, terms: QueryTerms,
                      records: list[dict[str, Any]], prefix: str = "") -> None:
        if isinstance(value, dict):
            title = str(value.get("name") or value.get("id") or value.get("title") or prefix)
            package = str(value.get("package") or value.get("id") or "")
            score, shared = lexical_score(terms, f"{title} {package}",
                                          aliases=(title, package))
            if score and (not terms.concepts or shared):
                records.append({"title": title, "source": source, "score": score,
                                "package": package,
                                "references": value.get("sources") or value.get("docs") or [],
                                "matched_concepts": sorted(shared)})
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
                "concurrency": self.concurrency,
                "resources": {"concurrency": self.resources.concurrency,
                              "default_memory_mb": self.resources.default_memory_mb,
                              "max_memory_mb": self.resources.max_memory_mb,
                              "default_wall_time_ms": self.resources.default_wall_time_ms,
                              "max_wall_time_ms": self.resources.max_wall_time_ms},
                "max_import_bytes": 512 * 1024 * 1024}

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
                         allowed_file_roots=allowed_file_roots,
                         resource_config=ResourceConfig.from_environment())
