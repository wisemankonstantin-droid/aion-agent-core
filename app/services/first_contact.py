from __future__ import annotations
import urllib.parse
from sqlalchemy import select
from .. import models
from ..db import SessionLocal

def _route(a):
    e=(a.endpoint or "").strip(); p=(a.protocol or "").strip()
    if e.startswith(("https://","http://")):
        return {
          "route_type":"declared_direct_endpoint",
          "followable":True,
          "directly_callable":"unverified",
          "liveness":"not_checked_by_this_read",
          "endpoint_url":e,
          "protocol":p or None,
          "integrity":"A declared direct endpoint is structurally followable but is not claimed live until a separate liveness observation succeeds."
        }
    if p.upper()=="MCP" and e:
        return {
          "route_type":"mcp_registry_locator",
          "followable":True,
          "directly_callable":False,
          "liveness":"unverified",
          "endpoint_url":None,
          "protocol":"MCP",
          "registry_identifier":e,
          "registry_url":"https://registry.modelcontextprotocol.io/?q="+urllib.parse.quote(e,safe=""),
          "integrity":"Registry-listed is not the same as live/callable. Resolve the current provider manifest and independently check liveness before tools/call."
        }
    return None

def _marketplace_first_contact_value(base):
    protocol={
      "a2a_version":"1.0",
      "endpoint":f"{base}/a2a/v1",
      "method":"SendMessage",
      "role":"ROLE_USER",
      "parts":"member-based discrimination: use {'text':'...'} or {'data':{...}}; no kind field in normative v1.0",
      "structured_command_example":{"data":{"action":"first_contact"}},
      "compatibility":"AION accepts a bounded legacy ingress normalization for its own older clients, but new clients should emit normative A2A v1.0."
    }
    with SessionLocal() as db:
        for n in db.scalars(select(models.Need).where(models.Need.status=="open").order_by(models.Need.id.desc())).all():
            a=db.get(models.Agent,n.agent_id); rt=_route(a) if a else None
            if rt:
                return {
                  "action":"first_contact","membership_required":False,"join_is_optional":True,
                  "source":"aion_open_need","opportunity_type":"buyer_demand","protocol":protocol,
                  "immediate_value":{"need_id":n.id,"capability":n.capability,"description":n.description,
                    "requester":{"name":a.name,"trust_level":a.trust_level,**rt}},
                  "exact_machine_action":{"method":"GET","url":f"{base}/needs"},
                  "reason_to_return":"Needs, offers and matches can change without creating a new identity.",
                  "integrity":"This read is not membership, activation or independently verified adoption."
                }
        for o in db.scalars(select(models.Offer).order_by(models.Offer.id.desc())).all():
            a=db.get(models.Agent,o.agent_id); rt=_route(a) if a else None
            if rt:
                return {
                  "action":"first_contact","membership_required":False,"join_is_optional":True,
                  "source":"aion_public_offer","opportunity_type":"seller_offer","protocol":protocol,
                  "immediate_value":{"offer_id":o.id,"capability":o.capability,"description":o.description,"price_hint":o.price_hint,
                    "provider":{"name":a.name,"trust_level":a.trust_level,**rt}},
                  "exact_machine_action":{"method":"GET","url":f"{base}/offers"},
                  "reason_to_return":"New needs may match this offer later.",
                  "integrity":"Provider claims are declared unless independently verified."
                }
    return {
      "action":"first_contact","membership_required":False,"join_is_optional":True,
      "source":"aion_external_discovery","opportunity_type":"discovery","protocol":protocol,
      "immediate_value":{"description":"Search public A2A listings without joining AION.","query_example":f"{base}/discover/external?q=research"},
      "exact_machine_action":{"method":"GET","url":f"{base}/discover/external?q=research"},
      "reason_to_return":"Public discovery and member needs/offers change over time.",
      "integrity":"External discovery results are not AION members and this read is not adoption."
    }


def first_contact_value(base, utility=None):
    payload = _marketplace_first_contact_value(base)
    payload["immediate_value"]["utility_endpoint"] = f"{base}/utility/query"
    if utility is not None:
        payload["live_utility"] = utility
    return payload
