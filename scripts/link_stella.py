"""Link an existing Windows CGAL build to StellaCAD/Codex without replacing other servers."""
import argparse
import datetime
import json
import pathlib
import shutil
import tomllib


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stella-root",required=True,type=pathlib.Path)
    parser.add_argument("--codex-home",required=True,type=pathlib.Path)
    parser.add_argument("--codex-project",action="append",default=[],type=pathlib.Path)
    args=parser.parse_args()
    repo=pathlib.Path(__file__).resolve().parents[1]
    python=repo/".venv"/"Scripts"/"python.exe"
    worker=repo/"build"/"Release"/"cgal-worker.exe"
    distance=repo/"build"/"Release"/"cgal-distance.exe"
    launcher=args.stella_root/"integration"/"cgal"/"stella_cgal_mcp.py"
    for path in (python,worker,distance,launcher):
        if not path.is_file():
            raise SystemExit(f"Required installed file is missing: {path}")
    settings={"command":str(python),"args":[str(launcher)],"cwd":str(repo),
        "enabled":True,"startup_timeout_sec":30,"tool_timeout_sec":300,
        "env":{"CGAL_MCP_WORKER":str(worker),"CGAL_MCP_DISTANCE":str(distance),
        "CGAL_MCP_DATA":str(args.stella_root/"cadmcp-workspace"/"cgal-mcp"),
        "PYTHONUTF8":"1","PYTHONIOENCODING":"utf-8"}}
    # Quoted JSON strings are valid TOML strings and preserve Windows paths.
    section="\n\n[mcp_servers.cgal-mcp]\n"+"\n".join(
        f"{key} = {json.dumps(value)}" for key,value in settings.items() if key!="env")
    section+="\n\n[mcp_servers.cgal-mcp.env]\n"+"\n".join(
        f"{key} = {json.dumps(value)}" for key,value in settings["env"].items())+"\n"
    configs=[args.codex_home/"config.toml",args.stella_root/".codex"/"config.toml"]
    configs.extend(p/".codex"/"config.toml" for p in args.codex_project)
    pending=[]
    for config in dict.fromkeys(configs):
        content=config.read_text(encoding="utf-8-sig") if config.exists() else ""
        before=tomllib.loads(content)
        existing=before.get("mcp_servers",{}).get("cgal-mcp")
        if existing is not None:
            if existing!=settings:
                raise SystemExit(f"Existing CGAL configuration differs; review it before updating: {config}")
            continue
        updated=content+section
        after=tomllib.loads(updated)
        restored=dict(after)
        restored["mcp_servers"]=dict(after["mcp_servers"])
        del restored["mcp_servers"]["cgal-mcp"]
        if not restored["mcp_servers"] and "mcp_servers" not in before:
            del restored["mcp_servers"]
        if restored!=before:
            raise SystemExit(f"Configuration preservation check failed: {config}")
        pending.append((config,updated))
    backups=args.codex_home/"backups"/"cgal-link"/datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    for index,(config,updated) in enumerate(pending):
        config.parent.mkdir(parents=True,exist_ok=True)
        if config.exists():
            backups.mkdir(parents=True,exist_ok=True)
            shutil.copy2(config,backups/f"{index}-config.toml")
        temporary=config.with_name(config.name+".cgal.tmp")
        temporary.write_text(updated,encoding="utf-8")
        temporary.replace(config)
        print(f"Linked: {config}")
    print("CGAL MCP registration verified; existing server settings preserved.")


if __name__=="__main__":
    main()
