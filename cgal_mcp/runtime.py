"""Immutable assets/plans and bounded asynchronous worker jobs."""
import asyncio, copy, hashlib, json, math, os, uuid
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

MAX_BYTES = 4 * 1024 * 1024

class SimplifyParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    edge_ratio: float = Field(gt=0, lt=1, allow_inf_nan=False)
    tolerance: float = Field(gt=0, allow_inf_nan=False)
    error_bound: float = Field(gt=0, allow_inf_nan=False)
    envelope: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    preserve_border: StrictBool = True
    constrained_edges: list[list[int]] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def error_is_useful(self):
        if any(len(edge)!=2 for edge in self.constrained_edges):
            raise ValueError("constrained_edges must contain index pairs")
        if self.error_bound >= self.tolerance:
            raise ValueError("error_bound must be smaller than tolerance")
        return self

def parse_off(content: str) -> dict:
    if not isinstance(content,str) or len(content.encode()) > MAX_BYTES:
        raise ValueError("OFF input exceeds 4 MiB")
    tokens=" ".join(line.split("#",1)[0] for line in content.splitlines()).split()
    if len(tokens)<4 or tokens[0]!="OFF":
        raise ValueError("Only ASCII triangle OFF is supported")
    nv,nf,ne=map(int,tokens[1:4])
    if nv<3 or nf<1 or nv>100000 or nf>200000 or ne<0:
        raise ValueError("Invalid mesh counts")
    pos=4
    vertices=[]
    for _ in range(nv):
        p=tuple(map(float,tokens[pos:pos+3]));pos+=3
        if len(p)!=3 or not all(math.isfinite(x) for x in p):
            raise ValueError("Invalid/nonfinite vertex")
        vertices.append(p)
    counts={}
    directions={}
    faces=set()
    for _ in range(nf):
        if pos>=len(tokens) or tokens[pos]!="3": raise ValueError("Triangle faces required")
        ids=tuple(map(int,tokens[pos+1:pos+4]));pos+=4
        if len(ids)!=3 or len(set(ids))!=3 or any(i<0 or i>=nv for i in ids):
            raise ValueError("Invalid face indices")
        key=tuple(sorted(ids))
        if key in faces: raise ValueError("Duplicate face")
        faces.add(key)
        a,b,c=(vertices[i] for i in ids)
        u=tuple(b[i]-a[i] for i in range(3));v=tuple(c[i]-a[i] for i in range(3))
        cross=(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
        if not all(math.isfinite(x) for x in cross) or not any(cross):
            raise ValueError("Degenerate or numerically overflowing triangle")
        for a,b in zip(ids,ids[1:]+ids[:1]):
            edge=tuple(sorted((a,b)))
            counts[edge]=counts.get(edge,0)+1
            if counts[edge]>2 or (a,b) in directions:
                raise ValueError("Nonmanifold or inconsistently oriented edge")
            directions[a,b]=True
    if pos!=len(tokens): raise ValueError("Unexpected trailing/truncated data")
    return {"vertices":nv,"faces":nf,"edges":len(counts),
            "closed":all(n==2 for n in counts.values()),"edge_ids":set(counts)}

class Runtime:
    def __init__(self, root: Path, worker: Path, distance: Path, timeout: float=120):
        self.root=root.resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.worker=worker.resolve();self.distance=distance.resolve()
        if not math.isfinite(timeout) or timeout<=0: raise ValueError("Invalid timeout")
        self.timeout=timeout
        self.assets={};self.plans={};self.jobs={};self.tasks={}
        self.semaphore=asyncio.Semaphore(2)

    def register(self, content: str, unit: str) -> dict:
        if unit not in ("mm","cm","m"): raise ValueError("Explicit unit must be mm, cm or m")
        info=parse_off(content)
        digest=hashlib.sha256(content.encode()).hexdigest()
        asset_id=hashlib.sha256((unit+":"+digest).encode()).hexdigest()
        path=self.root / (asset_id+".off")
        if not path.exists(): path.write_text(content,encoding="utf-8")
        data={"asset_id":asset_id,"sha256":digest,"unit":unit,"path":str(path),
              **{k:v for k,v in info.items() if k!="edge_ids"}}
        self.assets[asset_id]=data
        return {k:v for k,v in data.items() if k!="path"}

    def asset(self, asset_id: str) -> dict:
        if asset_id not in self.assets: raise KeyError("Unknown asset")
        data=self.assets[asset_id]
        if hashlib.sha256(Path(data["path"]).read_bytes()).hexdigest()!=data["sha256"]:
            raise ValueError("Asset changed after registration")
        return data

    def plan(self, asset_id: str, parameters: dict) -> dict:
        asset=self.asset(asset_id)
        p=SimplifyParameters.model_validate(parameters)
        edge_ids=parse_off(Path(asset["path"]).read_text())["edge_ids"]
        for a,b in p.constrained_edges:
            if a==b or tuple(sorted((a,b))) not in edge_ids:
                raise ValueError("Constrained edge does not exist in input")
        plan={"operation":"simplify","asset_id":asset_id,"input_sha256":asset["sha256"],
              "unit":asset["unit"],"parameters":p.model_dump(mode="json"),
              "schema_version":1,"cgal_version":"6.2.1",
              "steps":["CGAL preflight","plane_line_collapse","symmetric_hausdorff","publish_if_pass"]}
        plan_id=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
        plan["plan_id"]=plan_id;self.plans[plan_id]=copy.deepcopy(plan)
        return copy.deepcopy(plan)

    def execute(self, plan_id: str) -> dict:
        if plan_id not in self.plans: raise KeyError("Unknown plan")
        plan=copy.deepcopy(self.plans[plan_id]);self.asset(plan["asset_id"])
        if len([j for j in self.jobs.values() if j["state"] in ("queued","running")])>=16:
            raise ValueError("Job queue is full")
        job_id=uuid.uuid4().hex
        self.jobs[job_id]={"job_id":job_id,"state":"queued","plan":plan}
        self._audit(self.jobs[job_id])
        self.tasks[job_id]=asyncio.create_task(self._run(job_id))
        return {"job_id":job_id,"state":"queued"}

    def status(self, job_id: str) -> dict:
        if job_id not in self.jobs: raise KeyError("Unknown job")
        return copy.deepcopy(self.jobs[job_id])

    async def cancel(self, job_id: str) -> dict:
        self.status(job_id)
        task=self.tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
            # A queued task might be cancelled before entering _run.
            self.jobs[job_id]["state"]="cancelled"
            self._audit(self.jobs[job_id])
        return self.status(job_id)

    async def _call(self, executable: Path, request: dict) -> dict:
        if not executable.is_file(): raise RuntimeError("Worker binary is missing; build worker first")
        proc=await asyncio.create_subprocess_exec(str(executable),
             stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            stdout,stderr=await asyncio.wait_for(proc.communicate(json.dumps(request).encode()),self.timeout)
        except BaseException:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            raise
        if len(stdout)>65536 or len(stderr)>65536: raise RuntimeError("Worker response exceeds limit")
        try: result=json.loads(stdout)
        except (ValueError,UnicodeError) as e: raise RuntimeError("Malformed worker response") from e
        if not isinstance(result,dict) or result.get("version")!=1:
            raise RuntimeError("Invalid worker response version")
        if proc.returncode or result.get("ok") is not True:
            raise RuntimeError(str(result.get("error","Worker failed")))
        return result

    def _audit(self, job: dict):
        folder=self.root/job["job_id"];folder.mkdir(exist_ok=True)
        temporary=folder/"audit.tmp"
        temporary.write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding="utf-8")
        temporary.replace(folder/"audit.json")

    async def _run(self, job_id: str):
        job=self.jobs[job_id];folder=self.root/job_id;folder.mkdir(exist_ok=True)
        output=folder/"candidate.off"
        try:
            async with self.semaphore:
                job["state"]="running"
                plan=job["plan"];asset=self.asset(plan["asset_id"]);p=plan["parameters"]
                result=await self._call(self.worker,{"version":1,"operation":"simplify",
                      "input":asset["path"],"output":str(output),**p})
                if not output.is_file() or output.stat().st_size>MAX_BYTES:
                    raise RuntimeError("Invalid output artifact")
                candidate=output.read_text(encoding="utf-8");parse_off(candidate)
                verification=await self._call(self.distance,{"version":1,"operation":"hausdorff",
                    "input_a":asset["path"],"input_b":str(output),"error_bound":p["error_bound"],
                    "tolerance":p["tolerance"]})
                self.asset(plan["asset_id"])
                job["computation"]=result;job["verification"]=verification
                if verification.get("verdict")!="pass":
                    job["state"]="rejected"
                elif result.get("constraints_preserved") is not True:
                    raise RuntimeError("Worker did not verify constraints")
                else:
                    artifact=self.register(candidate,asset["unit"])
                    job["artifact"]=artifact;job["state"]="succeeded"
        except asyncio.CancelledError:
            job["state"]="cancelled"
            raise
        except asyncio.TimeoutError:
            job["state"]="timed_out";job["error"]="Worker timed out"
        except Exception as e:
            job["state"]="failed";job["error"]=str(e)
        finally:
            output.unlink(missing_ok=True)
            self._audit(job)

    def artifact(self, asset_id: str) -> dict:
        data=self.asset(asset_id)
        return {"asset_id":asset_id,"unit":data["unit"],"sha256":data["sha256"],
                "off":Path(data["path"]).read_text(encoding="utf-8")}
