#!/usr/bin/env bash
# Dev-loop deployer: rsync this checkout to a Pi running the controller.
# (For first-time install on a fresh Pi, use install.sh on the Pi instead.)
#
# Usage:
#   ./deploy.sh              # rsync + restart service
#   ./deploy.sh --dry-run    # show what would change
#   ./deploy.sh setup        # one-time: create dest, venv, systemd unit
#
# Override defaults via env vars: BATBRIDGE_HOST, BATBRIDGE_USER, BATBRIDGE_DEST.
# Requires: passwordless SSH to ${BATBRIDGE_USER}@${BATBRIDGE_HOST}.

set -euo pipefail

HOST="${BATBRIDGE_HOST:-192.168.2.185}"
USER="${BATBRIDGE_USER:-pi}"
DEST="${BATBRIDGE_DEST:-/srv/batmobile}"
SRC="$(cd "$(dirname "$0")" && pwd)"

DRY_RUN=""
MODE="deploy"
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN="--dry-run" ;;
    setup)     MODE="setup" ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

ssh_run() { ssh -o StrictHostKeyChecking=no "${USER}@${HOST}" "$@"; }

if [[ "$MODE" == "setup" ]]; then
  echo "==> One-time setup on ${HOST}"
  ssh_run "sudo mkdir -p ${DEST} && sudo chown ${USER}:${USER} ${DEST}"
  ssh_run "test -d ${DEST}/.venv || python3 -m venv ${DEST}/.venv"
  rsync -av ${DRY_RUN} \
    --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.venv' --exclude='deploy.sh' \
    "${SRC}/" "${USER}@${HOST}:${DEST}/"
  ssh_run "${DEST}/.venv/bin/pip install --upgrade pip && ${DEST}/.venv/bin/pip install -r ${DEST}/requirements.txt"
  ssh_run "sudo apt-get install -y ffmpeg"
  ssh_run "sudo cp ${DEST}/systemd/batmobile-service.service /etc/systemd/system/ && sudo systemctl daemon-reload"
  ssh_run "sudo systemctl enable batmobile-service.service"
  echo "==> Setup done. Start with: ssh ${USER}@${HOST} 'sudo systemctl start batmobile-service'"
  exit 0
fi

echo "==> Deploying to ${USER}@${HOST}:${DEST}"
rsync -av ${DRY_RUN} \
  --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.venv' --exclude='deploy.sh' --exclude='sounds.json' \
  "${SRC}/" "${USER}@${HOST}:${DEST}/"

if [[ -z "$DRY_RUN" ]]; then
  echo "==> Reinstalling systemd unit (in case it changed)"
  ssh_run "sudo cp ${DEST}/systemd/batmobile-service.service /etc/systemd/system/ && sudo systemctl daemon-reload"
  echo "==> Restarting service"
  ssh_run "sudo systemctl restart batmobile-service"
  sleep 1
  ssh_run "systemctl --no-pager status batmobile-service.service | head -15" || true
fi

echo "==> Done. WebUI: http://${HOST}:8000/"
