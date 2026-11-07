# Exelixisnet IT Support — change log

Versions follow `MAJOR.MINOR.PATCH`:
**MAJOR** for big changes that need customers to reinstall, **MINOR** for new features,
**PATCH** for fixes only. Every build publishes a GitHub release `vX.Y.Z` whose notes are
the matching section below.

**How to release a new version:** add a new section at the top of this file, change
`exelixis/VERSION` to the same number, push, then run the
"Exelixisnet IT Support - build (Windows + Android)" workflow. The build stops if that
version was already released, so every release has its own number and notes.

Based on RustDesk (AGPL-3.0); the RustDesk version each release is built on is shown in brackets.

## 1.1.0 — 2026-11-07 (RustDesk 1.5.1)

**Important:** the app was renamed, so existing test installs must be uninstalled and the new
file installed. One Windows download now comes in two forms, by file name:

### exSupport — the full program for you and your technicians (Windows)
- All features, for connecting out to customers. Does not register itself with the panel and
  asks no questions on first run. Its links use the `exsupport://` scheme.

### exQuickSupport — the locked customer build (Windows and Android)
- Runs without installing, incoming connections only, with all settings locked.
- Registers itself with the panel automatically — no name question. It stores a hidden random
  access password (which the customer can never see or change) and reports the computer name,
  local network address, signed-in user and system. The customer can only refresh the one-time
  code shown on screen.
- **Install** button: keeps the app on the computer and starts the service automatically, with
  no further questions.
- An **Instructions** panel (Greek and English) explains how to get help, what happens when we
  connect, what Install does and how privacy is handled.
- Android: a **Guide** tab walks the customer through granting every permission (screen sharing,
  control/accessibility, files, notifications, display-over-apps, battery, start on boot), each
  with a green tick when done. No more folder prompt on every start. WebSocket stays off.

### Panel
- Each computer shows a **Quick / Full** badge, its **local network address** and the
  **signed-in Windows user**; search matches these too.
- **Downloads** page has three links (exSupport, exQuickSupport Windows, exQuickSupport Android)
  with stable short links `/get/exsupport`, `/get/quick`, `/get/android`.
- Updated setup guide (PDF, Greek and English) for the new names and the customer flow.

## 1.0.2 — 2026-11-07 (RustDesk 1.5.1)

### App (Windows and Android)
- Removed the wrong tip "For faster connection, please set up your own server": the app now
  knows rustdesk.exelixisnet.gr is our own server (connections already went through it).
- Account and address-book requests now go to our server instead of RustDesk's public site,
  as in any standard self-hosted setup.
- Exelixisnet colours: red buttons, links and switches, logo-blue ID number and information messages.
- "IT Support", phone, e-mail and version are now centred under the logo.

## 1.0.1 — 2026-11-07 (RustDesk 1.5.1)

### App (Windows)
- Fixed: installation stopped with "Windows cannot find ...\\ExelixisnetITSupport.exe" and
  "install failed with elevated exit code 9059". The installer package now contains the
  program as ExelixisnetITSupport.exe, so nothing has to be renamed while installing.

## 1.0.0 — 2026-11-06 (RustDesk 1.5.1)

### App (Windows and Android)
- Named **Exelixisnet IT Support**, with the Exelixisnet icon and logo.
- Server `rustdesk.exelixisnet.gr` and its key built in: nothing to configure.
- Support phone 2615 00 2000 and info@exelixisnet.gr on the home screen.
- After installation on Windows, asks the customer's name or company (and optional phone),
  sets a random permanent password and registers the computer with the support panel.
- Reports to the panel every minute, so technicians see who is online; registers again by
  itself if the panel was offline or the computer's ID changed.
- Automatic updates from the stock RustDesk are switched off.
- Android app installs next to the stock RustDesk (package `eu.exelixisnet.itsupport`).
- Fixed: installing on Windows stopped with "Windows cannot find ...ExelixisnetITSupport.exe"
  (the test build before 1.0.0 did not rename the program file during installation).

### Support panel (rustdesk.exelixisnet.gr)
- Customer list with search, online/offline filter and one-click **Connect**.
- Customer details: name, phone, notes, view access password.
- Technician accounts with Administrator/Technician roles and two-factor sign-in.
- Activity log of sign-ins, connections and changes.
- API for ExelixisHub and the MikroTik VPN Monitoring site, each with its own key.
- New design: side menu, large search (Enter connects to the first result), light and dark mode.
