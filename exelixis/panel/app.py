"""Exelixisnet IT Support panel — multi-tenant.

Each tenant is a separate support business (brand, RustDesk server, customers,
technicians and computers). Tenants are fully isolated: a technician only ever
sees and connects to computers in their own tenant. Customer PCs running a
tenant's QuickSupport app register here with that tenant's enrollment token;
technicians sign in under their tenant's branded page at /t/<slug>.

The platform owner (a user with the "superadmin" flag) can create and manage
tenants from the Platform console. ExelixisHub and the MikroTik monitor read
the platform owner's own tenant through the /api/hub endpoints with an API key.
"""
import base64
import binascii
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Optional
from urllib.parse import quote

import pyotp
import qrcode
import qrcode.image.svg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# --- configuration (environment) -------------------------------------------
DB_PATH = os.environ.get("PANEL_DB", "/data/panel.db")
SESSION_SECRET = os.environ["PANEL_SESSION_SECRET"].encode()
FERNET = Fernet(os.environ["PANEL_FERNET_KEY"].encode())
ENROLL_TOKEN = os.environ["PANEL_ENROLL_TOKEN"]          # the default tenant's token
HUB_API_KEY = os.environ.get("PANEL_HUB_API_KEY", "")
MONITOR_API_KEY = os.environ.get("PANEL_MONITOR_API_KEY", "")
APP_URI = os.environ.get("PANEL_APP_URI", "exsupport")
if APP_URI == "exelixisnetitsupport":
    APP_URI = "exsupport"
# The platform owner's own tenant — the one existing data migrates into, and the
# one the root URL and the Hub API map to.
DEFAULT_SLUG = os.environ.get("PANEL_DEFAULT_TENANT", "exelixis")
DEFAULT_NAME = os.environ.get("PANEL_DEFAULT_NAME", "Exelixisnet IT Support")
DEFAULT_RD_ID_SERVER = os.environ.get("PANEL_RD_ID_SERVER", "rustdesk.exelixisnet.gr")
DEFAULT_RD_RELAY = os.environ.get("PANEL_RD_RELAY", os.environ.get("PANEL_RD_ID_SERVER", ""))
DEFAULT_RD_KEY = os.environ.get("PANEL_RD_KEY", "")
ONLINE_SECONDS = int(os.environ.get("PANEL_ONLINE_SECONDS", "180"))
SESSION_HOURS = int(os.environ.get("PANEL_SESSION_HOURS", "12"))
# An open support session whose computer stopped heart-beating (went offline) or
# that has run past this cap is auto-closed, so a force-closed/crashed app does
# not leave a session "in progress" forever.
MAX_SESSION_SECONDS = int(os.environ.get("PANEL_MAX_SESSION_HOURS", "12")) * 3600
COOKIE_SECURE = os.environ.get("PANEL_COOKIE_SECURE", "1") == "1"
ISSUER = "Exelixisnet IT Support"
CHANGELOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "CHANGELOG.md")

# --- exUpdates (central updates/deploy manager) -----------------------------
# When EXUPDATES_URL is set, the panel registers itself with exUpdates
# (updates.exelixisnet.eu): it heart-beats its version and status, and learns
# whether a newer panel version is available. Unset = disabled, nothing changes.
EXUPDATES_URL = os.environ.get("EXUPDATES_URL", "").rstrip("/")
EXUPDATES_KEY = os.environ.get("EXUPDATES_KEY", "")
EXUPDATES_APP_ID = os.environ.get("EXUPDATES_APP_ID", "exsupport-panel")
EXUPDATES_INSTANCE = os.environ.get("EXUPDATES_INSTANCE", DEFAULT_SLUG)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _read_changelog() -> str:
    try:
        with open(CHANGELOG_PATH, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _version_from_changelog(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("## "):
            return line[3:].split()[0]
    return "unknown"


PANEL_VERSION = _version_from_changelog(_read_changelog())
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = FastAPI(title="Exelixisnet IT Support panel", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
_db_lock = threading.Lock()


# --- database ----------------------------------------------------------------
@contextmanager
def db():
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


# Stable "latest release" links for the platform owner's own apps.
_REL = "https://github.com/kpap235/rustdesk/releases/latest/download"
DEFAULT_DOWNLOADS = {
    "download_exsupport": f"{_REL}/exSupport.exe",
    "download_quick": f"{_REL}/exQuickSupport.exe",
    "download_android": f"{_REL}/exQuickSupport.apk",
}


def _tenants_schema(c) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            phone TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            website TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            hours TEXT NOT NULL DEFAULT '',
            gdpr_text TEXT NOT NULL DEFAULT '',
            consent_text TEXT NOT NULL DEFAULT '',
            id_server TEXT NOT NULL DEFAULT '',
            relay_server TEXT NOT NULL DEFAULT '',
            rd_key TEXT NOT NULL DEFAULT '',
            app_uri TEXT NOT NULL DEFAULT 'exsupport',
            enroll_token TEXT UNIQUE NOT NULL,
            default_rate REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT '€',
            color_primary TEXT NOT NULL DEFAULT '#0B4FA3',
            color_accent TEXT NOT NULL DEFAULT '#C21F3A',
            logo BLOB,
            logo_mime TEXT NOT NULL DEFAULT '',
            download_exsupport TEXT NOT NULL DEFAULT '',
            download_quick TEXT NOT NULL DEFAULT '',
            download_android TEXT NOT NULL DEFAULT '',
            app_version TEXT NOT NULL DEFAULT '',
            created REAL NOT NULL
        );
        """
    )


def _ensure_default_tenant(c) -> int:
    row = c.execute("SELECT id FROM tenants WHERE slug=?", (DEFAULT_SLUG,)).fetchone()
    if row:
        return row["id"]
    # Carry forward anything the single-tenant panel kept in settings.
    def s(key, default=""):
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default
    try:
        rate = float(s("default_rate", "0") or 0)
    except ValueError:
        rate = 0.0
    cur = c.execute(
        """INSERT INTO tenants (slug, name, phone, email, website, id_server, relay_server,
                                rd_key, app_uri, enroll_token, default_rate, currency,
                                download_exsupport, download_quick, download_android,
                                app_version, created)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (DEFAULT_SLUG, DEFAULT_NAME, "2615 00 2000", "info@exelixisnet.gr",
         "https://exelixisnet.gr", DEFAULT_RD_ID_SERVER, DEFAULT_RD_RELAY or DEFAULT_RD_ID_SERVER,
         DEFAULT_RD_KEY, APP_URI, ENROLL_TOKEN, rate, s("currency", "€") or "€",
         s("download_exsupport", DEFAULT_DOWNLOADS["download_exsupport"]),
         s("download_quick", DEFAULT_DOWNLOADS["download_quick"]),
         s("download_android", DEFAULT_DOWNLOADS["download_android"]),
         s("app_version", ""), time.time()),
    )
    return cur.lastrowid


def _add_col(c, table: str, col: str, decl: str) -> None:
    have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
    if col not in have:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                full_name TEXT NOT NULL DEFAULT '',
                pw_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin','supervisor','tech')),
                superadmin INTEGER NOT NULL DEFAULT 0,
                totp_secret TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                session_gen INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL,
                UNIQUE (tenant_id, username)
            );
            CREATE TABLE IF NOT EXISTS devices (
                tenant_id INTEGER NOT NULL,
                rd_id TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                hostname TEXT NOT NULL DEFAULT '',
                os TEXT NOT NULL DEFAULT '',
                app_version TEXT NOT NULL DEFAULT '',
                pw_enc TEXT NOT NULL DEFAULT '',
                secret_hash TEXT NOT NULL,
                last_ip TEXT NOT NULL DEFAULT '',
                local_ip TEXT NOT NULL DEFAULT '',
                os_user TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT '',
                hidden INTEGER NOT NULL DEFAULT 0,
                hidden_sup INTEGER NOT NULL DEFAULT 0,
                customer_id INTEGER,
                ram TEXT NOT NULL DEFAULT '',
                disk TEXT NOT NULL DEFAULT '',
                created REAL NOT NULL,
                last_seen REAL NOT NULL,
                PRIMARY KEY (tenant_id, rd_id)
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER,
                ts REAL NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                rd_id TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                contact TEXT NOT NULL DEFAULT '',
                rate REAL,
                notes TEXT NOT NULL DEFAULT '',
                created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                rd_id TEXT NOT NULL,
                customer_id INTEGER,
                session_key TEXT NOT NULL DEFAULT '',
                started REAL NOT NULL,
                ended REAL,
                seconds INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'app',
                technician TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                billable INTEGER NOT NULL DEFAULT 1,
                created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                rd_id TEXT NOT NULL,
                customer_id INTEGER,
                message TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                claimed_by TEXT NOT NULL DEFAULT '',
                created REAL NOT NULL,
                updated REAL NOT NULL
            );
            """
        )
        _tenants_schema(c)

        # --- migrate a single-tenant (<=1.9) database -----------------------
        existing_tables = {r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        legacy = False
        if "devices" in existing_tables:
            dcols = {r["name"] for r in c.execute("PRAGMA table_info(devices)")}
            legacy = "tenant_id" not in dcols
        if legacy:
            tid = _ensure_default_tenant(c)
            _migrate_v1(c, tid)
        else:
            _ensure_default_tenant(c)

        # Make sure late-added columns exist on an already-multitenant DB.
        _add_col(c, "users", "superadmin", "INTEGER NOT NULL DEFAULT 0")
        _add_col(c, "tenants", "app_version", "TEXT NOT NULL DEFAULT ''")

        # Indexes last, once every table has its tenant_id column.
        c.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_devices_secret ON devices(secret_hash);
            CREATE INDEX IF NOT EXISTS idx_sessions_rd ON sessions(tenant_id, rd_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started);
            CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(tenant_id, status);
            """
        )

        # Bootstrap the first user (platform owner) on a brand-new database.
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            tid = c.execute("SELECT id FROM tenants WHERE slug=?", (DEFAULT_SLUG,)).fetchone()["id"]
            user = os.environ.get("PANEL_ADMIN_USER", "admin")
            pw = os.environ.get("PANEL_ADMIN_PASSWORD")
            if not pw:
                raise SystemExit("Set PANEL_ADMIN_PASSWORD for the first start")
            c.execute(
                "INSERT INTO users (tenant_id, username, full_name, pw_hash, role, superadmin, created) "
                "VALUES (?,?,?,?,?,1,?)",
                (tid, user, "Administrator", hash_pw(pw), "admin", time.time()),
            )


