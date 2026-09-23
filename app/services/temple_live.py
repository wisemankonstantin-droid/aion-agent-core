"""Read-only live Temple control-plane snapshot and browser visualization."""

from __future__ import annotations

from datetime import datetime, timezone
import html
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..acquisition import worker_manifest
from ..payment_models import RouteIntelligencePurchase
from .acquisition_swarm import worker_runtime_snapshot
from .lifecycle import funnel_snapshot
from .moltbook_acquisition import outbound_status as moltbook_outbound_status


_MAX_RECENT_CONTACTS = 250
_WORKER_IDS = tuple(row["id"] for row in worker_manifest())


def _iso(value):
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _worker_id_from_key(value: str | None) -> str | None:
    key = str(value or "")
    for worker_id in _WORKER_IDS:
        if key.startswith(f"intent-{worker_id}-") or key.startswith(
            f"dm-{worker_id}-"
        ):
            return worker_id
    return None


def _lane_from_campaign_name(value: str | None) -> str | None:
    name = str(value or "")
    prefix = "Intent swarm "
    if not name.startswith(prefix):
        return None
    return name[len(prefix):].split(" #", 1)[0].strip() or None


def _count(db: Session, statement) -> int:
    return int(db.scalar(statement) or 0)


def temple_live_snapshot(db: Session) -> dict:
    runtime = worker_runtime_snapshot()
    workers = {row["id"]: dict(row) for row in worker_manifest()}
    for row in runtime["workers"]:
        workers[row["worker_id"]].update(row)

    contacts = list(
        db.scalars(
            select(models.AmbassadorContactAttempt)
            .order_by(models.AmbassadorContactAttempt.id.desc())
            .limit(_MAX_RECENT_CONTACTS)
        )
    )
    recent_events = []
    persisted_by_worker: dict[str, dict] = {}
    for contact in contacts:
        target = db.get(models.AmbassadorTarget, contact.target_id)
        if target is None:
            continue
        campaign = db.get(models.AmbassadorCampaign, target.campaign_id)
        worker_id = _worker_id_from_key(contact.idempotency_key)
        lane = _lane_from_campaign_name(campaign.name if campaign else None)
        event = {
            "event_type": "contact",
            "worker_id": worker_id,
            "lane": lane,
            "timestamp": _iso(contact.created_at),
            "completed_at": _iso(contact.completed_at),
            "channel": target.discovery_source,
            "target_id": target.target_id,
            "target": target.source_identifier,
            "target_url": target.agent_card_url,
            "interaction_url": target.interaction_url,
            "qualification_state": target.qualification_state,
            "result_class": contact.result_class,
            "http_status": contact.http_status,
            "response_received": bool(contact.response_received),
            "conversation_topic": lane,
            "outbound_purpose": "before_external_spend",
        }
        recent_events.append(event)
        if worker_id and worker_id not in persisted_by_worker:
            persisted_by_worker[worker_id] = event

    worker_rows = []
    for worker_id in _WORKER_IDS:
        row = workers[worker_id]
        if worker_id in persisted_by_worker:
            row["last_persisted_contact"] = persisted_by_worker[worker_id]
        row["truth"] = "AION-operated worker; not an external customer or adoption unit"
        worker_rows.append(row)

    target_total = _count(
        db, select(func.count()).select_from(models.AmbassadorTarget)
    )
    target_qualified = _count(
        db,
        select(func.count())
        .select_from(models.AmbassadorTarget)
        .where(models.AmbassadorTarget.qualification_state == "qualified"),
    )
    contact_total = _count(
        db, select(func.count()).select_from(models.AmbassadorContactAttempt)
    )
    contact_delivered = _count(
        db,
        select(func.count())
        .select_from(models.AmbassadorContactAttempt)
        .where(
            models.AmbassadorContactAttempt.result_class.in_(
                ("delivered", "response_received")
            )
        ),
    )
    machine_responses = _count(
        db,
        select(func.count())
        .select_from(models.AmbassadorContactAttempt)
        .where(models.AmbassadorContactAttempt.response_received.is_(True)),
    )
    purchases_prepared = _count(
        db, select(func.count()).select_from(RouteIntelligencePurchase)
    )
    purchase_entitlements = _count(
        db,
        select(func.count())
        .select_from(RouteIntelligencePurchase)
        .where(RouteIntelligencePurchase.state == "entitled"),
    )
    settled_operations = _count(
        db,
        select(func.count())
        .select_from(models.EconomicOperation)
        .where(models.EconomicOperation.state == "settled"),
    )

    moltbook = moltbook_outbound_status()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "north_star": "FIRST_REAL_SETTLED_AGENT_TRANSACTION",
        "core": {
            "name": "AION SUPREME TEMPLE",
            "state": "online",
            "worker_count": runtime["worker_count"],
            "active_worker_count": runtime["active_worker_count"],
            "workers_per_cycle": runtime["workers_per_cycle"],
            "worker_shards": runtime["worker_shards"],
        },
        "channel_health": {
            "moltbook": {
                "suspended": bool(moltbook.get("suspended")),
                "suspended_until": moltbook.get("suspended_until"),
            },
            "federated_a2a": {
                "sources": ["agenstry", "findagent", "global_a2a_registry"],
                "strategy": "parallel_discovery_with_global_dedupe",
            },
        },
        "funnel": {
            "discovered_targets": target_total,
            "qualified_targets": target_qualified,
            "contact_attempts": contact_total,
            "delivered_contacts": contact_delivered,
            "machine_responses": machine_responses,
            "route_intelligence_purchases_prepared": purchases_prepared,
            "settled_purchase_entitlements": purchase_entitlements,
            "settled_economic_operations": settled_operations,
            "membership_funnel": funnel_snapshot(db),
            "truth": (
                "Attempts, workers, targets and responses are not SAT. "
                "Settlement evidence remains a separate stage."
            ),
        },
        "workers": worker_rows,
        "recent_events": recent_events,
        "privacy": {
            "raw_secrets_exposed": False,
            "raw_distribution_tokens_exposed": False,
            "raw_payment_authorizations_exposed": False,
            "raw_response_bodies_exposed": False,
        },
    }


