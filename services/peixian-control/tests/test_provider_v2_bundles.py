import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import zipfile

import pytest
from shared import theft_provider_v2 as adapter
from control.data_plugin_policy import ACTIVE_KINDS
from test_provider_contract_v2 import ID, REF, LIMITS, query, response


@pytest.fixture
def bundles(tmp_path):
    path=Path(__file__).resolve().parents[3]/'deploy/peixian/examples/theft_provider_v2/build.py'
    spec=importlib.util.spec_from_file_location('v2_bundle_builder',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.build(tmp_path)
    with pytest.raises(FileExistsError):module.build(tmp_path)
    return tmp_path


@pytest.mark.parametrize('kind',ACTIVE_KINDS)
def test_fixed_plugin_executes_only_own_read_contract(bundles,kind):
    pid='peixian-theft-'+kind.replace('_','-');tool='peixian_query_'+kind
    with zipfile.ZipFile(bundles/(pid+'-2.0.0.zip')) as z:
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['version']=='2.0.0' and manifest['tools']==[tool]
        assert ID not in z.read('entry.mjs').decode()
        entry=bundles/(pid+'.mjs');entry.write_bytes(z.read('entry.mjs'))
    frozen=adapter.request_spec(kind,query(kind),LIMITS,{REF:ID})
    script='''import plugin,{test} from ENTRY;
let seen=[];let status=200;
const api=await plugin({}, {}, {connections:{request:async(alias,input)=>{seen.push({alias,input});return {status,data:RESPONSE}}}});
const invoke=api.tool[TOOL].execute;
for(const request of [undefined,{...REQUEST,path:'/unexpected'},{...REQUEST,method:'DELETE'}]){
 let rejected=false;try{await invoke({request})}catch{rejected=true}if(!rejected)throw Error('invalid query accepted');
}
if(seen.length)throw Error('invalid query dispatched');
const result=JSON.parse(await invoke({request:REQUEST}));
status=503;let failed=false;try{await invoke({request:REQUEST})}catch{failed=true}
const health=await test();
console.log(JSON.stringify({result,seen,failed,health}));'''
    for key,value in {'ENTRY':entry.as_uri(),'TOOL':tool,'REQUEST':frozen,'RESPONSE':response(kind)}.items():
        script=script.replace(key,json.dumps(value))
    runtime=os.environ.get('BUN_EXECUTABLE') or shutil.which('bun') or shutil.which('node')
    assert runtime, 'Bun or Node.js is required to execute the bundled entry'
    flags=['--input-type=module'] if Path(runtime).stem.lower()=='node' else []
    output=subprocess.run([runtime,*flags,'-e',script],text=True,encoding='utf-8',capture_output=True,check=True,timeout=15)
    result=json.loads(output.stdout)
    assert result['failed'] and result['health']['ok'] is False and len(result['seen'])==2
    assert 'connection_group' not in result['seen'][0]['input']
    assert adapter.parse_response(kind,query(kind),result['result'],LIMITS,{REF:ID})['records']
