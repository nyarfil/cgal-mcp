"""Host-neutral integration contract. The real StellaCAD host supplies atomic undo-aware apply."""
from dataclasses import dataclass
from typing import Protocol
from .runtime import Runtime

@dataclass(frozen=True)
class Snapshot:
    object_id: str
    revision: str
    off: str
    unit: str

class CADHost(Protocol):
    def snapshot(self, object_id: str) -> Snapshot: ...
    def apply_mesh_atomic(self, object_id: str, expected_revision: str, off: str,
                          unit: str, metadata: dict) -> None:
        """Compare revision and replace mesh in one undoable transaction; raise on mismatch."""
        ...

class StellaCADAdapter:
    def __init__(self, host: CADHost, runtime: Runtime):
        self.host=host;self.runtime=runtime;self.bindings={}
    def prepare(self, object_id: str, parameters: dict) -> dict:
        snapshot=self.host.snapshot(object_id)
        asset=self.runtime.register(snapshot.off,snapshot.unit)
        plan=self.runtime.plan(asset["asset_id"],parameters)
        self.bindings[plan["plan_id"]]=snapshot
        return plan
    def apply(self, job_id: str) -> None:
        job=self.runtime.status(job_id)
        if job["state"]!="succeeded" or job.get("verification",{}).get("verdict")!="pass":
            raise ValueError("Only successfully verified jobs can be applied")
        plan_id=job["plan"]["plan_id"]
        if plan_id not in self.bindings: raise ValueError("Job is not bound to this CAD session")
        snapshot=self.bindings[plan_id]
        current=self.host.snapshot(snapshot.object_id)
        if current.revision!=snapshot.revision or current.off!=snapshot.off or current.unit!=snapshot.unit:
            raise ValueError("CAD object changed; recompute before applying")
        artifact=self.runtime.artifact(job["artifact"]["asset_id"])
        self.host.apply_mesh_atomic(snapshot.object_id,snapshot.revision,artifact["off"],
                                    artifact["unit"],job)
        del self.bindings[plan_id]
