"""Operator-only archival of legacy business plugins; never deletes packages or Runs.

Run with the matching Control image after a complete private backup. Each account
must be idle, and all eight replacement plugins must already be granted, installed,
and published. This script changes one account at a time.
"""
import argparse
import json
import os
from pathlib import Path

from .data_plugin_policy import ACTIVE_PLUGIN_IDS, installable
from .store import encode, ident, now
from .runtime_security import block_runtime


def rows(db, sql, params=()):
    return [dict(value) for value in db.execute(sql, params)]


def inventory(store):
    with store.read(snapshot=True) as db:
        plugins=rows(db,"SELECT id,version,enabled FROM plugins ORDER BY id,version")
        installs=rows(db,"SELECT plugin,version,enabled,count(*) AS accounts FROM installs GROUP BY plugin,version,enabled ORDER BY plugin,version")
        grants=rows(db,"SELECT resource,count(*) AS accounts FROM grants WHERE kind='plugin' GROUP BY resource ORDER BY resource")
        applied=[]
        for runtime in rows(db,"SELECT uid,applied_spec_ciphertext FROM runtimes"):
            if runtime['applied_spec_ciphertext']:
                for plugin in store.decrypt(runtime['applied_spec_ciphertext']).get('plugins',[]):
                    if not installable(plugin['id']):
                        applied.append({'uid':runtime['uid'],'plugin_id':plugin['id']})
        return {'active_ids':sorted(ACTIVE_PLUGIN_IDS),'published':plugins,'installs':installs,'grants':grants,'legacy_applied':applied}


