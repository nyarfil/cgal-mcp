"""Generic CGAL Master control-plane foundation.

The package intentionally lives beside the v0.1 mesh runtime.  Its public
objects are data-driven and do not import or mutate the legacy runtime.
"""

from .registry import OperationRegistry
from .runtime import MasterRuntime
from .store import ArtifactStore

__all__ = ["ArtifactStore", "MasterRuntime", "OperationRegistry"]