def _migrate_v1(c, tid: int) -> None:
    """Fold a single-tenant schema into tenant <tid> and add composite keys."""
    # devices: rebuild with (tenant_id, rd_id) primary key.
    c.execute("ALTER TABLE devices RENAME TO devices_old")
    c.executescript(
        """
        CREATE TABLE devices (
            tenant_id INTEGER NOT NULL,
            rd_id TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            hostname TEXT NOT NULL DEFAULT '',
            os TEXT NOT NULL DEFAULT '',
            app_version TEXT NOT NULL DEFAULT '',
            pw_enc TEXT NOT NULL DEFAULT '',
            secret_hash TEXT NOT NULL,
            last_ip TEXT NOT NULL DEFAULT '',
            local_ip TEXT NOT NULL DEFAULT '',
            os_user TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT '',
            hidden INTEGER NOT NULL DEFAULT 0,
            hidden_sup INTEGER NOT NULL DEFAULT 0,
            customer_id INTEGER,
            ram TEXT NOT NULL DEFAULT '',
            disk TEXT NOT NULL DEFAULT '',
            created REAL NOT NULL,
            last_seen REAL NOT NULL,
            PRIMARY KEY (tenant_id, rd_id)
        );
        CREATE INDEX IF NOT EXISTS idx_devices_secret ON devices(secret_hash);
        """
    )
    oldcols = [r["name"] for r in c.execute("PRAGMA table_info(devices_old)")]
    want = ["rd_id", "name", "phone", "notes", "hostname", "os", "app_version", "pw_enc",
            "secret_hash", "last_ip", "local_ip", "os_user", "kind", "hidden", "hidden_sup",
            "customer_id", "ram", "disk", "created", "last_seen"]
    cols = [col for col in want if col in oldcols]
    sel = ", ".join(cols)
    c.execute(
        f"INSERT INTO devices (tenant_id, {sel}) SELECT ?, {sel} FROM devices_old", (tid,))
    c.execute("DROP TABLE devices_old")

    # users: rebuild so username is unique per tenant and superadmin exists.
    c.execute("ALTER TABLE users RENAME TO users_old")
    c.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            full_name TEXT NOT NULL DEFAULT '',
            pw_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin','supervisor','tech')),
            superadmin INTEGER NOT NULL DEFAULT 0,
            totp_secret TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            session_gen INTEGER NOT NULL DEFAULT 0,
            created REAL NOT NULL,
            UNIQUE (tenant_id, username)
        );
        """
    )
    c.execute(
        "INSERT INTO users (id, tenant_id, username, full_name, pw_hash, role, totp_secret, "
        "active, session_gen, created) "
        "SELECT id, ?, username, full_name, pw_hash, role, totp_secret, active, session_gen, "
        "created FROM users_old", (tid,))
    c.execute("DROP TABLE users_old")
    # The lowest-id admin is the platform owner.
    row = c.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
    if row:
        c.execute("UPDATE users SET superadmin=1 WHERE id=?", (row["id"],))

    # customers / sessions / requests / audit: add tenant_id, backfill.
    for table in ("customers", "sessions", "requests", "audit"):
        if table in {r["name"] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}:
            _add_col(c, table, "tenant_id", "INTEGER")
            if table == "audit":
                c.execute("UPDATE audit SET tenant_id=? WHERE tenant_id IS NULL", (tid,))
            else:
                c.execute(f"UPDATE {table} SET tenant_id=? WHERE tenant_id IS NULL", (tid,))


def audit(actor: str, action: str, rd_id: str = "", detail: str = "",
          tenant_id: Optional[int] = None) -> None:
    with db() as c:
        c.execute(
            "INSERT INTO audit (tenant_id, ts, actor, action, rd_id, detail) VALUES (?,?,?,?,?,?)",
            (tenant_id, time.time(), actor, action, rd_id, detail),
        )


# --- crypto helpers ----------------------------------------------------------
def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def check_pw(pw: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(s), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def enc(s: str) -> str:
    return FERNET.encrypt(s.encode()).decode() if s else ""


def dec(s: str) -> str:
    if not s:
        return ""
    try:
        return FERNET.decrypt(s.encode()).decode()
    except InvalidToken:
        return ""


def sign_session(uid: int, gen: int) -> str:
    exp = int(time.time()) + SESSION_HOURS * 3600
    payload = f"{uid}.{gen}.{exp}"
    sig = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_session(token: str) -> Optional[tuple]:
    try:
        uid, gen, exp, sig = token.split(".")
        payload = f"{uid}.{gen}.{exp}"
        good = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, sig) or int(exp) < time.time():
            return None
        return int(uid), int(gen)
    except Exception:
        return None


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")


# --- login rate limiting -----------------------------------------------------
_fails: dict = {}


def too_many_fails(key: str) -> bool:
    now = time.time()
    recent = [t for t in _fails.get(key, []) if now - t < 900]
    _fails[key] = recent
    return len(recent) >= 8


def note_fail(key: str) -> None:
    _fails.setdefault(key, []).append(time.time())


# --- tenant helpers ----------------------------------------------------------
def tenant_by_slug(c, slug: str) -> Optional[sqlite3.Row]:
    return c.execute("SELECT * FROM tenants WHERE slug=?", (slug,)).fetchone()


def tenant_by_id(c, tid: int) -> Optional[sqlite3.Row]:
    return c.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()


def tenant_by_enroll_token(c, token: str) -> Optional[sqlite3.Row]:
    if not token:
        return None
    for t in c.execute("SELECT * FROM tenants WHERE active=1"):
        if hmac.compare_digest(t["enroll_token"], token):
            return t
    return None


def tenant_rate(t: sqlite3.Row) -> float:
    try:
        return float(t["default_rate"] or 0)
    except (ValueError, TypeError):
        return 0.0


def tenant_currency(t: sqlite3.Row) -> str:
    return t["currency"] or "€"


def tenant_downloads(t: sqlite3.Row) -> dict:
    return {
        "exsupport": t["download_exsupport"] or DEFAULT_DOWNLOADS["download_exsupport"],
        "quick": t["download_quick"] or DEFAULT_DOWNLOADS["download_quick"],
        "android": t["download_android"] or DEFAULT_DOWNLOADS["download_android"],
    }


# --- auth dependencies -------------------------------------------------------
def current_user(request: Request) -> sqlite3.Row:
    tok = request.cookies.get("exs_session", "")
    sess = read_session(tok)
    if not sess:
        raise HTTPException(401, "Not logged in")
    with db() as c:
        u = c.execute(
            "SELECT u.*, t.slug AS tenant_slug, t.name AS tenant_name, t.active AS tenant_active "
            "FROM users u JOIN tenants t ON t.id = u.tenant_id "
            "WHERE u.id=? AND u.active=1", (sess[0],)).fetchone()
    if not u or u["session_gen"] != sess[1] or not u["tenant_active"]:
        raise HTTPException(401, "Not logged in")
    return u


def admin_user(u=Depends(current_user)) -> sqlite3.Row:
    if u["role"] != "admin":
        raise HTTPException(403, "Admins only")
    return u


def manager_user(u=Depends(current_user)) -> sqlite3.Row:
    if u["role"] not in ("admin", "supervisor"):
        raise HTTPException(403, "Not allowed")
    return u


def super_user(u=Depends(current_user)) -> sqlite3.Row:
    if not u["superadmin"]:
        raise HTTPException(403, "Platform owner only")
    return u


def hub_auth(x_api_key: str = Header(default="")) -> str:
    for name, key in (("hub", HUB_API_KEY), ("monitor", MONITOR_API_KEY)):
        if key and hmac.compare_digest(x_api_key, key):
            return name
    raise HTTPException(401, "Bad API key")


def hub_tenant_id(c) -> int:
    r = c.execute("SELECT id FROM tenants WHERE slug=?", (DEFAULT_SLUG,)).fetchone()
    return r["id"] if r else 0


# --- device helpers ----------------------------------------------------------
def device_view(r: sqlite3.Row) -> dict:
    now = time.time()
    return {
        "id": r["rd_id"],
        "name": r["name"],
        "phone": r["phone"],
        "notes": r["notes"],
        "hostname": r["hostname"],
        "os": r["os"],
        "app_version": r["app_version"],
        "online": now - r["last_seen"] < ONLINE_SECONDS,
        "last_seen": r["last_seen"],
        "created": r["created"],
        "has_password": bool(r["pw_enc"]),
        "last_ip": r["last_ip"],
        "local_ip": r["local_ip"],
        "os_user": r["os_user"],
        "kind": r["kind"],
        "hidden": bool(r["hidden"]),
        "hidden_sup": bool(r["hidden_sup"]),
        "ram": r["ram"],
        "disk": r["disk"],
        "customer_id": r["customer_id"],
        "customer_name": (r["customer_name"] if "customer_name" in r.keys() else None),
    }


def connect_link(app_uri: str, rd_id: str, pw: str) -> str:
    link = f"{app_uri or 'exsupport'}://connection/new/{quote(rd_id)}"
    if pw:
        link += "?password=" + quote(pw, safe="")
    return link


def get_device(c, tid: int, rd_id: str) -> sqlite3.Row:
    r = c.execute("SELECT * FROM devices WHERE tenant_id=? AND rd_id=?", (tid, rd_id)).fetchone()
    if not r:
        raise HTTPException(404, "Unknown device")
    return r


def device_by_secret(c, secret: str) -> Optional[sqlite3.Row]:
    r = c.execute("SELECT * FROM devices WHERE secret_hash=?", (sha256(secret),)).fetchone()
    return r


# --- client (customer PC) API -----------------------------------------------
class RegisterIn(BaseModel):
    id: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(default="", max_length=40)
    hostname: str = Field(default="", max_length=120)
    os: str = Field(default="", max_length=120)
    version: str = Field(default="", max_length=40)
    password: str = Field(default="", max_length=128)
    local_ip: str = Field(default="", max_length=64)
    os_user: str = Field(default="", max_length=120)
    kind: str = Field(default="", max_length=16)
    ram: str = Field(default="", max_length=32)
    disk: str = Field(default="", max_length=32)


class HeartbeatIn(BaseModel):
    id: str = Field(min_length=3, max_length=40)
    secret: str = Field(min_length=10, max_length=128)
    version: str = Field(default="", max_length=40)
    hostname: str = Field(default="", max_length=120)
    password: str = Field(default="", max_length=128)
    local_ip: str = Field(default="", max_length=64)
    os_user: str = Field(default="", max_length=120)
    kind: str = Field(default="", max_length=16)
    os: str = Field(default="", max_length=120)
    ram: str = Field(default="", max_length=32)
    disk: str = Field(default="", max_length=32)
    old_id: str = Field(default="", max_length=40)


@app.post("/api/client/register")
def client_register(body: RegisterIn, request: Request, x_enroll_token: str = Header(default="")):
    now = time.time()
    ip = client_ip(request)
    secret = secrets.token_urlsafe(32)
    with db() as c:
        t = tenant_by_enroll_token(c, x_enroll_token)
        if not t:
            raise HTTPException(401, "Bad enrollment token")
        tid = t["id"]
        existed = c.execute(
            "SELECT 1 FROM devices WHERE tenant_id=? AND rd_id=?", (tid, body.id)).fetchone()
        c.execute(
            """INSERT INTO devices (tenant_id, rd_id, name, phone, hostname, os, app_version, pw_enc,
                                    secret_hash, last_ip, local_ip, os_user, kind, ram, disk,
                                    created, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(tenant_id, rd_id) DO UPDATE SET name=excluded.name, phone=excluded.phone,
                 hostname=excluded.hostname, os=excluded.os, app_version=excluded.app_version,
                 pw_enc=excluded.pw_enc, secret_hash=excluded.secret_hash,
                 last_ip=excluded.last_ip, local_ip=excluded.local_ip, os_user=excluded.os_user,
                 kind=excluded.kind, ram=excluded.ram, disk=excluded.disk,
                 last_seen=excluded.last_seen""",
            (tid, body.id, body.name.strip(), body.phone.strip(), body.hostname, body.os,
             body.version, enc(body.password), sha256(secret), ip, body.local_ip,
             body.os_user, body.kind, body.ram, body.disk, now, now),
        )
    audit("client", "re-register" if existed else "register", body.id,
          f"{body.name} from {ip}", tenant_id=tid)
    return {"secret": secret}


@app.post("/api/client/heartbeat")
def client_heartbeat(body: HeartbeatIn, request: Request):
    with db() as c:
        r = device_by_secret(c, body.secret)
        if not r:
            raise HTTPException(401, "Unknown device")  # app re-registers on 401
        tid = r["tenant_id"]
        lookup = r["rd_id"]
        fields = {"last_seen": time.time(), "last_ip": client_ip(request)}
        if body.version:
            fields["app_version"] = body.version
        if body.hostname:
            fields["hostname"] = body.hostname
        if body.local_ip:
            fields["local_ip"] = body.local_ip
        if body.os_user:
            fields["os_user"] = body.os_user
        if body.kind:
            fields["kind"] = body.kind
        if body.os:
            fields["os"] = body.os
        if body.ram:
            fields["ram"] = body.ram
        if body.disk:
            fields["disk"] = body.disk
        if body.password:
            fields["pw_enc"] = enc(body.password)
        id_changed = bool(body.id and body.id != lookup)
        if id_changed:
            if c.execute("SELECT 1 FROM devices WHERE tenant_id=? AND rd_id=?",
                         (tid, body.id)).fetchone():
                c.execute("DELETE FROM devices WHERE tenant_id=? AND rd_id=?", (tid, body.id))
            fields["rd_id"] = body.id
        sets = ", ".join(f"{k}=?" for k in fields)
        c.execute(f"UPDATE devices SET {sets} WHERE tenant_id=? AND rd_id=?",
                  (*fields.values(), tid, lookup))
    if id_changed:
        audit("client", "id-changed", body.id, f"was {lookup}", tenant_id=tid)
    if body.password:
        audit("client", "password-updated", body.id or lookup, tenant_id=tid)
    return {"ok": True}


# --- technician web API ------------------------------------------------------
class LoginIn(BaseModel):
    username: str
    password: str
    code: str = ""
    tenant: str = ""


@app.post("/api/login")
def login(body: LoginIn, request: Request, response: Response):
    slug = (body.tenant or DEFAULT_SLUG).strip().lower()
    key = f"{client_ip(request)}|{slug}|{body.username.lower()}"
    if too_many_fails(key):
        raise HTTPException(429, "Too many attempts, try again in 15 minutes")
    with db() as c:
        t = tenant_by_slug(c, slug)
        u = None
        if t and t["active"]:
            u = c.execute(
                "SELECT * FROM users WHERE tenant_id=? AND username=? AND active=1",
                (t["id"], body.username.strip())).fetchone()
    if not u or not check_pw(body.password, u["pw_hash"]):
        note_fail(key)
        raise HTTPException(401, "Wrong username or password")
    if u["totp_secret"]:
        if not body.code:
            return JSONResponse({"need_code": True}, status_code=401)
        if not pyotp.TOTP(u["totp_secret"]).verify(body.code.strip(), valid_window=1):
            note_fail(key)
            raise HTTPException(401, "Wrong 2FA code")
    response.set_cookie(
        "exs_session", sign_session(u["id"], u["session_gen"]), httponly=True,
        secure=COOKIE_SECURE, samesite="strict", max_age=SESSION_HOURS * 3600,
    )
    audit(u["username"], "login", detail=client_ip(request), tenant_id=t["id"])
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("exs_session")
    return {"ok": True}


@app.get("/api/me")
def me(u=Depends(current_user)):
    return {"username": u["username"], "full_name": u["full_name"], "role": u["role"],
            "superadmin": bool(u["superadmin"]), "tenant": u["tenant_slug"],
            "tenant_name": u["tenant_name"], "totp": bool(u["totp_secret"]),
            "panel_version": PANEL_VERSION}


def _visible_where(role: str, prefix: str = "") -> str:
    # Always tenant-scoped by the caller; this adds the hidden-visibility clause.
    if role == "admin":
        return ""
    if role == "supervisor":
        return f"AND {prefix}hidden_sup=0"
    return f"AND {prefix}hidden=0 AND {prefix}hidden_sup=0"


def _ver_tuple(v: str):
    try:
        return tuple(int(x) for x in v.strip().split(".")[:3])
    except (ValueError, AttributeError):
        return ()


def _is_older(a: str, b: str) -> bool:
    ta, tb = _ver_tuple(a), _ver_tuple(b)
    return bool(ta) and bool(tb) and ta < tb


def reap_stale_sessions(c, tid: Optional[int] = None) -> None:
    """Close sessions left open by a force-closed / crashed / powered-off app.

    The controlled computer reports when a technician disconnects, but if its app
    is killed that report never arrives. Such a session is closed once the computer
    stops heart-beating (goes offline) or it has run past the hard cap. The end
    time is estimated from the last heartbeat (≈ when the app actually stopped).
    """
    now = time.time()
    q = ("SELECT s.id, s.started, d.last_seen FROM sessions s "
         "JOIN devices d ON d.rd_id = s.rd_id AND d.tenant_id = s.tenant_id "
         "WHERE s.ended IS NULL")
    params: tuple = ()
    if tid is not None:
        q += " AND s.tenant_id=?"
        params = (tid,)
    for r in c.execute(q, params).fetchall():
        offline = now - r["last_seen"] > ONLINE_SECONDS
        too_long = now - r["started"] > MAX_SESSION_SECONDS
        if not (offline or too_long):
            continue
        end = r["last_seen"] if offline else now
        end = min(max(end, r["started"]), r["started"] + MAX_SESSION_SECONDS)
        c.execute("UPDATE sessions SET ended=?, seconds=? WHERE id=?",
                  (end, max(0, int(end - r["started"])), r["id"]))
    # Open sessions whose computer was deleted: close them without phantom time.
    orphan_q = ("SELECT s.id, s.started FROM sessions s WHERE s.ended IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM devices d WHERE d.rd_id=s.rd_id "
                "AND d.tenant_id=s.tenant_id)")
    oparams: tuple = ()
    if tid is not None:
        orphan_q += " AND s.tenant_id=?"
        oparams = (tid,)
    for r in c.execute(orphan_q, oparams).fetchall():
        c.execute("UPDATE sessions SET ended=?, seconds=0 WHERE id=?", (r["started"], r["id"]))


@app.get("/api/devices")
def list_devices(u=Depends(current_user)):
    tid = u["tenant_id"]
    where = _visible_where(u["role"], "d.")
    with db() as c:
        reap_stale_sessions(c, tid)
        t = tenant_by_id(c, tid)
        latest = latest_app_version(t)
        rows = c.execute(
            f"SELECT d.*, cu.name AS customer_name FROM devices d "
            f"LEFT JOIN customers cu ON cu.id = d.customer_id AND cu.tenant_id = d.tenant_id "
            f"WHERE d.tenant_id=? {where} ORDER BY d.name COLLATE NOCASE", (tid,)).fetchall()
        opens = {s["rd_id"]: s["technician"] for s in c.execute(
            "SELECT rd_id, technician FROM sessions WHERE tenant_id=? AND ended IS NULL", (tid,))}
    out = []
    for r in rows:
        d = device_view(r)
        appver = (d.get("app_version") or "").split(" ")[0]
        d["needs_update"] = _is_older(appver, latest)
        d["in_session"] = r["rd_id"] in opens
        d["active_tech"] = opens.get(r["rd_id"], "")
        out.append(d)
    return out


def _can_see_device(r: sqlite3.Row, role: str) -> bool:
    if role == "admin":
        return True
    if role == "supervisor":
        return not r["hidden_sup"]
    return not r["hidden"] and not r["hidden_sup"]


def get_visible_device(c, tid: int, rd_id: str, u: sqlite3.Row) -> sqlite3.Row:
    r = get_device(c, tid, rd_id)
    if not _can_see_device(r, u["role"]):
        raise HTTPException(404, "Unknown device")
    return r


class DeviceCreate(BaseModel):
    id: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(default="", max_length=40)
    password: str = Field(default="", max_length=128)
    notes: str = Field(default="", max_length=2000)


@app.post("/api/devices")
def device_create(body: DeviceCreate, u=Depends(manager_user)):
    tid = u["tenant_id"]
    rid = body.id.strip()
    now = time.time()
    with db() as c:
        if c.execute("SELECT 1 FROM devices WHERE tenant_id=? AND rd_id=?", (tid, rid)).fetchone():
            raise HTTPException(409, "A computer with this ID is already on the list")
        c.execute(
            """INSERT INTO devices (tenant_id, rd_id, name, phone, notes, hostname, os, app_version,
                                    pw_enc, secret_hash, last_ip, local_ip, os_user, kind,
                                    created, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, rid, body.name.strip(), body.phone.strip(), body.notes.strip(), "", "", "",
             enc(body.password), sha256(secrets.token_urlsafe(32)), "", "", "", "manual", now, now),
        )
    audit(u["username"], "manual-add", rid, body.name.strip(), tenant_id=tid)
    return {"ok": True}


