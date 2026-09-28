"""Versioned task-local table answers. No provider or model I/O during projection."""
import copy
import html
import json
import re
from shared import theft_provider_v2 as provider

from . import theft_scoring

VERSION = 'person-tables-v3'
SUPPORTED_FORMATS = {'person-tables-v1', 'person-tables-v2', 'person-tables-v3'}
SUPPORTED_POLICY = {'person-tables-v1', 'person-tables-v2', 'person-tables-v3'}


def person(store, uid, sid, context):
    value = context.get('confirmed', {}).get('person_identity')
    if not value:
        if len(context.get('source_refs', [])) == 1:
            from .native_tool_scope import source_values
            from fastapi import HTTPException
            try:
                derived, _ = source_values(store, uid, sid, 'profile', context)
                return derived.get('person_ref')
            except HTTPException:
                return None
        return None
    return provider.person_ref(provider.person_id(value), store.worker_key.encode(), uid + '/' + sid)


def _candidate_refs(context):
    return {item.get('person_ref') for item in (context.get('candidate_set') or []) if isinstance(item, dict) and item.get('person_ref')}


def freeze(store, uid, sid, snapshot, payload):
    from .trusted_results import checked_result
    context = snapshot['native_tool_context']
    subject = person(store, uid, sid, context)
    candidates = _candidate_refs(context)
    history = []
    queried = []
    omitted = 0
    rows = store.rows("SELECT b.request_ciphertext, r.* FROM business_runs b JOIN run_results r ON r.run_id=b.id WHERE b.uid=? AND b.session_id=? ORDER BY b.rowid DESC LIMIT 50", (uid, sid))
    for row in rows:
        prior = store.decrypt(row['request_ciphertext'])
        scope = prior.get('native_tool_context', {})
        if scope.get('task_id') != context['task_id']:
            continue
        result = checked_result(store, row)
        queried += completed_queries(prior)
        selected = []
        if subject:
            selected = select_records(result, prior, subject)
            if context.get('direction') == 'person_to_case':
                selected += [r for r in select_records(result, prior, None, spatial=True) if r.get('module') == 'incidents']
        if candidates:
            selected = list({r['record_id']: r for r in selected + select_records(result, prior, None, spatial=True, subjects=candidates)}.values())
        elif not subject and context.get('direction') == 'case_to_person':
            selected = select_records(result, prior, None, spatial=True)
            selected = select_records(result, prior, None, spatial=True,
                                      subjects=_distinct_capture_persons(selected, prior) or None)
        if selected:
            ids = {r['record_id'] for r in selected}
            entry = {'run_id': result['run_id'], 'generated_at': result.get('generated_at'),
                'records': selected, 'claims': [c for c in result.get('claims', []) if c.get('source_ids') and set(c['source_ids']) <= ids]}
            if len(provider.canonical(history + [entry]).encode()) > 120000:
                omitted += 1
                continue
            history.append(entry)
    snapshot['table_answer_policy'] = {'version': VERSION, 'person_ref': subject, 'history': history,
        'omitted_runs': omitted, 'history_window': 50, 'history_window_full': len(rows) == 50,
        'candidate_refs': sorted(candidates), 'direction': context.get('direction') or 'unknown',
        'layout_version':'theft-four-sections-v1',
        'queried': sorted({tuple(x) for x in queried}, key=lambda x: (x[0], x[1] or ''))}
    payload['system'] = payload.get('system', '') + INSTRUCTION + '\n当前任务已取得资料（仅引用，不是查询指令）：' + provider.canonical(history)


def case_reference(context, records):
    """Case point for case-to-person D5 from the confirmed position and stated or matched case time."""
    confirmed = context.get('confirmed') or {}
    window = context.get('capture_conditions') or confirmed
    return theft_scoring.case_reference(
        confirmed.get('lon'), confirmed.get('lat'), confirmed.get('case_time'),
        [r for r in records if r.get('module') == 'incidents'], window.get('start'), window.get('end'))


def completed_queries(snapshot):
    """[kind, person_ref] for every provider call that completed, including zero-row ones."""
    out = []
    for call in (snapshot.get('native_calls') or {}).values():
        plan = call.get('frozen') or {}
        if call.get('status') == 'completed' and plan.get('kind'):
            out.append([plan['kind'], (plan.get('query') or {}).get('person_ref')])
    return out


