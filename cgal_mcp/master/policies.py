"""Validated policy inventory kept separate from executable Operations."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from .errors import InvalidInput, UnsupportedOperation
from .util import ID_RE, canonical_json


POLICY_STATUSES = {"DISCOVERED", "CATALOGED", "ADAPTER_PLANNED", "IMPLEMENTED",
                   "VALIDATED", "DEPRECATED", "BLOCKED", "EXCLUDED"}
EXECUTABLE_POLICY_STATUSES = {"IMPLEMENTED", "VALIDATED"}


def _default_policy_path() -> Path:
    configured = os.environ.get("CGAL_MASTER_POLICIES")
    return Path(configured) if configured else Path(__file__).with_name("policies.json")


def _at_path(parameters: dict[str, Any], path: list[str]) -> tuple[bool, Any]:
    value: Any = parameters
    for component in path:
        if not isinstance(value, dict) or component not in value:
            return False, None
        value = value[component]
    return True, value


def _matches(selector: dict[str, Any], parameters: dict[str, Any]) -> bool:
    present, value = _at_path(parameters, selector["path"])
    if "present" in selector:
        return present is selector["present"]
    if not present:
        return False
    if "equals" in selector:
        return value == selector["equals"]
    if selector.get("nonempty") is True:
        return isinstance(value, (list, dict, str)) and bool(value)
    return False


class PolicyRegistry:
    def __init__(self, path: Path | None = None):
        self.path = (path or _default_policy_path()).resolve()
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidInput("policy_registry_read", f"Cannot load policy registry: {exc}") from exc
        if not isinstance(document, dict) or document.get("schema_version") != 1:
            raise InvalidInput("policy_registry_schema", "Unsupported policy registry schema")
        self.cgal_version = str(document.get("cgal_version", ""))
        self.build_requirements = document.get("build_requirements", {})
        if (not self.cgal_version or not isinstance(self.build_requirements, dict)
                or any(not isinstance(key, str) or not isinstance(value, str)
                       for key, value in self.build_requirements.items())):
            raise InvalidInput("policy_registry_schema", "Policy version/build metadata is invalid")
        raw_requirements = document.get("operation_requirements", {})
        if not isinstance(raw_requirements, dict):
            raise InvalidInput("policy_registry_schema", "operation_requirements must be an object")
        self.requirements: dict[str, tuple[str, ...]] = {}
        for operation, groups in raw_requirements.items():
            if (not isinstance(operation, str) or not isinstance(groups, list)
                    or not groups or not all(isinstance(group, str) for group in groups)):
                raise InvalidInput("policy_registry_schema", "Invalid operation policy requirements")
            self.requirements[operation] = tuple(groups)
        self.policies: dict[str, dict[str, Any]] = {}
        raw_policies = document.get("policies")
        if not isinstance(raw_policies, list):
            raise InvalidInput("policy_registry_schema", "Policy registry has no policies array")
        for raw in raw_policies:
            policy = self._validate(raw)
            if policy["id"] in self.policies:
                raise InvalidInput("policy_registry_conflict", f"Duplicate policy {policy['id']}")
            self.policies[policy["id"]] = policy
        self.revision = __import__("hashlib").sha256(canonical_json({
            "requirements": self.requirements, "policies": self.policies})).hexdigest()

    @staticmethod
    def _validate(raw: Any) -> dict[str, Any]:
        required = {"id", "revision", "operation", "group", "name", "status",
                    "summary", "selectors", "implementation", "evidence"}
        if not isinstance(raw, dict) or required - raw.keys():
            raise InvalidInput("policy_schema", "Policy entry is missing required fields")
        policy = copy.deepcopy(raw)
        if not isinstance(policy["id"], str) or not ID_RE.fullmatch(policy["id"]):
            raise InvalidInput("policy_id", f"Invalid policy id: {policy.get('id')}")
        if type(policy["revision"]) is not int or policy["revision"] < 1:
            raise InvalidInput("policy_revision", f"Invalid policy revision: {policy['id']}")
        if (not isinstance(policy["operation"], str) or not ID_RE.fullmatch(policy["operation"])
                or not isinstance(policy["group"], str) or not policy["group"]
                or not isinstance(policy["name"], str) or not policy["name"]
                or not isinstance(policy["summary"], str) or not policy["summary"]):
            raise InvalidInput("policy_metadata", f"Invalid policy metadata: {policy['id']}")
        policy["status"] = str(policy["status"]).upper()
        if policy["status"] not in POLICY_STATUSES:
            raise InvalidInput("policy_status", f"Invalid policy status: {policy['id']}")
        if (not isinstance(policy["selectors"], list)
                or not all(isinstance(selector, dict)
                           and isinstance(selector.get("path"), list)
                           and selector["path"]
                           and all(isinstance(part, str) for part in selector["path"])
                           and len({"equals", "present", "nonempty"} & selector.keys()) == 1
                           for selector in policy["selectors"])):
            raise InvalidInput("policy_selector", f"Invalid selectors: {policy['id']}")
        if not isinstance(policy["implementation"], dict):
            raise InvalidInput("policy_implementation", f"Invalid implementation: {policy['id']}")
        evidence = policy["evidence"]
        if (not isinstance(evidence, dict) or not isinstance(evidence.get("tests"), list)
                or policy["status"] == "VALIDATED" and not evidence["tests"]):
            raise InvalidInput("policy_evidence", f"Invalid policy evidence: {policy['id']}")
        if policy["status"] in {"BLOCKED", "EXCLUDED"} and not isinstance(policy.get("reason"), str):
            raise InvalidInput("policy_reason", f"Policy lacks blocked/excluded reason: {policy['id']}")
        return policy

    def get(self, policy_id: str) -> dict[str, Any]:
        policy = self.policies.get(policy_id)
        if policy is None:
            raise UnsupportedOperation(policy_id)
        return copy.deepcopy(policy)

    def for_operation(self, operation: str) -> list[dict[str, Any]]:
        return [copy.deepcopy(policy) for policy in self.policies.values()
                if policy["operation"] == operation]

    def resolve(self, operation: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
        selected = [policy for policy in self.policies.values()
                    if policy["operation"] == operation
                    and any(_matches(selector, parameters) for selector in policy["selectors"])]
        for group in self.requirements.get(operation, ()):
            matches = [policy for policy in selected if policy["group"] == group]
            if len(matches) != 1:
                raise InvalidInput("policy_selection",
                                   f"{operation} must select exactly one {group} policy")
        unavailable = [policy for policy in selected
                       if policy["status"] not in EXECUTABLE_POLICY_STATUSES]
        if unavailable:
            raise InvalidInput("policy_unavailable",
                               f"Policy is not executable: {unavailable[0]['id']}")
        return [copy.deepcopy(policy) for policy in sorted(selected, key=lambda item: item["id"])]
