import json, pathlib, subprocess, sys, tempfile
with tempfile.TemporaryDirectory() as folder:
    a,b=pathlib.Path(folder)/"a.off",pathlib.Path(folder)/"b.off"
    a.write_text("OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n")
    b.write_text("OFF\n3 1 0\n0 0 1\n1 0 1\n0 1 1\n3 0 1 2\n")
    request={"version":1,"operation":"hausdorff","input_a":str(a),"input_b":str(b),
             "error_bound":0.001,"tolerance":1.01}
    def run():
        result=subprocess.run([sys.argv[1]],input=json.dumps(request),text=True,
                              capture_output=True,timeout=120)
        assert result.returncode==0, result.stdout+result.stderr
        return json.loads(result.stdout)
    result=run()
    assert abs(result["distance"]-1)<=0.001, result
    assert result["lower"]<=1<=result["upper"],result
    assert result["verdict"]=="pass",result
    request["tolerance"]=0.9
    assert run()["verdict"]=="fail"
    request["tolerance"]=1.0
    assert run()["verdict"]=="indeterminate"
    print("Symmetric bounded-error Hausdorff and three-way verdict: PASS")
