"""Fixed, tools-disabled model planning RPC; durable no-resend receipts."""
import asyncio
import hashlib
import json
import os
import re
from fastapi import Request,HTTPException
from .http_utils import fixed_base


def register(app):
    @app.post('/internal/runtime/planning')
    async def planning(request:Request):
        data=await request.json()
        if not isinstance(data,dict) or set(data)!={'call_id','revision','model_id','system','input'} or not re.fullmatch('[a-f0-9]{32}',str(data['call_id'])) or not isinstance(data['system'],str) or not isinstance(data['input'],dict) or len(json.dumps(data).encode())>50000:raise HTTPException(422,'Invalid planning envelope')
        if data['revision']!=app.state.settings.revision:raise HTTPException(409,'Planning revision changed')
        gate=app.state.admission
        activity=await gate.admit('planning',resource=data['call_id'])
        try:
            folder=app.state.settings.activity_root/'planning-receipts'
            folder.mkdir(parents=True,exist_ok=True)
            path=folder/(data['call_id']+'.json')
            digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
            try:
                descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            except FileExistsError:
                try:prior=json.loads(path.read_text(encoding='utf-8'))
                except (OSError,ValueError):raise HTTPException(409,'Planning outcome unknown') from None
                if prior.get('digest')!=digest:raise HTTPException(409,'Planning identity conflict')
                if prior.get('status')=='completed':return prior['result']
                raise HTTPException(409,'Planning outcome unknown')
            with os.fdopen(descriptor,'w',encoding='utf-8') as target:
                json.dump({'digest':digest,'status':'sending'},target);target.flush();os.fsync(target.fileno())
            gate.require_egress()
            limit=int(os.getenv('PX_PLANNING_MAX_TOKENS','4096'))
            if not 256<=limit<=16384:raise HTTPException(503,'Invalid planning resource limit')
            body={'model':data['model_id'],'messages':[{'role':'system','content':data['system']},{'role':'user','content':json.dumps(data['input'],ensure_ascii=False)}],'stream':False,'max_tokens':limit,'temperature':0}
            async with asyncio.timeout(50):
                async with app.state.client.stream('POST',fixed_base(app.state.settings.relay_url)+'/v1/chat/completions',json=body,timeout=45) as response:
                    response.raise_for_status();raw=bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw)>65536:raise HTTPException(502,'Planning response limit')
            choice=json.loads(raw)['choices'][0]
            result={'content':choice['message']['content'],'finish_reason':choice.get('finish_reason')}
            if not isinstance(result['content'],str) or len(result['content'])>16000:raise HTTPException(502,'Invalid planning response')
            stage=path.with_suffix('.tmp')
            with stage.open('w',encoding='utf-8') as target:
                json.dump({'digest':digest,'status':'completed','result':result},target);target.flush();os.fsync(target.fileno())
            stage.replace(path)
            return result
        finally:gate.finish(activity)
