"""Operator-only archival of legacy business plugins; never deletes packages or Runs.

Run with the matching Control image after a complete private backup. Each account
must be idle, and all eight replacement plugins must already be granted, installed,
and published. This script changes one account at a time.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from .data_plugin_policy import ACTIVE_PLUGIN_IDS, ACTIVE_VERSION, installable
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
                    if not installable(plugin['id']) or plugin.get('version') != ACTIVE_VERSION:
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
        # Keep each account's existing eight grants; switch only those exact
        # installations to the matching v3 release in this same transaction.
        active_grants=rows(db,"SELECT resource FROM grants WHERE uid=? AND kind='plugin'",(uid,))
        upgrades=[]
        for grant in active_grants:
            pid=grant['resource']
            if pid not in ACTIVE_PLUGIN_IDS:
                continue
            install=db.execute("SELECT i.*,p.enabled AS published FROM installs i JOIN plugins p ON p.id=i.plugin AND p.version=i.version WHERE i.uid=? AND i.plugin=?",(uid,pid)).fetchone()
            release=db.execute("SELECT enabled FROM plugins WHERE id=? AND version=?",(pid,ACTIVE_VERSION)).fetchone()
            binding=db.execute("SELECT 1 FROM plugin_connections WHERE plugin=? AND version=? AND alias='provider'",(pid,ACTIVE_VERSION)).fetchone()
            if not install or not install['enabled'] or not install['published'] or not release or not release['enabled'] or not binding:
                raise ValueError('replacement_not_ready:'+pid)
            if install['version']!=ACTIVE_VERSION:
                upgrades.append(dict(install))
        before={'installs':rows(db,"SELECT * FROM installs WHERE uid=? AND plugin NOT IN ("+','.join('?' for _ in ACTIVE_PLUGIN_IDS)+")",(uid,*sorted(ACTIVE_PLUGIN_IDS))),
                'grants':rows(db,"SELECT * FROM grants WHERE uid=? AND kind='plugin' AND resource NOT IN ("+','.join('?' for _ in ACTIVE_PLUGIN_IDS)+")",(uid,*sorted(ACTIVE_PLUGIN_IDS))),
                'upgrades':upgrades}
        if not before['installs'] and not before['grants'] and not upgrades:
            return {'status':'already_converged','account':uid}
        # Block current execution authority before the complete desired
        # configuration is queued; old v2 and new v3 never apply together.
        block_runtime(store,db,uid,reason='authorization_revoked')
        for old in upgrades:
            db.execute("UPDATE installs SET version=?,previous=? WHERE uid=? AND plugin=?",
                (ACTIVE_VERSION,store.encrypt({'version':old['version'],'enabled':old['enabled'],
                                                'config':store.decrypt(old['config'])}),uid,old['plugin']))
        for value in before['installs']:
            db.execute("UPDATE installs SET enabled=0 WHERE uid=? AND plugin=?",(uid,value['plugin']))
        for value in before['grants']:
            db.execute("DELETE FROM grants WHERE uid=? AND kind='plugin' AND resource=?",(uid,value['resource']))
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
        return {'status':'revoked_waiting_for_runtime_reconcile','account':uid,'receipt':str(receipt_path),'archived_install_count':len(before['installs']),'revoked_grant_count':len(before['grants']),'upgraded_plugin_count':len(upgrades),'apply_job':job.get('id'),'desired_revision':job.get('revision')}


def archive_publications(store):
    with store.tx() as db:
        if db.execute("SELECT 1 FROM grants WHERE kind='plugin' AND resource NOT IN ("+','.join('?' for _ in ACTIVE_PLUGIN_IDS)+")",tuple(sorted(ACTIVE_PLUGIN_IDS))).fetchone():
            raise ValueError('legacy_grants_remain')
        if db.execute("SELECT 1 FROM installs WHERE enabled=1 AND plugin NOT IN ("+','.join('?' for _ in ACTIVE_PLUGIN_IDS)+")",tuple(sorted(ACTIVE_PLUGIN_IDS))).fetchone():
            raise ValueError('legacy_installs_remain')
        for runtime in rows(db,"SELECT applied_spec_ciphertext FROM runtimes"):
            if runtime['applied_spec_ciphertext'] and any(not installable(p['id']) or p.get('version')!=ACTIVE_VERSION for p in store.decrypt(runtime['applied_spec_ciphertext']).get('plugins',[])):
                raise ValueError('legacy_runtime_still_applied')
        releases=[(row['id'],row['version']) for row in rows(db,"SELECT id,version FROM plugins")
                  if not installable(row['id']) or row['version']!=ACTIVE_VERSION]
        for pid,version in releases:
            db.execute("UPDATE plugins SET enabled=0 WHERE id=? AND version=?",(pid,version))
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
        return {'status':'archived','publication_versions':[pid+'@'+version for pid,version in releases],'exclusive_connections_disabled':len(disabled)}



def purge_publications(store):
    """Delete old package rows and files only after all runtimes use v3.

    The complete deployment backup remains outside this active package store.
    Historical Run snapshots and evidence rows are never touched.
    """
    packages=(store.root/'packages').resolve()
    with store.tx() as db:
        legacy=rows(db,"SELECT id,version,path,digest,enabled FROM plugins "
                    "WHERE id NOT IN ("+','.join('?' for _ in ACTIVE_PLUGIN_IDS)+") OR version<>?",
                    (*sorted(ACTIVE_PLUGIN_IDS),ACTIVE_VERSION))
        if any(row['enabled'] for row in legacy):
            raise ValueError('disable_legacy_publications_first')
        if db.execute("SELECT 1 FROM grants WHERE kind='plugin' AND resource NOT IN ("+
                ','.join('?' for _ in ACTIVE_PLUGIN_IDS)+")",tuple(sorted(ACTIVE_PLUGIN_IDS))).fetchone():
            raise ValueError('legacy_grants_remain')
        if db.execute("SELECT 1 FROM installs WHERE enabled=1 AND "
                "(plugin NOT IN ("+','.join('?' for _ in ACTIVE_PLUGIN_IDS)+") OR version<>?)",
                (*sorted(ACTIVE_PLUGIN_IDS),ACTIVE_VERSION)).fetchone():
            raise ValueError('legacy_installs_remain')
        for runtime in rows(db,"SELECT applied_spec_ciphertext FROM runtimes"):
            if runtime['applied_spec_ciphertext'] and any(
                not installable(p['id']) or p.get('version')!=ACTIVE_VERSION
                for p in store.decrypt(runtime['applied_spec_ciphertext']).get('plugins',[])):
                raise ValueError('legacy_runtime_still_applied')
        files=[]
        for row in legacy:
            path=Path(row['path'])
            if path.exists():
                if path.is_symlink() or path.resolve().parent!=packages or path.name!=row['digest']+'.zip':
                    raise ValueError('legacy_package_path_untrusted')
                if hashlib.sha256(path.read_bytes()).hexdigest()!=row['digest']:
                    raise ValueError('legacy_package_digest_changed')
                files.append((str(path),row['digest']))
        legacy_cids=set()
        for row in legacy:
            legacy_cids.update(binding['connection_id'] for binding in rows(db,
                "SELECT connection_id FROM plugin_connections WHERE plugin=? AND version=?",
                (row['id'],row['version'])))
        db.execute("DELETE FROM installs WHERE plugin NOT IN ("+
                   ','.join('?' for _ in ACTIVE_PLUGIN_IDS)+") OR version<>?",
                   (*sorted(ACTIVE_PLUGIN_IDS),ACTIVE_VERSION))
        for row in legacy:
            db.execute("DELETE FROM plugin_connections WHERE plugin=? AND version=?",(row['id'],row['version']))
            db.execute("DELETE FROM plugins WHERE id=? AND version=?",(row['id'],row['version']))
        active_digests={r['digest'] for r in rows(db,"SELECT digest FROM plugins")}
        exclusive=[cid for cid in legacy_cids if not db.execute(
            "SELECT 1 FROM plugin_connections WHERE connection_id=?",(cid,)).fetchone()]
        for cid in exclusive:
            config=db.execute("SELECT config FROM connections WHERE id=?",(cid,)).fetchone()
            if config and not json.loads(config['config']).get('enabled'):
                db.execute("DELETE FROM connections WHERE id=?",(cid,))
        db.execute("INSERT INTO audit(id,actor,actor_role,action,target,result,created) "
                   "VALUES(?,?,'super_admin','eight.plugins.purge','business-data','success',?)",
                   (ident(),'operator',now()))
    removed=[]
    for name,digest in files:
        if digest in active_digests:
            continue
        path=Path(name)
        if path.is_file() and not path.is_symlink() and path.resolve().parent==packages:
            path.unlink()
            removed.append(path.name)
    return {'status':'purged','deleted_releases':len(legacy),
            'deleted_packages':len(set(removed)),'historical_runs_unchanged':True}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('inventory','account','archive','purge'))
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
    elif args.action=='archive':
        result=archive_publications(store)
    else:
        result=purge_publications(store)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