def migrate_account(store, uid, receipt_path):
    receipt_path=Path(receipt_path)
    if receipt_path.exists():
        raise ValueError('receipt_exists_review_before_retry')
    with store.tx() as db:
        account=db.execute("SELECT role,active FROM users WHERE id=?",(uid,)).fetchone()
        runtime=db.execute("SELECT * FROM runtimes WHERE uid=?",(uid,)).fetchone()
        if not account or account['role']!='user' or not account['active'] or not runtime:
            raise ValueError('ordinary_active_account_required')
        if db.execute("SELECT 1 FROM business_runs WHERE uid=? AND status NOT IN ('completed','failed','cancelled')",(uid,)).fetchone():
            raise ValueError('active_run_must_finish')
        if db.execute("SELECT 1 FROM jobs WHERE uid=? AND status IN ('queued','running','waiting_capacity')",(uid,)).fetchone():
            raise ValueError('environment_job_must_finish')
        if runtime['recovery_required'] or runtime['security_blocked']:
            raise ValueError('runtime_recovery_must_finish')
        # Preserve each account's least-privilege selection. Granted new tools
        # must be ready; do not grant the other seven merely to migrate old ones.
        active_grants=rows(db,"SELECT resource FROM grants WHERE uid=? AND kind='plugin'",(uid,))
        for grant in active_grants:
            pid=grant['resource']
            if pid not in ACTIVE_PLUGIN_IDS:
                continue
            install=db.execute("SELECT i.version,i.enabled,p.enabled AS published FROM installs i JOIN plugins p ON p.id=i.plugin AND p.version=i.version WHERE i.uid=? AND i.plugin=?",(uid,pid)).fetchone()
            if not install or install['version']!='3.0.0' or not install['enabled'] or not install['published']:
                raise ValueError('replacement_not_ready:'+pid)
        before={'installs':rows(db,"SELECT * FROM installs WHERE uid=? AND plugin NOT IN ("+','.join('?' for _ in ACTIVE_PLUGIN_IDS)+")",(uid,*sorted(ACTIVE_PLUGIN_IDS))),
                'grants':rows(db,"SELECT * FROM grants WHERE uid=? AND kind='plugin' AND resource NOT IN ("+','.join('?' for _ in ACTIVE_PLUGIN_IDS)+")",(uid,*sorted(ACTIVE_PLUGIN_IDS)))}
        if not before['installs'] and not before['grants']:
            return {'status':'already_converged','account':uid}
        # Revoke first, closing new calls immediately. Historical rows and packages stay.
        for value in before['installs']:
            db.execute("UPDATE installs SET enabled=0 WHERE uid=? AND plugin=?",(uid,value['plugin']))
        for value in before['grants']:
            db.execute("DELETE FROM grants WHERE uid=? AND kind='plugin' AND resource=?",(uid,value['resource']))
        block_runtime(store,db,uid,reason='authorization_revoked')
        job=store.queue_in_transaction(db,uid,'apply')
        action='eight.plugins.account.'+ident()
        payload={'version':1,'uid':uid,'action':action,'before':before,'created':now()}
        receipt_path.parent.mkdir(parents=True,exist_ok=True)
        descriptor=os.open(receipt_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w',encoding='utf-8') as output:
            output.write(store.encrypt(payload))
            output.flush()
            os.fsync(output.fileno())
        db.execute("INSERT INTO audit(id,actor,actor_role,action,target,result,created) VALUES(?,?,?,?,?,'success',?)",
                   (ident(),'operator','super_admin',action,uid,now()))
        return {'status':'revoked_waiting_for_runtime_reconcile','account':uid,'receipt':str(receipt_path),'archived_install_count':len(before['installs']),'revoked_grant_count':len(before['grants']),'apply_job':job.get('id'),'desired_revision':job.get('revision')}


def archive_publications(store):
    with store.tx() as db:
        if db.execute("SELECT 1 FROM grants WHERE kind='plugin' AND resource NOT IN ("+','.join('?' for _ in ACTIVE_PLUGIN_IDS)+")",tuple(sorted(ACTIVE_PLUGIN_IDS))).fetchone():
            raise ValueError('legacy_grants_remain')
        if db.execute("SELECT 1 FROM installs WHERE enabled=1 AND plugin NOT IN ("+','.join('?' for _ in ACTIVE_PLUGIN_IDS)+")",tuple(sorted(ACTIVE_PLUGIN_IDS))).fetchone():
            raise ValueError('legacy_installs_remain')
        for runtime in rows(db,"SELECT applied_spec_ciphertext FROM runtimes"):
            if runtime['applied_spec_ciphertext'] and any(not installable(p['id']) for p in store.decrypt(runtime['applied_spec_ciphertext']).get('plugins',[])):
                raise ValueError('legacy_runtime_still_applied')
        ids=[row['id'] for row in rows(db,"SELECT DISTINCT id FROM plugins") if not installable(row['id'])]
        for pid in ids:
            db.execute("UPDATE plugins SET enabled=0 WHERE id=?",(pid,))
        connection_ids=[row['connection_id'] for row in rows(db,"SELECT DISTINCT b.connection_id FROM plugin_connections b JOIN plugins p ON p.id=b.plugin WHERE p.enabled=0")]
        disabled=[]
        for cid in connection_ids:
            if db.execute("SELECT 1 FROM plugin_connections b JOIN plugins p ON p.id=b.plugin AND p.version=b.version WHERE b.connection_id=? AND p.enabled=1",(cid,)).fetchone():
                continue
            row=db.execute("SELECT config FROM connections WHERE id=?",(cid,)).fetchone()
            if row:
                config=json.loads(row['config'])
                if config.get('enabled'):
                    config['enabled']=False
                    db.execute("UPDATE connections SET config=?,revision=revision+1 WHERE id=?",(encode(config),cid))
                    disabled.append(cid)
        db.execute("INSERT INTO audit(id,actor,actor_role,action,target,result,created) VALUES(?,?,?,?,?,'success',?)",
                   (ident(),'operator','super_admin','eight.plugins.archive','business-data',now()))
        return {'status':'archived','publication_ids':ids,'exclusive_connections_disabled':len(disabled)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('inventory','account','archive'))
    parser.add_argument('--uid')
    parser.add_argument('--receipt',type=Path)
    args=parser.parse_args()
    from .settings import configured_store
    store=configured_store()
    if args.action=='inventory':
        result=inventory(store)
    elif args.action=='account':
        if not args.uid or not args.receipt:parser.error('account requires --uid and --receipt')
        result=migrate_account(store,args.uid,args.receipt)
    else:
        result=archive_publications(store)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
