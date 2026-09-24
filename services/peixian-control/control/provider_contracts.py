"""Explicit release/environment binding. No discovery, credentials or network calls."""
import json
import os
from pathlib import Path
from .backend_contract import error
from .capabilities import check_selection
from shared import theft_provider_v2 as adapter
from .data_plugin_policy import ACTIVE_KINDS

RELEASES = {'1.0.0': 'theft-provider-contract-v1', '2.0.0': adapter.VERSION, '3.0.0': adapter.VERSION}


def settings(uid):
    try:
        path=os.getenv('PX_THEFT_REAL_CONFIG_FILE')
        config=json.loads(Path(path).read_text(encoding='utf-8') if path else os.getenv('PX_THEFT_REAL_CONFIG','{}'))
        if not isinstance(config,dict):raise ValueError()
        if config.get('enabled') is not True or uid not in config.get('users',[]):
            error('real_provider_disabled','真实资料连接尚未开放。',409)
        if config.get('environment')!='acceptance_real':raise ValueError()
        limits=config['limits']
        adapter.normalize('incidents',{'lon':'0','lat':'0','radius_m':1},limits)
        if not isinstance(config['connections'],dict) or not config['connections'] or set(config['connections'])-({'police','warning'}|set(ACTIVE_KINDS)):raise ValueError()
        # Acceptance whitelist (bbox / identity hashes) is no longer required.
        return config
    except (OSError,ValueError,KeyError,TypeError):
        error('real_provider_configuration_invalid','真实连接配置尚未确认。',409)


def binding(store,uid,kind,applied):
    if kind not in ACTIVE_KINDS:error('provider_contract_unconfirmed','此资料合同尚未开放。',409)
    config=settings(uid)
    plugin_id='peixian-theft-'+kind.replace('_','-')
    check_selection(store,uid,{'skill_ids':[],'plugin_ids':[plugin_id]})
    plugin=next((p for p in applied.get('plugins',[]) if p['id']==plugin_id),None)
    if not plugin or RELEASES.get(plugin['version'])!=adapter.VERSION or plugin['manifest'].get('tools')!=['peixian_query_'+kind]:
        error('provider_not_applied','真实资料插件版本尚未生效。',409)
    group=adapter.CATALOG[kind][3]
    cid=config['connections'].get(kind,config['connections'].get(group))
    if not cid:error('provider_connection_unconfigured','此类资料连接尚未配置，其他已配置能力可继续使用。',409)
    row=store.one('SELECT c.* FROM connections c JOIN plugin_connections b ON b.connection_id=c.id WHERE b.plugin=? AND b.version=? AND b.alias=? AND c.id=?',(plugin_id,plugin['version'],'provider',cid))
    if not row:error('provider_connection_mismatch','资料连接与发布绑定不一致。',409)
    policy=json.loads(row['config'])
    if not policy.get('enabled') or policy.get('auth_type')!=('none' if group=='police' else 'bearer'):
        error('provider_connection_unavailable','资料连接未启用或认证合同不匹配。',409)
    return {'plugin_id':plugin_id,'plugin_version':plugin['version'],'tool_id':'peixian_query_'+kind,'connection_id':cid,'connection_revision':row['revision'],'contract_version':adapter.VERSION,'data_environment':'acceptance_real','limits':config['limits'],'coordinate_compatibility':config.get('coordinate_compatibility',{}),'binding_digest':adapter.digest({'manifest':plugin['manifest'],'connection':policy,'revision':row['revision'],'deployment':config})}


def freeze(store,uid,kind,query,identities,applied):
    value=binding(store,uid,kind,applied)
    try:
        normalized=adapter.normalize(kind,query,value['limits'])
        # Layer 4 removed: no approved_identity_hashes / approved_bbox gate.
        request=adapter.request_spec(kind,normalized,value['limits'],identities)
    except adapter.ContractError as exc:error(str(exc),'查询条件未满足资料接口合同，请补充指定条件。',422)
    return {**value,'kind':kind,'version':adapter.VERSION,'query':normalized,'request':request,'identities':identities}


def validate(store,uid,plan,applied):
    current=freeze(store,uid,plan['kind'],plan['query'],plan['identities'],applied)
    if any(plan.get(k)!=current[k] for k in current):
        error('provider_binding_changed','连接、合同、能力或范围已变化，请重新确认。',409)
    if adapter.request_spec(plan['kind'],plan['query'],plan['limits'],plan['identities'])!=plan['request']:
        error('provider_plan_mismatch','查询计划内容不一致。',409)
