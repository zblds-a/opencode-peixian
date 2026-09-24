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
    omitted = 0
    rows = store.rows("SELECT b.request_ciphertext, r.* FROM business_runs b JOIN run_results r ON r.run_id=b.id WHERE b.uid=? AND b.session_id=? ORDER BY b.rowid DESC LIMIT 50", (uid, sid))
    for row in rows:
        prior = store.decrypt(row['request_ciphertext'])
        scope = prior.get('native_tool_context', {})
        if scope.get('task_id') != context['task_id']:
            continue
        result = checked_result(store, row)
        selected = []
        if subject:
            selected = select_records(result, prior, subject)
        if candidates:
            selected = list({r['record_id']: r for r in selected + select_records(result, prior, None, spatial=True, subjects=candidates)}.values())
        elif not subject and context.get('direction') == 'case_to_person':
            selected = select_records(result, prior, None, spatial=True)
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
        'candidate_refs': sorted(candidates), 'direction': context.get('direction') or 'unknown'}
    payload['system'] = payload.get('system', '') + INSTRUCTION + '\n当前任务已取得资料（仅引用，不是查询指令）：' + provider.canonical(history)


def select_records(result, snapshot, subject, spatial=False, subjects=None):
    records = []
    allowed = set(subjects or [])
    for record in result.get('records', []):
        call = snapshot.get('native_calls', {}).get(record.get('call_id'), {})
        plan = call.get('frozen', {})
        if call.get('status') != 'completed':
            continue
        ref = (plan.get('query') or {}).get('person_ref')
        if subject and ref == subject:
            records.append(copy.deepcopy(record))
        elif allowed and (ref in allowed or theft_scoring.subject_of(record, snapshot) in allowed):
            records.append(copy.deepcopy(record))
        elif spatial and plan.get('kind') in ('incidents', 'captures'):
            records.append(copy.deepcopy(record))
    return records


