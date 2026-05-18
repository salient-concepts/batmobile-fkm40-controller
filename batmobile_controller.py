#!/usr/bin/env python3
"""
EPOCH Batmobile Controller
Reverse-engineered from Mattel Justice League Ultimate Batmobile APK (com.mattel.batmobilerc)

Protocol: Plain UDP ASCII text over WiFi
Target: 192.168.201.1:1051 (Batmobile acts as WiFi AP)
Send rate: 10 Hz (100ms intervals)
Camera: RTSP at rtsp://192.168.201.1/live/ch00_0 (1280x720)

Packet format: CMD1_VAL1[_CMD2_VAL2[_CMD3_VAL3]]_50_F0[_00_00...]_XX
  - Up to 3 command pairs per packet
  - 50_F0 = sync/heartbeat marker
  - Padded to 4 slots total (cmd pairs + sync + padding)
  - XX = 01 every 10th packet, otherwise 00
  - Idle packet: 41_80_31_80_50_F0_00_00_00

Command table:
  41_XX  Throttle    80=stop, 81-FF=forward (speed+128), 01-7F=reverse
  31_XX  Steering    80=center, 81-FF=right (angle+128), 01-7F=left
  A1_10  LED on      A1_01 = LED off
  91_10  Smoke on    91_01 = smoke off
  21_64  Toggle body shape (armor open/close)
  21_E4  Toggle gun up/down
  11_E4  Gun rotate/fire
  01_XX  Play sound  XX = sound_index - 1
  B1_00  Calibrate reset  B1_81 = +1  B1_01 = -1

Sensor response: 14 bytes, 7x 10-bit values
  Each pair: ((byte[n] & 0x03) << 8) + (byte[n+1] & 0xFF)

HTTP endpoints:
  GET http://192.168.201.1/custom/getDeviceInformation.cgi  -> JSON with software_version
  GET http://192.168.201.1/custom/getVideoProfiles.cgi      -> JSON with resolution
  GET http://192.168.201.1/getWifiConfig.cgi                -> JSON with AP_ESSID, AP_key
  GET http://192.168.201.1/isp/awb_ctl.cgi?ENABLE=1         -> Enable auto white balance
"""

import socket
import time
import signal
import sys
import threading
import urllib.request
import json


BATMOBILE_IP = "192.168.201.1"
BATMOBILE_PORT = 1051
SEND_INTERVAL = 0.1  # 100ms

# Shutdown constants
SHUTDOWN_STOP_PACKETS = 50     # 5 seconds of stop at 10Hz
SHUTDOWN_SETTLE_PACKETS = 20   # 2 seconds of idle after effects off


