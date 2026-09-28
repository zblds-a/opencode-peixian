"""Projection of authenticated provider receipts, never model prose."""
import copy
import re
from .trusted_results import claim
from .backend_contract import iso
from shared.theft_provider import CATALOG,LIMITATIONS
from shared import theft_provider_v2 as v2

TRACK_SENTENCE_VERSIONS=('provider-source-text-v2','provider-source-text-v3')
SOURCE_SENTENCE_VERSION='provider-source-text-v3'
_WIFI_DESC=re.compile(r'(?i)wi[- ]?fi|wif.?探针')


def track_type_label(fields):
    """Map track type code/desc to display label; WiFi probe is 非机动车."""
    code=fields.get('trackType')
    desc=fields.get('trackTypeDesc')
    desc_text=desc.strip() if isinstance(desc,str) else ''
    if code==2 or (desc_text and _WIFI_DESC.search(desc_text)):
        return '非机动车'
    if code==0:
        return '人卡'
    if code==1:
        return '机动车'
    if desc_text:
        return desc_text
    return '未明确'


def profile_sentence(f):
    person=f.get('person') if isinstance(f.get('person'),dict) else {}
    age=person.get('age')
    head=(f"{person.get('name') or '姓名未提供'}（{person.get('sfz') or '未提供'}）；"
          f"性别 {person.get('gender') or '未提供'}；年龄 {str(age)+' 岁' if type(age) is int else '未提供'}")
    warning=f.get('warning') if isinstance(f.get('warning'),dict) else {}
    if type(warning.get('warningCount')) is int:
        head+=f"；来源预警 {warning['warningCount']} 条"
    captures=[c for c in f.get('captures') or [] if isinstance(c,dict)]
    if not captures:
        return head+'。来源未返回最近抓拍。'
    captures=sorted(captures,key=lambda c:str(c.get('captureTime') or ''),reverse=True)[:10]
    def tags(c):
        value=c.get('xwbq') or c.get('tags')
        value='、'.join(str(x) for x in value) if isinstance(value,list) else value
        return f"；标签 {value}" if isinstance(value,(str,int)) and str(value) else ''
    lines=[f"- {c.get('captureTime') or '时间未提供'}，{c.get('deviceName') or c.get('location') or '地点未提供'}"
           +(f"（{c['deviceId']}）" if c.get('deviceId') else '')+tags(c) for c in captures]
    return head+f"。最近 {len(captures)} 条抓拍：\n"+'\n'.join(lines)


def sentence(kind,f,version=None):
    if kind=='tracks':
        label=track_type_label(f)
        if version in TRACK_SENTENCE_VERSIONS:
            code=f.get('trackType')
            code=str(code) if type(code) is int else '未提供'
            return f"观测时间 {f.get('captureTime','未提供')}；设备 {f.get('deviceId','未提供')}；来源地点 {f.get('deviceName','未提供')}；轨迹类型 {label}；来源类型代码 {code}。"
        return f"观测时间 {f.get('captureTime','未提供')}；设备 {f.get('deviceId','未提供')}；来源地点 {f.get('deviceName','未提供')}；轨迹类型 {label}。"
    if kind=='incidents':return f"警情引用 {f.get('cjbh','未提供')}；处警时间 {f.get('cjsj','未提供')}；来源地址 {f.get('bzdzmc') or f.get('cjxz') or f.get('address','未提供')}。"
    if kind=='captures':
        count=f.get('capture_count','未提供')
        return f"{f.get('target_name','对象未提供')}（{f.get('target_id_card','未提供')}）：来源范围内抓拍汇总 {count} 次。"
    if kind in ('warnings','warning_detail'):
        types=f.get('warningTypes','未提供')
        count=f.get('warningCount','未提供')
        return f"{f.get('personName','对象未提供')}（{f.get('idCard','未提供')}）：来源预警类型 {types}；预警类型数量 {count}；最新触发时间 {f.get('latestTime','未提供')}。"
    if kind=='night':return f"来源夜间观测时间 {f.get('captureTime','未提供')}；来源地点 {f.get('location','未提供')}。"
    if kind=='community' and version==SOURCE_SENTENCE_VERSION:
        hours=f.get('crossHours')
        names=f.get('communityList')
        names='、'.join(str(x) for x in names) if isinstance(names,list) else names
        span=f"（约 {hours} 小时）" if isinstance(hours,(int,float)) and not isinstance(hours,bool) else ''
        desc=f"；来源描述 {f['trajectoryDesc']}" if f.get('trajectoryDesc') else ''
        return f"{f.get('timeRangeStart','未提供')} 至 {f.get('timeRangeEnd','未提供')}{span}跨 {f.get('communityCount','未提供')} 个小区：{names or '小区名称未提供'}{desc}。"
    if kind=='community':return f"来源时间范围 {f.get('timeRangeStart','未提供')} 至 {f.get('timeRangeEnd','未提供')}；小区数量 {f.get('communityCount','未提供')}；来源描述 {f.get('trajectoryDesc','未提供')}。"
    if kind=='profile':return profile_sentence(f)
    return f"来源预警类型 {f.get('warningType','未提供')}；来源近7天规则触发 {f.get('count','未提供')} 次。"

