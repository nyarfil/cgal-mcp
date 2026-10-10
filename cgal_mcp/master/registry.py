"""Validated, editable Operation registry with deterministic hard gates."""

from __future__ import annotations

import copy
import json
import math
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .errors import InvalidInput, UnsupportedOperation
from .policies import PolicyRegistry
from .search import (DIRECT_VALIDATOR_CONTRACTS, METHOD_CONCEPTS, enriched_text,
                     document_terms, match_operation, parse_query, PhraseIndex, requested_parameter_features,
                     requested_parameter_values)
from .util import ID_RE, canonical_json


EXECUTABLE_STATUSES = {"IMPLEMENTED", "VALIDATED"}
# Discovery-only score penalty per uncovered query concept (see search()).
UNCOVERED_CONCEPT_PENALTY = 6.0
ALL_STATUSES = {"DISCOVERED", "CATALOGED", "ADAPTER_PLANNED", "IMPLEMENTED",
                "VALIDATED", "DEPRECATED", "BLOCKED", "EXCLUDED"}
LEGACY_STATUSES = {"blocked_by_dependency": "BLOCKED", "excluded_with_reason": "EXCLUDED"}
REQUIRED = {"id", "revision", "status", "summary", "aliases", "package", "sources",
            "license", "io", "parameters", "preconditions", "kernel", "validation"}


def _types_compatible(available: list[str], specifications: list[dict[str, Any]]) -> bool:
    if len(available) != len(specifications):
        return False
    def assign(index: int, remaining: list[str]) -> bool:
        if index == len(specifications):
            return not remaining
        accepted = specifications[index].get("types", [])
        for position, kind in enumerate(remaining):
            if kind in accepted and assign(index + 1, remaining[:position] + remaining[position + 1:]):
                return True
        return False
    return assign(0, list(available))


def _validate_json_schema(schema: Any, operation_id: str, location: str = "parameters") -> None:
    if not isinstance(schema, dict):
        raise InvalidInput("operation_parameters", f"{operation_id} {location} schema must be an object")
    kind = schema.get("type")
    if kind is not None and kind not in {"object", "array", "string", "number", "integer", "boolean",
                                         "TypedLength", "TypedAngle"}:
        raise InvalidInput("operation_parameters", f"Unsupported schema type for {operation_id} at {location}")
    if "required" in schema and (not isinstance(schema["required"], list)
            or not all(isinstance(item, str) for item in schema["required"])):
        raise InvalidInput("operation_parameters", f"Invalid required list for {operation_id} at {location}")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise InvalidInput("operation_parameters", f"Invalid properties for {operation_id} at {location}")
    for name, child in properties.items():
        if not isinstance(name, str):
            raise InvalidInput("operation_parameters", f"Non-string parameter name for {operation_id}")
        _validate_json_schema(child, operation_id, f"{location}.{name}")
    if "items" in schema:
        _validate_json_schema(schema["items"], operation_id, f"{location}[]")
    alternatives = schema.get("oneOf", [])
    if alternatives:
        if not isinstance(alternatives, list) or not alternatives:
            raise InvalidInput("operation_parameters", f"Invalid oneOf for {operation_id} at {location}")
        for index, alternative in enumerate(alternatives):
            _validate_json_schema(alternative, operation_id, f"{location}.oneOf[{index}]")


