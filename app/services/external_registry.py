import os
import httpx

A2A_REGISTRY_SEARCH = "https://api.a2a-registry.org/public/agents"

# Registry search/detail/resolve stage.
from urllib.parse import quote

def _a(x):
    if not isinstance(x,dict): return {}
    for k in ("agent","data","result"):
        if isinstance(x.get(k),dict): return x[k]
    return x

def _p(d,*ks):
    if not isinstance(d,dict): return None
    for k in ks:
        v=d.get(k)
        if v not in (None,""): return v

def _discover_external_agents_resolved(query:str,limit:int=5):
    q=(query or "").strip()
    if not q or os.getenv("AION_DISABLE_EXTERNAL_DISCOVERY")=="1": return []
    limit=max(1,min(int(limit),20)); t=max(.5,min(float(os.getenv("AION_EXTERNAL_DISCOVERY_TIMEOUT","4")),15))
    try:
        with httpx.Client(timeout=t,follow_redirects=True) as c:
            r=c.get(A2A_REGISTRY_SEARCH,params={"q":q}); r.raise_for_status(); x=r.json()
            rows=x if isinstance(x,list) else x.get("agents",x.get("data",[])); out=[]
            for row in rows[:limit]:
                if not isinstance(row,dict): continue
                ident=row.get("identifier") or row.get("id") or row.get("package_name") or row.get("name")
                d={}; z={}; err=None
                if ident:
                    try:
                        y=c.get(f"{A2A_REGISTRY_SEARCH}/{quote(str(ident),safe='')}")
                        if y.status_code==200: d=_a(y.json())
                        else: err=f"detail_http_{y.status_code}"
                    except Exception as e: err=type(e).__name__
                pkg=_p(d,"package_name","package","package_id") or row.get("package_name")
                url=_p(d,"manifest_url","manifestUrl","agent_card_url","agentCardUrl","url","endpoint") or _p(row,"manifest_url","manifestUrl","agent_card_url","agentCardUrl","url","endpoint")
                if not url and pkg:
                    try:
                        y=c.get(f"{A2A_REGISTRY_SEARCH}/resolve/{quote(str(pkg),safe='')}")
                        if y.status_code==200:
                            z=_a(y.json()); url=_p(z,"manifest_url","manifestUrl","agent_card_url","agentCardUrl","url","endpoint")
                        else: err=f"resolve_http_{y.status_code}"
                    except Exception as e: err=type(e).__name__
                ok=bool(url)
                out.append({"source":"global_a2a_registry","identifier":ident,"package_name":pkg or _p(z,"package_name","package","package_id"),"name":_p(d,"name","display_name","title") or _p(z,"name","display_name","title") or row.get("name") or row.get("display_name") or row.get("title") or ident,"description":_p(d,"description") or row.get("description") or "","url":url,"verified":d.get("verified") if "verified" in d else z.get("verified") if "verified" in z else row.get("verified"),"raw_category":row.get("category") or row.get("target"),"resolution_status":"resolved" if ok else "unresolved","resolution_reason":None if ok else (err or "no_followable_url"),"evidence_state":"resolved_manifest" if ok else "search_hit_unresolved","followable":ok})
            return out
    except Exception:
        return []


# AION_EXTERNAL_VALIDATION_V1
import datetime as _dt
import http.client as _http
import ipaddress as _ip
import json as _json
import socket as _socket
import ssl as _ssl
import urllib.parse as _uparse
import uuid as _uuid
import time as _time

_AION_RESOLVED_DISCOVER = _discover_external_agents_resolved
_AION_VALIDATION_CACHE = {}
_AION_VALIDATION_TTL = 600
_AION_MAX_EXTERNAL_BYTES = 1_000_000

