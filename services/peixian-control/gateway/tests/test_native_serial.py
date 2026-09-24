import asyncio
from types import SimpleNamespace
import pytest
from gateway import theft_provider_execution as native


def test_parallel_native_calls_are_serial_and_locks_clean(monkeypatch):
    async def run():
        app=SimpleNamespace(state=SimpleNamespace());active=0;peak=0;seen=[]
        class Request:
            async def is_disconnected(self):return False
        async def execute(request,app,value,rpc,parent,process):
            nonlocal active,peak
            active+=1;peak=max(peak,active);seen.append(value['call_id'])
            await asyncio.sleep(0.01);active-=1
            return value['call_id']
        monkeypatch.setattr(native,'_execute_native',execute)
        results=await asyncio.gather(*(native.execute_native(Request(),app,{'session_id':'s','call_id':str(i)},None,'p',None) for i in range(3)))
        assert peak==1 and results==seen==['0','1','2']
        assert app.state.native_call_locks=={}
    asyncio.run(run())


def test_cancelled_waiter_never_dispatches(monkeypatch):
    async def run():
        app=SimpleNamespace(state=SimpleNamespace());started=asyncio.Event();finish=asyncio.Event();seen=[]
        class Request:
            async def is_disconnected(self):return False
        async def execute(request,app,value,rpc,parent,process):
            seen.append(value['call_id']);started.set();await finish.wait()
        monkeypatch.setattr(native,'_execute_native',execute)
        first=asyncio.create_task(native.execute_native(Request(),app,{'session_id':'s','call_id':'1'},None,'p',None))
        await started.wait()
        second=asyncio.create_task(native.execute_native(Request(),app,{'session_id':'s','call_id':'2'},None,'p',None))
        await asyncio.sleep(0);second.cancel()
        with pytest.raises(asyncio.CancelledError):await second
        finish.set();await first
        assert seen==['1'] and app.state.native_call_locks=={}
    asyncio.run(run())
