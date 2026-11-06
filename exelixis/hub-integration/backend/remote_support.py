"""ExelixisHub - Remote Support module (FastAPI router).

Talks to the Exelixisnet IT Support panel (https://rustdesk.exelixisnet.gr)
with the Hub API key, so the panel's key never reaches the browser.

Settings (environment):
    SUPPORT_PANEL_URL      default https://rustdesk.exelixisnet.gr
    SUPPORT_PANEL_API_KEY  PANEL_HUB_API_KEY from the panel's .env

Hook up in the Hub:
    from .remote_support import router as remote_support_router
    app.include_router(remote_support_router, prefix="/api/remote-support")

Adapt the three functions marked ADAPT to the Hub's own auth and data model.
"""
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

PANEL_URL = os.environ.get("SUPPORT_PANEL_URL", "https://rustdesk.exelixisnet.gr").rstrip("/")
PANEL_KEY = os.environ.get("SUPPORT_PANEL_API_KEY", "")

router = APIRouter(tags=["remote-support"])


# --- ADAPT: Hub auth and assignments -----------------------------------------
def current_hub_user():
    """ADAPT: return the logged-in Hub user (use the Hub's existing dependency).
    Must expose: .username, .role in {"admin", "technician", "customer"}, .id"""
    raise NotImplementedError("Wire this to the Hub's auth dependency")


def allowed_device_ids(user) -> Optional[set]:
    """ADAPT: which panel device IDs this user may see.
    None = all (admin). For technicians: IDs of PCs assigned to them or to their
    customers. For customers: IDs of their own PCs (no Connect for customers).
    Store assignments in a Hub table, e.g.
        remote_pcs(rd_id TEXT PK, customer_id FK NULL, technician_ids via link table)"""
    if user.role == "admin":
        return None
    raise NotImplementedError("Look up assignments in the Hub database")


def can_connect(user) -> bool:
    """ADAPT: only staff may open remote sessions."""
    return user.role in ("admin", "technician")


# --- panel client --------------------------------------------------------------
def _headers(user) -> dict:
    if not PANEL_KEY:
        raise HTTPException(503, "SUPPORT_PANEL_API_KEY is not configured")
    return {"X-Api-Key": PANEL_KEY, "X-Hub-User": str(user.username)[:60]}


async def _panel(method: str, path: str, user, json: Optional[dict] = None):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.request(method, f"{PANEL_URL}{path}", headers=_headers(user), json=json)
    except httpx.HTTPError:
        raise HTTPException(502, "Support panel unreachable")
    if r.status_code == 404:
        raise HTTPException(404, "Unknown PC")
    if r.status_code >= 400:
        raise HTTPException(502, f"Support panel error {r.status_code}")
    return r.json()


def _check_access(user, rd_id: str):
    allowed = allowed_device_ids(user)
    if allowed is not None and rd_id not in allowed:
        raise HTTPException(404, "Unknown PC")


# --- routes --------------------------------------------------------------------
@router.get("/devices")
async def list_devices(user=Depends(current_hub_user)):
    """PCs the user may see: id, name, phone, notes, hostname, os, online, last_seen."""
    devices = await _panel("GET", "/api/hub/devices", user)
    allowed = allowed_device_ids(user)
    if allowed is not None:
        devices = [d for d in devices if d["id"] in allowed]
    return devices


@router.post("/devices/{rd_id}/connect")
async def connect(rd_id: str, user=Depends(current_hub_user)):
    """Returns {link}; the browser opens it and the Exelixisnet IT Support app connects."""
    if not can_connect(user):
        raise HTTPException(403, "Not allowed")
    _check_access(user, rd_id)
    return await _panel("POST", f"/api/hub/devices/{rd_id}/connect", user)


class DeviceEdit(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=40)
    notes: Optional[str] = Field(default=None, max_length=2000)


@router.patch("/devices/{rd_id}")
async def edit(rd_id: str, body: DeviceEdit, user=Depends(current_hub_user)):
    if not can_connect(user):
        raise HTTPException(403, "Not allowed")
    _check_access(user, rd_id)
    return await _panel("PATCH", f"/api/hub/devices/{rd_id}", user, json=body.model_dump(exclude_none=True))
