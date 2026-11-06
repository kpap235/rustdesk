"""Exelixisnet IT Support panel.

Customer PCs running the Exelixisnet IT Support app register here with their
RustDesk ID, a random permanent password and the customer's name. Technicians
log in, see who is online and connect with one click. ExelixisHub reads the
same data through the /api/hub endpoints with an API key.
"""
import base64
import hashlib
import hmac
import json
import os
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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# --- configuration (environment) -------------------------------------------
DB_PATH = os.environ.get("PANEL_DB", "/data/panel.db")
SESSION_SECRET = os.environ["PANEL_SESSION_SECRET"].encode()
FERNET = Fernet(os.environ["PANEL_FERNET_KEY"].encode())
ENROLL_TOKEN = os.environ["PANEL_ENROLL_TOKEN"]
HUB_API_KEY = os.environ.get("PANEL_HUB_API_KEY", "")
MONITOR_API_KEY = os.environ.get("PANEL_MONITOR_API_KEY", "")
APP_URI = os.environ.get("PANEL_APP_URI", "exelixisnetitsupport")
ONLINE_SECONDS = int(os.environ.get("PANEL_ONLINE_SECONDS", "180"))
SESSION_HOURS = int(os.environ.get("PANEL_SESSION_HOURS", "12"))
COOKIE_SECURE = os.environ.get("PANEL_COOKIE_SECURE", "1") == "1"
ISSUER = "Exelixisnet IT Support"

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
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL DEFAULT '',
                pw_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin','tech')),
                totp_secret TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                session_gen INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS devices (
                rd_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                hostname TEXT NOT NULL DEFAULT '',
                os TEXT NOT NULL DEFAULT '',
                app_version TEXT NOT NULL DEFAULT '',
                pw_enc TEXT NOT NULL DEFAULT '',
                secret_hash TEXT NOT NULL,
                last_ip TEXT NOT NULL DEFAULT '',
                created REAL NOT NULL,
                last_seen REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY,
                ts REAL NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                rd_id TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT ''
            );
            """
        )
        if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            user = os.environ.get("PANEL_ADMIN_USER", "admin")
            pw = os.environ.get("PANEL_ADMIN_PASSWORD")
            if not pw:
                raise SystemExit("Set PANEL_ADMIN_PASSWORD for the first start")
            c.execute(
                "INSERT INTO users (username, full_name, pw_hash, role, created) VALUES (?,?,?,?,?)",
                (user, "Administrator", hash_pw(pw), "admin", time.time()),
            )


def audit(actor: str, action: str, rd_id: str = "", detail: str = "") -> None:
    with db() as c:
        c.execute(
            "INSERT INTO audit (ts, actor, action, rd_id, detail) VALUES (?,?,?,?,?)",
            (time.time(), actor, action, rd_id, detail),
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


# --- auth dependencies -------------------------------------------------------
def current_user(request: Request) -> sqlite3.Row:
    tok = request.cookies.get("exs_session", "")
    sess = read_session(tok)
    if not sess:
        raise HTTPException(401, "Not logged in")
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE id=? AND active=1", (sess[0],)).fetchone()
    if not u or u["session_gen"] != sess[1]:
        raise HTTPException(401, "Not logged in")
    return u


def admin_user(u=Depends(current_user)) -> sqlite3.Row:
    if u["role"] != "admin":
        raise HTTPException(403, "Admins only")
    return u


def hub_auth(x_api_key: str = Header(default="")) -> str:
    """API key for other Exelixisnet systems. Returns which system is calling."""
    for name, key in (("hub", HUB_API_KEY), ("monitor", MONITOR_API_KEY)):
        if key and hmac.compare_digest(x_api_key, key):
            return name
    raise HTTPException(401, "Bad API key")


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
    }


def connect_link(rd_id: str, pw: str) -> str:
    link = f"{APP_URI}://connection/new/{quote(rd_id)}"
    if pw:
        link += "?password=" + quote(pw, safe="")
    return link


def get_device(rd_id: str) -> sqlite3.Row:
    with db() as c:
        r = c.execute("SELECT * FROM devices WHERE rd_id=?", (rd_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Unknown device")
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


class HeartbeatIn(BaseModel):
    id: str = Field(min_length=3, max_length=40)
    secret: str = Field(min_length=10, max_length=128)
    version: str = Field(default="", max_length=40)
    hostname: str = Field(default="", max_length=120)
    password: str = Field(default="", max_length=128)
    # When the ID changes (rare), the app sends its previous ID here.
    old_id: str = Field(default="", max_length=40)


@app.post("/api/client/register")
def client_register(body: RegisterIn, request: Request, x_enroll_token: str = Header(default="")):
    if not hmac.compare_digest(x_enroll_token, ENROLL_TOKEN):
        raise HTTPException(401, "Bad enrollment token")
    secret = secrets.token_urlsafe(32)
    now = time.time()
    ip = client_ip(request)
    with db() as c:
        existed = c.execute("SELECT 1 FROM devices WHERE rd_id=?", (body.id,)).fetchone()
        c.execute(
            """INSERT INTO devices (rd_id, name, phone, hostname, os, app_version, pw_enc,
                                    secret_hash, last_ip, created, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(rd_id) DO UPDATE SET name=excluded.name, phone=excluded.phone,
                 hostname=excluded.hostname, os=excluded.os, app_version=excluded.app_version,
                 pw_enc=excluded.pw_enc, secret_hash=excluded.secret_hash,
                 last_ip=excluded.last_ip, last_seen=excluded.last_seen""",
            (body.id, body.name.strip(), body.phone.strip(), body.hostname, body.os,
             body.version, enc(body.password), sha256(secret), ip, now, now),
        )
    audit("client", "re-register" if existed else "register", body.id, f"{body.name} from {ip}")
    return {"secret": secret}


@app.post("/api/client/heartbeat")
def client_heartbeat(body: HeartbeatIn, request: Request):
    lookup = body.old_id or body.id
    with db() as c:
        r = c.execute("SELECT * FROM devices WHERE rd_id=?", (lookup,)).fetchone()
        if not r or not hmac.compare_digest(r["secret_hash"], sha256(body.secret)):
            raise HTTPException(401, "Unknown device")  # app re-registers on 401
        fields = {"last_seen": time.time(), "last_ip": client_ip(request)}
        if body.version:
            fields["app_version"] = body.version
        if body.hostname:
            fields["hostname"] = body.hostname
        if body.password:
            fields["pw_enc"] = enc(body.password)
        if body.old_id and body.old_id != body.id:
            if c.execute("SELECT 1 FROM devices WHERE rd_id=?", (body.id,)).fetchone():
                c.execute("DELETE FROM devices WHERE rd_id=?", (body.id,))
            fields["rd_id"] = body.id
        sets = ", ".join(f"{k}=?" for k in fields)
        c.execute(f"UPDATE devices SET {sets} WHERE rd_id=?", (*fields.values(), lookup))
    if body.old_id and body.old_id != body.id:
        audit("client", "id-changed", body.id, f"was {body.old_id}")
    if body.password:
        audit("client", "password-updated", body.id)
    return {"ok": True}


# --- technician web API ------------------------------------------------------
class LoginIn(BaseModel):
    username: str
    password: str
    code: str = ""


@app.post("/api/login")
def login(body: LoginIn, request: Request, response: Response):
    key = f"{client_ip(request)}|{body.username.lower()}"
    if too_many_fails(key):
        raise HTTPException(429, "Too many attempts, try again in 15 minutes")
    with db() as c:
        u = c.execute(
            "SELECT * FROM users WHERE username=? AND active=1", (body.username.strip(),)
        ).fetchone()
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
    audit(u["username"], "login", detail=client_ip(request))
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("exs_session")
    return {"ok": True}


@app.get("/api/me")
def me(u=Depends(current_user)):
    return {"username": u["username"], "full_name": u["full_name"], "role": u["role"],
            "totp": bool(u["totp_secret"])}


@app.get("/api/devices")
def list_devices(u=Depends(current_user)):
    with db() as c:
        rows = c.execute("SELECT * FROM devices ORDER BY name COLLATE NOCASE").fetchall()
    return [device_view(r) for r in rows]


@app.post("/api/devices/{rd_id}/connect")
def device_connect(rd_id: str, u=Depends(current_user)):
    r = get_device(rd_id)
    audit(u["username"], "connect", rd_id, r["name"])
    return {"link": connect_link(rd_id, dec(r["pw_enc"]))}


@app.post("/api/devices/{rd_id}/reveal")
def device_reveal(rd_id: str, u=Depends(current_user)):
    r = get_device(rd_id)
    audit(u["username"], "reveal-password", rd_id, r["name"])
    return {"password": dec(r["pw_enc"])}


class DeviceEdit(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=40)
    notes: Optional[str] = Field(default=None, max_length=2000)


@app.patch("/api/devices/{rd_id}")
def device_edit(rd_id: str, body: DeviceEdit, u=Depends(current_user)):
    get_device(rd_id)
    fields = {k: v.strip() for k, v in body.model_dump().items() if v is not None}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        with db() as c:
            c.execute(f"UPDATE devices SET {sets} WHERE rd_id=?", (*fields.values(), rd_id))
        audit(u["username"], "edit", rd_id, json.dumps(fields, ensure_ascii=False))
    return {"ok": True}


@app.delete("/api/devices/{rd_id}")
def device_delete(rd_id: str, u=Depends(admin_user)):
    r = get_device(rd_id)
    with db() as c:
        c.execute("DELETE FROM devices WHERE rd_id=?", (rd_id,))
    audit(u["username"], "delete", rd_id, r["name"])
    return {"ok": True}


@app.get("/api/audit")
def audit_log(limit: int = 200, u=Depends(admin_user)):
    with db() as c:
        rows = c.execute(
            "SELECT ts, actor, action, rd_id, detail FROM audit ORDER BY id DESC LIMIT ?",
            (min(max(limit, 1), 1000),),
        ).fetchall()
    return [dict(r) for r in rows]


# --- users (admin) -----------------------------------------------------------
class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    full_name: str = Field(default="", max_length=80)
    password: str = Field(min_length=10, max_length=128)
    role: str = Field(default="tech", pattern="^(admin|tech)$")


@app.get("/api/users")
def users_list(u=Depends(admin_user)):
    with db() as c:
        rows = c.execute(
            "SELECT id, username, full_name, role, active, totp_secret != '' AS totp FROM users ORDER BY username"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/users")
def users_create(body: UserIn, u=Depends(admin_user)):
    try:
        with db() as c:
            c.execute(
                "INSERT INTO users (username, full_name, pw_hash, role, created) VALUES (?,?,?,?,?)",
                (body.username.strip(), body.full_name.strip(), hash_pw(body.password), body.role, time.time()),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username already exists")
    audit(u["username"], "user-create", detail=f"{body.username} ({body.role})")
    return {"ok": True}


class UserPatch(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=80)
    password: Optional[str] = Field(default=None, min_length=10, max_length=128)
    role: Optional[str] = Field(default=None, pattern="^(admin|tech)$")
    active: Optional[bool] = None
    reset_2fa: bool = False


@app.patch("/api/users/{uid}")
def users_edit(uid: int, body: UserPatch, u=Depends(admin_user)):
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
        fields["active"] = 1 if body.active else 0
    if body.reset_2fa:
        fields["totp_secret"] = ""
    if not fields:
        return {"ok": True}
    with db() as c:
        sets = ", ".join(f"{k}=?" for k in fields)
        # Any change to password, role or status logs the user out everywhere.
        c.execute(f"UPDATE users SET {sets}, session_gen=session_gen+1 WHERE id=?", (*fields.values(), uid))
    audit(u["username"], "user-edit", detail=f"user {uid}: {', '.join(fields)}")
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
        c.execute("UPDATE users SET pw_hash=?, session_gen=session_gen+1 WHERE id=?", (hash_pw(body.new), u["id"]))
        gen = c.execute("SELECT session_gen FROM users WHERE id=?", (u["id"],)).fetchone()[0]
    response.set_cookie("exs_session", sign_session(u["id"], gen), httponly=True,
                        secure=COOKIE_SECURE, samesite="strict", max_age=SESSION_HOURS * 3600)
    audit(u["username"], "password-change")
    return {"ok": True}


_pending_totp: dict = {}


@app.post("/api/me/2fa/start")
def me_2fa_start(u=Depends(current_user)):
    secret = pyotp.random_base32()
    _pending_totp[u["id"]] = secret
    uri = pyotp.TOTP(secret).provisioning_uri(name=u["username"], issuer_name=ISSUER)
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
    audit(u["username"], "2fa-enabled")
    return {"ok": True}


# --- ExelixisHub API (API key) ----------------------------------------------
@app.get("/api/hub/devices", dependencies=[Depends(hub_auth)])
def hub_devices():
    """Also used by the MikroTik VPN Monitoring site (with its own key)."""
    with db() as c:
        rows = c.execute("SELECT * FROM devices ORDER BY name COLLATE NOCASE").fetchall()
    return [device_view(r) for r in rows]


@app.post("/api/hub/devices/{rd_id}/connect")
def hub_connect(rd_id: str, x_hub_user: str = Header(default="user"), source: str = Depends(hub_auth)):
    r = get_device(rd_id)
    audit(f"{source}:{x_hub_user[:60]}", "connect", rd_id, r["name"])
    return {"link": connect_link(rd_id, dec(r["pw_enc"]))}


@app.patch("/api/hub/devices/{rd_id}")
def hub_edit(rd_id: str, body: DeviceEdit, x_hub_user: str = Header(default="user"), source: str = Depends(hub_auth)):
    get_device(rd_id)
    fields = {k: v.strip() for k, v in body.model_dump().items() if v is not None}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        with db() as c:
            c.execute(f"UPDATE devices SET {sets} WHERE rd_id=?", (*fields.values(), rd_id))
        audit(f"{source}:{x_hub_user[:60]}", "edit", rd_id, json.dumps(fields, ensure_ascii=False))
    return {"ok": True}


# --- web page ----------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


init_db()
