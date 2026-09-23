"""Publish exactly eight immutable v3 data bundles with per-interface egress bindings.

Operator-only. Run after a complete private backup, first against a database
copy. Existing v2 connection credentials stay in the encrypted Control store.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

from .data_plugin_policy import ACTIVE_KINDS, valid_bundle
from .store import encode, ident, now
from shared.connection_policy import policy
from shared.theft_provider_v2 import CATALOG

VERSION='3.0.0'


def publish(store, folder):
    folder=Path(folder)
    prepared=[]
    for kind in ACTIVE_KINDS:
        pid='peixian-theft-'+kind.replace('_','-')
        path=folder/(pid+'-'+VERSION+'.zip')
        raw=path.read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if set(archive.namelist())!={'manifest.json','entry.mjs'}:
                raise ValueError('unexpected_bundle_files')
            manifest=json.loads(archive.read('manifest.json'))
        if not valid_bundle(manifest) or manifest['id']!=pid or manifest['version']!=VERSION:
            raise ValueError('bundle_identity_mismatch')
        prepared.append((kind,pid,raw,digest,manifest))
    output=[]
    with store.tx() as db:
        for kind,pid,raw,digest,manifest in prepared:
            source=db.execute(
                "SELECT c.config,c.secret FROM connections c JOIN plugin_connections b ON b.connection_id=c.id "
                "WHERE b.plugin=? AND b.version='2.0.0' AND b.alias='provider'",(pid,)).fetchone()
            if not source:
                raise ValueError('previous_connection_missing:'+pid)
            prior=json.loads(source['config'])
            method,upstream,group=CATALOG[kind][1:]
            if not prior.get('enabled') or method not in prior.get('allowed_methods',[]):
                raise ValueError('previous_connection_disabled:'+pid)
            target_path=upstream.replace('{person}','*')
            connection=policy({**{k:v for k,v in prior.items() if k!='request_rules'},
                'name':manifest['name']+'专属连接','allowed_methods':[method],
                'allowed_paths':[target_path]})
            cid=hashlib.sha256(('native-eight-v3:'+pid).encode()).hexdigest()[:32]
            existing=db.execute('SELECT config,secret FROM connections WHERE id=?',(cid,)).fetchone()
            if existing and (existing['config']!=encode(connection) or existing['secret']!=source['secret']):
                raise ValueError('connection_identity_conflict:'+pid)
            package=store.root/'packages'/(digest+'.zip')
            package.parent.mkdir(exist_ok=True)
            if package.exists() and hashlib.sha256(package.read_bytes()).hexdigest()!=digest:
                raise ValueError('package_digest_conflict:'+pid)
            if not package.exists():
                package.write_bytes(raw)
                package.chmod(0o644)
            prior_release=db.execute('SELECT digest FROM plugins WHERE id=? AND version=?',(pid,VERSION)).fetchone()
            if prior_release and prior_release['digest']!=digest:
                raise ValueError('immutable_release_conflict:'+pid)
            db.execute('INSERT OR IGNORE INTO plugins VALUES(?,?,?,?,?,?,?,1)',
                (pid,VERSION,manifest['name'],manifest['description'],encode(manifest),str(package),digest))
            db.execute('INSERT OR IGNORE INTO connections VALUES(?,?,?,1)',
                (cid,encode(connection),source['secret']))
            binding=db.execute(
                "SELECT connection_id FROM plugin_connections WHERE plugin=? AND version=? AND alias='provider'",
                (pid,VERSION)).fetchone()
            if binding and binding['connection_id']!=cid:
                raise ValueError('binding_identity_conflict:'+pid)
            db.execute('INSERT OR IGNORE INTO plugin_connections VALUES(?,?,?,?)',
                (pid,VERSION,'provider',cid))
            output.append({'id':pid,'version':VERSION,'sha256':digest})
        db.execute("INSERT INTO audit(id,actor,actor_role,action,target,result,created) "
                   "VALUES(?,?,'super_admin','eight.plugins.publish','business-data','success',?)",
                   (ident(),'operator',now()))
    return output


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--packages',required=True,type=Path)
    args=parser.parse_args()
    from .settings import configured_store
    print(json.dumps({'published':publish(configured_store(),args.packages)},ensure_ascii=False))


if __name__=='__main__':
    main()
