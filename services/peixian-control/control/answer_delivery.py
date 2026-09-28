"""Durable verified source segments, independent of unverified model tokens."""
import copy
import html
from .backend_contract import error

VERSION = 'controlled-segments-v1'


def freeze(snapshot, rid):
    snapshot['answer_delivery'] = {'version': VERSION, 'message_id': 'msg_delivery_' + rid,
                                  'segments': [], 'calls': [], 'final': False}


def zero_text(query):
    if isinstance(query.get('start'), str) and isinstance(query.get('end'), str):
        return '查询时段 ' + html.escape(query['start']) + ' 至 ' + html.escape(query['end']) + ' 返回 0 条。'
    return '返回 0 条。'


def record(snapshot, row, call_id):
    delivery = snapshot.get('answer_delivery')
    if not delivery or delivery.get('final') or call_id in delivery['calls']:
        return
    call = snapshot.get('native_calls', {}).get(call_id, {})
    if call.get('status') != 'completed':
        return
    from shared.theft_provider_v2 import VERSION as CONTRACT_VERSION
    public=call.get('public_response') or {}
    if public.get('version')!=CONTRACT_VERSION or public.get('kind')!=call.get('frozen',{}).get('kind') or not public.get('response_snapshot_id'):
        return
    if type(public.get('returned_count')) is not int or public['returned_count']!=len(public.get('records',[])):
        return
    from .native_tool_result import project
    isolated = {**snapshot, 'native_calls': {call_id: call}}
    result = project(dict(row), isolated)
    from .reply_presentation import build
    cards = build(result)['clues']
    # Publish complete source sentences only after response contract validation.
    # Paging above five is explicit; the remaining records stay in Result V2.
    selected = cards[:5]
    if not selected and (result.get('records') or public['returned_count']!=0):
        return
    from shared.theft_provider_v2 import CATALOG
    from shared.capability_labels import display
    label = display(call['frozen']['kind'], CATALOG[call['frozen']['kind']][0])
    text = '### ' + label + '\n\n'
    text += '\n\n'.join(html.escape(c['summary']) for c in selected)
    if not selected:
        text += zero_text(call['frozen'].get('query') or {})
    gaps = [s for s in public.get('segments') or [] if isinstance(s, dict) and s.get('status') != 'ok']
    if gaps:
        text += '\n\n未核验时段：' + '；'.join(html.escape(str(s.get('start')) + ' 至 ' + str(s.get('end'))) for s in gaps) + '。'
    sequence = len(delivery['segments']) + 1
    delivery['segments'].append({'sequence': sequence, 'content_revision': 1,
        'part_id': 'part_delivery_' + row['id'] + '_' + str(sequence), 'operation': 'append',
        'origin': 'controlled_source', 'visibility': 'user', 'display_kind': 'source_answer',
        'text': text, 'source_ids': [s for c in selected for s in c['source_ids']],
        'claim_ids': [s for c in selected for s in c['claim_ids']]})
    delivery['calls'].append(call_id)


def finish(snapshot):
    delivery = snapshot.get('answer_delivery')
    if delivery:
        delivery['final'] = True


def read(store, row, after=0, limit=100):
    if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
        error('invalid_sequence', '增量序号或条数无效。', 422)
    delivery = store.decrypt(row['request_ciphertext']).get('answer_delivery')
    if not delivery:
        return {'version': VERSION, 'run_id': row['id'], 'status': 'unavailable',
                'items': [], 'next_sequence': after, 'final': row['status'] in ('completed','failed','cancelled')}
    segments = delivery['segments']
    if after > len(segments):
        error('sequence_ahead', '增量序号超过本次执行范围，请从零恢复。', 409)
    items = copy.deepcopy(segments[after:after + limit])
    return {'version': VERSION, 'run_id': row['id'], 'message_id': delivery['message_id'],
            'status': 'ready' if delivery['final'] else 'streaming', 'items': items,
            'next_sequence': items[-1]['sequence'] if items else after,
            'final': delivery['final'], 'has_more': after + len(items) < len(segments),
            'execution_status': row['status']}


def attach(store, uid, sid, messages):
    for row in store.rows('SELECT * FROM business_runs WHERE uid=? AND session_id=? ORDER BY created,id', (uid, sid)):
        delivery = store.decrypt(row['request_ciphertext']).get('answer_delivery')
        if not delivery or not delivery['segments']:
            continue
        # Source segments use a different stable message from the final answer;
        # late upstream snapshots therefore cannot remove or rewrite them.
        messages[:] = [m for m in messages if m['info']['id'] != delivery['message_id']]
        messages.append({'info': {'id': delivery['message_id'], 'role': 'assistant',
            'sessionID': sid, 'run_id': row['id'], 'parentID': row['message_id'],
            'time': {'created': row['created'] * 1000}},
            'parts': [{'id': s['part_id'], 'type': 'text', 'run_id': row['id'],
                       **{k: copy.deepcopy(s[k]) for k in ('text','origin','visibility','display_kind','sequence','content_revision','source_ids')}}
                      for s in delivery['segments']]})
    messages.sort(key=lambda m: m['info'].get('time', {}).get('created', 0))
    return messages
