# Troubleshooting

Operational gotchas hit while running this in production. If you hit something
that's not covered here, please file an issue — the next person benefits.

## Driving / control

### Batmobile WiFi AP not appearing in scans

The toy's AP only broadcasts when the unit is **powered on**. If `nmcli dev wifi
list | grep BATMOBILE` returns nothing, check:

1. The unit is switched on (front-bottom slider switch)
2. Battery isn't fully depleted — when battery drops below ~10%, the WiFi
   chipset shuts down before the rest of the toy
3. You're within ~25 ft (the AP is intentionally short-range)

### `bat-connect` fails: "The base network connection was interrupted"

batbridge sees the AP and tries to associate, but the handshake gets dropped
mid-stream. Almost always the Batmobile's **WiFi firmware state is stuck**,
typically after:

- A recharge/discharge cycle
- Heavy HTTP/RTSP probing (e.g., nmap or wordlist enumeration — see
  `camera-investigation.md`)
- An armed-then-disconnected-without-shutdown sequence

**Fix:** power-cycle the Batmobile. Switch off, wait ~10 seconds, switch back
on, wait ~15 seconds for the AP to come up. Then `bat-connect` should succeed.

### Running `bat-connect` via `sudo` fails with "no terminal"

```
sudo: a terminal is required to read the password; either use the -S option…
```

**Don't wrap `bat-connect` in `sudo`.** The script self-elevates internally
only for the specific `nmcli` call, which is whitelisted via the sudoers drop-in
created by `install.sh`. Run as the regular service user:

```bash
/usr/local/bin/bat-connect       # ✓
sudo /usr/local/bin/bat-connect  # ✗
```

### ARM button on the WebUI does nothing / hangs

The WebUI's ARM endpoint calls `bat-connect` server-side, then starts the
controller's 10 Hz loop. If `bat-connect` hangs (see above), the ARM call
stalls.

**Diagnose:**

```bash
ssh pi@<batbridge-ip> "
  systemctl is-active batmobile-service.service
  nmcli -t -f GENERAL.STATE dev show wlan0
  ping -c 2 -W 1 192.168.201.1
  curl -s -m 5 -X POST http://127.0.0.1:8000/api/arm
"
```

If `wlan0` is stuck in `connecting (configuring)` or `ping` fails,
power-cycle the Batmobile. After the toy's AP is healthy, retry ARM from the
phone — it'll succeed within a couple seconds.

### Batmobile WiFi password isn't `BATMOBILE1` anymore

The first time you connect to a fresh Batmobile via the **original Mattel app**
(no longer on Google Play, but if you side-loaded it for some reason), the app
silently rotates the AP password to a random value. The new password isn't
recoverable from the toy.

**Fix:** factory-reset the Batmobile.

- Locate the small reset hole on the **bottom-left of the battery housing**
- Insert a paperclip, hold for **10 seconds**, then release
- Power-cycle (off → 5 seconds → on)
- The AP returns to SSID `XXXX-BATMOBILE` with password `BATMOBILE1`

This project's `install.sh` only ever touches the AP read-side, so the
password stays default. You only end up needing this if you've used the
original app or got a unit that someone else paired.

### Runaway motors after WiFi disconnect

If the radio link drops while the throttle command is non-zero (e.g., your
phone leaves Wi-Fi range, or you Ctrl+C the controller mid-drive), the
Batmobile keeps the last commanded throttle indefinitely — a runaway motor
condition.

**Always disarm before powering off:**

```bash
/usr/local/bin/bat-disconnect    # runs the controlled shutdown sequence
```

Or via the WebUI: tap the **ABORT** dome (hold ~700 ms), then **DISARM**.

The shutdown sequence sends ~70 stop packets over 7 seconds before dropping
the WiFi link. This is what the protocol's "mandatory shutdown" section refers
to — it's not optional, it prevents runaway behavior.

### PoE undervolt on boot

If batbridge runs on a PoE HAT with an underspec'd PoE switch, you may see:

```
$ vcgencmd get_throttled
throttled=0x50000
```

Bits `0x50000` are *history bits* — the boot-inrush briefly exceeded supply,
but steady-state is clean. The Pi runs fine. For Track B sales units, spec a
proper 5V/3A USB-C supply in the BOM since buyers can't be expected to have
PoE infra.

## Camera

### "Camera not supported" / no video feed

This is intentional. The Mattel FKM40's camera firmware handshakes RTSP
correctly but emits zero RTP frames — across the entire product line, not
just specific units. We've enumerated the entire network surface and exhausted
the software-side debugging. The WebUI's camera section was removed
deliberately. See `camera-investigation.md` for the full record.

If you want to take another shot at it, the path forward is hardware-side
(UART debug header on the camera PCB, OpenIPC reflash, or replacement of the
camera module entirely).

## Network

### batbridge can't reach ai-engine / EPOCH gateway

Not a Batmobile problem — this happens when batbridge's `wlan0` is up to the
Batmobile AP and `eth0` has lost its default route somehow.

**Verify:**

```bash
ip route show default
```

Should show `default via <home-router-ip> dev eth0`. If it shows wlan0 instead,
NetworkManager has assigned the Batmobile's link as default, which is wrong —
the Batmobile's AP doesn't have internet. The `batmobile` NM profile is
configured with `ipv4.never-default=yes` to prevent this; if it happens
anyway, edit the profile:

```bash
sudo nmcli con modify batmobile ipv4.never-default yes
```

### Phone WebUI loads but commands time out

Phone is reaching the WebUI (so HTTP/8000 is fine), but the WebUI can't reach
the Batmobile. Same diagnostic as "ARM hangs" above — the issue is
batbridge↔Batmobile, not phone↔batbridge.

## Reporting new issues

If you hit something not in this doc, file a GitHub issue with:

- Exact symptom (UI behavior, what you tried, what error appeared)
- `journalctl -u batmobile-service --since '5 minutes ago'`
- `journalctl -u NetworkManager --since '5 minutes ago' | grep -E 'wlan0|batmobile'`
- Output of: `vcgencmd get_throttled`, `uname -a`, batbridge model

Most issues turn out to be Batmobile firmware state weirdness recoverable
with a power-cycle, but the journal is what tells us when it's something else.
