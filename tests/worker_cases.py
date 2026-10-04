"""Closed curved mesh, hole boundaries, and self-intersection rejection."""
import json,math,pathlib,subprocess,sys,tempfile

def off(points,faces):
    return "OFF\n"+f"{len(points)} {len(faces)} 0\n"+"\n".join(
        " ".join(map(str,p)) for p in points)+"\n"+"\n".join(
        "3 "+" ".join(map(str,f)) for f in faces)+"\n"

def run(source,output,ratio=0.7,envelope=0.0):
    request={"version":1,"operation":"simplify","input":str(source),"output":str(output),
             "edge_ratio":ratio,"preserve_border":True,"envelope":envelope}
    result=subprocess.run([sys.argv[1]],input=json.dumps(request),text=True,
                          capture_output=True,timeout=120)
    return result,json.loads(result.stdout)

with tempfile.TemporaryDirectory() as folder:
    source=pathlib.Path(folder)/"in.off";output=pathlib.Path(folder)/"out.off"
    points=[(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]
    faces=[(4,0,2),(4,2,1),(4,1,3),(4,3,0),(5,2,0),(5,1,2),(5,3,1),(5,0,3)]
    for _ in range(2):
        mids={};newfaces=[]
        def midpoint(a,b):
            key=tuple(sorted((a,b)))
            if key not in mids:
                p=tuple((points[a][i]+points[b][i])/2 for i in range(3))
                norm=math.sqrt(sum(x*x for x in p))
                mids[key]=len(points);points.append(tuple(x/norm for x in p))
            return mids[key]
        for a,b,c in faces:
            ab,bc,ca=midpoint(a,b),midpoint(b,c),midpoint(c,a)
            newfaces.extend([(a,ab,ca),(ab,b,bc),(ca,bc,c),(ab,bc,ca)])
        faces=newfaces
    source.write_text(off(points,faces));result,data=run(source,output)
    assert result.returncode==0 and data["edges_after"]<data["edges_before"],data
    n=10;points=[(x,y,0) for y in range(n+1) for x in range(n+1)];faces=[]
    for y in range(n):
        for x in range(n):
            if x in (4,5) and y in (4,5):continue
            a=y*(n+1)+x
            faces.extend([(a,a+1,a+n+2),(a,a+n+2,a+n+1)])
    edges={}
    for face in faces:
        for a,b in zip(face,face[1:]+face[:1]):
            key=tuple(sorted((a,b)));edges[key]=edges.get(key,0)+1
    protected={tuple(map(float,points[i])) for e,c in edges.items() if c==1 for i in e}
    source.write_text(off(points,faces));result,data=run(source,output,envelope=0.01)
    assert result.returncode==0 and data["constraints_preserved"],data
    rows=output.read_text().split();nv=int(rows[1])
    actual={tuple(map(float,rows[4+3*i:7+3*i])) for i in range(nv)}
    assert protected<=actual,"Hole boundary changed"
    points=[(-1,-1,0),(1,-1,0),(0,1,0),(0,-0.5,-1),(0,-0.5,1),(0,0.5,0)]
    source.write_text(off(points,[(0,1,2),(3,4,5)]))
    result,data=run(source,output)
    assert result.returncode!=0 and not data["ok"] and "intersect" in data["error"],data
    print("Closed curved surface, hole boundary, self-intersection rejection: PASS")
