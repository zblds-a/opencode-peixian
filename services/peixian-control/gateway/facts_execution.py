"""Authenticated fixed facts bridge; no caller-selected URLs, files or commands."""
import asyncio
import base64
import contextlib
import json
import os
from pathlib import Path
import signal
import tempfile
import httpx
from fastapi import HTTPException, Request
from .http_utils import json_body
from .plugin_test import specification

HELPERS={'peixian_get_scenario_context','peixian_prepare_scenario_facts','peixian_check_scenario_summary'}
MODULES=('funds','calls','portrait','composite','night','vehicle','lookup')
TOOLS={'peixian_get_'+m+'_records':m for m in MODULES}
from shared.theft_provider import CATALOG
from shared.theft_provider_v2 import CATALOG as PROVIDER_V2
PROVIDER_TOOLS={'peixian_query_'+m:m for m in set(CATALOG)|set(PROVIDER_V2)}

async def process(input):
    with tempfile.TemporaryDirectory(prefix='px-facts-') as temporary:
        child=await asyncio.create_subprocess_exec(os.environ.get('BUN_EXECUTABLE','/usr/local/bin/bun'),str(Path(__file__).with_name('facts_worker.mjs')),
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,
            env={'PATH':os.defpath,'HOME':temporary,'TMPDIR':temporary,'LANG':'C.UTF-8'},cwd=temporary,start_new_session=os.name=='posix')
        try:
            child.stdin.write(json.dumps(input).encode());await child.stdin.drain();child.stdin.close()
            async with asyncio.timeout(70):
                raw=bytearray()
                while chunk:=await child.stdout.read(16384):
                    raw.extend(chunk)
                    if len(raw)>2*1024*1024:raise ValueError('facts_output_limit')
                await child.wait()
            value=json.loads(raw)
            if child.returncode or value.get('ok') is not True:raise ValueError('facts_execution_failed')
            return value['value']
        finally:
            if os.name=='posix':
                with contextlib.suppress(ProcessLookupError):os.killpg(child.pid,signal.SIGKILL)
            elif child.returncode is None:child.kill()
            await child.wait()