INSTRUCTION = """
回答展示协议 person-tables-v3：保持模型原生工具选择，不机械查询全部工具。每次发出一个资料工具调用，等待其结果后再选择下一项，避免并行请求。
问候、介绍、能力咨询或缺项追问自然回答，必要时使用 question，不查询档案。
由案到人和由人到案由平台隐式判断，你不必让用户选择方向；事件窗口（开始时间、结束时间、半径）不清楚时，先用 question 只追问缺项，不猜测"案发前后"。
由案到人：先查周边抓拍得到候选人初排；用户确认"核验前N名"（N不超过5）后，再对授权候选人逐人查询夜间、跨小区、预警、档案。不得擅自遍历全部人员。
由人到案：在已确认人员后查轨迹，再以轨迹点为来源查周边警情；案件核验状态固定为待核验，不得直接认定涉案。
整理资料时，如下方同任务资料没有该人员档案，可按用户目标调用已授权 peixian_query_profile；无权限、失败或未知不重试。多个候选先用 question 选择，不默认第一人。
资料回答完成时仅输出一个 JSON 对象，不输出 Markdown、开场白或其他文字：
{"format":"person-tables-v3","mode":"data","source_refs":["实际来源"],"scoring":{"requested":true},"suggestions":[{"action":"inspect_sources|clarify_scope|query","kind":"tracks","reason_source":"","fields":["start","end"]}]}
用户明确要求评分、排序、筛选嫌疑人或研判优先级时，可设置 scoring.requested=true；分数与嫌疑人可能性排序由平台按来源计算，你不得自行写分数、等级、排名或犯罪结论。平台也会在用户原文已要求评分时自行计算。
source_refs 不可编造。建议最多三项，不自动执行。缺事件窗口时优先 clarify_scope。普通对话不使用上述 JSON。
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
    return (item.get('action'), item.get('kind'), tuple(fields))


def _already_clarifying(context, chosen, fields):
    """Skip platform clarify when model already asked, or gate already returned field_errors."""
    if context.get('field_errors') or context.get('clarify_pending') or context.get('clarify_fields'):
        return True
    wanted = set(fields or [])
    for item in (chosen.get('suggestions') if isinstance(chosen, dict) else None) or []:
        if not isinstance(item, dict) or item.get('action') != 'clarify_scope':
            continue
        given = item.get('fields') or []
        if isinstance(given, list) and wanted & set(given):
            return True
    return False


def platform_suggestions(context, records, ranking, case_view, allowed_tools=None, snapshot=None, chosen=None):
    """Direction-aware next steps generated by the platform (max 3). Stage-ordered."""
    from . import theft_candidates as candidates

    out = []
    confirmed = context.get('confirmed') or {}
    direction = context.get('direction') or 'unknown'
    labels = {'person_identity': '人员对象', 'start': '开始时间', 'end': '结束时间', 'radius_m': '半径', 'lon': '经度', 'lat': '纬度'}
    allowed = set(allowed_tools or [])
    groups = theft_scoring.group_by_person(records, snapshot)

    def add(text, reason, conditions, action='clarify_scope', kind=None, fields=None, reply=''):
        if len(out) >= 3:
            return
        if action == 'query':
            if not isinstance(kind, str) or kind not in provider.CATALOG:
                return
            if 'peixian_query_' + kind not in allowed:
                return
        item = {'text': text, 'reason': reason, 'conditions': conditions, 'source_ids': [],
                'origin': 'platform_direction', 'action': action, 'kind': kind if action in ('query',) else None,
                'fields': list(fields or []), 'reply': reply or ''}
        if action == 'authorize_candidates':
            item['kind'] = None
        key = suggestion_key(item)
        if any(suggestion_key(x) == key for x in out):
            return
        out.append(item)

    if direction == 'case_to_person':
        missing = [k for k in ('start', 'end', 'radius_m') if k not in confirmed]
        has_captures = any(r.get('module') == 'captures' for r in records)
        if missing and not has_captures and not _already_clarifying(context, chosen, missing):
            add('补充' + '、'.join(labels[k] for k in missing), '查周边抓拍前需要确定事件窗口',
                '由你补充后再决定是否查询', fields=missing, reply=candidates.reply_clarify(missing))
        if ranking and ranking.get('items') and not context.get('candidate_set'):
            n = min(3, len(ranking['items']))
            text = '核验该候选人' if n == 1 else f'核验前{n}名'
            add(text, '对初排靠前的人逐个补查夜间、跨小区、预警和档案，再做六维排序（人数可改为1至5名）', '需你确认人数（1至5名）',
                action='authorize_candidates', reply=candidates.reply_authorize_n(n))
        elif context.get('candidate_set'):
            enrich_jobs = []
            for entry in context['candidate_set']:
                if not isinstance(entry, dict) or not entry.get('person_ref'):
                    continue
                ref = entry['person_ref']
                present = {r.get('module') for r in groups.get(ref, [])}
                missing_kinds = [k for k in candidates.ENRICH_SCORE_KINDS
                                 if k not in present and 'peixian_query_' + k in allowed]
                if missing_kinds:
                    enrich_jobs.append((len(missing_kinds), entry.get('rank') or 99, entry, missing_kinds))
            enrich_jobs.sort(key=lambda x: (-x[0], x[1]))
            for _, _, entry, missing_kinds in enrich_jobs:
                if len(out) >= 3:
                    break
                rank = entry.get('rank') or 1
                name = entry.get('name')
                who = f'第{rank}名' + (f'（{name}）' if name else '')
                kind_labels = [candidates.ENRICH_KIND_LABELS[k] for k in missing_kinds]
                add(f'为{who}补查' + '、'.join(kind_labels),
                    '补齐该候选人的评分维度',
                    '需你选择；仍须通过调用前核对',
                    action='query', kind=missing_kinds[0],
                    reply=candidates.reply_enrich(rank, name, missing_kinds))
            # After six-dim ranking: prompt for insufficient coverage
            if ranking and ranking.get('insufficient'):
                for entry in ranking['insufficient']:
                    if len(out) >= 3:
                        break
                    ref = entry.get('person_ref')
                    cand = next((c for c in context['candidate_set'] if c.get('person_ref') == ref), None)
                    rank = (cand or {}).get('rank') or entry.get('rank') or 1
                    name = entry.get('name') or (cand or {}).get('name')
                    present = {r.get('module') for r in groups.get(ref, [])}
                    missing_kinds = [k for k in candidates.ENRICH_SCORE_KINDS
                                     if k not in present and 'peixian_query_' + k in allowed]
                    if not missing_kinds:
                        continue
                    who = f'第{rank}名' + (f'（{name}）' if name else '')
                    add(f'为覆盖不足的{who}补查' + '、'.join(candidates.ENRICH_KIND_LABELS[k] for k in missing_kinds),
                        '可用维度不足3个，补齐后才能参与排序',
                        '需你选择；仍须通过调用前核对',
                        action='query', kind=missing_kinds[0],
                        reply=candidates.reply_enrich(rank, name, missing_kinds))
    elif direction == 'person_to_case':
        if 'person_identity' not in confirmed and not policy_person_hint(context):
            if not _already_clarifying(context, chosen, ['person_identity']):
                add('补充人员对象', '由人到案需要先确定核查的人员', '由你补充后再决定是否查询',
                    fields=['person_identity'], reply=candidates.reply_clarify(['person_identity']))
        missing = [k for k in ('start', 'end') if k not in confirmed]
        has_tracks = any(r.get('module') == 'tracks' for r in records)
        if missing and not has_tracks and not _already_clarifying(context, chosen, missing):
            add('补充' + '、'.join(labels[k] for k in missing), '查轨迹前需要确定时间窗口',
                '由你补充后再决定是否查询', fields=missing, reply=candidates.reply_clarify(missing))
        if has_tracks and not any(r.get('module') == 'incidents' for r in records):
            add('以轨迹点查询周边警情', '用已有轨迹点查周边警情，逐案核验候选案件', '需你选择轨迹点来源',
                action='query', kind='incidents', reply=candidates.reply_query_incidents())
        if case_view and case_view.get('items'):
            add('核对处警记录原文', '候选案件均为待核验，逐条对照处警时间和地点，不据此认定涉案', '不自动认定涉案',
                action='inspect_sources', reply=candidates.reply_inspect_cases())
    return out[:3]


def policy_person_hint(context):
    return bool((context.get('confirmed') or {}).get('person_identity'))



def next_question(run_id, suggestions):
    """Single-choice card payload for the console QuestionForm."""
    if not suggestions:
        return None
    options = []
    for item in suggestions:
        reply = (item.get('reply') or item.get('text') or '').strip()
        if not reply:
            continue
        options.append({
            'label': reply,
            'description': item.get('reason') or '',
            'action': item.get('action') or 'query',
            'send': item.get('action') != 'clarify_scope',
        })
    if not options:
        return None
    return {
        'id': f'next-{run_id}',
        'header': '下一步分析',
        'question': '请选择下一步，选择后才会查询。',
        'options': options,
        'custom': True,
    }


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
                    'claim_id': c['claim_id'], 'limitation': '仅表示来源记录，不能据此认定行为或完整覆盖。'} for c in approved[:5]]
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
    if not basic and policy.get('person_ref'):
        missing.append('尚未取得当前人员的档案信息；不影响查看其他已取得资料。')
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
    allowed = set(snapshot.get('native_tool_policy', {}).get('allowed_tools', []))
    present = {r['module'] for r in records}
    confirmed = context.get('confirmed') or {}
    labels = {'person_identity': '人员对象', 'start': '开始时间', 'end': '结束时间', 'radius_m': '半径', 'lon': '经度', 'lat': '纬度'}

    direction = context.get('direction') or policy.get('direction') or 'unknown'
    ranking = None
    case_view = None
    scoring = None
    # Server-side scoring_requested is authoritative; model flag is only supplementary.
    want_score = bool(context.get('scoring_requested'))
    if direction == 'case_to_person' and want_score:
        captures = [r for r in records if r.get('module') == 'captures']
        if context.get('candidate_set'):
            groups = theft_scoring.group_by_person(records, snapshot)
            authorized = {item['person_ref']: groups.get(item['person_ref'], []) for item in context['candidate_set']}
            ranking = theft_scoring.rank(authorized, include_d5=False)
        elif captures:
            ranking = theft_scoring.stage1_rank(captures)
        if ranking and ranking.get('items'):
            top = ranking['items'][0]
            conclusions = [{
                'text': f"嫌疑人可能性排序（{ranking.get('stage', '')}）首位有效得分率 {top.get('rate')}%，{top.get('band') or ''}。建议人工核验。",
                'source_ids': top.get('source_ids') or [],
                'source_run_id': result['run_id'],
                'claim_id': 'platform-ranking',
                'limitation': ranking.get('disclaimer') or theft_scoring.DISCLAIMER,
            }] + conclusions
        elif ranking and ranking.get('status') == 'empty':
            missing.append('尚无可用的抓拍候选人可供排序。')
    elif want_score and policy.get('person_ref'):
        person_records = [r for r in records if theft_scoring.subject_of(r, snapshot) == policy['person_ref']
                          or ((snapshot.get('native_calls') or {}).get(r.get('call_id'), {}).get('frozen', {}).get('query', {}).get('person_ref') == policy['person_ref'])]
        scoring = theft_scoring.compute(person_records, include_d5=True)
        if scoring.get('status') == 'ready':
            conclusions = [{
                'text': f"有效得分率 {scoring['rate']}%（{scoring['earned']} / {scoring['available_max']}），{scoring['band']}。建议人工复核。",
                'source_ids': sorted({sid for d in scoring['dimensions'] for sid in d.get('source_ids', [])}),
                'source_run_id': result['run_id'],
                'claim_id': 'platform-scoring',
                'limitation': scoring['disclaimer'],
            }] + conclusions
        elif scoring.get('status') == 'insufficient':
            missing.append(scoring['disclaimer'])

    if direction == 'person_to_case':
        tracks = [r for r in records if r.get('module') == 'tracks']
        incidents = [r for r in records if r.get('module') == 'incidents']
        if tracks and incidents:
            case_view = theft_scoring.case_checks(tracks, incidents)

    # Platform flow steps first; model suggestions only fill remaining slots.
    suggestions = platform_suggestions(
        context, records, ranking, case_view,
        allowed_tools=allowed, snapshot=snapshot, chosen=chosen,
    )
    seen = {suggestion_key(x) for x in suggestions}
    for item in chosen.get('suggestions', []) if isinstance(chosen.get('suggestions'), list) else []:
        if len(suggestions) >= 3:
            break
        if not isinstance(item, dict):
            continue
        action, kind = item.get('action'), item.get('kind')
        reason = item.get('reason_source')
        refs = aliases.get(reason, []) if isinstance(reason, str) else []
        if reason and not refs:
            continue
        fields = []
        who = '此人' if policy.get('person_ref') else '候选人'
        if action == 'inspect_sources':
            text, condition = '核对已有来源记录', '无需重新查询'
            reply, purpose = '说明已取得的来源记录', '不重新查询，逐条解读已经取得的资料'
        elif action == 'clarify_scope':
            fields = item.get('fields', [])
            if not isinstance(fields, list) or not fields or any(not isinstance(k, str) or k not in labels or k in confirmed for k in fields):
                continue
            text, condition = '补充' + '、'.join(labels[k] for k in fields), '由你补充后再决定是否查询'
            from . import theft_candidates as _cand
            reply, purpose = _cand.reply_clarify(fields), '查询前需要确定这些条件'
        elif action == 'query' and isinstance(kind, str) and kind in provider.CATALOG and 'peixian_query_' + kind in allowed and kind not in present:
            text, condition = '进一步核对' + provider.CATALOG[kind][0], '需你选择；对象、来源与范围仍需通过调用前核对'
            from . import theft_candidates as _cand
            reply, purpose = _cand.reply_query(kind, who)
        else:
            continue
        candidate = {'text': text, 'reason': purpose,
            'conditions': condition, 'source_ids': refs, 'origin': 'model_selection', 'action': action,
            'kind': kind if action == 'query' else None, 'fields': list(fields), 'reply': reply}
        key = suggestion_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(candidate)

    return {'version': VERSION, 'run_id': result['run_id'], 'person_ref': policy.get('person_ref'),
        'status': 'partial' if missing else 'ready',
        'basic': basic, 'conclusions': conclusions, 'evidence': evidence, 'suggestions': suggestions,
        'next_question': next_question(result['run_id'], suggestions),
        'missing': list(dict.fromkeys(missing)), 'preview_count': min(10, len(evidence)), 'total': len(evidence),
        'selection_status': 'accepted' if chosen else 'fallback',
        'source_runs': sorted({r['source_run_id'] for r in records}),
        'scoring': scoring, 'ranking': ranking, 'case_checks': case_view,
        'direction': direction}


def escape(value):
    text = html.escape(str(value), quote=True).replace('\r', ' ').replace('\n', ' ')
    for char in ('\\', '`', '*', '_', '[', ']', '|', '#'):
        text = text.replace(char, '\\' + char)
    return text


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |'] +
        ['| ' + ' | '.join(escape(v) for v in row) + ' |' for row in rows])


def markdown(view):
    if view.get('version') not in SUPPORTED_POLICY:
        return '当前表格版本暂不受支持，请查看已有来源。'
    sections = ['### 人员基本信息', table(['信息项', '内容', '来源／说明'],
        [(x['label'], x['value'], '、'.join(x['source_ids']) + '；取得时间：' + str(x['obtained_at'] or '未提供')) for x in view['basic']]
        or [('档案信息', '尚未取得', '请查看下方资料缺口')]), '### 基本结论',
        table(['结论', '依据', '适用范围／局限'], [(x['text'], '、'.join(x['source_ids']) or '本轮已确认响应统计', x['limitation']) for x in view['conclusions']]
        or [('暂无可确认结论', '尚无对应事实', '不表示没有发生')]), '### 判断依据']

    def evidence(rows):
        return table(['资料类型', '时间／范围', '记录摘要', '来源'], [(x['label'], x['time'], x['text'], '、'.join(x['source_ids'])) for x in rows])

    sections += [f"当前展示 {view['preview_count']} 条／已取得 {view['total']} 条；不代表上游全部记录。", evidence(view['evidence'][:10])]
    if len(view['evidence']) > 10:
        sections += ['<details><summary>展开其余已取得记录</summary>\n\n' + evidence(view['evidence'][10:]) + '\n\n</details>']
    if view['missing']:
        sections += ['资料缺口：' + '；'.join(escape(x) for x in view['missing'])]

    ranking = view.get('ranking')
    if ranking and ranking.get('items'):
        sections += ['### 关联线索与嫌疑人可能性排序']
        rows = []
        for item in ranking['items']:
            rows.append((
                item.get('rank'),
                (item.get('name') or '') + '／' + (item.get('person_ref') or ''),
                item.get('stage'),
                f"{item.get('rate')}%" if item.get('rate') is not None else '—',
                item.get('available_count'),
                item.get('role'),
                '、'.join(item.get('source_ids') or []) or '无',
                '；'.join(item.get('gaps') or []) or '无',
                item.get('follow_up') or '',
            ))
        sections += [table(['排序', '人员', '阶段', '有效得分率', '可用维度', '关系角色', '支持来源', '矛盾与缺口', '补证任务'], rows)]
        for item in ranking.get('insufficient') or []:
            sections += [f"覆盖不足：{(item.get('name') or '') + '／' + (item.get('person_ref') or '')}；" + '；'.join(item.get('gaps') or [])]
        sections += [ranking.get('disclaimer') or theft_scoring.DISCLAIMER]

    scoring = view.get('scoring')
    if scoring:
        sections += ['### 可疑度评分（辅助参考）']
        rows = []
        for d in scoring.get('dimensions', []):
            score = '—' if d['status'] != 'available' else f"{d['score']} / {d['max']}"
            status = '可用' if d['status'] == 'available' else '不可用'
            rows.append((d['label'], score, status, d.get('evidence') or '', '、'.join(d.get('source_ids') or []) or '无', d.get('limitation') or ''))
        sections += [table(['维度', '得分／满分', '状态', '依据', '来源', '局限'], rows)]
        if scoring.get('status') == 'ready':
            sections += [f"有效得分率 {scoring['rate']}%（{scoring['earned']} / {scoring['available_max']}），{scoring['band']}。"]
        sections += [scoring.get('disclaimer') or theft_scoring.DISCLAIMER]

    case_view = view.get('case_checks')
    if case_view and case_view.get('items'):
        sections += ['### 候选案件逐案核验']
        rows = []
        for item in case_view['items']:
            rows.append((
                item.get('cjbh'),
                item.get('cjsj'),
                '—' if item.get('distance_m') is None else f"{item['distance_m']} 米",
                '—' if item.get('time_delta_hours') is None else f"{item['time_delta_hours']} 小时",
                item.get('relation'),
                item.get('status'),
                item.get('follow_up'),
            ))
        sections += [table(['警情编号', '处警时间', '最近直线距离', '时间差', '关系', '核验状态', '补证任务'], rows)]
        sections += [case_view.get('disclaimer') or '']

    output = '\n\n'.join(sections)
    sources = []
    for index, item in enumerate(view['evidence'], 1):
        rid = item['source_ids'][0]
        anchor = 'source-' + re.sub('[^a-zA-Z0-9-]', '', view.get('run_id', 'result')) + '-' + str(index)
        output = output.replace(escape(rid), f'[来源{index}](#{anchor})')
        sources.append(f'<details id="{anchor}"><summary>来源{index} · ' + escape(item['label']) + '</summary>\n\n' +
            table(['来源信息', '值'], [('记录编号', rid), ('执行编号', item['source_run_id']), ('快照', item['snapshot_id'])]) + '\n\n</details>')
    if sources:
        output = output + '\n\n<details><summary>查看来源编号与版本</summary>\n\n' + '\n\n'.join(sources) + '\n\n</details>'
    return output
