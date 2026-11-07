#!/usr/bin/env python3
"""Build the Exelixisnet IT Support quick guide PDFs (Greek and English).

    python3 exelixis/guide/make_guide.py   # writes exelixis/panel/static/guide-el.pdf and guide-en.pdf

Needs Pillow, qrcode and Playwright with a Chromium/Chrome browser.
The QR codes point at the panel's short links, which never change.
"""
import base64
import html
import io
import os
import sys

import qrcode
import qrcode.image.svg
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "exelixis", "panel", "static")
PANEL = "https://rustdesk.exelixisnet.gr"
CHROME = os.environ.get("CHROME", "/usr/bin/google-chrome")

BLUE, RED, NAVY = "#0B4FA3", "#C21F3A", "#0A2E63"


def data_uri(path, mime):
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


LOGO = data_uri(os.path.join(ROOT, "res", "exelixis", "exelixisnet-logo.png"), "image/png")
ICON = data_uri(os.path.join(ROOT, "res", "exelixis", "app-icon.jpg"), "image/jpeg")


def qr_svg(url):
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
    return img.to_string(encoding="unicode")


T = {
    "el": {
        "lang": "el",
        "title": "Οδηγός εγκατάστασης",
        "subtitle": "Απομακρυσμένη υποστήριξη από την Exelixisnet, σε λίγα βήματα.",
        "intro": "Με την εφαρμογή Exelixisnet IT Support ο τεχνικός μας βλέπει την οθόνη σας και σας βοηθά από απόσταση. Η σύνδεση γίνεται μόνο μέσω του δικού μας ασφαλούς διακομιστή.",
        "scan": "Σαρώστε με το κινητό ή ανοίξτε τον σύνδεσμο",
        "win": "Windows", "and": "Android",
        "win_for": "Για υπολογιστές και laptop",
        "and_for": "Για κινητά και tablet",
        "two_ways": "Δύο τρόποι χρήσης",
        "quick_t": "Γρήγορη βοήθεια", "quick_d": "Ανοίγετε την εφαρμογή, λέτε στον τεχνικό το ID και τον κωδικό. Όταν κλείσετε, δεν μένει τίποτα εγκατεστημένο.",
        "perm_t": "Μόνιμη υποστήριξη", "perm_d": "Εγκαθιστάτε την εφαρμογή μία φορά. Μετά σας βοηθάμε όποτε χρειαστεί, χωρίς να κάνετε τίποτα.",
        "help": "Χρειάζεστε βοήθεια;", "hours": "Δευτέρα–Παρασκευή 09:00–17:00",
        "w_h": "Εγκατάσταση στα Windows",
        "w1_t": "Κατεβάστε την εφαρμογή", "w1_d": "Ανοίξτε τον σύνδεσμο που σας στείλαμε ή σαρώστε τον κωδικό QR της πρώτης σελίδας. Ανοίξτε το αρχείο που κατέβηκε.",
        "w2_t": "Επιτρέψτε την εκκίνηση", "w2_d": "Αν τα Windows εμφανίσουν μπλε προειδοποίηση, πατήστε «Περισσότερες πληροφορίες» και μετά «Εκτέλεση οπωσδήποτε».",
        "w3_t": "Εγκαταστήστε", "w3_d": "Πατήστε «Αποδοχή και εγκατάσταση» και μετά «Ναι» στο μήνυμα των Windows. Για γρήγορη βοήθεια χωρίς εγκατάσταση, πατήστε «Εκτέλεση χωρίς εγκατάσταση».",
        "w4_t": "Γράψτε το όνομά σας", "w4_d": "Σε λίγα δευτερόλεπτα εμφανίζεται ένα παράθυρο. Γράψτε το όνομα ή την επωνυμία σας και πατήστε OK. Τέλος!",
        "w5_t": "Έτοιμο", "w5_d": "Η εφαρμογή ξεκινά μόνη της με τα Windows και φαίνεται δίπλα στο ρολόι. Ο τεχνικός μας μπορεί πλέον να σας βοηθήσει όποτε χρειαστεί.",
        "a_h": "Εγκατάσταση στο Android",
        "a1_t": "Κατεβάστε και εγκαταστήστε", "a1_d": "Ανοίξτε τον σύνδεσμο ή σαρώστε τον κωδικό QR. Αν ρωτήσει, επιτρέψτε την «Εγκατάσταση άγνωστων εφαρμογών» και πατήστε «Εγκατάσταση».",
        "a2_t": "Ξεκινήστε την υπηρεσία", "a2_d": "Ανοίξτε την εφαρμογή, πατήστε κάτω την «Κοινή χρήση οθόνης» και μετά «Έναρξη υπηρεσίας».",
        "a3_t": "Επιτρέψτε την εγγραφή οθόνης", "a3_d": "Στο μήνυμα του κινητού πατήστε «Έναρξη τώρα», ώστε ο τεχνικός να βλέπει την οθόνη σας.",
        "a4_t": "Πείτε ID και κωδικό", "a4_d": "Πείτε στον τεχνικό το ID και τον κωδικό μίας χρήσης. Όταν συνδεθεί, πατήστε «Αποδοχή».",
        "a_tip": "Για να μπορεί ο τεχνικός και να πατά στην οθόνη: ενεργοποιήστε τον «Έλεγχο εισόδου» και, στις Ρυθμίσεις προσβασιμότητας, το «Exelixisnet IT Support Input».",
        "safe_h": "Ασφάλεια",
        "safe_d": "Συνδεόμαστε μόνο όταν χρειάζεται για την υποστήριξή σας. Μπορείτε να απεγκαταστήσετε την εφαρμογή όποτε θέλετε από τις Ρυθμίσεις → Εφαρμογές.",
        # screen texts
        "s_dl": "Λήψεις", "s_open": "Άνοιγμα αρχείου",
        "s_ss_t": "Τα Windows προστάτευσαν τον υπολογιστή σας",
        "s_ss_d": "Το Microsoft Defender SmartScreen εμπόδισε την εκκίνηση μιας μη αναγνωρισμένης εφαρμογής.",
        "s_more": "Περισσότερες πληροφορίες", "s_run": "Εκτέλεση οπωσδήποτε", "s_norun": "Να μην εκτελεστεί",
        "s_inst": "Εγκατάσταση", "s_path": "Διαδρομή εγκατάστασης",
        "s_accept": "Αποδοχή και εγκατάσταση", "s_portable": "Εκτέλεση χωρίς εγκατάσταση", "s_cancel": "Άκυρο",
        "s_welcome": "Καλώς ήρθατε στο Exelixisnet IT Support",
        "s_name": "Ονοματεπώνυμο ή επωνυμία *", "s_phone": "Τηλέφωνο (προαιρετικό)", "s_later": "Αργότερα",
        "s_name_ex": "Παπαδόπουλος ΑΕ",
        "s_ready": "Έτοιμο", "s_your_id": "Το ID σας", "s_pw": "Κωδικός",
        "s_install_app": "Εγκατάσταση", "s_allow_unknown": "Επιτρέπεται από αυτή την πηγή",
        "s_share": "Κοινή χρήση οθόνης", "s_connect": "Σύνδεση", "s_chat": "Κουβέντα", "s_settings": "Ρυθμίσεις",
        "s_start": "Έναρξη υπηρεσίας", "s_perm": "Άδειες", "s_rec": "Καταγραφή οθόνης", "s_input": "Έλεγχος εισόδου",
        "s_record_q": "Έναρξη εγγραφής ή μετάδοσης με το Exelixisnet IT Support;", "s_start_now": "Έναρξη τώρα",
        "s_device": "Η συσκευή σας", "s_otp": "Κωδικός μίας χρήσης", "s_accept_c": "Αποδοχή", "s_dismiss": "Απόρριψη",
        "s_wants": "Ο τεχνικός Exelixisnet θέλει να συνδεθεί",
        "page": "Σελίδα",
    },
    "en": {
        "lang": "en",
        "title": "Setup guide",
        "subtitle": "Remote support from Exelixisnet, in a few steps.",
        "intro": "With the Exelixisnet IT Support app our technician sees your screen and helps you remotely. Connections go only through our own secure server.",
        "scan": "Scan with your phone or open the link",
        "win": "Windows", "and": "Android",
        "win_for": "For PCs and laptops",
        "and_for": "For phones and tablets",
        "two_ways": "Two ways to use it",
        "quick_t": "Quick help", "quick_d": "Open the app and read the ID and password to the technician. When you close it, nothing stays installed.",
        "perm_t": "Permanent support", "perm_d": "Install the app once. After that we can help whenever you need it, without you doing anything.",
        "help": "Need help?", "hours": "Monday–Friday 09:00–17:00",
        "w_h": "Installing on Windows",
        "w1_t": "Download the app", "w1_d": "Open the link we sent you or scan the QR code on the first page. Open the downloaded file.",
        "w2_t": "Allow it to start", "w2_d": "If Windows shows a blue warning, click “More info” and then “Run anyway”.",
        "w3_t": "Install", "w3_d": "Click “Accept and install”, then “Yes” in the Windows prompt. For quick help without installing, click “Run without install”.",
        "w4_t": "Enter your name", "w4_d": "After a few seconds a window appears. Type your name or company name and click OK. Done!",
        "w5_t": "Ready", "w5_d": "The app starts with Windows and sits next to the clock. Our technician can now help you whenever needed.",
        "a_h": "Installing on Android",
        "a1_t": "Download and install", "a1_d": "Open the link or scan the QR code. If asked, allow “Install unknown apps”, then tap “Install”.",
        "a2_t": "Start the service", "a2_d": "Open the app, tap “Share screen” at the bottom, then “Start service”.",
        "a3_t": "Allow screen recording", "a3_d": "In the phone’s prompt tap “Start now”, so the technician can see your screen.",
        "a4_t": "Read out ID and password", "a4_d": "Tell the technician the ID and the one-time password. When they connect, tap “Accept”.",
        "a_tip": "So the technician can also tap on your screen: turn on “Input control” and, in Accessibility settings, “Exelixisnet IT Support Input”.",
        "safe_h": "Security",
        "safe_d": "We connect only when needed for your support. You can uninstall the app at any time from Settings → Apps.",
        "s_dl": "Downloads", "s_open": "Open file",
        "s_ss_t": "Windows protected your PC",
        "s_ss_d": "Microsoft Defender SmartScreen prevented an unrecognised app from starting.",
        "s_more": "More info", "s_run": "Run anyway", "s_norun": "Don’t run",
        "s_inst": "Installation", "s_path": "Installation path",
        "s_accept": "Accept and install", "s_portable": "Run without install", "s_cancel": "Cancel",
        "s_welcome": "Welcome to Exelixisnet IT Support",
        "s_name": "Full name or company name *", "s_phone": "Phone (optional)", "s_later": "Later",
        "s_name_ex": "Papadopoulos Ltd",
        "s_ready": "Ready", "s_your_id": "Your ID", "s_pw": "Password",
        "s_install_app": "Install", "s_allow_unknown": "Allow from this source",
        "s_share": "Share screen", "s_connect": "Connect", "s_chat": "Chat", "s_settings": "Settings",
        "s_start": "Start service", "s_perm": "Permissions", "s_rec": "Screen capture", "s_input": "Input control",
        "s_record_q": "Start recording or casting with Exelixisnet IT Support?", "s_start_now": "Start now",
        "s_device": "Your device", "s_otp": "One-time password", "s_accept_c": "Accept", "s_dismiss": "Dismiss",
        "s_wants": "Exelixisnet technician wants to connect",
        "page": "Page",
    },
}

