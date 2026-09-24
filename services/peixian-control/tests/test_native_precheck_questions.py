"""Tests for native precheck → question conversion."""
import copy
import pytest
from fastapi import HTTPException
from control import native_precheck_questions as q
from control.native_tool_scope import arguments


def base_context(**extra):
    ctx = {
        'version': 'native-tool-context-v1',
        'task_id': 'task',
        'scope_version': 1,
        'confirmed': {},
        'source_refs': [],
        'current_text': '查询抓拍',
        'constraints_text': '查询抓拍',
        'user_conditions': {},
        'scoring_requested': False,
        'direction': 'case_to_person',
        'candidate_set': [],
    }
    ctx.update(extra)
    return ctx


def test_clarifiable_codes():
    assert q.is_clarifiable('capture_scope_unconfirmed')
    assert q.is_clarifiable('source_selection_required')
    assert q.is_clarifiable('scope_missing')
    assert not q.is_clarifiable('coordinate_contract_unconfirmed')
    assert not q.is_clarifiable('native_no_progress')


def test_build_source_selection_without_sources():
    class FakeStore:
        def rows(self, *a, **k):
            return []
    spec = q.build('captures', 'source_selection_required', {}, base_context(), FakeStore(), 'u', 's')
    assert spec and spec['fields'] == ['source']
    pub = q.public(spec)
    assert pub['questions'][0]['header'] == '来源记录'
    assert pub['questions'][0]['custom'] is True
    assert 'source_ref' not in str(pub)


def test_build_capture_scope_with_anchor_presets():
    class FakeStore:
        def rows(self, *a, **k):
            return []
    ctx = base_context(source_refs=[{
        'run_id': 'r', 'result_digest': 'd', 'record_id': 'r:c:snap:1', 'snapshot_id': 'snap',
    }])
    # Without listable sources, presets fall back to free text only.
    spec = q.build('captures', 'capture_scope_unconfirmed', {}, ctx, FakeStore(), 'u', 's')
    assert 'start' in spec['fields'] and 'end' in spec['fields'] and 'radius_m' in spec['fields']
    assert any(x['field'] == 'time_window' for x in spec['questions'])
    assert any(x['field'] == 'radius_m' for x in spec['questions'])
    # Inject presets manually via capture_time_presets
    options, values = q.capture_time_presets('2025-07-06 23:00:00')
    assert len(options) == 3
    assert '处警前后各2小时' in options[1]['label']
    assert values[options[1]['label']]['start'].endswith('21:00:00')
    assert values[options[1]['label']]['end'].endswith('01:00:00')


def test_apply_reply_option_and_free_text():
    options, values = q.capture_time_presets('2025-07-06 23:00:00')
    radius_opts, radius_vals = q._label_options(q.RADIUS_OPTIONS)
    values.update(radius_vals)
    spec = {
        'token': 't1', 'kind': 'captures', 'code': 'capture_scope_unconfirmed', 'status': 'pending',
        'fields': ['start', 'end', 'radius_m'],
        'questions': [
            {'field': 'time_window', 'header': '抓拍时间', 'question': '请确认', 'options': options, 'custom': True},
            {'field': 'radius_m', 'header': '查询范围', 'question': '半径', 'options': radius_opts, 'custom': True},
        ],
        'values': values,
    }
    ctx = base_context(source_refs=[{'run_id': 'r', 'result_digest': 'd', 'record_id': 'r:1', 'snapshot_id': 's'}])
    next_ctx, text, cancel = q.apply_reply(spec, [[options[1]['label']], ['半径 500 米']], ctx)
    assert cancel is False
    assert next_ctx['confirmed']['radius_m'] == '500' or next_ctx['confirmed']['radius_m'] == 500 or str(next_ctx['confirmed']['radius_m']) == '500'
    assert 'start' in next_ctx['user_conditions'] and 'end' in next_ctx['user_conditions']
    assert next_ctx['scope_version'] == 2
    assert '2025-07-06' in text

    # Free-text time window
    next_ctx2, _, _ = q.apply_reply(spec, [
        ['开始时间 2025-07-06 20:00:00，结束时间 2025-07-07 04:00:00'],
        ['500 米'],
    ], ctx)
    assert next_ctx2['confirmed']['start'] == '2025-07-06 20:00:00'
    assert next_ctx2['confirmed']['end'] == '2025-07-07 04:00:00'


