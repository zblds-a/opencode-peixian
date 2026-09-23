"""Per-tool native admission, bound to the immutable user Run and OpenCode call ID."""
import copy
import hashlib
import hmac
import json
import os
import re

from .backend_contract import error
from .data_plugin_policy import ACTIVE_KINDS
from .store import now
from .native_tool_scope import TOOL_TO_KIND, arguments
from . import provider_contracts
from shared import theft_provider_v2 as adapter
from shared import native_intent_review

VERSION='native-provider-gate-v1'
REVIEW_PROMPT=native_intent_review.PROMPT
REVIEW_VERSION=native_intent_review.VERSION

def enabled(store,uid):
    return store.schema_version()>=11 and uid in {value.strip() for value in os.getenv('PX_THEFT_NATIVE_UIDS','').split(',') if value.strip()}


def digest(value):
    return adapter.digest(value)


def review_id(run_id,call_id,plan_digest):
    return hashlib.sha256(adapter.canonical([VERSION,run_id,call_id,plan_digest]).encode()).hexdigest()[:32]


def verdict(value):
    if not isinstance(value,dict) or set(value)!={'verdict','reason_code'} or value['verdict'] not in ('allow','clarify','deny'):
        error('intent_review_invalid','意图核对结果无效，尚未查询资料。',409)
    reason=value['reason_code']
    if not isinstance(reason,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',reason):
        error('intent_review_invalid','意图核对结果无效，尚未查询资料。',409)
    return value


def redact(text, identities=None):
    references={value:key for key,value in (identities or {}).items()}
    return re.sub(r'(?<!\d)\d{17}[\dXx](?!\d)',lambda match:references.get(match.group(), '[其他身份已脱敏]'),text)[:4000]


def prepare(store,uid,sid,message_id,call_id,tool,args,revision):
    if not isinstance(call_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',call_id):
        error('tool_call_identity_invalid','工具调用身份无法核对。',409)
    if not isinstance(args,dict):error('native_tool_invalid','资料工具参数必须是对象。',422)
    kind=TOOL_TO_KIND.get(tool)
    if kind not in ACTIVE_KINDS:error('tool_archived','资料能力已归档或未授权。',404)
    with store.tx() as db:
        row=db.execute("SELECT * FROM business_runs WHERE uid=? AND session_id=? AND message_id=?",(uid,sid,message_id)).fetchone()
        if not row:error('run_not_found','执行记录不存在。',404)
        snapshot=store.decrypt(row['request_ciphertext'])
        policy=snapshot.get('native_tool_policy') or {}
        if policy.get('version')!=VERSION or tool not in policy.get('allowed_tools',[]):
            error('native_tool_unavailable','本轮未授权此资料工具。',409)
        if row['status'] not in ('queued','running') or row['cancel_requested'] or row['revision']!=revision:
            error('run_not_active','本轮执行已停止或配置已变化。',409)
        runtime=db.execute("SELECT * FROM runtimes WHERE uid=?",(uid,)).fetchone()
        user=db.execute("SELECT auth_version,active FROM users WHERE id=?",(uid,)).fetchone()
        if not user or not user['active'] or user['auth_version']!=row['auth_version'] or not runtime or runtime['revision']!=revision or runtime['security_blocked'] or runtime['recovery_required'] or runtime['gate_policy']!='open':
            error('native_authority_changed','授权或运行环境已变化。',409)
        calls=snapshot.setdefault('native_calls',{})
        if call_id in calls:
            item=calls[call_id]
            if item['tool']!=tool or item['args_digest']!=digest(args):
                error('tool_call_conflict','同一工具调用标识对应不同参数。',409)
            if item['status']=='completed':
                return {'cached':True,'response':copy.deepcopy(item['public_response'])}
            error('tool_call_unconfirmed','该调用已进入核对或投递流程，结果未知时不会重发。',409)
        if any(x['status'] in ('review_pending','approved','dispatching') for x in calls.values()):
            error('tool_call_busy','当前工具调用尚未结束。',409)
        no_progress=int(os.getenv('PX_NATIVE_NO_PROGRESS_LIMIT','3'))
        if not 1<=no_progress<=20:error('native_limits_invalid','无进展限制配置无效。',503)
        if len(calls)>=no_progress and all(x['status'] in ('rejected','unknown') for x in list(calls.values())[-no_progress:]):
            error('native_no_progress','连续调用没有取得新条件或结果，本轮停止取数。',409)
        context=snapshot.get('native_tool_context')
        if not context or context.get('version')!='native-tool-context-v1':
            error('scope_unavailable','本轮确认范围不可用。',409)
        # A scoped display reference is accepted only when it proves equality
        # to this Run's already confirmed raw identity. Never resolve arbitrary
        # prior persons, another account/session, or a merely model-supplied ID.
        checked_args=copy.deepcopy(args)
        identity_format='raw'
        if kind in adapter.PERSON and isinstance(args.get('person_identity'),str) and args['person_identity'].startswith('person-'):
            identity=context['confirmed'].get('person_identity')
            try:expected=adapter.person_ref(adapter.person_id(identity),store.worker_key.encode(),uid+'/'+sid)
            except adapter.ContractError:error('identity_parameter_invalid','请先明确本次查询对象；引用不能替代对象确认。',409)
            if not hmac.compare_digest(args['person_identity'],expected):
                error('identity_parameter_invalid','该引用与本轮已确认对象不一致。',409)
            checked_args['person_identity']=identity
            identity_format='confirmed_scoped_reference'
        query=arguments(kind,checked_args,context)
        identities={}
        if context['source_refs']:
            from .native_tool_scope import source_values
            derived,identities=source_values(store,uid,sid,kind,context)
            query.update(derived)
        elif kind in adapter.PERSON:
            identity=context['confirmed'].get('person_identity')
            if identity!=checked_args.get('person_identity'):
                error('identity_unconfirmed','人员条件尚未确认。',409)
            ref=adapter.person_ref(adapter.person_id(identity),store.worker_key.encode(),uid+'/'+sid)
            query['person_ref']=ref
            identities[ref]=identity
        applied=store.decrypt(runtime['applied_spec_ciphertext']) if runtime['applied_spec_ciphertext'] else {}
        frozen=provider_contracts.freeze(store,uid,kind,query,identities,applied)
        if frozen['plugin_version']!='3.0.0':
            error('native_plugin_version_required','资料插件原生调用版本尚未生效。',409)
        plan_digest=digest(frozen)
        if any(x['plan_digest']==plan_digest for x in calls.values()):
            error('native_duplicate_call','本轮已请求过相同资料；请使用已有结果。',409)
        item={'call_id':call_id,'tool':tool,'args_digest':digest(args),'plan_digest':plan_digest,
              'status':'review_pending','frozen':frozen,'scope_version':context['scope_version'],
              'source_refs':copy.deepcopy(context['source_refs']),'review_context_version':REVIEW_VERSION,'identity_input_format':identity_format,'created':now()}
        calls[call_id]=item
        db.execute("UPDATE business_runs SET request_ciphertext=?,updated=? WHERE id=?",(store.encrypt(snapshot),now(),row['id']))
        return {'cached':False,'run_id':row['id'],'call_id':call_id,'review_id':review_id(row['id'],call_id,plan_digest),
            'model_id':row['model_id'],'revision':revision,'digest':plan_digest,
            'review_input':{'version':REVIEW_VERSION,'user_request':redact(context['current_text'],identities),'task_id':context['task_id'],
                'scope_version':context['scope_version'],'confirmed_fields':sorted(set(context['confirmed']) & set(args)),
                'source_count':len(context['source_refs']),'tool':tool,'kind':kind,
                'capability_name':adapter.CATALOG[kind][0],
                'person_identity_confirmed':kind in adapter.PERSON,
                'confirmation_basis':'selected_source' if context['source_refs'] else 'user_supplied_values',
                'capability_limits':adapter.LIMITATIONS[kind],
                'identity_binding':({'status':'matched','person_ref':query['person_ref']} if kind in adapter.PERSON else None),
                'confirmed_values':{('person_ref' if k=='person_identity' else k):(query['person_ref'] if k=='person_identity' else v) for k,v in checked_args.items()},
                'source_refs':copy.deepcopy(context['source_refs']),
                'selected_source_values':derived if context['source_refs'] else {},
                'contract_defaults':{k:v for k,v in frozen['query'].items() if k not in query},
                'query_fields':sorted(frozen['query']),'requested_values':copy.deepcopy(frozen['query'])}}


def approve(store,uid,rid,call_id,plan_digest,decision,revision):
    result=verdict(decision)
    with store.tx() as db:
        row=db.execute("SELECT * FROM business_runs WHERE id=? AND uid=?",(rid,uid)).fetchone()
        if not row or row['revision']!=revision or row['status'] not in ('queued','running') or row['cancel_requested']:
            error('run_not_active','执行状态已变化。',409)
        snapshot=store.decrypt(row['request_ciphertext'])
        item=snapshot.get('native_calls',{}).get(call_id)
        if not item or item['status']!='review_pending' or item['plan_digest']!=plan_digest:
            error('intent_binding_changed','意图核对不属于当前调用。',409)
        runtime=db.execute("SELECT * FROM runtimes WHERE uid=?",(uid,)).fetchone()
        user=db.execute("SELECT active,auth_version FROM users WHERE id=?",(uid,)).fetchone()
        if (not user or not user['active'] or user['auth_version']!=row['auth_version']
            or not runtime or runtime['revision']!=revision or runtime['security_blocked']
            or runtime['recovery_required'] or runtime['gate_policy']!='open' or runtime['status']!='ready'):
            error('native_authority_changed','运行环境已变化。',409)
        applied=store.decrypt(runtime['applied_spec_ciphertext'])
        provider_contracts.validate(store,uid,item['frozen'],applied)
        item['verdict']={'version':'intent-review-v1','decision':result,'bound_digest':plan_digest,
                         'scope_version':item['scope_version'],'review_id':review_id(rid,call_id,plan_digest)}
        item['status']='approved' if result['verdict']=='allow' else 'rejected'
        if item['status']=='approved':
            snapshot['provider_plan']=copy.deepcopy(item['frozen'])
            snapshot['native_current_call']=call_id
        db.execute("UPDATE business_runs SET request_ciphertext=?,updated=? WHERE id=?",(store.encrypt(snapshot),now(),rid))
        return {'allowed':item['status']=='approved','reason_code':result['reason_code']}


def review_failed(store,uid,rid,call_id,plan_digest,revision):
    """Close only an unapproved review; this cannot grant or resend a call."""
    with store.tx() as db:
        row=db.execute('SELECT * FROM business_runs WHERE id=? AND uid=?',(rid,uid)).fetchone()
        if not row or row['revision']!=revision:error('run_not_found','执行记录无法核对。',409)
        snapshot=store.decrypt(row['request_ciphertext']);item=snapshot.get('native_calls',{}).get(call_id)
        if not item or item['plan_digest']!=plan_digest:error('intent_binding_changed','核对身份不一致。',409)
        if item['status']=='review_pending':
            item.update(status='rejected',error_code='intent_review_unavailable',dispatch_status='not_dispatched')
            db.execute('UPDATE business_runs SET request_ciphertext=?,updated=? WHERE id=?',(store.encrypt(snapshot),now(),rid))
        return {'ok':True}