CSS = f"""
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: 'Commissioner', 'Noto Sans', sans-serif; color: #14213D; font-size: 11pt; line-height: 1.45; }}
.page {{ width: 210mm; height: 297mm; padding: 16mm 16mm 14mm; position: relative; overflow: hidden; page-break-after: always; }}
.page:last-child {{ page-break-after: auto; }}
h1, h2, h3 {{ font-style: italic; font-weight: 900; letter-spacing: -0.01em; margin: 0; }}
h1 {{ font-size: 30pt; line-height: 1.05; color: {NAVY}; }}
h2 {{ font-size: 20pt; color: {NAVY}; margin-bottom: 4mm; }}
h3 {{ font-size: 13pt; color: {NAVY}; }}
.muted {{ color: #5D6B85; }}
.band {{ position: absolute; left: 0; right: 0; top: 0; height: 6mm; background: {NAVY}; }}
.band::after {{ content: ""; position: absolute; left: 0; bottom: -1.5mm; width: 40mm; height: 1.5mm; background: {RED}; }}
.foot {{ position: absolute; left: 16mm; right: 16mm; bottom: 8mm; display: flex; justify-content: space-between; font-size: 8.5pt; color: #5D6B85; border-top: 0.4mm solid #DCE3EE; padding-top: 2.5mm; }}
.cover-top {{ display: flex; align-items: center; justify-content: space-between; margin-top: 6mm; }}
.cover-top img.logo {{ width: 70mm; }}
.cover-top img.icon {{ width: 22mm; height: 22mm; border-radius: 5mm; }}
.lead {{ font-size: 13pt; margin: 4mm 0 2mm; }}
.qrs {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8mm; margin-top: 4mm; }}
.qr {{ border: 0.5mm solid #DCE3EE; border-radius: 5mm; padding: 4.5mm; text-align: center; }}
.qr svg {{ width: 34mm; height: 34mm; }}
.qr .os {{ font-size: 16pt; font-weight: 800; font-style: italic; color: {NAVY}; }}
.qr .for {{ font-size: 9.5pt; color: #5D6B85; margin-bottom: 3mm; }}
.qr .url {{ font-size: 9.5pt; color: {BLUE}; font-weight: 600; margin-top: 3mm; word-break: break-all; }}
.ways {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8mm; margin-top: 6mm; }}
.way {{ background: #F3F6FA; border-radius: 4mm; padding: 5mm 6mm; }}
.way h3 {{ margin-bottom: 1.5mm; }}
.contact {{ margin-top: 6mm; background: {NAVY}; color: #fff; border-radius: 5mm; padding: 6mm 7mm; display: flex; justify-content: space-between; align-items: center; }}
.contact .big {{ font-size: 20pt; font-weight: 900; font-style: italic; }}
.contact .small {{ color: #B9C8E4; font-size: 10pt; }}
.steps {{ display: grid; gap: 4mm; }}
.steps.compact {{ gap: 2mm; }}
.steps.compact .step {{ grid-template-columns: 9mm 1fr 52mm; padding-bottom: 2mm; }}
.step {{ display: grid; grid-template-columns: 9mm 1fr 78mm; gap: 4mm; align-items: center; border-bottom: 0.3mm solid #E6EBF2; padding-bottom: 4.5mm; }}
.step:last-child {{ border-bottom: 0; }}
.num {{ width: 9mm; height: 9mm; border-radius: 50%; background: {RED}; color: #fff; font-weight: 800; display: grid; place-items: center; font-size: 12pt; align-self: start; margin-top: 1mm; }}
.step p {{ margin: 1mm 0 0; font-size: 10.5pt; }}
.tip {{ background: #FFF4F5; border-left: 1.5mm solid {RED}; padding: 3mm 5mm; font-size: 9.5pt; margin-top: 3mm; border-radius: 0; }}
/* ---- screen mock-ups ---- */
.scr {{ font-family: 'Segoe UI', 'Noto Sans', sans-serif; font-size: 7.5pt; line-height: 1.3; color: #1d1d1f; }}
.win {{ border: 0.4mm solid #C9CFD8; border-radius: 2mm; background: #fff; overflow: hidden; box-shadow: 0 1mm 3mm rgba(10,46,99,.15); }}
.win .bar {{ height: 5mm; background: #F1F3F6; border-bottom: 0.3mm solid #E1E5EE; display: flex; align-items: center; padding: 0 2mm; gap: 1.5mm; font-size: 6.5pt; color: #5D6B85; }}
.win .bar img {{ width: 3mm; height: 3mm; border-radius: 0.6mm; }}
.win .body {{ padding: 3mm; }}
.btn {{ display: inline-block; border-radius: 1mm; padding: 1.2mm 3mm; font-weight: 600; font-size: 7pt; border: 0.3mm solid #C9CFD8; background: #fff; color: #1d1d1f; }}
.btn.red {{ background: {RED}; border-color: {RED}; color: #fff; }}
.btn.ms {{ background: #fff; border-color: #fff; color: #1d1d1f; }}
.hl {{ outline: 0.7mm solid {RED}; outline-offset: 0.7mm; border-radius: 1mm; }}
.ss {{ background: #0B5CAD; color: #fff; padding: 4mm; border-radius: 1mm; }}
.ss .t {{ font-size: 10.5pt; font-weight: 300; margin-bottom: 2mm; }}
.ss a {{ color: #fff; text-decoration: underline; }}
.field {{ border: 0.3mm solid #C9CFD8; border-radius: 1mm; padding: 1.2mm 1.8mm; margin: 1mm 0 2mm; color: #1d1d1f; }}
.lbl {{ font-size: 6.5pt; color: #5D6B85; }}
.idbig {{ font-size: 13pt; font-weight: 700; color: {BLUE}; letter-spacing: 0.02em; }}
.phone {{ width: 40mm; margin: 0 auto; border: 1.2mm solid #1d1d1f; border-radius: 5mm; overflow: hidden; background: #1E2433; color: #E7ECF5; }}
.phone .top {{ background: #121722; text-align: center; font-weight: 700; padding: 1.2mm 0; font-size: 7pt; }}
.phone .card {{ background: #2A3142; margin: 1.5mm; border-radius: 2mm; padding: 2mm; }}
.phone .tabs {{ display: flex; background: #121722; padding: 1.2mm 0.5mm; font-size: 4.6pt; color: #93A1BB; text-align: center; }}
.phone .tabs span {{ flex: 1; padding: 0 0.3mm; }}
.phone .tabs .on {{ color: #fff; font-weight: 700; }}
.sw {{ display: inline-block; width: 6mm; height: 3.2mm; border-radius: 2mm; background: #4A5873; position: relative; vertical-align: middle; }}
.sw::after {{ content: ""; position: absolute; left: 0.4mm; top: 0.4mm; width: 2.4mm; height: 2.4mm; border-radius: 50%; background: #fff; }}
.sw.on {{ background: {RED}; }} .sw.on::after {{ left: auto; right: 0.4mm; }}
.row {{ display: flex; justify-content: space-between; align-items: center; margin: 1mm 0; }}
.phone .btn {{ padding: 0.9mm 1.8mm; font-size: 6pt; }}
.sheet {{ background: #fff; color: #1d1d1f; border-radius: 3mm 3mm 0 0; padding: 2mm 2.5mm; margin-top: 1mm; }}
.dim {{ opacity: .35; }}
"""