def temple_live_html() -> str:
    # The page contains no operator data. The browser asks for the existing
    # Ambassador control token and uses it only in Authorization headers.
    return r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>AION Temple Live</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}
*{box-sizing:border-box}body{margin:0;background:#05070b;color:#dce8ff;overflow:hidden}
#top{position:fixed;z-index:5;left:12px;right:12px;top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.badge{background:rgba(12,18,29,.82);border:1px solid #24354c;border-radius:10px;padding:7px 10px;font-size:12px;backdrop-filter:blur(10px)}
#auth{margin-left:auto;display:flex;gap:6px}.auth-input{width:180px;background:#0a0f18;color:#dce8ff;border:1px solid #324866;border-radius:8px;padding:7px}
button{background:#13233a;color:#eaf2ff;border:1px solid #355a88;border-radius:8px;padding:7px 10px}
#scene{width:100vw;height:100vh;display:block}
#panel{position:fixed;z-index:4;right:12px;top:58px;width:min(390px,calc(100vw - 24px));max-height:calc(100vh - 76px);overflow:auto;background:rgba(7,11,18,.91);border:1px solid #263c58;border-radius:14px;padding:14px;backdrop-filter:blur(12px)}
#panel.hidden{display:none}.k{font-size:11px;color:#8aa1bd;text-transform:uppercase;letter-spacing:.08em}.v{font-size:13px;margin:2px 0 10px;word-break:break-word}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.metric{padding:8px;border-radius:9px;background:#0c1420;border:1px solid #1b2b40}.metric b{display:block;font-size:18px}.metric span{font-size:10px;color:#90a5bd}
#legend{position:fixed;left:12px;bottom:12px;background:rgba(7,11,18,.82);border:1px solid #22364f;border-radius:10px;padding:8px 10px;font-size:11px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}
.ok{background:#59e391}.run{background:#61a8ff}.idle{background:#7f8b99}.err{background:#ff6d6d}.resp{background:#ffd166}
a{color:#8dc2ff}
@media(max-width:720px){#panel{top:auto;bottom:10px;max-height:46vh}.auth-input{width:135px}#top{right:8px;left:8px}.badge{padding:5px 7px}}
</style>
</head>
<body>
<div id="top">
  <div class="badge"><b>AION TEMPLE LIVE</b></div>
  <div class="badge" id="clock">offline snapshot</div>
  <div class="badge" id="workers">workers —</div>
  <div class="badge" id="funnel">responses — / SAT evidence —</div>
  <div id="auth">
    <input id="token" class="auth-input" type="password" autocomplete="current-password" placeholder="operator token">
    <button id="connect">Connect</button>
  </div>
</div>
<canvas id="scene"></canvas>
<div id="panel" class="hidden"></div>
<div id="legend"><span class="dot run"></span>running <span class="dot ok"></span>working <span class="dot resp"></span>response <span class="dot idle"></span>idle <span class="dot err"></span>error</div>
<script>
const canvas=document.getElementById('scene'),ctx=canvas.getContext('2d');
const panel=document.getElementById('panel'),tokenInput=document.getElementById('token');
let state=null, nodes=[], angle=0, selected=null, lastFetch=0;
tokenInput.value=sessionStorage.getItem('aionTempleToken')||'';
function resize(){canvas.width=innerWidth*devicePixelRatio;canvas.height=innerHeight*devicePixelRatio;ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0)}
addEventListener('resize',resize);resize();
function statusColor(w){
  const s=(w.status||'').toLowerCase();
  if((w.last_persisted_contact||{}).response_received)return '#ffd166';
  if(s==='error')return '#ff6d6d';
  if(s==='running')return '#61a8ff';
  if(['working','plan_met'].includes(s))return '#59e391';
  return '#7f8b99';
}
function project(x,y,z){
  const w=innerWidth,h=innerHeight,depth=700;
  const scale=depth/(depth+z+450);
  return {x:w/2+x*scale,y:h/2+y*scale,scale};
}
function draw(){
  ctx.clearRect(0,0,innerWidth,innerHeight);
  const g=ctx.createRadialGradient(innerWidth/2,innerHeight/2,10,innerWidth/2,innerHeight/2,Math.min(innerWidth,innerHeight)*.7);
  g.addColorStop(0,'#0d1e34');g.addColorStop(1,'#030509');ctx.fillStyle=g;ctx.fillRect(0,0,innerWidth,innerHeight);
  nodes=[];angle+=0.0015;
  const core=project(0,0,-80);
  ctx.beginPath();ctx.arc(core.x,core.y,34,0,Math.PI*2);ctx.fillStyle='#9bd3ff';ctx.shadowBlur=28;ctx.shadowColor='#62b4ff';ctx.fill();ctx.shadowBlur=0;
  ctx.fillStyle='#dff3ff';ctx.font='12px system-ui';ctx.textAlign='center';ctx.fillText('AION CORE',core.x,core.y+55);
  const workers=(state&&state.workers)||Array.from({length:100},(_,i)=>({worker_id:'aion-net-'+String(i+1).padStart(3,'0'),status:'offline',shard:i%4}));
  workers.forEach((w,i)=>{
    const ring=i%4, ringIndex=Math.floor(i/4), count=25;
    const a=(ringIndex/count)*Math.PI*2+angle*(ring%2?1:-1)+ring*.45;
    const radius=145+ring*72;
    let x=Math.cos(a)*radius, z=Math.sin(a)*radius;
    const y=Math.sin(a*1.7+ring)*42 + (ring-1.5)*18;
    const ca=Math.cos(.55),sa=Math.sin(.55); const yy=y*ca-z*sa, zz=y*sa+z*ca;
    const p=project(x,yy,zz);
    const r=Math.max(3.3,6.2*p.scale);
    ctx.strokeStyle='rgba(79,126,174,.13)';ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(core.x,core.y);ctx.lineTo(p.x,p.y);ctx.stroke();
    ctx.beginPath();ctx.arc(p.x,p.y,r,0,Math.PI*2);ctx.fillStyle=statusColor(w);ctx.fill();
    if(w.scheduled_now){ctx.strokeStyle='#d6ecff';ctx.lineWidth=1;ctx.stroke()}
    nodes.push({x:p.x,y:p.y,r:Math.max(9,r+5),w});
  });
  requestAnimationFrame(draw);
}
draw();
function esc(v){return String(v??'—').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function showWorker(w){
  selected=w.worker_id; const c=w.last_persisted_contact||{}, live=w.last_contact||{}, d=w.last_daily_accountability||{};
  panel.classList.remove('hidden');
  panel.innerHTML='<div class="k">worker</div><div class="v"><b>'+esc(w.worker_id)+'</b></div>'+
  '<div class="grid">'+
  '<div class="metric"><b>'+esc(w.status)+'</b><span>status</span></div>'+
  '<div class="metric"><b>'+esc(w.shard)+'</b><span>shard</span></div>'+
  '</div><br>'+
  '<div class="k">intent lane</div><div class="v">'+esc(w.lane)+'</div>'+
  '<div class="k">preferred channel</div><div class="v">'+esc(w.preferred_channel)+'</div>'+
  '<div class="k">scheduled now</div><div class="v">'+esc(w.scheduled_now)+'</div>'+
  '<div class="k">last target</div><div class="v">'+esc(c.target||live.target_id)+'</div>'+
  '<div class="k">site / interaction</div><div class="v">'+(c.interaction_url?'<a target="_blank" rel="noreferrer" href="'+esc(c.interaction_url)+'">'+esc(c.interaction_url)+'</a>':'—')+'</div>'+
  '<div class="k">result</div><div class="v">'+esc(c.result_class||live.result_class||live.error)+'</div>'+
  '<div class="k">response</div><div class="v">'+esc(c.response_received)+'</div>'+
  '<div class="k">topic</div><div class="v">'+esc(c.conversation_topic||w.lane)+'</div>'+
  '<div class="k">safe response intelligence</div><div class="v"><pre style="white-space:pre-wrap">'+esc(JSON.stringify(w.last_response_intelligence||{},null,2))+'</pre></div>'+
  '<div class="k">updated</div><div class="v">'+esc(w.updated_at||c.timestamp)+'</div>';
}
canvas.addEventListener('click',e=>{
  let best=null,bd=1e9; for(const n of nodes){const d=(e.clientX-n.x)**2+(e.clientY-n.y)**2;if(d<n.r*n.r&&d<bd){best=n;bd=d}}
  if(best)showWorker(best.w); else {panel.classList.add('hidden');selected=null}
});
async function refresh(){
  const token=tokenInput.value.trim(); if(!token)return;
  try{
    const r=await fetch('/temple/live/state',{headers:{Authorization:'Bearer '+token},cache:'no-store'});
    if(!r.ok)throw new Error('HTTP '+r.status);
    state=await r.json(); lastFetch=Date.now();
    document.getElementById('clock').textContent='updated '+new Date(state.generated_at).toLocaleTimeString();
    document.getElementById('workers').textContent=state.core.active_worker_count+'/'+state.core.worker_count+' workers active';
    const f=state.funnel;document.getElementById('funnel').textContent=f.machine_responses+' responses / '+f.settled_purchase_entitlements+' settled entitlements';
    if(selected){const w=state.workers.find(x=>x.worker_id===selected);if(w)showWorker(w)}
  }catch(e){document.getElementById('clock').textContent='connection '+e.message}
}
document.getElementById('connect').onclick=()=>{sessionStorage.setItem('aionTempleToken',tokenInput.value.trim());refresh()};
setInterval(refresh,5000); if(tokenInput.value)refresh();
</script>
</body>
</html>"""
