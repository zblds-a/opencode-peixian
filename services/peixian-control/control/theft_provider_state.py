"""Provider calls reuse durable Run storage and Gateway-owned operation leases."""
import copy,json
from .facts_runtime import FactsState,reject
from .business_runs import event
from .store import now,encode
from .theft_provider_flow import availability,pid
from shared.theft_provider import parse_response,ContractError,CATALOG
from shared import theft_provider_v2 as v2
class ProviderState(FactsState):
    def _load(self,db,uid,rid,revision):
        row=db.execute('SELECT * FROM business_runs WHERE id=? AND uid=?',(rid,uid)).fetchone()
        if not row or row['revision']!=revision:reject('provider_execution_identity')
        snapshot=self.store.decrypt(row['request_ciphertext'])
        if not snapshot.get('provider_plan'):reject('provider_plan_missing')
        state=snapshot.setdefault('provider_state',{'modules':{},'operation':None})
        return row,snapshot,state
    def read(self,uid,rid,revision):
        with self.store.read(snapshot=True) as db:
            row,snap,state=self._load(db,uid,rid,revision)
            value=copy.deepcopy({'plan':snap['provider_plan'],'state':state})
            if value['plan'].get('version')==v2.VERSION:
                value['plan'].pop('identities',None)
                for entry in value['state']['modules'].values():
                    if 'response' in entry:entry['response']=v2.public_result(entry['response'],self.store.worker_key.encode(),uid+'/'+row['session_id'])
            return value
    def authorize(self,db,row,snapshot,module=None):
        from .agents.runtime import validate_execution
        validate_execution(snapshot)
        runtime=db.execute('SELECT * FROM runtimes WHERE uid=?',(row['uid'],)).fetchone();user=db.execute('SELECT * FROM users WHERE id=?',(row['uid'],)).fetchone()
        if not user or not user['active'] or user['auth_version']!=row['auth_version'] or row['cancel_requested'] or row['status'] not in ('queued','running'):reject('provider_authority_changed')
        if not runtime or runtime['revision']!=row['revision'] or runtime['security_blocked'] or runtime['recovery_required'] or runtime['gate_policy']=='closed_all' or runtime['status'] not in ('ready','draining'):reject('provider_runtime_changed')
        if self.store.maintenance_status(db)['maintenance_mode'] not in ('normal','frozen'):reject('provider_maintenance')
        plan=snapshot['provider_plan']
        if snapshot.get('provider_followup'):reject('provider_followup_read_only')
        if module is not None and module!=plan['kind']:reject('provider_method_changed')
        if snapshot.get('agent_profile',{}).get('id')!='theft-assistant':reject('provider_agent_changed')
        applied=self.store.decrypt(runtime['applied_spec_ciphertext'])
        if snapshot.get('native_tool_policy'):
            from .native_tool_gate import VERSION as native_version
            from shared.theft_provider_v2 import digest
            call_id=snapshot.get('native_current_call')
            call=snapshot.get('native_calls',{}).get(call_id,{})
            verdict=call.get('verdict',{})
            if (snapshot['native_tool_policy'].get('version')!=native_version
                or snapshot.get('task_spec',{}).get('schema_version')!='native-tools-v1'
                or not call_id or call.get('status') not in ('approved','dispatching','completed','rejected','unknown','cancelled')
                or call.get('plan_digest')!=digest(plan)
                or verdict.get('bound_digest')!=digest(plan)
                or verdict.get('scope_version')!=snapshot.get('native_tool_context',{}).get('scope_version')
                or verdict.get('decision',{}).get('verdict')!='allow'
                or plan.get('tool_id') not in snapshot['native_tool_policy'].get('allowed_tools',[])):
                reject('native_intent_binding_changed')
            from .provider_contracts import validate
            validate(self.store,row['uid'],plan,applied)
            return
        if snapshot.get('task_spec',{}).get('schema_version')!='task-spec-v4':reject('provider_agent_changed')
        if plan.get('version')==v2.VERSION:
            from .provider_contracts import validate
            validate(self.store,row['uid'],plan,applied)
            if snapshot.get('analysis_task'):
                from .analysis_tasks import check_execution
                check_execution(self.store,row['uid'],row['session_id'],row['id'],snapshot['analysis_task'])
            return
        p=availability(self.store,row['uid'],plan['kind'],applied)
        if p['version']!=plan['plugin_version']:reject('provider_plugin_changed')
    def _event(self,rid,module,status):
        kind=module
        if module not in v2.CATALOG and module not in CATALOG:
            row=self.store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(rid,))
            if row:
                kind=self.store.decrypt(row['request_ciphertext']).get('native_calls',{}).get(module,{}).get('frozen',{}).get('kind',module)
        label=(v2.CATALOG.get(kind) or CATALOG.get(kind) or ('资料查询',))[0]
        event(self.store,rid,'provider.'+module,'plugin',label,
              {'pending':'running','unknown':'failed'}.get(status,status),
              completed=now() if status!='pending' else None,capability=pid(kind))
    def reserve(self,uid,rid,revision,operation,module):
        with self.store.tx() as db:
            row,snap,state=self._owned(db,uid,rid,revision,operation);self.authorize(db,row,snap,module)
            key=snap.get('native_current_call') or module
            if key in state['modules']:return False
            state['modules'][key]={'status':'pending','started':now(),'reservation_count':1,'dispatch_attempts':0,'response_count':0,'may_have_sent':False}
            self._save(db,rid,snap);self._event(rid,key,'pending')
            prior=db.execute('SELECT actual_plugins FROM invocations WHERE run_id=?',(rid,)).fetchone()
            if prior:db.execute('UPDATE invocations SET actual_plugins=? WHERE run_id=?',(encode(sorted(set(json.loads(prior[0]))|{pid(module)})),rid))
            return True
    def dispatch(self,uid,rid,revision,operation,module):
        with self.store.tx() as db:
            row,snap,state=self._owned(db,uid,rid,revision,operation);self.authorize(db,row,snap,module)
            key=snap.get('native_current_call') or module
            value=state['modules'].get(key)
            if not value or value['status']!='pending' or value.get('dispatch_attempts',0):reject('provider_dispatch_already_reserved')
            # This is a durable send-boundary attempt, not proof the supplier received HTTP.
            value.update(dispatch_attempts=1,may_have_sent=True)
            if snap.get('native_current_call'):snap['native_calls'][key]['status']='dispatching'
            self._save(db,rid,snap)

    def complete(self,uid,rid,revision,operation,module,status,response=None):
        if status not in ('completed','unknown','cancelled'):reject('provider_invalid_status')
        with self.store.tx() as db:
            row,snap,state=self._owned(db,uid,rid,revision,operation);self.authorize(db,row,snap,module)
            key=snap.get('native_current_call') or module
            value=state['modules'].get(key)
            if not value or value['status']!='pending':reject('provider_not_pending')
            if status=='completed':
                value['response_count']=1
                value['may_have_sent']=True
                try:
                    plan=snap['provider_plan']
                    value['response']=(v2.parse_response(module,plan['query'],response,plan['limits'],plan['identities']) if plan.get('version')==v2.VERSION else parse_response(module,plan['query'],response))
                    if plan.get('version')==v2.VERSION:
                        value['public_response']=v2.public_result(value['response'],self.store.worker_key.encode(),uid+'/'+row['session_id'])
                except (ContractError,ValueError,TypeError,KeyError):status='rejected'
            value.update(status=status,completed=now())
            if snap.get('native_current_call'):
                call=snap['native_calls'][key]
                call['status']=status
                if status=='completed':call['public_response']=copy.deepcopy(value['public_response'])
            self._save(db,rid,snap);self._event(rid,key,status)
            return status
    def check(self,uid,rid,revision,operation,module=None):
        with self.store.tx() as db:
            row,snap,state=self._owned(db,uid,rid,revision,operation);self.authorize(db,row,snap,module)

    def terminate(self,uid,rid,revision):
        with self.store.tx() as db:
            _,snap,state=self._load(db,uid,rid,revision)
            for kind,value in state['modules'].items():
                if value['status']=='pending':
                    value.update(status='unknown',completed=now())
                    if kind in snap.get('native_calls',{}):snap['native_calls'][kind]['status']='unknown'
                    self._event(rid,kind,'unknown')
            self._save(db,rid,snap)

    def finish(self,uid,rid,revision,operation):
        super().finish(uid,rid,revision,operation)
        with self.store.tx() as db:
            _,snap,state=self._load(db,uid,rid,revision)
            current=snap.get('native_current_call')
            if current:
                call=snap.get('native_calls',{}).get(current)
                entry=state['modules'].get(current,{})
                if call and call['status'] in ('approved','dispatching'):
                    call['status']=entry.get('status') if entry.get('status') in ('completed','rejected','cancelled') else 'unknown'
                snap['native_current_call']=None
                self._save(db,rid,snap)
