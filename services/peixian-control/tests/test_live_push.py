import asyncio
import json
import threading

import pytest

from control import answer_delivery, live_push
from test_store_transactions import store_args, store  # noqa: F401
from test_event_hub import fixture


BODY = ('## 结论\n\n共核对 3 人。\n\n### 人员一\n\n夜间出现 2 次。\n\n'
        '### 人员二\n\n无记录。\n\n### 六维可疑度排序\n\n| 序号 | 人员 |\n|---|---|\n| 1 | 甲 |\n')


def test_split_sections_joins_back_exactly():
    parts = answer_delivery.split_sections(BODY)
    assert ''.join(parts) == BODY
    assert [p.split('\n', 1)[0] for p in parts] == ['## 结论', '### 人员一', '### 人员二', '### 六维可疑度排序']
    assert answer_delivery.split_sections('无标题正文') == ['无标题正文']
    assert answer_delivery.split_sections('### 只有一节\n') == ['### 只有一节\n']


class Recorder:
    def __init__(self):
        self.callbacks = []

    def after_commit(self, callback):
        self.callbacks.append(callback)


def test_append_final_freezes_sections_after_source_segments(monkeypatch):
    pushed = []
    monkeypatch.setattr(live_push, 'push', lambda uid, notice: pushed.append((uid, notice)))
    snapshot = {'answer_delivery': {'message_id': 'msg_d', 'segments': [{'sequence': 1}, {'sequence': 2}], 'final': True}}
    row = {'id': 'run1', 'uid': 'u1', 'session_id': 's1', 'assistant_id': 'msg_a'}
    recorder = Recorder()
    segments = answer_delivery.append_final(recorder, row, snapshot, BODY)
    assert [x['sequence'] for x in segments] == [3, 4, 5, 6]
    assert ''.join(x['text'] for x in segments) == BODY
    assert {x['display_kind'] for x in segments} == {'final_answer'}
    assert not pushed
    for callback in recorder.callbacks:
        callback()
    assert [n['final'] for _, n in pushed] == [False, False, False, True]
    assert {n['message_id'] for _, n in pushed} == {'msg_a'}
    assert answer_delivery.append_final(recorder, row, snapshot, BODY) == []


def test_append_final_caps_segment_count(monkeypatch):
    monkeypatch.setattr(live_push, 'push', lambda uid, notice: None)
    body = ''.join(f'### 第{i}节\n\n内容{i}\n\n' for i in range(40))
    snapshot = {'answer_delivery': {'message_id': 'm', 'segments': [], 'final': True}}
    segments = answer_delivery.append_final(Recorder(), {'id': 'r', 'uid': 'u', 'session_id': 's'}, snapshot, body)
    assert len(segments) <= answer_delivery.MAX_FINAL_SEGMENTS
    assert ''.join(x['text'] for x in segments) == body


def test_read_replays_final_segments_after_source_segments(store):
    row = {'id': 'r', 'status': 'completed', 'request_ciphertext': store.encrypt({'answer_delivery': {
        'version': answer_delivery.VERSION, 'message_id': 'm', 'final': True,
        'segments': [{'sequence': 1, 'text': 'a'}], 'final_segments': [{'sequence': 2, 'text': 'b'}]}})}
    value = answer_delivery.read(store, row, 1)
    assert [x['text'] for x in value['items']] == ['b']


def test_large_segment_is_announced_without_text():
    row = {'id': 'r', 'session_id': 's'}
    segment = {'part_id': 'p', 'sequence': 1, 'display_kind': 'final_answer', 'origin': 'controlled_answer', 'text': '盗' * 40000}
    notice = live_push.segment_notice(row, 'm', segment)
    assert notice['truncated'] is True and 'text' not in notice
    assert len(json.dumps(notice, separators=(',', ':'))) < 262144
    small = live_push.segment_notice(row, 'm', {**segment, 'text': '短'})
    assert small['text'] == '短' and 'truncated' not in small


def test_phase_notice_uses_fixed_labels():
    row = {'id': 'r', 'session_id': 's'}
    assert live_push.phase_notice(row, 'running', 'generating')['label'] == '正在分析问题'
    assert live_push.phase_notice(row, 'completed', 'completed')['phase'] == 'completed'
    assert live_push.phase_notice(row, 'running', 'unknown_phase') is None


def test_after_commit_runs_only_after_outer_commit(store):
    seen = []
    with store.tx():
        store.after_commit(lambda: seen.append('outer'))
        with store.tx():
            store.after_commit(lambda: seen.append('inner'))
        assert seen == []
    assert seen == ['outer', 'inner']
    with pytest.raises(RuntimeError):
        with store.tx():
            store.after_commit(lambda: seen.append('rolled back'))
            raise RuntimeError
    assert 'rolled back' not in seen
    store.after_commit(lambda: seen.append('immediate'))
    assert seen[-1] == 'immediate'
    with store.tx():
        store.after_commit(lambda: 1 / 0)
        store.after_commit(lambda: seen.append('after failure'))
    assert seen[-1] == 'after failure'


def test_push_from_worker_thread_reaches_hub():
    async def run():
        received = []
        class Hub:
            closed = False
            def publish(self, notice):
                received.append(notice)
        class Hubs:
            hubs = {'u1': Hub()}
        live_push.install(asyncio.get_running_loop(), Hubs())
        try:
            thread = threading.Thread(target=live_push.push, args=('u1', {'type': 'run.progress'}))
            thread.start(); thread.join()
            live_push.push('missing', {'type': 'run.progress'})
            await asyncio.sleep(0)
            assert received == [{'type': 'run.progress'}]
        finally:
            live_push.uninstall()
    asyncio.run(run())


def test_updated_notices_coalesce_but_content_does_not():
    async def run():
        async with fixture(hub_coalesce_seconds=.05) as (hubs, registry, subscribe, opened, identity):
            _, sub = await subscribe()
            notice = {'type': 'updated', 'resources': ['messages'], 'session_id': 's'}
            def drain():
                items = []
                while not sub.queue.empty():
                    items.append(sub.queue.get_nowait())
                sub.pending.clear()
                return items
            sub.hub.publish(dict(notice))
            assert drain() == [notice]
            for _ in range(5):
                sub.hub.publish(dict(notice))
            for sequence in (1, 2):
                sub.hub.publish({'type': 'answer.segment', 'sequence': sequence})
            assert [x.get('sequence') for x in drain()] == [1, 2]
            await asyncio.sleep(.1)
            assert drain() == [notice]
            await asyncio.sleep(.1)
            sub.hub.publish(dict(notice))
            assert drain() == [notice]
    asyncio.run(run())
