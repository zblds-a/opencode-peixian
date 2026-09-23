import importlib.util
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from control.data_plugin_policy import ACTIVE_KINDS
from shared.theft_provider_v2 import CATALOG


@pytest.fixture
def bundles(tmp_path):
    builder=Path(__file__).resolve().parents[3]/'deploy/peixian/examples/theft_provider_v2/build_native.py'
    spec=importlib.util.spec_from_file_location('native_bundle_builder',builder)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build(tmp_path)
    with pytest.raises(FileExistsError):module.build(tmp_path)
    return tmp_path


@pytest.mark.parametrize('kind',ACTIVE_KINDS)
def test_single_model_tool_and_fixed_export(bundles,kind):
    pid='peixian-theft-'+kind.replace('_','-')
    tool='peixian_query_'+kind
    with zipfile.ZipFile(bundles/(pid+'-3.0.0.zip')) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        assert manifest['tools']==[tool]
        assert manifest['version']=='3.0.0'
        entry=bundles/(pid+'.mjs')
        entry.write_bytes(archive.read('entry.mjs'))
    runtime=shutil.which('node') or shutil.which('bun')
    assert runtime
    method,path,_=CATALOG[kind][1:]
    script="import plugin from ENTRY;\nlet calls=[];\nconst api=await plugin({}, {}, {connections:{request:async(alias,input)=>{calls.push({alias,input});return {status:200,data:{code:200}}}}});\nconst t=api.tool[TOOL];if(Object.keys(api.tool).length!==1||!t)throw Error('tool inventory');\nconst request={method:METHOD,path:PATH};\nfor(const bad of [{...request,method:'DELETE'},{...request,path:'/other'}]){\n  let denied=false;try{await t.execute({request:bad})}catch{denied=true}if(!denied)throw Error('bad accepted');\n}\nif(calls.length)throw Error('bad reached egress');\nawait t.execute({request});\nconsole.log(JSON.stringify({keys:Object.keys(t.args),calls}));"
    values={'ENTRY':entry.as_uri(),'TOOL':tool,'METHOD':method,
        'PATH':path.replace('{person}','990000200001010014')}
    for key,value in values.items():script=script.replace(key,json.dumps(value))
    flags=['--input-type=module'] if Path(runtime).stem.lower()=='node' else []
    result=subprocess.run([runtime,*flags,'-e',script],capture_output=True,text=True,encoding='utf-8',timeout=15,check=True)
    payload=json.loads(result.stdout)
    assert len(payload['calls'])==1
    assert payload['calls'][0]['alias']=='provider'
    assert payload['calls'][0]['input']=={'method':method,'path':values['PATH']}
    if kind=='incidents':assert {'lon','lat','radius_m'}<=set(payload['keys'])
    if kind=='captures':assert {'radius_m','start','end'}<=set(payload['keys'])
