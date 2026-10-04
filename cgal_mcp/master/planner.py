"""Typed immutable DAG planner with mandatory validator insertion."""

from __future__ import annotations

from collections import deque
import copy
import math
from typing import Any

from .errors import InvalidInput, PreconditionFailure, UnsupportedOperation
from .registry import OperationRegistry
from .store import ArtifactStore
from .util import canonical_json, digest_bytes


def _validate_value(schema: dict[str, Any], value: Any, path: str) -> None:
    if "const" in schema and value != schema["const"]:
        raise InvalidInput("parameter_const", f"{path} has an invalid discriminator")
    if schema.get("oneOf"):
        matches = 0
        last_error: InvalidInput | None = None
        for alternative in schema["oneOf"]:
            try:
                _validate_value(alternative, value, path)
                matches += 1
            except InvalidInput as exc:
                last_error = exc
        if matches != 1:
            raise InvalidInput("parameter_one_of",
                               f"{path} must match exactly one allowed shape") from last_error
        return
    kind = schema.get("type")
    if kind == "TypedLength":
        if (not isinstance(value, dict) or set(value) != {"value", "unit"}
                or not isinstance(value["value"], (int, float)) or isinstance(value["value"], bool)
                or not math.isfinite(float(value["value"]))
                or value["unit"] not in {"mm", "cm", "m"}):
            raise InvalidInput("parameter_length", f"{path} must be a normalized TypedLength")
        number = float(value["value"])
        if "minimum" in schema and number < schema["minimum"]:
            raise InvalidInput("parameter_range", f"{path} is below its minimum")
        if "exclusiveMinimum" in schema and number <= schema["exclusiveMinimum"]:
            raise InvalidInput("parameter_range", f"{path} must exceed its minimum")
        return
    valid_type = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "integer": lambda item: type(item) is int,
        "boolean": lambda item: type(item) is bool,
    }.get(kind)
    if valid_type and not valid_type(value):
        raise InvalidInput("parameter_type", f"{path} must be {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise InvalidInput("parameter_enum", f"{path} is outside its enum")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise InvalidInput("parameter_finite", f"{path} must be finite")
        if "minimum" in schema and value < schema["minimum"]:
            raise InvalidInput("parameter_range", f"{path} is below its minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise InvalidInput("parameter_range", f"{path} is above its maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise InvalidInput("parameter_range", f"{path} must exceed its minimum")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            raise InvalidInput("parameter_range", f"{path} must be below its maximum")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            raise InvalidInput("parameter_length", f"{path} has invalid item count")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                _validate_value(schema["items"], item, f"{path}[{index}]")
    if not isinstance(value, dict):
        return
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    missing = required - value.keys()
    if missing:
        raise InvalidInput("parameters_required", f"{path} lacks: {', '.join(sorted(missing))}")
    if schema.get("additionalProperties") is False:
        unknown = value.keys() - properties.keys()
        if unknown:
            raise InvalidInput("parameters_unknown", f"Unknown parameters: {', '.join(sorted(unknown))}")
    for name, item in value.items():
        _validate_value(properties.get(name, {}), item, f"{path}.{name}")


def _validate_parameters(schema: dict[str, Any], value: dict[str, Any]) -> None:
    _validate_value(schema, value, "parameters")


def _schema_alternative(schema: dict[str, Any], value: Any) -> dict[str, Any]:
    alternatives = schema.get("oneOf", [])
    for alternative in alternatives:
        try:
            # Discriminators and the raw container shape are sufficient to
            # select a branch before TypedLength normalization.
            if isinstance(value, dict):
                properties = alternative.get("properties", {})
                if all("const" not in child or value.get(name) == child["const"]
                       for name, child in properties.items()):
                    return alternative
        except (AttributeError, TypeError):
            continue
    raise InvalidInput("parameter_one_of", "Parameter does not select an allowed shape")


def _apply_defaults(schema: dict[str, Any], value: Any) -> Any:
    if schema.get("oneOf"):
        return _apply_defaults(_schema_alternative(schema, value), value)
    if schema.get("type") == "object" and isinstance(value, dict):
        result = copy.deepcopy(value)
        for name, child in schema.get("properties", {}).items():
            if name not in result and "default" in child:
                result[name] = copy.deepcopy(child["default"])
            if name in result:
                result[name] = _apply_defaults(child, result[name])
        return result
    if schema.get("type") == "array" and isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [_apply_defaults(schema["items"], item) for item in value]
    return copy.deepcopy(value)


def _normalize_parameter_value(schema: dict[str, Any], value: Any, input_unit: str,
                               path: str, history: list[dict[str, Any]]) -> Any:
    if schema.get("oneOf"):
        return _normalize_parameter_value(_schema_alternative(schema, value), value,
                                          input_unit, path, history)
    if schema.get("type") == "TypedLength":
        if (not isinstance(value, dict) or set(value) != {"value", "unit"}
                or not isinstance(value.get("value"), (int, float))
                or isinstance(value.get("value"), bool)
                or not math.isfinite(float(value["value"]))):
            raise InvalidInput("parameter_length", "TypedLength requires only finite value and unit")
        source_unit = value.get("unit")
        scales = {"mm": 1.0, "cm": 10.0, "m": 1000.0}
        if source_unit not in scales or input_unit not in scales:
            raise InvalidInput("parameter_unit", "TypedLength requires mm, cm or m")
        source_value = float(value["value"])
        factor = scales[source_unit] / scales[input_unit]
        target_value = source_value * factor
        if not math.isfinite(target_value):
            raise InvalidInput("parameter_unit_overflow",
                               "TypedLength conversion produced a non-finite value")
        history.append({"path": path, "dimension": "length",
                        "source": {"value": source_value, "unit": source_unit},
                        "target": {"value": target_value, "unit": input_unit},
                        "factor": factor})
        return {"value": target_value, "unit": input_unit}
    if schema.get("type") == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        return {name: _normalize_parameter_value(properties.get(name, {}), item, input_unit,
                                                  f"{path}.{name}" if path else name, history)
                for name, item in value.items()}
    if schema.get("type") == "array" and isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [_normalize_parameter_value(schema["items"], item, input_unit,
                                           f"{path}[{index}]", history)
                for index, item in enumerate(value)]
    return copy.deepcopy(value)


def _prepare_parameters(schema: dict[str, Any], value: Any,
                        input_unit: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(value, dict):
        raise InvalidInput("parameter_type", "parameters must be object")
    defaulted = _apply_defaults(schema, value)
    history: list[dict[str, Any]] = []
    normalized = _normalize_parameter_value(schema, defaulted, input_unit, "", history)
    _validate_parameters(schema, normalized)
    return normalized, history


def _acyclic(steps: list[dict[str, Any]]) -> None:
    identifiers = {step["id"] for step in steps}
    if len(identifiers) != len(steps):
        raise InvalidInput("duplicate_step", "Plan step identifiers must be unique")
    outgoing: dict[str, list[str]] = {identifier: [] for identifier in identifiers}
    indegree = {identifier: 0 for identifier in identifiers}
    for step in steps:
        for binding in step["inputs"].values():
            if "step" in binding:
                source = binding["step"]
                if source not in identifiers:
                    raise InvalidInput("unknown_step_reference", f"Step {step['id']} references {source}")
                outgoing[source].append(step["id"])
                indegree[step["id"]] += 1
    queue = deque(identifier for identifier, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        source = queue.popleft(); visited += 1
        for target in outgoing[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(steps):
        raise InvalidInput("cyclic_plan", "Plan dependency graph contains a cycle")


class PlanBuilder:
    def __init__(self, registry: OperationRegistry, store: ArtifactStore):
        self.registry = registry
        self.store = store

    def build(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise InvalidInput("plan_request", "Plan request must be an object")
        if "steps" in request:
            steps = self._explicit_steps(request["steps"])
            route = {"mode": "explicit_dag"}
        else:
            operation_id, route = self._select_operation(request)
            bindings = request.get("inputs", request.get("artifacts"))
            steps = [self._make_step("s1", operation_id, bindings, request.get("parameters", {}),
                                     request.get("policy", {}).get("kernel"))]
            steps = self._inject_validators(steps)
        policy = request.get("policy", {})
        if not isinstance(policy, dict):
            raise InvalidInput("plan_policy", "Plan policy must be an object")
        for step in steps:
            self._policy_gate(self.registry.get(step["operation"]), policy)
        _acyclic(steps)
        body = {"schema_version": 1, "registry_revision": self.registry.revision,
                "steps": steps, "route": route, "policy": request.get("policy", {}),
                "immutable": True}
        plan_id = "plan_" + digest_bytes(canonical_json(body))
        return self.store.persist_plan({"plan_id": plan_id, **body})

    def _select_operation(self, request: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if isinstance(request.get("operation_id"), str):
            operation_id = request["operation_id"]
            operation = self.registry.get(operation_id, executable=True)
            self._policy_gate(operation, request.get("policy", {}))
            return operation_id, {"mode": "explicit", "selected": operation_id,
                                  "why": ["caller selected a registered executable operation"]}
        goal = request.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise InvalidInput("plan_operation", "operation_id or non-empty goal is required")
        artifacts = self._artifact_list(request.get("inputs", request.get("artifacts")))
        input_types = [self.store.inspect(artifact_id)["type"] for artifact_id in artifacts]
        policy = request.get("policy", {})
        result = self.registry.search(goal, input_types=input_types,
            status=["IMPLEMENTED", "VALIDATED"], dependencies=policy.get("dependencies"),
            kernel=policy.get("kernel"), allowed_licenses=policy.get("allowed_licenses"), limit=5)
        candidates = result["candidates"]
        if not candidates:
            raise UnsupportedOperation(goal)
        if len(candidates) > 1 and candidates[0]["score"] <= candidates[1]["score"]:
            raise InvalidInput("ambiguous_route", "Goal matches multiple operations equally; provide operation_id")
        selected = candidates[0]["operation_id"]
        return selected, {"mode": "registry_route", "selected": selected,
                          "why": candidates[0]["why"], "candidates": candidates}

    @staticmethod
    def _policy_gate(operation: dict[str, Any], policy: Any) -> None:
        if not isinstance(policy, dict):
            raise InvalidInput("plan_policy", "Plan policy must be an object")
        kernel = policy.get("kernel")
        if kernel is not None and not isinstance(kernel, str):
            raise InvalidInput("plan_policy", "Policy kernel must be a string")
        if kernel and kernel not in operation["kernel"]["supported"]:
            raise InvalidInput("kernel_unsupported", f"Unsupported kernel for {operation['id']}")
        if policy.get("dependencies") is not None:
            if (not isinstance(policy["dependencies"], list)
                    or not all(isinstance(item, str) for item in policy["dependencies"])):
                raise InvalidInput("plan_policy", "Policy dependencies must be a string array")
            required = set(operation.get("dependencies", [operation["package"]]))
            if not required.issubset(set(policy["dependencies"])):
                raise PreconditionFailure(f"Dependencies are unavailable for {operation['id']}")
        if policy.get("allowed_licenses") is not None:
            if (not isinstance(policy["allowed_licenses"], list)
                    or not all(isinstance(item, str) for item in policy["allowed_licenses"])):
                raise InvalidInput("plan_policy", "Policy allowed_licenses must be a string array")
            expression = operation["license"]["expression"]
            if expression not in policy["allowed_licenses"]:
                raise PreconditionFailure(f"License policy excludes {operation['id']}")

    @staticmethod
    def _artifact_list(bindings: Any) -> list[str]:
        if isinstance(bindings, list) and all(isinstance(item, str) for item in bindings):
            return bindings
        if isinstance(bindings, dict):
            result = []
            for item in bindings.values():
                if isinstance(item, str): result.append(item)
                elif isinstance(item, dict) and isinstance(item.get("artifact_id"), str): result.append(item["artifact_id"])
            return result
        return []

    def _normalize_bindings(self, operation: dict[str, Any], bindings: Any) -> dict[str, dict[str, str]]:
        specs = operation["io"]["inputs"]
        if isinstance(bindings, list):
            if len(bindings) != len(specs):
                raise InvalidInput("input_arity", f"{operation['id']} requires {len(specs)} inputs")
            bindings = {spec["slot"]: artifact_id for spec, artifact_id in zip(specs, bindings)}
        if not isinstance(bindings, dict):
            raise InvalidInput("input_bindings", "Inputs must be a slot mapping or ordered artifact list")
        if set(bindings) != {spec["slot"] for spec in specs}:
            raise InvalidInput("input_slots", f"Input slots for {operation['id']} must be: {', '.join(spec['slot'] for spec in specs)}")
        normalized: dict[str, dict[str, str]] = {}
        for spec in specs:
            raw = bindings[spec["slot"]]
            artifact_id = raw if isinstance(raw, str) else raw.get("artifact_id") if isinstance(raw, dict) else None
            if not isinstance(artifact_id, str):
                raise InvalidInput("input_binding", f"Input {spec['slot']} must name an artifact")
            artifact = self.store.inspect(artifact_id)
            if artifact["type"] not in spec["types"]:
                raise InvalidInput("input_type", f"Input {spec['slot']} requires {spec['types']}, got {artifact['type']}")
            if spec.get("formats") and artifact["format"] not in spec["formats"]:
                raise InvalidInput("input_format", f"Input {spec['slot']} format {artifact['format']} is unsupported")
            normalized[spec["slot"]] = {"artifact_id": artifact_id,
                                        "sha256": artifact["sha256"], "type": artifact["type"],
                                        "format": artifact["format"], "unit": artifact["unit"]}
        self._preconditions(operation, normalized)
        units = {self.store.inspect(value["artifact_id"])["unit"] for value in normalized.values()}
        if len(units) > 1:
            raise InvalidInput("unit_mismatch", "Operation inputs must use one unit")
        return normalized

    def _preconditions(self, operation: dict[str, Any], bindings: dict[str, dict[str, str]]) -> None:
        artifacts = [self.store.inspect(value["artifact_id"]) for value in bindings.values()]
        for condition in operation.get("preconditions", []):
            prop = condition.get("property")
            values = [artifact["properties"].get(prop, artifact["metadata"].get(prop, "unknown"))
                      for artifact in artifacts]
            if "equals" in condition and any(value != condition["equals"] for value in values):
                raise PreconditionFailure(f"{operation['id']} requires {prop}={condition['equals']}")
            if "minimum" in condition and any(not isinstance(value, (int, float)) or value < condition["minimum"] for value in values):
                raise PreconditionFailure(f"{operation['id']} requires {prop}>={condition['minimum']}")

    def _make_step(self, step_id: str, operation_id: str, bindings: Any,
                   parameters: dict[str, Any], kernel: str | None = None) -> dict[str, Any]:
        operation = self.registry.get(operation_id, executable=True)
        normalized = self._normalize_bindings(operation, bindings)
        input_unit = self.store.inspect(next(iter(normalized.values()))["artifact_id"])["unit"] if normalized else "mm"
        normalized_parameters, normalization_history = _prepare_parameters(
            operation["parameters"], parameters, input_unit)
        selected_policies = self.registry.resolve_policies(operation_id, normalized_parameters)
        selected_kernel = kernel or operation["kernel"]["default"]
        if selected_kernel not in operation["kernel"]["supported"]:
            raise InvalidInput("kernel_unsupported", f"Unsupported kernel for {operation_id}")
        return {"id": step_id, "operation": operation_id, "revision": operation["revision"],
                "role": operation.get("role", "transform"), "inputs": normalized,
                "parameters": normalized_parameters, "kernel": selected_kernel,
                "outputs": operation["io"]["outputs"],
                "parameter_normalization": normalization_history,
                "policies": [{key: policy[key] for key in ("id", "revision", "group", "name", "status")}
                             for policy in selected_policies]}

    def _inject_validators(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = list(steps)
        for step in list(steps):
            operation = self.registry.get(step["operation"])
            validators = operation["validation"]["validators"]
            if operation["validation"]["required"] and not validators:
                raise InvalidInput("missing_validator", f"Mutating operation {operation['id']} has no validator")
            for index, validator_id in enumerate(validators, 1):
                result.append(self._validator_step(step, operation, validator_id, index))
        return result

    def _validator_step(self, step: dict[str, Any], operation: dict[str, Any],
                        validator_id: str, index: int) -> dict[str, Any]:
        validator = self.registry.get(validator_id, executable=True)
        binding_recipe = operation["validation"].get("bindings", {}).get(validator_id)
        if not isinstance(binding_recipe, dict):
            raise InvalidInput("validator_binding", f"{operation['id']} lacks bindings for {validator_id}")
        artifact_recipe = binding_recipe.get("artifacts", binding_recipe)
        bindings: dict[str, dict[str, str]] = {}
        for spec in validator["io"]["inputs"]:
            recipe = artifact_recipe.get(spec["slot"])
            if not isinstance(recipe, dict):
                raise InvalidInput("validator_binding", f"Binding for {validator_id}:{spec['slot']} is missing")
            if isinstance(recipe.get("output"), str):
                output = next((item for item in operation["io"]["outputs"]
                               if item["slot"] == recipe["output"]), None)
                if output is None or output["type"] not in spec["types"]:
                    raise InvalidInput("validator_type", f"{validator_id} cannot validate the configured output")
                output_binding = {"step": step["id"], "slot": output["slot"],
                                  "type": output["type"], "format": output["format"]}
                if output.get("unit_from") and output["unit_from"] in step["inputs"]:
                    output_binding["unit"] = step["inputs"][output["unit_from"]]["unit"]
                elif output.get("unit"):
                    output_binding["unit"] = output["unit"]
                bindings[spec["slot"]] = output_binding
            elif isinstance(recipe.get("input"), str) and recipe["input"] in step["inputs"]:
                bindings[spec["slot"]] = dict(step["inputs"][recipe["input"]])
            else:
                raise InvalidInput("validator_binding", f"Invalid binding for {validator_id}:{spec['slot']}")
        parameter_recipe = binding_recipe.get("parameters", {}) if "artifacts" in binding_recipe else {}
        parameters: dict[str, Any] = {}
        normalization_history: list[dict[str, Any]] = []
        for target, recipe in parameter_recipe.items():
            source = recipe.get("parameter") if isinstance(recipe, dict) else None
            if source not in step["parameters"]:
                raise InvalidInput("validator_parameter_binding",
                                   f"{operation['id']} parameter {source!r} is unavailable for {validator_id}")
            parameters[target] = copy.deepcopy(step["parameters"][source])
            for entry in step.get("parameter_normalization", []):
                if entry.get("path") == source or str(entry.get("path", "")).startswith(source + "."):
                    propagated = copy.deepcopy(entry)
                    propagated["path"] = target + str(entry["path"])[len(source):]
                    propagated["bound_from"] = source
                    normalization_history.append(propagated)
        _validate_parameters(validator["parameters"], parameters)
        return {"id": f"{step['id']}_validate_{index}", "operation": validator_id,
                "revision": validator["revision"], "role": "validator",
                "inputs": bindings, "parameters": parameters,
                "parameter_normalization": normalization_history,
                "kernel": validator["kernel"]["default"],
                "outputs": validator["io"]["outputs"], "validates": step["id"],
                "policies": []}

    def _explicit_steps(self, raw_steps: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_steps, list) or not raw_steps:
            raise InvalidInput("plan_steps", "Explicit plan steps must be a non-empty array")
        # Foundation explicit DAG accepts artifact bindings and typed step references.
        result: list[dict[str, Any]] = []
        produced: dict[tuple[str, str], dict[str, str]] = {}
        for raw in raw_steps:
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not isinstance(raw.get("operation"), str):
                raise InvalidInput("plan_step", "Each plan step requires id and operation")
            operation = self.registry.get(raw["operation"], executable=True)
            inputs = raw.get("inputs", {})
            if not isinstance(inputs, dict):
                raise InvalidInput("input_bindings", "Step inputs must be a slot mapping")
            normalized: dict[str, dict[str, str]] = {}
            input_units: set[str] = set()
            for spec in operation["io"]["inputs"]:
                binding = inputs.get(spec["slot"])
                if isinstance(binding, dict) and "step" in binding:
                    source = produced.get((binding["step"], binding.get("slot", "geometry")))
                    if source is None or source["type"] not in spec["types"]:
                        raise InvalidInput("dag_type", f"Step reference for {spec['slot']} has incompatible type")
                    if spec.get("formats") and source["format"] not in spec["formats"]:
                        raise InvalidInput("dag_format", f"Step reference for {spec['slot']} has incompatible format")
                    normalized[spec["slot"]] = {"step": binding["step"], "slot": binding.get("slot", "geometry"),
                                                "type": source["type"], "format": source["format"], "unit": source["unit"]}
                    input_units.add(source["unit"])
                else:
                    artifact_id = binding if isinstance(binding, str) else binding.get("artifact_id") if isinstance(binding, dict) else None
                    if not isinstance(artifact_id, str):
                        raise InvalidInput("input_binding", f"Input {spec['slot']} must name an artifact or prior step")
                    artifact = self.store.inspect(artifact_id)
                    if artifact["type"] not in spec["types"]:
                        raise InvalidInput("input_type", f"Input {spec['slot']} has incompatible type")
                    if spec.get("formats") and artifact["format"] not in spec["formats"]:
                        raise InvalidInput("input_format", f"Input {spec['slot']} has incompatible format")
                    normalized[spec["slot"]] = {"artifact_id": artifact_id, "sha256": artifact["sha256"],
                                                "type": artifact["type"], "format": artifact["format"], "unit": artifact["unit"]}
                    input_units.add(artifact["unit"])
            if set(inputs) != {spec["slot"] for spec in operation["io"]["inputs"]}:
                raise InvalidInput("input_slots", f"Explicit step {raw['id']} has missing or extra slots")
            if len(input_units) > 1:
                raise InvalidInput("unit_mismatch", "Operation inputs must use one unit")
            if operation.get("preconditions"):
                if not all("artifact_id" in binding for binding in normalized.values()):
                    raise PreconditionFailure(f"{operation['id']} preconditions cannot be proven for a prior-step output")
                self._preconditions(operation, normalized)
            input_unit = next(iter(input_units), "mm")
            normalized_parameters, normalization_history = _prepare_parameters(
                operation["parameters"], raw.get("parameters", {}), input_unit)
            selected_policies = self.registry.resolve_policies(operation["id"], normalized_parameters)
            step = {"id": raw["id"], "operation": operation["id"], "revision": operation["revision"],
                    "role": operation.get("role", "transform"), "inputs": normalized,
                    "parameters": normalized_parameters, "kernel": raw.get("kernel", operation["kernel"]["default"]),
                    "outputs": operation["io"]["outputs"],
                    "parameter_normalization": normalization_history,
                    "policies": [{key: policy[key] for key in ("id", "revision", "group", "name", "status")}
                                 for policy in selected_policies]}
            if isinstance(raw.get("validates"), str):
                step["validates"] = raw["validates"]
            if step["kernel"] not in operation["kernel"]["supported"]:
                raise InvalidInput("kernel_unsupported", f"Unsupported kernel for {operation['id']}")
            result.append(step)
            for output in step["outputs"]:
                unit = output.get("unit")
                if output.get("unit_from"):
                    unit = normalized[output["unit_from"]]["unit"]
                produced[(step["id"], output["slot"])] = {
                    "type": output["type"], "format": output["format"], "unit": unit or input_unit}
        # Do not silently add validators to an explicit validator-bearing graph unless absent.
        validators_after: dict[str, list[dict[str, Any]]] = {}
        bound_validator_steps: set[str] = set()
        for step in list(result):
            operation = self.registry.get(step["operation"])
            for validator_id in operation["validation"]["validators"]:
                existing = [candidate for candidate in result
                            if candidate.get("validates") == step["id"] and candidate["operation"] == validator_id]
                for candidate in existing:
                    validator_index = operation["validation"]["validators"].index(validator_id) + 1
                    expected = self._validator_step(step, operation, validator_id, validator_index)
                    if (candidate["inputs"] != expected["inputs"]
                            or candidate["parameters"] != expected["parameters"]
                            or candidate["kernel"] != expected["kernel"]):
                        raise InvalidInput("validator_binding", f"Explicit validator {candidate['id']} does not bind exactly to {step['id']}")
                    bound_validator_steps.add(candidate["id"])
                if not existing:
                    validator_index = operation["validation"]["validators"].index(validator_id) + 1
                    existing = [self._validator_step(step, operation, validator_id, validator_index)]
                validators_after.setdefault(step["id"], []).extend(existing)
        ordered: list[dict[str, Any]] = []
        for step in result:
            if step["id"] in bound_validator_steps:
                continue
            ordered.append(step)
            ordered.extend(validators_after.get(step["id"], []))
        return ordered
