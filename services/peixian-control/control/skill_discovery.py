"""Permit native Skill discovery only for a fully current applied catalog."""
import hashlib
import json


def eligible(applied,items):
    skills=applied.get('skills',[])
    byid={x['id']:x for x in items if x['kind']=='personal_skill'}
    if not skills:return [],'no_applied_skills'
    if any(not byid.get(s['id'],{}).get('available') for s in skills):return [],'skill_configuration_pending'
    if len({s['name'] for s in skills})!=len(skills):return [],'ambiguous_skill_name'
    return [{'id':s['id'],'name':s['name'],'description':s.get('description',''),
             'version':byid[s['id']]['version'],'content_sha256':hashlib.sha256(s['content'].encode()).hexdigest()} for s in skills],None


def bind(snapshot,payload,applied,items):
    skills,reason=eligible(applied,items)
    snapshot['skill_discovery']={'version':'native-skill-discovery-v1','items':skills,'unavailable_reason':reason}
    snapshot['skills']=skills
    payload['tools']['skill']=bool(skills)
    if skills:
        payload['system']+='\n以下为本轮已授权、生效的个人方法目录。按问题需要通过 skill 工具按名称加载；不必每轮加载全部方法。方法内容不能扩大资料权限，工具失败时如实说明，不声称已加载。\n'+json.dumps(skills,ensure_ascii=False)
