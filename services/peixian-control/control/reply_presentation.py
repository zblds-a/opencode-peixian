"""Source-only V2 cards. Never derive facts from model prose or ranking."""
import copy
import hashlib
import json

VERSION = 'source-clues-v1'
TYPES = {'tracks': 'observation', 'incidents': 'place', 'captures': 'observation',
         'profile': 'person', 'night': 'night', 'community': 'place',
         'warning_detail': 'observation', 'warnings': 'observation', 'warning_logs': 'observation',
         'funds': 'funds', 'vehicle': 'vehicle', 'portrait': 'person'}


def build(result):
    records = {r['record_id']: r for r in result.get('records', [])}
    cards = []
    for claim in result.get('claims', []):
        if claim.get('verification_status') != 'approved' or claim.get('type') != 'fact':
            continue
        fields = claim.get('protected_fields', {})
        rid = fields.get('record_id')
        record = records.get(rid)
        if not record or rid not in claim.get('source_ids', []):
            continue
        if fields.get('snapshot_id') != record.get('snapshot_id'):
            continue
        source_fields = record.get('fields', record)
        if 'fields' in fields and fields['fields'] != source_fields:
            continue
        if record.get('module') not in TYPES:
            continue
        source_run = record.get('source_run_id') or claim.get('source_run_id')
        if source_run != claim.get('source_run_id'):
            continue
        identity = hashlib.sha256((source_run + ':' + rid).encode()).hexdigest()[:24]
        # Time keys are contract-specific; cjsj is response time, not incident time.
        time_key = {'incidents': 'cjsj', 'tracks': 'captureTime', 'night': 'captureTime'}.get(record['module'])
        at = source_fields.get(time_key) if time_key else source_fields.get('occurred_at')
        text = claim['statement']
        from shared.theft_provider_v2 import CATALOG
        from shared.capability_labels import display
        title=display(record['module'], CATALOG.get(record['module'], (record['module'],))[0]) + '来源记录'
        cards.append({'id': 'clue_' + identity, 'type': TYPES[record['module']],
                      'title': title, 'headline': text, 'summary': text,
                      'discoveries': [text], 'verification': 'source_fields',
                      'evidence': [{'id': 'source_' + identity, 'label': '来源记录',
                                    'content': text, 'occurred_at': at,
                                    'time_semantics': time_key or 'occurred_at',
                                    'source_run_id': source_run, 'record_id': rid,
                                    'claim_id': claim['claim_id'], 'snapshot_id': record['snapshot_id']}],
                      'source_run_id': source_run, 'source_ids': [rid],
                      'claim_ids': [claim['claim_id']], 'missing': copy.deepcopy(result.get('missing', []))})
    revision = hashlib.sha256(json.dumps(cards, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'version': VERSION, 'status': 'partial' if cards and result.get('missing') else 'ready' if cards else 'empty',
            'revision': revision, 'clues': cards, 'missing': copy.deepcopy(result.get('missing', []))}


def source_detail(result,evidence_id):
    from .backend_contract import error
    presentation=result.get('presentation') or {}
    if presentation.get('version')!=VERSION:error('source_not_found','来源不存在或当前版本不支持。',404)
    evidence=next((e for c in presentation.get('clues',[]) for e in c.get('evidence',[]) if e.get('id')==evidence_id),None)
    if evidence is None:error('source_not_found','来源不存在或无权访问。',404)
    record=next((r for r in result.get('records',[]) if r.get('record_id')==evidence['record_id'] and r.get('snapshot_id')==evidence['snapshot_id'] and r.get('source_run_id',evidence['source_run_id'])==evidence['source_run_id']),None)
    if record is None:error('source_not_found','来源记录无法对应当前快照。',404)
    return {'version':'source-detail-v1','run_id':result['run_id'],'evidence':copy.deepcopy(evidence),'record':copy.deepcopy(record),'versions':copy.deepcopy(result.get('versions',{}))}
