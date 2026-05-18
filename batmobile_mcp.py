#!/usr/bin/env python3
"""
EPOCH Batmobile MCP server (Pattern B, JSON-RPC over HTTP)
==========================================================

The ai-engine MCP gateway proxies tool calls from Aria here. We register one
proxy entry per tool in the gateway; this endpoint dispatches them against
the live BatmobileController owned by batmobile_service.

Tool surface (6):
  batmobile_arm()                                  -> connect wlan0 + start controller
  batmobile_disarm()                               -> shutdown + disconnect wlan0
  batmobile_drive(throttle_pct, steer_pct,
                  duration_sec=null)               -> drive with optional auto-stop
  batmobile_effect(led=null, smoke=null,
                   armor=false, gun_up=false,
                   fire=false)                     -> bundled effect toggles
  batmobile_sound(index)                           -> play sound 1-N
  batmobile_status()                               -> armed state, last cmd, sounds
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

LOG = logging.getLogger("batmobile.mcp")


TOOLS: list[dict[str, Any]] = [
    {
        "name": "batmobile_arm",
        "description": "Bring up the WiFi link to the Batmobile and start the 10Hz UDP control loop. Required before any drive/effect command.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "batmobile_disarm",
        "description": "Run the mandatory shutdown sequence (effects off, motors stop, 70 idle packets) then drop the WiFi link. Always safe to call.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "batmobile_drive",
        "description": "Drive the Batmobile. throttle_pct: -100 (full reverse) to 100 (full forward), 0 = stop. steer_pct: -100 (full left) to 100 (full right), 0 = center. duration_sec: optional, auto-stops after.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "throttle_pct": {"type": "integer", "minimum": -100, "maximum": 100},
                "steer_pct": {"type": "integer", "minimum": -100, "maximum": 100},
                "duration_sec": {"type": "number", "minimum": 0.1, "maximum": 10.0},
            },
            "required": ["throttle_pct", "steer_pct"],
        },
    },
    {
        "name": "batmobile_effect",
        "description": "Toggle one or more Batmobile effects in a single call. led/smoke take true/false (state). armor/gun_up/fire take true to trigger the toggle/action; omit or false to leave alone.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "led": {"type": "boolean", "description": "Headlight LED on/off"},
                "smoke": {"type": "boolean", "description": "Smoke generator on/off"},
                "armor": {"type": "boolean", "description": "Toggle armor open/close"},
                "gun_up": {"type": "boolean", "description": "Toggle gun raise/lower"},
                "fire": {"type": "boolean", "description": "Fire/rotate the gun"},
            },
            "required": [],
        },
    },
    {
        "name": "batmobile_sound",
        "description": "Play a sound effect by 1-based index. See batmobile_status for the catalog.",
        "inputSchema": {
            "type": "object",
            "properties": {"index": {"type": "integer", "minimum": 1, "maximum": 256}},
            "required": ["index"],
        },
    },
    {
        "name": "batmobile_status",
        "description": "Return current arm state, last command time, and the sound-effect catalog.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]


def _ok(req_id: Any, payload: Any) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": False},
    }


def _err(req_id: Any, message: str, code: int = -32000) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _pct_to_axis(pct: int) -> int:
    """Convert -100..100 to controller's 0..200 (center=100)."""
    pct = max(-100, min(100, int(pct)))
    return 100 + pct


async def _call_tool(name: str, args: dict[str, Any], state) -> dict[str, Any]:
    if name == "batmobile_arm":
        return await state.arm()

    if name == "batmobile_disarm":
        return await state.disarm()

    if name == "batmobile_status":
        from batmobile_service import _load_sounds
        return {**state.status(), "sounds": _load_sounds()}

    state.require_armed()

    if name == "batmobile_drive":
        throttle = _pct_to_axis(args.get("throttle_pct", 0))
        steer = _pct_to_axis(args.get("steer_pct", 0))
        duration = args.get("duration_sec")
        state.controller.drive(throttle, steer)
        state.log("mcp", "drive", {"throttle_pct": args.get("throttle_pct", 0), "steer_pct": args.get("steer_pct", 0), "duration_sec": duration})
        if duration:
            await asyncio.sleep(float(duration))
            state.controller.full_stop()
            state.log("mcp", "auto_stop", {"after_sec": duration})
            return {"ok": True, "auto_stopped_after_sec": duration}
        return {"ok": True, "throttle_pct": args.get("throttle_pct", 0), "steer_pct": args.get("steer_pct", 0)}

    if name == "batmobile_effect":
        applied = []
        if "led" in args:
            state.controller.set_led(bool(args["led"]))
            applied.append(f"led={'on' if args['led'] else 'off'}")
        if "smoke" in args:
            state.controller.set_smoke(bool(args["smoke"]))
            applied.append(f"smoke={'on' if args['smoke'] else 'off'}")
        if args.get("armor"):
            state.controller.toggle_armor()
            applied.append("armor=toggle")
        if args.get("gun_up"):
            state.controller.toggle_gun_elevation()
            applied.append("gun_up=toggle")
        if args.get("fire"):
            state.controller.fire_gun()
            applied.append("fire=trigger")
        state.log("mcp", "effect", args)
        return {"ok": True, "applied": applied}

    if name == "batmobile_sound":
        idx = int(args["index"])
        state.controller.play_sound(idx)
        state.log("mcp", "sound", {"index": idx})
        return {"ok": True, "index": idx}

    raise ValueError(f"unknown tool: {name}")


async def handle_mcp(req: dict[str, Any], state) -> dict[str, Any]:
    """Top-level JSON-RPC dispatch. Mirrors the gateway's protocol surface."""
    method = req.get("method")
    req_id = req.get("id")

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if not name:
            return _err(req_id, "missing tool name", -32602)
        try:
            result = await _call_tool(name, args, state)
            return _ok(req_id, result)
        except Exception as e:
            LOG.exception("tool %s failed", name)
            return _err(req_id, f"{type(e).__name__}: {e}")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "epoch-batmobile", "version": "1.0"},
                "capabilities": {"tools": {}},
            },
        }

    return _err(req_id, f"unknown method: {method}", -32601)
