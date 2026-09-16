from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid

from argon2 import PasswordHasher
from cryptography.fernet import Fernet

SCHEMA_VERSION = 3


def ident():
    return uuid.uuid4().hex


def now():
    return int(time.time())


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, root, key_file, worker_key_file, admin_password_file):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "control.sqlite3"
        self.cipher = Fernet(Path(key_file).read_bytes().strip())
        self.worker_key = Path(worker_key_file).read_text().strip()
        if len(self.worker_key) < 32:
            raise ValueError("Worker credential is invalid")
        self.passwords = PasswordHasher()
        with self.tx() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError("Control database schema is newer than this application")
            schema = """
                CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,must_change INTEGER NOT NULL DEFAULT 0,auth_version INTEGER NOT NULL DEFAULT 1,created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS auth(hash TEXT PRIMARY KEY,uid TEXT NOT NULL,kind TEXT NOT NULL,name TEXT,csrf TEXT,expires INTEGER NOT NULL,version INTEGER NOT NULL,created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS runtimes(uid TEXT PRIMARY KEY,id TEXT UNIQUE NOT NULL,status TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,desired INTEGER NOT NULL DEFAULT 1,reserved INTEGER NOT NULL DEFAULT 1,error TEXT,spec TEXT NOT NULL,updated INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,uid TEXT NOT NULL,action TEXT NOT NULL,status TEXT NOT NULL,revision INTEGER NOT NULL,lease TEXT,heartbeat INTEGER,attempts INTEGER NOT NULL DEFAULT 0,error TEXT,created INTEGER NOT NULL,updated INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created);
                CREATE TABLE IF NOT EXISTS models(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,base_url TEXT NOT NULL,model_id TEXT NOT NULL,secret TEXT NOT NULL,enabled INTEGER NOT NULL,is_default INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS grants(uid TEXT NOT NULL,kind TEXT NOT NULL,resource TEXT NOT NULL,PRIMARY KEY(uid,kind,resource));
                CREATE TABLE IF NOT EXISTS plugins(id TEXT NOT NULL,version TEXT NOT NULL,name TEXT NOT NULL,description TEXT NOT NULL,manifest TEXT NOT NULL,path TEXT NOT NULL,digest TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS installs(uid TEXT NOT NULL,plugin TEXT NOT NULL,version TEXT NOT NULL,enabled INTEGER NOT NULL,config TEXT NOT NULL,previous TEXT,PRIMARY KEY(uid,plugin));
                CREATE TABLE IF NOT EXISTS skills(id TEXT PRIMARY KEY,uid TEXT NOT NULL,name TEXT NOT NULL,description TEXT NOT NULL,content TEXT NOT NULL,enabled INTEGER NOT NULL,version INTEGER NOT NULL,history TEXT NOT NULL,UNIQUE(uid,name));
                CREATE TABLE IF NOT EXISTS templates(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,actor TEXT NOT NULL,action TEXT NOT NULL,target TEXT NOT NULL,created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS files(uid TEXT NOT NULL,id TEXT NOT NULL,metadata TEXT NOT NULL,PRIMARY KEY(uid,id));
            """
            # executescript implicitly commits an existing transaction. Execute the
            # fixed statements separately so schema, roles and auth revoke commit together.
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
            if version < 2:
                self.migrate_roles(db, admin_password_file)
            if version < 3:
                self.migrate_connections(db)
            self.ensure_final_platform(db)
            if not db.execute("SELECT 1 FROM users WHERE role='super_admin'").fetchone():
                raise ValueError("Control database has no super administrator")
            if db.execute("SELECT 1 FROM users WHERE role NOT IN ('super_admin','admin','user')").fetchone():
                raise ValueError("Control database contains an unsupported role")

    def migrate_roles(self, db, admin_password_file):
        columns = {row["name"] for row in db.execute("PRAGMA table_info(audit)")}
        if "actor_role" not in columns:
            db.execute("ALTER TABLE audit ADD COLUMN actor_role TEXT NOT NULL DEFAULT 'unknown'")
        if "result" not in columns:
            db.execute("ALTER TABLE audit ADD COLUMN result TEXT NOT NULL DEFAULT 'success'")
        old_admins = [row[0] for row in db.execute("SELECT id FROM users WHERE role='admin'")]
        for uid in old_admins:
            db.execute("UPDATE users SET role='super_admin',auth_version=auth_version+1 WHERE id=?", (uid,))
            db.execute("DELETE FROM auth WHERE uid=?", (uid,))
        if not db.execute("SELECT 1 FROM users WHERE role='super_admin'").fetchone():
            password = Path(admin_password_file).read_text().strip()
            if len(password) < 16:
                raise ValueError("Administrator bootstrap password is invalid")
            db.execute("INSERT INTO users(id,username,password,role,must_change,created) VALUES(?,?,?,?,0,?)",
                       (ident(), "admin", self.passwords.hash(password), "super_admin", now()))
        db.execute("UPDATE audit SET actor_role=COALESCE((SELECT role FROM users WHERE id=audit.actor),CASE WHEN actor='worker' THEN 'worker' ELSE 'unknown' END) WHERE actor_role='unknown'")
        db.execute("INSERT INTO audit(id,actor,actor_role,action,target,result,created) VALUES(?,?,?,?,?,?,?)",
                   (ident(), "system", "system", "schema.migrate", "control.roles.v2", "success", now()))
        db.execute("PRAGMA user_version=2")

    def migrate_connections(self, db):
        db.execute("CREATE TABLE IF NOT EXISTS connections(id TEXT PRIMARY KEY,config TEXT NOT NULL,secret TEXT NOT NULL,revision INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS plugin_connections(plugin TEXT NOT NULL,version TEXT NOT NULL,alias TEXT NOT NULL,connection_id TEXT NOT NULL REFERENCES connections(id),PRIMARY KEY(plugin,version,alias),FOREIGN KEY(plugin,version) REFERENCES plugins(id,version))")
        db.execute("INSERT INTO audit(id,actor,actor_role,action,target,result,created) VALUES(?,?,?,?,?,?,?)",
                   (ident(), "system", "system", "schema.migrate", "control.connections.v3", "success", now()))
        db.execute("PRAGMA user_version=3")

    def ensure_final_platform(self, db):
        db.execute("UPDATE users SET must_change=0 WHERE must_change<>0")
        db.execute("CREATE TABLE IF NOT EXISTS departments(id TEXT PRIMARY KEY,name TEXT NOT NULL,parent_id TEXT REFERENCES departments(id),code TEXT UNIQUE,sort_order INTEGER NOT NULL DEFAULT 0,created INTEGER NOT NULL,updated INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS user_profiles(uid TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,display_name TEXT NOT NULL DEFAULT '',police_no TEXT UNIQUE,department_id TEXT REFERENCES departments(id),position TEXT NOT NULL DEFAULT '',last_login_at INTEGER)")
        db.execute("CREATE TABLE IF NOT EXISTS model_metadata(model_id TEXT PRIMARY KEY REFERENCES models(id) ON DELETE CASCADE,provider TEXT NOT NULL DEFAULT '',context_length INTEGER NOT NULL DEFAULT 131072,access_mode TEXT NOT NULL DEFAULT 'api',supports_tools INTEGER NOT NULL DEFAULT 1,test_status TEXT NOT NULL DEFAULT 'untested',updated INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS skill_metadata(skill_id TEXT PRIMARY KEY REFERENCES skills(id) ON DELETE CASCADE,source_type TEXT NOT NULL DEFAULT 'manual',dependencies TEXT NOT NULL DEFAULT '[]',input_schema TEXT NOT NULL DEFAULT '{}',default_rules TEXT NOT NULL DEFAULT '[]',scope TEXT NOT NULL DEFAULT 'personal',updated INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS skill_drafts(id TEXT PRIMARY KEY,uid TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,session_id TEXT,source_type TEXT NOT NULL,name TEXT NOT NULL,description TEXT NOT NULL,content TEXT NOT NULL,dependencies TEXT NOT NULL,input_schema TEXT NOT NULL,default_rules TEXT NOT NULL,created INTEGER NOT NULL,updated INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS official_capabilities(id TEXT PRIMARY KEY,kind TEXT NOT NULL,name TEXT NOT NULL,description TEXT NOT NULL,version TEXT NOT NULL,category TEXT NOT NULL,dependencies TEXT NOT NULL,visibility TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,config TEXT NOT NULL DEFAULT '{}',created INTEGER NOT NULL,updated INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,uid TEXT NOT NULL REFERENCES users(id),session_id TEXT NOT NULL,model_id TEXT,query_summary TEXT NOT NULL,mode TEXT NOT NULL,status TEXT NOT NULL,started INTEGER NOT NULL,completed INTEGER,error TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS run_events(id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,sequence INTEGER NOT NULL,step_type TEXT NOT NULL,name TEXT NOT NULL,status TEXT NOT NULL,started INTEGER,completed INTEGER,input_summary TEXT NOT NULL DEFAULT '',output_summary TEXT NOT NULL DEFAULT '',record_count INTEGER,error TEXT,capability_id TEXT,evidence_refs TEXT NOT NULL DEFAULT '[]')")
        db.execute("CREATE TABLE IF NOT EXISTS run_evidence(run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,content TEXT NOT NULL,updated INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS invocations(id TEXT PRIMARY KEY,run_id TEXT NOT NULL UNIQUE REFERENCES runs(id) ON DELETE CASCADE,uid TEXT NOT NULL REFERENCES users(id),department_id TEXT,model_id TEXT,skill_ids TEXT NOT NULL,plugin_ids TEXT NOT NULL,status TEXT NOT NULL,duration_ms INTEGER,record_count INTEGER NOT NULL DEFAULT 0,created INTEGER NOT NULL,error TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS login_events(id TEXT PRIMARY KEY,uid TEXT,username TEXT NOT NULL,result TEXT NOT NULL,client TEXT NOT NULL DEFAULT '',created INTEGER NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS invocations_created ON invocations(created DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS run_events_run ON run_events(run_id,sequence)")

    def schema_version(self):
        with self.tx() as db:
            return db.execute("PRAGMA user_version").fetchone()[0]

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, query, args=()):
        with self.tx() as db:
            return [dict(row) for row in db.execute(query, args)]

    def one(self, query, args=()):
        result = self.rows(query, args)
        return result[0] if result else None

    def encrypt(self, value):
        return self.cipher.encrypt(encode(value).encode()).decode()

    def decrypt(self, value):
        return json.loads(self.cipher.decrypt(value.encode()))

    def audit(self, actor, action, target, *, actor_role=None, result="success"):
        with self.tx() as db:
            role = db.execute("SELECT role FROM users WHERE id=?", (actor,)).fetchone()
            db.execute("INSERT INTO audit(id,actor,actor_role,action,target,result,created) VALUES(?,?,?,?,?,?,?)",
                       (ident(), actor, actor_role or (role[0] if role else "unknown"), action, target, result, now()))

    def set_grants(self, db, uid, kind, values):
        if kind not in ("model", "plugin") or not isinstance(values, list) or len(values) > 100:
            raise ValueError("授权列表格式不正确")
        if any(not isinstance(value, str) or not value or len(value) > 100 for value in values):
            raise ValueError("授权列表格式不正确")
        table = "models" if kind == "model" else "plugins"
        for value in set(values):
            if not db.execute(f"SELECT 1 FROM {table} WHERE id=? AND enabled=1", (value,)).fetchone():
                raise ValueError("授权目标不存在或不可用")
        db.execute("DELETE FROM grants WHERE uid=? AND kind=?", (uid, kind))
        db.executemany("INSERT INTO grants VALUES(?,?,?)", [(uid, kind, value) for value in set(values)])

    def queue(self, uid, action="apply"):
        with self.tx() as db:
            return self.queue_in_transaction(db, uid, action)

    def queue_in_transaction(self, db, uid, action="apply"):
        if action not in ("apply", "pause", "resume", "provision"):
            raise ValueError("环境操作不支持")
        runtime = db.execute("SELECT * FROM runtimes WHERE uid=?", (uid,)).fetchone()
        if not runtime:
            raise ValueError("Environment is not registered")
        desired = runtime["desired"] + (action == "apply")
        existing = db.execute("SELECT * FROM jobs WHERE uid=? AND status IN ('queued','running') ORDER BY created,rowid", (uid,)).fetchall()
        pause = next((job for job in existing if job["action"] == "pause"), None)
        if action == "pause" and pause:
            return dict(pause)
        if action == "apply":
            db.execute("UPDATE runtimes SET desired=?,updated=? WHERE uid=?", (desired, now(), uid))
            if pause:
                return dict(pause)
            # Configuration editing must not silently start an unreserved runtime.
            if not runtime["reserved"]:
                return {"id": None, "uid": uid, "action": action, "status": "deferred", "revision": desired}
            if existing and existing[-1]["action"] in ("apply", "provision", "resume"):
                return dict(existing[-1])
        if existing and action != "pause":
            raise ValueError("该环境正在处理其他操作，请稍后重试")
        if action in ("resume", "provision") and not runtime["reserved"]:
            count = db.execute("SELECT count(*) FROM runtimes WHERE reserved=1").fetchone()[0]
            if count >= int(os.getenv("MAX_RUNTIMES", "4")):
                raise ValueError("运行环境名额已满，请先暂停其他环境")
            db.execute("UPDATE runtimes SET reserved=1 WHERE uid=?", (uid,))
        job_id = ident()
        state = {"apply": "updating", "provision": "provisioning", "resume": "provisioning", "pause": "updating"}[action]
        db.execute("UPDATE runtimes SET desired=?,status=?,error=NULL,updated=? WHERE uid=?", (desired, state, now(), uid))
        db.execute("INSERT INTO jobs(id,uid,action,status,revision,created,updated) VALUES(?,?,?,'queued',?,?,?)",
                   (job_id, uid, action, desired, now(), now()))
        return {"id": job_id, "uid": uid, "action": action, "status": "queued", "revision": desired}

    def update_user(self, uid, data, *, allow_admin=False):
        with self.tx() as db:
            target = db.execute("SELECT role,active FROM users WHERE id=?", (uid,)).fetchone()
            if not target or target["role"] not in (("user", "admin") if allow_admin else ("user",)):
                raise ValueError("可管理的账号不存在")
            if target["role"] == "admin" and set(data) - {"active"}:
                raise ValueError("管理员账号不接受业务授权")
            for kind, key in (("model", "model_ids"), ("plugin", "plugin_ids")):
                if key in data:
                    self.set_grants(db, uid, kind, data[key])
            active = bool(target["active"])
            if "active" in data:
                if not isinstance(data["active"], bool):
                    raise ValueError("账号启用状态必须是布尔值")
                active = data["active"]
                db.execute("UPDATE users SET active=?,auth_version=auth_version+1 WHERE id=?", (active, uid))
                db.execute("DELETE FROM auth WHERE uid=?", (uid,))
            if target["role"] == "admin":
                job = None
            elif active and not target["active"]:
                if db.execute("SELECT 1 FROM jobs WHERE uid=? AND action='pause' AND status IN ('queued','running')", (uid,)).fetchone():
                    raise ValueError("账号停用尚未完成，请等待空间暂停后再启用")
                # Resuming with new grants requires a new immutable config revision.
                if "model_ids" in data or "plugin_ids" in data:
                    db.execute("UPDATE runtimes SET desired=desired+1,updated=? WHERE uid=?", (now(), uid))
                # Account activation, capacity reservation and resume are atomic.
                # A full host or an in-flight job rolls all of them back.
                job = self.queue_in_transaction(db, uid, "resume")
            else:
                if not active and ("model_ids" in data or "plugin_ids" in data):
                    db.execute("UPDATE runtimes SET desired=desired+1,updated=? WHERE uid=?", (now(), uid))
                # Editing an already active but manually paused account never resumes it.
                job = self.queue_in_transaction(db, uid, "apply" if active else "pause")
        return self.user(uid), job

    def user(self, uid):
        user = self.one("SELECT id,username,role,active,must_change AS must_change_password FROM users WHERE id=?", (uid,))
        if user:
            user["active"] = bool(user["active"])
            user["must_change_password"] = bool(user["must_change_password"])
            user["runtime"] = self.one("SELECT id,status,revision,desired,error FROM runtimes WHERE uid=?", (uid,))
            profile = self.one("SELECT display_name,police_no,department_id,position,last_login_at FROM user_profiles WHERE uid=?", (uid,))
            user.update(profile or {"display_name": "", "police_no": None, "department_id": None, "position": "", "last_login_at": None})
            user["system_role"] = user["role"]
            user["department"] = self.one("SELECT id,name,code FROM departments WHERE id=?", (user.get("department_id"),)) if user.get("department_id") else None
        return user

    def create_user(self, username, password, legacy=None, *, model_ids=None, plugin_ids=None, role="user"):
        if role not in ("user", "admin"):
            raise ValueError("账号角色不支持")
        if role == "admin":
            if legacy is not None or model_ids is not None or plugin_ids is not None:
                raise ValueError("管理员账号不接受业务授权或运行环境")
            uid = ident()
            with self.tx() as db:
                if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                    raise ValueError("账号已存在")
                db.execute("INSERT INTO users(id,username,password,role,must_change,created) VALUES(?,?,?,?,0,?)",
                           (uid, username, self.passwords.hash(password), role, now()))
            return self.user(uid), None
        uid, rid = ident(), ident()
        spec = {"gateway_key": secrets.token_urlsafe(48), "agent_password": secrets.token_urlsafe(48), "legacy": legacy}
        with self.tx() as db:
            count = db.execute("SELECT count(*) FROM runtimes WHERE reserved=1").fetchone()[0]
            if count >= int(os.getenv("MAX_RUNTIMES", "4")):
                raise ValueError("运行环境名额已满，请先暂停其他环境")
            if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                raise ValueError("账号已存在")
            db.execute("INSERT INTO users(id,username,password,role,must_change,created) VALUES(?,?,?,'user',0,?)", (uid, username, self.passwords.hash(password), now()))
            self.set_grants(db, uid, "model", [] if model_ids is None else model_ids)
            self.set_grants(db, uid, "plugin", [] if plugin_ids is None else plugin_ids)
            db.execute("INSERT INTO runtimes(uid,id,status,spec,updated) VALUES(?,?,'pending',?,?)", (uid, rid, self.encrypt(spec), now()))
            job_id = ident()
            db.execute("INSERT INTO jobs(id,uid,action,status,revision,created,updated) VALUES(?,?,'provision','queued',1,?,?)", (job_id, uid, now(), now()))
        return self.user(uid), {"id": job_id, "status": "queued"}
