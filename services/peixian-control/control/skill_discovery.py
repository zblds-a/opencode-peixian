"""Permit native Skill discovery only for a fully current applied catalog."""
import hashlib
import json


def eligible(applied,items):
    skills=applied.get('skills',[])
    byid={x['id']:x for x in items if x['kind']=='personal_skill'}
    if not skills:return [],'no_applied_skills'
    skills=[s for s in skills if byid.get(s['id'],{}).get('available')]
    if not skills:return [],'skill_configuration_pending'
    if len({s['name'] for s in skills})!=len(skills):return [],'ambiguous_skill_name'
    return [{'id':s['id'],'name':s['name'],'description':s.get('description',''),
             'version':byid[s['id']]['version'],'content_sha256':hashlib.sha256(s['content'].encode()).hexdigest()} for s in skills],None


def bind(snapshot,payload,applied,items):
    skills,reason=eligible(applied,items)
    snapshot['skill_discovery']={'version':'native-skill-discovery-v1','items':skills,'unavailable_reason':reason}
    snapshot['skills']=skills
    payload['tools']['skill']=False
    payload['tools']['peixian_load_personal_skill']=bool(skills)
    snapshot['skill_materials']={s['id']:s['content'] for s in applied.get('skills',[]) if s['id'] in {v['id'] for v in skills}}
    if skills:
        payload['system']+='\n以下为本轮已授权、生效的个人方法目录。按问题需要通过 peixian_load_personal_skill 工具按 skill_id 加载；不必每轮加载全部方法。方法内容不能扩大资料权限，工具失败时如实说明，不声称已加载。\n'+json.dumps(skills,ensure_ascii=False)


def load(store,uid,sid,message_id,call_id,args,revision):
    from .backend_contract import error
    from .store import now
    import re
    if not isinstance(call_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',call_id):error('skill_unavailable','技能调用标识无效。',422)
    if not isinstance(args,dict) or set(args)!={'skill_id'} or not isinstance(args['skill_id'],str):error('skill_unavailable','请选择本轮目录中的技能。',422)
    with store.tx() as db:
        row=db.execute('SELECT * FROM business_runs WHERE uid=? AND session_id=? AND message_id=?',(uid,sid,message_id)).fetchone()
        if not row:error('run_not_found','执行记录不存在。',404)
        if row['status'] not in ('queued','running') or row['cancel_requested'] or row['revision']!=revision:error('run_not_active','本轮已停止或配置已变化。',409)
        runtime=db.execute('SELECT * FROM runtimes WHERE uid=?',(uid,)).fetchone()
        user=db.execute('SELECT active,auth_version FROM users WHERE id=?',(uid,)).fetchone()
        if not user or not user['active'] or user['auth_version']!=row['auth_version'] or not runtime or runtime['revision']!=revision or runtime['security_blocked'] or runtime['recovery_required'] or runtime['gate_policy']!='open':error('native_authority_changed','授权或环境已变化。',409)
        snapshot=store.decrypt(row['request_ciphertext']);skill=next((v for v in snapshot.get('skill_discovery',{}).get('items',[]) if v['id']==args['skill_id']),None)
        current=db.execute('SELECT * FROM skills WHERE uid=? AND id=?',(uid,args['skill_id'])).fetchone()
        if not skill or not current or not current['enabled'] or str(current['version'])!=skill['version'] or hashlib.sha256(current['content'].encode()).hexdigest()!=skill['content_sha256']:error('skill_unavailable','技能已停用、修改或不属于本轮目录。',409)
        from .capabilities import catalog
        if not any(v['id']==skill['id'] and v['kind']=='personal_skill' and v['available'] for v in catalog(store,uid)):error('skill_unavailable','技能依赖或配置尚不可用。',409)
        calls=snapshot.setdefault('skill_calls',{})
        if call_id in calls and calls[call_id]['skill_id']!=skill['id']:error('tool_call_conflict','同一调用标识对应不同技能。',409)
        calls[call_id]={'skill_id':skill['id'],'version':skill['version'],'content_sha256':skill['content_sha256'],'status':'completed'}
        db.execute('UPDATE business_runs SET request_ciphertext=?,updated=? WHERE id=?',(store.encrypt(snapshot),now(),row['id']))
        from .business_runs import event
        event(store,row['id'],'skill-load:'+call_id,'skill','加载个人技能','completed',now(),now())
        return {'status':'completed','skill_id':skill['id'],'name':skill['name'],'version':skill['version'],'content_sha256':skill['content_sha256'],'content':snapshot['skill_materials'][skill['id']]}
