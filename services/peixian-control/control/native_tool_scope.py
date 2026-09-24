"""Native theft-tool conditions. Facts are accepted only from user-confirmed scope.

This module has no business workflow graph. It records exact input values and
rejects model-generated widening. A model chooses the next tool and can ask a
question; only the independent execution gate may call a supplier.
"""
import copy
import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .backend_contract import error
from .data_plugin_policy import ACTIVE_KINDS
from .theft_planner import slots
from shared import theft_provider_v2 as adapter

TOOL_TO_KIND={'peixian_query_'+kind:kind for kind in ACTIVE_KINDS}
SCORING_REQUEST=re.compile(r'评分|打分|可疑度|嫌疑评估|研判优先级|嫌疑程度|排序|筛选嫌疑人|可能性|嫌疑人列表|核验前')
SCORING_NEGATE=re.compile(
    r'不要\s*(?:评分|排序|研判)|无需\s*(?:评分|排序)|不用\s*(?:评分|排序|打分)|'
    r'不\s*要\s*打分|禁止\s*(?:评分|排序)|取消\s*(?:评分|排序)'
)
CASE_HINT=re.compile(r'案件|警情|案发|盗窃案|由案到人|周边人员|可疑人员')
PERSON_HINT=re.compile(r'由人到案|此人|该人|这名人员|已确认人员')


def scoring_requested(text, prior=None, direction=None):
    """Fallback scoring intent when the model does not declare scoring.requested.

    Defaults to False. Explicit user negation always wins. direction is ignored.
    """
    if not isinstance(text, str):
        if prior and 'scoring_requested' in prior:
            return bool(prior.get('scoring_requested'))
        return False
    if SCORING_NEGATE.search(text):
        return False
    if SCORING_REQUEST.search(text):
        return True
    if prior and 'scoring_requested' in prior:
        return bool(prior.get('scoring_requested'))
    return False


def infer_direction(confirmed, refs, text, prior=None):
    """Implicit case_to_person / person_to_case; user never picks a mode."""
    if 'person_identity' in (confirmed or {}) or PERSON_HINT.search(text or ''):
        return 'person_to_case'
    if refs:
        # Selected sources may already bind a person; prefer person_to_case when prior said so.
        if prior and prior.get('direction') == 'person_to_case' and 'person_identity' in (prior.get('confirmed') or {}):
            return 'person_to_case'
    if {'lon', 'lat'} <= set((confirmed or {}).keys()) or CASE_HINT.search(text or ''):
        return 'case_to_person'
    if prior and prior.get('direction') in ('case_to_person', 'person_to_case'):
        return prior['direction']
    return 'unknown'


