"""Official MCP client → plan → CGAL subprocesses → accepted artifact."""
import asyncio,json,pathlib,tempfile
from mcp import Client
import cgal_mcp.server as server
from cgal_mcp.runtime import Runtime

async def main():
    with tempfile.TemporaryDirectory() as folder:
        server._runtime=Runtime(pathlib.Path(folder),pathlib.Path("build/cgal-worker"),
                                pathlib.Path("build/cgal-distance"))
        n=10;points=[(x,y,0) for y in range(n+1) for x in range(n+1)]
        faces=[]
        for y in range(n):
            for x in range(n):
                a=y*(n+1)+x
                faces.extend([(a,a+1,a+n+2),(a,a+n+2,a+n+1)])
        off="OFF\n"+f"{len(points)} {len(faces)} 0\n"+"\n".join(
            " ".join(map(str,p)) for p in points)+"\n"+"\n".join(
            "3 "+" ".join(map(str,f)) for f in faces)+"\n"
        async with Client(server.mcp) as client:
            async def call(name,args):
                result=await client.call_tool(name,args)
                assert not result.is_error,result
                return result.structured_content
            asset=await call("register_mesh",{"off":off,"unit":"mm"})
            plan=await call("plan_simplification",{"asset_id":asset["asset_id"],
                "parameters":{"edge_ratio":0.5,"tolerance":0.1,"error_bound":0.001,
                              "envelope":0.01,"constrained_edges":[[0,1],[60,61]]}})
            job=await call("execute_plan",{"plan_id":plan["plan_id"]})
            for _ in range(600):
                state=await call("job_status",{"job_id":job["job_id"]})
                if state["state"] not in ("queued","running"):break
                await asyncio.sleep(0.1)
            assert state["state"]=="succeeded",state
            assert state["verification"]["verdict"]=="pass",state
            output=await call("get_artifact",{"asset_id":state["artifact"]["asset_id"]})
            assert output["unit"]=="mm" and output["off"].startswith("OFF")
            assert state["computation"]["edges_after"]<state["computation"]["edges_before"]
            print("Official MCP client + CGAL + constraints + Hausdorff + artifact: PASS")
asyncio.run(main())
