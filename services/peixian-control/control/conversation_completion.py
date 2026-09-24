"""Finish a dismissed clarification without dispatching or inventing a model reply."""
from . import business_runs as runs
from .store import now

VERSION = 'adaptive-dialogue-v1'

def dismissed(part):
    state = part.get('state') or {}
    return part.get('type') == 'tool' and part.get('tool') == 'question' and state.get('status') == 'error' and state.get('error') == 'The user dismissed this question'

def finish_dismissed(store, row, messages):
    with store.tx() as db:
        current = dict(db.execute('SELECT * FROM business_runs WHERE id=?', (row['id'],)).fetchone())
        snapshot = store.decrypt(current['request_ciphertext'])
        if snapshot.get('dialogue_policy') != VERSION or current['status'] in runs.TERMINAL or current['cancel_requested']:
            return False
        selected = [m for m in messages if m.get('info', {}).get('role') == 'assistant' and m.get('info', {}).get('parentID') == current['message_id']]
        if not selected or selected[-1]['info'].get('error'):
            return False
        parts = [p for m in selected for p in m.get('parts', []) if p.get('type') == 'tool']
        if not parts or not dismissed(parts[-1]):
            return False
        if any(c.get('status') not in ('completed','failed','rejected','cancelled') for c in snapshot.get('native_calls', {}).values()):
            return False
        snapshot['dialogue_completion'] = {'version': VERSION, 'reason': 'clarification_dismissed', 'model_final': False}
        pending = snapshot.get('native_pending_questions', {})
        for spec in pending.values():
            if spec.get('status') == 'pending': spec['status'] = 'rejected'
        from .native_tool_result import project
        result = project(current, snapshot)
        delivery = snapshot.get('answer_delivery')
        if delivery and not delivery.get('final'):
            sequence = len(delivery['segments']) + 1
            text = '已停止需要补充条件的查询，已取得资料仍然保留。\n\n' + result['answer']['summary']
            delivery['segments'].append({'sequence': sequence, 'content_revision': 1,
                'part_id': 'part_completion_' + current['id'], 'operation': 'append',
                'origin': 'controlled_source', 'visibility': 'user', 'display_kind': 'source_answer',
                'text': text, 'source_ids': [], 'claim_ids': []})
        db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?', (store.encrypt(snapshot), current['id']))
        for event in store.rows("SELECT * FROM run_events WHERE run_id=? AND status IN ('pending','waiting_input')", (current['id'],)):
            runs.event(store,current['id'],event['event_key'],event['step_type'],event['name'],'cancelled',event['started'],now(),event['capability_id'],event['record_count'])
        runs.set_state(store,current['id'],'completed','completed')
        runs.event(store,current['id'],'dialogue-summary','result','汇总已有资料','completed',completed=now())
        return True
