#!/usr/bin/env bash
# One-time host setup for an efferents event cluster. Run as root on a fresh
# Ubuntu 24.04 machine:
#
#   DOMAIN=event.example.org bash deploy/setup.sh
#
# Optional: REF=<branch> (default main; use the event's branch, e.g. glasgow),
# EFFERENTS_REPO=<git url> (default this repository), POPPER_REPO=<git url>.
#
# Idempotent: re-running updates the release and units without touching
# /etc/efferents/event.env or the cluster directory.
set -euo pipefail

EFFERENTS_REPO="${EFFERENTS_REPO:-https://github.com/Entangled-Research/efferents-events}"
POPPER_REPO="${POPPER_REPO:-https://github.com/mashathepotato/popper-probe}"
DOMAIN="${DOMAIN:?set DOMAIN to the hostname participants will open}"
REF="${REF:-main}"
ROOT=/srv/efferents
USER_NAME=efferents
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== packages"
apt-get update -q
apt-get install -y -q git curl ufw debian-keyring debian-archive-keyring apt-transport-https
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi

echo "== user and directories"
id -u "$USER_NAME" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "$USER_NAME"
mkdir -p "$ROOT"/{releases,cluster,backups}
chown -R "$USER_NAME:$USER_NAME" "$ROOT"

echo "== firewall (22, 80, 443 only)"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

echo "== uv + release checkout"
su - "$USER_NAME" -c '
  set -e
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  if [ ! -d '"$ROOT"'/popper-probe/.git ]; then
    git clone --depth 1 '"$POPPER_REPO"' '"$ROOT"'/popper-probe
  else
    git -C '"$ROOT"'/popper-probe pull --ff-only
  fi
  tmp=$(mktemp -d)
  git clone --depth 1 --branch '"$REF"' '"$EFFERENTS_REPO"' "$tmp/src"
  sha=$(git -C "$tmp/src" rev-parse --short HEAD)
  dest='"$ROOT"'/releases/$sha
  if [ ! -d "$dest" ]; then
    mv "$tmp/src" "$dest"
    (cd "$dest" && uv sync)
  fi
  rm -rf "$tmp"
  ln -sfn "$dest" '"$ROOT"'/current.new && mv -T '"$ROOT"'/current.new '"$ROOT"'/current
  echo "release: $sha"
'

echo "== secrets and policy files (never overwritten)"
mkdir -p /etc/efferents
if [ ! -f /etc/efferents/event.env ]; then
  install -m 600 -o root -g root "$HERE/event.env.example" /etc/efferents/event.env
  echo "!! fill in /etc/efferents/event.env (keys) before starting the units"
fi
if [ ! -f "$ROOT/cluster/cluster.yaml" ]; then
  su - "$USER_NAME" -c "cd $ROOT/current && .venv/bin/efferents cluster init $ROOT/cluster" >/dev/null
  install -m 644 -o "$USER_NAME" -g "$USER_NAME" "$HERE/cluster.yaml.example" "$ROOT/cluster/cluster.yaml"
  echo "!! edit $ROOT/cluster/cluster.yaml (name, join_code) and add tracks under $ROOT/cluster/tracks/"
fi
# The cluster reads secrets from the systemd EnvironmentFile, not from its .env.
rm -f "$ROOT/cluster/.env"

echo "== systemd units, limits, proxy"
install -m 644 "$HERE"/efferents-*.service "$HERE"/efferents-*.timer /etc/systemd/system/
install -m 644 "$HERE/limits.conf" /etc/security/limits.d/efferents.conf
sed "s/event.example.org/$DOMAIN/" "$HERE/Caddyfile" > /etc/caddy/Caddyfile
mkdir -p /var/log/caddy && chown caddy:caddy /var/log/caddy
systemctl daemon-reload
systemctl enable caddy efferents-cluster efferents-keeper efferents-sync efferents-backup.timer >/dev/null
systemctl restart caddy

cat <<MSG

Done. Next:
  1. Put keys in /etc/efferents/event.env (chmod 600 already).
  2. Edit $ROOT/cluster/cluster.yaml; add tracks under $ROOT/cluster/tracks/<id>/.
  3. sudo -u $USER_NAME bash -c 'set -a; . /etc/efferents/event.env; cd $ROOT/current && .venv/bin/efferents cluster check $ROOT/cluster'
  4. systemctl start efferents-cluster efferents-keeper efferents-sync efferents-backup.timer
  5. Open https://$DOMAIN/ (DNS A record must already point here for TLS to issue).
MSG
