"""Authorized candidate enrichment for case-to-person ranking. No provider I/O here."""
from __future__ import annotations

import copy
import hmac

from .backend_contract import error
from . import theft_scoring
from shared import theft_provider_v2 as adapter

VERSION = 'theft-candidates-v1'
MAX_N = 20
SCORE_KINDS = frozenset({'night', 'community', 'warning_detail', 'warnings', 'warning_logs', 'profile', 'tracks'})


def task_capture_records(store, uid, sid, task_id):
    """Return integrity-checked capture records from the same native task."""
    from .trusted_results import checked_result, digest as result_digest
    rows = store.rows(
        "SELECT b.request_ciphertext, r.* FROM business_runs b "
        "JOIN run_results r ON r.run_id=b.id WHERE b.uid=? AND b.session_id=? "
        "ORDER BY b.rowid DESC LIMIT 50",
        (uid, sid),
    )
    records = []
    for row in rows:
        snapshot = store.decrypt(row['request_ciphertext'])
        context = snapshot.get('native_tool_context') or {}
        if context.get('task_id') != task_id:
            continue
        result = checked_result(store, row)
        for record in result.get('records') or []:
            call = (snapshot.get('native_calls') or {}).get(record.get('call_id'), {})
            plan = call.get('frozen') or {}
            if call.get('status') != 'completed' or plan.get('kind') != 'captures':
                continue
            item = copy.deepcopy(record)
            item['result_digest'] = result_digest(result)
            item['source_run_id'] = result.get('run_id') or row['run_id'] if 'run_id' in row.keys() else result.get('run_id')
            # Prefer explicit run id from result
            item['source_run_id'] = result.get('run_id')
            records.append(item)
    return records


def stage1_from_task(store, uid, sid, task_id):
    captures = task_capture_records(store, uid, sid, task_id)
    return theft_scoring.stage1_rank(captures)


def authorize(ranked_items, n):
    """Freeze top-N candidates from a stage-1 ranking. N is 1..MAX_N (soft ceiling)."""
    if type(n) is not int or n < 1:
        error('candidate_limit_invalid', '核验人数须为正整数。', 422)
    n = min(n, MAX_N)
    items = list(ranked_items or [])
    selected = items[:n]
    if not selected:
        error('candidate_set_empty', '尚无可用的抓拍候选人；请先取得周边抓拍结果。', 409)
    out = []
    for index, item in enumerate(selected, 1):
        if not item.get('person_ref') or not item.get('record_id') or not item.get('run_id') or not item.get('snapshot_id'):
            error('candidate_source_incomplete', '候选人缺少可核验的来源引用。', 409)
        out.append({
            'version': VERSION,
            'rank': index,
            'person_ref': item['person_ref'],
            'name': item.get('name'),
            'run_id': item['run_id'],
            'record_id': item['record_id'],
            'snapshot_id': item['snapshot_id'],
            'result_digest': item.get('result_digest'),
            'source_ids': list(item.get('source_ids') or [item['record_id']]),
            'stage1_rate': item.get('rate'),
        })
    return out


def find(context, person_ref):
    if not isinstance(person_ref, str) or not person_ref.startswith('person-'):
        return None
    for item in context.get('candidate_set') or []:
        if isinstance(item, dict) and item.get('person_ref') == person_ref:
            return item
    return None


