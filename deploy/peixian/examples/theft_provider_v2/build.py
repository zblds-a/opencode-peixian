"""Build immutable v2 read-only bundles; never publish or configure connections."""
from pathlib import Path
import json
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'services/peixian-control'))
from shared.theft_provider_v2 import CATALOG
from control.data_plugin_policy import ACTIVE_KINDS


def build(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    for kind in ACTIVE_KINDS:
        name,method,path,group=CATALOG[kind]
        pid='peixian-theft-'+kind.replace('_','-');tool='peixian_query_'+kind
        pattern='^'+path.replace('{person}','[0-9]{17}[0-9X]')+'$'
        manifest={'id':pid,'version':'2.0.0','name':name,'description':'受控查询明确对象与范围；来源记录不构成犯罪判断。','opencode_version':'1.18.30','entry':'entry.mjs','tools':[tool],'connections':{'provider':{'description':group+'只读供应方连接'}},'display':{'input_fields':[],'output_fields':['code']},'config_schema':{'type':'object','properties':{},'additionalProperties':False}}
        entry='''export default async function plugin(_context,_options,platform) {
 return {tool:{TOOL:{description:"读取平台冻结范围的来源资料，不接受模型自定义条件。",args:{},async execute(args){
 const request=args?.request;
 if(!request||request.method!==METHOD||!new RegExp(PATTERN).test(request.path))throw new Error('查询范围或接口合同不匹配。');
 const {connection_group,...input}=request;
 const response=await platform.connections.request('provider',input);
 if(response.status!==200)throw new Error('资料服务未确认成功。');
 return JSON.stringify(response.data);
 }}}};
}
export async function test(){return {ok:false,message:'上游未约定无资料健康检查接口；请使用获准范围的受控验收，不自动查询人员。'};}
'''.replace('TOOL',tool).replace('METHOD',json.dumps(method)).replace('PATTERN',json.dumps(pattern))
        target=output/(pid+'-2.0.0.zip')
        if target.exists():raise FileExistsError(target)
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            z.writestr('entry.mjs',entry)


if __name__=='__main__':build(sys.argv[1])
