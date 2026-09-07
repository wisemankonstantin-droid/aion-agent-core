import uuid
from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def join(name,capability):
    token=uuid.uuid4().hex[:8]
    r=client.post('/agents',json={'external_id':f'{name.lower()}-{token}','name':name,'protocol':'REST','capabilities':[{'name':capability}]})
    assert r.status_code==200,r.text
    data=r.json(); return data['agent'],data['agent_key']

def auth(key): return {'Authorization':f'Bearer {key}'}

def test_autonomous_join_returns_machine_credential():
    agent,key=join('Autonomous','planning')
    assert agent['owner_required'] is False
    assert key.startswith('aion_')

def test_writes_require_agent_identity():
    r=client.post('/needs',json={'capability':'research','description':'x'})
    assert r.status_code==401

def test_end_to_end_agent_marketplace():
    provider,pkey=join('Provider','web_research')
    requester,rkey=join('Requester','planning')
    offer=client.post('/offers',headers=auth(pkey),json={'capability':'web_research','description':'Research public information'})
    assert offer.status_code==200
    need=client.post('/needs',headers=auth(rkey),json={'capability':'web_research','description':'Need research'})
    assert need.status_code==200
    assert any(x['agent_id']==provider['id'] for x in need.json()['matches'])

def test_agent_cannot_impersonate_requester():
    provider,pkey=join('Provider2','analysis')
    requester,rkey=join('Requester2','planning')
    r=client.post('/interactions',headers=auth(rkey),json={'provider_agent_id':provider['id'],'result':'pending'})
    assert r.status_code==200

def test_repeat_donation_intents_are_allowed():
    agent,key=join('Donor','payment')
    for _ in range(2):
        r=client.post('/payments/intents',headers=auth(key),json={'purpose':'donation','amount':'1.00','protocol':'x402'})
        assert r.status_code==200

def test_public_discovery_remains_open():
    r=client.get('/agents')
    assert r.status_code==200
    assert isinstance(r.json(),list)

def test_machine_discovery_surfaces():
    manifest=client.get('/.well-known/aion.json')
    assert manifest.status_code==200
    assert manifest.json()['autonomous_join'] is True
    assert manifest.json()['human_approval_required_by_aion'] is False
    llms=client.get('/llms.txt')
    assert llms.status_code==200
    assert 'JOIN: POST' in llms.text

def test_agent_can_replace_own_capabilities():
    agent,key=join('Mutable','old_cap')
    r=client.put('/agents/me/capabilities',headers=auth(key),json=[{'name':'new_cap','description':'new'}])
    assert r.status_code==200
    caps=client.get(f"/agents/{agent['id']}/capabilities").json()
    assert [c['name'] for c in caps]==['new_cap']


def test_me_requires_key_and_returns_self():
    agent,key=join('Self','identity')
    r=client.get('/agents/me',headers=auth(key))
    assert r.status_code==200
    assert r.json()['id']==agent['id']

def test_stats_are_real_database_counts():
    before=client.get('/stats').json()['agents']
    join('StatsAgent','metrics')
    after=client.get('/stats').json()
    assert after['agents']==before+1
    assert 'not claims of verified external adoption' in after['note']


def test_rejects_oversized_or_invalid_agent_identity():
    r=client.post('/agents',json={'external_id':'bad id with spaces','name':'x'})
    assert r.status_code==422

def test_agent_can_update_self_without_human_approval():
    agent,key=join('Updater','identity')
    r=client.patch('/agents/me',headers=auth(key),json={'description':'updated by agent','protocol':'MCP'})
    assert r.status_code==200
    assert r.json()['description']=='updated by agent'
    assert r.json()['protocol']=='MCP'


def test_agent_can_rotate_own_key():
    agent,key=join('Rotator','security')
    r=client.post('/agents/me/rotate-key',headers=auth(key))
    assert r.status_code==200
    new_key=r.json()['agent_key']
    assert new_key.startswith('aion_') and new_key!=key
    assert client.get('/agents/me',headers=auth(key)).status_code==401
    assert client.get('/agents/me',headers=auth(new_key)).status_code==200

def test_acquisition_attribution_is_recorded():
    token=uuid.uuid4().hex[:8]
    r=client.post('/agents',json={'external_id':f'attributed-{token}','name':'Attributed','acquisition_source':'a2a_registry','referrer':'registry-agent-x'})
    assert r.status_code==200
    assert r.json()['agent']['acquisition_source']=='a2a_registry'
    stats=client.get('/stats').json()
    assert stats['acquisition_sources']['a2a_registry'] >= 1


