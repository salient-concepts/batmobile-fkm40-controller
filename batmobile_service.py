#!/usr/bin/env python3
"""
EPOCH Batmobile Service
=======================

Single-process FastAPI daemon that owns the BatmobileController singleton.
Exposes three input surfaces, all funneling into the same controller:

  - WebUI       : phone-friendly HTML/JS at GET /
  - WebSocket   : continuous drive stream at /ws/drive
  - REST        : one-shot effects at /api/{led,smoke,armor,gun_up,fire,sound,...}
  - MCP         : JSON-RPC at POST /mcp (Pattern B remote MCP, gateway proxies)

The controller owns the UDP socket and the 10Hz tick. It MUST be the only
process touching the Batmobile -- two processes writing UDP races into
runaway-motor territory.

Lifecycle:
  Service starts disarmed -> controller created, no UDP traffic.
  POST /api/arm        -> bat-connect (wlan0 to Batmobile AP) + controller.connect()
  POST /api/disarm     -> controller.disconnect() (full shutdown) + bat-disconnect
  Any drive/effect cmd -> 503 if not armed.

Designed for batbridge (Pi 4, NetworkManager + nmcli).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from batmobile_controller import BatmobileController

LOG = logging.getLogger("batmobile.service")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

BAT_CONNECT = os.environ.get("BAT_CONNECT", "/usr/local/bin/bat-connect")
BAT_DISCONNECT = os.environ.get("BAT_DISCONNECT", "/usr/local/bin/bat-disconnect")
STATIC_DIR = os.environ.get("BATMOBILE_STATIC", os.path.join(os.path.dirname(__file__), "static"))
SOUNDS_FILE = os.environ.get("BATMOBILE_SOUNDS", os.path.join(os.path.dirname(__file__), "sounds.json"))


class ServiceState:
    """Holds the controller singleton + arm state. Not thread-safe; serialized via async."""

    def __init__(self) -> None:
        self.controller = BatmobileController()
        self.armed: bool = False
        self.armed_at: float | None = None
        self.last_command_at: float | None = None
        self.command_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def arm(self) -> dict[str, Any]:
        async with self._lock:
            if self.armed:
                return self.status()
            LOG.info("Arming: bat-connect")
            rc = await _run([BAT_CONNECT])
            if rc != 0:
                raise HTTPException(status_code=502, detail=f"bat-connect failed (rc={rc})")
            self.controller.connect()
            self.armed = True
            self.armed_at = time.time()
            LOG.info("Armed")
            return self.status()

    async def disarm(self) -> dict[str, Any]:
        async with self._lock:
            if not self.armed:
                return self.status()
            LOG.info("Disarming: controller shutdown")
            await asyncio.to_thread(self.controller.disconnect)
            LOG.info("Disarming: bat-disconnect")
            await _run([BAT_DISCONNECT])
            self.armed = False
            self.armed_at = None
            LOG.info("Disarmed")
            return self.status()

    def require_armed(self) -> None:
        if not self.armed:
            raise HTTPException(status_code=503, detail="not armed; POST /api/arm first")

    def log(self, source: str, action: str, payload: dict | None = None) -> None:
        entry = {"t": time.time(), "source": source, "action": action, "payload": payload or {}}
        self.command_log.append(entry)
        if len(self.command_log) > 50:
            self.command_log = self.command_log[-50:]
        self.last_command_at = entry["t"]

    def status(self) -> dict[str, Any]:
        return {
            "armed": self.armed,
            "armed_at": self.armed_at,
            "armed_for_sec": (time.time() - self.armed_at) if self.armed_at else None,
            "last_command_at": self.last_command_at,
            "demo_running": getattr(self.controller, "_demo_running", False),
        }


async def _run(cmd: list[str]) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        LOG.warning("cmd %s failed rc=%s err=%s", cmd, proc.returncode, err.decode().strip())
    return proc.returncode or 0


def _load_sounds() -> dict[int, str]:
    if not os.path.exists(SOUNDS_FILE):
        return {}
    try:
        with open(SOUNDS_FILE) as f:
            data = json.load(f)
        return {int(k): str(v) for k, v in data.items()}
    except Exception as e:
        LOG.warning("failed to load sounds catalog: %s", e)
        return {}


# ---- Telemetry helpers ---------------------------------------------------------

_telemetry_cache: dict[str, Any] = {"data": None, "at": 0.0}
TELEMETRY_TTL = 1.0   # seconds — cap subprocess load to ~1Hz regardless of poll rate

IW_BIN = "/usr/sbin/iw"
PING_BIN = "/usr/bin/ping"


async def _read_link_info() -> dict[str, Any]:
    """Run `iw dev wlan0 link` and parse signal (dBm) + tx bitrate (Mbps).
    Returns {"signal_dbm": int|None, "bitrate_mbps": float|None, "ssid": str|None}.
    When wlan0 isn't associated, all fields are None.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            IW_BIN, "dev", "wlan0", "link",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
    except (asyncio.TimeoutError, FileNotFoundError):
        return {"signal_dbm": None, "bitrate_mbps": None, "ssid": None}
    text = (out or b"").decode("utf-8", "ignore")
    if "Not connected" in text:
        return {"signal_dbm": None, "bitrate_mbps": None, "ssid": None}
    sig = brate = ssid = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("signal:"):
            try: sig = int(s.split()[1])
            except Exception: pass
        elif s.startswith("tx bitrate:"):
            try: brate = float(s.split()[2])
            except Exception: pass
        elif s.startswith("SSID:"):
            ssid = s.split(":", 1)[1].strip()
    return {"signal_dbm": sig, "bitrate_mbps": brate, "ssid": ssid}