def freeze_context(store,uid,sid,data):
    """Freeze explicit user conditions with a stable session task identity."""
    text=data['text']
    parsed=slots(text,data.get('scope'))
    current={v['field']:v['value'] for v in parsed.values()}
    prior=None
    for row in store.rows("SELECT request_ciphertext FROM business_runs WHERE uid=? AND session_id=? ORDER BY rowid DESC LIMIT 30",(uid,sid)):
        snapshot=store.decrypt(row['request_ciphertext'])
        if snapshot.get('native_tool_context'):
            prior=snapshot['native_tool_context']
            break
    task_id=prior['task_id'] if prior else uuid.uuid4().hex
    confirmed=copy.deepcopy(prior['confirmed']) if prior else {}
    confirmed.update(current)
    # A user can change direction within one task. When the new object is only
    # described as 'another' one, never reuse the former person's identity or
    # position merely because it was confirmed in an earlier Run.
    ambiguous_person=bool(re.search(r'另一个人|其他人员|换个人|换一名人员|另一个对象',text) and 'person_identity' not in current)
    ambiguous_location=bool(re.search(r'另一个位置|其他地点|换个地点|另一个警情',text) and not {'lon','lat'}<=current.keys())
    if ambiguous_person:confirmed.pop('person_identity',None)
    if ambiguous_location:confirmed.pop('lon',None);confirmed.pop('lat',None)
    # A new explicit object or position supersedes any earlier selected source.
    # Otherwise a later question could silently query the old source instead.
    changed_object=bool({'person_identity','lon','lat'} & current.keys()) or ambiguous_person or ambiguous_location
    if 'source_refs' in data:
        refs=copy.deepcopy(data['source_refs'])
    else:
        named=named_sources(store,uid,sid,text)
        refs=named if named else ([] if changed_object else copy.deepcopy(prior.get('source_refs',[]) if prior else []))
        if '来源记录编号' in text and not named:
            error('source_record_unavailable','所述来源编号未在本人本会话结果中找到。',409)
    if not isinstance(refs,list) or len(refs)>20:
        error('source_selection_invalid','请选择明确的来源记录，不自动选择候选。',422)
    if refs:
        from .analysis_tasks import source
        for ref in refs:source(store,uid,sid,ref,'acceptance_real')
    prior_constraints=prior.get('constraints_text','') if prior else ''
    if re.search(r'同意使用上游默认覆盖范围',text):
        prior_constraints=''
    constraints=(prior_constraints+' '+text)[-12000:]
    direction=infer_direction(confirmed, refs, text, prior)
    want_score=scoring_requested(text, prior, direction)
    from .theft_candidates import candidate_request_n, stage1_from_task, authorize, build_enrichment_plan, task_person_modules
    request_n=candidate_request_n(text)
    candidate_set=[] if changed_object else copy.deepcopy((prior or {}).get('candidate_set') or [])
    if request_n and want_score and direction == 'case_to_person':
        ranked=stage1_from_task(store, uid, sid, task_id)
        if ranked.get('items'):
            candidate_set=authorize(ranked['items'], request_n)
    enrichment=None
    if candidate_set and direction == 'case_to_person' and want_score:
        present=task_person_modules(store, uid, sid, task_id)
        enrichment=build_enrichment_plan(candidate_set, present_by_person=present)
    stop_phrase='不再追问，请基于已取得资料直接作答。'
    stop_followup=bool((prior or {}).get('stop_followup')) or (text.strip() == stop_phrase) or ('不再追问' in text and '直接作答' in text)
    return {'version':'native-tool-context-v1','task_id':task_id,
        'scope_version':prior['scope_version']+1 if prior else 1,
        'confirmed':confirmed,'source_refs':refs,
        'current_text':text,'constraints_text':constraints,'user_conditions':current,
        'scoring_requested':want_score,
        'direction':direction,
        'candidate_request_n':request_n,
        'candidate_set':candidate_set,
        'enrichment_plan':enrichment,
        'stop_followup':stop_followup}


FIELD_NAMES = {'person_identity':'人员','start':'开始时间','end':'结束时间','lon':'经度','lat':'纬度','radius_m':'半径','page':'页码','page_size':'每页条数'}