@app.post("/api/devices/{rd_id}/connect")
def device_connect(rd_id: str, u=Depends(current_user)):
    tid = u["tenant_id"]
    with db() as c:
        r = get_visible_device(c, tid, rd_id, u)
        t = tenant_by_id(c, tid)
    audit(u["username"], "connect", rd_id, r["name"], tenant_id=tid)
    return {"link": connect_link(t["app_uri"], rd_id, dec(r["pw_enc"]))}


@app.post("/api/devices/{rd_id}/reveal")
def device_reveal(rd_id: str, u=Depends(current_user)):
    tid = u["tenant_id"]
    with db() as c:
        r = get_visible_device(c, tid, rd_id, u)
    audit(u["username"], "reveal-password", rd_id, r["name"], tenant_id=tid)
    return {"password": dec(r["pw_enc"])}


class DeviceEdit(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=40)
    notes: Optional[str] = Field(default=None, max_length=2000)
    hidden: Optional[bool] = None
    hidden_sup: Optional[bool] = None
    customer_id: Optional[int] = None


@app.patch("/api/devices/{rd_id}")
def device_edit(rd_id: str, body: DeviceEdit, u=Depends(current_user)):
    tid = u["tenant_id"]
    with db() as c:
        get_visible_device(c, tid, rd_id, u)
        fields = {}
        for k in ("name", "phone", "notes"):
            v = getattr(body, k)
            if v is not None:
                fields[k] = v.strip()
        if body.hidden is not None:
            if u["role"] not in ("admin", "supervisor"):
                raise HTTPException(403, "Only admins or supervisors can hide computers")
            fields["hidden"] = 1 if body.hidden else 0
        if body.hidden_sup is not None:
            if u["role"] != "admin":
                raise HTTPException(403, "Only administrators can hide computers from supervisors")
            fields["hidden_sup"] = 1 if body.hidden_sup else 0
        if body.customer_id is not None:
            cid = body.customer_id or None
            if cid is not None:
                if not c.execute("SELECT 1 FROM customers WHERE id=? AND tenant_id=?",
                                 (cid, tid)).fetchone():
                    raise HTTPException(404, "Unknown customer")
            fields["customer_id"] = cid
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            c.execute(f"UPDATE devices SET {sets} WHERE tenant_id=? AND rd_id=?",
                      (*fields.values(), tid, rd_id))
    if fields:
        audit(u["username"], "edit", rd_id, json.dumps(fields, ensure_ascii=False), tenant_id=tid)
    return {"ok": True}