async def _ping_batmobile() -> float | None:
    """Single ICMP echo with 1s timeout. Returns RTT in ms, or None if unreachable."""
    try:
        proc = await asyncio.create_subprocess_exec(
            PING_BIN, "-c", "1", "-W", "1", "-q", "192.168.201.1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
    except (asyncio.TimeoutError, FileNotFoundError):
        return None
    if proc.returncode != 0:
        return None
    text = (out or b"").decode("utf-8", "ignore")
    # rtt min/avg/max/mdev = 1.846/1.846/1.846/0.000 ms
    for line in text.splitlines():
        if "min/avg/max" in line:
            try:
                stats = line.split("=")[1].strip().split()[0]
                return float(stats.split("/")[1])  # avg
            except Exception:
                pass
    return None


def _read_cpu_temp() -> float | None:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except Exception:
        return None


def _read_loadavg() -> float | None:
    try:
        with open("/proc/loadavg") as f:
            return float(f.read().split()[0])
    except Exception:
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    LOG.info("Batmobile service starting")
    yield
    LOG.info("Batmobile service shutting down")
    if state.armed:
        try:
            await asyncio.to_thread(state.controller.disconnect)
        except Exception as e:
            LOG.warning("shutdown error: %s", e)


state = ServiceState()
app = FastAPI(title="EPOCH Batmobile Service", version="1.0", lifespan=lifespan)


# ---- REST: lifecycle ----------------------------------------------------------

@app.post("/api/arm")
async def arm() -> dict[str, Any]:
    return await state.arm()


@app.post("/api/disarm")
async def disarm() -> dict[str, Any]:
    return await state.disarm()


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return {**state.status(), "sounds": _load_sounds()}


@app.get("/api/log")
async def log() -> dict[str, Any]:
    return {"entries": state.command_log[-20:]}


@app.get("/api/telemetry")
async def telemetry() -> dict[str, Any]:
    """Live system telemetry. Cached ~1s to keep subprocess churn low under polling."""
    now = time.time()
    cached = _telemetry_cache.get("data")
    if cached and (now - _telemetry_cache.get("at", 0.0)) < TELEMETRY_TTL:
        return cached
    link, rtt = await asyncio.gather(_read_link_info(), _ping_batmobile())
    data = {
        "ts": now,
        "armed": state.armed,
        "link": link,
        "rtt_ms": rtt,
        "cpu_temp_c": _read_cpu_temp(),
        "loadavg": _read_loadavg(),
        "tx_rate_hz": 10 if state.armed else 0,
    }
    _telemetry_cache["data"] = data
    _telemetry_cache["at"] = now
    return data


# ---- REST: one-shot effects ---------------------------------------------------

@app.post("/api/led")
async def api_led(on: bool = True) -> dict[str, Any]:
    state.require_armed()
    state.controller.set_led(on)
    state.log("rest", "led", {"on": on})
    return {"ok": True, "on": on}


@app.post("/api/smoke")
async def api_smoke(on: bool = True) -> dict[str, Any]:
    state.require_armed()
    state.controller.set_smoke(on)
    state.log("rest", "smoke", {"on": on})
    return {"ok": True, "on": on}


@app.post("/api/armor")
async def api_armor() -> dict[str, Any]:
    state.require_armed()
    state.controller.toggle_armor()
    state.log("rest", "armor")
    return {"ok": True}


@app.post("/api/gun_up")
async def api_gun_up() -> dict[str, Any]:
    state.require_armed()
    state.controller.toggle_gun_elevation()
    state.log("rest", "gun_up")
    return {"ok": True}


@app.post("/api/fire")
async def api_fire() -> dict[str, Any]:
    state.require_armed()
    state.controller.fire_gun()
    state.log("rest", "fire")
    return {"ok": True}


@app.post("/api/sound/{index}")
async def api_sound(index: int) -> dict[str, Any]:
    state.require_armed()
    if index < 1 or index > 256:
        raise HTTPException(status_code=400, detail="index 1-256")
    state.controller.play_sound(index)
    state.log("rest", "sound", {"index": index})
    return {"ok": True, "index": index}


@app.post("/api/stop")
async def api_stop() -> dict[str, Any]:
    state.require_armed()
    state.controller.full_stop()
    state.log("rest", "stop")
    return {"ok": True}


@app.post("/api/demo")
async def api_demo() -> dict[str, Any]:
    """Run the choreographed demo sequence in the background. Returns
    immediately; the demo runs ~70s during which the controller's normal
    drive/effect loop yields the radio. Disarm aborts cleanly."""
    state.require_armed()
    if state.controller._demo_running:
        raise HTTPException(status_code=409, detail="demo already running")
    from batmobile_controller import run_demo
    state.log("rest", "demo_start")

    async def _run():
        try:
            await asyncio.to_thread(run_demo, state.controller, False)
        except Exception as e:
            LOG.warning("demo error: %s", e)
        finally:
            state.controller._demo_running = False
            state.log("rest", "demo_end")

    asyncio.create_task(_run())
    return {"ok": True, "running": True}


# ---- WebSocket: continuous drive ---------------------------------------------

@app.websocket("/ws/drive")
async def ws_drive(ws: WebSocket) -> None:
    await ws.accept()
    LOG.info("drive WS connected")
    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=0.5)
            except asyncio.TimeoutError:
                # No update -- if armed, ensure we're not driving
                if state.armed:
                    state.controller.full_stop()
                continue
            if not state.armed:
                await ws.send_json({"error": "not armed"})
                continue
            kind = msg.get("type", "drive")
            if kind == "drive":
                t = int(msg.get("throttle", 100))
                s = int(msg.get("steering", 100))
                state.controller.drive(t, s)
                state.log("ws", "drive", {"throttle": t, "steering": s})
            elif kind == "stop":
                state.controller.full_stop()
                state.log("ws", "stop")
    except WebSocketDisconnect:
        LOG.info("drive WS disconnected -- safety stop")
        if state.armed:
            state.controller.full_stop()
    except Exception as e:
        LOG.warning("drive WS error: %s", e)
        if state.armed:
            state.controller.full_stop()


# ---- MCP: JSON-RPC tool surface (Pattern B remote) ---------------------------

from batmobile_mcp import handle_mcp


@app.post("/mcp")
async def mcp_endpoint(req: dict) -> dict[str, Any]:
    return await handle_mcp(req, state)


# ---- Static WebUI ------------------------------------------------------------

if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


# ---- Signal handling for systemd ---------------------------------------------

def _handle_term(signum, frame):
    LOG.info("signal %s -- shutdown", signum)
    if state.armed:
        try:
            state.controller.disconnect()
        except Exception:
            pass
    raise SystemExit(0)


signal.signal(signal.SIGINT, _handle_term)
signal.signal(signal.SIGTERM, _handle_term)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_config=None)
