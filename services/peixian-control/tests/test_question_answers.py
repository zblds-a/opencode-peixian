import uuid

import pytest
from fastapi import HTTPException

from control import business_runs, question_answers as qa
from test_provider_flow import provider, enabled, v6, task_env, multi, accept  # noqa: F401


QUESTION = {'id': 'next-r', 'multiple': True, 'custom': True, 'options': [
    {'id': 'option-1', 'label': '核查夜间出现', 'send': True},
    {'id': 'option-2', 'label': '补充查询范围', 'send': False}]}


def code(exc):
    return exc.value.detail['code'] if isinstance(exc.value.detail, dict) else exc.value.detail


def test_clarification_text_matches_frontend_wording():
    text, label = qa.clarification_text(['start', 'end', 'radius_m', 'page', 'supported_scope'], {
        'start': '2026-09-01 00:00:00', 'end': '2026-09-02 00:00:00', 'radius_m': '500', 'page': '2', 'supported_scope': 'option-1'})
    assert text == '开始时间：2026-09-01 00:00:00；结束时间：2026-09-02 00:00:00；半径：500 米；第2页；同意使用上游默认覆盖范围'
    assert label == text


@pytest.mark.parametrize('missing,values', [
    (['start'], {'start': '2026/09/01'}),
    (['person_identity'], {'person_identity': '123'}),
    (['lon'], {'lon': '东经117'}),
    (['radius_m'], {'radius_m': '0'}),
    (['start'], {}),
    (['start'], {'start': '2026-09-01 00:00:00', 'end': '2026-09-02 00:00:00'}),
    (['supported_scope'], {'supported_scope': '不同意'}),
])
def test_clarification_text_rejects_invalid(missing, values):
    with pytest.raises(HTTPException) as exc:
        qa.clarification_text(missing, values)
    assert exc.value.status_code == 422


def test_next_question_text():
    assert qa.next_question_text(QUESTION, ['option-1'], '  另查同行人 ') == ('核查夜间出现；另查同行人', '核查夜间出现；另查同行人')
    assert qa.next_question_text(QUESTION, [], '只写自定义')[0] == '只写自定义'
    for option_ids, custom in ((['option-2'], None), (['option-9'], None), ([], '  '), (['option-1', 'option-1'], None)):
        with pytest.raises(HTTPException) as exc:
            qa.next_question_text(QUESTION, option_ids, custom)
        assert exc.value.status_code == 422
    single = {**QUESTION, 'multiple': False, 'options': QUESTION['options'][:1] + [{'id': 'option-2', 'label': 'B', 'send': True}]}
    with pytest.raises(HTTPException):
        qa.next_question_text(single, ['option-1', 'option-2'], None)


@pytest.fixture
def parent(provider, monkeypatch):
    s = provider[0]; uid = provider[4]['uid']
    _, _, row, _ = accept(provider)
    business_runs.set_state(s, row['id'], 'completed', 'completed')
    monkeypatch.setattr(qa, '_question', lambda store, u, sid, r, kind: ('next-' + r['id'], {**QUESTION, 'id': 'next-' + r['id']}))
    return s, uid, row


def body(rid, **extra):
    return {'kind': 'next_question', 'question_id': 'next-' + rid, 'option_ids': ['option-1'], 'client_request_id': str(uuid.uuid4()), **extra}


def test_reserve_settle_replay_and_single_answer(parent):
    s, uid, row = parent
    request = body(row['id'])
    record, receipt = qa.prepare(s, uid, 'ses_multi', row['id'], request)
    assert receipt is None and record['text'] == '核查夜间出现' and record['status'] == 'pending'
    again, receipt = qa.prepare(s, uid, 'ses_multi', row['id'], request)
    assert receipt is None and again['client_request_id'] == request['client_request_id']
    with pytest.raises(HTTPException) as exc:
        qa.prepare(s, uid, 'ses_multi', row['id'], body(row['id']))
    assert exc.value.status_code == 409 and code(exc) == 'question_already_answered'
    with pytest.raises(HTTPException) as exc:
        qa.prepare(s, uid, 'ses_multi', row['id'], {**request, 'option_ids': [], 'custom_value': '别的'})
    assert code(exc) == 'request_conflict'
    qa.settle(s, row['id'], record['question_id'], request['client_request_id'], {'accepted': True, 'run_id': 'run_child', 'message_id': 'msg_child'})
    replayed, receipt = qa.prepare(s, uid, 'ses_multi', row['id'], request)
    assert receipt == {'accepted': True, 'run_id': 'run_child', 'message_id': 'msg_child'}
    response = qa.response(replayed, receipt)
    assert response['message_kind'] == 'question_answer' and response['parent_run_id'] == row['id']
    projected = qa.project(s, uid, 'ses_multi', [{'info': {'id': 'msg_child', 'role': 'user'}}, {'info': {'id': 'x', 'role': 'user'}}])
    assert projected[0]['info']['message_kind'] == 'question_answer'
    assert projected[0]['info']['answer_label'] == '核查夜间出现'
    assert 'message_kind' not in projected[1]['info']


def test_failed_dispatch_releases_reservation(parent):
    s, uid, row = parent
    request = body(row['id'])
    record, _ = qa.prepare(s, uid, 'ses_multi', row['id'], request)
    qa.settle(s, row['id'], record['question_id'], request['client_request_id'], None)
    other = body(row['id'])
    record, receipt = qa.prepare(s, uid, 'ses_multi', row['id'], other)
    assert receipt is None and record['client_request_id'] == other['client_request_id']


def test_newer_run_expires_question(parent, provider):
    s, uid, row = parent
    accept(provider)
    with pytest.raises(HTTPException) as exc:
        qa.prepare(s, uid, 'ses_multi', row['id'], body(row['id']))
    assert code(exc) == 'question_expired'


def test_stop_uses_fixed_text(parent):
    s, uid, row = parent
    record, _ = qa.prepare(s, uid, 'ses_multi', row['id'], {'kind': 'stop', 'client_request_id': str(uuid.uuid4())})
    assert record['text'] == qa.STOP_TEXT and record['question_id'] == 'next-' + row['id']


def test_invalid_kind_and_request_id(parent):
    s, uid, row = parent
    for bad in ({'kind': 'other', 'client_request_id': str(uuid.uuid4())}, {'kind': 'stop', 'client_request_id': 'x'}):
        with pytest.raises(HTTPException) as exc:
            qa.prepare(s, uid, 'ses_multi', row['id'], bad)
        assert exc.value.status_code == 422