def windows_screens(t):
    s = {}
    s["w1"] = f"""<div class="scr win"><div class="bar">{t['s_dl']}</div><div class="body">
      <div style="display:flex;align-items:center;gap:2mm"><img src="{ICON}" style="width:7mm;height:7mm;border-radius:1.5mm">
      <div><b>ExelixisnetITSupport-windows-x64.exe</b><div class="lbl">25 MB</div></div></div>
      <div style="margin-top:2.5mm"><span class="btn red hl">{t['s_open']}</span></div></div></div>"""
    s["w2"] = f"""<div class="scr ss"><div class="t">{html.escape(t['s_ss_t'])}</div>
      <div style="font-size:6.8pt">{html.escape(t['s_ss_d'])}</div>
      <div style="margin:2mm 0"><a class="hl" style="padding:0 0.6mm">{t['s_more']}</a></div>
      <div style="text-align:right"><span class="btn ms hl">{t['s_run']}</span> <span class="btn ms">{t['s_norun']}</span></div></div>"""
    s["w3"] = f"""<div class="scr win"><div class="bar"><img src="{ICON}">Exelixisnet IT Support</div><div class="body">
      <div style="font-size:10pt;font-weight:300;margin-bottom:2mm">{t['s_inst']}</div>
      <div class="lbl">{t['s_path']}</div><div class="field">C:\\Program Files\\ExelixisnetITSupport</div>
      <div style="text-align:right"><span class="btn">{t['s_cancel']}</span> <span class="btn red hl">{t['s_accept']}</span></div>
      <div style="text-align:right;margin-top:1.5mm"><span class="btn">{t['s_portable']}</span></div></div></div>"""
    s["w4"] = f"""<div class="scr win"><div class="bar"><img src="{ICON}">Exelixisnet IT Support</div><div class="body">
      <div style="font-weight:700;font-size:8pt;margin-bottom:2mm">{t['s_welcome']}</div>
      <div class="lbl">{t['s_name']}</div><div class="field hl">{t['s_name_ex']}</div>
      <div class="lbl">{t['s_phone']}</div><div class="field">&nbsp;</div>
      <div style="text-align:right"><span class="btn">{t['s_later']}</span> <span class="btn red hl">OK</span></div></div></div>"""
    s["w5"] = f"""<div class="scr win"><div class="bar"><img src="{ICON}">Exelixisnet IT Support</div><div class="body" style="display:flex;gap:3mm">
      <div style="flex:1"><img src="{LOGO}" style="width:30mm"><div class="lbl" style="margin-top:1mm">IT Support · 2615 00 2000</div>
      <div class="lbl" style="margin-top:2mm">{t['s_your_id']}</div><div class="idbig">123 456 789</div>
      <div class="lbl">{t['s_pw']}: ••••••••</div></div>
      <div style="align-self:end;font-size:7pt;color:#18A058;font-weight:700">● {t['s_ready']}</div></div></div>"""
    return s


