from contextlib import contextmanager, suppress
from pathlib import Path
import hashlib
import json
import os
import secrets
import sqlite3
import time
import threading
import uuid

from argon2 import PasswordHasher, extract_parameters
from cryptography.fernet import Fernet

SCHEMA_VERSION = 4  # Legacy initialization remains v4 unless on_demand is explicit.
MAX_SCHEMA_VERSION = 11


def ident():
    return uuid.uuid4().hex


def now():
    return int(time.time())


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, root, key_file, worker_key_file, admin_password_file, *, runtime_mode=None, runtime_pool=None):
        from shared.runtime_pool_config import validate as pool_config
        self.pool_settings = pool_config(runtime_pool or {})
        self._idle_started = now()
        if runtime_mode not in (None, "eager", "on_demand"):
            raise ValueError("Unsupported runtime mode")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "control.sqlite3"
        raw_busy = os.getenv("PX_DB_BUSY_MS", "1000")
        if not raw_busy.isascii() or not raw_busy.isdecimal() or not 1 <= int(raw_busy) <= 1000:
            raise ValueError("PX_DB_BUSY_MS must be an integer between 1 and 1000")
        self.busy_timeout_ms = int(raw_busy)
        self.cipher = Fernet(Path(key_file).read_bytes().strip())
        self.worker_key = Path(worker_key_file).read_text().strip()
        if len(self.worker_key) < 32:
            raise ValueError("Worker credential is invalid")
        self.passwords = PasswordHasher()
        self._transaction_local = threading.local()
        self._initialize_wal()
        with self.tx() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            fresh = version == 0 and not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
            if version > MAX_SCHEMA_VERSION:
                raise ValueError("Control database schema is newer than this application")
            if version in (4, 5, 6, 7, 8):
                from .schema import validate
                validate(db)
            schema = """
                CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,must_change INTEGER NOT NULL DEFAULT 1,auth_version INTEGER NOT NULL DEFAULT 1,created INTEGER NOT NULL);
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
            if not db.execute("SELECT 1 FROM users WHERE role='super_admin'").fetchone():
                raise ValueError("Control database has no super administrator")
            if db.execute("SELECT 1 FROM users WHERE role NOT IN ('super_admin','admin','user')").fetchone():
                raise ValueError("Control database contains an unsupported role")
            from .migrations_v4 import migrate
            from .schema import validate
            if version < 4:
                migrate(self, db, fresh=fresh, timestamp=now())
            else:
                validate(db)
            if version < 5 and runtime_mode == "on_demand":
                from .migrations_v5 import migrate as migrate_pool
                migrate_pool(db, fresh=fresh, timestamp=now(), mode=runtime_mode)
            policy = self.maintenance_status(db)
            actual_mode = policy.get("runtime_mode", "eager")
            if runtime_mode is not None and runtime_mode != actual_mode:
                raise ValueError("Runtime policy differs from the initialized database")
            if runtime_pool is not None:
                wanted = self.pool_settings['capacity_wait_enabled']
                actual = bool(policy.get('capacity_wait_enabled', False))
                if wanted != actual:
                    if actual_mode != 'on_demand':
                        raise ValueError('Runtime waiting requires on-demand mode')
                    if not fresh and (os.getenv('PX_ALLOW_POOL_POLICY_CHANGE') != '1'
                            or policy['maintenance_mode'] != 'frozen'
                            or db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') OR recovery_required=1").fetchone()
                            or db.execute("SELECT 1 FROM job_attempts WHERE outcome IS NULL").fetchone()):
                        raise ValueError('Waiting policy change requires frozen offline approval')
                    # Disabling admission retains the newer policy identity and
                    # existing waiters for status, cancellation and expiry cleanup.
                    db.execute("UPDATE platform_state SET capacity_wait_enabled=?,pool_policy_version=MAX(pool_policy_version,2) WHERE id=1", (int(wanted),))
                idle = self.pool_settings['idle_pause_enabled']
                if idle != bool(policy.get('idle_pause_enabled', False)):
                    if actual_mode != 'on_demand' or (not fresh and (os.getenv('PX_ALLOW_POOL_POLICY_CHANGE') != '1'
                            or policy['maintenance_mode'] != 'frozen'
                            or db.execute("SELECT 1 FROM jobs WHERE (status IN ('queued','running') AND reason<>'idle_timeout') OR recovery_required=1").fetchone())):
                        raise ValueError('Idle policy change requires frozen offline approval')
                    db.execute('UPDATE platform_state SET idle_pause_enabled=?,pool_policy_version=3 WHERE id=1',(int(idle),))
                validate(db)

            if db.execute("PRAGMA user_version").fetchone()[0] < 6 and os.getenv("PX_BACKEND_V6") == "1":
                from .migrations_v6 import migrate as backend_migrate
                backend_migrate(db, fresh=fresh, timestamp=now())
            if db.execute("PRAGMA user_version").fetchone()[0]<7 and os.getenv('PX_TASK_CONTEXT_V1')=='1':
                from .migrations_v7 import migrate as context_migrate
                context_migrate(db,fresh=fresh,timestamp=now())
            if db.execute("PRAGMA user_version").fetchone()[0] == 7 and os.getenv("PX_TASK_CLARIFICATION_V1") == "1":
                from .migrations_v8 import migrate as clarification_migrate
                clarification_migrate(db, fresh=fresh, timestamp=now())

            if db.execute("PRAGMA user_version").fetchone()[0] == 8 and os.getenv("PX_TRUSTED_RESULT_V2") == "1":
                from .migrations_v9 import migrate
                migrate(db, fresh=fresh, timestamp=now())
            if db.execute('PRAGMA user_version').fetchone()[0] == 9 and os.getenv('PX_OWNER_REVIEWS_V1') == '1':
                from .migrations_v10 import migrate
                migrate(db,fresh=fresh,timestamp=now())
            if db.execute('PRAGMA user_version').fetchone()[0] == 10 and os.getenv('PX_ANALYSIS_TASKS_V1') == '1':
                from .migrations_v11 import migrate
                migrate(db,fresh=fresh,timestamp=now())
            validate(db)


    def on_demand(self, db=None):
        return self.maintenance_status(db).get("runtime_mode", "eager") == "on_demand"

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
            db.execute("INSERT INTO users(id,username,password,role,created) VALUES(?,?,?,?,?)",
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

    def _connect(self, *, readonly=False):
        target = self.path.resolve().as_uri() + "?mode=ro" if readonly else self.path
        db = sqlite3.connect(target, timeout=self.busy_timeout_ms / 1000,
                             isolation_level=None, uri=readonly,
                             autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            if readonly:
                db.execute("PRAGMA query_only=ON")
            return db
        except BaseException:
            self._abort_connection(db)
            raise

    @staticmethod
    def _abort_connection(db):
        # Cleanup must preserve the original setup/transaction error.
        with suppress(sqlite3.Error):
            if db.in_transaction:
                db.execute("ROLLBACK")
        with suppress(sqlite3.Error):
            db.close()

    def _initialize_wal(self):
        db = self._connect()
        try:
            if db.execute("PRAGMA user_version").fetchone()[0] > MAX_SCHEMA_VERSION:
                raise ValueError("Control database schema is newer than this application")
            mode = db.execute("PRAGMA journal_mode").fetchone()[0]
            if mode.lower() != "wal":
                mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode.lower() != "wal":
                raise ValueError("Control database requires WAL journal mode")
        except BaseException:
            self._abort_connection(db)
            raise
        else:
            db.close()

    def schema_version(self):
        with self.read() as db:
            return db.execute("PRAGMA user_version").fetchone()[0]

    @contextmanager
    def read(self, *, snapshot=False):
        active = getattr(self._transaction_local, "db", None)
        if active is not None:
            yield active
            return
        db = self._connect(readonly=True)
        try:
            if snapshot:
                db.execute("BEGIN")
            yield db
            if snapshot:
                db.execute("COMMIT")
        except BaseException:
            self._abort_connection(db)
            raise
        else:
            db.close()

    @contextmanager
    def tx(self):
        active = getattr(self._transaction_local, "db", None)
        if active is not None:
            yield active
            return
        db = self._connect()
        self._transaction_local.after = []
        try:
            # Keep BEGIN inside the cleanup scope: busy can fail before yielding.
            db.execute("BEGIN IMMEDIATE")
            self._transaction_local.db = db
            yield db
            db.execute("COMMIT")
        except BaseException:
            self._abort_connection(db)
            self._transaction_local.after = []
            raise
        else:
            db.close()
        finally:
            self._transaction_local.db = None
        callbacks, self._transaction_local.after = self._transaction_local.after, []
        for callback in callbacks:
            with suppress(Exception):
                callback()

    atomic_request = tx

    def after_commit(self, callback):
        """Run callback once the outermost transaction commits; immediately when none is open."""
        if getattr(self._transaction_local, "db", None) is None:
            with suppress(Exception):
                callback()
            return
        self._transaction_local.after.append(callback)

    def rows(self, query, args=()):
        with self.read() as db:
            return [dict(row) for row in db.execute(query, args)]

    def one(self, query, args=()):
        with self.read() as db:
            row = db.execute(query, args).fetchone()
            return dict(row) if row is not None else None

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
        if kind == "plugin":
            from .data_plugin_policy import installable
            if any(not installable(value) for value in values):
                raise ValueError("资料插件已归档，不可新增授权")
        table = "models" if kind == "model" else "plugins"
        for value in set(values):
            if not db.execute(f"SELECT 1 FROM {table} WHERE id=? AND enabled=1", (value,)).fetchone():
                raise ValueError("授权目标不存在或不可用")
        previous = {row[0] for row in db.execute("SELECT resource FROM grants WHERE uid=? AND kind=?", (uid, kind))}
        if previous - set(values):
            from .runtime_security import block_runtime
            block_runtime(self, db, uid, reason="authorization_revoked")
        db.execute("DELETE FROM grants WHERE uid=? AND kind=?", (uid, kind))
        db.executemany("INSERT INTO grants VALUES(?,?,?)", [(uid, kind, value) for value in set(values)])

    def queue(self, uid, action="apply", **kwargs):
        with self.tx() as db:
            return self.queue_in_transaction(db, uid, action, **kwargs)

    def queue_in_transaction(self, db, uid, action="apply", *, reason="normal", bump_desired=True):
        if action not in ("apply", "pause", "resume", "provision"):
            raise ValueError("环境操作不支持")
        runtime = db.execute("SELECT * FROM runtimes WHERE uid=?", (uid,)).fetchone()
        if not runtime:
            raise ValueError("Environment is not registered")
        if self.on_demand(db) and action in ("resume", "provision"):
            from .runtime_pool import start
            return start(self, db, uid, admin=reason == "admin_resume")["job"]
        if self.on_demand(db) and action == "pause":
            from .runtime_pool import stop
            return stop(self, db, uid, reason=reason)["job"]
        platform = self.maintenance_status(db)
        metadata_apply = action == "apply" and self.on_demand(db) and not runtime["reserved"]
        if action != "pause" and (platform["maintenance_mode"] != "normal" or (not platform["capacity_healthy"] and not metadata_apply)):
            raise ValueError("平台维护或容量核对中，暂不接受新环境操作")
        desired = runtime["desired"] + (action == "apply" and bump_desired)
        existing = db.execute("SELECT * FROM jobs WHERE uid=? AND status IN ('queued','running') ORDER BY created,rowid", (uid,)).fetchall()
        pause = next((job for job in existing if job["action"] == "pause"), None)
        if action == "pause" and pause:
            return dict(pause)
        if action == "pause":
            db.execute("UPDATE jobs SET status='cancelled',phase='finished',cancel_requested=1,updated=? WHERE uid=? AND action<>'pause' AND status='queued' AND recovery_required=0", (now(), uid))
        if action == "apply":
            db.execute("UPDATE runtimes SET desired=?,updated=?,state_version=state_version+1 WHERE uid=?", (desired, now(), uid))
            if pause:
                return dict(pause)
            # Configuration editing must not silently start an unreserved runtime.
            if not runtime["reserved"]:
                return {"id": None, "uid": uid, "action": action, "status": "deferred", "revision": desired}
            if existing and existing[-1]["action"] in ("apply", "provision", "resume"):
                return dict(existing[-1])
        if existing and action != "pause":
            raise ValueError("该环境正在处理其他操作，请稍后重试")
        if action == "resume" and reason == "normal":
            # Explicit administrator resume retires its own prior pause intent.
            # Neither apply completion nor a security-blocked start may do this.
            db.execute("UPDATE runtimes SET stop_reason='none' WHERE uid=? AND stop_reason='admin' AND security_blocked=0", (uid,))
        if action in ("resume", "provision") and not runtime["reserved"]:
            count = db.execute("SELECT count(*) FROM runtimes WHERE reserved=1").fetchone()[0]
            if count >= int(os.getenv("MAX_RUNTIMES", "4")):
                raise ValueError("运行环境名额已满，请先暂停其他环境")
            db.execute("UPDATE runtimes SET reserved=1 WHERE uid=?", (uid,))
        job_id = ident()
        state = runtime["status"] if action == "apply" else "draining" if action == "pause" else "provisioning"
        db.execute("UPDATE runtimes SET desired=?,status=?,error=NULL,updated=?,state_version=state_version+1 WHERE uid=?", (desired, state, now(), uid))
        if action == "pause":
            db.execute("UPDATE runtimes SET gate_policy='closed',stop_reason=CASE WHEN security_blocked=1 THEN stop_reason ELSE ? END WHERE uid=?", ("admin" if reason == "normal" else reason, uid))
        db.execute("INSERT INTO jobs(id,uid,action,status,revision,reason,created,updated) VALUES(?,?,?,'queued',?,?,?,?)",
                   (job_id, uid, action, desired, reason, now(), now()))
        return {"id": job_id, "uid": uid, "action": action, "status": "queued", "revision": desired}

    def ensure_apply_job(self, db, uid):
        runtime = db.execute("SELECT * FROM runtimes WHERE uid=?", (uid,)).fetchone()
        if not runtime or not runtime["reserved"] or runtime["desired"] <= runtime["revision"]:
            return None
        existing = db.execute("SELECT * FROM jobs WHERE uid=? AND status IN ('queued','running') ORDER BY enqueue_seq", (uid,)).fetchall()
        if existing:
            return dict(existing[-1])
        job_id = ident()
        db.execute("INSERT INTO jobs(id,uid,action,status,revision,created,updated) VALUES(?,?,'apply','queued',?,?,?)", (job_id, uid, runtime["desired"], now(), now()))
        return {"id": job_id, "uid": uid, "action": "apply", "status": "queued", "revision": runtime["desired"]}

    def ensure_recovery_job(self, db, uid):
        """Recover unexpected restarts from verified applied state, never desired state."""
        runtime = db.execute("SELECT * FROM runtimes WHERE uid=?", (uid,)).fetchone()
        if (not runtime or not runtime["recovery_required"] or not runtime["reserved"]
                or not runtime["applied_spec_ciphertext"] or not runtime["applied_spec_digest"]):
            return None
        existing = db.execute("SELECT * FROM jobs WHERE uid=? AND (status='running' OR recovery_required=1 OR (status='queued' AND action='pause')) ORDER BY enqueue_seq LIMIT 1", (uid,)).fetchone()
        if existing:
            return dict(existing)
        job_id = ident()
        db.execute("INSERT INTO jobs(id,uid,action,status,phase,revision,reason,recovery_required,created,updated) VALUES(?,?,'apply','queued','reconciling',?,'runtime_reconcile',1,?,?)",
                   (job_id, uid, runtime["revision"], now(), now()))
        return {"id": job_id, "uid": uid, "action": "apply", "status": "queued", "revision": runtime["revision"]}

    def maintenance_status(self, db=None):
        if db is None:
            with self.read() as db:
                return self.maintenance_status(db)
        row = db.execute("SELECT * FROM platform_state WHERE id=1").fetchone()
        if row is None:
            raise ValueError("平台维护状态缺失")
        return dict(row)

    def set_maintenance(self, mode, expected_state_version, actor):
        from .orchestration import Orchestration
        return Orchestration(self).maintenance(mode, expected_state_version, actor)

    def release_capacity_and_promote(self, db, uid, *, expected_state_version, job_id, attempt, observation_id, operation_id):
        from .orchestration import Orchestration
        return Orchestration(self).release(db, uid, expected_state_version=expected_state_version,
                                           job_id=job_id, attempt=attempt, observation_id=observation_id, operation_id=operation_id)

    def resolve_drain(self, uid, action, actor):
        from .orchestration import Orchestration
        return Orchestration(self).resolve_drain(uid, action, actor)

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
                if not active and target["role"] == "user":
                    from .runtime_security import block_runtime
                    block_runtime(self, db, uid, reason="account_disabled")
            if target["role"] == "admin":
                job = None
            elif self.on_demand(db):
                from .runtime_pool import identity_updated
                job = identity_updated(self, db, uid, data, active)
            elif active and not target["active"]:
                if db.execute("SELECT 1 FROM jobs WHERE uid=? AND action='pause' AND status IN ('queued','running')", (uid,)).fetchone():
                    raise ValueError("账号停用尚未完成，请等待空间暂停后再启用")
                # Resuming with new grants requires a new immutable config revision.
                if "model_ids" in data or "plugin_ids" in data:
                    db.execute("UPDATE runtimes SET desired=desired+1,updated=? WHERE uid=?", (now(), uid))
                db.execute("UPDATE runtimes SET stop_reason='none',security_blocked=0,security_intent_id=NULL,cancellation_confirmed=0,state_version=state_version+1,gate_policy='closed' WHERE uid=? AND status IN ('paused','failed') AND reserved=0", (uid,))
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
        with self.read(snapshot=True) as db:
            row = db.execute("SELECT id,username,role,active,must_change AS must_change_password FROM users WHERE id=?", (uid,)).fetchone()
            if row is None:
                return None
            user = dict(row)
            user["active"] = bool(user["active"])
            user["must_change_password"] = bool(user["must_change_password"])
            runtime = db.execute("SELECT id,status,revision,desired,error,security_blocked,recovery_required,gate_policy,cancellation_confirmed FROM runtimes WHERE uid=?", (uid,)).fetchone()
            user["runtime"] = dict(runtime) if runtime is not None else None
            if user["runtime"]:
                for name in ("security_blocked", "recovery_required", "cancellation_confirmed"):
                    user["runtime"][name] = bool(user["runtime"][name])
                job = db.execute("SELECT phase FROM jobs WHERE uid=? AND status IN ('queued','running') ORDER BY CASE WHEN status='running' THEN 0 ELSE 1 END,enqueue_seq LIMIT 1", (uid,)).fetchone()
                user["runtime"]["phase"] = job["phase"] if job else None
                from .runtime_view import interaction_view
                user['runtime'].update(interaction_view(user['runtime'], user['active'],
                    self.maintenance_status(db)['maintenance_mode'], user['runtime']['phase']))
                if self.on_demand(db):
                    from .runtime_pool import public_status
                    user["runtime"].update(public_status(self, db, uid))
            if db.execute("PRAGMA user_version").fetchone()[0] >= 6:
                from .backend_contract import profile
                user.update(profile(db, uid))
            user["system_role"] = user["role"]
            return user

    def create_browser_auth(self, uid, *, expected_password, expected_auth_version,
                            token_hash, csrf, expires):
        with self.tx() as db:
            user = db.execute("SELECT active,password,auth_version FROM users WHERE id=?", (uid,)).fetchone()
            if (user is None or not user["active"] or user["password"] != expected_password
                    or user["auth_version"] != expected_auth_version):
                return False
            db.execute("INSERT INTO auth VALUES(?,?,?,?,?,?,?,?)",
                       (token_hash, uid, "session", "browser", csrf, expires, expected_auth_version, now()))
            if db.execute("PRAGMA user_version").fetchone()[0] >= 6:
                db.execute("INSERT INTO user_profiles(uid,last_login) VALUES(?,?) ON CONFLICT(uid) DO UPDATE SET last_login=excluded.last_login", (uid,now()))
            return True

    def change_password(self, uid, *, expected_password, expected_auth_version,
                        session_hash, new_password_hash):
        extract_parameters(new_password_hash)
        with self.tx() as db:
            user = db.execute("SELECT active,password,auth_version FROM users WHERE id=?", (uid,)).fetchone()
            auth = db.execute("SELECT uid,version,expires FROM auth WHERE hash=?", (session_hash,)).fetchone()
            if (user is None or not user["active"] or user["password"] != expected_password
                    or user["auth_version"] != expected_auth_version or auth is None
                    or auth["uid"] != uid or auth["version"] != expected_auth_version or auth["expires"] < now()):
                return False
            version = expected_auth_version + 1
            db.execute("UPDATE users SET password=?,must_change=0,auth_version=? WHERE id=?",
                       (new_password_hash, version, uid))
            db.execute("DELETE FROM auth WHERE uid=? AND hash<>?", (uid, session_hash))
            db.execute("UPDATE auth SET version=? WHERE hash=?", (version, session_hash))
            return True

    def create_user(self, username, password, legacy=None, *, model_ids=None, plugin_ids=None, role="user"):
        password_hash = self.passwords.hash(password)
        return self.create_user_prehashed(username, password_hash, legacy,
                                          model_ids=model_ids, plugin_ids=plugin_ids, role=role)

    def create_user_prehashed(self, username, password_hash, legacy=None, *, model_ids=None, plugin_ids=None, role="user", authorize=None):
        """Internal entry after the bounded crypto executor; never accept a hash from HTTP."""
        extract_parameters(password_hash)
        if role not in ("user", "admin"):
            raise ValueError("账号角色不支持")
        if role == "admin":
            if legacy is not None or model_ids is not None or plugin_ids is not None:
                raise ValueError("管理员账号不接受业务授权或运行环境")
            uid = ident()
            with self.tx() as db:
                if authorize is not None:
                    authorize(db)
                if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                    raise ValueError("账号已存在")
                db.execute("INSERT INTO users(id,username,password,role,created) VALUES(?,?,?,?,?)",
                           (uid, username, password_hash, role, now()))
            return self.user(uid), None
        uid, rid = ident(), ident()
        spec = {"gateway_key": secrets.token_urlsafe(48), "agent_password": secrets.token_urlsafe(48),
                "runtime_key": secrets.token_urlsafe(48), "relay_management_key": secrets.token_urlsafe(48), "legacy": legacy}
        with self.tx() as db:
            if authorize is not None:
                authorize(db)
            platform = self.maintenance_status(db)
            on_demand = self.on_demand(db)
            if on_demand and legacy is not None:
                raise ValueError("按需注册不接受旧环境接管参数")
            if platform["maintenance_mode"] != "normal" or (not on_demand and not platform["capacity_healthy"]):
                raise ValueError("平台维护或容量核对中，暂不接受新环境操作")
            count = db.execute("SELECT count(*) FROM runtimes WHERE reserved=1").fetchone()[0]
            if not on_demand and count >= int(os.getenv("MAX_RUNTIMES", "4")):
                raise ValueError("运行环境名额已满，请先暂停其他环境")
            if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                raise ValueError("账号已存在")
            db.execute("INSERT INTO users(id,username,password,role,created) VALUES(?,?,?,'user',?)", (uid, username, password_hash, now()))
            self.set_grants(db, uid, "model", [] if model_ids is None else model_ids)
            self.set_grants(db, uid, "plugin", [] if plugin_ids is None else plugin_ids)
            if on_demand:
                db.execute("INSERT INTO runtimes(uid,id,status,reserved,stop_reason,spec,updated) VALUES(?,?,'unprovisioned',0,'unprovisioned',?,?)", (uid, rid, self.encrypt(spec), now()))
                job = None
            else:
                db.execute("INSERT INTO runtimes(uid,id,status,spec,updated) VALUES(?,?,'pending',?,?)", (uid, rid, self.encrypt(spec), now()))
                job_id = ident()
                db.execute("INSERT INTO jobs(id,uid,action,status,revision,created,updated) VALUES(?,?,'provision','queued',1,?,?)", (job_id, uid, now(), now()))
                job = {"id": job_id, "status": "queued"}
        return self.user(uid), job
