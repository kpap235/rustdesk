#!/usr/bin/env python3
"""Apply Exelixisnet IT Support settings to the RustDesk source tree.

Run from the repository root after checking out submodules:
    python res/exelixis/apply.py

It edits libs/hbb_common/src/config.rs (a submodule we do not fork) so the
built client uses our own ID/relay server and public key by default, and
carries our own internal app name. Safe to run more than once.
"""
import os
import re
import sys

# --- Settings (per tenant, with the Exelixisnet defaults) ------------------
# A multi-tenant build overrides these through the environment so each reseller's
# app points at their own RustDesk deployment and carries their own name. With no
# environment set, the values are exactly the Exelixisnet defaults, so the
# platform owner's own build is unchanged.
SERVER = os.environ.get("EXELIXIS_ID_SERVER", "").strip() or "rustdesk.exelixisnet.gr"
PUB_KEY = os.environ.get("EXELIXIS_PUB_KEY", "").strip() or "OMTaNaukuebffcMIkLStsdfGx6bP0vgtJ68bRpX7Ec0="
# Compiled-in default internal name, also the custom URI scheme (lower-cased:
# exSupport -> exsupport://). At runtime exelixis::init_variant() switches the
# display between the full and QuickSupport build. Must not contain spaces
# (Windows service commands are not quoted) — letters and digits only.
APP_NAME = os.environ.get("EXELIXIS_APP_NAME", "").strip() or "exSupport"
if not re.fullmatch(r"[A-Za-z0-9]+", APP_NAME):
    print(f"ERROR: EXELIXIS_APP_NAME must be letters/digits only (got {APP_NAME!r})")
    sys.exit(1)
# ---------------------------------------------------------------------------

def _find_root() -> str:
    # CI runs this file through exec() from the repository root, where
    # __file__ points at a temporary script, so try the working directory too.
    candidates = [os.getcwd()]
    try:
        candidates.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    except NameError:
        pass
    for c in candidates:
        if os.path.exists(os.path.join(c, "libs", "hbb_common", "src", "config.rs")):
            return c
    return candidates[-1]


ROOT = _find_root()
CONFIG_RS = os.path.join(ROOT, "libs", "hbb_common", "src", "config.rs")

PATCHES = [
    (
        r'pub const RENDEZVOUS_SERVERS: &\[&str\] = &\[[^\]]*\];',
        f'pub const RENDEZVOUS_SERVERS: &[&str] = &["{SERVER}"];',
    ),
    (
        r'pub const RS_PUB_KEY: &str = "[^"]*";',
        f'pub const RS_PUB_KEY: &str = "{PUB_KEY}";',
    ),
    (
        # Makes the app treat our server as its own server, not the public one
        # (no "please set up your own server" tip).
        r'pub static ref PROD_RENDEZVOUS_SERVER: RwLock<String> = RwLock::new\("[^"]*"\.to_owned\(\)\);',
        f'pub static ref PROD_RENDEZVOUS_SERVER: RwLock<String> = RwLock::new("{SERVER}".to_owned());',
    ),
    (
        r'pub static ref APP_NAME: RwLock<String> = RwLock::new\("[^"]*"\.to_owned\(\)\);',
        f'pub static ref APP_NAME: RwLock<String> = RwLock::new("{APP_NAME}".to_owned());',
    ),
]


def main() -> int:
    if not os.path.exists(CONFIG_RS):
        print(f"ERROR: {CONFIG_RS} not found - were submodules checked out?")
        return 1
    with open(CONFIG_RS, encoding="utf-8") as f:
        src = f.read()
    for pattern, replacement in PATCHES:
        src, n = re.subn(pattern, lambda _m: replacement, src)
        if n != 1:
            print(f"ERROR: expected exactly one match for {pattern!r}, found {n}")
            return 1
        print(f"patched: {replacement}")
    with open(CONFIG_RS, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print("Exelixisnet settings applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
