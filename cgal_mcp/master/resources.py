"""Validated resource configuration for Master worker execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os


DEFAULT_CONCURRENCY = 2
DEFAULT_MEMORY_MB = 4096
DEFAULT_WALL_TIME_MS = 120_000
MAX_WALL_TIME_MS = 86_400_000


def _environment_integer(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if str(value) != raw.strip() and not (raw.strip().startswith("+") and str(value) == raw.strip()[1:]):
        raise ValueError(f"{name} must be a canonical integer")
    return value


@dataclass(frozen=True)
class ResourceConfig:
    concurrency: int = DEFAULT_CONCURRENCY
    max_memory_mb: int = DEFAULT_MEMORY_MB
    default_memory_mb: int = DEFAULT_MEMORY_MB
    default_wall_time_ms: int = DEFAULT_WALL_TIME_MS
    max_wall_time_ms: int = MAX_WALL_TIME_MS

    def __post_init__(self) -> None:
        values = {
            "concurrency": self.concurrency,
            "max_memory_mb": self.max_memory_mb,
            "default_memory_mb": self.default_memory_mb,
            "default_wall_time_ms": self.default_wall_time_ms,
            "max_wall_time_ms": self.max_wall_time_ms,
        }
        if any(type(value) is not int for value in values.values()):
            raise ValueError("Resource configuration values must be integers")
        if not 1 <= self.concurrency <= 64:
            raise ValueError("Master worker concurrency must be between 1 and 64")
        if not 64 <= self.max_memory_mb <= 1_048_576:
            raise ValueError("Master maximum memory must be between 64 MiB and 1 TiB")
        if not 64 <= self.default_memory_mb <= self.max_memory_mb:
            raise ValueError("Master default memory must be within the configured memory ceiling")
        if not 1 <= self.default_wall_time_ms <= self.max_wall_time_ms <= MAX_WALL_TIME_MS:
            raise ValueError("Master wall-time limits are invalid")

    @classmethod
    def from_environment(cls) -> "ResourceConfig":
        concurrency = _environment_integer("CGAL_MASTER_CONCURRENCY", DEFAULT_CONCURRENCY)
        maximum = _environment_integer("CGAL_MASTER_MAX_MEMORY_MB", DEFAULT_MEMORY_MB)
        default_memory = _environment_integer(
            "CGAL_MASTER_DEFAULT_MEMORY_MB", min(DEFAULT_MEMORY_MB, maximum))
        default_wall = _environment_integer("CGAL_MASTER_DEFAULT_WALL_TIME_MS", DEFAULT_WALL_TIME_MS)
        max_wall = _environment_integer("CGAL_MASTER_MAX_WALL_TIME_MS", MAX_WALL_TIME_MS)
        return cls(concurrency=concurrency, max_memory_mb=maximum,
                   default_memory_mb=default_memory,
                   default_wall_time_ms=default_wall, max_wall_time_ms=max_wall)

    def with_concurrency(self, concurrency: int) -> "ResourceConfig":
        return replace(self, concurrency=concurrency)
