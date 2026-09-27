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
    """Freeze scoring intent. case_to_person and person_to_case default on unless negated."""
    if not isinstance(text, str):
        if prior and 'scoring_requested' in prior:
            return bool(prior.get('scoring_requested'))
        return direction in ('case_to_person', 'person_to_case')
    if SCORING_NEGATE.search(text):
        return False
    if SCORING_REQUEST.search(text):
        return True
    if prior and 'scoring_requested' in prior:
        return bool(prior.get('scoring_requested'))
    return direction in ('case_to_person', 'person_to_case')



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
    changed_object=any(canonical_field(k, current[k]) != canonical_field(k, (prior or {}).get('confirmed', {}).get(k)) if (prior or {}).get('confirmed', {}).get(k) is not None else True for k in ('person_identity','lon','lat') if k in current) or ambiguous_person or ambiguous_location
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
    stop_phrase='不再追问，请基于已取得资料直接作答。'
    stop_followup=bool((prior or {}).get('stop_followup')) or (text.strip() == stop_phrase) or ('不再追问' in text and '直接作答' in text)
    capture_conditions={} if changed_object else copy.deepcopy((prior or {}).get('capture_conditions',{}))
    if re.search(r'抓拍',text):
        capture_conditions.update({k:current[k] for k in ('start','end','radius_m') if k in current})
    return {'version':'native-tool-context-v1','task_id':task_id,
        'scope_version':prior['scope_version']+1 if prior else 1,
        'confirmed':confirmed,'source_refs':refs,
        'query_rules_version':'on-demand-v1',
        'capture_scope_version':'capture-purpose-v1',
        'source_selection':'explicit',
        'capture_conditions':capture_conditions,
        'capture_position_confirmed':bool((prior or {}).get('capture_position_confirmed')) and not changed_object,
        'current_text':text,'constraints_text':constraints,'user_conditions':current,
        'scoring_requested':scoring_requested(text,prior,direction),
        'direction':direction,
        'candidate_request_n':None,
        'candidate_set':[],
        'enrichment_plan':None,
        'person_case_plan':None,
        'center_set':[],
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


MAX_QUERY_DAYS=31


def time_window_span(start, end):
    try:
        left,right=(datetime.strptime(str(v).replace('T',' '),'%Y-%m-%d %H:%M:%S') for v in (start,end))
    except ValueError:
        return None
    return right-left


def check_time_window(start, end):
    span=time_window_span(start,end)
    if span is None:
        return
    if span.total_seconds()<=0 or span.total_seconds()>MAX_QUERY_DAYS*86400:
        from fastapi import HTTPException
        raise HTTPException(409,{'code':'time_range_limit',
            'message':f'开始时间须早于结束时间，且单次时间跨度不超过 {MAX_QUERY_DAYS} 天；尚未访问资料接口。',
            'field_errors':{'start':'超出接口限制','end':'超出接口限制'},'limits':{'max_days':MAX_QUERY_DAYS}})


def resolve_arguments(kind, args, context):
    if not isinstance(args,dict): error('native_tool_invalid','资料工具参数必须是对象。',422)
    resolved=copy.deepcopy(args)
    confirmed=context.get('capture_conditions',{}) if kind=='captures' and (context.get('capture_scope_version')=='capture-purpose-v1' or context.get('dialogue_policy')=='adaptive-dialogue-v1') else context['confirmed']
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
    if kind=='captures' and (context.get('capture_scope_version')=='capture-purpose-v1' or context.get('dialogue_policy')=='adaptive-dialogue-v1'):
        conditions=context.get('capture_conditions',{})
        absent={k:FIELD_NAMES[k]+'需针对抓拍查询明确' for k in ('start','end','radius_m') if k not in conditions or (k in args and canonical_field(k,args[k])!=canonical_field(k,conditions[k]))}
        if absent:error('scope_missing','请补充抓拍查询的指定条件。',409,absent)
    if isinstance(args.get('person_identity'),str) and args['person_identity'].startswith('person-'):
        error('identity_parameter_invalid','person_identity 必须使用已确认的原始身份号码，不能使用展示引用。',409)
    if context['source_refs'] and {'lon','lat','person_identity'} & args.keys():
        error('source_value_override','已选择来源时不能再替换对象或坐标。',409)
    required=({'radius_m'} if context['source_refs'] else {'lon','lat','radius_m'}) if kind=='incidents' else {'radius_m'} if kind=='captures' else set() if context['source_refs'] else {'person_identity'}
    if kind in adapter.TIMED:required|={'start','end'}
    if not required<=set(args):
        error('scope_missing','查询条件不完整，未访问资料接口；只补充列出的字段，不重试或猜测权限。',409,{k:FIELD_NAMES[k]+'尚未明确' for k in sorted(required-set(args))})
    if kind=='captures' and len(context['source_refs'])!=1 and not (context.get('capture_position_confirmed') and {'lon','lat'} <= context.get('confirmed',{}).keys()):
        error('source_selection_required','周边抓拍必须先选择一个明确的位置来源。',409)
    if kind in adapter.TIMED:
        check_time_window(args['start'],args['end'])
    # Accept model values into confirmed so later turns see them as known.
    confirmed=context.setdefault('confirmed',{})
    user_conditions=context.setdefault('user_conditions',{})
    for key,value in args.items():
        if key=='person_identity':
            continue
        confirmed[key]=copy.deepcopy(value)
        user_conditions[key]=copy.deepcopy(value)
    applicable=({'lon','lat','radius_m'} if kind in ('incidents','captures') else set())|({'start','end'} if kind in adapter.TIMED else set())|({'page','page_size'} if kind in adapter.PAGED else set())
    query={key:copy.deepcopy(value) for key,value in args.items() if key in applicable}
    if kind=='captures' and not context['source_refs'] and context.get('capture_position_confirmed'):
        query.update({k:canonical_field(k,context['confirmed'][k]) for k in ('lon','lat')})
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
    """Expose confirmed conditions; the model decides the next useful query."""
    payload = {'version':'native-tool-arguments-v1', 'scope_version':context['scope_version'],
        'confirmed':context['confirmed'], 'selected_source_refs':context['source_refs'],
        'direction':context.get('direction') or 'unknown'}
    return """
本轮对话规则：围绕用户当前问题选择必要工具，不要求八项全查，不按固定人员补查计划执行。
已取得资料足够时直接回答；普通问候、解释、表格调整不取数。
沿用同一任务已确认且用途适用的人员、时间和位置；不要反复确认同一条件。
人员或地点不明确、多个候选时，用 question 只问缺项，不默认取第一项，不自动遍历所有位置。
已取得位置只是候选，需用户明确选择。抓拍时间与半径需用途明确，轨迹时间不自动变成抓拍时间。
person_identity 可使用已确认身份或该任务来源中的人员引用；已选来源的坐标由平台读取。
零记录只写查询时段和 0 条；不得自动扩大范围、自动翻页或重试未知调用。单次时间跨度不超过 31 天。
答复不写免责声明或「不等于/不证明/不代表/仅作参考」类句子。
用户取消补充时停止对应查询，基于成功资料给出阶段回答，不把取消解释为全部资料失败。
资料类回答包含人员基本信息、研判摘要、分析依据、下一步研判；来源事实与模型说明区分。
建议最多三项，只建议必要且可用的下一步，不自动执行。不作个人犯罪倾向、嫌疑评分或排名。
周边警情仅支持空间及分页条件；用户要求的时间或类别条件无法传给接口时，在答复中写明未按该条件筛选。时间线中区分处警时间与案发时间。
""" + ('用户已要求停止追问，直接整理已有资料。' if context.get('stop_followup') else '') + '\n' + adapter.canonical(payload)
