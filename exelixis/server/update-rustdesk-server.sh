#!/usr/bin/env bash
# Exelixisnet: update the RustDesk server (hbbs + hbbr) on this VPS, keeping its key.
#
#   bash update-rustdesk-server.sh          # check only: shows what it finds and would do
#   bash update-rustdesk-server.sh --yes    # back up the key, update, verify the key
#
# Works with the three common installs: Docker (compose), .deb packages, or plain
# hbbs/hbbr binaries run by systemd. Never touches the support panel containers.
set -euo pipefail

APPLY=0
[[ "${1:-}" == "--yes" ]] && APPLY=1

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31mStopped:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root (sudo -i first)"
for t in curl find sha256sum; do command -v "$t" >/dev/null || die "missing tool: $t"; done

case "$(uname -m)" in
  x86_64)  ARCH=amd64 ;;
  aarch64) ARCH=arm64v8 ;;
  armv7l)  ARCH=armv7 ;;
  *) die "unsupported CPU $(uname -m)" ;;
esac

# ---------------------------------------------------------------- key
say "1. Server key"
mapfile -t KEYS < <(find / -xdev -name id_ed25519.pub -not -path '/proc/*' -not -path '/root/rustdesk-key-backup/*' -not -path '*/overlay2/*' 2>/dev/null || true)
[[ ${#KEYS[@]} -gt 0 ]] || die "no id_ed25519.pub found - is the RustDesk server on this machine?"
for k in "${KEYS[@]}"; do ok "$k  ($(cat "$k"))"; done
KEYDIR="$(dirname "${KEYS[0]}")"
[[ ${#KEYS[@]} -gt 1 ]] && warn "several keys found; using $KEYDIR (the server's working folder)"
[[ -f "$KEYDIR/id_ed25519" ]] || die "private key $KEYDIR/id_ed25519 is missing next to the public key"
KEY_BEFORE="$(sha256sum "$KEYDIR/id_ed25519" "$KEYDIR/id_ed25519.pub")"

# ---------------------------------------------------------------- install type
say "2. How the server is installed"
METHOD=""
COMPOSE_DIR=""
if command -v docker >/dev/null; then
  mapfile -t CONTAINERS < <(docker ps -a --format '{{.Names}}|{{.Image}}' | grep -i 'rustdesk/rustdesk-server' | grep -v exsupport || true)
  if [[ ${#CONTAINERS[@]} -gt 0 ]]; then
    METHOD=docker
    for c in "${CONTAINERS[@]}"; do ok "Docker container ${c%%|*} (image ${c#*|})"; done
    COMPOSE_DIR="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "${CONTAINERS[0]%%|*}" 2>/dev/null || true)"
    if [[ -n "$COMPOSE_DIR" && -d "$COMPOSE_DIR" ]]; then ok "started by docker compose in $COMPOSE_DIR"
    else warn "not started by docker compose: the image will be pulled, but you recreate the containers yourself"; fi
  fi
fi
if [[ -z "$METHOD" ]] && dpkg -s rustdesk-server-hbbs >/dev/null 2>&1; then
  METHOD=deb
  ok "Debian packages: hbbs $(dpkg-query -W -f='${Version}' rustdesk-server-hbbs), hbbr $(dpkg-query -W -f='${Version}' rustdesk-server-hbbr 2>/dev/null || echo '?')"
fi
if [[ -z "$METHOD" ]]; then
  HBBS="$(command -v hbbs || true)"
  [[ -z "$HBBS" ]] && HBBS="$(find / -xdev -type f -name hbbs -perm -u+x -not -path '/proc/*' 2>/dev/null | head -1 || true)"
  [[ -n "$HBBS" ]] || die "could not find a Docker container, Debian package or hbbs binary"
  METHOD=binary
  BINDIR="$(dirname "$HBBS")"
  [[ -x "$BINDIR/hbbr" ]] || die "found $HBBS but no hbbr next to it"
  mapfile -t UNITS < <(systemctl list-units --all --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -i -E 'hbbs|hbbr|rustdesk' | grep -v exsupport || true)
  ok "plain binaries in $BINDIR"
  [[ ${#UNITS[@]} -gt 0 ]] && ok "systemd services: ${UNITS[*]}" || warn "no systemd service found; you will need to restart hbbs/hbbr yourself"
fi

# ---------------------------------------------------------------- latest release
say "3. Latest RustDesk server release"
API="$(curl -fsSL https://api.github.com/repos/rustdesk/rustdesk-server/releases/latest)" || die "could not reach GitHub"
TAG="$(printf '%s' "$API" | grep -m1 '"tag_name"' | cut -d'"' -f4)"
ok "latest version: $TAG"
asset_url() { printf '%s' "$API" | grep '"browser_download_url"' | cut -d'"' -f4 | grep -E "$1" | head -1; }

if [[ $APPLY -eq 0 ]]; then
  say "Check only - nothing changed."
  echo "  Would back up the key to /root/rustdesk-key-backup/, update the $METHOD install to $TAG,"
  echo "  restart it and confirm the key is unchanged. Run again with --yes to do it."
  exit 0
fi

# ---------------------------------------------------------------- backup
say "4. Backing up"
BACKUP="/root/rustdesk-key-backup/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
cp -a "$KEYDIR/id_ed25519" "$KEYDIR/id_ed25519.pub" "$BACKUP/"
chmod 700 /root/rustdesk-key-backup "$BACKUP"
ok "key copied to $BACKUP"

# ---------------------------------------------------------------- update
say "5. Updating ($METHOD)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
case "$METHOD" in
  docker)
    if [[ -n "$COMPOSE_DIR" && -d "$COMPOSE_DIR" ]]; then
      (cd "$COMPOSE_DIR" && docker compose pull && docker compose up -d)
      ok "containers recreated with the new image"
    else
      for c in "${CONTAINERS[@]}"; do docker pull "${c#*|}"; done
      warn "image pulled; recreate the containers with your usual docker run command"
    fi
    ;;
  deb)
    DEBARCH="$(dpkg --print-architecture)"
    for p in hbbs hbbr; do
      url="$(asset_url "rustdesk-server-${p}_.*_${DEBARCH}\.deb$")"
      [[ -n "$url" ]] || die "no $p .deb for $DEBARCH in release $TAG"
      curl -fsSL -o "$TMP/$p.deb" "$url"
    done
    dpkg -i "$TMP/hbbs.deb" "$TMP/hbbr.deb"
    ok "packages installed"
    ;;
  binary)
    url="$(asset_url "rustdesk-server-linux-${ARCH}\.zip$")"
    [[ -n "$url" ]] || die "no linux $ARCH zip in release $TAG"
    command -v unzip >/dev/null || apt-get install -y unzip >/dev/null
    curl -fsSL -o "$TMP/server.zip" "$url"
    unzip -q "$TMP/server.zip" -d "$TMP/x"
    NEW_HBBS="$(find "$TMP/x" -type f -name hbbs | head -1)"; NEW_HBBR="$(find "$TMP/x" -type f -name hbbr | head -1)"
    [[ -n "$NEW_HBBS" && -n "$NEW_HBBR" ]] || die "zip did not contain hbbs/hbbr"
    [[ ${#UNITS[@]} -gt 0 ]] && systemctl stop "${UNITS[@]}"
    cp -a "$BINDIR/hbbs" "$BACKUP/hbbs.old"; cp -a "$BINDIR/hbbr" "$BACKUP/hbbr.old"
    install -m 755 "$NEW_HBBS" "$BINDIR/hbbs"; install -m 755 "$NEW_HBBR" "$BINDIR/hbbr"
    [[ ${#UNITS[@]} -gt 0 ]] && systemctl start "${UNITS[@]}"
    ok "binaries replaced (old ones kept in $BACKUP)"
    ;;
esac

# ---------------------------------------------------------------- verify
say "6. Checking"
sleep 5
KEY_AFTER="$(sha256sum "$KEYDIR/id_ed25519" "$KEYDIR/id_ed25519.pub" 2>/dev/null || true)"
if [[ "$KEY_BEFORE" == "$KEY_AFTER" ]]; then
  ok "key unchanged: $(cat "$KEYDIR/id_ed25519.pub")"
else
  warn "key files changed - restoring the backup"
  cp -a "$BACKUP/id_ed25519" "$BACKUP/id_ed25519.pub" "$KEYDIR/"
  die "the key was restored from $BACKUP; restart the server and check again"
fi
if command -v ss >/dev/null; then
  for port in 21115 21116 21117; do
    ss -ltn | grep -q ":$port " && ok "listening on $port" || warn "nothing listening on $port yet"
  done
fi
say "Done: RustDesk server updated to $TAG with the same key."
