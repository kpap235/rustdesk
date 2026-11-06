# Exelixisnet IT Support

Branded RustDesk client for Exelixisnet, plus the support panel that lists customer PCs.
Based on [RustDesk](https://github.com/rustdesk/rustdesk) (AGPL-3.0); this fork's source stays public.

## Client changes

| What | Where |
|---|---|
| Built-in server `rustdesk.exelixisnet.gr`, public key, internal app name | `res/exelixis/apply.py` (applied by CI after checkout) |
| Icons and logo (from `res/exelixis/atom.png`, `exelixisnet-logo.png`) | `res/exelixis/make_icons.py` |
| Name window after install, permanent password, panel registration, heartbeat | `src/exelixis.rs`, `flutter/lib/desktop/widgets/exelixis_register.dart` |
| Windows + Android build | Actions → "Exelixisnet IT Support - build (Windows + Android)" |

The build needs the repository secret **`EXELIXIS_ENROLL_TOKEN`**; the Android app also needs `ANDROID_SIGNING_KEY`, `ANDROID_ALIAS`, `ANDROID_KEY_STORE_PASSWORD`, `ANDROID_KEY_PASSWORD` (Settings → Secrets and variables → Actions).
It must match `PANEL_ENROLL_TOKEN` in the panel's `.env`. Without it the app works but never registers.

## Support panel (`exelixis/panel`)

Runs on the RustDesk VPS with Docker. Caddy gets the HTTPS certificate automatically.

```bash
git clone https://github.com/kpap235/rustdesk.git /opt/exelixis-src --depth 1
cp -r /opt/exelixis-src/exelixis/panel /opt/exsupport-panel && cd /opt/exsupport-panel
sh setup.sh                 # creates .env and prints admin password, enrollment token, Hub API key
docker compose up -d --build
```

Ports 80 and 443 must be free and open. Back up `.env` and `data/` — `PANEL_FERNET_KEY` decrypts the stored passwords.

### API for ExelixisHub

All calls need header `X-Api-Key: <PANEL_HUB_API_KEY>`; optional `X-Hub-User: <technician>` is written to the activity log.

| Call | Purpose |
|---|---|
| `GET /api/hub/devices` | All customer PCs: id, name, phone, notes, hostname, os, online, last_seen |
| `POST /api/hub/devices/{id}/connect` | Returns `{link}` — open it to connect with the stored password |
| `PATCH /api/hub/devices/{id}` | Change name / phone / notes |