def _schema_properties(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = dict(schema.get("properties", {}))
    for alternative in schema.get("oneOf", []):
        for name, child in _schema_properties(alternative).items():
            existing = result.get(name)
            if existing is not None and existing.get("type") != child.get("type"):
                raise InvalidInput("operation_parameters",
                                   f"Conditional parameter {name} has inconsistent types")
            result[name] = child
    return result


def _schema_required_sets(schema: dict[str, Any]) -> list[set[str]]:
    alternatives = schema.get("oneOf", [])
    if alternatives:
        return [required for alternative in alternatives
                for required in _schema_required_sets(alternative)]
    return [set(schema.get("required", []))]


def _default_paths() -> list[Path]:
    configured = os.environ.get("CGAL_MASTER_OPERATIONS")
    if configured:
        return [Path(configured)]
    bundled = Path(__file__).with_name("operations.json")
    generated = Path("catalog/operations.json")
    return [bundled, generated] if generated.is_file() else [bundled]


class OperationRegistry:
    def __init__(self, paths: Path | Iterable[Path] | None = None, *,
                 policies: Path | None = None):
        if paths is None:
            selected = _default_paths()
        elif isinstance(paths, Path):
            selected = [paths]
        else:
            selected = list(paths)
        if not selected:
            raise InvalidInput("registry_empty", "At least one operation registry is required")
        self.paths = tuple(path.resolve() for path in selected)
        self.operations: dict[str, dict[str, Any]] = {}
        self.cgal_versions: set[str] = set()
        self.build_requirements: dict[str, str] = {}
        self.policy_registry = PolicyRegistry(policies)
        for path in self.paths:
            self._load(path)
        if self.cgal_versions and self.policy_registry.cgal_version not in self.cgal_versions:
            raise InvalidInput("policy_registry_version", "Policy and Operation CGAL versions disagree")
        if any(self.build_requirements.get(key) != value
               for key, value in self.policy_registry.build_requirements.items()):
            raise InvalidInput("policy_registry_build", "Policy and Operation build requirements disagree")
        self._validate_links()
        self.revision = __import__("hashlib").sha256(canonical_json({
            "operations": {key: self.operations[key] for key in sorted(self.operations)},
            "policy_revision": self.policy_registry.revision,
        })).hexdigest()
        self.search_phrases = self._load_search_phrases()
        self.phrase_index = PhraseIndex(self.search_phrases, {
            key: " ".join([operation["summary"], *operation.get("aliases", [])])
            for key, operation in self.operations.items()})
        self._search = sqlite3.connect(":memory:")
        self._build_index()

    def _load_search_phrases(self) -> dict[str, tuple[str, ...]]:
        """Load search-only phrases for registered operations (unknown IDs are ignored)."""
        path = Path(__file__).with_name("search_data.json")
        if not path.is_file():
            return {}
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            raw = document["operations"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise InvalidInput("search_data_read", f"Cannot load search data {path}: {exc}") from exc
        result: dict[str, tuple[str, ...]] = {}
        for key, value in raw.items():
            if not (isinstance(value, list) and all(isinstance(item, str) for item in value)):
                raise InvalidInput("search_data_schema", f"Invalid search phrases for {key}")
            if key in self.operations:
                result[key] = tuple(value)
        return result

    def _validate_links(self) -> None:
        for policy in self.policy_registry.policies.values():
            if policy["operation"] not in self.operations:
                raise InvalidInput("policy_operation", f"Policy references unknown operation {policy['operation']}")
        for operation_id in self.policy_registry.requirements:
            if operation_id not in self.operations:
                raise InvalidInput("policy_operation", f"Policy requirements reference unknown operation {operation_id}")
        for operation in self.operations.values():
            outputs_geometry = any(item.get("type") != "ValidationReport"
                                   for item in operation["io"]["outputs"])
            if operation.get("role", "transform") != "validator" and outputs_geometry:
                if not operation["validation"]["required"]:
                    raise InvalidInput("missing_validator", f"Geometry operation {operation['id']} must require validation")
            for validator_id in operation["validation"]["validators"]:
                validator = self.operations.get(validator_id)
                if validator is None or validator.get("role") != "validator":
                    raise InvalidInput("validator_reference", f"{operation['id']} references invalid validator {validator_id}")
                if any(item.get("type") != "ValidationReport" for item in validator["io"]["outputs"]):
                    raise InvalidInput("validator_reference", f"Validator {validator_id} has non-report output")
                recipe = operation["validation"]["bindings"].get(validator_id)
                validator_slots = {item["slot"]: item for item in validator["io"]["inputs"]}
                artifact_recipe = recipe.get("artifacts") if isinstance(recipe, dict) and "artifacts" in recipe else recipe
                if not isinstance(artifact_recipe, dict) or set(artifact_recipe) != set(validator_slots):
                    raise InvalidInput("validator_binding", f"{operation['id']} bindings do not cover {validator_id}")
                input_specs = {item["slot"]: item for item in operation["io"]["inputs"]}
                output_specs = {item["slot"]: item for item in operation["io"]["outputs"]}
                for slot, binding in artifact_recipe.items():
                    if not isinstance(binding, dict) or set(binding) not in ({"input"}, {"output"}):
                        raise InvalidInput("validator_binding", f"Invalid binding recipe for {operation['id']}:{slot}")
                    source = (output_specs.get(binding.get("output")) if "output" in binding
                              else input_specs.get(binding.get("input")))
                    if source is None:
                        raise InvalidInput("validator_binding", f"Unknown binding referent for {operation['id']}:{slot}")
                    source_types = [source["type"]] if "type" in source else source["types"]
                    if not any(kind in validator_slots[slot]["types"] for kind in source_types):
                        raise InvalidInput("validator_binding", f"Binding type mismatch for {operation['id']}:{slot}")
                    source_formats = [source["format"]] if "format" in source else source["formats"]
                    if not any(name in validator_slots[slot]["formats"] for name in source_formats):
                        raise InvalidInput("validator_binding", f"Binding format mismatch for {operation['id']}:{slot}")
                parameter_recipe = recipe.get("parameters", {}) if isinstance(recipe, dict) and "artifacts" in recipe else {}
                if not isinstance(parameter_recipe, dict):
                    raise InvalidInput("validator_binding", f"Invalid parameter bindings for {operation['id']}:{validator_id}")
                source_parameters = _schema_properties(operation["parameters"])
                validator_parameters = _schema_properties(validator["parameters"])
                required_sets = _schema_required_sets(validator["parameters"])
                if not any(required.issubset(parameter_recipe) for required in required_sets):
                    raise InvalidInput("validator_binding", f"Parameter bindings do not cover required parameters for {validator_id}")
                for target, binding in parameter_recipe.items():
                    source_name = binding.get("parameter") if isinstance(binding, dict) else None
                    if target not in validator_parameters or source_name not in source_parameters:
                        raise InvalidInput("validator_binding", f"Unknown parameter binding for {operation['id']}:{target}")
                    if set(binding) - {"parameter", "optional"} or (
                            "optional" in binding and type(binding["optional"]) is not bool):
                        raise InvalidInput("validator_binding", f"Invalid parameter binding for {operation['id']}:{target}")
                    if validator_parameters[target].get("type") != source_parameters[source_name].get("type"):
                        raise InvalidInput("validator_binding", f"Parameter binding type mismatch for {operation['id']}:{target}")

    def close(self) -> None:
        self._search.close()

    def _load(self, path: Path) -> None:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput("registry_read", f"Cannot load operation registry {path}: {exc}") from exc
        if isinstance(document, list):
            operations = document
        elif isinstance(document, dict):
            if document.get("schema_version", 1) != 1:
                raise InvalidInput("registry_schema", f"Unsupported registry schema in {path}")
            if document.get("cgal_version"):
                self.cgal_versions.add(str(document["cgal_version"]))
            requirements = document.get("build_requirements", {})
            if requirements:
                if not isinstance(requirements, dict) or any(not isinstance(value, str) for value in requirements.values()):
                    raise InvalidInput("registry_build", f"Invalid build requirements in {path}")
                for key, value in requirements.items():
                    if key in self.build_requirements and self.build_requirements[key] != value:
                        raise InvalidInput("registry_build", f"Conflicting build requirement {key}")
                    self.build_requirements[key] = value
            operations = document.get("operations")
        else:
            operations = None
        if not isinstance(operations, list):
            raise InvalidInput("registry_schema", f"Registry {path} has no operations array")
        for value in operations:
            operation = self._validate_operation(value, path)
            existing = self.operations.get(operation["id"])
            if existing and existing["revision"] == operation["revision"] and existing != operation:
                raise InvalidInput("registry_conflict", f"Conflicting definition: {operation['id']}")
            if existing is None or operation["revision"] >= existing["revision"]:
                self.operations[operation["id"]] = operation

    @staticmethod
    def _validate_operation(value: Any, path: Path) -> dict[str, Any]:
        if not isinstance(value, dict) or REQUIRED - value.keys():
            missing = sorted(REQUIRED - value.keys()) if isinstance(value, dict) else sorted(REQUIRED)
            raise InvalidInput("operation_schema", f"Operation in {path} lacks: {', '.join(missing)}")
        operation = copy.deepcopy(value)
        if not isinstance(operation["id"], str) or not ID_RE.fullmatch(operation["id"]):
            raise InvalidInput("operation_id", f"Invalid operation id: {operation.get('id')}")
        if type(operation["revision"]) is not int or operation["revision"] < 1:
            raise InvalidInput("operation_revision", f"Invalid revision for {operation['id']}")
        raw_status = str(operation["status"])
        operation["status"] = LEGACY_STATUSES.get(raw_status.lower(), raw_status.upper())
        if operation["status"] not in ALL_STATUSES:
            raise InvalidInput("operation_status", f"Invalid status for {operation['id']}")
        if operation.get("role", "transform") not in {"transform", "analysis", "validator"}:
            raise InvalidInput("operation_role", f"Invalid role for {operation['id']}")
        if operation["status"] == "VALIDATED":
            evidence = operation.get("evidence")
            if not isinstance(evidence, dict) or not isinstance(evidence.get("tests"), list) or not evidence["tests"]:
                raise InvalidInput("operation_evidence", f"VALIDATED operation lacks test evidence: {operation['id']}")
        if not isinstance(operation["aliases"], list) or not all(isinstance(x, str) for x in operation["aliases"]):
            raise InvalidInput("operation_aliases", f"Invalid aliases for {operation['id']}")
        if not isinstance(operation["summary"], str) or not operation["summary"].strip() or not isinstance(operation["package"], str):
            raise InvalidInput("operation_metadata", f"Invalid summary/package for {operation['id']}")
        sources = operation["sources"]
        if (not isinstance(sources, list) or not sources
                or not all(isinstance(item, dict) and isinstance(item.get("kind"), str)
                           and isinstance(item.get("identifier"), str) for item in sources)):
            raise InvalidInput("operation_sources", f"Invalid sources for {operation['id']}")
        io = operation["io"]
        if not isinstance(io, dict) or not isinstance(io.get("inputs"), list) or not isinstance(io.get("outputs"), list):
            raise InvalidInput("operation_io", f"Invalid I/O for {operation['id']}")
        slots: set[str] = set()
        for input_spec in io["inputs"]:
            if not isinstance(input_spec, dict) or not isinstance(input_spec.get("slot"), str):
                raise InvalidInput("operation_io", f"Invalid input slot for {operation['id']}")
            if input_spec["slot"] in slots or not isinstance(input_spec.get("types"), list):
                raise InvalidInput("operation_io", f"Duplicate/invalid input slot for {operation['id']}")
            if not input_spec["types"] or not all(isinstance(item, str) for item in input_spec["types"]):
                raise InvalidInput("operation_io", f"Invalid input types for {operation['id']}")
            if (not isinstance(input_spec.get("formats"), list) or not input_spec["formats"]
                    or not all(isinstance(item, str) for item in input_spec["formats"])):
                raise InvalidInput("operation_io", f"Invalid input formats for {operation['id']}")
            slots.add(input_spec["slot"])
        output_slots: set[str] = set()
        for output_spec in io["outputs"]:
            if (not isinstance(output_spec, dict) or not isinstance(output_spec.get("slot"), str)
                    or output_spec["slot"] in output_slots or not isinstance(output_spec.get("type"), str)
                    or not isinstance(output_spec.get("format"), str)):
                raise InvalidInput("operation_io", f"Invalid/duplicate output for {operation['id']}")
            if output_spec.get("unit_from") is not None and output_spec["unit_from"] not in slots:
                raise InvalidInput("operation_io", f"Output unit source is invalid for {operation['id']}")
            if output_spec.get("unit") is None and output_spec.get("unit_from") is None:
                raise InvalidInput("operation_io", f"Output unit policy is missing for {operation['id']}")
            output_slots.add(output_spec["slot"])
        if not output_slots:
            raise InvalidInput("operation_io", f"Operation {operation['id']} has no outputs")
        _validate_json_schema(operation["parameters"], operation["id"])
        if operation["parameters"].get("type") != "object":
            raise InvalidInput("operation_parameters", f"Parameters schema must be object for {operation['id']}")
        def valid_precondition(item: Any) -> bool:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                return False
            if item.get("id") == "bounded_input":
                allowed = {"id", "maximum_bytes", "maximum_vertices",
                           "maximum_faces", "maximum_face_degree"}
                return (not (set(item) - allowed)
                        and any(key in item for key in allowed - {"id"})
                        and all(type(value) is int and value > 0
                                for key, value in item.items() if key != "id"))
            if isinstance(item.get("property"), str) and ("equals" in item or "minimum" in item):
                return True
            if isinstance(item.get("worker_check"), dict):
                return True
            bounds = item.get("bounds")
            return (isinstance(bounds, dict)
                    and set(bounds) == {"minimum_span", "maximum_absolute_coordinate",
                                        "maximum_translation_to_span_ratio"}
                    and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                            and math.isfinite(float(value)) and value > 0
                            for value in bounds.values()))
        if (not isinstance(operation["preconditions"], list)
                or not all(valid_precondition(item) for item in operation["preconditions"])):
            raise InvalidInput("operation_preconditions", f"Invalid preconditions for {operation['id']}")
        parameter_preconditions = operation.get("parameter_preconditions", [])
        if (not isinstance(parameter_preconditions, list)
                or not all(isinstance(item, dict)
                           and isinstance(item.get("parameter"), str)
                           and isinstance(item.get("input"), str)
                           and item["input"] in slots
                           and ((isinstance(item.get("less_than_metadata"), str)
                                 and "finite_coordinate_ratio_metadata" not in item)
                                or (isinstance(item.get("finite_coordinate_ratio_metadata"), str)
                                    and "less_than_metadata" not in item))
                           for item in parameter_preconditions)):
            raise InvalidInput("operation_preconditions",
                               f"Invalid parameter preconditions for {operation['id']}")
        resource_profile = operation.get("resource_profile", {})
        if (not isinstance(resource_profile, dict)
                or set(resource_profile) - {"default_wall_time_ms"}
                or ("default_wall_time_ms" in resource_profile
                    and (type(resource_profile["default_wall_time_ms"]) is not int
                         or not 1 <= resource_profile["default_wall_time_ms"] <= 86_400_000))):
            raise InvalidInput("operation_resources", f"Invalid resource profile for {operation['id']}")
        kernel = operation["kernel"]
        if (not isinstance(kernel, dict) or not isinstance(kernel.get("supported"), list)
                or kernel.get("default") not in kernel.get("supported", [])):
            raise InvalidInput("operation_kernel", f"Invalid kernel policy for {operation['id']}")
        validation = operation["validation"]
        if (not isinstance(validation, dict) or type(validation.get("required")) is not bool
                or not isinstance(validation.get("validators"), list)
                or not all(isinstance(item, str) for item in validation.get("validators", []))
                or len(set(validation.get("validators", []))) != len(validation.get("validators", []))):
            raise InvalidInput("operation_validation", f"Invalid validation policy for {operation['id']}")
        bindings = validation.get("bindings", {})
        if validation["required"] and (not isinstance(bindings, dict)
                or any(validator not in bindings for validator in validation["validators"])):
            raise InvalidInput("operation_validation", f"Validator bindings are incomplete for {operation['id']}")
        required_checks = validation.get("required_report_checks", {})
        required_fields = validation.get("required_report_fields", [])
        required_minimum = validation.get("required_report_minimum", {})
        if (not isinstance(required_checks, dict)
                or not isinstance(required_fields, list)
                or not all(isinstance(item, str) for item in required_fields)
                or not isinstance(required_minimum, dict)
                or not all(isinstance(key, str)
                           and isinstance(value, (int, float)) and not isinstance(value, bool)
                           for key, value in required_minimum.items())):
            raise InvalidInput("operation_validation", f"Invalid report contract for {operation['id']}")
        license_metadata = operation["license"]
        if (not isinstance(license_metadata, dict)
                or not isinstance(license_metadata.get("expression"), str)
                or not isinstance(license_metadata.get("package"), str)
                or not isinstance(license_metadata.get("evidence"), list)
                or not license_metadata["evidence"]):
            raise InvalidInput("operation_license", f"License evidence is incomplete for {operation['id']}")
        if not all(isinstance(item, dict) and isinstance(item.get("path"), str)
                   and isinstance(item.get("sha256"), str) for item in license_metadata["evidence"]):
            raise InvalidInput("operation_license", f"License evidence is invalid for {operation['id']}")
        return operation

    def policies_for(self, operation_id: str) -> list[dict[str, Any]]:
        self.get(operation_id)
        return self.policy_registry.for_operation(operation_id)

    def resolve_policies(self, operation_id: str,
                         parameters: dict[str, Any]) -> list[dict[str, Any]]:
        self.get(operation_id)
        return self.policy_registry.resolve(operation_id, parameters)

    def _build_index(self) -> None:
        try:
            self._search.execute("CREATE VIRTUAL TABLE operation_fts USING fts5(id UNINDEXED, text, tokenize='trigram')")
            self._search.execute("CREATE VIRTUAL TABLE operation_fts_discovery USING fts5(id UNINDEXED, text, tokenize='trigram')")
            self.search_mode = "fts5-trigram"
        except sqlite3.OperationalError:
            self._search.execute("CREATE VIRTUAL TABLE operation_fts USING fts5(id UNINDEXED, text)")
            self._search.execute("CREATE VIRTUAL TABLE operation_fts_discovery USING fts5(id UNINDEXED, text)")
            self.search_mode = "fts5-unicode61"
        for operation in self.operations.values():
            phrases = self.search_phrases.get(operation["id"], ())
            for table, extra in (("operation_fts", ()), ("operation_fts_discovery", phrases)):
                search_text = enriched_text(" ".join([
                    operation["id"], operation["summary"], operation["package"],
                    *operation.get("aliases", []), *extra,
                    *operation.get("dependencies", []),
                    *(item.get("identifier", "") for item in operation.get("sources", [])),
                    *(kind for spec in operation["io"]["inputs"] for kind in spec.get("types", [])),
                    *(spec.get("type", "") for spec in operation["io"]["outputs"]),
                ]))
                self._search.execute(f"INSERT INTO {table}(id,text) VALUES(?,?)",
                                     (operation["id"], search_text))
        self._search.commit()

    def get(self, operation_id: str, executable: bool = False) -> dict[str, Any]:
        operation = self.operations.get(operation_id)
        if operation is None:
            raise UnsupportedOperation(operation_id)
        if executable and operation["status"] not in EXECUTABLE_STATUSES:
            raise UnsupportedOperation(operation_id)
        return copy.deepcopy(operation)

    def search(self, query: str, *, input_types: list[str] | None = None,
               status: list[str] | None = None, dependencies: list[str] | None = None,
               kernel: str | None = None, allowed_licenses: list[str] | None = None,
               limit: int = 8, discovery: bool = False) -> dict[str, Any]:
        """Rank registered operations for ``query``.

        ``discovery`` (capabilities_search, never planning) adds the authored
        search phrases as evidence and ranks an operation whose only blocker is
        an uncovered concept by score minus a penalty instead of sinking it below
        every covered operation: a user's incidental word (``sample points`` of
        data, an ``area`` limit) must not hide the operation that otherwise
        matches the whole request.  Planning keeps the conservative evidence, so
        ``plan(goal=...)`` routing is unchanged by search phrases.
        """
        if not isinstance(query, str) or not query.strip():
            raise InvalidInput("search_query", "Search query must not be empty")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise InvalidInput("search_limit", "Search limit must be between 1 and 100")
        parsed = parse_query(query)
        candidates: list[tuple[bool, float, dict[str, Any], list[str], Any,
                               dict[str, Any], dict[str, list[Any]],
                               dict[str, str]]] = []
        blocked_soft: dict[str, bool] = {}
        fts_scores: dict[str, float] = {}
        fts_terms = list(parsed.words)
        for concept in sorted(parsed.concepts):
            fts_terms.append(concept.replace("_", " "))
        table = "operation_fts_discovery" if discovery else "operation_fts"
        if fts_terms:
            expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in fts_terms)
            try:
                for operation_id, rank in self._search.execute(
                        f"SELECT id,bm25({table}) FROM {table} WHERE text MATCH ?",
                        (expression,)).fetchall():
                    fts_scores[operation_id] = 8.0 / (1.0 + abs(float(rank)))
            except sqlite3.OperationalError:
                fts_scores = {}
        available_dependencies = set(dependencies or [])
        normalized_status = ({LEGACY_STATUSES.get(item.lower(), item.upper()) for item in status}
                             if status else None)
        for operation in self.operations.values():
            reasons: list[str] = []
            if normalized_status and operation["status"] not in normalized_status:
                continue
            input_specs = operation["io"]["inputs"]
            accepted_types = {kind for spec in input_specs for kind in spec.get("types", [])}
            if input_types and not _types_compatible(input_types, input_specs):
                continue
            if input_types:
                reasons.append("input type hard gate passed")
            required_dependencies = set(operation.get("dependencies", [operation["package"]]))
            if dependencies is not None and not required_dependencies.issubset(available_dependencies):
                continue
            if kernel and kernel not in operation["kernel"]["supported"]:
                continue
            expression = operation["license"].get("expression") or operation["license"].get("spdx")
            if allowed_licenses is not None and expression not in allowed_licenses:
                continue
            aliases = tuple(operation.get("aliases", []))
            schema_parameters = _schema_properties(operation["parameters"])
            # Planar artifact types (PointSet2, Polygon2, ...) make the operation 2D.
            dimension_tag = ["2d"] if any(re.fullmatch(r"[A-Za-z]+2", kind)
                                          for kind in accepted_types) else []
            primary_text = " ".join([*dimension_tag,
                operation["id"], operation["summary"], operation["package"],
                *aliases, *schema_parameters,
            ])
            phrases = self.search_phrases.get(operation["id"], ()) if discovery else ()
            phrase_bonus = self.phrase_index.bonus(
                operation["id"], query, parsed.bridge_words) if phrases else 0.0
            evidence = match_operation(parsed, primary_text, aliases=aliases,
                                       phrases=phrases, phrase_bonus=phrase_bonus)
            fts_score = fts_scores.get(operation["id"], 0.0)
            score = evidence.score + fts_score
            # A concept named by the Operation ID itself is its primary identity;
            # an incidental mention in the summary must not tie with it.
            score += 6.0 * len(evidence.covered_primary_concepts
                               & document_terms(operation["id"]).concepts)
            if fts_score:
                reasons.append("FTS5 registry index matched")
            if score <= 0:
                continue
            if evidence.covered_primary_concepts:
                reasons.append("registered metadata covers: " + ", ".join(
                    sorted(evidence.covered_primary_concepts)))
            if evidence.uncovered_primary_concepts:
                reasons.append("registered metadata does not cover: " + ", ".join(
                    sorted(evidence.uncovered_primary_concepts)))
            if evidence.word_matches or evidence.alias_matches:
                reasons.append("registry alias/text matched")
            route_supported = evidence.route_supported
            concept_supported = route_supported
            if operation.get("role", "transform") == "validator" and "validation" not in parsed.concepts:
                direct_contract = any(
                    concept in evidence.covered_primary_concepts
                    and required.issubset(schema_parameters)
                    for concept, required in DIRECT_VALIDATOR_CONTRACTS.items()
                    if concept in parsed.concepts)
                if direct_contract:
                    reasons.append("registered validator exposes a complete direct measurement contract")
                else:
                    route_supported = False
                    reasons.append("validator requires explicit validation intent")
            required_parameters: dict[str, Any] = {}
            parameter_conflicts: dict[str, list[Any]] = {}
            for parameter, values in requested_parameter_values(parsed.concepts).items():
                if parameter not in schema_parameters:
                    continue
                if len(values) == 1:
                    required_parameters[parameter] = next(iter(values))
                else:
                    parameter_conflicts[parameter] = sorted(values)
            if parameter_conflicts:
                route_supported = False
                reasons.append("query requests conflicting parameter values")
            required_features = {
                parameter: requirement
                for parameter, requirement in requested_parameter_features(
                    parsed.concepts).items()
                if parameter in schema_parameters
            }
            if operation["status"] in EXECUTABLE_STATUSES:
                score += 1.0
                reasons.append("registered adapter available")
            candidates.append((route_supported, score, operation,
                               reasons, evidence, required_parameters,
                               parameter_conflicts, required_features))
            soft_blocked = not route_supported and not concept_supported
            blocked_soft[operation["id"]] = soft_blocked
        if discovery:
            def discovery_key(item: Any) -> tuple[Any, ...]:
                hard = not item[0] and not blocked_soft.get(item[2]["id"], False)
                penalty = (UNCOVERED_CONCEPT_PENALTY * len(item[4].uncovered_primary_concepts)
                           if blocked_soft.get(item[2]["id"], False) else 0.0)
                return (hard, -(item[1] - penalty), item[2]["id"])
            candidates.sort(key=discovery_key)
        else:
            candidates.sort(key=lambda item: (not item[0], -item[1], item[2]["id"]))
        safe = [item for item in candidates if item[0]]
        route_confidence = "none"
        recommended: str | None = None
        recommended_parameters: dict[str, Any] = {}
        recommended_features: dict[str, str] = {}
        if safe:
            gap = math.inf if len(safe) == 1 else safe[0][1] - safe[1][1]
            if safe[0][4].confidence == "high" and gap > 2.0:
                route_confidence = "high"
                recommended = safe[0][2]["id"]
                recommended_parameters = safe[0][5]
                recommended_features = safe[0][7]
            else:
                route_confidence = "ambiguous" if gap <= 2.0 else safe[0][4].confidence
        primary = sorted(parsed.concepts)
        return {"query": query, "search_mode": self.search_mode, "candidates": [
            {"operation_id": operation["id"], "revision": operation["revision"],
             "status": operation["status"], "score": score, "why": reasons,
             "route_supported": route_supported,
             "confidence": evidence.confidence if route_supported else "low",
             "covered_primary_concepts": sorted(evidence.covered_primary_concepts),
             "uncovered_primary_concepts": sorted(evidence.uncovered_primary_concepts),
             "covered_method_concepts": sorted(evidence.covered_method_concepts),
             "uncovered_method_concepts": sorted(evidence.uncovered_method_concepts),
             "required_parameters": required_parameters,
             "required_parameter_features": required_features,
             "parameter_conflicts": parameter_conflicts,
             "input_types": [kind for spec in operation["io"]["inputs"] for kind in spec.get("types", [])],
             "output_types": [spec.get("type") for spec in operation["io"]["outputs"]]}
            for (route_supported, score, operation, reasons, evidence,
                 required_parameters, parameter_conflicts,
                 required_features) in candidates[:limit]
        ], "query_analysis": {
            "normalized": parsed.normalized,
            "primary_concepts": primary,
            "requested_method_concepts": sorted(parsed.concepts & METHOD_CONCEPTS),
            "routing_confidence": route_confidence,
            "recommended_operation": recommended,
            "required_parameters": recommended_parameters,
            "required_parameter_features": recommended_features,
            "automatic_route_supported": recommended is not None,
        }}

    def verify_manifest(self, manifest: dict[str, Any], required_operation: str) -> dict[str, Any]:
        if manifest.get("protocol") != 1 or not isinstance(manifest.get("operations"), list):
            raise InvalidInput("manifest_protocol", "Worker manifest protocol/operations are invalid")
        declared = {item.get("id"): item for item in manifest["operations"] if isinstance(item, dict)}
        expected = self.get(required_operation, executable=True)
        actual = declared.get(required_operation)
        if actual is None:
            raise InvalidInput("manifest_missing_operation", f"Worker lacks {required_operation}")
        expected_inputs = [kind for spec in expected["io"]["inputs"] for kind in spec["types"]]
        expected_output = expected["io"]["outputs"][0]["type"]
        if (actual.get("revision") != expected["revision"]
                or actual.get("input_types") != expected_inputs
                or actual.get("output_type") != expected_output):
            raise InvalidInput("manifest_registry_mismatch", f"Worker manifest disagrees with registry for {required_operation}")
        actual_version = manifest.get("actual_cgal_version") or manifest.get("build", {}).get("actual_cgal_version")
        if self.cgal_versions and actual_version not in self.cgal_versions:
            raise InvalidInput("manifest_cgal_version", f"Worker CGAL version {actual_version!r} does not match registry")
        build = manifest.get("build", {})
        for key, value in self.build_requirements.items():
            if build.get(key) != value:
                raise InvalidInput("manifest_build_mismatch", f"Worker build {key} disagrees with registry")
        if not set(expected["kernel"]["supported"]).issubset(set(actual.get("supported_kernels", []))):
            raise InvalidInput("manifest_kernel_mismatch", f"Worker kernels disagree with registry for {required_operation}")
        if actual.get("role") != expected.get("role", "transform"):
            raise InvalidInput("manifest_role_mismatch", f"Worker role disagrees with registry for {required_operation}")
        manifest_contract = expected.get("worker_manifest", {})
        if manifest_contract.get("require_dependencies"):
            if set(actual.get("dependencies", [])) != set(expected.get("dependencies", [])):
                raise InvalidInput("manifest_dependency_mismatch", f"Worker dependencies disagree with registry for {required_operation}")
        effective_kernel = manifest_contract.get("effective_kernel")
        if effective_kernel and actual.get("effective_kernel") != effective_kernel:
            raise InvalidInput("manifest_kernel_mismatch", f"Worker effective kernel disagrees with registry for {required_operation}")
        expected_info = manifest_contract.get("info", {})
        actual_info = actual.get("info", {})
        if any(actual_info.get(key) != value for key, value in expected_info.items()):
            raise InvalidInput("manifest_metadata_mismatch", f"Worker metadata disagrees with registry for {required_operation}")
        parameter_bindings = {}
        for validator, recipe in expected["validation"].get("bindings", {}).items():
            if isinstance(recipe, dict) and isinstance(recipe.get("parameters"), dict):
                parameter_bindings[validator] = {
                    target: binding["parameter"] for target, binding in recipe["parameters"].items()}
        if parameter_bindings and actual_info.get("validator_parameter_bindings") != parameter_bindings:
            raise InvalidInput("manifest_binding_mismatch", f"Worker validator bindings disagree with registry for {required_operation}")
        return copy.deepcopy(manifest)
