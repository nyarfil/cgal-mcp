"""Stable failure taxonomy returned by the Master control plane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MasterError(Exception):
    code: str
    message: str
    failure_class: str = "internal"
    recoverable: bool = False
    suggested_operations: tuple[str, ...] = ()
    source_class: str | None = None

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict[str, Any]:
        result = {
            "class": self.failure_class,
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
            "suggested_operations": list(self.suggested_operations),
        }
        if self.source_class:
            result["source_class"] = self.source_class
        return result


class InvalidInput(MasterError):
    def __init__(self, code: str, message: str):
        super().__init__(code, message, "invalid_input", False)


class UnsupportedOperation(MasterError):
    def __init__(self, operation: str):
        super().__init__("unsupported_operation", f"Unsupported operation: {operation}",
                         "unsupported_adapter", False)


class PreconditionFailure(MasterError):
    def __init__(self, message: str):
        super().__init__("unmet_precondition", message, "unmet_precondition", False)


class WorkerFailure(MasterError):
    pass