@app.delete("/api/devices/{rd_id}")
def device_delete(rd_id: str, u=Depends(admin_user)):
    tid = u["tenant_id"]
    with db() as c:
        r = get_device(c, tid, rd_id)
        c.execute("DELETE FROM devices WHERE tenant_id=? AND rd_id=?", (tid, rd_id))
    audit(u["username"], "delete", rd_id, r["name"], tenant_id=tid)
    return {"ok": True}


# --- customers (clients that computers belong to) ---------------------------
def customer_view(r: sqlite3.Row, admin: bool, rate_default: float) -> dict:
    v = {
        "id": r["id"],
        "name": r["name"],
        "contact": r["contact"],
        "notes": r["notes"],
        "computers": r["computers"] if "computers" in r.keys() else 0,
    }
    if admin:
        v["rate"] = r["rate"]
        v["effective_rate"] = r["rate"] if r["rate"] is not None else rate_default
    return v


@app.get("/api/customers")
def customers_list(u=Depends(current_user)):
    tid = u["tenant_id"]
    admin = u["role"] == "admin"
    with db() as c:
        t = tenant_by_id(c, tid)
        rows = c.execute(
            "SELECT cu.*, (SELECT COUNT(*) FROM devices d WHERE d.customer_id=cu.id "
            "AND d.tenant_id=cu.tenant_id) AS computers "
            "FROM customers cu WHERE cu.tenant_id=? ORDER BY cu.name COLLATE NOCASE",
            (tid,)).fetchall()
    rate_default = tenant_rate(t)
    return {"default_rate": rate_default if admin else None,
            "currency": tenant_currency(t),
            "customers": [customer_view(r, admin, rate_default) for r in rows]}


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    contact: str = Field(default="", max_length=200)
    rate: Optional[float] = Field(default=None, ge=0, le=100000)
    notes: str = Field(default="", max_length=2000)


@app.post("/api/customers")
def customer_create(body: CustomerIn, u=Depends(manager_user)):
    tid = u["tenant_id"]
    rate = body.rate if u["role"] == "admin" else None
    with db() as c:
        cur = c.execute(
            "INSERT INTO customers (tenant_id, name, contact, rate, notes, created) "
            "VALUES (?,?,?,?,?,?)",
            (tid, body.name.strip(), body.contact.strip(), rate, body.notes.strip(), time.time()))
        cid = cur.lastrowid
    audit(u["username"], "customer-create", detail=body.name.strip(), tenant_id=tid)
    return {"id": cid}


@app.patch("/api/customers/{cid}")
def customer_edit(cid: int, body: CustomerIn, u=Depends(manager_user)):
    tid = u["tenant_id"]
    with db() as c:
        if not c.execute("SELECT 1 FROM customers WHERE id=? AND tenant_id=?",
                         (cid, tid)).fetchone():
            raise HTTPException(404, "Unknown customer")
        if u["role"] == "admin":
            c.execute("UPDATE customers SET name=?, contact=?, rate=?, notes=? "
                      "WHERE id=? AND tenant_id=?",
                      (body.name.strip(), body.contact.strip(), body.rate, body.notes.strip(),
                       cid, tid))
        else:
            c.execute("UPDATE customers SET name=?, contact=?, notes=? WHERE id=? AND tenant_id=?",
                      (body.name.strip(), body.contact.strip(), body.notes.strip(), cid, tid))
    audit(u["username"], "customer-edit", detail=body.name.strip(), tenant_id=tid)
    return {"ok": True}


@app.delete("/api/customers/{cid}")
def customer_delete(cid: int, u=Depends(manager_user)):
    tid = u["tenant_id"]
    with db() as c:
        r = c.execute("SELECT name FROM customers WHERE id=? AND tenant_id=?", (cid, tid)).fetchone()
        if not r:
            raise HTTPException(404, "Unknown customer")
        c.execute("UPDATE devices SET customer_id=NULL WHERE customer_id=? AND tenant_id=?",
                  (cid, tid))
        c.execute("DELETE FROM customers WHERE id=? AND tenant_id=?", (cid, tid))
    audit(u["username"], "customer-delete", detail=r["name"], tenant_id=tid)
    return {"ok": True}


class BillingIn(BaseModel):
    default_rate: float = Field(ge=0, le=100000)
    currency: str = Field(default="€", max_length=8)


@app.put("/api/billing")
def billing_save(body: BillingIn, u=Depends(admin_user)):
    tid = u["tenant_id"]
    with db() as c:
        c.execute("UPDATE tenants SET default_rate=?, currency=? WHERE id=?",
                  (body.default_rate, body.currency.strip() or "€", tid))
    audit(u["username"], "billing-edit", detail=f"{body.default_rate} {body.currency}", tenant_id=tid)
    return {"ok": True}


# --- session reporting (from the controlled computer's app) -----------------
class SessionIn(BaseModel):
    id: str = Field(min_length=3, max_length=40)
    secret: str = Field(min_length=10, max_length=128)
    event: str = Field(pattern="^(start|end)$")
    session_key: str = Field(min_length=1, max_length=80)


@app.post("/api/client/session")
def client_session(body: SessionIn):
    now = time.time()
    with db() as c:
        r = device_by_secret(c, body.secret)
        if not r:
            raise HTTPException(401, "Unknown device")
        tid, rd_id = r["tenant_id"], r["rd_id"]
        if body.event == "start":
            open_row = c.execute(
                "SELECT id FROM sessions WHERE tenant_id=? AND rd_id=? AND session_key=? "
                "AND ended IS NULL", (tid, rd_id, body.session_key)).fetchone()
            if not open_row:
                tech = ""
                a = c.execute(
                    "SELECT actor FROM audit WHERE tenant_id=? AND rd_id=? AND action='connect' "
                    "AND ts>=? ORDER BY ts DESC LIMIT 1", (tid, rd_id, now - 300)).fetchone()
                if a:
                    tech = a["actor"]
                c.execute(
                    "INSERT INTO sessions (tenant_id, rd_id, customer_id, session_key, started, "
                    "source, technician, created) VALUES (?,?,?,?,?,?,?,?)",
                    (tid, rd_id, r["customer_id"], body.session_key, now, "app", tech, now))
        else:
            row = c.execute(
                "SELECT id, started FROM sessions WHERE tenant_id=? AND rd_id=? AND session_key=? "
                "AND ended IS NULL ORDER BY started DESC LIMIT 1",
                (tid, rd_id, body.session_key)).fetchone()
            if row:
                secs = max(0, int(now - row["started"]))
                c.execute("UPDATE sessions SET ended=?, seconds=? WHERE id=?", (now, secs, row["id"]))
    return {"ok": True}


# --- support requests (customer presses "Call for help") --------------------
class RequestIn(BaseModel):
    id: str = Field(min_length=3, max_length=40)
    secret: str = Field(min_length=10, max_length=128)
    message: str = Field(default="", max_length=500)


@app.post("/api/client/request")
def client_request(body: RequestIn):
    now = time.time()
    with db() as c:
        r = device_by_secret(c, body.secret)
        if not r:
            raise HTTPException(401, "Unknown device")
        tid, rd_id = r["tenant_id"], r["rd_id"]
        existing = c.execute(
            "SELECT id FROM requests WHERE tenant_id=? AND rd_id=? AND status IN ('open','claimed') "
            "ORDER BY created DESC LIMIT 1", (tid, rd_id)).fetchone()
        if existing:
            c.execute("UPDATE requests SET message=?, status='open', updated=? WHERE id=?",
                      (body.message.strip(), now, existing["id"]))
        else:
            c.execute(
                "INSERT INTO requests (tenant_id, rd_id, customer_id, message, status, created, updated) "
                "VALUES (?,?,?,?,'open',?,?)",
                (tid, rd_id, r["customer_id"], body.message.strip(), now, now))
    audit("client", "help-request", rd_id, body.message.strip()[:120], tenant_id=tid)
    return {"ok": True}


@app.get("/api/requests")
def requests_list(u=Depends(current_user)):
    tid = u["tenant_id"]
    with db() as c:
        rows = c.execute(
            "SELECT rq.*, d.name AS dev_name, d.hidden, d.hidden_sup, d.pw_enc, "
            "cu.name AS customer_name FROM requests rq "
            "JOIN devices d ON d.rd_id = rq.rd_id AND d.tenant_id = rq.tenant_id "
            "LEFT JOIN customers cu ON cu.id = rq.customer_id AND cu.tenant_id = rq.tenant_id "
            "WHERE rq.tenant_id=? AND rq.status IN ('open','claimed') ORDER BY rq.created",
            (tid,)).fetchall()
    out = []
    for r in rows:
        if not _can_see_device(r, u["role"]):
            continue
        out.append({
            "id": r["id"], "rd_id": r["rd_id"], "name": r["dev_name"],
            "customer_name": r["customer_name"], "message": r["message"],
            "status": r["status"], "claimed_by": r["claimed_by"],
            "created": r["created"], "has_password": bool(r["pw_enc"]),
        })
    return out


