#!/usr/bin/env bash
#
# EPOCH Batmobile Controller — bootstrap installer
# https://github.com/salient-concepts/batmobile-fkm40-controller
#
# Sets up a vanilla Raspberry Pi OS Lite (Trixie) install to run the
# Batmobile controller as a systemd service. Idempotent — safe to re-run.
#
# Usage (recommended, from a clone of the repo):
#   sudo ./install.sh
#
# Usage (one-shot, no clone):
#   curl -sL https://raw.githubusercontent.com/salient-concepts/batmobile-fkm40-controller/main/install.sh | sudo bash
#
# Environment overrides (optional):
#   BATMOBILE_USER       service user (default: pi)
#   BATMOBILE_DEST       install path (default: /srv/batmobile)
#   BATMOBILE_AP_SSID    Batmobile WiFi SSID (default: prompts)
#   BATMOBILE_AP_PSK     Batmobile WiFi password (default: BATMOBILE1)
#   BATMOBILE_REPO       git URL when running curl-piped (default: upstream)
#   COUNTRY_CODE         WiFi regulatory domain (default: US)

set -euo pipefail

# ---- args / config ---------------------------------------------------------

BM_USER="${BATMOBILE_USER:-pi}"
BM_DEST="${BATMOBILE_DEST:-/srv/batmobile}"
BM_AP_PSK="${BATMOBILE_AP_PSK:-BATMOBILE1}"
COUNTRY_CODE="${COUNTRY_CODE:-US}"
REPO_URL="${BATMOBILE_REPO:-https://github.com/salient-concepts/batmobile-fkm40-controller.git}"

if [[ $EUID -ne 0 ]]; then
  echo "==> install.sh must run as root. Re-run with sudo." >&2
  exit 1
fi

if ! id "$BM_USER" >/dev/null 2>&1; then
  echo "==> User '$BM_USER' does not exist on this system." >&2
  echo "    Create it first or set BATMOBILE_USER to an existing user." >&2
  exit 1
fi

# ---- locate source --------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/batmobile_controller.py" ]]; then
  SRC="$SCRIPT_DIR"
  echo "==> Installing from local checkout at $SRC"
else
  SRC="$(mktemp -d)"
  echo "==> No local checkout found; cloning $REPO_URL"
  apt-get install -y git >/dev/null
  git clone --depth=1 "$REPO_URL" "$SRC"
fi

# ---- prompt for AP SSID (if not provided) ---------------------------------

if [[ -z "${BATMOBILE_AP_SSID:-}" ]]; then
  echo
  echo "==> The Batmobile broadcasts a WiFi network with SSID 'XXXX-BATMOBILE',"
  echo "    where XXXX is the last 4 hex digits of the unit's MAC address."
  read -rp "    Enter your Batmobile's SSID (e.g. 16E6-BATMOBILE): " BM_AP_SSID
else
  BM_AP_SSID="$BATMOBILE_AP_SSID"
fi

if [[ -z "$BM_AP_SSID" ]]; then
  echo "==> SSID required. Aborting." >&2
  exit 1
fi

# ---- system packages ------------------------------------------------------

echo "==> Installing system dependencies (apt)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip \
  network-manager \
  rfkill iw \
  ffmpeg \
  curl ca-certificates \
  >/dev/null

# ---- WiFi country (required for wlan0 to scan on Pi OS) -------------------

echo "==> Setting WiFi country to $COUNTRY_CODE"
if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_wifi_country "$COUNTRY_CODE" || true
fi
rfkill unblock wifi 2>/dev/null || true

# ---- user permissions (NetworkManager polkit + nmcli sudoers) -------------

echo "==> Granting WiFi permissions to $BM_USER"
usermod -aG netdev "$BM_USER"
cat > /etc/sudoers.d/batmobile-nmcli <<EOF
# Lets the batmobile service user toggle the Batmobile AP without a password.
$BM_USER ALL=(ALL) NOPASSWD: /usr/bin/nmcli
EOF
chmod 440 /etc/sudoers.d/batmobile-nmcli

# ---- install application files --------------------------------------------

echo "==> Installing application to $BM_DEST"
mkdir -p "$BM_DEST"
chown "$BM_USER:$BM_USER" "$BM_DEST"

sudo -u "$BM_USER" rsync -a \
  --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.venv' --exclude='install.sh' \
  "$SRC/" "$BM_DEST/"

