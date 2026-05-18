# EPOCH Batmobile Controller

> Bring the **Mattel Justice League Ultimate Batmobile R/C** (FKM40) back to
> life. No app required. No cloud. No Mattel.

On **15 March 2024**, Mattel pulled the *Batmobile™ R/C Controller* app from
the Google Play Store. Tens of thousands of $50–$200 toys became paperweights
overnight — owners could no longer connect to their own hardware. Mattel
customer service has confirmed no replacement is planned.

This project replaces the abandoned app with an open-source controller that
runs on any Raspberry Pi. Drive your Batmobile from a phone, a desktop browser,
or via voice through any MCP-compatible AI assistant.

> **Maintained by [Salient Concepts](https://salient-concepts.github.io/)**
> as part of the EPOCH platform — open hardware, open protocol, owner-first.

---

## What you get

- **Phone/Tablet WebUI** — twin joysticks, dead-man-switch abort, live drive-vector
  visualization on an animated top-down silhouette of the actual Batmobile.
  State-driven: lamps light up, smoke trails, armor plates rotate open,
  cannon turret rises, muzzle flash on fire.
- **Desktop / keyboard** — same UI, plus WASD/arrow-key drive, hotkeys for
  every effect, Esc to disarm.
- **Choreographed demo mode** — 70-second scripted sequence showing off the
  full effect suite. Useful at parties.
- **MCP server** (optional) — remote tool surface for AI assistants. Voice
  control: *"Drive the Batmobile forward"*, *"Fire the cannons"*, *"Run a
  patrol sequence."*
- **Reverse-engineered protocol documentation** — full UDP command table,
  packet format, sensor response decoding, mandatory shutdown sequence.

## What you need

| Component | Notes |
|---|---|
| Mattel Batmobile, model **FKM40** | The *Justice League Ultimate Batmobile R/C, 1/10 scale*. Other Batmobile RCs (Hot Wheels, BvS, etc.) use different protocols and are **not** supported. |
| Raspberry Pi 4 or Pi 5 | Pi 3B+ may work but untested. ARM only. |
| Pi OS Lite, Trixie or newer | 64-bit recommended. Python 3.11+ and NetworkManager required. |
| WiFi adapter | Onboard works. The Pi joins the Batmobile's own WiFi AP. |
| Power | Any 5V/3A supply. PoE works with steady supply (boot inrush may report undervolt history bits — harmless once running). |

The Batmobile must be **factory-reset** so its WiFi password is back to the
default `BATMOBILE1`. Pinhole reset on the bottom-left of the battery housing,
hold 10 seconds.

## Quick start

```bash
# On a fresh Pi OS Lite install
curl -sL https://raw.githubusercontent.com/salient-concepts/batmobile-fkm40-controller/main/install.sh | sudo bash
```

The bootstrap script:

1. Installs `python3-venv`, `nmcli`, `ffmpeg`, `iw`
2. Configures the WiFi country code (required for `wlan0` to scan)
3. Adds the user to `netdev` and grants passwordless `nmcli` (so the helper
   commands work without `sudo` prompts)
4. Creates `/srv/batmobile/`, sets up the venv, installs requirements
5. Installs the systemd unit and the `bat-connect` / `bat-disconnect` /
   `bat-status` helpers
6. Prompts for the Batmobile WiFi SSID (`XXXX-BATMOBILE` — the `XXXX` is the
   last 4 hex digits of the unit's MAC) and password (`BATMOBILE1` by default)
7. Starts the service on `http://<pi-ip>:8000/`

Then, on the Pi:

```bash
bat-connect          # Brings up wlan0 to the Batmobile AP
# Open http://<pi-ip>:8000/ on your phone, hit ARM, drive
bat-disconnect       # Always run BEFORE powering off the Batmobile
```

## Manual install

If you don't trust `curl | sudo bash` (you shouldn't):

```bash
git clone https://github.com/salient-concepts/batmobile-fkm40-controller.git
cd batmobile-fkm40-controller
sudo ./install.sh
```

Or do it by hand — see [docs/manual-install.md](docs/manual-install.md).

## Drive it

Open `http://<pi-ip>:8000/` from any phone or laptop on the same network as
the Pi. (Note: you connect to the *Pi*, the Pi connects to the *Batmobile*.
Don't try to connect your phone to the Batmobile directly — only one device
can hold that AP at a time.)

- Tap **ARM** to bring up the radio link
- Twin joysticks: left = throttle, right = steering
- Single tap toggles for LAMPS / SMOKE; momentary push for ARMOR / CANNON;
  guarded button for FIRE
- Press-and-hold the central E-stop dome (~700 ms) to abort
- DEMO runs the full choreographed sequence

Keyboard (desktop): `W A S D` drive, `Space` stop, `F` fire, `L` lamps,
`K` smoke, `M` armor, `G` cannon, `1–9` sound effects, `/` open FX panel,
`Esc` disarm.

## Optional: voice control via MCP

The service exposes a JSON-RPC MCP endpoint at `POST /mcp`. Six tools:

| Tool | Action |
|---|---|
| `batmobile_arm` | Connect to AP, start the 10 Hz control loop |
| `batmobile_disarm` | Run shutdown sequence, drop AP link |
| `batmobile_drive` | Throttle / steer percentage with optional auto-stop duration |
| `batmobile_effect` | Bundled toggle for lamps / smoke / armor / cannon / fire |
| `batmobile_sound` | Trigger sound effect by index |
| `batmobile_status` | Current arm state, last-command time, sound catalog |

Wire it into Claude, Aria, OpenAI, or any MCP-compatible assistant by adding
your Pi's address as a remote MCP server.

## Known limitations

- **Camera does not work.** The Batmobile's RTSP camera handshakes correctly
  but emits no frames. This is a documented firmware fragility across the
  product line — even Mattel's own app's reviews describe the same symptom.
  We've enumerated the entire network surface; there's no software fix from
  the network side. The WebUI camera section has been removed accordingly.
  See [docs/camera-investigation.md](docs/camera-investigation.md) for the
  full debugging record if you want to try where we stopped.
- **Battery telemetry is not decoded.** The Batmobile sends back a 14-byte
  sensor packet with seven 10-bit values; one is almost certainly battery,
  but which one is unknown. Decoding contributions welcome.
- **Sound-effect catalog is undocumented.** 256 sound indices exist, but no
  one has yet labeled which is which. Run `sound_sweep.py` to walk through
  them and submit a PR with the labels.

## Hardware bundle (limited)

If you'd rather not flash a Pi yourself, **Salient Concepts** offers two
options:

- **Full bundle** — one open-box Mattel Batmobile (FKM40) paired with a
  pre-flashed Pi 4 controller, ready to drive out of the package. Limited
  single-unit availability.
- **Pre-flashed Pi 4 only** — for owners of a working FKM40 who'd rather
  skip the install. Pi 4, microSD, power supply, ready to plug in.

Watch [salient-concepts.github.io](https://salient-concepts.github.io/)
for availability.

## Documentation

- [docs/troubleshooting.md](docs/troubleshooting.md) — operational gotchas
  hit in production: stuck WiFi handshake after recharge, runaway-motor
  prevention, password recovery, PoE undervolt, ARM hangs
- [docs/protocol.md](docs/protocol.md) — full reverse-engineered command
  table, packet format, sensor response, mandatory shutdown sequence
- [docs/architecture.md](docs/architecture.md) — controller / WebUI / MCP /
  systemd unit relationships
- [docs/manual-install.md](docs/manual-install.md) — step-by-step if the
  bootstrap script doesn't fit your environment
- [docs/camera-investigation.md](docs/camera-investigation.md) — full record
  of the camera debugging effort and why we declared it out of scope
- [LEGAL.md](LEGAL.md) — trademarks, reverse-engineering posture,
  right-to-repair basis

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Most-wanted areas:

- Sensor-response decoding (which byte = battery?)
- Sound-effect catalog labeling
- Camera firmware investigation (UART path, OpenIPC, etc.)
- Additional language UIs (current strings are English-only)

## License

[MIT](LICENSE) — do whatever you want, just keep the copyright notice.

## Acknowledgements

- The original Mattel team — for shipping the toy and the protocol that
  made it reverse-engineerable.
- Owners who kept asking *"is anyone fixing this?"* — you were the
  motivation.

---

**Not affiliated with, endorsed by, or sponsored by Mattel, Inc., DC
Comics, or Warner Bros. Discovery.** See [LEGAL.md](LEGAL.md).
