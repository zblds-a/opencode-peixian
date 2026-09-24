"""Public execution metadata from observed calls and admission-frozen capabilities."""
import json
import math
import re
from .backend_contract import iso


def label(value, fallback):
    if not isinstance(value, str) or not value or len(value) > 100:
        return fallback
    if re.search(r'https?://|[/\\]|Bearer |sk-|px_|[\r\n\x00]|\d{17}[\dXx]', value, re.I):
        return fallback
    return value


def observed(snapshot, part):
    """Never infer execution from the selected skill/plugin list."""
    from .app import display_values
    tool = part.get('tool'); state = part.get('state', {})
    plugin = next((p for p in snapshot.get('plugins', []) if tool in p.get('tools', [])), None)
    skill = None
    if tool == 'skill' and isinstance(state.get('input'), dict):
        skill = next((s for s in snapshot.get('skills', []) if s.get('name') == state['input'].get('name')), None)
    capability = skill or plugin
    name = label((capability or {}).get('name'), '使用技能' if tool == 'skill' else '调用已授权插件' if plugin else '执行辅助操作')
    status = {'error': 'failed', 'completed': 'completed', 'running': 'running', 'pending': 'pending', 'cancelled': 'cancelled', 'waiting_input': 'waiting_input'}.get(state.get('status'), 'pending')
    # Only execution-time approved scalar fields are public. Skill content is never returned.
    display = (plugin or {}).get('display', {})
    inputs = display_values(state.get('input'), display.get('input_fields'), snapshot.get('display_secrets', []))
    raw = state.get('output', {})
    try:
        output = json.loads(raw) if isinstance(raw, str) and len(raw) <= 1048576 else raw if isinstance(raw, dict) else {}
    except (ValueError, TypeError):
        output = {}
    if isinstance(output, dict) and output.get('status') == 'needs_input' and status == 'completed':
        status = 'waiting_input'
        name = '待你确认查询条件' if not capability else name
    outputs = display_values(output, display.get('output_fields'), snapshot.get('display_secrets', [])) if status in ('completed', 'waiting_input') else {}
    outputs={k:v for k,v in outputs.items() if not isinstance(v,float) or math.isfinite(v)}
    count = outputs.get('returned_count')
    if type(count) is not int or not 0 <= count <= 1000000:
        outputs.pop('returned_count',None)
        count=0
    return {'call_id': part.get('callID') if isinstance(part.get('callID'), str) else part.get('id'),
            'message_id': part.get('messageID'), 'part_id': part.get('id'),
            'step_type': 'skill' if tool == 'skill' else 'plugin' if plugin else 'analysis',
            'name': name, 'status': status, 'capability_id': capability.get('id') if capability else None,
            'capability_name': name if capability else None, 'capability_version': str(capability['version']) if capability and capability.get('version') is not None else None,
            'input_summary': '按本轮已确认范围执行' if capability else '',
            'output_summary': f'返回 {count} 条记录' if 'returned_count' in outputs else '技能已加载' if skill and status == 'completed' else '无可公开的结果摘要' if status == 'completed' else '',
            'result': outputs, 'result_truncated': bool(isinstance(output, dict) and set(output) - set(outputs)),
            'record_count': count, 'details': {'inputs': inputs, 'outputs': outputs}}


def event_view(row, snapshot=None):
    from .business_runs import public_event
    value = public_event(row)
    metadata = (snapshot or {}).get('public_steps', {}).get(row['event_key'], {})
    if not metadata and row.get('capability_id') and row.get('started') is not None:
        capability=next((p for p in (snapshot or {}).get('plugins',[]) if p['id']==row['capability_id']),None)
        if capability:
            metadata={'capability_name':label(capability.get('name'),row['name']),
                      'capability_version':str(capability['version']) if capability.get('version') is not None else None,
                      'output_summary':f"返回 {row['record_count']} 条记录" if row['status']=='completed' else '',
                      'result':{'returned_count':row['record_count']} if row['status']=='completed' else {},'result_truncated':False}
    value.update({k: v for k, v in metadata.items() if k not in ('status', 'record_count')})
    value.update(run_id=row['run_id'], step_id=row['id'], call_id=metadata.get('call_id'),
                 capability_name=metadata.get('capability_name'), capability_version=metadata.get('capability_version'),
                 result=metadata.get('result', {}), result_truncated=metadata.get('result_truncated', False))
    return value


def attach(store, uid, sid, messages):
    """Use explicit message parent IDs and persisted call identities, never adjacency."""
    rows = store.rows('SELECT * FROM business_runs WHERE uid=? AND session_id=?', (uid, sid))
    observed_ids = {mid:r for r in rows for mid in store.decrypt(r['request_ciphertext']).get('observed_message_ids',[])}
    roots = {r['message_id']: r for r in rows}; endings = {r['assistant_id']: r for r in rows if r['assistant_id']}
    for message in messages:
        info = message['info']; row = roots.get(info.get('id')) or roots.get(info.get('parentID')) or endings.get(info.get('id')) or observed_ids.get(info.get('id'))
        if not row:
            continue
        info.update(run_id=row['id'], turn_id=row['message_id'])
        snapshot = store.decrypt(row['request_ciphertext'])
        if info.get('role')=='user' and info.get('id')==row['message_id']:
            from .message_attachments import project
            message['attachments']=project(store,uid,snapshot)
        events = {e['event_key']: e for e in store.rows('SELECT * FROM run_events WHERE run_id=?', (row['id'],))}
        for part in message.get('parts', []):
            if part.get('type') != 'tool':
                continue
            step = events.get(str(part.get('id') or part.get('callID')))
            if not step:
                continue
            view = event_view(step, snapshot)
            part['execution'] = view
            part['run_id'] = row['id']; part['step_id'] = step['id']; part['call_id'] = view['call_id']
            part['state'].update(status=view['status'], title=view['name'])
            part['tool'] = view['name']
            if 'details' in view:
                part['details'] = view['details']
        # A separate server-authored part leaves upstream model text and IDs untouched.
        if info.get('id') == row['assistant_id'] and row['result_ciphertext']:
            result = store.decrypt(row['result_ciphertext'])
            markdown = result.get('public_markdown') if isinstance(result, dict) else None
            if markdown:
                message['parts'].append({'id': 'part_summary_' + row['id'], 'type': 'text', 'text': markdown,
                                         'origin': 'verified_result', 'run_id': row['id']})
    return messages