# Python venv + deps
if [[ ! -d "$BM_DEST/.venv" ]]; then
  echo "==> Creating Python virtualenv"
  sudo -u "$BM_USER" python3 -m venv "$BM_DEST/.venv"
fi
echo "==> Installing Python dependencies"
sudo -u "$BM_USER" "$BM_DEST/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$BM_USER" "$BM_DEST/.venv/bin/pip" install --quiet -r "$BM_DEST/requirements.txt"

# ---- NetworkManager profile for the Batmobile AP --------------------------

echo "==> Configuring NetworkManager profile for $BM_AP_SSID"
if nmcli -t -f NAME con show | grep -qx 'batmobile'; then
  nmcli con delete batmobile >/dev/null
fi
nmcli con add type wifi con-name batmobile ifname wlan0 ssid "$BM_AP_SSID" \
  -- \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$BM_AP_PSK" \
  802-11-wireless.band bg \
  connection.autoconnect no \
  ipv4.method auto ipv4.never-default yes \
  ipv6.method ignore \
  >/dev/null

# ---- helper commands ------------------------------------------------------

echo "==> Installing bat-connect / bat-disconnect / bat-status to /usr/local/bin"

cat > /usr/local/bin/bat-connect <<'EOF'
#!/usr/bin/env bash
# Bring up the WiFi link to the Batmobile AP and verify reachability.
set -e
sudo /usr/bin/nmcli con up batmobile
for i in 1 2 3 4 5; do
  if ping -c1 -W1 -q 192.168.201.1 >/dev/null; then
    echo "Batmobile online (192.168.201.1)"
    exit 0
  fi
  sleep 1
done
echo "Batmobile WiFi up but unreachable. Check that the unit is powered on." >&2
exit 1
EOF
chmod 755 /usr/local/bin/bat-connect

cat > /usr/local/bin/bat-disconnect <<'EOF'
#!/usr/bin/env bash
# Drop the WiFi link to the Batmobile. Run this BEFORE powering off the toy.
sudo /usr/bin/nmcli con down batmobile 2>/dev/null || true
echo "Batmobile link down"
EOF
chmod 755 /usr/local/bin/bat-disconnect

cat > /usr/local/bin/bat-status <<'EOF'
#!/usr/bin/env bash
echo "--- batmobile NM profile ---"
nmcli -p con show batmobile 2>/dev/null | grep -E '802-11-wireless\.ssid|GENERAL\.STATE|IP4\.ADDRESS\[1\]|IP4\.GATEWAY' || echo "(profile not active)"
echo
echo "--- routes for 192.168.201.0/24 ---"
ip route show 192.168.201.0/24 || echo "(no route)"
echo
echo "--- default route ---"
ip route show default
EOF
chmod 755 /usr/local/bin/bat-status

# ---- systemd unit ---------------------------------------------------------

echo "==> Installing systemd unit"
install -m 644 "$BM_DEST/systemd/batmobile-service.service" \
  /etc/systemd/system/batmobile-service.service

# Patch user/path if non-default
if [[ "$BM_USER" != "pi" || "$BM_DEST" != "/srv/batmobile" ]]; then
  sed -i \
    -e "s|^User=pi$|User=$BM_USER|" \
    -e "s|^Group=pi$|Group=$BM_USER|" \
    -e "s|/srv/batmobile|$BM_DEST|g" \
    /etc/systemd/system/batmobile-service.service
fi

systemctl daemon-reload
systemctl enable batmobile-service.service
systemctl restart batmobile-service.service

# ---- sanity check ---------------------------------------------------------

sleep 1
if ! systemctl is-active --quiet batmobile-service.service; then
  echo "==> Service failed to start. Recent logs:" >&2
  journalctl -u batmobile-service.service -n 20 --no-pager >&2
  exit 1
fi

PI_IP="$(hostname -I | awk '{print $1}')"
echo
echo "============================================================"
echo "  EPOCH Batmobile Controller installed."
echo
echo "  WebUI:        http://$PI_IP:8000/"
echo "  Connect AP:   bat-connect"
echo "  Disconnect:   bat-disconnect"
echo "  Status:       bat-status"
echo "  Service:      systemctl status batmobile-service"
echo
echo "  Power on the Batmobile, run 'bat-connect', open the WebUI,"
echo "  hit ARM, and drive."
echo "============================================================"
