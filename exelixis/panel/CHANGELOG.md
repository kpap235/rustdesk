# Support panel — change log

The newest version is at the top; its number is the panel's version.
To release a panel change: add a section here, then update the VPS.

## 1.9.0 — 2026-11-08
- **Support requests ("Call for help"):** when a customer asks for help from the app, it shows as
  a banner at the top of Computers with Claim / Connect / Done, and a counter on the menu.
- **Connect by customer:** a "Group by customer" toggle, and search now matches the customer name.
- **"Needs update" filter** flags computers running an app older than the latest release.
- **"In session" indicator** shows which computers a technician is connected to right now.
- **Sessions page:** the full time log — add a note per session and untick one to exclude it from
  billing (the dashboard then charges only billable time). Visible to supervisors and admins.
- Each computer row now shows its **Windows version, RAM and disk** at a glance (not only in Details).
- A **Refresh** button on Computers to update the list instantly (it still auto-refreshes every 30s).

## 1.8.0 — 2026-11-07
- New **Supervisor** role between Administrator and Technician: supervisors manage technicians and
  customers and can hide computers from technicians, but do not see rates or € amounts (billing
  stays admin-only). Administrators can also **hide a computer from supervisors**.
- Redesigned the **computer row**: name on top, then local IP and WAN IP, then the ID; the
  customer and the app version now show in the row, and Online sits next to Connect.
- A computer's details now show the reported **Windows version, RAM and disk size** (from app 1.4.0).
- **Security hardening:** Content-Security-Policy, HSTS (over HTTPS), Permissions-Policy and
  `Cache-Control: no-store` on the API, on top of the existing strict/secure cookies, login
  rate-limiting, scrypt passwords and 2FA. The whole panel is confirmed responsive on phones.

## 1.7.0 — 2026-11-07
- New **Dashboard** with this month's figures: computers online, sessions in progress, hours
  worked, amount charged (admins), and a six-month hours chart, plus **time and charges per
  customer** and **per computer**.
- New **Customers** page: add clients, set a per-customer hourly rate (or use a global default),
  and see how many computers each has. Each computer can be **assigned to a customer** from its
  details, so support time rolls up per customer.
- **Billing** is admin-only: technicians see hours and stats but not rates or € amounts.
- Support time is measured automatically from the app (needs app 1.3.0 or newer on the customer's
  computer); the computer list was renamed **Computers**.
- New `/api/appversion` endpoint so the apps can check for a newer version and offer to update;
  the latest version is read from the newest GitHub release (cached), overridable via an
  `app_version` setting.

## 1.6.0 — 2026-11-07
- **Hide computers from technicians:** in a computer's details an administrator can tick
  "Hide this computer from technicians". Hidden computers (and their passwords) are visible and
  connectable only to administrators; they carry a **Hidden** badge in the admin's list.
- **Add a computer by hand:** a new **+ Add computer** button (admins) lets you register a
  machine that didn't enrol itself — a plain RustDesk, a server, or one set up manually — by its
  ID and password. The dialog explains where to find the ID and how to set a permanent password.
  Such entries show a **Manual** badge.

## 1.5.0 — 2026-11-07
- **Sign-in page** now shows customers how to get the app: download buttons (with icons) for
  **exQuickSupport** on Windows and Android, and links to the setup guide (Greek and English).
- Added a **consent statement** — by downloading and installing the app the customer agrees to
  be supported remotely by ExelixisNet — and a short **GDPR notice** about what is processed.

## 1.4.0 — 2026-11-07
- Each computer now shows a **Quick / Full** badge, its **local network address** and the
  **signed-in Windows user**, so you can tell machines apart at a glance. Search matches these too.
- **Downloads** page now has three links: exSupport (technicians), exQuickSupport for Windows and
  exQuickSupport for Android. Short links: `/get/exsupport`, `/get/quick`, `/get/android`.
- Connect links use the `exsupport://` scheme to match the renamed technician app.

## 1.3.0 — 2026-11-07
- Short links for customers that never change: `/get/windows`, `/get/android` (they lead to the
  links set on the Downloads page) and the setup guide `/guide/el`, `/guide/en`.
- Illustrated setup guide (PDF, Greek and English) for Windows and Android, with QR codes.

## 1.2.0 — 2026-11-07
- New **Downloads** page with the links to the Windows and Android app, ready to copy and send
  to customers. Administrators can change the links when a new version is released.

## 1.1.0 — 2026-11-07
- New **What's new** page with this change log, so everyone can see what changed and when.
- The panel version is shown on the sign-in page and at the bottom of the side menu.

## 1.0.0 — 2026-11-06
- Customer list with search, Online/Offline filter and one-click **Connect** (Enter connects to the first result).
- Customer details: name, phone, notes, and the access password on request.
- Technician accounts with Administrator and Technician roles, and two-factor sign-in.
- Activity log of sign-ins, connections, viewed passwords and changes.
- API for ExelixisHub and MikroTik VPN Monitoring, each with its own key.
- Exelixisnet design with light and dark mode, works on phones.
