import importlib.util
import hashlib
import json
from pathlib import Path

import pytest

from test_provider_flow import provider, accept
from control import business_runs, trusted_results
from control.theft_provider_state import ProviderState
from shared.theft_provider import fixture_response
from test_trusted_results import enabled, v6
from test_task_spec import task_env
from test_multi_agent import multi
from control import eight_plugin_archive, eight_plugin_publish
from control.data_plugin_policy import ACTIVE_KINDS, ACTIVE_VERSION
from shared.connection_policy import policy
from shared.theft_provider_v2 import CATALOG


def test_eight_release_and_account_convergence(provider, tmp_path):
    store=provider[0]
    uid=provider[4]['uid']
    _,_,historical,snapshot=accept(provider,'incidents')
    state=ProviderState(store)
    operation=state.begin(uid,historical['id'],1)
    assert state.reserve(uid,historical['id'],1,operation,'incidents')
    state.complete(uid,historical['id'],1,operation,'incidents','completed',
        fixture_response('incidents',snapshot['provider_plan']['query']))
    state.finish(uid,historical['id'],1,operation)
    business_runs.set_state(store,historical['id'],'completed','completed')
    history_before=trusted_results.read(store,uid,'ses_multi',historical['id'])
    for kind in ACTIVE_KINDS:
        pid='peixian-theft-'+kind.replace('_','-')
        method,path,group=CATALOG[kind][1:]
        source=group+'-legacy'
        with store.tx() as db:
            current=db.execute('SELECT 1 FROM connections WHERE id=?',(source,)).fetchone()
            if not current:
                paths=[entry[2].replace('{person}','*') for entry in CATALOG.values() if entry[3]==group]
                config=policy({'name':'合成合同来源','base_url':'http://127.0.0.1:19499',
                    'allowed_methods':['GET','POST'],'allowed_paths':paths,
                    'timeout_seconds':10,'max_response_bytes':1048576,
                    'auth_type':'none' if group=='police' else 'bearer','enabled':True})
                db.execute('INSERT INTO connections VALUES(?,?,?,1)',
                    (source,json.dumps(config),store.encrypt('synthetic-test-secret')))
            db.execute('INSERT OR IGNORE INTO plugins VALUES(?,?,?,?,?,?,?,1)',
                (pid,'2.0.0',kind,'',json.dumps({'tools':['peixian_query_'+kind],
                    'connections':{'provider':{}}}),'old','0'*64))
            db.execute('INSERT OR IGNORE INTO plugin_connections VALUES(?,?,?,?)',
                (pid,'2.0.0','provider',source))
            db.execute('UPDATE installs SET version=? WHERE uid=? AND plugin=?',
                ('2.0.0',uid,pid))
    builder=Path(__file__).resolve().parents[3]/'deploy/peixian/examples/theft_provider_v2/build_native.py'
    spec=importlib.util.spec_from_file_location('eight_builder',builder)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    package_folder=tmp_path/'bundles'
    module.build(package_folder)
    published=eight_plugin_publish.publish(store,package_folder)
    assert len(published)==8
    assert eight_plugin_publish.publish(store,package_folder)==published
    for kind in ACTIVE_KINDS:
        pid='peixian-theft-'+kind.replace('_','-')
        row=store.one("SELECT c.config FROM connections c JOIN plugin_connections b ON b.connection_id=c.id "
            "WHERE b.plugin=? AND b.version=?",(pid,ACTIVE_VERSION))
        config=json.loads(row['config'])
        method,path,_=CATALOG[kind][1:]
        assert config['allowed_methods']==[method]
        assert config['allowed_paths']==[path.replace('{person}','*')]
        assert '/health' not in config['allowed_paths']
    with store.tx() as db:
        db.execute("UPDATE jobs SET status='succeeded' WHERE uid=? AND status IN ('queued','running','waiting_capacity')",(uid,))
    granted_before={r['resource'] for r in store.rows(
        "SELECT resource FROM grants WHERE uid=? AND kind='plugin'",(uid,))
        if r['resource'].startswith('peixian-theft-') and r['resource']!='peixian-theft-warnings'}
    receipt=tmp_path/'account.receipt'
    changed=eight_plugin_archive.migrate_account(store,uid,receipt)
    assert changed['upgraded_plugin_count']==len(granted_before)
    assert changed['revoked_grant_count']>0
    assert receipt.exists()
    assert all(row['version']==ACTIVE_VERSION for row in store.rows(
        "SELECT version FROM installs WHERE uid=? AND plugin LIKE 'peixian-theft-%' "
        "AND plugin<>'peixian-theft-warnings'",(uid,)))
    granted_after={r['resource'] for r in store.rows(
        "SELECT resource FROM grants WHERE uid=? AND kind='plugin'",(uid,))}
    assert granted_after==granted_before
    assert not store.one("SELECT 1 FROM grants WHERE uid=? AND kind='plugin' AND resource='sample-records'",(uid,))
    with pytest.raises(ValueError,match='legacy_runtime_still_applied'):
        eight_plugin_archive.archive_publications(store)
    applied=store.decrypt(store.one('SELECT applied_spec_ciphertext FROM runtimes WHERE uid=?',(uid,))['applied_spec_ciphertext'])
    applied['plugins']=[{'id':'peixian-theft-'+kind.replace('_','-'),'version':ACTIVE_VERSION,
        'manifest':{'tools':['peixian_query_'+kind]}} for kind in ACTIVE_KINDS]
    with store.tx() as db:
        db.execute('UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?',(store.encrypt(applied),uid))
    archived=eight_plugin_archive.archive_publications(store)
    assert archived['status']=='archived'
    assert not any(row["enabled"] for row in store.rows("SELECT enabled FROM plugins WHERE id NOT LIKE 'peixian-theft-%'"))
    old_blob=b'legacy-test-package'
    old_digest=hashlib.sha256(old_blob).hexdigest()
    old_path=store.root/'packages'/(old_digest+'.zip')
    old_path.write_bytes(old_blob)
    with store.tx() as db:
        db.execute("UPDATE plugins SET path=?,digest=? WHERE id=? AND version='1.0.0'",
            (str(old_path),old_digest,'peixian-theft-incidents'))
    purged=eight_plugin_archive.purge_publications(store)
    assert purged['deleted_releases']>0 and purged['deleted_packages']==1
    assert not old_path.exists()
    assert {r['id'] for r in store.rows("SELECT id FROM plugins")}=={
        'peixian-theft-'+kind.replace('_','-') for kind in ACTIVE_KINDS}
    assert not store.one("SELECT 1 FROM installs WHERE uid=? AND plugin='peixian-theft-warnings'",(uid,))
    assert not store.one("SELECT 1 FROM plugins WHERE id='peixian-theft-tracks' AND version='2.0.0'")
    assert store.one("SELECT enabled FROM plugins WHERE id='peixian-theft-tracks' AND version='3.0.0'")['enabled']==1
    assert trusted_results.read(store,uid,'ses_multi',historical['id'])==history_before