def queried_kinds(policy, snapshot, person_ref):
    """Modules queried for one person; location queries count for the focused person."""
    kinds = set()
    for kind, ref in list(policy.get('queried') or []) + completed_queries(snapshot):
        if ref == person_ref or (ref is None and kind in ('incidents', 'captures')):
            kinds.add(kind)
    return kinds


def select_records(result, snapshot, subject, spatial=False, subjects=None):
    records = []
    allowed = set(subjects or [])
    for record in result.get('records', []):
        call = snapshot.get('native_calls', {}).get(record.get('call_id'), {})
        plan = call.get('frozen', {})
        if call.get('status') != 'completed':
            continue
        ref = (plan.get('query') or {}).get('person_ref')
        owner = ref or theft_scoring.subject_of(record, snapshot)
        if (subject and ref == subject) or (allowed and owner in allowed) or (spatial and plan.get('kind') in ('incidents', 'captures')):
            item = copy.deepcopy(record)
            if owner:
                item['subject_ref'] = owner
            records.append(item)
    return records


INSTRUCTION = """
资料终稿只输出一个 person-tables-v3 JSON 对象，由平台渲染为人员基本信息、研判摘要、分析依据、下一步研判四段式，不另外生成Markdown终稿。
格式：{"format":"person-tables-v3","mode":"data","source_refs":["已取得的记录编号"],"scoring":{"requested":true},"suggestions":[{"action":"inspect_sources","text":"查看本次来源详情","reason":"核对已取得记录","conditions":"无需新增查询","reason_source":"已取得的记录编号"}]}。
scoring仅当用户明确要求综合研判、嫌疑评估、评分或排序，且处于由人到案或由案到人工作流时才声明requested=true；其余场景省略该字段。评分与排名由平台按确定性规则计算并在终稿表格中呈现，你不得自行给出、修改分数或排序。
source_refs只能引用当前任务已取得资料；平台逐字段核对并生成事实表，不把自由文字当作已核验结论。
suggestions由你按具体缺口提出，最多三项。action可为query、clarify_scope、inspect_sources、inspect_cases；query须提供当前授权的kind，缺项放fields，具体建议用text、reason、conditions、reply。不得自动执行建议。
不要求查完全部接口，未查询不是失败。失败、零条和未知分别说明；不输出个人犯罪倾向，不下确定性罪责结论，评分相关表述用「可能性研判」措辞。
问候、能力说明和缺项追问使用自然中文，不输出JSON；需要补充时用question。取消补充后整理已有结果。
"""



def selection(text):
    if not isinstance(text, str):
        return {}
    value = text.strip()
    blocks = re.findall(r'```json\s*([\s\S]*?)```', value)
    if len(blocks) == 1:
        value = blocks[0].strip()
    try:
        data, _ = json.JSONDecoder().raw_decode(value)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) and data.get('format') in SUPPORTED_FORMATS and data.get('mode') == 'data' else {}


def suggestion_key(item):
    """Semantic identity for dedup: action + kind + fields."""
    fields = item.get('fields') or []
    if not isinstance(fields, list):
        fields = []
    n = item.get('n')
    return (item.get('action'), item.get('kind'), tuple(fields), n)


def _clip(text, limit=200):
    if not isinstance(text, str):
        return ''
    value = text.strip()
    return value[:limit] if len(value) > limit else value


def _distinct_capture_persons(records, snapshot=None):
    refs = set()
    for r in records or []:
        if r.get('module') != 'captures':
            continue
        ref = theft_scoring.subject_of(r, snapshot)
        if ref:
            refs.add(ref)
    return refs


