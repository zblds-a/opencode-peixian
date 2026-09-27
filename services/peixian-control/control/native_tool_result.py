"""Trusted multi-call source projection for model-native theft Runs."""
import copy

from .backend_contract import iso
from .trusted_results import claim
from .theft_provider_result import sentence, SOURCE_SENTENCE_VERSION
from shared import theft_provider_v2 as adapter

VERSION='native-provider-result-v1'
MISSING_TEXT={'track_segments_unverified':'人员轨迹：部分时段未核验。'}


def project(row,snapshot):
    calls=snapshot.get('native_calls',{})
    sentence_version=snapshot.get('provider_sentence_version')
    identity=snapshot['agent_profile']
    records=[];claims=[];missing=[];modules=[];seen=set()
    for call_id,item in calls.items():
        plan=item['frozen'];kind=plan['kind']
        status=item['status'];public=item.get('public_response')
        confirmed=status=='completed' and isinstance(public,dict)
        modules.append({'module':kind,'call_id':call_id,'status':status,
            'reserved':status in ('dispatching','completed','unknown','rejected','cancelled'),
            'response_confirmed':confirmed})
        if not confirmed:
            missing.append(adapter.CATALOG[kind][0]+'未取得已确认结果；不能理解为零条或没有发生。')
            continue
        if public.get('kind')!=kind or public.get('version')!=adapter.VERSION or public.get('response_snapshot_id') is None:
            missing.append(adapter.CATALOG[kind][0]+'的资料版本无法核对。')
            continue
        subject = plan.get('query',{}).get('person_ref') if snapshot.get('answer_delivery') and kind in adapter.PERSON else None
        if subject and public.get('query',{}).get('person_ref') != subject:
            missing.append('资料对象与冻结查询对象不一致。')
            continue
        source_ids=[]
        for entry in public.get('records',[]):
            if not isinstance(entry,dict) or not isinstance(entry.get('source_ref'),str) or not isinstance(entry.get('fields'),dict):
                missing.append(adapter.CATALOG[kind][0]+'存在格式不完整的记录。')
                continue
            rid=row['id']+':'+call_id+':'+entry['source_ref']
            if rid in seen:
                missing.append(adapter.CATALOG[kind][0]+'存在重复来源编号。')
                continue
            seen.add(rid);source_ids.append(rid)
            fields=copy.deepcopy(entry['fields'])
            records.append({'record_id':rid,'module':kind,'source_run_id':row['id'],
                'call_id':call_id,'snapshot_id':public['response_snapshot_id'],'fields':fields, **({'subject_ref':subject} if subject else {})})
            claims.append(claim(row,identity,'fact','provider.'+kind+('.record.v2' if kind=='tracks' and sentence_version==SOURCE_SENTENCE_VERSION else '.record.v1'),
                sentence(kind,fields,sentence_version),{'record_id':rid,'fields':fields,
                'snapshot_id':public['response_snapshot_id'], **({'subject_ref':subject} if subject else {})},[rid]))
        count=public.get('returned_count')
        if type(count) is int and count>=0:
            description=adapter.CATALOG[kind][0]+'：本次取得 '+str(count)+' 条来源记录。'
            claims.append(claim(row,identity,'computed','provider.page.v1',description,
                {'returned_count':count,'total':public.get('total'),'coverage':public.get('coverage'),
                 'call_id':call_id,'snapshot_id':public['response_snapshot_id']},source_ids))
        missing+=[MISSING_TEXT.get(m,m) for m in public.get('missing',[])]
    questions=[q for q in snapshot.get('native_pending_questions',{}).values() if q.get('status') in ('pending','rejected')]
    for q in questions:
        missing.append(adapter.CATALOG[q['kind']][0]+('：已取消补充，尚未查询。' if q['status']=='rejected' else '：等待补充条件，尚未查询。'))
    confirmed=[m for m in modules if m['response_confirmed']]
    if confirmed and len(confirmed)==len(modules) and not questions:
        use_status='confirmed'
    elif confirmed:
        use_status='partial'
    elif any(m['status']=='unknown' for m in modules):
        use_status='unknown'
    elif modules:
        use_status='rejected'
    else:
        use_status='not_started'
    missing=list(dict.fromkeys(missing))
    summary=('本轮已取得 '+str(len(confirmed))+' 项已核对资料，可展开来源逐项查看。' if confirmed
        else '本轮未取得可核对的资料；请补充对象、位置来源或时间范围。')
    answer={'version':'controlled-zh-v1',
        'status':'ready' if use_status=='confirmed' else 'partial' if confirmed else 'needs_input',
        'summary':summary,
        'items':[{'text':c['statement'],'claim_id':c['claim_id'],
                  'source_run_id':row['id'],'source_ids':c['source_ids']} for c in claims[:5]],
        'missing':missing,
        'next_steps':['可查看本轮来源记录并指定需要继续核对的一项。'] if confirmed
            else ['请明确对象、位置来源及所需时间，再继续查询。']}
    return {'schema':'peixian.analysis-result','version':'2.0','run_id':row['id'],
        'agent':copy.deepcopy(identity),'task':copy.deepcopy(snapshot['task_spec']),
        'data_environment':'acceptance_real',
        'data_usage':{'status':use_status,'queried':bool(confirmed),
            'attempted':any(m['reserved'] for m in modules),
            'may_have_sent':any(m['reserved'] for m in modules),
            'new_call_count':sum(m['reserved'] for m in modules),
            'reuse_count':0,'source_data_run_id':None,'modules':modules,
            'basis':'逐次Gateway回执与代码核对；未确认调用不视为已取数'},
        'claims':claims,'records':records,'missing':missing,
        'narrative':{'status':'unverified','text':None,'claim_refs':[],
            'conflicts':[],'review_version':'native-separate-v1',
            'coverage':'模型自由说明不自动成为已核验事实。'},
        'versions':{**({'provider_sentence':sentence_version} if sentence_version else {}),'native_gate':snapshot['native_tool_policy']['version'],
            'task_id':snapshot['native_tool_context']['task_id'],
            'scope_version':snapshot['native_tool_context']['scope_version'],
            'plugin_versions':{item['frozen']['plugin_id']:item['frozen']['plugin_version'] for item in calls.values()}},
        'generated_at':iso(row.get('completed') or row['created']),'answer':answer}