def find_capture_person(store, uid, sid, context, person_ref):
    """Locate a person_ref in completed capture records of this task (no authorize required)."""
    if not isinstance(person_ref, str) or not person_ref.startswith('person-'):
        return None
    task_id = (context or {}).get('task_id')
    if not task_id:
        return None
    # Read raw provider rows from the run snapshots: public results carry only
    # scoped references, and the current run has no run_results row yet.
    key = store.worker_key.encode()
    scope = uid + '/' + sid
    rows = store.rows(
        "SELECT id, request_ciphertext FROM business_runs WHERE uid=? AND session_id=? ORDER BY rowid DESC LIMIT 50",
        (uid, sid),
    )
    for row in rows:
        snapshot = store.decrypt(row['request_ciphertext'])
        if (snapshot.get('native_tool_context') or {}).get('task_id') != task_id:
            continue
        modules = (snapshot.get('provider_state') or {}).get('modules') or {}
        for call_id, call in (snapshot.get('native_calls') or {}).items():
            if call.get('status') != 'completed' or (call.get('frozen') or {}).get('kind') != 'captures':
                continue
            entry = modules.get(call_id) or {}
            if entry.get('status') != 'completed':
                continue
            raw = entry.get('response') or {}
            for item in raw.get('records') or []:
                fields = item.get('fields') or {}
                names = [n for n in ('target_id_card', 'targetIdCard', 'idCard') if n in fields]
                if len(names) != 1:
                    continue
                try:
                    identity = adapter.person_id(fields[names[0]])
                except adapter.ContractError:
                    continue
                if not hmac.compare_digest(adapter.person_ref(identity, key, scope), person_ref):
                    continue
                record_id = row['id'] + ':' + call_id + ':' + str(item.get('source_ref', ''))
                return {
                    'version': VERSION,
                    'rank': None,
                    'person_ref': person_ref,
                    'name': fields.get('target_name') or fields.get('name'),
                    'run_id': row['id'],
                    'record_id': record_id,
                    'snapshot_id': raw.get('response_snapshot_id'),
                    'result_digest': None,
                    'source_ids': [record_id],
                    'identity': identity,
                }
    return None


def resolve_capture_person(store, uid, sid, context, person_ref):
    """Resolve any capture-sourced person_ref without requiring candidate_set authorization."""
    entry = find(context, person_ref)
    if entry:
        return resolve(store, uid, sid, context, person_ref)
    found = find_capture_person(store, uid, sid, context, person_ref)
    if not found or not found.get('identity'):
        error('identity_parameter_invalid', '该引用不在本任务已取得的抓拍结果中。', 409)
    return found['identity'], person_ref


def resolve(store, uid, sid, context, person_ref):
    """Resolve a candidate person_ref to raw identity via source integrity check."""
    entry = find(context, person_ref)
    if not entry:
        # Fall back to any capture person from this task (authorization no longer required).
        return resolve_capture_person(store, uid, sid, context, person_ref)
    if not entry.get('result_digest'):
        error('candidate_source_incomplete', '候选人来源摘要缺失，无法核验身份。', 409)
    from .analysis_tasks import source
    reference = {
        'run_id': entry['run_id'],
        'result_digest': entry['result_digest'],
        'record_id': entry['record_id'],
        'snapshot_id': entry['snapshot_id'],
    }
    # Prefer acceptance_real; fall back to synthetic if the run used it.
    record = None
    snapshot = None
    last = None
    for environment in ('acceptance_real', 'synthetic'):
        try:
            record, snapshot = source(store, uid, sid, reference, environment)
            break
        except Exception as exc:  # HTTPException from FastAPI
            last = exc
            continue
    if record is None:
        if last is not None:
            raise last
        error('source_record_unavailable', '候选人来源无法核验。', 409)
    call_id = record.get('call_id')
    plan = (snapshot.get('native_calls') or {}).get(call_id, {}).get('frozen') or snapshot.get('provider_plan') or {}
    if plan.get('kind') != 'captures' and record.get('module') != 'captures':
        error('source_identity_missing', '候选人来源不是抓拍记录。', 409)
    entry_state = (snapshot.get('provider_state') or {}).get('modules') or {}
    raw_entry = entry_state.get(call_id) or entry_state.get('captures') or {}
    raw = raw_entry.get('response') or {}
    expected_prefix = reference['run_id'] + ':' + (call_id + ':' if call_id else '')
    raw_rows = [
        r for r in raw.get('records') or []
        if expected_prefix + r.get('source_ref', '') == reference['record_id']
        or reference['run_id'] + ':' + r.get('source_ref', '') == reference['record_id']
    ]
    if len(raw_rows) != 1:
        # Fall back to projected field only when it still looks like a raw id card
        projected = (record.get('fields') or {}).get('target_id_card')
        try:
            identity = adapter.person_id(projected)
        except adapter.ContractError:
            error('source_identity_missing', '候选人原始身份无法从抓拍来源取得。', 409)
    else:
        fields = raw_rows[0].get('fields') or {}
        names = [n for n in ('target_id_card', 'targetIdCard', 'idCard') if n in fields]
        if len(names) != 1:
            error('source_identity_missing', '此条来源不能唯一确定人员。', 409)
        try:
            identity = adapter.person_id(fields[names[0]])
        except adapter.ContractError:
            error('source_identity_missing', '候选人原始身份格式无效。', 409)
    ref = adapter.person_ref(identity, store.worker_key.encode(), uid + '/' + sid)
    if not hmac.compare_digest(ref, person_ref):
        error('identity_parameter_invalid', '该引用与候选人来源不一致。', 409)
    return identity, ref