def model_suggestions(chosen, aliases=None):
    """Accept model suggestions with loose validation. Max 5."""
    out = []
    seen = set()
    allowed_actions = {
        'query', 'clarify_scope', 'inspect_sources', 'authorize_candidates', 'inspect_cases',
    }
    for item in chosen.get('suggestions', []) if isinstance(chosen.get('suggestions'), list) else []:
        if len(out) >= 5 or not isinstance(item, dict):
            continue
        action = item.get('action')
        if action not in allowed_actions:
            continue
        kind = item.get('kind')
        if action == 'query':
            if not isinstance(kind, str) or kind not in provider.CATALOG:
                continue
        else:
            kind = kind if isinstance(kind, str) and kind in provider.CATALOG else None
        fields = item.get('fields') if isinstance(item.get('fields'), list) else []
        fields = [f for f in fields if isinstance(f, str)][:8]
        text = _clip(item.get('text') or item.get('reply') or '')
        reply = _clip(item.get('reply') or text)
        if not text and not reply:
            continue
        reason = _clip(item.get('reason') or item.get('purpose') or '', 300)
        conditions = _clip(item.get('conditions') or '', 200)
        refs = []
        reason_source = item.get('reason_source')
        if isinstance(reason_source, str) and aliases:
            refs = list(aliases.get(reason_source, []))
        candidate = {
            'text': text or reply,
            'reason': reason or '模型建议',
            'conditions': conditions or '需你选择',
            'source_ids': refs,
            'origin': 'model_selection',
            'action': action,
            'kind': kind if action == 'query' else None,
            'fields': fields,
            'reply': reply or text,
        }
        if type(item.get('n')) is int and 1 <= item['n'] <= 20:
            candidate['n'] = item['n']
        key = suggestion_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def model_case_checks(chosen, record_ids):
    """Accept model case_checks rows when source_ids map to real records."""
    raw = chosen.get('case_checks') if isinstance(chosen, dict) else None
    items_in = None
    if isinstance(raw, dict):
        items_in = raw.get('items')
    elif isinstance(raw, list):
        items_in = raw
    if not isinstance(items_in, list):
        return None
    allowed = set(record_ids or [])
    items = []
    for row in items_in[:20]:
        if not isinstance(row, dict):
            continue
        sources = row.get('source_ids') if isinstance(row.get('source_ids'), list) else []
        sources = [s for s in sources if isinstance(s, str) and s in allowed]
        if not sources:
            continue
        compare = _clip(row.get('compare') or row.get('comparison') or '', 40)
        if compare and compare not in ('待核验', '仅案类相同', '存在待核联系'):
            compare = '待核验'
        items.append({
            'cjbh': _clip(row.get('cjbh') or '未提供编号', 80),
            'cjsj': _clip(row.get('cjsj') or '未提供处警时间', 80),
            'distance_m': row.get('distance_m') if isinstance(row.get('distance_m'), (int, float)) else None,
            'time_delta_hours': row.get('time_delta_hours') if isinstance(row.get('time_delta_hours'), (int, float)) else None,
            'item_or_id': _clip(row.get('item_or_id') or row.get('item') or '', 120),
            'time_link': _clip(row.get('time_link') or '', 200),
            'behavior_link': _clip(row.get('behavior_link') or '', 200),
            'compare': compare or '待核验',
            'relation': _clip(row.get('relation') or '', 200),
            'status': _clip(row.get('status') or '待核验', 40),
            'follow_up': _clip(row.get('follow_up') or '', 200),
            'source_ids': sources,
        })
    if not items:
        return None
    return {
        'version': 'model-case-checks-v1',
        'title': '候选案件逐案核验',
        'items': items,
        'disclaimer': '候选案件状态由模型填写，需人工核对处警记录。',
    }


def next_question(run_id, suggestions, chosen=None, context=None):
    """Prefer model-authored next_question; else build options from suggestion replies."""
    context = context or {}
    if context.get('stop_followup'):
        return None
    chosen = chosen or {}
    raw = chosen.get('next_question') if isinstance(chosen.get('next_question'), dict) else None
    if raw:
        options = []
        for opt in raw.get('options') or []:
            if not isinstance(opt, dict):
                continue
            label = _clip(opt.get('label') or opt.get('reply') or opt.get('text') or '')
            if not label:
                continue
            options.append({
                'label': label,
                'description': _clip(opt.get('description') or opt.get('reason') or '', 300),
                'action': opt.get('action') if isinstance(opt.get('action'), str) else 'query',
                'send': False if opt.get('send') is False else True,
            })
            if len(options) >= 8:
                break
        if options:
            multiple = False if raw.get('multiple') is False else True
            return {
                'id': f'next-{run_id}',
                'header': _clip(raw.get('header') or '下一步分析', 40) or '下一步分析',
                'question': _clip(raw.get('question') or '请选择下一步。', 200) or '请选择下一步。',
                'options': options,
                'custom': True,
                'multiple': multiple,
            }
    options = []
    for item in suggestions or []:
        reply = (item.get('reply') or item.get('text') or '').strip()
        if not reply:
            continue
        options.append({
            'label': reply[:200],
            'description': item.get('reason') or '',
            'action': item.get('action') or 'query',
            'send': item.get('action') != 'clarify_scope',
        })
        if len(options) >= 5:
            break
    if not options:
        return None
    return {
        'id': f'next-{run_id}',
        'header': '下一步分析',
        'question': '请选择下一步，选择后才会查询。',
        'options': options,
        'custom': True,
        'multiple': True,
    }