def _get_request_device(c, tid: int, req_id: int, u: sqlite3.Row) -> sqlite3.Row:
    r = c.execute(
        "SELECT rq.*, d.hidden, d.hidden_sup FROM requests rq "
        "JOIN devices d ON d.rd_id = rq.rd_id AND d.tenant_id = rq.tenant_id "
        "WHERE rq.id=? AND rq.tenant_id=?", (req_id, tid)).fetchone()
    if not r or not _can_see_device(r, u["role"]):
        raise HTTPException(404, "Unknown request")
    return r


@app.post("/api/requests/{req_id}/claim")
def request_claim(req_id: int, u=Depends(current_user)):
    tid = u["tenant_id"]
    with db() as c:
        _get_request_device(c, tid, req_id, u)
        c.execute("UPDATE requests SET status='claimed', claimed_by=?, updated=? "
                  "WHERE id=? AND tenant_id=?", (u["username"], time.time(), req_id, tid))
    return {"ok": True}


@app.post("/api/requests/{req_id}/close")
def request_close(req_id: int, u=Depends(current_user)):
    tid = u["tenant_id"]
    with db() as c:
        _get_request_device(c, tid, req_id, u)
        c.execute("UPDATE requests SET status='closed', updated=? WHERE id=? AND tenant_id=?",
                  (time.time(), req_id, tid))
    return {"ok": True}


# --- dashboard / statistics -------------------------------------------------
def _month_key(ts: float) -> str:
    return time.strftime("%Y-%m", time.gmtime(ts))


@app.get("/api/dashboard")
def dashboard(u=Depends(current_user)):
    tid = u["tenant_id"]
    admin = u["role"] == "admin"
    now = time.time()
    this_month = time.strftime("%Y-%m", time.gmtime(now))
    with db() as c:
        reap_stale_sessions(c, tid)
        t = tenant_by_id(c, tid)
        rate_default = tenant_rate(t)
        crates, cnames = {}, {}
        for row in c.execute("SELECT id, name, rate FROM customers WHERE tenant_id=?", (tid,)):
            crates[row["id"]] = row["rate"] if row["rate"] is not None else rate_default
            cnames[row["id"]] = row["name"]
        where = _visible_where(u["role"])
        devrows = c.execute(
            f"SELECT rd_id, name, last_seen FROM devices WHERE tenant_id=? {where}", (tid,)).fetchall()
        visible = {row["rd_id"] for row in devrows}
        devnames = {row["rd_id"]: row["name"] for row in devrows}
        online_now = sum(1 for row in devrows if now - row["last_seen"] < ONLINE_SECONDS)
        total_computers = len(devrows)
        total_customers = c.execute(
            "SELECT COUNT(*) n FROM customers WHERE tenant_id=?", (tid,)).fetchone()["n"]
        done = [s for s in c.execute(
            "SELECT rd_id, customer_id, started, seconds, billable FROM sessions "
            "WHERE tenant_id=? AND ended IS NOT NULL", (tid,)) if s["rd_id"] in visible]
        open_now = sum(1 for s in c.execute(
            "SELECT rd_id FROM sessions WHERE tenant_id=? AND ended IS NULL", (tid,))
            if s["rd_id"] in visible)

    months, per_customer, per_computer, sessions_month = {}, {}, {}, 0
    for s in done:
        mk = _month_key(s["started"])
        secs = s["seconds"] or 0
        cid = s["customer_id"]
        rate = crates.get(cid, rate_default)
        bsecs = secs if s["billable"] else 0
        months.setdefault(mk, {"seconds": 0, "charge": 0.0, "sessions": 0})
        months[mk]["seconds"] += secs
        months[mk]["charge"] += bsecs / 3600 * rate
        months[mk]["sessions"] += 1
        if mk == this_month:
            sessions_month += 1
            pc = per_customer.setdefault(cid, {"seconds": 0, "bsecs": 0, "sessions": 0})
            pc["seconds"] += secs; pc["bsecs"] += bsecs; pc["sessions"] += 1
            pk = per_computer.setdefault(s["rd_id"], {"seconds": 0, "sessions": 0})
            pk["seconds"] += secs; pk["sessions"] += 1

    series = []
    cm = time.gmtime(now)
    y, m = cm.tm_year, cm.tm_mon
    buckets = []
    for _ in range(6):
        buckets.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12; y -= 1
    for mk in reversed(buckets):
        d = months.get(mk, {"seconds": 0, "charge": 0.0, "sessions": 0})
        row = {"month": mk, "hours": round(d["seconds"] / 3600, 2), "sessions": d["sessions"]}
        if admin:
            row["charge"] = round(d["charge"], 2)
        series.append(row)

    customers_out = []
    for cid, d in per_customer.items():
        hours = d["seconds"] / 3600
        row = {"customer_id": cid,
               "name": cnames.get(cid, "Unassigned") if cid else "Unassigned",
               "hours": round(hours, 2), "sessions": d["sessions"]}
        if admin:
            row["charge"] = round(d.get("bsecs", 0) / 3600 * crates.get(cid, rate_default), 2)
        customers_out.append(row)
    customers_out.sort(key=lambda x: x["hours"], reverse=True)

    computers_out = []
    for rid, d in per_computer.items():
        computers_out.append({"rd_id": rid, "name": devnames.get(rid, rid),
                              "hours": round(d["seconds"] / 3600, 2), "sessions": d["sessions"]})
    computers_out.sort(key=lambda x: x["hours"], reverse=True)

    hours_month = round(sum(d["seconds"] for cid, d in per_customer.items()) / 3600, 2)
    out = {
        "currency": tenant_currency(t),
        "month": this_month,
        "tiles": {
            "online_now": online_now,
            "active_sessions": open_now,
            "total_computers": total_computers,
            "total_customers": total_customers,
            "sessions_month": sessions_month,
            "hours_month": hours_month,
        },
        "months": series,
        "customers": customers_out,
        "computers": computers_out[:20],
    }
    if admin:
        out["tiles"]["charge_month"] = round(sum(c["charge"] for c in customers_out), 2)
        out["default_rate"] = rate_default
    return out


# --- full statistics (reports page) -----------------------------------------
def _parse_ts(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _stats_rows(c, u, frm: float, to: float):
    """Closed sessions in [frm, to) the viewer may see, with rate/name lookups."""
    tid = u["tenant_id"]
    t = tenant_by_id(c, tid)
    rate_default = tenant_rate(t)
    crates, cnames = {}, {}
    for row in c.execute("SELECT id, name, rate FROM customers WHERE tenant_id=?", (tid,)):
        crates[row["id"]] = row["rate"] if row["rate"] is not None else rate_default
        cnames[row["id"]] = row["name"]
    where = _visible_where(u["role"])
    devrows = c.execute(
        f"SELECT rd_id, name, customer_id FROM devices WHERE tenant_id=? {where}", (tid,)).fetchall()
    visible = {r["rd_id"] for r in devrows}
    devnames = {r["rd_id"]: r["name"] for r in devrows}
    devcust = {r["rd_id"]: r["customer_id"] for r in devrows}
    rows = c.execute(
        "SELECT rd_id, customer_id, started, seconds, billable, technician FROM sessions "
        "WHERE tenant_id=? AND ended IS NOT NULL AND started>=? AND started<?",
        (tid, frm, to)).fetchall()
    rows = [r for r in rows if r["rd_id"] in visible]
    return rows, crates, cnames, devnames, devcust, rate_default, tenant_currency(t)


@app.get("/api/stats")
def stats(request: Request, u=Depends(manager_user)):
    admin = u["role"] == "admin"
    now = time.time()
    frm = _parse_ts(request.query_params.get("from"), 0.0)
    to = _parse_ts(request.query_params.get("to"), now)
    with db() as c:
        reap_stale_sessions(c, u["tenant_id"])
        rows, crates, cnames, devnames, devcust, rate_default, cur = _stats_rows(c, u, frm, to)

    def blank():
        return {"seconds": 0, "bsecs": 0, "sessions": 0, "charge": 0.0}

    per_customer, per_computer, per_tech, months = {}, {}, {}, {}
    tot = blank()
    comps_seen, custs_seen, techs_seen = set(), set(), set()
    for r in rows:
        secs = r["seconds"] or 0
        cid = r["customer_id"]
        bsecs = secs if r["billable"] else 0
        ch = bsecs / 3600 * crates.get(cid, rate_default)
        tech = (r["technician"] or "").strip()
        for bucket, key in ((per_customer, cid), (per_computer, r["rd_id"]),
                            (per_tech, tech), (months, _month_key(r["started"]))):
            d = bucket.setdefault(key, blank())
            d["seconds"] += secs; d["bsecs"] += bsecs; d["sessions"] += 1; d["charge"] += ch
        tot["seconds"] += secs; tot["bsecs"] += bsecs; tot["sessions"] += 1; tot["charge"] += ch
        comps_seen.add(r["rd_id"])
        if cid:
            custs_seen.add(cid)
        if tech:
            techs_seen.add(tech)

    def hrs(s):
        return round(s / 3600, 2)

    def rowset(bucket, namer, extra=None):
        out = []
        for key, d in bucket.items():
            row = {"hours": hrs(d["seconds"]), "billable_hours": hrs(d["bsecs"]),
                   "sessions": d["sessions"]}
            row.update(namer(key))
            if extra:
                row.update(extra(key))
            if admin:
                row["charge"] = round(d["charge"], 2)
            out.append(row)
        out.sort(key=lambda x: x.get("charge", x["hours"]), reverse=True)
        return out

    customers_out = rowset(per_customer,
                           lambda cid: {"customer_id": cid,
                                        "name": cnames.get(cid, "Unassigned") if cid else "Unassigned"})
    computers_out = rowset(per_computer,
                           lambda rid: {"rd_id": rid, "name": devnames.get(rid, rid),
                                        "customer_name": cnames.get(devcust.get(rid)) if devcust.get(rid) else None})
    tech_out = rowset(per_tech, lambda nm: {"name": nm or "—"})

    series = []
    for mk in sorted(months.keys()):
        d = months[mk]
        row = {"month": mk, "hours": hrs(d["seconds"]), "sessions": d["sessions"]}
        if admin:
            row["charge"] = round(d["charge"], 2)
        series.append(row)

    out = {
        "currency": cur,
        "from": frm, "to": to,
        "totals": {
            "sessions": tot["sessions"],
            "hours": hrs(tot["seconds"]),
            "billable_hours": hrs(tot["bsecs"]),
            "unbilled_hours": hrs(tot["seconds"] - tot["bsecs"]),
            "computers": len(comps_seen),
            "customers": len(custs_seen),
            "technicians": len(techs_seen),
        },
        "months": series,
        "customers": customers_out,
        "computers": computers_out,
        "technicians": tech_out,
    }
    if admin:
        out["totals"]["charge"] = round(tot["charge"], 2)
        out["default_rate"] = rate_default
    return out


def _csv_safe(v):
    """Neutralise spreadsheet formula injection: a cell that starts with = + - @
    (or a control char) is treated as a formula by Excel/Sheets, so prefix it."""
    if isinstance(v, str) and v and (v[0] in "=+-@\t\r" or (len(v) > 1 and v[0] in " " and v.lstrip()[:1] in "=+-@")):
        return "'" + v
    return v


@app.get("/api/stats.csv")
def stats_csv(request: Request, u=Depends(manager_user)):
    admin = u["role"] == "admin"
    now = time.time()
    frm = _parse_ts(request.query_params.get("from"), 0.0)
    to = _parse_ts(request.query_params.get("to"), now)
    with db() as c:
        reap_stale_sessions(c, u["tenant_id"])
        rows, crates, cnames, devnames, devcust, rate_default, cur = _stats_rows(c, u, frm, to)
    buf = io.StringIO()
    w = csv.writer(buf)
    head = ["Date", "Time (UTC)", "Customer", "Computer", "RustDesk ID", "Technician",
            "Minutes", "Hours", "Billable"]
    if admin:
        head += ["Rate/h", "Charge"]
    w.writerow(head)
    for r in sorted(rows, key=lambda x: x["started"]):
        secs = r["seconds"] or 0
        cid = r["customer_id"]
        tm = time.gmtime(r["started"])
        line = [time.strftime("%Y-%m-%d", tm), time.strftime("%H:%M", tm),
                _csv_safe(cnames.get(cid, "Unassigned") if cid else "Unassigned"),
                _csv_safe(devnames.get(r["rd_id"], r["rd_id"])), _csv_safe(r["rd_id"]),
                _csv_safe(r["technician"] or ""),
                round(secs / 60), round(secs / 3600, 2), ("yes" if r["billable"] else "no")]
        if admin:
            rate = crates.get(cid, rate_default)
            charge = (secs if r["billable"] else 0) / 3600 * rate
            line += [round(rate, 2), round(charge, 2)]
        w.writerow(line)
    fname = f"statistics_{time.strftime('%Y%m%d', time.gmtime(frm))}_{time.strftime('%Y%m%d', time.gmtime(to))}.csv"
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"',
                             "Cache-Control": "no-store"})


