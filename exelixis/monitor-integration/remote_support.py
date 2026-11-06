"""MikroTik VPN Monitoring (Exelixis Monitor) - Remote Support add-on.

Shows the customer PCs running Exelixisnet IT Support next to each router and
lets staff connect with one click. Data comes from the support panel
(https://rustdesk.exelixisnet.gr) with the Monitor's own API key.

How PCs are matched to routers: each PC reports in from its site's public IP
(`last_ip`). A router whose WAN/public IP equals that address is the router the
PC sits behind. The Monitor already knows each router's public IP (for example
from /ip/cloud or the CHR's PPP "caller-id" of the OVPN session).

Settings (environment):
    SUPPORT_PANEL_URL      default https://rustdesk.exelixisnet.gr
    SUPPORT_PANEL_API_KEY  PANEL_MONITOR_API_KEY from the panel's .env

FastAPI hook-up:
    from .remote_support import router as remote_support_router
    app.include_router(remote_support_router, prefix="/api/remote-support")

Fill in the two ADAPT functions for the Monitor's own login and router data.
"""
import os
import time
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

PANEL_URL = os.environ.get("SUPPORT_PANEL_URL", "https://rustdesk.exelixisnet.gr").rstrip("/")
PANEL_KEY = os.environ.get("SUPPORT_PANEL_API_KEY", "")
CACHE_SECONDS = 30

router = APIRouter(tags=["remote-support"])


# --- ADAPT ---------------------------------------------------------------------
def current_user():
    """ADAPT: the Monitor's logged-in user dependency. Must expose .username."""
    raise NotImplementedError("Wire this to the Monitor's auth dependency")


def router_public_ips() -> Dict[str, str]:
    """ADAPT: {router_id: public_ip} for the routers the Monitor tracks,
    e.g. router_id = PPP secret name or its OVPN IP (10.30.16.x / 10.30.64.x)."""
    raise NotImplementedError("Return each router's current public IP")


# --- panel client ----------------------------------------------------------------
_cache: dict = {"ts": 0.0, "devices": []}


async def _panel(method: str, path: str, username: str) -> object:
    if not PANEL_KEY:
        raise HTTPException(503, "SUPPORT_PANEL_API_KEY is not configured")
    headers = {"X-Api-Key": PANEL_KEY, "X-Hub-User": username[:60]}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.request(method, f"{PANEL_URL}{path}", headers=headers)
    except httpx.HTTPError:
        raise HTTPException(502, "Support panel unreachable")
    if r.status_code == 404:
        raise HTTPException(404, "Unknown PC")
    if r.status_code >= 400:
        raise HTTPException(502, f"Support panel error {r.status_code}")
    return r.json()


async def get_devices(username: str) -> List[dict]:
    """All PCs from the panel, cached briefly so router pages stay fast."""
    if time.time() - _cache["ts"] > CACHE_SECONDS:
        _cache["devices"] = await _panel("GET", "/api/hub/devices", username)
        _cache["ts"] = time.time()
    return _cache["devices"]


def match_to_routers(devices: List[dict], ips: Dict[str, str]) -> Dict[str, List[dict]]:
    """{router_id: [pcs behind it]} by public IP. PCs with no match go under "".
    Note: PCs report their IP every minute; a router whose public IP changed
    shows its PCs again after their next report."""
    by_ip: Dict[str, List[str]] = {}
    for rid, ip in ips.items():
        if ip:
            by_ip.setdefault(ip, []).append(rid)
    out: Dict[str, List[dict]] = {}
    for d in devices:
        rids = by_ip.get(d.get("last_ip", ""), [""])
        for rid in rids:
            out.setdefault(rid, []).append(d)
    return out


# --- routes ----------------------------------------------------------------------
@router.get("/devices")
async def all_devices(user=Depends(current_user)):
    return await get_devices(user.username)


@router.get("/by-router")
async def devices_by_router(user=Depends(current_user)):
    """{router_id: [pcs]} - use it to show a "PCs" column/badge on the router list."""
    return match_to_routers(await get_devices(user.username), router_public_ips())


@router.get("/routers/{router_id}/devices")
async def router_devices(router_id: str, user=Depends(current_user)):
    ips = router_public_ips()
    if router_id not in ips:
        raise HTTPException(404, "Unknown router")
    return match_to_routers(await get_devices(user.username), {router_id: ips[router_id]}).get(router_id, [])


@router.post("/devices/{rd_id}/connect")
async def connect(rd_id: str, user=Depends(current_user)):
    """Returns {link}; open it in the browser to start Exelixisnet IT Support."""
    return await _panel("POST", f"/api/hub/devices/{rd_id}/connect", user.username)
