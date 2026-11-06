# MikroTik VPN Monitoring — Remote Support add-on (handoff)

**For the "Mikrotik VPN Monitoring" project (Exelixis Monitor).** Show the customer PCs running
**Exelixisnet IT Support** next to each router, with online status and one-click **Connect**.
Data comes from the support panel at `https://rustdesk.exelixisnet.gr`.

## What's here

`remote_support.py` — FastAPI router (if the Monitor uses another framework, reuse
`get_devices`, `match_to_routers` and the panel calls as plain functions).

Fill in the two `ADAPT` functions: `current_user` (Monitor login) and `router_public_ips`
(`{router_id: public_ip}` — e.g. from each router's `/ip/cloud` public address, or the
`caller-id` of its OVPN session on the CHR).

## Configuration

```
SUPPORT_PANEL_URL=https://rustdesk.exelixisnet.gr
SUPPORT_PANEL_API_KEY=<PANEL_MONITOR_API_KEY from /opt/exsupport-panel/.env on the RustDesk VPS>
```

The Monitor has its own key (not the Hub's), so it can be revoked separately; its actions appear
in the panel's Activity log as `monitor:<username>`.

## Suggested UI

- Router list: a **PCs** badge (`3 · 2 online`) from `GET /api/remote-support/by-router`.
- Router page: a **Customer PCs** table (name, PC name, online/last seen, **Connect**) from
  `GET /api/remote-support/routers/{router_id}/devices`.
- Connect: `POST /api/remote-support/devices/{id}/connect` → open the returned `link` in the browser;
  it starts the Exelixisnet IT Support app on the technician's computer (must be installed).

## Panel API (server-side only)

Headers `X-Api-Key`, optional `X-Hub-User`. `GET /api/hub/devices` →
`[{id, name, phone, notes, hostname, os, app_version, online, last_seen, last_ip, ...}]`;
`POST /api/hub/devices/{id}/connect` → `{link}`.

Matching is by public IP, so it only works for PCs whose internet goes out through that router,
and PCs behind a router that shares its public IP with others (CGNAT) may match several routers.
Never log the connect link: it contains the PC's password.
