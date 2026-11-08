#!/usr/bin/env python3
"""Load a tenant's build settings and expose them to the workflow / apply.py.

A tenant is described by res/tenants/<slug>.json (committed, non-secret). The
only secret is the enrollment token, which the workflow injects from a secret —
never stored here.

Usage:
    python res/exelixis/tenant_env.py <slug>

Writes `key=value` lines to $GITHUB_OUTPUT (or stdout) for the workflow, and the
matching EXELIXIS_* lines to $GITHUB_ENV (if set) so the compile and apply.py
pick them up. With slug "exelixis" (the default) the values equal the built-in
Exelixisnet defaults, so the platform owner's own build is unchanged.
"""
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REQUIRED = ("slug", "name", "id_server", "pub_key", "app_name", "app_uri", "panel_url",
            "exe_full", "exe_quick")


def load(slug: str) -> dict:
    slug = slug.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,38}[a-z0-9]", slug):
        sys.exit(f"ERROR: bad tenant slug {slug!r}")
    path = os.path.join(ROOT, "res", "tenants", f"{slug}.json")
    if not os.path.exists(path):
        sys.exit(f"ERROR: no tenant config at res/tenants/{slug}.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    for k in REQUIRED:
        if not str(cfg.get(k, "")).strip():
            sys.exit(f"ERROR: res/tenants/{slug}.json is missing '{k}'")
    if cfg["slug"].lower() != slug:
        sys.exit(f"ERROR: slug inside {slug}.json is {cfg['slug']!r}")
    if not re.fullmatch(r"[A-Za-z0-9]+", cfg["app_name"]):
        sys.exit("ERROR: app_name must be letters/digits only")
    if cfg["app_uri"].lower() != cfg["app_name"].lower():
        sys.exit("ERROR: app_uri must equal app_name lower-cased")
    if "quick" not in cfg["exe_quick"].lower():
        sys.exit("ERROR: exe_quick must contain 'quick' (runtime detects the customer build by name)")
    return cfg


def emit(cfg: dict) -> None:
    outputs = {
        "slug": cfg["slug"],
        "name": cfg["name"],
        "id_server": cfg["id_server"],
        "pub_key": cfg["pub_key"],
        "app_name": cfg["app_name"],
        "app_uri": cfg["app_uri"],
        "panel_url": cfg["panel_url"],
        "exe_full": cfg["exe_full"],
        "exe_quick": cfg["exe_quick"],
    }
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            for k, v in outputs.items():
                f.write(f"{k}={v}\n")
    gh_env = os.environ.get("GITHUB_ENV")
    if gh_env:
        with open(gh_env, "a", encoding="utf-8") as f:
            f.write(f"EXELIXIS_ID_SERVER={cfg['id_server']}\n")
            f.write(f"EXELIXIS_PUB_KEY={cfg['pub_key']}\n")
            f.write(f"EXELIXIS_APP_NAME={cfg['app_name']}\n")
            f.write(f"EXELIXIS_PANEL_URL={cfg['panel_url']}\n")
    if not gh_out and not gh_env:
        for k, v in outputs.items():
            print(f"{k}={v}")


if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TENANT", "exelixis")
    emit(load(slug))