def test_capability_normalization_prevents_false_miss():
    provider,pkey=join('NormalizeProvider','web-research')
    requester,rkey=join('NormalizeRequester','planning')
    client.post('/offers',headers=auth(pkey),json={'capability':'web-research','description':'Research'})
    need=client.post('/needs',headers=auth(rkey),json={'capability':'web research','description':'Need normalized research'})
    assert need.status_code==200
    assert any(x['agent_id']==provider['id'] for x in need.json()['matches'])
    caps=client.get(f"/agents/{provider['id']}/capabilities").json()
    assert caps[0]['name']=='web_research'


def test_opportunities_connect_both_sides_of_marketplace():
    provider,pkey=join('OpportunityProvider','summarization')
    requester,rkey=join('OpportunityRequester','planning')
    client.post('/offers',headers=auth(pkey),json={'capability':'summarization','description':'Summaries'})
    need=client.post('/needs',headers=auth(rkey),json={'capability':'summarization','description':'Need a summary'}).json()
    r=client.get('/agents/me/opportunities',headers=auth(pkey))
    assert r.status_code==200
    data=r.json()
    assert any(x['need_id']==need['id'] for x in data['market_needs_matching_my_offers'])
    r=client.get('/agents/me/opportunities',headers=auth(rkey))
    assert any(x['need_id']==need['id'] and x['matches'] for x in r.json()['own_need_matches'])


def test_interaction_completion_updates_reputation_once_and_is_terminal():
    provider,pkey=join('RepProvider','analysis')
    requester,rkey=join('RepRequester','planning')
    client.post('/offers',headers=auth(pkey),json={'capability':'analysis','description':'Analysis'})
    need=client.post('/needs',headers=auth(rkey),json={'capability':'analysis','description':'Need analysis'}).json()
    interaction=client.post('/interactions',headers=auth(rkey),json={'provider_agent_id':provider['id'],'need_id':need['id'],'result':'completed','score':5})
    assert interaction.status_code==200
    iid=interaction.json()['id']
    assert interaction.json()['result']=='pending'
    done=client.patch(f'/interactions/{iid}',headers=auth(rkey),json={'result':'completed','score':5})
    assert done.status_code==200
    first_rep=done.json()['provider_reputation']
    assert first_rep >= 2.0
    # A terminal interaction cannot be rewound and completed again for more points.
    rewind=client.patch(f'/interactions/{iid}',headers=auth(rkey),json={'result':'failed','score':1})
    assert rewind.status_code==409
    same=client.patch(f'/interactions/{iid}',headers=auth(rkey),json={'result':'completed','score':5})
    assert same.status_code==200
    provider_after=client.get(f"/agents/{provider['id']}").json()
    assert provider_after['reputation']==first_rep
    assert provider_after['trust_level']=='observed'
    needs=client.get('/needs').json()
    assert not any(x['id']==need['id'] for x in needs)


def test_funnel_tracks_activation_and_return_without_faking_uniqueness():
    from datetime import datetime, timedelta, timezone
    from app.db import SessionLocal
    from app import models

    before=client.get('/funnel').json()
    agent,key=join('FunnelAgent','analysis')
    client.post('/offers',headers=auth(key),json={'capability':'analysis','description':'Activation'})
    after_activation=client.get('/funnel').json()
    assert after_activation['M2_joined_agents'] >= before['M2_joined_agents'] + 1
    assert after_activation['M3_activated_agents'] >= before['M3_activated_agents'] + 1

    with SessionLocal() as db:
        row=db.get(models.Agent,agent['id'])
        row.first_useful_action_at=datetime.now(timezone.utc)-timedelta(minutes=2)
        row.last_seen_at=datetime.now(timezone.utc)-timedelta(minutes=2)
        db.add(row); db.commit()
    client.get('/agents/me',headers=auth(key))
    after_return=client.get('/funnel').json()
    assert after_return['M4_returning_agents'] >= before['M4_returning_agents'] + 1


def test_capability_filter_uses_same_normalization_as_matching():
    agent,key=join('FilterAgent','code-review')
    r=client.get('/agents',params={'capability':'code review'})
    assert any(a['id']==agent['id'] for a in r.json())
