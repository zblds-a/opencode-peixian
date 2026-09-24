"""Stable record-level references for completed calls in a still active Run."""
import copy
from . import business_runs, trusted_results
from shared.theft_provider_v2 import digest
from .backend_contract import error

PREFIX='record-v1:'

def projection(store,uid,sid,rid):
    row=business_runs.owned(store,uid,sid,rid)
    snapshot=store.decrypt(row['request_ciphertext'])
    if not snapshot.get('native_tool_policy'):
        return trusted_results.read(store,uid,sid,rid)
    from .native_tool_result import project
    # Only confirmed immutable call responses contribute; never model text.
    return project(row,snapshot)

def reference(result,record):
    return {'run_id':result['run_id'],'record_id':record['record_id'],
        'snapshot_id':record['snapshot_id'], 'result_digest':PREFIX+digest({
        'run_id':result['run_id'],'task_id':result['versions']['task_id'],
        'agent':result['agent'],'environment':result['data_environment'],'record':record})}

def resolve(store,uid,sid,ref,environment):
    row=business_runs.owned(store,uid,sid,ref['run_id'])
    result=projection(store,uid,sid,row['id'])
    if result.get('data_environment')!=environment or result.get('agent',{}).get('id')!='theft-assistant':
        error('source_version_changed','来源环境或助手不匹配。',409)
    matches=[r for r in result.get('records',[]) if r['record_id']==ref['record_id'] and r['snapshot_id']==ref['snapshot_id']]
    if len(matches)!=1 or reference(result,matches[0])!=ref:
        error('source_version_changed','来源记录或版本已变化。',409)
    return copy.deepcopy(matches[0]),store.decrypt(row['request_ciphertext'])
