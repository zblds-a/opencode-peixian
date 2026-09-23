"""Authorized candidate enrichment for case-to-person ranking. No provider I/O here."""
from __future__ import annotations

import copy
import hmac

from .backend_contract import error
from . import theft_scoring
from shared import theft_provider_v2 as adapter

VERSION = 'theft-candidates-v1'
MAX_N = 5
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
    """Freeze top-N candidates from a stage-1 ranking. N is 1..5."""
    if type(n) is not int or not 1 <= n <= MAX_N:
        error('candidate_limit_invalid', '核验人数须为1至5名。', 422)
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


def resolve(store, uid, sid, context, person_ref):
    """Resolve a candidate person_ref to raw identity via source integrity check."""
    entry = find(context, person_ref)
    if not entry:
        error('identity_parameter_invalid', '该引用不在本轮已授权的核验候选人中。', 409)
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


def candidate_request_n(text):
    """Parse 核验前N名 / 对前N人评分; return int 1..5 or None."""
    import re
    if not isinstance(text, str):
        return None
    match = re.search(
        r'(?:核验|评分|查|核对|筛)\s*前\s*([1-5])\s*名|(?:对|给)\s*前\s*([1-5])\s*(?:人|名)|前\s*([1-5])\s*名(?:核验|评分|排序)',
        text,
    )
    if not match:
        return None
    for group in match.groups():
        if group:
            return int(group)
    return None