def project(row,snapshot):
    if snapshot.get('provider_history'):
        result=copy.deepcopy(snapshot['provider_history']);source=result.get('data_usage',{}).get('source_data_run_id') or result['run_id']
        result.update(run_id=row['id'],task=copy.deepcopy(snapshot['task_spec']),generated_at=iso(row.get('completed') or row['created']))
        result['data_usage']={'status':'historical_evidence','queried':False,'attempted':False,'may_have_sent':False,'new_call_count':0,'reuse_count':0,'source_data_run_id':source,'modules':[],'basis':'本人已冻结来源；未重新取数'}
        result['answer']['summary']='本次说明已有资料，没有重新查询。'+result['answer']['summary'].removeprefix('本次说明已有资料，没有重新查询。')
        return result
    plan=snapshot['provider_plan'];kind=plan['kind'];state=snapshot.get('provider_state',{});entry=state.get('modules',{}).get(kind,{})
    real=plan.get('version')==v2.VERSION
    data=copy.deepcopy(entry.get('public_response' if real else 'response')) if entry.get('status')=='completed' else None
    if real and data:data['snapshot_id']=data['response_snapshot_id']
    catalog=v2.CATALOG if real else CATALOG
    limitations=v2.LIMITATIONS if real else LIMITATIONS
    records=[];claims=[];identity=snapshot['agent_profile'];missing=[limitations[kind]]
    if data:
        for record in data['records']:
            rid=row['id']+':'+record['source_ref'];fields=copy.deepcopy(record['fields'])
            records.append({'record_id':rid,'module':kind,'source_run_id':row['id'],'snapshot_id':data['snapshot_id'],'fields':fields})
            claims.append(claim(row,identity,'fact','provider.'+kind+'.record.v1',sentence(kind,fields),{'record_id':rid,'subject_refs':snapshot['task_spec']['target_refs'],'fields':fields,'snapshot_id':data['snapshot_id']},[rid]))
        summary=f"{catalog[kind][0]}：本次取得 {data['returned_count']} 条来源记录。"
        summary+=f"来源总数 {data['total']}；当前第 {plan['query'].get('page',1)} 页。" if data['total'] is not None else '来源未提供完整总数。'
        claims.insert(0,claim(row,identity,'computed','provider.page.v1',summary,{'subject_refs':snapshot['task_spec']['target_refs'],'returned_count':data['returned_count'],'total':data['total'],'coverage':data['coverage']},[r['record_id'] for r in records]))
        if data['coverage']!='complete':missing.append('本次覆盖有限，不能把当前返回数量当作全部资料。')
        missing+=data['limitations']
    else:summary='本轮尚未取得可核对的资料；不能解释为没有相关记录。';missing.append('请查看原执行状态；结果未知时不会自动重新查询。')
    if snapshot.get('provider_followup'):summary=snapshot['task_response']['message']
    status='needs_input' if snapshot.get('provider_followup') else 'partial' if data and (data['coverage']!='complete' or row['status']!='completed') else 'ready' if data else 'unavailable'
    use='partial' if data and data['coverage']!='complete' else 'confirmed' if data else entry.get('status') if entry.get('status') in ('rejected','cancelled','unknown') else 'in_flight' if entry else 'not_started'
    items=[{'text':c['statement'],'claim_id':c['claim_id'],'source_run_id':row['id'],'source_ids':c['source_ids']} for c in claims[:5]]
    steps=['可展开本轮来源，确认对象和范围后继续查询。','可追加来源复核意见或导出本轮报告。'] if data else ['请查看本轮执行步骤，不要自动重复发送。']
    return {'schema':'peixian.analysis-result','version':'2.0','run_id':row['id'],'agent':identity,'task':copy.deepcopy(snapshot['task_spec']),'data_environment':plan.get('data_environment','synthetic'),'data_usage':{'status':use,'queried':True if data else None if entry else False,'attempted':bool(entry.get('dispatch_attempts') or entry.get('response_count')),'may_have_sent':entry.get('may_have_sent',bool(entry)),'new_call_count':max(entry.get('dispatch_attempts',0),entry.get('response_count',int(bool(data)))),'reuse_count':0,'source_data_run_id':None,'modules':[{'module':kind,'status':entry.get('status','not_started'),'reserved':bool(entry),'response_confirmed':bool(entry.get('response_count',bool(data))),'reservation_count':int(bool(entry)),'dispatch_attempts':entry.get('dispatch_attempts',0),'response_count':entry.get('response_count',int(bool(data)))}],'basis':'Gateway投递边界计数与确认响应；预留不代表确定HTTP次数'},'claims':claims,'records':records,'missing':list(dict.fromkeys(missing)),'narrative':{'status':'not_generated','text':None,'claim_refs':[],'conflicts':[],'review_version':'provider-code-v1','coverage':'公开说明由代码从已确认回执生成。'},'versions':{'provider_contract':plan['version'],'provider_snapshot':data['snapshot_id'] if data else None,'plugin_versions':{plan['plugin_id']:plan['plugin_version']},'query':plan['query']},'generated_at':iso(row.get('completed') or row['created']),'answer':{'version':'controlled-zh-v1','status':status,'summary':summary,'items':items,'missing':list(dict.fromkeys(missing)),'next_steps':steps}}
