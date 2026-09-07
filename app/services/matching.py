from __future__ import annotations
import hashlib
from sqlalchemy.orm import Session
from sqlalchemy import select
from ..models import Need, Offer, Agent
from .capabilities import normalize_capability

_GENERIC={"ai","agent","agents","tool","tools","service","services","api","mcp","a2a","capability","capabilities"}

def _tokens(v):
    return {x for x in normalize_capability(v).split("_") if x}

def _capability_score(left,right):
    a=normalize_capability(left); b=normalize_capability(right)
    if not a or not b:return 0.0,[]
    if a==b:return 1.0,[{"type":"exact_capability","left":a,"right":b,"weight":1.0}]
    ta,tb=_tokens(a),_tokens(b); common=(ta&tb)-_GENERIC; union=ta|tb
    if not common or not union:return 0.0,[]
    j=len(ta&tb)/len(union)
    if j<0.33:return 0.0,[]
    sc=min(0.9,0.50+0.50*j)
    return sc,[{"type":"capability_token_overlap","common":sorted(common),"jaccard":round(j,4),"weight":round(sc,4)}]

def _route(agent):
    e=(getattr(agent,"endpoint",None) or "").strip(); p=(getattr(agent,"protocol",None) or "").upper()
    if e.startswith(("https://","http://")):
        return {"type":"declared_direct_endpoint","endpoint":e,"protocol":p or None,
                "availability":"declared_unverified","directly_callable":"unverified"}
    if p=="MCP" and e:
        return {"type":"mcp_registry_locator","registry_identifier":e,"protocol":"MCP",
                "availability":"registry_listed_liveness_unverified","directly_callable":False}
    return {"type":"aion_internal_identity","endpoint":None,"protocol":p or None,
            "availability":"interaction_via_aion","directly_callable":False}

def _logical_map(db):
    try:
        from .identity_resolution import logical_groups
        out={}
        for g in logical_groups(db):
            for rid in g["row_ids"]:out[rid]=g["canonical_agent_id"]
        return out
    except Exception:return {}

def find_matches(db: Session, need_id: int):
    need=db.get(Need,need_id)
    if not need or getattr(need,"status","open")!="open":return []
    logical=_logical_map(db); requester_logical=logical.get(need.agent_id,need.agent_id); candidates={}
    for offer in db.scalars(select(Offer).order_by(Offer.id.desc())).all():
        provider_logical=logical.get(offer.agent_id,offer.agent_id)
        if provider_logical==requester_logical:continue
        cap_score,reasons=_capability_score(offer.capability,need.capability)
        if cap_score<=0:continue
        key=(provider_logical,normalize_capability(offer.capability))
        if key in candidates:continue
        agent=db.get(Agent,offer.agent_id)
        if not agent:continue
        route=_route(agent); rep=max(0.0,float(agent.reputation or 0.0))
        rb=min(0.05,rep/100.0); trust=(agent.trust_level or "declared").lower()
        tb={"observed":0.03,"verified":0.05,"trusted":0.05}.get(trust,0.0)
        eb=0.05 if route["type"]=="declared_direct_endpoint" else 0.02 if route["type"]=="mcp_registry_locator" else 0.0
        score=min(1.0,0.85*cap_score+rb+tb+eb)
        if rb:reasons.append({"type":"reputation_evidence","reputation":rep,"weight":round(rb,4)})
        if tb:reasons.append({"type":"trust_evidence","trust_level":trust,"weight":tb})
        reasons.append({"type":"active_offer","offer_id":offer.id,"weight":0.0})
        mid="mt_"+hashlib.sha256(f"{need.id}:{provider_logical}:{offer.id}".encode()).hexdigest()[:20]
        candidates[key]={
          "match_id":mid,"match_score":round(score,4),"score_scale":"0..1","reasons":reasons,
          "need":{"id":need.id,"capability":need.capability,"requirements":need.description},
          "offer":{"id":offer.id,"capability":offer.capability,"description":offer.description,"price_hint":offer.price_hint},
          "provider":{"agent_id":offer.agent_id,"canonical_agent_id":provider_logical,"name":agent.name,
                      "trust_level":agent.trust_level,"reputation":rep,"route":route},
          "availability":route["availability"],
          "next_action":{"method":"POST","endpoint":"/interactions",
                         "body":{"provider_agent_id":offer.agent_id,"need_id":need.id},
                         "authentication":"Bearer requester agent key"},
          "integrity":{"endpoint_liveness_verified":False,
                       "capability_verification":trust if trust!="declared" else "declared",
                       "note":"A match is a ranked opportunity, not proof that the provider endpoint is currently reachable or that work has completed."}}
    rows=list(candidates.values())
    rows.sort(key=lambda x:(x["match_score"],x["provider"]["reputation"],x["offer"]["id"]),reverse=True)
    return rows
