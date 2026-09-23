"""Native theft-tool conditions. Facts are accepted only from user-confirmed scope.

This module has no business workflow graph. It records exact input values and
rejects model-generated widening. A model chooses the next tool and can ask a
question; only the independent execution gate may call a supplier.
"""
import copy
import re
import uuid

from .backend_contract import error
from .data_plugin_policy import ACTIVE_KINDS
from .theft_planner import slots
from shared import theft_provider_v2 as adapter

TOOL_TO_KIND={'peixian_query_'+kind:kind for kind in ACTIVE_KINDS}
FILTERS=re.compile(r'近期|最近|近\s*\d+\s*[天月年]|仅.*盗窃|只.*盗窃|限定时间|限定日期')


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
    return {'version':'native-tool-context-v1','task_id':task_id,
        'scope_version':prior['scope_version']+1 if prior else 1,
        'confirmed':confirmed,'source_refs':refs,
        'current_text':text,'constraints_text':constraints,'user_conditions':current}


def arguments(kind,args,context):
    """Return only values the user explicitly confirmed; never trust tool input."""
    if kind not in ACTIVE_KINDS or not isinstance(args,dict):
        error('native_tool_invalid','资料工具或参数无效。',422)
    supported={'lon','lat','radius_m','person_identity','start','end','page','page_size'}
    if kind=='captures':supported-={'lon','lat'}
    if set(args)-supported:
        error('native_tool_invalid','查询参数包含未开放的条件。',422)
    confirmed=context['confirmed']
    if isinstance(args.get('person_identity'),str) and args['person_identity'].startswith('person-'):
        error('identity_parameter_invalid','person_identity 必须使用已确认的原始身份号码，不能使用展示引用。',409)
    for key,value in args.items():
        if key not in confirmed or str(confirmed[key])!=str(value):
            error('scope_unconfirmed','工具参数未在当前任务范围内确认，请先向用户提问。',409)
    # A supplied user condition cannot be silently discarded for the selected
    # interface. In particular /jq/search has no time/category filter.
    if kind=='incidents' and FILTERS.search(context.get('constraints_text',context['current_text'])):
        error('unsupported_scope','当前警情接口只支持空间及分页；请说明上游默认覆盖范围并征求确认。',409)
    # A person may be present in a multi-tool task without filtering the
    # spatial incident query. Explicit person-only restrictions cannot be enforced.
    if (kind=='incidents' and 'person_identity' in context.get('user_conditions',{})
            and re.search(r'(仅|只)(查询|查|看)?.{0,12}(此人|该人员|这名人员|身份证|该人)',context['current_text'])):
        error('unsupported_scope','当前警情接口不能按人员筛选；请说明限制并澄清查询范围。',409)
    if context['source_refs'] and {'lon','lat','person_identity'} & args.keys():
        error('source_value_override','已选择来源时不能再替换对象或坐标。',409)
    required=({'radius_m'} if context['source_refs'] else {'lon','lat','radius_m'}) if kind=='incidents' else {'radius_m'} if kind=='captures' else set() if context['source_refs'] else {'person_identity'}
    if kind in adapter.TIMED:required|={'start','end'}
    if not required<=set(args):
        error('scope_missing','查询所需对象、时间或范围尚未明确，请先提问。',409)
    if kind=='captures':
        if len(context['source_refs'])!=1:
            error('source_selection_required','周边抓拍必须先选择一个明确的位置来源。',409)
        if not {'radius_m','start','end'}<=set(context['user_conditions']):
            error('capture_scope_unconfirmed','抓拍时间和半径必须独立确认，不能沿用轨迹或警情范围。',409)
    if kind in adapter.PAGED:
        # Pagination defaults are contract defaults; page >1 requires an
        # explicit user-supplied value, not a model continuation guess.
        if args.get('page',1)>1 and 'page' not in context['user_conditions']:
            error('page_unconfirmed','翻页需要用户明确请求。',409)
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
    """Explain the frozen argument contract; never rewrite submitted tool input."""
    return ('\n本轮原生工具参数约定：person_identity 只填写用户已确认的原始单人身份号码；'
        'person-* 是来源展示引用，不是身份号码，不能填入 person_identity，不要要求用户确认内部引用。'
        '已选定来源时，对象或坐标由平台从该来源读取，不在工具参数中重复传入。'
        '以下已确认值不是要求查询全部能力；只取当前问题需要的字段，缺项通过 question 提问。'
        '意图核对或参数错误不代表记录为零；不自行重试失败调用。\n'
        +adapter.canonical({'version':'native-tool-arguments-v1','scope_version':context['scope_version'],
            'confirmed':context['confirmed'],'selected_source_refs':context['source_refs']}))