# Standard reply phrases the platform shows for quick follow-up. Keep in sync with
# candidate_request_n / SCORING_REQUEST recognition so a pasted reply advances the flow.
ENRICH_KIND_LABELS = {
    'night': '夜间',
    'community': '跨小区',
    'warning_detail': '预警',
    'profile': '档案',
    'tracks': '轨迹',
    'incidents': '周边警情',
}
ENRICH_SCORE_KINDS = ('night', 'community', 'warning_detail', 'profile')

# Bands at or above this threshold count toward recommend_n.
_RECOMMEND_BANDS = frozenset({'存在一定关联', '关联度中等', '关联度较高', '关联度很高'})
_RATE_DROP = 15


def recommend_n(ranking):
    """Pick a default authorize count from stage-1 ranking. Returns 1..MAX_N."""
    items = list((ranking or {}).get('items') or [])
    if not items:
        return 1
    eligible = []
    for item in items:
        if item.get('band') in _RECOMMEND_BANDS or (isinstance(item.get('rate'), (int, float)) and item['rate'] >= 20):
            eligible.append(item)
        else:
            break
    if not eligible:
        eligible = items[:1]
    cut = len(eligible)
    for index in range(1, len(eligible)):
        prev = eligible[index - 1].get('rate')
        cur = eligible[index].get('rate')
        if isinstance(prev, (int, float)) and isinstance(cur, (int, float)) and (prev - cur) >= _RATE_DROP:
            cut = index
            break
    return max(1, min(MAX_N, cut, len(items)))


def task_person_modules(store, uid, sid, task_id):
    """Map person_ref -> completed module kinds for the same native task."""
    rows = store.rows(
        "SELECT b.request_ciphertext FROM business_runs b "
        "WHERE b.uid=? AND b.session_id=? ORDER BY b.rowid DESC LIMIT 50",
        (uid, sid),
    )
    present = {}
    for row in rows:
        snapshot = store.decrypt(row['request_ciphertext'])
        context = snapshot.get('native_tool_context') or {}
        if context.get('task_id') != task_id:
            continue
        for call in (snapshot.get('native_calls') or {}).values():
            if not isinstance(call, dict) or call.get('status') != 'completed':
                continue
            plan = call.get('frozen') or {}
            kind = plan.get('kind')
            ref = (plan.get('query') or {}).get('person_ref')
            if kind and ref:
                present.setdefault(ref, set()).add(kind)
                if kind == 'warnings':
                    present[ref].add('warning_detail')
    return present


def build_enrichment_plan(candidate_set, allowed_tools=None, records=None, snapshot=None, present_by_person=None):
    """Static per-candidate enrichment jobs after authorize. Progress from records when given."""
    allowed = set(allowed_tools) if allowed_tools is not None else None
    groups = theft_scoring.group_by_person(records or [], snapshot) if records is not None else {}
    items = []
    done = 0
    total = 0
    for entry in candidate_set or []:
        if not isinstance(entry, dict) or not entry.get('person_ref'):
            continue
        ref = entry['person_ref']
        kinds = list(ENRICH_SCORE_KINDS)
        if allowed is not None:
            kinds = [k for k in kinds if 'peixian_query_' + k in allowed]
        present = set()
        if present_by_person and ref in present_by_person:
            present |= set(present_by_person[ref])
        if records is not None:
            present |= {r.get('module') for r in groups.get(ref, [])}
        if 'warnings' in present:
            present.add('warning_detail')
        missing = [k for k in kinds if k not in present]
        finished = [k for k in kinds if k not in missing]
        total += len(kinds)
        done += len(finished)
        items.append({
            'rank': entry.get('rank'),
            'person_ref': ref,
            'name': entry.get('name'),
            'kinds': kinds,
            'missing_kinds': missing,
            'done_kinds': finished,
        })
    pending = sum(len(i['missing_kinds']) for i in items)
    return {
        'version': VERSION,
        'items': items,
        'done': done,
        'total': total,
        'pending': pending,
        'complete': pending == 0 and bool(items),
    }