class BatmobileController:
    def __init__(self, ip=BATMOBILE_IP, port=BATMOBILE_PORT):
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.1)
        self.running = False
        self.receive_count = 0

        # Command state (mirrors AndroidMain.java fields)
        self.str_fb = ""        # throttle (forward/back)
        self.str_rl = ""        # steering (left/right)
        self.str_led = ""       # headlight LED
        self.str_smoke = ""     # smoke generator
        self.str_shape = ""     # body shape (armor)
        self.str_updown = ""    # gun elevation
        self.str_rotate = ""    # gun rotation
        self.str_voice = ""     # sound effects
        self.str_calibration = ""
        self.str_adj = ""
        self.tag_rotate = False

        self._send_thread = None
        self._sensor_data = [0] * 7
        self._demo_running = False  # When True, _send_loop yields the radio

    # --- Control methods ---

    def set_throttle(self, value: int):
        """Set throttle. 0-99=reverse, 100=stop, 101-200=forward."""
        value = max(0, min(200, value))
        if value < 100:
            speed = 100 - value
            self.str_fb = f"41_{speed:02x}"
        elif value == 100:
            self.str_fb = ""
        else:
            speed = (value - 100) + 128
            self.str_fb = f"41_{speed:02x}"

    def stop_throttle(self):
        """Emergency stop -- sends explicit stop command."""
        self.str_fb = "41_80"

    def set_steering(self, value: int):
        """Set steering. 0-99=left, 100=center, 101-200=right."""
        value = max(0, min(200, value))
        if value < 100:
            angle = 100 - value
            self.str_rl = f"31_{angle:02x}"
        elif value == 100:
            self.str_rl = ""
        else:
            angle = (value - 100) + 128
            self.str_rl = f"31_{angle:02x}"

    def center_steering(self):
        """Center the steering."""
        self.str_rl = "31_80"

    def set_led(self, on: bool):
        """Turn head LED on/off."""
        self.str_led = "A1_10" if on else "A1_01"

    def set_smoke(self, on: bool):
        """Turn smoke generator on/off."""
        self.str_smoke = "91_10" if on else "91_01"

    def toggle_armor(self):
        """Toggle body shape (armor open/close)."""
        self.str_shape = "21_64"

    def toggle_gun_elevation(self):
        """Toggle gun up/down."""
        self.str_updown = "21_E4"

    def fire_gun(self):
        """Rotate/fire the machine gun."""
        self.tag_rotate = True

    def play_sound(self, index: int):
        """Play a sound effect (1-based index)."""
        if index >= 1:
            self.str_voice = f"01_{(index - 1):02x}"

    def calibrate(self, direction: int = 0):
        """Calibrate steering. 0=reset, 1=right, -1=left."""
        if direction == 0:
            self.str_calibration = "B1_00"
        elif direction == 1:
            self.str_calibration = "B1_81"
        elif direction == -1:
            self.str_calibration = "B1_01"

    # --- Driving helpers ---

    def drive(self, throttle: int, steering: int):
        """Combined drive command. throttle/steering: 0-200, center=100."""
        self.set_throttle(throttle)
        self.set_steering(steering)

    def full_stop(self):
        """Stop all movement."""
        self.stop_throttle()
        self.center_steering()

    # --- Packet assembly (exact replica of AndroidMain.getSendCmd) ---

    def _build_packet(self) -> str:
        commands = []
        count = 0

        # Priority order matches original app
        for attr, one_shot in [
            ("str_fb", False), ("str_rl", False), ("str_calibration", True),
            ("str_led", True), ("str_smoke", True), ("str_shape", True),
            ("str_updown", True), ("str_voice", True),
        ]:
            if count >= 3:
                break
            val = getattr(self, attr)
            if val:
                commands.append(val)
                count += 1
                if one_shot:
                    setattr(self, attr, "")

        # Gun rotation
        if self.tag_rotate and count < 3:
            commands.append("11_E4")
            count += 1
            self.tag_rotate = False

        # Adj
        if self.str_adj and count < 3:
            commands.append(self.str_adj)
            count += 1
            self.str_adj = ""

        # Build packet string
        self.receive_count = (self.receive_count + 1) % 10
        tail = "01" if self.receive_count == 0 else "00"

        if count > 0:
            packet = "_".join(commands) + "_50_F0"
            slots_used = count + 1  # commands + sync marker
            for _ in range(4 - slots_used):
                packet += "_00_00"
            packet += f"_{tail}"
        else:
            # Idle packet -- send neutral throttle + steering
            packet = f"41_80_31_80_50_F0_00_00_{tail}"

        return packet

    def _send_packet(self, packet: str):
        """Send a single UDP packet to the Batmobile."""
        try:
            self.sock.sendto(packet.encode("ascii"), (self.ip, self.port))
        except Exception:
            pass

    def _send_loop(self):
        """Background send loop at 10 Hz. Yields when a demo owns the radio."""
        while self.running:
            if not self._demo_running:
                packet = self._build_packet()
                self._send_packet(packet)
            time.sleep(SEND_INTERVAL)

    # --- Shutdown sequence ---

    def shutdown(self):
        """Safe shutdown sequence. MUST be called before disconnecting WiFi.

        Failure to call this before dropping WiFi will leave motors running.
        """
        print("Shutdown: effects off...")
        self.set_smoke(False)
        self._send_packet(self._build_packet())
        time.sleep(0.2)

        self.set_led(False)
        self._send_packet(self._build_packet())
        time.sleep(0.2)

        print("Shutdown: motors stop...")
        self.full_stop()

        # Spam stop packets to guarantee motors are dead
        idle = "41_80_31_80_50_F0_00_00_00"
        for i in range(SHUTDOWN_STOP_PACKETS):
            self._send_packet(idle)
            time.sleep(SEND_INTERVAL)

        # Settle period -- keep sending idle
        for i in range(SHUTDOWN_SETTLE_PACKETS):
            self._send_packet(idle)
            time.sleep(SEND_INTERVAL)

        print("Shutdown: complete")

    # --- Lifecycle ---

    def connect(self):
        """Start the send loop. Assumes WiFi is already connected to Batmobile AP."""
        self.running = True
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._send_thread.start()
        print(f"Connected to Batmobile at {self.ip}:{self.port}")

    def disconnect(self):
        """Safe disconnect -- runs full shutdown sequence then stops send loop."""
        self.shutdown()
        self.running = False
        if self._send_thread:
            self._send_thread.join(timeout=2)
        print("Disconnected")

    # --- HTTP queries ---

    def get_device_info(self) -> dict:
        """Query device information via HTTP."""
        try:
            resp = urllib.request.urlopen(
                f"http://{self.ip}/custom/getDeviceInformation.cgi", timeout=3
            ).read().decode()
            return json.loads(resp)
        except Exception as e:
            return {"error": str(e)}

    def get_firmware_version(self) -> str:
        """Query firmware version via HTTP."""
        info = self.get_device_info()
        return info.get("software_version", info.get("error", "Unknown"))

    def get_video_profiles(self) -> dict:
        """Query video stream profiles via HTTP."""
        try:
            resp = urllib.request.urlopen(
                f"http://{self.ip}/custom/getVideoProfiles.cgi", timeout=3
            ).read().decode()
            return json.loads(resp)
        except Exception as e:
            return {"error": str(e)}

    def get_wifi_config(self) -> dict:
        """Query WiFi AP configuration via HTTP."""
        try:
            resp = urllib.request.urlopen(
                f"http://{self.ip}/getWifiConfig.cgi", timeout=3
            ).read().decode()
            return json.loads(resp)
        except Exception as e:
            return {"error": str(e)}


