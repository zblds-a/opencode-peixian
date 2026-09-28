"""Structured replies to clarification and next-question cards.

The reply text is composed here, never by the browser. Records live in the
parent run snapshot (the parent is terminal, so no worker rewrites it) and are
reserved inside one transaction so a card can be answered at most once.
"""
import copy
import re
import uuid
from .backend_contract import error
from . import business_runs as runs

VERSION = 'question-answer-v1'
KINDS = ('clarification', 'next_question', 'stop')
STOP_TEXT = '不再追问，请基于已取得资料直接作答。'
SCOPE_OPTION = {'id': 'option-1', 'label': '同意使用上游默认覆盖范围'}
FIELD_NAMES = {'lon': '经度', 'lat': '纬度', 'radius_m': '半径', 'start': '开始时间', 'end': '结束时间',
               'person_identity': '人员', 'source': '来源记录编号'}
MAX_CUSTOM = 500


def _invalid(message, field):
    error('invalid_answer', message, 422, {field: message})


def clarification_text(missing, values):
    if not isinstance(values, dict):_invalid('请回答全部问题。', 'values')
    parts = []
    for field in missing:
        value = values.get(field)
        value = value.strip() if isinstance(value, str) else ''
        if not value:_invalid('请回答全部问题。', field)
        if field == 'supported_scope':
            if value not in (SCOPE_OPTION['id'], SCOPE_OPTION['label']):_invalid('请明确是否同意使用上游默认覆盖范围。', field)
            parts.append(SCOPE_OPTION['label']);continue
        if field == 'person_identity' and not re.fullmatch(r'\d{17}[\dXx]', value):_invalid('请填写一名人员的完整身份号码。', field)
        if field in ('start', 'end') and not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):_invalid('时间请填写为 YYYY-MM-DD HH:mm:ss。', field)
        if field in ('lon', 'lat') and not re.fullmatch(r'-?\d+(?:\.\d+)?', value):_invalid('经纬度请填写数字。', field)
        if field in ('radius_m', 'page', 'page_size') and not re.fullmatch(r'[1-9]\d*', value):_invalid('半径、页码和每页数量请填写正整数。', field)
        if len(value) > 200:_invalid('填写内容过长。', field)
        if field == 'page':parts.append(f'第{value}页')
        elif field == 'page_size':parts.append(f'每页{value}条')
        else:parts.append(FIELD_NAMES.get(field, '补充信息') + '：' + value + (' 米' if field == 'radius_m' else ''))
    extra = set(values) - set(missing)
    if extra:_invalid('包含本问题之外的字段。', sorted(extra)[0])
    return '；'.join(parts), '；'.join(parts)


def next_question_text(question, option_ids, custom):
    if option_ids is None:option_ids = []
    if not isinstance(option_ids, list) or any(not isinstance(x, str) for x in option_ids) or len(set(option_ids)) != len(option_ids):
        _invalid('选项无效。', 'option_ids')
    options = {item.get('id'): item for item in question.get('options') or []}
    chosen = []
    for oid in option_ids:
        if oid not in options:_invalid('选项已失效，请刷新后重试。', 'option_ids')
        if options[oid].get('send') is False:_invalid('该选项需要先补充内容，请编辑后再发送。', 'option_ids')
        chosen.append(options[oid]['label'].strip())
    if len(chosen) > 1 and question.get('multiple') is False:_invalid('该问题只能选择一项。', 'option_ids')
    if custom is not None:
        if not isinstance(custom, str) or len(custom) > MAX_CUSTOM:_invalid(f'补充内容不超过{MAX_CUSTOM}个字符。', 'custom_value')
        if question.get('custom') is False and custom.strip():_invalid('该问题不接受自定义回答。', 'custom_value')
        if custom.strip():chosen.append(custom.strip())
    chosen = [x for x in chosen if x]
    if not chosen:_invalid('请选择下一步。', 'option_ids')
    text = '；'.join(chosen)
    return text, text


def _latest(db, uid, sid):
    row = db.execute('SELECT id FROM business_runs WHERE uid=? AND session_id=? ORDER BY created DESC,rowid DESC LIMIT 1', (uid, sid)).fetchone()
    return row['id'] if row else None


def _question(store, uid, sid, row, kind):
    if kind == 'clarification':
        from .theft_planner import public_question
        question = public_question(store, row)
        if not question:error('question_expired', '该问题已失效，请刷新后查看最新状态。', 409)
        return question['id'], question
    if row['status'] not in runs.TERMINAL:error('run_active', '本次分析尚未结束。', 409)
    from .trusted_results import read
    try:
        view = read(store, uid, sid, row['id']).get('answer_view') or {}
    except Exception:
        view = {}
    question = view.get('next_question') if isinstance(view.get('next_question'), dict) else None
    if kind == 'next_question' and not question:error('question_expired', '该问题已失效，请刷新后查看最新状态。', 409)
    return (question or {}).get('id') or 'next-' + row['id'], question


