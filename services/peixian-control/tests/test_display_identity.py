from control import display_identity as d

REF = 'person-' + 'b' * 32
OTHER = 'person-' + 'c' * 32
ID = '320322198803159911'


def snapshot():
    return {'native_calls': {'c1': {'frozen': {'identities': {REF: ID}}}},
            'provider_state': {'modules': {'c2': {'status': 'completed',
                'response': {'records': [{'source_ref': 's:1', 'fields': {'target_id_card': '32032219930303998x',
                    'records': [{'idCard': '32032219930303998x', 'note': '关联 32032219930303998x'}]}}]},
                'public_response': {'records': [{'source_ref': 's:1', 'fields': {'target_id_card': OTHER,
                    'records': [{'idCard': OTHER, 'note': '关联 ' + OTHER}]}}]}}}}}


def test_collect_frozen_and_raw_public_pairs():
    m = d.collect(snapshot())
    assert m[REF] == ID and m[OTHER] == '32032219930303998X'


def test_reveal_known_keeps_unknown():
    m = {REF: ID}
    text = d.reveal(f'孙强（{REF}）与 {OTHER}', m)
    assert ID in text and OTHER in text and REF not in text
    assert d.reveal(None, m) is None and d.reveal('x', {}) == 'x'


def test_mapping_merges_history():
    snap = snapshot()
    snap['table_answer_policy'] = {'display_identities': {'person-' + 'd' * 32: '320322199001011234'}}
    assert len(d.mapping(snap)) == 3


def test_rendered_table_shows_identity(monkeypatch):
    try:
        from tests.test_table_answer import fixture
    except ImportError:
        from test_table_answer import fixture
    from control import table_answer as t
    result, snap = fixture()
    ref = 'person-' + 'e' * 32
    result['records'][0]['fields']['person']['sfz'] = ref
    snap['table_answer_policy']['person_ref'] = ref
    snap['native_calls']['call']['frozen']['query']['person_ref'] = ref
    snap['native_calls']['call']['frozen']['identities'] = {ref: ID}
    view = t.build(result, snap)
    text = d.reveal(t.markdown(view), d.mapping(snap))
    assert ID in text and ref not in text
    assert view['basic'][1]['value'] == ref



def test_live_source_section_shows_identity(monkeypatch):
    from control import answer_delivery, native_tool_result, reply_presentation
    from shared.theft_provider_v2 import VERSION
    snap = snapshot()
    snap['native_calls']['c1'].update(status='completed', public_response={
        'version': VERSION, 'kind': 'profile', 'response_snapshot_id': 'snap-1', 'returned_count': 1, 'records': [{}]})
    snap['native_calls']['c1']['frozen']['kind'] = 'profile'
    monkeypatch.setattr(native_tool_result, 'project', lambda row, s: {'records': [{}]})
    monkeypatch.setattr(reply_presentation, 'build', lambda result: {'clues': [
        {'summary': f'孙强（{REF}）；来源预警类型 2 个', 'source_ids': ['r1'], 'claim_ids': ['c1']}]})
    answer_delivery.freeze(snap, 'run-1')
    segment = answer_delivery.record(snap, {'id': 'run-1'}, 'c1')
    assert ID in segment['text'] and REF not in segment['text']