# --- Demo sequence ---

def run_demo(bat: BatmobileController, run_shutdown: bool = True):
    """Full choreographed demo sequence.

    When called from the WebUI service, pass ``run_shutdown=False`` so the
    controller stays armed and the user can keep driving after the demo.
    """
    bat._demo_running = True
    def send(pkt, label, delay=1.5):
        bat._send_packet(pkt)
        print(f"  >> {label}")
        time.sleep(delay)

    def send_continuous(pkt, label, duration=1.0):
        print(f"  >> {label} ({duration}s)")
        end = time.time() + duration
        while time.time() < end:
            bat._send_packet(pkt)
            time.sleep(SEND_INTERVAL)

    def stop(duration=0.5):
        send_continuous("41_80_31_80_50_F0_00_00_00", "HOLD", duration)

    print("\n=== ACT 1: AWAKENING ===")
    send("01_02_50_F0_00_00_00_00_00", "Engine sound", 2)
    send("A1_10_50_F0_00_00_00_00_00", "Headlights ON", 2)
    send("01_00_50_F0_00_00_00_00_00", "Power up sound", 2)

    print("\n=== ACT 2: TRANSFORMATION ===")
    send("91_10_50_F0_00_00_00_00_00", "Smoke ON", 2.5)
    send("21_64_50_F0_00_00_00_00_00", "Armor OPEN", 3)
    send("01_03_50_F0_00_00_00_00_00", "Transform sound", 2)

    print("\n=== ACT 3: WEAPONS ONLINE ===")
    send("21_E4_50_F0_00_00_00_00_00", "Gun RAISE", 2.5)
    send("01_04_50_F0_00_00_00_00_00", "Weapon charge sound", 1.5)
    send("11_E4_50_F0_00_00_00_00_00", "Gun FIRE", 2)
    send("11_E4_50_F0_00_00_00_00_00", "Gun FIRE again", 2)
    send("11_E4_50_F0_00_00_00_00_00", "Gun FIRE burst", 1.5)

    print("\n=== ACT 4: PATROL ===")
    send("01_01_50_F0_00_00_00_00_00", "Engine rev", 1.5)
    send_continuous("41_A0_31_80_50_F0_00_00_00", "Forward cruise", 2.0)
    stop(0.5)
    send_continuous("41_98_31_B0_50_F0_00_00_00", "Turn RIGHT", 1.5)
    stop(0.5)
    send_continuous("41_98_31_50_50_F0_00_00_00", "Turn LEFT", 1.5)
    stop(0.5)
    send_continuous("41_B0_31_80_50_F0_00_00_00", "Forward BURST", 1.5)
    stop(0.5)
    send_continuous("41_30_31_80_50_F0_00_00_00", "REVERSE", 1.5)
    stop(0.8)

    print("\n=== ACT 5: FULL ASSAULT ===")
    send("01_02_50_F0_00_00_00_00_00", "Battle sound", 1)
    print("  >> FULL ASSAULT: smoke + fire + drive")
    for i in range(20):
        if i % 3 == 0:
            pkt = "91_10_11_E4_41_98_50_F0_00"
        else:
            pkt = "41_98_31_90_50_F0_00_00_00"
        bat._send_packet(pkt)
        time.sleep(SEND_INTERVAL)
    stop(0.8)

    print("  >> SPIN MOVE")
    send_continuous("41_90_31_FF_50_F0_00_00_00", "Hard right spin", 2.0)
    stop(0.8)
    send("11_E4_50_F0_00_00_00_00_00", "Final shot 1", 0.8)
    send("11_E4_50_F0_00_00_00_00_00", "Final shot 2", 0.8)
    send("11_E4_50_F0_00_00_00_00_00", "Final shot 3", 1.5)

    print("\n=== ACT 6: STAND DOWN ===")
    send("01_00_50_F0_00_00_00_00_00", "Power down sound", 2)
    send("91_01_50_F0_00_00_00_00_00", "Smoke OFF", 1.5)
    send("21_E4_50_F0_00_00_00_00_00", "Gun LOWER", 2)
    send("21_64_50_F0_00_00_00_00_00", "Armor CLOSE", 2.5)
    send("A1_01_50_F0_00_00_00_00_00", "Headlights OFF", 2)

    if run_shutdown:
        bat.shutdown()
    bat._demo_running = False
    print("\n========================================")
    print("   EPOCH BATMOBILE - STANDING BY")
    print("========================================\n")


