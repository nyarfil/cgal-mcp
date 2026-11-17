"""Copy freshly replayed family reports to the published paths and approve their digests in the catalog."""
import hashlib, json, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(REPO))
from scripts import replay_master_capabilities as rc
work = Path(sys.argv[1])
target = REPO / 'catalog/major_requirements.json'
text = target.read_text(encoding='utf-8'); catalog = json.loads(text)
assert json.dumps(catalog, ensure_ascii=False, indent=2) + "\n" == text, 'catalog format differs'
changed = 0
for family in rc.REPLAY_FAMILIES:
    source = work / f'family-{family}.json'
    data = source.read_bytes(); digest = hashlib.sha256(data).hexdigest()
    published = rc.published_output(family); rel = published.relative_to(REPO).as_posix()
    hits = 0
    for fam in catalog['families']:
        for item in fam['requirements']:
            for ev in item.get('evidence', []):
                if ev.get('path') == rel:
                    ev['sha256'] = digest; hits += 1
    published.write_bytes(data); changed += hits
    print(family, rel, digest[:12], 'requirements', hits)
target.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding='utf-8', newline='\n')
print('updated', changed)
