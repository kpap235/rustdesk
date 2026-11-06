# ExelixisHub — Remote Support module (handoff)

**For the ExelixisHub project.** Add a *Remote Support* module that shows the customer PCs
running the **Exelixisnet IT Support** app (the branded RustDesk client) and lets technicians
connect with one click. The data comes from the support panel at
`https://rustdesk.exelixisnet.gr`, which is already running.

## What's here

| File | Purpose |
|---|---|
| `backend/remote_support.py` | FastAPI router: proxies to the panel with the Hub API key; filters by assignment |
| `frontend/RemoteSupport.jsx` | React page: search, online status, Connect, edit name/phone/notes |

Copy both into the Hub, then fill in the three `ADAPT` functions in the router:
`current_hub_user` (Hub's auth dependency), `allowed_device_ids` (assignments) and `can_connect`.

## Hub configuration

```
SUPPORT_PANEL_URL=https://rustdesk.exelixisnet.gr
SUPPORT_PANEL_API_KEY=<PANEL_HUB_API_KEY from /opt/exsupport-panel/.env on the RustDesk VPS>
```

Register the router: `app.include_router(remote_support_router, prefix="/api/remote-support")`,
and add a **Remote Support** menu entry for admins and technicians.

## Assignments (Hub side)

Follow the Hub's existing pattern (a service can belong to a customer and/or one or more technicians):

- Table `remote_pcs(rd_id TEXT PRIMARY KEY, customer_id NULL)` plus a link table to technicians.
- Admin UI: on a customer's page, "Remote PCs" → pick from the panel's list (`GET /api/remote-support/devices`)
  and attach it to that customer; optionally to technicians.
- Admins see all PCs; technicians see PCs of their customers or assigned directly; customers see
  their own PCs (status only, no Connect).

## Panel API (called only from the Hub backend)

Headers: `X-Api-Key: <key>`, optional `X-Hub-User: <username>` (shown in the panel's Activity log).

| Call | Returns |
|---|---|
| `GET /api/hub/devices` | `[{id, name, phone, notes, hostname, os, app_version, online, last_seen, created, has_password}]` |
| `POST /api/hub/devices/{id}/connect` | `{link}` — `exelixisnetitsupport://connection/new/<id>?password=…` |
| `PATCH /api/hub/devices/{id}` | body `{name?, phone?, notes?}` |

`online` is true when the PC reported in during the last 3 minutes. `last_seen` is a Unix timestamp.

## Notes

- The Connect link opens the **Exelixisnet IT Support** app on the technician's own computer,
  so it must be installed there.
- The link contains the PC's password: never log it or show it in the Hub UI.
- Keep `SUPPORT_PANEL_API_KEY` server-side only.