TRACK_SEGMENT_LABELS = {'too_many': '单段结果过多', 'failed': '查询失败', 'not_queried': '超出分段上限未查询'}


def track_segment_gaps(snapshot):
    gaps = []
    for call in (snapshot.get('native_calls') or {}).values():
        if call.get('status') != 'completed':
            continue
        for item in (call.get('public_response') or {}).get('segments') or []:
            if isinstance(item, dict) and item.get('status') in TRACK_SEGMENT_LABELS:
                gaps.append(f"{item.get('start')} 至 {item.get('end')}（{TRACK_SEGMENT_LABELS[item['status']]}）")
    return gaps


def build(result, snapshot):
    policy = snapshot.get('table_answer_policy', {})
    if policy.get('version') not in SUPPORTED_POLICY:
        return None
    chosen = selection(snapshot.get('model_final_text', ''))
    if not snapshot.get('native_calls') and not chosen:
        return None
    history = policy.get('history', [])
    context = snapshot.get('native_tool_context') or {}
    candidates = _candidate_refs(context)
    records = select_records(result, snapshot, policy.get('person_ref'), spatial=True,
                             subjects=candidates or None)
    if not candidates and not policy.get('person_ref') and context.get('direction') == 'case_to_person':
        records = select_records(result, snapshot, None, spatial=True,
                                 subjects=_distinct_capture_persons(records, snapshot) or None)
    current_ids = {r['record_id'] for r in records}
    eligible_calls = {r.get('call_id') for r in records} | {
        k for k, v in snapshot.get('native_calls', {}).items()
        if v.get('status') == 'completed' and (
            v.get('frozen', {}).get('query', {}).get('person_ref') == policy.get('person_ref')
            or v.get('frozen', {}).get('query', {}).get('person_ref') in candidates
        ) and (policy.get('person_ref') or candidates)
    }
    claims = [c for c in result.get('claims', []) if (c.get('source_ids') and set(c['source_ids']) <= current_ids) or (not c.get('source_ids') and c.get('protected_fields', {}).get('call_id') in eligible_calls)]
    for item in history:
        records += copy.deepcopy(item['records'])
        claims += copy.deepcopy(item['claims'])
    records = list({r['record_id']: r for r in records}.values())
    ids = {r['record_id'] for r in records}
    approved = [c for c in claims if c.get('verification_status') == 'approved' and set(c.get('source_ids', [])) <= ids]
    aliases = {}
    for r in records:
        for key in (r['record_id'], r['record_id'].split(':', 2)[-1]):
            aliases.setdefault(key, []).append(r['record_id'])
    for r in records:
        group = [x for x in records if x['snapshot_id'] == r['snapshot_id']]
        if len({x['source_run_id'] for x in group}) == 1:
            aliases[r['snapshot_id']] = [x['record_id'] for x in group]
    selected = []
    for ref in chosen.get('source_refs', []) if isinstance(chosen.get('source_refs'), list) else []:
        if isinstance(ref, str) and aliases.get(ref):
            selected.extend(aliases[ref])
    rank_map = {rid: i for i, rid in enumerate(selected)}
    approved.sort(key=lambda c: min((rank_map.get(r, 100000) for r in c.get('source_ids', [])), default=100001))
    conclusions = [{'text': c['statement'], 'source_ids': c['source_ids'], 'source_run_id': c['source_run_id'],
                    'claim_id': c['claim_id'], 'limitation': ''} for c in approved[:5]]
    basic = []
    dates = {result['run_id']: result.get('generated_at'), **{h['run_id']: h.get('generated_at') for h in history}}
    for r in records:
        if r['module'] != 'profile':
            continue
        data = r['fields'].get('person', {})
        if not isinstance(data, dict) or (policy.get('person_ref') and data.get('sfz') != policy.get('person_ref')):
            if not candidates or data.get('sfz') not in candidates:
                continue
        for key, label in [('name', '姓名'), ('sfz', '人员编号'), ('gender', '性别'), ('age', '年龄')]:
            v = data.get(key)
            value = str(v) if isinstance(v, (str, int)) and not isinstance(v, bool) else '来源未提供'
            basic.append({'label': label, 'value': value, 'source_ids': [r['record_id']],
                          'source_run_id': r['source_run_id'], 'obtained_at': dates.get(r['source_run_id'])})
    missing = list(result.get('missing', []))
    track_gaps = track_segment_gaps(snapshot)
    if policy.get('omitted_runs'):
        missing.append('历史上下文达到资源上限，部分执行未纳入本次整理；可指定来源另行解释。')
    if policy.get('history_window_full'):
        missing.append('历史引用限于当前会话最近50次执行，未声称覆盖更早资料。')
    evidence = []
    for r in records:
        c = next((c for c in approved if c.get('type') == 'fact' and r['record_id'] in c['source_ids']), None)
        f = r['fields']
        evidence.append({'module': r['module'], 'label': provider.CATALOG[r['module']][0],
            'time': f.get('captureTime') or f.get('timeRangeStart') or f.get('latestTime') or '来源未明确时间',
            'text': c['statement'] if c else '已取得来源，尚无可展示的逐项核对说明。',
            'source_ids': [r['record_id']], 'source_run_id': r['source_run_id'], 'snapshot_id': r['snapshot_id']})
    from .data_plugin_policy import ACTIVE_KINDS
    allowed = {'peixian_query_' + k for k in ACTIVE_KINDS}
    present = {r['module'] for r in records}
    confirmed = context.get('confirmed') or {}
    labels = {'person_identity': '人员对象', 'start': '开始时间', 'end': '结束时间', 'radius_m': '半径', 'lon': '经度', 'lat': '纬度'}

    model_direction = chosen.get('direction') if isinstance(chosen.get('direction'), str) else None
    if model_direction not in ('case_to_person', 'person_to_case', 'unknown'):
        model_direction = None
    direction = model_direction or context.get('direction') or policy.get('direction') or 'unknown'
    ranking = None
    case_view = None
    scoring = None
    # Model scoring.requested is authoritative when present; else fall back to context.
    if isinstance(chosen.get('scoring'), dict) and 'requested' in chosen['scoring']:
        want_score = bool(chosen['scoring'].get('requested'))
    else:
        want_score = bool(context.get('scoring_requested'))
    # Scoring allowed only in the two workflow directions (p2c/c2p); legacy adaptive policy stays off.
    if snapshot.get('dialogue_policy')=='adaptive-dialogue-v1' or direction not in ('case_to_person','person_to_case'): want_score=False
    if direction == 'case_to_person' and want_score:
        captures = [r for r in records if r.get('module') == 'captures']
        case_ref = case_reference(context, records)
        if context.get('candidate_set'):
            groups = theft_scoring.group_by_person(records, snapshot)
            authorized = {item['person_ref']: groups.get(item['person_ref'], []) for item in context['candidate_set']}
            ranking = theft_scoring.rank(authorized, case_ref=case_ref,
                                         queried_by_person={ref: queried_kinds(policy, snapshot, ref) for ref in authorized})
        else:
            # No authorize step required: rank people who already have non-capture records,
            # else fall back to stage-1 capture ranking.
            groups = theft_scoring.group_by_person(records, snapshot)
            enriched = {
                ref: rows for ref, rows in groups.items()
                if ref and any(r.get('module') != 'captures' for r in rows)
            }
            if enriched:
                ranking = theft_scoring.rank(enriched, case_ref=case_ref,
                                             queried_by_person={ref: queried_kinds(policy, snapshot, ref) for ref in enriched})
            elif captures and len(_distinct_capture_persons(captures, snapshot)) >= 2:
                ranking = theft_scoring.stage1_rank(captures)
        if ranking and ranking.get('items'):
            top = ranking['items'][0]
            title = ranking.get('title') or ('初步关注排序' if ranking.get('stage') == 'stage1' else '嫌疑人可能性排序')
            conclusions = [{
                'text': f"{title}首位有效得分率 {top.get('rate')}%，{top.get('band') or ''}。",
                'source_ids': top.get('source_ids') or [],
                'source_run_id': result['run_id'],
                'claim_id': 'platform-ranking',
                'limitation': '',
            }] + conclusions
        elif ranking and ranking.get('status') == 'empty':
            missing.append('尚无可用的抓拍候选人可供排序。')
    elif want_score and policy.get('person_ref'):
        person_ref = policy['person_ref']
        history_ids = set() if candidates else {r['record_id'] for item in history for r in item['records']}
        calls = snapshot.get('native_calls') or {}
        person_records = [r for r in records if r.get('module') == 'incidents' or r['record_id'] in history_ids
                          or theft_scoring.subject_of(r, snapshot) == person_ref
                          or calls.get(r.get('call_id'), {}).get('frozen', {}).get('query', {}).get('person_ref') == person_ref]
        scoring = theft_scoring.compute(person_records, include_d5=True,
                                        queried=queried_kinds(policy, snapshot, person_ref))
        if scoring.get('status') == 'ready':
            conclusions = [{
                'text': f"有效得分率 {scoring['rate']}%（{scoring['earned']} / {scoring['available_max']}），{scoring['band']}。",
                'source_ids': sorted({sid for d in scoring['dimensions'] for sid in d.get('source_ids', [])}),
                'source_run_id': result['run_id'],
                'claim_id': 'platform-scoring',
                'limitation': '',
            }] + conclusions
        elif scoring.get('status') == 'insufficient':
            pass

    case_view = None if context.get('query_rules_version')=='on-demand-v1' else model_case_checks(chosen, {r['record_id'] for r in records})
    if direction == 'person_to_case' and context.get('query_rules_version') != 'on-demand-v1' and snapshot.get('dialogue_policy') != 'adaptive-dialogue-v1':
        tracks = [r for r in records if r.get('module') == 'tracks']
        incidents = [r for r in records if r.get('module') == 'incidents']
        if tracks and incidents:
            platform_cases = theft_scoring.case_checks(tracks, incidents)
            if not case_view or not case_view.get('items'):
                case_view = platform_cases
            elif platform_cases.get('items'):
                case_view = platform_cases
        # Ensure six-dim scoring for the focused person
        if want_score and scoring is None:
            person_ref = policy.get('person_ref')
            person_records = [r for r in records if person_ref and (
                theft_scoring.subject_of(r, snapshot) == person_ref
                or ((snapshot.get('native_calls') or {}).get(r.get('call_id'), {}).get('frozen', {}).get('query', {}).get('person_ref') == person_ref)
            )]
            if not person_records:
                person_records = [r for r in records if r.get('module') in (
                    'tracks', 'night', 'community', 'warning_detail', 'warnings', 'warning_logs', 'profile', 'incidents')]
            scoring = theft_scoring.compute(person_records, include_d5=True)
            if scoring.get('status') == 'ready':
                conclusions = [{
                    'text': f"关联可疑度（辅助）有效得分率 {scoring['rate']}%（{scoring['earned']} / {scoring['available_max']}），{scoring['band']}。",
                    'source_ids': sorted({sid for d in scoring['dimensions'] for sid in d.get('source_ids', [])}),
                    'source_run_id': result['run_id'],
                    'claim_id': 'platform-scoring',
                    'limitation': '',
                }] + conclusions
            elif scoring.get('status') == 'insufficient':
                pass

    coverage = None
    plan = context.get('person_case_plan')
    if isinstance(plan, dict) and plan.get('coverage'):
        from . import person_case_flow as pcf
        coverage = {'version': plan.get('version'), 'rows': pcf.coverage_appendix(plan), 'complete': plan.get('complete')}

    # Model suggestions only; platform no longer injects flow steps.
    suggestions = model_suggestions(chosen, aliases=aliases)
    if context.get('query_rules_version')=='on-demand-v1':
        tools=set(snapshot.get('native_tool_policy',{}).get('allowed_tools',[]))
        suggestions=[x for x in suggestions if x['action']!='authorize_candidates' and (x['action']!='query' or 'peixian_query_'+str(x['kind']) in tools)][:3]

    return {'version': VERSION, 'run_id': result['run_id'], 'person_ref': policy.get('person_ref'),
        **({'layout_version':policy['layout_version']} if policy.get('layout_version') else {}),
        'status': 'partial' if missing else 'ready',
        'basic': basic, 'conclusions': conclusions, 'evidence': evidence, 'suggestions': suggestions,
        'next_question': next_question(result['run_id'], suggestions, chosen=chosen, context=context),
        'missing': list(dict.fromkeys(missing)), 'preview_count': min(10, len(evidence)), 'total': len(evidence),
        'selection_status': 'accepted' if chosen else 'fallback',
        'source_runs': sorted({r['source_run_id'] for r in records}),
        'scoring': scoring, 'ranking': ranking, 'case_checks': case_view,
        'coverage': coverage,
        'track_gaps': track_gaps,
        'direction': direction,
        'case_type': chosen.get('case_type') if isinstance(chosen.get('case_type'), str) else None}


