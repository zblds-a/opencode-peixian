"""Fixed private Gateway callbacks. Never a browser HTTP forwarding surface."""
import hmac
import json
import threading
from fastapi import HTTPException, Request
from .facts_runtime import FactsState, reject
from .backend_contract import require_v6


def register(app):
    # One owner per Control process. A restarted process cannot resend pending reads.
    state = None
    provider_state = None
    initialization = threading.Lock()
    def execute(data, credential):
        nonlocal state,provider_state
        store = app.state.store
        require_v6(store)
        with initialization:
            if state is None: state = FactsState(store)
            if provider_state is None:
                from .theft_provider_state import ProviderState
                provider_state=ProviderState(store)
        if not isinstance(data,dict) or len(json.dumps(data).encode()) > 2*1024*1024: raise HTTPException(422,"事实协议无效")
        if any(not isinstance(data.get(k),str) or not 1<=len(data[k])<=160 for k in ('runtime_id','action','gateway_boot_id')) or type(data.get('revision')) is not int: raise HTTPException(422,'事实协议无效')
        for k in ('run_id','operation','session_id','message_id','module','call_id','tool','digest'):
            if k in data and (not isinstance(data[k],str) or not 1<=len(data[k])<=160):raise HTTPException(422,'事实协议无效')
        runtime = store.one("SELECT * FROM runtimes WHERE id=?",(data.get('runtime_id'),))
        if not runtime or len(credential)<32 or not hmac.compare_digest(credential,store.decrypt(runtime['spec']).get('runtime_key','')): raise HTTPException(403,"运行环境身份无效")
        if runtime['revision'] != data.get('revision'): reject('facts_revision_changed')
        if runtime['gateway_boot_id'] != data['gateway_boot_id']: reject('facts_gateway_changed')
        uid = runtime['uid']; action = data.get('action')
        if action=='native_skill':
            if set(data)!={'action','runtime_id','revision','gateway_boot_id','session_id','message_id','call_id','args'}:raise HTTPException(422,'技能调用协议无效')
            from .skill_discovery import load
            return load(store,uid,data['session_id'],data['message_id'],data['call_id'],data['args'],data['revision'])
        if action=='native_prepare':
            if set(data)!={'action','runtime_id','revision','gateway_boot_id','session_id','message_id','call_id','tool','args'}:
                raise HTTPException(422,'原生资料调用协议无效')
            from .native_tool_gate import prepare
            return prepare(store,uid,data['session_id'],data['message_id'],data['call_id'],data['tool'],data['args'],data['revision'])
        if action=='native_review_failed':
            if set(data)!={'action','runtime_id','revision','gateway_boot_id','run_id','call_id','digest'}:
                raise HTTPException(422,'原生意图核对协议无效')
            from .native_tool_gate import review_failed
            return review_failed(store,uid,data['run_id'],data['call_id'],data['digest'],data['revision'])
        if action=='native_approve':
            if set(data)!={'action','runtime_id','revision','gateway_boot_id','run_id','call_id','digest','decision'}:
                raise HTTPException(422,'原生意图核对协议无效')
            from .native_tool_gate import approve
            return approve(store,uid,data['run_id'],data['call_id'],data['digest'],data['decision'],data['revision'])
        engine=provider_state if action.startswith('provider_') else state
        if action.startswith('provider_'):
            action=action[len('provider_'):]
            if action not in ('begin','finish','authorize','reserve','dispatch','complete','read'):raise HTTPException(422,'不支持的资料操作')
        if action == 'begin':
            if set(data) != {'action','runtime_id','revision','gateway_boot_id','session_id','message_id'}: raise HTTPException(422,'事实协议无效')
            row=store.one("SELECT * FROM business_runs WHERE uid=? AND session_id=? AND message_id=?",(uid,data['session_id'],data['message_id']))
            if not row: raise HTTPException(404,'执行记录不存在')
            operation=engine.begin(uid,row['id'],data['revision'],data['gateway_boot_id'])
            return {'uid':uid,'run_id':row['id'],'revision':data['revision'],'operation':operation,**engine.read(uid,row['id'],data['revision'])}
        if not {'action','runtime_id','revision','run_id','operation'} <= set(data):raise HTTPException(422,'事实协议无效')
        args=(uid,data['run_id'],data['revision'],data['operation'])
        if action=='finish':engine.finish(*args);return {'ok':True}
        if action=='authorize':engine.check(*args,data.get('module'));return {'ok':True}
        if action=='reserve':return {'reserved':engine.reserve(*args,data.get('module'))}
        if action=='dispatch' and engine is provider_state:engine.dispatch(*args,data.get('module'));return {'ok':True}
        if action=='complete':return {'status':engine.complete(*args,data.get('module'),data.get('status'),data.get('response'))}
        if action=='read':engine.check(*args);return engine.read(*args[:3])
        if action=='table':engine.save_table(*args,data.get('table'));return {'ok':True}
        if action=='check':return engine.check_claims(*args,data.get('claims'))
        raise HTTPException(422,'不支持的事实操作')

    @app.post('/internal/runtime/facts')
    async def facts(request:Request):
        # Limit the decoded body before handing work to the bounded DB pool.
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>2*1024*1024:raise HTTPException(413,'事实状态超过限制')
        try:data=json.loads(raw)
        except ValueError:raise HTTPException(422,'事实协议无效') from None
        credential=request.headers.get('X-Runtime-Key','')
        try:return await app.state.db_work.run(execute,data,credential)
        except HTTPException:
            def denied():
                if not isinstance(data,dict) or not all(isinstance(data.get(k),str) for k in ('runtime_id','run_id','module')):return
                from .facts_runtime import MODULES,capability
                from .business_runs import event
                from .store import now
                if data['module'] not in MODULES:return
                s=app.state.store
                runtime=s.one('SELECT * FROM runtimes WHERE id=?',(data['runtime_id'],))
                if not runtime or not hmac.compare_digest(credential,s.decrypt(runtime['spec']).get('runtime_key','')):return
                if not s.one('SELECT 1 FROM business_runs WHERE id=? AND uid=?',(data['run_id'],runtime['uid'])):return
                event(s,data['run_id'],'facts.denied.'+data['module'],'authorization','资料能力准入未通过','rejected',completed=now(),capability=capability(data['module']))
            await app.state.db_work.run(denied)
            raise
