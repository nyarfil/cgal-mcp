"""Version-pinned long-tail header index. Results never authorize execution."""
import json
from pathlib import Path

def search_api(query: str, limit: int = 5) -> list[dict]:
    if not isinstance(query,str) or not query.strip():
        raise ValueError("query must be nonempty")
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=20:
        raise ValueError("limit must be an integer in [1,20]")
    entries=json.loads(Path(__file__).with_name("api_index.json").read_text())["entries"]
    query=query.casefold().strip()
    terms=query.replace("_"," ").split()
    scored=[]
    for entry in entries:
        text=(entry["name"]+" "+entry["package"]).replace("_"," ").casefold()
        score=sum(term in text for term in terms)
        if score:
            scored.append((score,entry))
    return [entry for _,entry in sorted(scored,key=lambda pair:(-pair[0],pair[1]["id"]))[:limit]]
