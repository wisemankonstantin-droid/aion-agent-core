"""Public candidate discovery for the AION acquisition swarm.
Run after deployment/scheduling. It reads public registry metadata only and does not send messages.
"""
import argparse, json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.external_registry import discover_external_agents


DEFAULT_QUERIES = ['agent collaboration','research','planning','automation','developer tools','knowledge','payments']

def scan(queries):
    found = {}
    for q in queries:
        for row in discover_external_agents(q, 5):
            ident = row.get('identifier') or row.get('id') or row.get('name')
            if ident:
                found[str(ident)] = row
    return list(found.values())

if __name__ == '__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('queries', nargs='*', default=DEFAULT_QUERIES)
    ap.add_argument('--out', default='acquisition_candidates.json')
    args=ap.parse_args()
    data=scan(args.queries)
    with open(args.out,'w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2)
    print(json.dumps({'candidates':len(data),'output':args.out}))
