from __future__ import annotations
import os,re
from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlsplit,urlunsplit
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models

PACKAGE_RE=re.compile(r"\bio\.github\.[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\b",re.I)
URL_RE=re.compile(r"https://[^\s<>\"]+",re.I)
RETURN_MINUTES=max(1,int(os.getenv("AION_RETURN_THRESHOLD_MINUTES","15")))

def _norm(v): return re.sub(r"[^a-z0-9]+","",(v or "").lower())
def _canon_url(v):
    if not v or not str(v).startswith(("http://","https://")): return None
    try:
        u=urlsplit(str(v).strip())
        return urlunsplit((u.scheme.lower(),u.netloc.lower(),(u.path or "/").rstrip("/") or "/",u.query,""))
    except Exception: return str(v).strip().rstrip("/").lower()

def _packages(o):
    out=set()
    for raw in (getattr(o,"endpoint",None),getattr(o,"description",None),getattr(o,"external_id",None)):
        if raw:
            out|={m.lower().rstrip(".,;:)") for m in PACKAGE_RE.findall(str(raw))}
    ep=getattr(o,"endpoint",None); proto=(getattr(o,"protocol",None) or "").upper()
    if ep and proto=="MCP" and not str(ep).startswith(("http://","https://")) and "/" in str(ep):
        out.add(str(ep).strip().lower())
    return out

def _resolvers(o):
    out=set()
    for raw in (getattr(o,"endpoint",None),getattr(o,"description",None)):
        if not raw: continue
        for u in URL_RE.findall(str(raw)):
            c=_canon_url(u.rstrip(".,;:)"))
            if c and ("raw.githubusercontent.com/" in c or c.endswith("/server.json") or "/.well-known/agent" in c):
                out.add(c)
    return out

def _fps(o):
    ep=_canon_url(getattr(o,"endpoint",None)); nm=_norm(getattr(o,"name",None))
    return {
      "external_id":{(getattr(o,"external_id","") or "").strip().lower()}-{""},
      "packages":_packages(o),
      "resolvers":_resolvers(o),
      "endpoint_name":{f"{ep}|{nm}"} if ep and nm else set(),
    }

def _caps(db):
    out=defaultdict(set)
    for c in db.scalars(select(models.Capability)).all():
        out[c.agent_id].add((c.name or "").strip().lower())
    return out

def same_logical(a,b,caps=None):
    fa,fb=_fps(a),_fps(b); ev=[]
    if fa["external_id"] & fb["external_id"]: ev.append("stable_external_id")
    if fa["packages"] & fb["packages"]: ev.append("durable_package")
    if fa["resolvers"] & fb["resolvers"]: ev.append("canonical_resolver")
    if fa["endpoint_name"] & fb["endpoint_name"]: ev.append("canonical_endpoint_plus_declared_identity")
    if caps is not None and _norm(getattr(a,"name",None))==_norm(getattr(b,"name",None)):
        ca=caps.get(getattr(a,"id",None),set()); cb=caps.get(getattr(b,"id",None),set())
        if ca and cb and ca&cb: ev.append("declared_identity_plus_capability_overlap")
    strong=any(x in ev for x in ("stable_external_id","durable_package","canonical_resolver","canonical_endpoint_plus_declared_identity"))
    return strong,ev

def find_logical_duplicate(payload,db:Session):
    caps=_caps(db)
    for a in db.scalars(select(models.Agent).order_by(models.Agent.id.asc())).all():
        ok,ev=same_logical(payload,a,caps)
        if ok: return {"agent":a,"evidence":ev}
    return None

def _operated_or_test(a):
    explicit={x.strip().lower() for x in os.getenv("AION_OPERATED_EXTERNAL_IDS","").split(",") if x.strip()}
    if (a.external_id or "").lower() in explicit: return True
    src=((a.acquisition_source or "")+" "+(a.referrer or "")).lower()
    return any(x in src for x in ("aion-operated","internal-test","synthetic-test","probe-test","staging-test"))

def logical_groups(db:Session):
    agents=db.scalars(select(models.Agent).order_by(models.Agent.id.asc())).all()
    caps=_caps(db); parent=list(range(len(agents)))
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]]; x=parent[x]
        return x
    def union(i,j):
        ri,rj=find(i),find(j)
        if ri!=rj: parent[rj]=ri
    for i in range(len(agents)):
        for j in range(i+1,len(agents)):
            ok,_=same_logical(agents[i],agents[j],caps)
            if ok: union(i,j)
    buckets=defaultdict(list)
    for i,a in enumerate(agents): buckets[find(i)].append(a)
    out=[]
    for rows in buckets.values():
        first=min((a.first_useful_action_at for a in rows if a.first_useful_action_at),default=None)
        last=max((a.last_seen_at for a in rows if a.last_seen_at),default=None)
        ev=set()
        for i in range(len(rows)):
            for j in range(i+1,len(rows)):
                _,e=same_logical(rows[i],rows[j],caps); ev.update(e)
        out.append({
          "canonical_agent_id":min(a.id for a in rows),
          "row_ids":[a.id for a in rows],
          "external_ids":[a.external_id for a in rows],
          "names":sorted(set(a.name for a in rows)),
          "durable_packages":sorted(set().union(*[_packages(a) for a in rows])),
          "canonical_resolvers":sorted(set().union(*[_resolvers(a) for a in rows])),
          "capabilities":sorted(set().union(*[caps.get(a.id,set()) for a in rows])),
          "identity_evidence":sorted(ev),
          "raw_rows":len(rows),
          "credential_confirmed":any((a.authenticated_calls or 0)>0 for a in rows),
          "activated":any(a.first_useful_action_at is not None for a in rows),
          "returning":bool(first and last and last>=first+timedelta(minutes=RETURN_MINUTES)),
          "aion_operated_or_test":all(_operated_or_test(a) for a in rows),
          "first_useful_action_at":first.isoformat() if first else None,
          "last_seen_at":last.isoformat() if last else None,
        })
    return sorted(out,key=lambda g:g["canonical_agent_id"])

def snapshot(db:Session):
    groups=logical_groups(db); ext=[g for g in groups if not g["aion_operated_or_test"]]
    return {
      "raw_agent_rows":sum(g["raw_rows"] for g in groups),
      "estimated_unique_logical_agents":len(groups),
      "estimated_unique_external_agents":len(ext),
      "duplicate_identity_rows":sum(max(0,g["raw_rows"]-1) for g in groups),
      "groups":groups,
      "integrity_note":"Automatic grouping uses stable external_id, durable package, canonical resolver, or canonical endpoint plus declared identity. Name/capability overlap is supporting evidence only. AION-operated/test identities are excluded from estimated external adoption."
    }

def unique_funnel(db:Session):
    gs=[g for g in logical_groups(db) if not g["aion_operated_or_test"]]
    return {
      "M2_unique_external_agents":len(gs),
      "M2b_credential_confirmed_agents":sum(1 for g in gs if g["credential_confirmed"]),
      "M3_activated_agents":sum(1 for g in gs if g["activated"]),
      "M4_returning_agents":sum(1 for g in gs if g["returning"]),
    }
