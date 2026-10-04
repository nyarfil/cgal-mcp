"""Typed immutable DAG planner with mandatory validator insertion."""

from __future__ import annotations

from collections import deque
import math
from typing import Any

from .errors import InvalidInput, PreconditionFailure, UnsupportedOperation
from .registry import OperationRegistry
from .store import ArtifactStore
from .util import canonical_json, digest_bytes, normalize_quantities


def _validate_value(schema: dict[str, Any], value: Any, path: str) -> None:
    kind = schema.get("type")
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
                                        "sha256": artifact["sha256"], "type": artifact["type"]}
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
        try:
            normalized_parameters = normalize_quantities(parameters, input_unit)
        except ValueError as exc:
            raise InvalidInput("parameter_unit", str(exc)) from exc
        _validate_parameters(operation["parameters"], normalized_parameters)
        selected_kernel = kernel or operation["kernel"]["default"]
        if selected_kernel not in operation["kernel"]["supported"]:
            raise InvalidInput("kernel_unsupported", f"Unsupported kernel for {operation_id}")
        return {"id": step_id, "operation": operation_id, "revision": operation["revision"],
                "role": operation.get("role", "transform"), "inputs": normalized,
                "parameters": normalized_parameters, "kernel": selected_kernel,
                "outputs": operation["io"]["outputs"]}

    def _inject_validators(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = list(steps)
        for step in list(steps):
            operation = self.registry.get(step["operation"])
            validators = operation["validation"]["validators"]
            if operation["validation"]["required"] and not validators:
                raise InvalidInput("missing_validator", f"Mutating operation {operation['id']} has no validator")
            for index, validator_id in enumerate(validators, 1):
                validator = self.registry.get(validator_id, executable=True)
                validator_specs = validator["io"]["inputs"]
                binding_recipe = operation["validation"].get("bindings", {}).get(validator_id)
                if not isinstance(binding_recipe, dict):
                    raise InvalidInput("validator_binding", f"{operation['id']} lacks bindings for {validator_id}")
                bindings: dict[str, dict[str, str]] = {}
                for spec in validator_specs:
                    recipe = binding_recipe.get(spec["slot"])
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
                            source_unit = step["inputs"][output["unit_from"]].get("unit")
                            if source_unit:
                                output_binding["unit"] = source_unit
                        elif output.get("unit"):
                            output_binding["unit"] = output["unit"]
                        bindings[spec["slot"]] = output_binding
                    elif isinstance(recipe.get("input"), str) and recipe["input"] in step["inputs"]:
                        bindings[spec["slot"]] = dict(step["inputs"][recipe["input"]])
                    else:
                        raise InvalidInput("validator_binding", f"Invalid binding for {validator_id}:{spec['slot']}")
                result.append({"id": f"{step['id']}_validate_{index}", "operation": validator_id,
                               "revision": validator["revision"], "role": "validator",
                               "inputs": bindings, "parameters": {},
                               "kernel": validator["kernel"]["default"],
                               "outputs": validator["io"]["outputs"], "validates": step["id"]})
        return result

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
            try:
                normalized_parameters = normalize_quantities(raw.get("parameters", {}), input_unit)
            except ValueError as exc:
                raise InvalidInput("parameter_unit", str(exc)) from exc
            _validate_parameters(operation["parameters"], normalized_parameters)
            step = {"id": raw["id"], "operation": operation["id"], "revision": operation["revision"],
                    "role": operation.get("role", "transform"), "inputs": normalized,
                    "parameters": normalized_parameters, "kernel": raw.get("kernel", operation["kernel"]["default"]),
                    "outputs": operation["io"]["outputs"]}
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
                    expected = self._inject_validators([step])[1]["inputs"]
                    if candidate["inputs"] != expected:
                        raise InvalidInput("validator_binding", f"Explicit validator {candidate['id']} does not bind exactly to {step['id']}")
                    bound_validator_steps.add(candidate["id"])
                if not existing:
                    existing = self._inject_validators([step])[1:]
                validators_after.setdefault(step["id"], []).extend(existing)
        ordered: list[dict[str, Any]] = []
        for step in result:
            if step["id"] in bound_validator_steps:
                continue
            ordered.append(step)
            ordered.extend(validators_after.get(step["id"], []))
        return ordered
