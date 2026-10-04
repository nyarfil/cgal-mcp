"""Real planar-grid simplification and border preservation."""
import json, pathlib, subprocess, sys, tempfile

with tempfile.TemporaryDirectory() as folder:
    root = pathlib.Path(folder)
    source, output = root / "in.off", root / "out.off"
    n = 10
    points = [(x,y,0) for y in range(n+1) for x in range(n+1)]
    faces = []
    for y in range(n):
        for x in range(n):
            a=y*(n+1)+x
            faces.extend([(a,a+1,a+n+2),(a,a+n+2,a+n+1)])
    source.write_text("OFF\n" + f"{len(points)} {len(faces)} 0\n" +
        "\n".join(" ".join(map(str,p)) for p in points) + "\n" +
        "\n".join("3 "+" ".join(map(str,f)) for f in faces) + "\n")
    request = {"version":1,"operation":"simplify","input":str(source),"output":str(output),
               "edge_ratio":0.5,"preserve_border":True,"envelope":0.01}
    result = subprocess.run([sys.argv[1]], input=json.dumps(request), text=True,
                            capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr + result.stdout
    data = json.loads(result.stdout)
    assert data["ok"] and data["edges_after"] < data["edges_before"], data
    assert data["hausdorff_verified"] is False
    rows = output.read_text().split()
    assert rows[0] == "OFF"
    nv = int(rows[1])
    actual = {tuple(map(float,rows[4+3*i:7+3*i])) for i in range(nv)}
    border = {tuple(map(float,p)) for p in points if p[0] in (0,n) or p[1] in (0,n)}
    assert border <= actual, "Border vertex positions changed"
    request["edge_ratio"] = -1
    rejected = subprocess.run([sys.argv[1]], input=json.dumps(request), text=True,
                              capture_output=True, timeout=20)
    assert rejected.returncode != 0
    assert not json.loads(rejected.stdout)["ok"]
    print("Worker simplification, envelope, border preservation, invalid ratio: PASS")