def _resolve_public_https(url):
    try:
        p=_uparse.urlparse(str(url or ""))
        if p.scheme!="https" or not p.hostname or p.username or p.password:
            return None,(),"url_must_be_public_https"
        if p.port not in (None,443):
            return None,(),"nonstandard_port_rejected"
        infos=_socket.getaddrinfo(p.hostname,p.port or 443,type=_socket.SOCK_STREAM)
        if not infos:
            return None,(),"dns_no_addresses"
        candidates=[]
        seen=set()
        for family,socktype,proto,_,sockaddr in infos:
            raw=sockaddr[0]
            ip=_ip.ip_address(raw)
            if not ip.is_global:
                return None,(),"non_public_address:"+str(ip)
            key=(family,socktype,proto,sockaddr)
            if key not in seen:
                seen.add(key); candidates.append(key)
        return p,tuple(candidates),None
    except Exception as e:
        return None,(),"url_validation_error:"+type(e).__name__

def _public_url(url):
    _,candidates,reason=_resolve_public_https(url)
    return bool(candidates),reason

class _PinnedHTTPSConnection(_http.HTTPConnection):
    """HTTPS over one already validated numeric socket destination."""
    def __init__(self,hostname,candidate,timeout):
        super().__init__(hostname,443,timeout=timeout)
        self._candidate=candidate
        self._tls_context=_ssl.create_default_context()

    def connect(self):
        family,socktype,proto,sockaddr=self._candidate
        raw=_socket.socket(family,socktype,proto)
        try:
            raw.settimeout(self.timeout)
            raw.connect(sockaddr)
            # The TCP peer is pinned, while the original hostname remains the
            # TLS SNI and certificate-verification identity.
            self.sock=self._tls_context.wrap_socket(raw,server_hostname=self.host)
        except Exception:
            raw.close()
            raise

def _host_header(hostname):
    return "["+hostname+"]" if ":" in hostname else hostname

def _read_json(method,url,payload=None,headers=None,timeout=7):
    parsed,candidates,reason=_resolve_public_https(url)
    if reason:
        return None,None,reason
    data=None if payload is None else _json.dumps(payload).encode()
    h={"User-Agent":"AION-External-Validator/0.7.1","Accept":"application/json"}
    if payload is not None:
        h["Content-Type"]="application/json"
    if headers:
        h.update(headers)
    h["Host"]=_host_header(parsed.hostname)
    target=(parsed.path or "/")+("?"+parsed.query if parsed.query else "")
    last_error=None
    for candidate in candidates:
        connection=_PinnedHTTPSConnection(parsed.hostname,candidate,timeout)
        try:
            connection.request(method,target,body=data,headers=h)
            r=connection.getresponse()
            raw=r.read(_AION_MAX_EXTERNAL_BYTES+1)
            if len(raw)>_AION_MAX_EXTERNAL_BYTES:
                return r.status,None,"response_too_large"
            if 300 <= r.status < 400:
                return r.status,None,"redirect_rejected"
            if r.status >= 400:
                body=raw.decode("utf-8","replace")
                return r.status,None,"http_"+str(r.status)+":"+body[:300]
            try:
                return r.status,_json.loads(raw.decode("utf-8","replace")),None
            except Exception:
                return r.status,None,"non_json_response"
        except Exception as e:
            last_error=type(e).__name__+":"+str(e)[:240]
        finally:
            connection.close()
    return None,None,last_error or "connection_failed"

def _interface(card):
    if not isinstance(card,dict):
        return None,None,None
    interfaces=card.get("supportedInterfaces") or card.get("supported_interfaces") or []
    if isinstance(interfaces,list):
        for it in interfaces:
            if not isinstance(it,dict):
                continue
            binding=(it.get("protocolBinding") or it.get("protocol_binding") or "").upper()
            ver=str(it.get("protocolVersion") or it.get("protocol_version") or "")
            url=it.get("url")
            if binding=="JSONRPC" and url:
                return url,ver or None,"JSONRPC"
    url=card.get("url") or card.get("endpoint")
    ver=str(card.get("protocolVersion") or card.get("protocol_version") or "")
    if url:
        return url,ver or None,"JSONRPC_LEGACY"
    return None,None,None