def android_screens(t):
    tabs = lambda on: f"""<div class="tabs"><span>{t['s_connect']}</span><span>{t['s_chat']}</span>
      <span class="{'on' if on else ''}">{t['s_share']}</span><span>{t['s_settings']}</span></div>"""
    s = {}
    s["a1"] = f"""<div class="scr phone"><div class="top">ExelixisnetITSupport.apk</div>
      <div style="padding:2mm;text-align:center"><img src="{ICON}" style="width:9mm;height:9mm;border-radius:2mm">
      <div style="margin:1mm 0 1.5mm;font-weight:700">Exelixisnet IT Support</div>
      <div class="row" style="font-size:6.5pt"><span>{t['s_allow_unknown']}</span><span class="sw on hl"></span></div>
      <div style="margin-top:2mm"><span class="btn red hl">{t['s_install_app']}</span></div></div></div>"""
    s["a2"] = f"""<div class="scr phone"><div class="top">Exelixisnet IT Support</div>
      <div class="card"><b>{t['s_perm']}</b><div style="margin:1.5mm 0"><span class="btn red hl">▶ {t['s_start']}</span></div>
      <div class="row dim"><span>{t['s_rec']}</span><span class="sw"></span></div>
      <div class="row dim"><span>{t['s_input']}</span><span class="sw"></span></div></div>{tabs(True)}</div>"""
    s["a3"] = f"""<div class="scr phone"><div class="top dim">Exelixisnet IT Support</div>
      <div class="card dim" style="height:4mm"></div>
      <div class="sheet"><div style="font-weight:700;margin-bottom:1.5mm">{t['s_record_q']}</div>
      <div style="text-align:right"><span class="btn">{t['s_cancel']}</span> <span class="btn red hl">{t['s_start_now']}</span></div></div></div>"""
    s["a4"] = f"""<div class="scr phone"><div class="top">Exelixisnet IT Support</div>
      <div class="card"><b>{t['s_device']}</b><div class="lbl" style="color:#93A1BB;margin-top:1.5mm">ID</div>
      <div class="idbig hl" style="color:#7FB0F0;display:inline-block">123 456 789</div>
      <div class="lbl" style="color:#93A1BB;margin-top:1.5mm">{t['s_otp']}</div><div class="hl" style="font-size:11pt;font-weight:700;display:inline-block">9bdfvx</div></div>
      <div class="sheet"><div style="font-weight:700;margin-bottom:1.5mm">{t['s_wants']}</div>
      <div style="text-align:right"><span class="btn">{t['s_dismiss']}</span> <span class="btn red hl">{t['s_accept_c']}</span></div></div></div>"""
    return s