def register(app):
    @app.get('/internal/facts/status')
    async def status():
        root=app.state.settings.managed_root
        try:
            plugins=json.loads((root/'plugin-tests.json').read_text())
            modules=[m for m in MODULES if 'peixian-records-'+m in plugins]
            ready=(root/'platform-facts/engine.mjs').is_file() and bool(modules)
        except (OSError,ValueError):modules=[];ready=False
        return {'protocol':'facts-coordinator-v1','ready':ready,'modules':modules}
    @app.post('/internal/facts/execute')
    async def execute(request:Request):
        value=await json_body(request,16384)
        if not isinstance(value,dict) or set(value) not in ({'session_id','message_id','tool','args'},{'session_id','message_id','tool','args','call_id'}) or not isinstance(value['tool'],str) or value['tool'] not in HELPERS|set(TOOLS)|set(PROVIDER_TOOLS):raise HTTPException(422,'资料调用无效')
        for name in ('session_id','message_id'):
            if not isinstance(value[name],str) or not value[name] or len(value[name])>150 or any(not(c.isalnum() or c in '_-') for c in value[name]):raise HTTPException(422,'执行身份无效')
        config=app.state.settings;manager=getattr(app.state,'runtime_management',None)
        if not manager:raise HTTPException(409,'资料运行协议未启用')
        gate=manager.gate
        gate.require_egress()
        # ToolContext.messageID is an assistant message. Resolve its parent from
        # the authenticated Agent, never from model arguments or newest-session guesses.
        authorization=base64.b64encode(('opencode:'+config.opencode_password).encode()).decode()
        result=await app.state.client.get(config.opencode_url+'/session/'+value['session_id']+'/message/'+value['message_id'],
            params={'directory':'/workspace'},headers={'Authorization':'Basic '+authorization,'x-opencode-directory':'/workspace'},timeout=5)
        result.raise_for_status();info=result.json().get('info',{})
        if info.get('role')!='assistant' or info.get('sessionID')!=value['session_id'] or not isinstance(info.get('parentID'),str):raise HTTPException(409,'执行身份无法核对')
        async def rpc(action,**fields):
            response=await app.state.client.post(config.control_url+'/internal/runtime/facts',headers={'X-Runtime-Key':config.runtime_key},
                json={'action':action,'runtime_id':config.runtime_id,'revision':config.revision,'gateway_boot_id':gate.boot_id,**fields},timeout=5)
            if response.status_code>=400:
                # Only native admission runs before any data dispatch. Never pass
                # upstream messages/stack traces through this public boundary.
                if action == 'native_prepare':
                    try:
                        detail=response.json()
                        detail=detail.get('detail',detail)
                        code=detail.get('code') if isinstance(detail,dict) else None
                    except ValueError:code=None
                    messages={
                        'identity_parameter_invalid':'请使用用户已确认的原始单人身份号码。person-* 是展示引用，不能填入 person_identity；不要要求用户确认内部引用。',
                        'scope_unconfirmed':'工具参数与已确认条件不一致，请补充或确认查询范围。',
                        'scope_missing':'请补充查询所需对象、时间或范围。',
                        'unsupported_scope':'此接口不支持所要求的筛选条件，请先确认受支持范围。',
                        'real_provider_disabled':'资料连接尚未配置，请联系管理员恢复当前资料连接。',
                        'real_provider_configuration_invalid':'资料连接配置尚未通过校验，请联系管理员。',
                        'provider_connection_mismatch':'资料插件与连接绑定不一致，请联系管理员。',
                        'outside_acceptance_scope':'当前对象或位置不在已授权测试范围。',
                    }
                    # A duplicate/in-progress call can already have dispatched.
                    if code in messages:
                        raise HTTPException(409,{'code':code,'dispatch_status':'not_dispatched',
                            'message':messages[code]+' 本次未访问资料接口。'})
                raise HTTPException(409,'当前资料能力不可用或执行已停止')
            return response.json()
        if value['tool'] in PROVIDER_TOOLS:
            from .theft_provider_execution import execute,execute_native
            if 'call_id' in value and value['args']!={}:
                parts=result.json().get('parts',[])
                matches=[part for part in parts if part.get('type')=='tool' and part.get('callID')==value['call_id'] and part.get('tool')==value['tool']]
                if len(matches)!=1 or matches[0].get('state',{}).get('input')!=value['args']:
                    raise HTTPException(409,'模型工具调用身份或参数无法核对')
                return await execute_native(request,app,value,rpc,info['parentID'],process)
            return await execute(request,app,value,rpc,info['parentID'],process)
        admitted=await rpc('begin',session_id=value['session_id'],message_id=info['parentID'])
        identity={'run_id':admitted['run_id'],'operation':admitted['operation']}
        plan=admitted['plan'];args=value['args'];selected=value['tool']
        async def call(action,**fields):return await rpc(action,**identity,**fields)
        async def watched(input):
            task=asyncio.create_task(process(input))
            try:
                while not task.done():
                    done,_=await asyncio.wait({task},timeout=0.5)
                    if done:break
                    gate.require_egress()
                    await call('authorize')
                    if await request.is_disconnected():raise asyncio.CancelledError()
                return await task
            finally:
                if not task.done():task.cancel()
                await asyncio.gather(task,return_exceptions=True)
        try:
            from shared.developer_plan import validate
            try:validate(plan)
            except (ValueError,KeyError,TypeError):raise HTTPException(409,'资料能力与规则版本无法核对') from None
            scene=plan['scenario']['scenario_id']
            if selected in HELPERS:
                expected={'scenario_id','claims'} if selected.endswith('summary') else {'scenario_id','methods'} if selected.endswith('facts') and isinstance(args,dict) and 'methods' in args else {'scenario_id'}
                if not isinstance(args,dict) or set(args)!=expected or args.get('scenario_id')!=scene:raise HTTPException(422,'本轮场景参数不一致')
            elif args!={}:raise HTTPException(422,'资料查询不接受额外参数')
            if selected=='peixian_get_scenario_context':return plan['scenario']
            if selected=='peixian_check_scenario_summary':return await call('check',claims=args['claims'])
            methods=args.get('methods',plan['methods']) if selected in HELPERS else []
            if selected in HELPERS and (not isinstance(methods,list) or not methods or any(not isinstance(m,str) for m in methods) or len(set(methods))!=len(methods) or any(m not in plan['methods'] for m in methods)):raise HTTPException(422,'方法不在本轮计划内')
            mapping={'night':['night'],'companions':['portrait'],'funds':['funds'],'relations':['lookup','composite'],'calls':['calls'],'vehicles':['vehicle']}
            modules=list(dict.fromkeys(m for method in methods for m in mapping[method])) if selected in HELPERS else [TOOLS[selected]]
            for module in modules:
                await call('authorize',module=module)
                if not (await call('reserve',module=module))['reserved']:continue
                try:
                    spec=specification(config.managed_root,'peixian-records-'+module)
                    response=await watched({**spec,'action':'invoke','tool':'peixian_get_'+module+'_records'})
                    await call('complete',module=module,status='completed',response=response)
                except (ValueError,httpx.HTTPError,TimeoutError):
                    await call('complete',module=module,status='unknown')
            current=(await call('read'))['state']
            if selected in TOOLS:
                item=current['modules'].get(TOOLS[selected],{})
                if item.get('status')!='completed':raise HTTPException(409,'资料结果尚未确认，本轮不会重试')
            # Include every started method, including its still-missing dependencies.
            # A lookup-only result must not claim the two-module relations method complete.
            required=list(dict.fromkeys(m for method in plan['methods'] if set(mapping[method]) & set(current['modules']) for m in mapping[method]))
            from shared.task_scope import scoped
            filtered={m:scoped(plan,m,current['modules'][m]['response']) for m in required if current['modules'].get(m,{}).get('status')=='completed'}
            responses={m:{**value,'records':value['items']} for m,value in filtered.items()}
            table=await watched({'action':'compile','engine':str(config.managed_root/'platform-facts/engine.mjs'),
                'context':{**plan['scenario'],'required_modules':required},'responses':responses})
            await call('table',table=table)
            # Even a direct query produces code-derived facts in this same Run.
            # Preserve the query payload while keeping fact computation out of the model.
            return {**filtered[TOOLS[selected]],'facts_table':table} if selected in TOOLS else table
        finally:
            with contextlib.suppress(httpx.HTTPError,HTTPException):await call('finish')