def prepare(store, uid, sid, rid, body):
    """Validate and reserve. Returns (record, replay_receipt)."""
    if not isinstance(body, dict):error('invalid_answer', '请求格式无效。', 422)
    kind = body.get('kind')
    if kind not in KINDS:_invalid('kind 只能是 clarification、next_question 或 stop。', 'kind')
    key = body.get('client_request_id')
    try:uuid.UUID(key)
    except (ValueError, TypeError, AttributeError):_invalid('client_request_id 必须为UUID', 'client_request_id')
    row = runs.owned(store, uid, sid, rid)
    for record in (store.decrypt(row['request_ciphertext']).get('question_answers') or {}).values():
        if record['client_request_id'] == key and record.get('receipt'):return copy.deepcopy(record), copy.deepcopy(record['receipt'])
    qid, question = _question(store, uid, sid, row, kind)
    if kind != 'stop' and body.get('question_id') != qid:error('question_expired', '该问题已失效，请刷新后查看最新状态。', 409)
    if kind == 'clarification':
        text, label = clarification_text(question['missing'], body.get('values'))
    elif kind == 'next_question':
        text, label = next_question_text(question, body.get('option_ids'), body.get('custom_value'))
    else:
        text, label = STOP_TEXT, '不再追问'
    with store.tx() as db:
        current = dict(db.execute('SELECT * FROM business_runs WHERE id=?', (rid,)).fetchone())
        snapshot = store.decrypt(current['request_ciphertext'])
        answers = snapshot.setdefault('question_answers', {})
        record = answers.get(qid)
        if record:
            if record['client_request_id'] != key:error('question_already_answered', '该问题已经回答过。', 409)
            if record['text'] != text:error('request_conflict', '同一请求标识对应不同内容', 409)
            if record.get('receipt'):return copy.deepcopy(record), copy.deepcopy(record['receipt'])
            return copy.deepcopy(record), None
        if _latest(db, uid, sid) != rid:error('question_expired', '会话已有更新的分析，该问题已失效。', 409)
        record = {'version': VERSION, 'question_id': qid, 'kind': kind, 'client_request_id': key,
                  'text': text, 'answer_label': label, 'parent_run_id': rid, 'status': 'pending'}
        answers[qid] = record
        db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?', (store.encrypt(snapshot), rid))
        return copy.deepcopy(record), None


def settle(store, rid, qid, key, receipt):
    with store.tx() as db:
        current = db.execute('SELECT uid,session_id,request_ciphertext FROM business_runs WHERE id=?', (rid,)).fetchone()
        if receipt is None:
            admitted = db.execute('SELECT * FROM business_runs WHERE uid=? AND session_id=? AND request_key=?', (current['uid'], current['session_id'], key)).fetchone()
            if admitted:receipt = runs.receipt(admitted)
        snapshot = store.decrypt(current['request_ciphertext'])
        record = snapshot.get('question_answers', {}).get(qid)
        if not record or record['client_request_id'] != key:return
        if receipt is None:
            if not record.get('receipt'):snapshot['question_answers'].pop(qid)
        else:
            record['receipt'] = {k: receipt[k] for k in ('accepted', 'run_id', 'message_id') if k in receipt}
            record['status'] = 'dispatched'
        db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?', (store.encrypt(snapshot), rid))


def response(record, receipt):
    return {**receipt, 'question_id': record['question_id'], 'kind': record['kind'],
            'parent_run_id': record['parent_run_id'], 'answer_label': record['answer_label'], 'message_kind': 'question_answer'}


def projections(store, uid, sid):
    """user message id -> question_answer projection, for answers recorded on parent runs."""
    found = {}
    for row in store.rows('SELECT id,message_id,request_ciphertext FROM business_runs WHERE uid=? AND session_id=?', (uid, sid)):
        for record in (store.decrypt(row['request_ciphertext']).get('question_answers') or {}).values():
            receipt = record.get('receipt') or {}
            mid = receipt.get('message_id')
            if not mid and receipt.get('run_id'):
                child = store.one('SELECT message_id FROM business_runs WHERE id=? AND uid=?', (receipt['run_id'], uid))
                mid = child and child['message_id']
            if mid:found[mid] = {'message_kind': 'question_answer', 'question_id': record['question_id'], 'question_kind': record['kind'],
                                 'parent_run_id': record['parent_run_id'], 'answer_label': record['answer_label']}
    return found


def project(store, uid, sid, values):
    found = projections(store, uid, sid)
    if not found:return values
    for message in values:
        info = message.get('info') or {}
        meta = found.get(info.get('id'))
        if meta and info.get('role') == 'user':info.update(meta)
    return values