def step(n, title, text, screen):
    return f"""<div class="step"><div class="num">{n}</div><div><h3>{html.escape(title)}</h3><p>{html.escape(text)}</p></div><div>{screen}</div></div>"""


def build(lang):
    t = T[lang]
    ws, an = windows_screens(t), android_screens(t)
    foot = lambda n: f"""<div class="foot"><span>Exelixisnet IT Support · {t['title']}</span><span>2615 00 2000 · info@exelixisnet.gr · {t['page']} {n}/3</span></div>"""
    cover = f"""<section class="page"><div class="band"></div>
      <div class="cover-top"><img class="logo" src="{LOGO}" alt="exelixis net"><img class="icon" src="{ICON}" alt=""></div>
      <h1 style="margin-top:7mm">Exelixisnet IT Support<br>{t['title']}</h1>
      <p class="lead">{t['subtitle']}</p><p class="muted">{t['intro']}</p>
      <p style="margin:5mm 0 0;font-weight:700">{t['scan']}</p>
      <div class="qrs">
        <div class="qr"><div class="os">{t['win']}</div><div class="for">{t['win_for']}</div>{qr_svg(PANEL + '/get/windows')}<div class="url">{PANEL.replace('https://','')}/get/windows</div></div>
        <div class="qr"><div class="os">{t['and']}</div><div class="for">{t['and_for']}</div>{qr_svg(PANEL + '/get/android')}<div class="url">{PANEL.replace('https://','')}/get/android</div></div>
      </div>
      <div class="ways"><div class="way"><h3>{t['quick_t']}</h3><p style="margin:0">{t['quick_d']}</p></div>
        <div class="way"><h3>{t['perm_t']}</h3><p style="margin:0">{t['perm_d']}</p></div></div>
      <div class="contact"><div><div class="small">{t['help']}</div><div class="big">2615 00 2000</div><div class="small">{t['hours']}</div></div>
        <div style="text-align:right"><div class="small">E-mail</div><div style="font-size:12pt;font-weight:700">info@exelixisnet.gr</div><div class="small">exelixisnet.gr · Viber 6936566500</div></div></div>
      {foot(1)}</section>"""
    win = f"""<section class="page"><div class="band"></div><h2 style="margin-top:6mm">{t['w_h']}</h2><div class="steps">
      {step(1, t['w1_t'], t['w1_d'], ws['w1'])}{step(2, t['w2_t'], t['w2_d'], ws['w2'])}{step(3, t['w3_t'], t['w3_d'], ws['w3'])}
      {step(4, t['w4_t'], t['w4_d'], ws['w4'])}{step(5, t['w5_t'], t['w5_d'], ws['w5'])}</div>{foot(2)}</section>"""
    andr = f"""<section class="page"><div class="band"></div><h2 style="margin-top:6mm">{t['a_h']}</h2><div class="steps compact">
      {step(1, t['a1_t'], t['a1_d'], an['a1'])}{step(2, t['a2_t'], t['a2_d'], an['a2'])}{step(3, t['a3_t'], t['a3_d'], an['a3'])}
      {step(4, t['a4_t'], t['a4_d'], an['a4'])}</div><div class="tip">{t['a_tip']}</div>
      <p style="margin:3mm 0 0;font-size:10pt"><b style="color:{NAVY}">{t['safe_h']}:</b> {t['safe_d']}</p>{foot(3)}</section>"""
    return f"""<!doctype html><html lang="{t['lang']}"><head><meta charset="utf-8">
      <link href="https://fonts.googleapis.com/css2?family=Commissioner:ital,wght@0,300..900;1,300..900&display=swap" rel="stylesheet">
      <style>{CSS}</style></head><body>{cover}{win}{andr}</body></html>"""


def main():
    os.makedirs(OUT, exist_ok=True)
    preview_dir = sys.argv[1] if len(sys.argv) > 1 else None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        for lang in ("el", "en"):
            page = browser.new_page()
            page.set_content(build(lang), wait_until="networkidle")
            page.wait_for_timeout(500)
            out = os.path.join(OUT, f"guide-{lang}.pdf")
            page.pdf(path=out, format="A4", print_background=True, prefer_css_page_size=True)
            print("wrote", out)
            if preview_dir:
                page.set_viewport_size({"width": 794, "height": 1123})
                for i, sec in enumerate(page.query_selector_all("section.page"), 1):
                    sec.screenshot(path=os.path.join(preview_dir, f"guide-{lang}-{i}.png"))
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
