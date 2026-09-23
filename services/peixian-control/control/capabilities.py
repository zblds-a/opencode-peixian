import json
from fastapi import Depends, Request
from .backend_contract import error, require_v6, page_values
from .concurrency import blocking_endpoint
from .connections import resolved_bindings
from .store import encode, now


def dependencies(db,sid):
    row=db.execute('SELECT dependencies FROM skill_profiles WHERE sid=?',(sid,)).fetchone()
    return json.loads(row[0]) if row else []


def save_dependencies(db,uid,sid,data):
    if 'dependency_ids' not in data:return
    values=data['dependency_ids']
    if not isinstance(values,list) or len(values)>20 or any(not isinstance(v,str) for v in values) or len(set(values))!=len(values):error('invalid_dependencies','依赖列表无效')
    for pid in values:
        from .data_plugin_policy import installable
        if not installable(pid):error("dependency_archived","依赖的资料插件已归档",409)
        if not db.execute("SELECT 1 FROM grants WHERE uid=? AND kind='plugin' AND resource=?",(uid,pid)).fetchone():error('dependency_forbidden','依赖插件未授权',403)
    db.execute('INSERT INTO skill_profiles(sid,dependencies,updated) VALUES(?,?,?) ON CONFLICT(sid) DO UPDATE SET dependencies=excluded.dependencies,updated=excluded.updated',(sid,encode(values),now()))


def catalog(store,uid):
    require_v6(store)
    with store.read(snapshot=True) as db:
        runtime=db.execute('SELECT * FROM runtimes WHERE uid=?',(uid,)).fetchone()
        applied=store.decrypt(runtime['applied_spec_ciphertext']) if runtime and runtime['applied_spec_ciphertext'] else {}
        ready=runtime and runtime['status']=='ready' and runtime['gate_policy']=='open' and not runtime['security_blocked'] and not runtime['recovery_required']
        plugins={p['id']:p for p in applied.get('plugins',[])};skills={p['id']:p for p in applied.get('skills',[])};items=[]
        for g in db.execute("SELECT resource FROM grants WHERE uid=? AND kind='plugin'",(uid,)):
            from .data_plugin_policy import installable
            if not installable(g[0]):continue
            installed=db.execute('SELECT * FROM installs WHERE uid=? AND plugin=?',(uid,g[0])).fetchone()
            p=db.execute('SELECT * FROM plugins WHERE id=? AND version=?',(g[0],installed['version'])).fetchone() if installed else db.execute('SELECT * FROM plugins WHERE id=? AND enabled=1 ORDER BY rowid DESC LIMIT 1',(g[0],)).fetchone()
            if not p:continue
            manifest=json.loads(p['manifest']);_,missing=resolved_bindings(db,p['id'],p['version'],manifest)
            reason='not_installed' if not installed else 'disabled' if not installed['enabled'] or not p['enabled'] else 'connection_unavailable' if missing else 'configuration_pending' if p['id'] not in plugins or plugins[p['id']]['version']!=p['version'] or plugins[p['id']].get('options')!=store.decrypt(installed['config']) else 'runtime_unavailable' if not ready else None
            items.append({'id':p['id'],'kind':'plugin','name':p['name'],'description':p['description'],'version':p['version'],'category':'plugin','recommended':False,'enabled':bool(installed and installed['enabled'] and p['enabled']),'owned':bool(installed),'scope':'personal','available':reason is None,'unavailable_reason':reason,'dependency_ids':[]})
        byid={x['id']:x for x in items}
        from .official_methods import identify,public as official_public
        for p in db.execute('SELECT * FROM skills WHERE uid=? ORDER BY name',(uid,)):
            official=identify(p['content'])
            deps=list(dict.fromkeys(dependencies(db,p['id'])+(official['dependency_ids'] if official else [])))
            reason='unpublished_method' if official and official['state']!='published' else 'disabled' if not p['enabled'] else 'dependency_unavailable' if any(not byid.get(x,{}).get('available') for x in deps) else 'configuration_pending' if p['id'] not in skills or skills[p['id']]['content']!=p['content'] else 'runtime_unavailable' if not ready else None
            items.append({'id':p['id'],'kind':'personal_skill','name':p['name'],'description':p['description'],'version':str(p['version']),'category':'skill','recommended':False,'enabled':bool(p['enabled']),'owned':True,'scope':'personal','available':reason is None,'unavailable_reason':reason,'dependency_ids':deps,'official_method':official_public(official) if official else None})
        for p in db.execute('SELECT * FROM templates ORDER BY name'):
            official=identify(p['content'])
            items.append({'id':p['id'],'kind':'official_skill','name':p['name'],'description':p['description'],'version':None,'category':'template','recommended':False,'enabled':True,'owned':False,'scope':'official','available':False,'unavailable_reason':'unpublished_method' if official and official['state']!='published' else 'copy_required','dependency_ids':official['dependency_ids'] if official else [],'official_method':official_public(official) if official else None})
        return items


def check_selection(store,uid,data):
    entries={(x['kind'],x['id']):x for x in catalog(store,uid)}
    for field,kind in [('skill_ids','personal_skill'),('plugin_ids','plugin')]:
        for identity in data[field]:
            item=entries.get((kind,identity))
            if not item:error('capability_not_found','所选能力不存在或未授权',404,{field:'请重新选择'})
            if not item['available']:error('capability_unavailable','所选能力或依赖尚不可用',409,{field:item['unavailable_reason']})


def register(app):
    from .app import PREFIX,normal
    @app.get(PREFIX+'/capabilities')
    @blocking_endpoint(app)
    def capability_catalog(request:Request,page:int=1,page_size:int=100,user=Depends(normal)):
        offset=page_values(page,page_size);values=catalog(app.state.store,user['uid'])
        return {'items':values[offset:offset+page_size],'total':len(values),'page':page,'page_size':page_size}