# --- sessions (time log the technician can annotate) ------------------------
@app.get("/api/sessions")
def sessions_list(limit: int = 120, u=Depends(manager_user)):
    tid = u["tenant_id"]
    with db() as c:
        reap_stale_sessions(c, tid)
        t = tenant_by_id(c, tid)
        rows = c.execute(
            "SELECT s.*, d.name AS dev_name, cu.name AS customer_name FROM sessions s "
            "LEFT JOIN devices d ON d.rd_id = s.rd_id AND d.tenant_id = s.tenant_id "
            "LEFT JOIN customers cu ON cu.id = s.customer_id AND cu.tenant_id = s.tenant_id "
            "WHERE s.tenant_id=? AND s.ended IS NOT NULL ORDER BY s.started DESC LIMIT ?",
            (tid, max(1, min(limit, 500)))).fetchall()
    admin = u["role"] == "admin"
    out = []
    for r in rows:
        row = {"id": r["id"], "rd_id": r["rd_id"], "name": r["dev_name"] or r["rd_id"],
               "customer_name": r["customer_name"], "started": r["started"],
               "seconds": r["seconds"], "technician": r["technician"],
               "note": r["note"], "billable": bool(r["billable"])}
        if admin:
            row["currency"] = tenant_currency(t)
        out.append(row)
    return out


class SessionEdit(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)
    billable: Optional[bool] = None


@app.patch("/api/sessions/{sid}")
def session_edit(sid: int, body: SessionEdit, u=Depends(manager_user)):
    tid = u["tenant_id"]
    fields: dict = {}
    if body.note is not None:
        fields["note"] = body.note.strip()
    if body.billable is not None:
        fields["billable"] = 1 if body.billable else 0
    if fields:
        with db() as c:
            if not c.execute("SELECT 1 FROM sessions WHERE id=? AND tenant_id=?",
                             (sid, tid)).fetchone():
                raise HTTPException(404, "Unknown session")
            sets = ", ".join(f"{k}=?" for k in fields)
            c.execute(f"UPDATE sessions SET {sets} WHERE id=? AND tenant_id=?",
                      (*fields.values(), sid, tid))
    return {"ok": True}


@app.get("/api/audit")
def audit_log(limit: int = 200, u=Depends(manager_user)):
    tid = u["tenant_id"]
    with db() as c:
        rows = c.execute(
            "SELECT ts, actor, action, rd_id, detail FROM audit WHERE tenant_id=? "
            "ORDER BY id DESC LIMIT ?", (tid, min(max(limit, 1), 1000))).fetchall()
    return [dict(r) for r in rows]


# --- users (admin / supervisor) ---------------------------------------------
class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    full_name: str = Field(default="", max_length=80)
    password: str = Field(min_length=10, max_length=128)
    role: str = Field(default="tech", pattern="^(admin|supervisor|tech)$")


@app.get("/api/users")
def users_list(u=Depends(manager_user)):
    tid = u["tenant_id"]
    with db() as c:
        rows = c.execute(
            "SELECT id, username, full_name, role, active, totp_secret != '' AS totp "
            "FROM users WHERE tenant_id=? ORDER BY username", (tid,)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/users")
def users_create(body: UserIn, u=Depends(manager_user)):
    tid = u["tenant_id"]
    if u["role"] != "admin" and body.role != "tech":
        raise HTTPException(403, "Supervisors can only add technicians")
    try:
        with db() as c:
            c.execute(
                "INSERT INTO users (tenant_id, username, full_name, pw_hash, role, created) "
                "VALUES (?,?,?,?,?,?)",
                (tid, body.username.strip(), body.full_name.strip(), hash_pw(body.password),
                 body.role, time.time()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username already exists")
    audit(u["username"], "user-create", detail=f"{body.username} ({body.role})", tenant_id=tid)
    return {"ok": True}


class UserPatch(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=80)
    password: Optional[str] = Field(default=None, min_length=10, max_length=128)
    role: Optional[str] = Field(default=None, pattern="^(admin|supervisor|tech)$")
    active: Optional[bool] = None
    reset_2fa: bool = False


@app.patch("/api/users/{uid}")
def users_edit(uid: int, body: UserPatch, u=Depends(manager_user)):
    tid = u["tenant_id"]
    with db() as c:
        target = c.execute("SELECT role, superadmin FROM users WHERE id=? AND tenant_id=?",
                           (uid, tid)).fetchone()
    if not target:
        raise HTTPException(404, "Unknown user")
    if u["role"] != "admin":
        if target["role"] != "tech":
            raise HTTPException(403, "Supervisors can only manage technicians")
        if body.role and body.role != "tech":
            raise HTTPException(403, "Supervisors cannot change roles")
    fields: dict = {}
    if body.full_name is not None:
        fields["full_name"] = body.full_name.strip()
    if body.password:
        fields["pw_hash"] = hash_pw(body.password)
    if body.role:
        fields["role"] = body.role
    if body.active is not None:
        if uid == u["id"] and not body.active:
            raise HTTPException(400, "You cannot disable yourself")
        if target["superadmin"] and not body.active:
            raise HTTPException(400, "You cannot disable the platform owner")
        fields["active"] = 1 if body.active else 0
    if body.reset_2fa:
        fields["totp_secret"] = ""
    if not fields:
        return {"ok": True}
    with db() as c:
        sets = ", ".join(f"{k}=?" for k in fields)
        c.execute(f"UPDATE users SET {sets}, session_gen=session_gen+1 WHERE id=? AND tenant_id=?",
                  (*fields.values(), uid, tid))
    audit(u["username"], "user-edit", detail=f"user {uid}: {', '.join(fields)}", tenant_id=tid)
    return {"ok": True}


# --- own account: password and 2FA ------------------------------------------
class PwChange(BaseModel):
    current: str
    new: str = Field(min_length=10, max_length=128)


@app.post("/api/me/password")
def me_password(body: PwChange, response: Response, u=Depends(current_user)):
    if not check_pw(body.current, u["pw_hash"]):
        raise HTTPException(400, "Current password is wrong")
    with db() as c:
        c.execute("UPDATE users SET pw_hash=?, session_gen=session_gen+1 WHERE id=?",
                  (hash_pw(body.new), u["id"]))
        gen = c.execute("SELECT session_gen FROM users WHERE id=?", (u["id"],)).fetchone()[0]
    response.set_cookie("exs_session", sign_session(u["id"], gen), httponly=True,
                        secure=COOKIE_SECURE, samesite="strict", max_age=SESSION_HOURS * 3600)
    audit(u["username"], "password-change", tenant_id=u["tenant_id"])
    return {"ok": True}


_pending_totp: dict = {}


@app.post("/api/me/2fa/start")
def me_2fa_start(u=Depends(current_user)):
    secret = pyotp.random_base32()
    _pending_totp[u["id"]] = secret
    label = f"{u['username']}@{u['tenant_slug']}"
    uri = pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name=ISSUER)
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    return {"secret": secret, "svg": img.to_string(encoding="unicode")}


class CodeIn(BaseModel):
    code: str


@app.post("/api/me/2fa/confirm")
def me_2fa_confirm(body: CodeIn, u=Depends(current_user)):
    secret = _pending_totp.get(u["id"])
    if not secret or not pyotp.TOTP(secret).verify(body.code.strip(), valid_window=1):
        raise HTTPException(400, "Wrong code, try again")
    with db() as c:
        c.execute("UPDATE users SET totp_secret=? WHERE id=?", (secret, u["id"]))
    _pending_totp.pop(u["id"], None)
    audit(u["username"], "2fa-enabled", tenant_id=u["tenant_id"])
    return {"ok": True}


# --- download links for customers (per tenant) ------------------------------
class DownloadsIn(BaseModel):
    exsupport: str = Field(max_length=500)
    quick: str = Field(max_length=500)
    android: str = Field(max_length=500)


@app.get("/api/downloads")
def downloads(u=Depends(current_user)):
    with db() as c:
        t = tenant_by_id(c, u["tenant_id"])
    return tenant_downloads(t)


@app.put("/api/downloads")
def downloads_save(body: DownloadsIn, u=Depends(admin_user)):
    tid = u["tenant_id"]
    values = {
        "download_exsupport": body.exsupport.strip(),
        "download_quick": body.quick.strip(),
        "download_android": body.android.strip(),
    }
    for v in values.values():
        if v and not v.startswith("https://"):
            raise HTTPException(400, "Links must start with https://")
    with db() as c:
        c.execute("UPDATE tenants SET download_exsupport=?, download_quick=?, download_android=? "
                  "WHERE id=?", (values["download_exsupport"], values["download_quick"],
                                 values["download_android"], tid))
        t = tenant_by_id(c, tid)
    audit(u["username"], "downloads-edit", detail=json.dumps(values), tenant_id=tid)
    return tenant_downloads(t)


def _resolve_tenant_for_public(c, slug: str, token: str) -> Optional[sqlite3.Row]:
    if token:
        t = tenant_by_enroll_token(c, token)
        if t:
            return t
    if slug:
        return tenant_by_slug(c, slug.strip().lower())
    return tenant_by_slug(c, DEFAULT_SLUG)


# Public short links for customers, per tenant. Legacy /get/<platform> keeps
# serving the platform owner's own apps so old links and guides still work.
@app.get("/get/{platform}")
def get_app(platform: str):
    with db() as c:
        t = tenant_by_slug(c, DEFAULT_SLUG)
    links = tenant_downloads(t) if t else {}
    if platform not in links or not links[platform]:
        raise HTTPException(404, "Unknown download")
    return RedirectResponse(links[platform], status_code=302)


@app.get("/t/{slug}/get/{platform}")
def get_app_tenant(slug: str, platform: str):
    with db() as c:
        t = tenant_by_slug(c, slug.strip().lower())
    if not t:
        raise HTTPException(404, "Unknown workspace")
    links = tenant_downloads(t)
    if platform not in links or not links[platform]:
        raise HTTPException(404, "Unknown download")
    return RedirectResponse(links[platform], status_code=302)


_APP_VER_CACHE = {"ts": 0.0, "ver": ""}


def _github_latest() -> str:
    now = time.time()
    if now - _APP_VER_CACHE["ts"] < 3600 and _APP_VER_CACHE["ver"]:
        return _APP_VER_CACHE["ver"]
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.github.com/repos/kpap235/rustdesk/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "exsupport-panel"})
        with urllib.request.urlopen(req, timeout=5) as r:
            tag = json.load(r).get("tag_name", "")
        ver = tag.lstrip("v").strip()
        if ver:
            _APP_VER_CACHE.update(ts=now, ver=ver)
        return ver
    except Exception:
        return _APP_VER_CACHE["ver"]