# --- CLI ---

if __name__ == "__main__":
    bat = BatmobileController()

    # Catch Ctrl+C and ensure clean shutdown
    def signal_handler(sig, frame):
        print("\nInterrupted -- emergency shutdown...")
        bat.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if "--test-packet" in sys.argv:
        print("Idle packet:", bat._build_packet())
        bat.set_throttle(150)
        bat.set_steering(130)
        print("Forward+right:", bat._build_packet())
        bat.set_led(True)
        print("LED on:", bat._build_packet())
        bat.toggle_armor()
        print("Armor toggle:", bat._build_packet())
        bat.fire_gun()
        print("Fire gun:", bat._build_packet())
        bat.full_stop()
        print("Full stop:", bat._build_packet())
        sys.exit(0)

    if "--demo" in sys.argv:
        print("========================================")
        print("   EPOCH BATMOBILE DEMO")
        print("========================================")
        bat.connect()
        run_demo(bat)
        sys.exit(0)

    if "--info" in sys.argv:
        print("Device info:", json.dumps(bat.get_device_info(), indent=2))
        print("Video profiles:", json.dumps(bat.get_video_profiles(), indent=2))
        sys.exit(0)

    # Interactive keyboard control
    print("EPOCH Batmobile Controller")
    print(f"Target: {BATMOBILE_IP}:{BATMOBILE_PORT}")
    print()
    print("Commands: w/s=throttle, a/d=steer, space=stop")
    print("          l/L=LED on/off, k/K=smoke on/off")
    print("          m=armor, g=gun elevation, f=fire")
    print("          1-9=sounds, c=calibrate reset")
    print("          D=run demo, q=quit")
    print()

    bat.connect()

    try:
        import tty
        import termios

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        tty.setcbreak(fd)

        try:
            while True:
                ch = sys.stdin.read(1)
                if ch == "q":
                    break
                elif ch == "w":
                    bat.set_throttle(160)
                elif ch == "W":
                    bat.set_throttle(190)
                elif ch == "s":
                    bat.set_throttle(40)
                elif ch == "S":
                    bat.set_throttle(10)
                elif ch == "a":
                    bat.set_steering(40)
                elif ch == "A":
                    bat.set_steering(10)
                elif ch == "d":
                    bat.set_steering(160)
                elif ch == "D" and False:  # reserved for demo
                    pass
                elif ch == " ":
                    bat.full_stop()
                elif ch == "l":
                    bat.set_led(True)
                elif ch == "L":
                    bat.set_led(False)
                elif ch == "k":
                    bat.set_smoke(True)
                elif ch == "K":
                    bat.set_smoke(False)
                elif ch == "m":
                    bat.toggle_armor()
                elif ch == "g":
                    bat.toggle_gun_elevation()
                elif ch == "f":
                    bat.fire_gun()
                elif ch == "c":
                    bat.calibrate(0)
                elif ch in "123456789":
                    bat.play_sound(int(ch))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except ImportError:
        print("Interactive mode requires a terminal.")
        print("Use --demo for choreographed demo or --test-packet for offline test.")

    bat.disconnect()