def test_apply_reply_rejects_bad_format():
    spec = {
        'token': 't2', 'kind': 'captures', 'code': 'capture_scope_unconfirmed', 'status': 'pending',
        'fields': ['start', 'end', 'radius_m'],
        'questions': [
            {'field': 'time_window', 'header': '抓拍时间', 'question': '请确认', 'options': [], 'custom': True},
            {'field': 'radius_m', 'header': '查询范围', 'question': '半径', 'options': [], 'custom': True},
        ],
        'values': {},
    }
    with pytest.raises(HTTPException) as exc:
        q.apply_reply(spec, [['明天'], ['500']], base_context())
    assert exc.value.detail['code'] == 'clarification_invalid'


def test_apply_reply_rejects_extra_field_via_slots_outside_asked():
    # person answer when only radius asked
    spec = {
        'token': 't3', 'kind': 'incidents', 'code': 'scope_missing', 'status': 'pending',
        'fields': ['radius_m'],
        'questions': [
            {'field': 'radius_m', 'header': '查询范围', 'question': '半径', 'options': [], 'custom': True},
        ],
        'values': {},
    }
    # Typing an ID into radius free text still resolves as radius digits if present;
    # ensure a non-radius-only identity answer on person field is rejected separately.
    with pytest.raises(HTTPException):
        q.apply_reply(spec, [['不是半径']], base_context())


def test_match_public_detects_rewrite():
    spec = q.build('captures', 'page_unconfirmed', {}, base_context(), type('S', (), {'rows': lambda *a, **k: []})(), 'u', 's')
    pub = q.public(spec)
    assert q.match_public(spec, pub['questions'])
    rewritten = copy.deepcopy(pub['questions'])
    rewritten[0]['question'] = '改写后的问题'
    assert not q.match_public(spec, rewritten)


def test_unsupported_scope_option():
    spec = q.build('incidents', 'unsupported_scope', {}, base_context(), type('S', (), {'rows': lambda *a, **k: []})(), 'u', 's')
    next_ctx, text, cancel = q.apply_reply(spec, [['同意使用上游默认覆盖范围']], base_context(constraints_text='近期盗窃'))
    assert cancel is False
    assert next_ctx['constraints_text'] == ''
    assert '同意' in text
    _, _, cancel2 = q.apply_reply(spec, [['取消本次查询']], base_context())
    assert cancel2 is True


def test_record_pending_and_kind_cap():
    snap = {}
    for _ in range(3):
        spec = q.build('captures', 'source_selection_required', {}, base_context(), type('S', (), {'rows': lambda *a, **k: []})(), 'u', 's')
        q.record_pending(snap, spec, max_keep=3)
    pending = [s for s in snap['native_pending_questions'].values() if s['status'] == 'pending']
    assert len(pending) <= 3
    # mark two answered
    for i, (t, s) in enumerate(list(snap['native_pending_questions'].items())[:2]):
        s['status'] = 'answered'
    assert q.kind_question_count(snap, 'captures') >= 2


def test_arguments_still_blocks_capture_without_user_conditions():
    # Direct precheck still raises; gate converts it.
    c = base_context(confirmed={'start': '2025-07-06 20:00:00', 'end': '2025-07-07 04:00:00', 'radius_m': 500},
                     source_refs=[{'record_id': 'x'}], user_conditions={})
    with pytest.raises(HTTPException) as exc:
        arguments('captures', dict(c['confirmed']), c)
    assert exc.value.detail['code'] == 'capture_scope_unconfirmed'
