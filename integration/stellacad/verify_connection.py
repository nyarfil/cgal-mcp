"""Exercise the installed StellaCAD sidecar from its real Codex configuration."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tomllib
import trimesh
from mcp import Client,StdioServerParameters


async def verify(config: Path, output_dir: Path):
    settings=tomllib.loads(config.read_text(encoding="utf-8-sig"))["mcp_servers"]["cgal-mcp"]
    assert settings.get("enabled",True)
    output_dir.mkdir(parents=True,exist_ok=False)
    n=10
    points=[(x,y,0) for y in range(n+1) for x in range(n+1)]
    faces=[]
    for y in range(n):
        for x in range(n):
            a=y*(n+1)+x
            faces.extend([(a,a+1,a+n+2),(a,a+n+2,a+n+1)])
    source=output_dir/"source.stl"
    source.write_bytes(trimesh.Trimesh(vertices=points,faces=faces,process=False).export(file_type="stl"))
    source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    # All writes during this connection check stay in an explicitly isolated workspace.
    connection=StdioServerParameters(command=settings["command"],args=settings["args"],
        cwd=settings["cwd"],env={**os.environ,**settings["env"],
                               "CGAL_MCP_DATA":str(output_dir/"runtime")})
    report={"config":str(config),"command":settings["command"],"args":settings["args"],"modes":{}}
    for mode in ("auto","legacy"):
        async with Client(connection,mode=mode) as client:
            tools=(await client.list_tools()).tools
            names=[tool.name for tool in tools]
            assert len(names)==12 and "stella_cgal_simplify_file" in names,names
            output=output_dir/f"simplified-{mode}.stl"
            arguments={"input_path":str(source),"output_path":str(output),"unit":"mm",
                "parameters":{"edge_ratio":0.5,"tolerance":0.1,"error_bound":0.001,
                              "envelope":0.01,"preserve_border":True}}
            result=await client.call_tool("stella_cgal_simplify_file",arguments)
            assert not result.is_error,result
            data=result.structured_content
            if data is None:
                data=json.loads("".join(block.text for block in result.content if hasattr(block,"text")))
            assert data["verification"]["verdict"]=="pass",data
            assert data["export_verification"]["verdict"]=="pass",data
            assert data["output"]["faces"]<data["source"]["faces"],data
            assert hashlib.sha256(source.read_bytes()).hexdigest()==source_sha
            assert hashlib.sha256(output.read_bytes()).hexdigest()==data["output"]["file_sha256"]
            # A second write to the same result must fail without touching either file.
            refused=await client.call_tool("stella_cgal_simplify_file",arguments)
            assert refused.is_error
            assert hashlib.sha256(output.read_bytes()).hexdigest()==data["output"]["file_sha256"]
            report["modes"][mode]={"tools":names,"result":data,"overwrite_rejected":True}
            print(f"StellaCAD configured MCP ({mode}): {data['source']['faces']} -> {data['output']['faces']} faces; export Hausdorff PASS; source preserved")
    (output_dir/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",required=True,type=Path)
    parser.add_argument("--output-dir",required=True,type=Path)
    args=parser.parse_args()
    asyncio.run(verify(args.config,args.output_dir.resolve()))