def _handshake(url):
    body={
      "jsonrpc":"2.0",
      "id":"aion-validate-"+str(_uuid.uuid4()),
      "method":"SendMessage",
      "params":{"message":{
        "messageId":"aion-validate-msg-"+str(_uuid.uuid4()),
        "role":"ROLE_USER",
        "parts":[{"text":"AION interoperability probe. Return a harmless acknowledgement or capability summary only. Do not perform external side effects."}]
      }}
    }
    status,data,err=_read_json("POST",url,body,{"A2A-Version":"1.0"},timeout=10)
    if err:
        return False,status,None,err
    if not isinstance(data,dict):
        return False,status,None,"invalid_jsonrpc_response"
    if data.get("error"):
        return False,status,None,"jsonrpc_error:"+str(data.get("error"))[:350]
    result=data.get("result")
    if not isinstance(result,dict) or not ("message" in result or "task" in result):
        return False,status,None,"no_a2a_result_payload"
    rtype="message" if "message" in result else "task"
    return True,status,rtype,None

def _validate_external(row):
    base=dict(row or {})
    manifest=base.get("url")
    cache_key=str(manifest or "")
    now=_time.time()
    cached=_AION_VALIDATION_CACHE.get(cache_key)
    if cached and now-cached[0]<_AION_VALIDATION_TTL:
        merged=dict(base); merged.update(cached[1]); return merged

    state={
      "resolved":bool(manifest),
      "reachable":False,
      "protocol_detected":False,
      "conformant":False,
      "interaction_success":False,
      "last_success_at":None,
      "failure_reason":None,
      "verified_external_agent":False,
      "manifest_followable":bool(base.get("followable")),
    }
    if not manifest:
        state["failure_reason"]="no_manifest_url"
    else:
        status,card,err=_read_json("GET",manifest,timeout=7)
        state["manifest_http_status"]=status
        if status==200 and isinstance(card,dict):
            state["reachable"]=True
            state["card_name"]=card.get("name")
            state["card_version"]=card.get("version")
            iurl,ver,binding=_interface(card)
            state["interaction_url"]=iurl
            state["protocol_version"]=ver
            state["protocol_binding"]=binding
            state["protocol_detected"]=bool(iurl and binding)
            if iurl and binding=="JSONRPC" and str(ver)=="1.0":
                ok,hs,rtype,herr=_handshake(iurl)
                state["conformant"]=True
                state["interaction_http_status"]=hs
                state["interaction_success"]=bool(ok)
                state["verified_external_agent"]=bool(ok)
                state["response_type"]=rtype
                if ok:
                    state["last_success_at"]=_dt.datetime.now(_dt.timezone.utc).isoformat()
                else:
                    state["failure_reason"]=herr
            else:
                state["failure_reason"]="not_a2a_v1_jsonrpc_interface"
        else:
            state["failure_reason"]=err or "manifest_unreachable"

    if state["interaction_success"]:
        state["evidence_state"]="verified_interaction"
        state["validation_status"]="verified"
    elif state["reachable"] and state["protocol_detected"]:
        state["evidence_state"]="reachable_manifest_nonconformant"
        state["validation_status"]="rejected_or_legacy"
    elif state["reachable"]:
        state["evidence_state"]="reachable_manifest_protocol_unknown"
        state["validation_status"]="unverified"
    else:
        state["evidence_state"]="unreachable_or_invalid"
        state["validation_status"]="unverified"

    state["followable"]=bool(state["interaction_success"])
    _AION_VALIDATION_CACHE[cache_key]=(now,state)
    merged=dict(base); merged.update(state)
    return merged

def discover_external_agents(query: str, limit: int = 5):
    rows=_AION_RESOLVED_DISCOVER(query,min(max(int(limit),1),5))
    return [_validate_external(r) for r in rows]