def canonical_field(key, value):
    """Only representation equivalence; never infer dates, timezone or units."""
    try:
        if key in ('page','page_size'):
            if type(value) is int: return value
            if isinstance(value,str) and re.fullmatch(r'[0-9]{1,9}',value): return int(value)
            raise ValueError()
        if key in ('start','end'):
            if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}',value): raise ValueError()
            return datetime.strptime(value.replace('T',' '),'%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
        if key in ('lon','lat','radius_m'):
            if isinstance(value,bool) or not isinstance(value,(str,int,float)): raise ValueError()
            n=Decimal(str(value))
            if not n.is_finite(): raise ValueError()
            return format(n.normalize(),'f')
        return value
    except (ValueError,InvalidOperation,OverflowError):
        error('scope_parameter_invalid','参数格式无效，尚未查询；请仅补充提示字段。',422,{key:FIELD_NAMES.get(key,key)+'格式不符合接口合同'})


def resolve_arguments(kind, args, context):
    if not isinstance(args,dict): error('native_tool_invalid','资料工具参数必须是对象。',422)
    resolved=copy.deepcopy(args)
    confirmed=context['confirmed']
    # Only fill existing task-bound conditions, never new objects or inferred times.
    reusable=set()
    if kind in adapter.PERSON and not context['source_refs']: reusable.add('person_identity')
    if kind in adapter.TIMED and kind!='captures': reusable.update(('start','end'))
    if kind=='captures': reusable.update({'start','end','radius_m'})
    for key in reusable:
        if key not in resolved and key in confirmed: resolved[key]=copy.deepcopy(confirmed[key])
    return {key:canonical_field(key,value) for key,value in resolved.items()}


def arguments(kind,args,context):
    """Accept model-supplied values with format and required-field checks only.

    Authorization-style blocks (scope_unconfirmed, capture_scope_unconfirmed,
    page_unconfirmed, unsupported_scope) are removed. Values that pass
    canonical_field are accepted and may be written back to confirmed by the caller.
    """
    if kind not in ACTIVE_KINDS or not isinstance(args,dict):
        error('native_tool_invalid','资料工具或参数无效。',422)
    supported={'lon','lat','radius_m','person_identity','start','end','page','page_size'}
    if kind=='captures':supported-={'lon','lat'}
    if set(args)-supported:
        error('native_tool_invalid','查询参数包含未开放的条件。',422)
    args=resolve_arguments(kind,args,context)
    if isinstance(args.get('person_identity'),str) and args['person_identity'].startswith('person-'):
        error('identity_parameter_invalid','person_identity 必须使用已确认的原始身份号码，不能使用展示引用。',409)
    if context['source_refs'] and {'lon','lat','person_identity'} & args.keys():
        error('source_value_override','已选择来源时不能再替换对象或坐标。',409)
    required=({'radius_m'} if context['source_refs'] else {'lon','lat','radius_m'}) if kind=='incidents' else {'radius_m'} if kind=='captures' else set() if context['source_refs'] else {'person_identity'}
    if kind in adapter.TIMED:required|={'start','end'}
    if not required<=set(args):
        error('scope_missing','查询条件不完整，未访问资料接口；只补充列出的字段，不重试或猜测权限。',409,{k:FIELD_NAMES[k]+'尚未明确' for k in sorted(required-set(args))})
    if kind=='captures' and len(context['source_refs'])!=1:
        error('source_selection_required','周边抓拍必须先选择一个明确的位置来源。',409)
    # Accept model values into confirmed so later turns see them as known.
    confirmed=context.setdefault('confirmed',{})
    user_conditions=context.setdefault('user_conditions',{})
    for key,value in args.items():
        if key=='person_identity':
            continue
        confirmed[key]=copy.deepcopy(value)
        user_conditions[key]=copy.deepcopy(value)
    query={key:copy.deepcopy(value) for key,value in args.items() if key!='person_identity'}
    return query

def source_values(store,uid,sid,kind,context):
    """Derive one coordinate/person from the exact selected prior source."""
    from .analysis_tasks import source
    if len(context['source_refs'])!=1:
        error('explicit_source_required','请从候选结果中明确选择一条来源。',409)
    reference=context['source_refs'][0]
    record,snapshot=source(store,uid,sid,reference,'acceptance_real')
    native=snapshot.get('native_tool_policy')
    call_id=record.get('call_id')
    if native:
        plan=snapshot.get('native_calls',{}).get(call_id,{}).get('frozen',{})
        entry=snapshot.get('provider_state',{}).get('modules',{}).get(call_id,{})
        expected=reference['run_id']+':'+call_id+':'
    else:
        plan=snapshot.get('provider_plan',{})
        entry=snapshot.get('provider_state',{}).get('modules',{}).get(plan.get('kind'),{})
        expected=reference['run_id']+':'
    if plan.get('version')!=adapter.VERSION or entry.get('status')!='completed':
        error('source_contract_unsupported','所选来源未取得可核对的真实合同结果。',409)
    raw=entry.get('response',{})
    if raw.get('response_snapshot_id')!=reference['snapshot_id']:
        error('source_version_changed','所选来源快照已变化。',409)
    rows=[r for r in raw.get('records',[]) if expected+r.get('source_ref','')==reference['record_id']]
    if len(rows)!=1:
        error('source_record_unavailable','所选来源原始记录无法核对。',409)
    fields=rows[0].get('fields',{})
    projected=adapter.public_result(fields,store.worker_key.encode(),uid+'/'+sid)
    if projected!=record.get('fields'):
        error('source_integrity_failed','来源展示字段与原始记录不一致。',409)
    origin=plan['kind']
    if kind in ('incidents','captures'):
        names=('gisX','gisY') if origin=='incidents' else ('lon','lat') if origin=='tracks' else None
        if not names or any(fields.get(k) is None for k in names):
            error('source_coordinates_missing','所选来源没有完整、受支持的坐标。',409)
        from .provider_contracts import settings
        compatibility=settings(uid).get('coordinate_compatibility',{})
        key=adapter.CATALOG[origin][3]+':'+adapter.CATALOG[kind][3]
        if compatibility.get(key) is not True:
            error('coordinate_contract_unconfirmed','来源与目标接口的坐标兼容性尚未确认。',409)
        return {'lon':str(fields[names[0]]),'lat':str(fields[names[1]])},{}
    names=[n for n in ('target_id_card','targetIdCard','idCard') if n in fields]
    if len(names)!=1:
        error('source_identity_missing','所选来源不能唯一确定一名人员。',409)
    identity=adapter.person_id(fields[names[0]])
    ref=adapter.person_ref(identity,store.worker_key.encode(),uid+'/'+sid)
    return {'person_ref':ref},{ref:identity}

def named_sources(store,uid,sid,text):
    """An exact user-written record reference may select a prior owned source."""
    from . import trusted_results
    found=[]
    for row in store.rows("SELECT id,status FROM business_runs WHERE uid=? AND session_id=? ORDER BY rowid DESC LIMIT 50",(uid,sid)):
        if row['status'] not in ('completed','failed','cancelled'):
            continue
        result=trusted_results.read(store,uid,sid,row['id'])
        if result.get('data_environment')!='acceptance_real':
            continue
        for record in result.get('records',[]):
            rid=record.get('record_id')
            if not isinstance(rid,str):
                continue
            if re.search(r'(?<![\w:-])'+re.escape(rid)+r'(?![\w:-])',text):
                found.append({'run_id':row['id'],'result_digest':trusted_results.digest(result),
                    'record_id':rid,'snapshot_id':record['snapshot_id']})
    unique={adapter.digest(ref):ref for ref in found}
    if len(unique)>20:
        error('source_selection_limit','本次选定的来源过多，请明确其中一条。',422)
    return list(unique.values())


def model_context(context):
    """Explain available confirmed values; model decides direction, scoring and next steps."""
    plan = context.get('enrichment_plan')
    enrich_note = ''
    payload = {
        'version': 'native-tool-arguments-v1',
        'scope_version': context['scope_version'],
        'confirmed': context['confirmed'],
        'selected_source_refs': context['source_refs'],
    }
    if isinstance(plan, dict) and plan.get('items'):
        payload['enrichment_plan'] = plan
        if not plan.get('complete'):
            enrich_note = (
                '本轮已有候选人补查计划。可按 enrichment_plan 逐项调用对应资料工具（每次一个调用）；'
                '不必再向用户确认人数或是否补查；某次失败则记下缺口并继续下一项。'
            )
        else:
            enrich_note = 'enrichment_plan 已完成；可基于已取得资料作答，覆盖不足者可再建议补查。'
    stop_note=''
    if context.get('stop_followup'):
        stop_note='用户已要求停止追问，请基于已取得资料直接作答，不要再调用 question，也不要再写 next_question。'
    return ('\n本轮原生工具参数约定：研判方向、是否评分、核验人数、下一步建议与追问均由你自行判断；'
        '条件齐全即可直接查询，不必等用户逐项确认。缺条件时用 question 工具自己组织题干和选项。'
        'person_identity 可填写原始身份号码，或本会话抓拍结果中的 person-* 引用；'
        'person-* 不是新对象或身份证号，平台只校验来源完整性。'
        '已选定来源时，对象或坐标由平台从该来源读取，不在工具参数中重复传入。'
        '以下已确认值不是要求查询全部能力；只取当前问题需要的字段。'
        '服务端会补齐本任务已确认且用途适用的人员和时间。'
        '真正失败不代表记录为零；不要自行重试失败调用。分数、等级与排序数值只由平台按来源计算。'
        + stop_note + enrich_note + '\n'
        + adapter.canonical(payload))