def enrichment_progress_label(plan, rank, kind, index=None):
    """Human label for an enrichment tool step."""
    label = ENRICH_KIND_LABELS.get(kind, kind)
    who = f'第{rank}名' if rank else '候选人'
    if isinstance(plan, dict) and plan.get('total'):
        i = index if isinstance(index, int) else (plan.get('done') or 0) + 1
        return f'补查 {who} {label} ({i}/{plan["total"]})'
    return f'补查 {who} {label}'


def reply_authorize_n(n):
    """Reply text that candidate_request_n will parse as N."""
    if type(n) is not int or n < 1:
        return '核验前1名'
    if n == 1:
        return '核验该候选人'
    return f'核验前{min(n, MAX_N)}名'


def reply_authorize_option(n, recommended=None):
    """Card option label; recommended N is marked."""
    base = reply_authorize_n(n)
    if recommended is not None and n == recommended:
        return base + '（推荐）'
    return base


def reply_enrich(rank, name, kinds):
    labels = [ENRICH_KIND_LABELS[k] for k in kinds if k in ENRICH_KIND_LABELS]
    who = f'第{rank}名'
    if name:
        who = f'{who}（{name}）'
    if not labels:
        return f'对{who}补查资料'
    return f'对{who}补查{"和".join(labels)}记录'


def reply_clarify(fields):
    """Example reply for missing scope fields; shown as 例如, not sent automatically."""
    wanted = set(fields or [])
    parts = []
    if 'person_identity' in wanted:
        parts.append('人员身份证号 3203XXXXXXXXXXXXXX')
    if wanted & {'start', 'end'}:
        parts.append('时间 2026-09-10 20:00 至 2026-09-10 23:00')
    if 'radius_m' in wanted:
        parts.append('半径 500 米')
    if wanted & {'lon', 'lat'}:
        parts.append('位置 经度 117.19、纬度 34.73')
    return '，'.join(parts) or '时间 2026-09-10 20:00 至 2026-09-10 23:00'


QUERY_REPLIES = {
    'night': ('查询{who}夜间活动记录', '看{who}在夜间是否有活动'),
    'community': ('查询{who}跨小区记录', '看{who}是否在多个小区之间活动'),
    'warning_detail': ('查询{who}预警概况', '核对{who}有无预警记录'),
    'warning_logs': ('查询{who}预警明细', '核对{who}的逐条预警'),
    'profile': ('查询{who}档案', '核对{who}的基本信息和最近抓拍'),
    'tracks': ('查询{who}轨迹', '查看{who}在时间窗口内的行动轨迹'),
    'incidents': ('以轨迹点查询周边警情', '用已有轨迹点查周边警情，逐案核验候选案件'),
    'captures': ('查询周边抓拍并初排', '找出案发点附近出现过的关联人员并做初步关注排序'),
}


def reply_query(kind, who='此人'):
    reply, purpose = QUERY_REPLIES.get(kind, ('进一步核对该项资料', '补齐尚未取得的资料'))
    return reply.format(who=who), purpose.format(who=who)


def reply_query_incidents():
    return '以轨迹点查询周边警情'


def reply_query_captures():
    return '查询周边抓拍并初排'


def reply_inspect_cases():
    return '核对处警记录原文'


def candidate_request_n(text):
    """Parse 核验前N名 / 对前N人评分 / 核验该候选人; return int 1..5 or None."""
    import re
    if not isinstance(text, str):
        return None
    cleaned = re.sub(r'[（(]\s*推荐\s*[）)]', '', text)
    if re.search(r'核验该候选人|对该候选人(?:核验|评分)', cleaned):
        return 1
    match = re.search(
        r'(?:核验|评分|查|核对|筛)\s*前\s*([1-5])\s*名|(?:对|给)\s*前\s*([1-5])\s*(?:人|名)|前\s*([1-5])\s*名(?:核验|评分|排序)',
        cleaned,
    )
    if not match:
        return None
    for group in match.groups():
        if group:
            return int(group)
    return None