def latest_app_version(t: Optional[sqlite3.Row]) -> str:
    if t and t["app_version"]:
        return t["app_version"]
    # Only the platform owner's apps auto-resolve from GitHub; others set it manually.
    if t and t["slug"] == DEFAULT_SLUG:
        return _github_latest()
    return ""


@app.api_route("/api/appversion", methods=["GET", "POST"])
def app_version(tenant: str = "", x_enroll_token: str = Header(default="")):
    with db() as c:
        t = _resolve_tenant_for_public(c, tenant, x_enroll_token)
        if not t:
            raise HTTPException(404, "Unknown workspace")
        links = tenant_downloads(t)
        ver = latest_app_version(t)
    return {
        "version": ver,
        "windows_quick": links.get("quick", ""),
        "windows_full": links.get("exsupport", ""),
        "android": links.get("android", ""),
    }


@app.get("/guide")
@app.get("/guide/{lang}")
def guide(lang: str = "el"):
    if lang not in ("el", "en"):
        raise HTTPException(404, "Unknown guide")
    path = os.path.join(STATIC_DIR, f"guide-{lang}.pdf")
    if not os.path.exists(path):
        raise HTTPException(404, "Guide not available")
    return FileResponse(path, media_type="application/pdf",
                        filename=f"Exelixisnet-IT-Support-{'odigos' if lang == 'el' else 'guide'}.pdf",
                        content_disposition_type="inline")


# --- public tenant branding --------------------------------------------------
def _public_tenant(t: sqlite3.Row) -> dict:
    return {
        "slug": t["slug"],
        "name": t["name"],
        "phone": t["phone"],
        "email": t["email"],
        "website": t["website"],
        "address": t["address"],
        "hours": t["hours"],
        "gdpr_text": t["gdpr_text"],
        "consent_text": t["consent_text"],
        "color_primary": t["color_primary"],
        "color_accent": t["color_accent"],
        "has_logo": bool(t["logo"]),
        "logo_url": f"/t/{t['slug']}/logo.png" if t["logo"] else "",
        "downloads": tenant_downloads(t),
        "app_uri": t["app_uri"],
        "panel_version": PANEL_VERSION,
        "is_default": t["slug"] == DEFAULT_SLUG,
    }


@app.get("/api/tenant")
def public_tenant(slug: str = ""):
    with db() as c:
        t = tenant_by_slug(c, (slug or DEFAULT_SLUG).strip().lower())
    if not t or not t["active"]:
        raise HTTPException(404, "Unknown workspace")
    return _public_tenant(t)


@app.get("/t/{slug}/logo.png")
def tenant_logo(slug: str):
    with db() as c:
        t = tenant_by_slug(c, slug.strip().lower())
    if not t or not t["logo"]:
        raise HTTPException(404, "No logo")
    return Response(content=t["logo"], media_type=t["logo_mime"] or "image/png",
                    headers={"Cache-Control": "public, max-age=300",
                             "Content-Security-Policy": LOGO_CSP,
                             "X-Content-Type-Options": "nosniff"})


# --- platform console (superadmin) ------------------------------------------
def _tenant_admin_view(c, t: sqlite3.Row) -> dict:
    counts = {}
    for tbl in ("devices", "users", "customers"):
        counts[tbl] = c.execute(
            f"SELECT COUNT(*) n FROM {tbl} WHERE tenant_id=?", (t["id"],)).fetchone()["n"]
    return {
        "id": t["id"], "slug": t["slug"], "name": t["name"], "active": bool(t["active"]),
        "phone": t["phone"], "email": t["email"], "website": t["website"],
        "address": t["address"], "hours": t["hours"],
        "gdpr_text": t["gdpr_text"], "consent_text": t["consent_text"],
        "id_server": t["id_server"], "relay_server": t["relay_server"], "rd_key": t["rd_key"],
        "app_uri": t["app_uri"], "default_rate": t["default_rate"], "currency": t["currency"],
        "color_primary": t["color_primary"], "color_accent": t["color_accent"],
        "has_logo": bool(t["logo"]), "logo_url": f"/t/{t['slug']}/logo.png" if t["logo"] else "",
        "download_exsupport": t["download_exsupport"], "download_quick": t["download_quick"],
        "download_android": t["download_android"], "app_version": t["app_version"],
        "enroll_token": t["enroll_token"],
        "devices": counts["devices"], "users": counts["users"], "customers": counts["customers"],
    }


@app.get("/api/admin/tenants")
def tenants_list(u=Depends(super_user)):
    with db() as c:
        rows = c.execute("SELECT * FROM tenants ORDER BY id").fetchall()
        return [_tenant_admin_view(c, t) for t in rows]


class TenantCreate(BaseModel):
    slug: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    admin_username: str = Field(min_length=2, max_length=40)
    admin_password: str = Field(min_length=10, max_length=128)
    phone: str = Field(default="", max_length=60)
    email: str = Field(default="", max_length=160)
    website: str = Field(default="", max_length=200)
    id_server: str = Field(default="", max_length=200)
    relay_server: str = Field(default="", max_length=200)
    rd_key: str = Field(default="", max_length=400)
    app_uri: str = Field(default="exsupport", max_length=40)