def escape(value):
    text = str(value).replace('：\n- ', '：').replace('\n- ', '；')
    text = html.escape(text, quote=True).replace('\r', ' ').replace('\n', ' ')
    for char in ('\\', '`', '*', '_', '[', ']', '|', '#'):
        text = text.replace(char, '\\' + char)
    return text


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |'] +
        ['| ' + ' | '.join(escape(v) for v in row) + ' |' for row in rows])


def markdown(view):
    if view.get('version') not in SUPPORTED_POLICY:
        return '当前表格版本暂不受支持，请查看已有来源。'
    sections = []
    revised=view.get('layout_version')=='theft-four-sections-v1'
    if view.get('basic'):
        sections += ['### 人员基本信息', table(['信息项', '内容', '来源／说明'],
            [(x['label'], x['value'], '、'.join(x['source_ids']) + '；取得时间：' + str(x['obtained_at'] or '未提供')) for x in view['basic']])]
    if view.get('conclusions'):
        sections += ['### 研判摘要' if revised else '### 基本结论',
            table(['结论', '依据'], [(x['text'], '、'.join(x['source_ids']) or '本轮已确认响应统计') for x in view['conclusions']])]

    def evidence(rows):
        return table(['资料类型', '时间／范围', '记录摘要', '来源'], [(x['label'], x['time'], x['text'], '、'.join(x['source_ids'])) for x in rows])

    if view.get('evidence'):
        sections += ['### 分析依据' if revised else '### 判断依据', evidence(view['evidence'][:10])]
        if len(view['evidence']) > 10:
            sections += ['<details><summary>展开其余已取得记录</summary>\n\n' + evidence(view['evidence'][10:]) + '\n\n</details>']
    if view.get('track_gaps'):
        sections += ['轨迹未核验时段：' + '；'.join(escape(x) for x in view['track_gaps']) + '。其余时段轨迹已取得。']

    ranking = view.get('ranking')
    if ranking and ranking.get('items'):
        title = ranking.get('title') or '关联线索与嫌疑人可能性排序'
        sections += [f'### {title}']
        rows = []
        for item in ranking['items']:
            rows.append((
                item.get('rank'),
                (item.get('name') or '') + '／' + (item.get('person_ref') or ''),
                item.get('stage'),
                f"{item.get('rate')}%" if item.get('rate') is not None else '—',
                item.get('band') or '',
                '；'.join(item.get('reasons') or []) or '—',
                '；'.join(item.get('next_checks') or []) or (item.get('follow_up') or ''),
                '、'.join(item.get('source_ids') or []) or '无',
                '；'.join(item.get('gaps') or []) or '无',
            ))
        sections += [table(
            ['排序', '人员', '阶段', '有效得分率', '关联度', '主要依据', '建议核验', '支持来源', '矛盾与缺口'],
            rows,
        )]
        for item in ranking.get('insufficient') or []:
            gaps = '；'.join(item.get('gaps') or []) or '可用维度不足'
            sections += [
                f"覆盖不足：{(item.get('name') or '') + '／' + (item.get('person_ref') or '')}；缺：{gaps}"
            ]

    scoring = view.get('scoring')
    if scoring:
        sections += ['### 可疑度评分']
        rows = []
        for d in scoring.get('dimensions', []):
            score = '—' if d['status'] != 'available' else f"{d['score']} / {d['max']}"
            status = '可用' if d['status'] == 'available' else '不可用'
            rows.append((d['label'], score, status, d.get('evidence') or '', '、'.join(d.get('source_ids') or []) or '无'))
        sections += [table(['维度', '得分／满分', '状态', '依据', '来源'], rows)]
        if scoring.get('status') == 'ready':
            sections += [f"有效得分率 {scoring['rate']}%（{scoring['earned']} / {scoring['available_max']}），{scoring['band']}。"]

    case_view = view.get('case_checks')
    if case_view and case_view.get('items'):
        sections += ['### 候选案件逐案核验']
        rows = []
        graded = any(isinstance(item, dict) and item.get('grade') for item in case_view['items'])
        for item in case_view['items']:
            if graded:
                rows.append((
                    item.get('cjbh'),
                    item.get('cjsj'),
                    '—' if item.get('distance_m') is None else f"{item['distance_m']} 米",
                    '—' if item.get('time_delta_hours') is None else f"{item['time_delta_hours']} 小时",
                    item.get('grade') or '',
                    item.get('relation'),
                    '；'.join(item.get('reasons') or []) or '—',
                    '；'.join(item.get('next_checks') or []) or (item.get('follow_up') or ''),
                    item.get('status'),
                ))
            else:
                rows.append((
                    item.get('cjbh'),
                    item.get('cjsj'),
                    '—' if item.get('distance_m') is None else f"{item['distance_m']} 米",
                    '—' if item.get('time_delta_hours') is None else f"{item['time_delta_hours']} 小时",
                    item.get('item_or_id') or '',
                    item.get('time_link') or '',
                    item.get('behavior_link') or '',
                    item.get('compare') or '',
                    item.get('relation'),
                    item.get('status'),
                    item.get('follow_up'),
                ))
        if graded:
            sections += [table(
                ['警情编号', '处警时间', '最近直线距离', '时间差', '时空等级', '关系', '主要依据', '建议核验', '核验状态'],
                rows,
            )]
        else:
            sections += [table(
                ['警情编号', '处警时间', '最近直线距离', '时间差', '物品／编号', '时间联系', '行为联系', '比较结论', '关系', '核验状态', '补证任务'],
                rows,
            )]


    coverage = view.get('coverage')
    if coverage and coverage.get('rows'):
        sections += ['### 八接口覆盖清单']
        sections += [table(['资料接口', '状态'], coverage['rows'])]
        if coverage.get('complete'):
            sections += ['本轮计划内接口已覆盖完毕（失败项见上表）。']

    # Enrich platform case rows with grade/reasons when present
    case_view = view.get('case_checks')
    if case_view and case_view.get('items') and any(item.get('grade') for item in case_view['items']):
        # Replace last case table section content by rebuilding from grade-aware rows if simple format was used
        pass

    if revised:
        sections += ['### 下一步研判', table(['建议','提出原因','需要补充的条件'],
            [(x['text'],x['reason'],x['conditions']) for x in view.get('suggestions',[])]) if view.get('suggestions') else '暂无新的分析建议，可查看已有来源。']
    output = '\n\n'.join(sections)
    sources = []
    links = {}
    for index, item in enumerate(view['evidence'], 1):
        rid = item['source_ids'][0]
        anchor = 'source-' + re.sub('[^a-zA-Z0-9-]', '', view.get('run_id', 'result')) + '-' + str(index)
        links.setdefault(escape(rid), f'[来源{index}](#{anchor})')
        sources.append(f'<details id="{anchor}"><summary>来源{index} · ' + escape(item['label']) + '</summary>\n\n' +
            table(['来源信息', '值'], [('记录编号', rid), ('执行编号', item['source_run_id']), ('快照', item['snapshot_id'])]) + '\n\n</details>')
    if links:
        # Record ids share prefixes (":1" vs ":10"); match longest first and never stop mid-number.
        pattern = re.compile('(?:' + '|'.join(re.escape(k) for k in sorted(links, key=len, reverse=True)) + ')(?![0-9])')
        output = pattern.sub(lambda m: links[m.group(0)], output)
    if sources:
        output = output + '\n\n<details><summary>查看来源编号与版本</summary>\n\n' + '\n\n'.join(sources) + '\n\n</details>'
    return output
