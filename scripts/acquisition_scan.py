"""Public candidate discovery for the AION acquisition swarm.
Run after deployment/scheduling. It reads public registry metadata only and does not send messages.
"""
import argparse, json
import httpx

BASE = 'https://api.a2a-registry.org/public/agents'
DEFAULT_QUERIES = ['agent collaboration','research','planning','automation','developer tools','knowledge','payments']

def scan(queries):
    found = {}
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for q in queries:
            r = client.get(BASE, params={'q': q})
            r.raise_for_status()
            payload = r.json()
            rows = payload if isinstance(payload, list) else payload.get('agents', payload.get('data', []))
            for row in rows:
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