@app.post("/api/admin/tenants")
def tenant_create(body: TenantCreate, u=Depends(super_user)):
    slug = body.slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(400, "Slug must be 3-40 chars: lowercase letters, digits and hyphens")
    app_uri = re.sub(r"[^a-z0-9]", "", body.app_uri.strip().lower()) or "exsupport"
    token = secrets.token_urlsafe(24)
    now = time.time()
    with db() as c:
        if tenant_by_slug(c, slug):
            raise HTTPException(409, "A workspace with this slug already exists")
        cur = c.execute(
            """INSERT INTO tenants (slug, name, phone, email, website, id_server, relay_server,
                                    rd_key, app_uri, enroll_token, created)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (slug, body.name.strip(), body.phone.strip(), body.email.strip(),
             body.website.strip(), body.id_server.strip(),
             body.relay_server.strip() or body.id_server.strip(), body.rd_key.strip(),
             app_uri, token, now))
        tid = cur.lastrowid
        c.execute(
            "INSERT INTO users (tenant_id, username, full_name, pw_hash, role, created) "
            "VALUES (?,?,?,?,?,?)",
            (tid, body.admin_username.strip(), "Administrator", hash_pw(body.admin_password),
             "admin", now))
    audit(u["username"], "tenant-create", detail=f"{slug} ({body.name})", tenant_id=tid)
    return {"id": tid, "slug": slug, "enroll_token": token}


class TenantPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=160)
    active: Optional[bool] = None
    phone: Optional[str] = Field(default=None, max_length=60)
    email: Optional[str] = Field(default=None, max_length=160)
    website: Optional[str] = Field(default=None, max_length=200)
    address: Optional[str] = Field(default=None, max_length=300)
    hours: Optional[str] = Field(default=None, max_length=200)
    gdpr_text: Optional[str] = Field(default=None, max_length=4000)
    consent_text: Optional[str] = Field(default=None, max_length=4000)
    id_server: Optional[str] = Field(default=None, max_length=200)
    relay_server: Optional[str] = Field(default=None, max_length=200)
    rd_key: Optional[str] = Field(default=None, max_length=400)
    app_uri: Optional[str] = Field(default=None, max_length=40)
    default_rate: Optional[float] = Field(default=None, ge=0, le=100000)
    currency: Optional[str] = Field(default=None, max_length=8)
    color_primary: Optional[str] = Field(default=None, max_length=16)
    color_accent: Optional[str] = Field(default=None, max_length=16)
    download_exsupport: Optional[str] = Field(default=None, max_length=500)
    download_quick: Optional[str] = Field(default=None, max_length=500)
    download_android: Optional[str] = Field(default=None, max_length=500)
    app_version: Optional[str] = Field(default=None, max_length=40)


@app.patch("/api/admin/tenants/{tid}")
def tenant_patch(tid: int, body: TenantPatch, u=Depends(super_user)):
    with db() as c:
        t = tenant_by_id(c, tid)
        if not t:
            raise HTTPException(404, "Unknown workspace")
        fields: dict = {}
        data = body.model_dump(exclude_unset=True)
        for k in ("name", "phone", "email", "website", "address", "hours", "gdpr_text",
                  "consent_text", "id_server", "relay_server", "rd_key", "currency",
                  "color_primary", "color_accent", "download_exsupport", "download_quick",
                  "download_android", "app_version"):
            if k in data and data[k] is not None:
                fields[k] = data[k].strip() if isinstance(data[k], str) else data[k]
        if "app_uri" in data and data["app_uri"] is not None:
            fields["app_uri"] = re.sub(r"[^a-z0-9]", "", data["app_uri"].lower()) or "exsupport"
        if "active" in data and data["active"] is not None:
            if t["slug"] == DEFAULT_SLUG and not data["active"]:
                raise HTTPException(400, "The platform owner's workspace cannot be suspended")
            fields["active"] = 1 if data["active"] else 0
        if "default_rate" in data and data["default_rate"] is not None:
            fields["default_rate"] = data["default_rate"]
        for link in ("download_exsupport", "download_quick", "download_android"):
            if fields.get(link) and not fields[link].startswith("https://"):
                raise HTTPException(400, "Links must start with https://")
        for ck in ("color_primary", "color_accent"):
            if fields.get(ck) and not HEX_RE.match(fields[ck]):
                raise HTTPException(400, "Colours must be a hex value like #0B4FA3")
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            c.execute(f"UPDATE tenants SET {sets} WHERE id=?", (*fields.values(), tid))
    audit(u["username"], "tenant-edit", detail=f"{t['slug']}: {', '.join(fields)}", tenant_id=tid)
    return {"ok": True}


class LogoIn(BaseModel):
    data_url: str = Field(max_length=4_000_000)  # data:image/png;base64,...


@app.put("/api/admin/tenants/{tid}/logo")
def tenant_logo_set(tid: int, body: LogoIn, u=Depends(super_user)):
    m = re.match(r"^data:(image/(?:png|jpeg|svg\+xml|webp));base64,(.+)$", body.data_url.strip(),
                 re.DOTALL)
    if not m:
        raise HTTPException(400, "Send a PNG/JPEG/SVG/WebP data URL")
    mime, b64 = m.group(1), m.group(2)
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Bad image data")
    if len(raw) > 2_000_000:
        raise HTTPException(400, "Logo is too large (max 2 MB)")
    with db() as c:
        if not tenant_by_id(c, tid):
            raise HTTPException(404, "Unknown workspace")
        c.execute("UPDATE tenants SET logo=?, logo_mime=? WHERE id=?", (raw, mime, tid))
    audit(u["username"], "tenant-logo", tenant_id=tid)
    return {"ok": True}


@app.delete("/api/admin/tenants/{tid}/logo")
def tenant_logo_clear(tid: int, u=Depends(super_user)):
    with db() as c:
        if not tenant_by_id(c, tid):
            raise HTTPException(404, "Unknown workspace")
        c.execute("UPDATE tenants SET logo=NULL, logo_mime='' WHERE id=?", (tid,))
    return {"ok": True}


@app.post("/api/admin/tenants/{tid}/rotate-token")
def tenant_rotate_token(tid: int, u=Depends(super_user)):
    token = secrets.token_urlsafe(24)
    with db() as c:
        if not tenant_by_id(c, tid):
            raise HTTPException(404, "Unknown workspace")
        c.execute("UPDATE tenants SET enroll_token=? WHERE id=?", (token, tid))
    audit(u["username"], "tenant-rotate-token", tenant_id=tid)
    return {"enroll_token": token}


@app.get("/api/admin/tenants/{tid}/config")
def tenant_build_config(tid: int, request: Request, u=Depends(super_user)):
    """The branding + server config a per-tenant app build is compiled with."""
    with db() as c:
        t = tenant_by_id(c, tid)
        if not t:
            raise HTTPException(404, "Unknown workspace")
    base = str(request.base_url).rstrip("/")
    return {
        "slug": t["slug"],
        "name": t["name"],
        "app_uri": t["app_uri"],
        "id_server": t["id_server"],
        "relay_server": t["relay_server"] or t["id_server"],
        "rd_key": t["rd_key"],
        "enroll_token": t["enroll_token"],
        "api_base": base,
        "phone": t["phone"],
        "email": t["email"],
        "website": t["website"],
        "color_primary": t["color_primary"],
        "color_accent": t["color_accent"],
        "logo_url": f"{base}/t/{t['slug']}/logo.png" if t["logo"] else "",
    }


class TenantAdminIn(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(default="Administrator", max_length=80)


@app.post("/api/admin/tenants/{tid}/admin")
def tenant_add_admin(tid: int, body: TenantAdminIn, u=Depends(super_user)):
    with db() as c:
        if not tenant_by_id(c, tid):
            raise HTTPException(404, "Unknown workspace")
        try:
            c.execute(
                "INSERT INTO users (tenant_id, username, full_name, pw_hash, role, created) "
                "VALUES (?,?,?,?,?,?)",
                (tid, body.username.strip(), body.full_name.strip(), hash_pw(body.password),
                 "admin", time.time()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Username already exists in this workspace")
    audit(u["username"], "tenant-add-admin", detail=body.username.strip(), tenant_id=tid)
    return {"ok": True}


# --- ExelixisHub API (API key) — the platform owner's own tenant ------------
@app.get("/api/hub/devices", dependencies=[Depends(hub_auth)])
def hub_devices():
    with db() as c:
        tid = hub_tenant_id(c)
        rows = c.execute("SELECT * FROM devices WHERE tenant_id=? ORDER BY name COLLATE NOCASE",
                         (tid,)).fetchall()
    return [device_view(r) for r in rows]


@app.post("/api/hub/devices/{rd_id}/connect")
def hub_connect(rd_id: str, x_hub_user: str = Header(default="user"), source: str = Depends(hub_auth)):
    with db() as c:
        tid = hub_tenant_id(c)
        r = get_device(c, tid, rd_id)
        t = tenant_by_id(c, tid)
    audit(f"{source}:{x_hub_user[:60]}", "connect", rd_id, r["name"], tenant_id=tid)
    return {"link": connect_link(t["app_uri"], rd_id, dec(r["pw_enc"]))}


@app.patch("/api/hub/devices/{rd_id}")
def hub_edit(rd_id: str, body: DeviceEdit, x_hub_user: str = Header(default="user"),
             source: str = Depends(hub_auth)):
    with db() as c:
        tid = hub_tenant_id(c)
        get_device(c, tid, rd_id)
        fields = {k: v.strip() for k, v in body.model_dump().items()
                  if v is not None and isinstance(v, str)}
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            c.execute(f"UPDATE devices SET {sets} WHERE tenant_id=? AND rd_id=?",
                      (*fields.values(), tid, rd_id))
    if fields:
        audit(f"{source}:{x_hub_user[:60]}", "edit", rd_id,
              json.dumps(fields, ensure_ascii=False), tenant_id=tid)
    return {"ok": True}


# --- exUpdates client (central updates/deploy manager) ----------------------
_EXUP = {"last_ok": 0.0, "last_err": "", "latest": "", "update": False}


def exupdates_enabled() -> bool:
    return bool(EXUPDATES_URL)


def _exupdates_post(path: str, payload: dict) -> dict:
    import urllib.request
    req = urllib.request.Request(
        EXUPDATES_URL + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "exsupport-panel",
                 "X-Updates-Key": EXUPDATES_KEY})
    with urllib.request.urlopen(req, timeout=6) as r:
        return json.load(r)


def exupdates_heartbeat() -> None:
    """Report this panel's version/status to exUpdates and learn the latest version."""
    try:
        data = _exupdates_post("/api/app/heartbeat", {
            "app_id": EXUPDATES_APP_ID, "instance": EXUPDATES_INSTANCE,
            "kind": "panel", "version": PANEL_VERSION, "status": "running"})
        _EXUP["last_ok"] = time.time()
        _EXUP["last_err"] = ""
        if isinstance(data, dict):
            latest = str(data.get("latest", "") or "")
            _EXUP["latest"] = latest
            _EXUP["update"] = bool(latest and _is_older(PANEL_VERSION, latest))
    except Exception as e:
        _EXUP["last_err"] = str(e)[:200]


def _exupdates_loop() -> None:
    while True:
        exupdates_heartbeat()
        time.sleep(900)


@app.get("/api/platform/exupdates")
def platform_exupdates(u=Depends(super_user)):
    return {
        "enabled": exupdates_enabled(),
        "url": EXUPDATES_URL,
        "app_id": EXUPDATES_APP_ID,
        "instance": EXUPDATES_INSTANCE,
        "panel_version": PANEL_VERSION,
        "latest": _EXUP["latest"],
        "update_available": _EXUP["update"],
        "last_ok": _EXUP["last_ok"],
        "last_error": _EXUP["last_err"],
    }


# --- web page ----------------------------------------------------------------
@app.get("/api/changelog")
def changelog(u=Depends(current_user)):
    return {"version": PANEL_VERSION, "markdown": _read_changelog()}


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": PANEL_VERSION}


_CSP_COMMON = (
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "connect-src 'self'; "
    "default-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
# Non-HTML responses (API/JSON, downloads) need no scripts at all.
CSP = "script-src 'self'; " + _CSP_COMMON
# A served logo must never execute anything — defends against a malicious SVG logo
# being opened directly (it would otherwise run in our origin).
LOGO_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


def _page_csp(nonce: str) -> str:
    # The single inline <script> runs only with this per-request nonce, so an
    # injected inline script (XSS) will not execute. No 'unsafe-inline' for scripts.
    return f"script-src 'self' 'nonce-{nonce}'; " + _CSP_COMMON


def _spa() -> Response:
    nonce = secrets.token_urlsafe(16)
    try:
        with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
            page = f.read()
    except OSError:
        raise HTTPException(500, "UI not available")
    page = page.replace("<script>", f'<script nonce="{nonce}">', 1)
    return Response(page, media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store",
                             "Content-Security-Policy": _page_csp(nonce)})


@app.get("/")
def index():
    return _spa()


@app.get("/t/{slug}")
def tenant_page(slug: str):
    return _spa()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    # Endpoints that set their own CSP (the SPA page, the logo) keep it.
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if COOKIE_SECURE:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


init_db()
if exupdates_enabled():
    threading.Thread(target=_exupdates_loop, daemon=True, name="exupdates").start()
