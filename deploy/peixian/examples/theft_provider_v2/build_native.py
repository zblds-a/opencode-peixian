"""Build the eight immutable v3 model-callable, Gateway-mediated bundles.

The Agent loader replaces execute with the private Gateway bridge. The packaged
execute function is only run in Gateway after a frozen server plan is approved.
"""
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'services/peixian-control'))
from shared.theft_provider_v2 import CATALOG, PAGED, TIMED
from control.data_plugin_policy import ACTIVE_KINDS

VERSION='3.0.0'
BASE_FIELDS={
    'lon':{'type':'number','description':'已确认的经度'},
    'lat':{'type':'number','description':'已确认的纬度'},
    'radius_m':{'type':'integer','description':'已确认半径，单位米'},
    'start':{'type':'string','description':'已确认开始时间 YYYY-MM-DD HH:mm:ss'},
    'end':{'type':'string','description':'已确认结束时间 YYYY-MM-DD HH:mm:ss'},
    'page':{'type':'integer','description':'明确请求的页码'},
    'page_size':{'type':'integer','description':'明确请求的每页条数'},
    'person_identity':{'type':'string','description':'已确认的单人身份号码，不得猜测'},
}

def arguments(kind):
    fields=('lon','lat','radius_m') if kind=='incidents' else ('radius_m',) if kind=='captures' else ('person_identity',)
    if kind in TIMED: fields+=('start','end')
    if kind in PAGED: fields+=('page','page_size')
    return {key:BASE_FIELDS[key] for key in fields}

def build(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    for kind in ACTIVE_KINDS:
        name,method,path,group=CATALOG[kind]
        pid='peixian-theft-'+kind.replace('_','-');tool='peixian_query_'+kind
        pattern='^'+path.replace('{person}','[0-9]{17}[0-9X]')+'$'
        manifest={'id':pid,'version':VERSION,'name':name,
            'description':'按本轮确认的对象、来源和范围查询；不能扩展条件或自动翻页。',
            'opencode_version':'1.18.30','entry':'entry.mjs','tools':[tool],
            'connections':{'provider':{'description':group+'只读供应方连接'}},
            'display':{'input_fields':[],'output_fields':['code']},
            'config_schema':{'type':'object','properties':{},'additionalProperties':False}}
        entry='''export default async function plugin(_context,_options,platform) {
 return {tool:{TOOL:{description:DESCRIPTION,args:ARGUMENTS,async execute(args){
 const request=args?.request;
 if(!request||request.method!==METHOD||!new RegExp(PATTERN).test(request.path))throw new Error('查询范围或接口合同不匹配。');
 const {connection_group,...input}=request;
 const response=await platform.connections.request('provider',input);
 if(response.status!==200)throw new Error('资料服务未确认成功。');
 return JSON.stringify(response.data);
 }}}};
}
export async function test(){return {ok:false,message:'无资料健康检查合同；不自动查询人员。'};}
'''.replace('TOOL',tool).replace('DESCRIPTION',json.dumps('查询'+name+'；仅可使用用户已确认条件，缺项先提问，不得重复未知结果。',ensure_ascii=False)).replace('ARGUMENTS',json.dumps(arguments(kind),ensure_ascii=False)).replace('METHOD',json.dumps(method)).replace('PATTERN',json.dumps(pattern))
        target=output/(pid+'-'+VERSION+'.zip')
        if target.exists():raise FileExistsError(target)
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            archive.writestr('entry.mjs',entry)

if __name__=='__main__':build(sys.argv[1])
