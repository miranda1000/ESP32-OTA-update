#!/usr/bin/env python3
"""
esp32_ota.py — ESP32 OTA helper for PlatformIO
================================================

Sub-commands
────────────
  check   Query a USB-connected ESP32 using the serial command protocol.
  scan    Discover ESP32 boards on the network via mDNS, with wildcard filter.
  flash   Build and upload via USB (initial flash, supports --hostname).
  upload  Build and upload wirelessly via OTA (espota).

Examples
────────
  # Query MAC / IP / hostname from the board over USB:
  python esp32_ota.py check --port /dev/ttyUSB0
  python esp32_ota.py check --port /dev/ttyUSB0 --cmd get_ip

  # Scan the local network for ArduinoOTA boards:
  python esp32_ota.py scan
  python esp32_ota.py scan --pattern "esp32-blink-*"

  # First USB flash (sets hostname at build time):
  python esp32_ota.py flash --port /dev/ttyUSB0 --hostname esp32-blink-1

  # OTA upload — various ways to specify the target:
  python esp32_ota.py upload --hostname esp32-blink-1   # resolve via mDNS
  python esp32_ota.py upload --ip 192.168.1.42          # direct IP
  python esp32_ota.py upload --port /dev/ttyUSB0        # ask the board
"""

import argparse
import fnmatch
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

# ── Optional dependency checks ────────────────────────────────────────────────

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[error] pyserial missing.  Run:  pip install pyserial")
    sys.exit(1)

try:
    from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False


# ── Constants ─────────────────────────────────────────────────────────────────

BAUD_RATE   = 115200
CMD_TIMEOUT = 5       # seconds to wait for a [CMD] response line
OTA_SERVICE = "_arduino._tcp.local."
USB_ENV     = "esp32_usb"
OTA_ENV     = "esp32_ota"

# [CMD] lines emitted by the firmware
CMD_PATTERN  = re.compile(r"\[CMD\]\s+(\w+):\s*(.+)")
BOOT_MAC     = re.compile(r"\[boot\]\s+MAC\s*:\s*([0-9A-Fa-f:]{17})")
BOOT_IP      = re.compile(r"\[boot\]\s+IP\s*:\s*(\d{1,3}(?:\.\d{1,3}){3})")
BOOT_HOST    = re.compile(r"\[boot\]\s+Hostname\s*:\s*(\S+)")

# Diagnostic patterns — used to give specific failure messages
DIAG_WIFI_CONNECTING = re.compile(r"\[WiFi\] Connecting to (.+)")
DIAG_WIFI_CONNECTED  = re.compile(r"\[WiFi\] Connected")
DIAG_WIFI_TIMEOUT    = re.compile(r"\[WiFi\] Timeout")
DIAG_BROWNOUT        = re.compile(r"Brownout detector was triggered")
DIAG_BOOT_ROM        = re.compile(r"ets \w+ \d+ \d+ \d+:\d+:\d+")  # ROM bootloader line


# ═══════════════════════════════════════════════════════════════════════════
#  Serial helpers
# ═══════════════════════════════════════════════════════════════════════════

def _pick_port() -> str | None:
    """Auto-pick or interactively select a serial port."""
    ports = [p.device for p in serial.tools.list_ports.comports()]
    if not ports:
        print("[error] No serial ports found. Is the board plugged in?")
        return None
    if len(ports) == 1:
        print(f"[serial] Auto-selected: {ports[0]}")
        return ports[0]
    print("Available serial ports:")
    for i, p in enumerate(ports):
        print(f"  [{i}]  {p}")
    try:
        return ports[int(input("Select: ").strip())]
    except (ValueError, IndexError):
        print("[error] Invalid selection.")
        return None


def serial_command(port: str, command: str, timeout: int = CMD_TIMEOUT) -> tuple[list[dict], dict]:
    """
    Send *command* over serial and collect all [CMD] reply lines.

    Returns:
        results  – list of dicts: [{"key": "IP", "value": "192.168.1.42"}, …]
        diag     – dict of observed conditions for failure diagnosis:
                   {
                     "wifi_ssid":      str | None,   # SSID seen in "Connecting to …"
                     "wifi_connected": bool,
                     "wifi_timeout":   bool,
                     "brownout":       bool,
                     "saw_bootrom":    bool,          # ROM bootloader output seen
                   }
    """
    results = []
    diag = {
        "wifi_ssid":      None,
        "wifi_connected": False,
        "wifi_timeout":   False,
        "brownout":       False,
        "saw_bootrom":    False,
    }
    try:
        with serial.Serial(port, BAUD_RATE, timeout=1) as ser:
            ser.reset_input_buffer()
            ser.write((command.strip() + "\n").encode("utf-8"))
            ser.flush()

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    print(f"  ← {line}")

                # Collect diagnostics from every line regardless of [CMD]
                if m := DIAG_WIFI_CONNECTING.search(line):
                    diag["wifi_ssid"] = m.group(1).strip()
                if DIAG_WIFI_CONNECTED.search(line):
                    diag["wifi_connected"] = True
                if DIAG_WIFI_TIMEOUT.search(line):
                    diag["wifi_timeout"] = True
                if DIAG_BROWNOUT.search(line):
                    diag["brownout"] = True
                if DIAG_BOOT_ROM.search(line):
                    diag["saw_bootrom"] = True

                if m := CMD_PATTERN.search(line):
                    results.append({"key": m.group(1), "value": m.group(2).strip()})
                    # Single-key commands finish after one [CMD] line;
                    # get_info sends 3 lines, so keep reading until timeout.
                    if command.strip() != "get_info" and results:
                        break
    except serial.SerialException as exc:
        print(f"[error] Serial error on {port}: {exc}")
    return results, diag


def _diagnose(diag: dict, command: str) -> None:
    """Print a specific failure reason based on observed serial output."""
    if diag["brownout"]:
        print("[warn] Brownout detected — the board is restarting repeatedly.")
        print("       This usually means insufficient USB power. Try a different")
        print("       cable or port, or add a capacitor across the 3.3 V rail.")

    if diag["wifi_ssid"] and not diag["wifi_connected"]:
        ssid = diag["wifi_ssid"]
        if ssid in ("YOUR_SSID", "YOUR_WIFI_SSID"):
            print(f"[warn] WiFi credentials are still the placeholder values.")
            print(f"       Edit include/config.h and set WIFI_SSID / WIFI_PASSWORD,")
            print(f"       then re-flash with:  ./run.sh flash --port <port>")
        else:
            print(f"[warn] Board is trying to connect to '{ssid}' but failing.")
            print(f"       Check that the SSID and password in include/config.h are")
            print(f"       correct and that the board is within range.")
        print(f"       The serial command handler only starts after WiFi connects.")
        return

    if diag["wifi_timeout"]:
        print("[warn] WiFi connection timed out — board restarted before responding.")
        return

    if diag["saw_bootrom"] and not diag["wifi_ssid"]:
        print("[warn] Saw ESP32 ROM bootloader output but no firmware log.")
        print("       The board may be in flash mode or running different firmware.")
        print("       Re-flash with:  ./run.sh flash --port <port>")
        return

    if not diag["saw_bootrom"] and not diag["wifi_ssid"]:
        print("[warn] No output received at all.")
        print("       — Wrong baud rate? (firmware uses 115200)")
        print("       — Board not running this project's firmware?")
        print("       — Try pressing EN/RESET and re-running.")
        return

    # Catch-all if none of the above matched
    print(f"[warn] No [CMD] response to '{command}'.")
    print("       The board is running but did not answer — try again once")
    print("       you see '[boot] Type help for serial commands' in the output.")


def read_boot_info(port: str, timeout: int = 20) -> dict:
    """
    Listen passively for the boot log lines (useful if the board just reset).
    Prompts the user to press EN/RESET.
    Returns {"mac", "ip", "hostname"}.
    """
    info = {"mac": None, "ip": None, "hostname": None}
    print(f"[serial] Listening on {port} for boot output  (timeout {timeout} s)")
    print("         Press EN / RESET on the board if nothing appears.\n")
    try:
        with serial.Serial(port, BAUD_RATE, timeout=1) as ser:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    print(f"  {line}")
                if m := BOOT_MAC.search(line):
                    info["mac"] = m.group(1).upper()
                if m := BOOT_IP.search(line):
                    info["ip"] = m.group(1)
                if m := BOOT_HOST.search(line):
                    info["hostname"] = m.group(1)
                if all(info.values()):
                    break
    except serial.SerialException as exc:
        print(f"[error] {exc}")
    return info


# ═══════════════════════════════════════════════════════════════════════════
#  mDNS / network helpers
# ═══════════════════════════════════════════════════════════════════════════

def scan_mdns(pattern: str | None = None, timeout: float = 4.0) -> list[dict]:
    """
    Browse _arduino._tcp.local. (ArduinoOTA's mDNS service) and return
    a list of dicts: [{"hostname": …, "ip": …, "port": …}, …]

    Optionally filter by *pattern* using shell-style wildcards (fnmatch).
    Requires the `zeroconf` package.
    """
    if not HAS_ZEROCONF:
        print("[error] zeroconf not installed.  Run:  pip install zeroconf")
        return []

    found: list[dict] = []

    class Listener(ServiceListener):
        def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:  # type: ignore[override]
            info = zc.get_service_info(type_, name)
            if not info:
                return
            # name is like "esp32-blink-1._arduino._tcp.local."
            hostname = name.replace(f".{type_}", "").strip(".")
            addresses = info.addresses
            if not addresses:
                return
            ip = socket.inet_ntoa(addresses[0])
            found.append({"hostname": hostname, "ip": ip, "port": info.port})

        def remove_service(self, *_):
            pass

        def update_service(self, *_):
            pass

    zc = Zeroconf()
    browser = ServiceBrowser(zc, OTA_SERVICE, Listener())  # noqa: F841
    time.sleep(timeout)
    zc.close()

    if pattern:
        found = [b for b in found if fnmatch.fnmatch(b["hostname"], pattern)]

    return found


def resolve_hostname_mdns(hostname: str, timeout: float = 5.0) -> str | None:
    """
    Resolve *hostname* (without .local) to an IP via mDNS.
    Falls back to system resolver (requires Bonjour / avahi on the host).
    """
    # Try zeroconf scan first (platform-independent)
    if HAS_ZEROCONF:
        boards = scan_mdns(pattern=hostname, timeout=timeout)
        if boards:
            return boards[0]["ip"]

    # Fall back to system mDNS resolver
    try:
        result = socket.getaddrinfo(f"{hostname}.local", None)
        if result:
            return result[0][4][0]
    except socket.gaierror:
        pass

    return None


# ═══════════════════════════════════════════════════════════════════════════
#  Build / upload helpers
# ═══════════════════════════════════════════════════════════════════════════

def _hostname_build_flag(hostname: str) -> str:
    """Return the compiler flag that overrides OTA_HOSTNAME."""
    # Produces: -DOTA_HOSTNAME=\"esp32-blink-1\"
    return f'-DOTA_HOSTNAME=\\"{hostname}\\"'


def pio_run(env: str, project_dir: Path,
            upload_port: str | None = None,
            hostname: str | None = None,
            extra_flags: list[str] | None = None) -> int:
    """
    Run `pio run -e <env> [-t upload]` and return the exit code.
    """
    cmd = ["pio", "run", "--environment", env]

    if upload_port:
        cmd += ["--target", "upload", "--upload-port", upload_port]
    else:
        cmd += ["--target", "upload"]

    if hostname:
        cmd += ["--build-flag", _hostname_build_flag(hostname)]

    if extra_flags:
        for f in extra_flags:
            cmd += ["--build-flag", f]

    print(f"\n[pio]  {' '.join(cmd)}")
    print(f"[pio]  Project: {project_dir}\n")
    return subprocess.run(cmd, cwd=str(project_dir)).returncode


# ═══════════════════════════════════════════════════════════════════════════
#  Sub-commands
# ═══════════════════════════════════════════════════════════════════════════

def cmd_check(args) -> None:
    """Query the USB-connected board via the serial command protocol."""
    port = args.port or _pick_port()
    if not port:
        sys.exit(1)

    command = args.cmd  # e.g. get_info, get_ip, get_mac, get_hostname, help

    print(f"\n[serial] → {command}")
    results, diag = serial_command(port, command, timeout=args.timeout)

    if not results:
        print()
        _diagnose(diag, command)
        sys.exit(1)

    print()
    width = max(len(r["key"]) for r in results)
    for r in results:
        print(f"  {r['key'].ljust(width)} : {r['value']}")


def cmd_scan(args) -> None:
    """Scan the local network for ArduinoOTA boards."""
    if not HAS_ZEROCONF:
        print("[error] Install zeroconf first:  pip install zeroconf")
        sys.exit(1)

    pattern = args.pattern
    print(f"[scan] Browsing {OTA_SERVICE}  ({args.timeout} s)…")
    if pattern:
        print(f"[scan] Filter: {pattern}")

    boards = scan_mdns(pattern=pattern, timeout=args.timeout)

    print()
    if not boards:
        print("No boards found." + (" (no pattern match)" if pattern else ""))
        return

    col_h = max(len(b["hostname"]) for b in boards)
    print(f"  {'Hostname':<{col_h}}  {'IP':<16}  Port")
    print(f"  {'-'*col_h}  {'-'*16}  ----")
    for b in boards:
        print(f"  {b['hostname']:<{col_h}}  {b['ip']:<16}  {b['port']}")
    print(f"\n{len(boards)} board(s) found.")


def cmd_flash(args) -> None:
    """USB flash (initial or re-flash). Sets hostname at build time."""
    project_dir = Path(args.project_dir).resolve()
    if not (project_dir / "platformio.ini").exists():
        print(f"[error] No platformio.ini in {project_dir}")
        sys.exit(1)

    port = args.port or _pick_port()
    if not port:
        sys.exit(1)

    # Build and upload via USB
    rc = pio_run(
        env=args.env,
        project_dir=project_dir,
        upload_port=port,
        hostname=args.hostname,
    )

    if rc != 0:
        print(f"\n❌  USB flash failed (exit {rc}).")
        sys.exit(rc)

    print("\n✅  USB flash succeeded!")

    # Optionally verify by querying the board after reboot
    if args.verify:
        print("\n[verify] Waiting for board to reboot…")
        time.sleep(3)
        print("[verify] Querying board…")
        results, diag = serial_command(port, "get_info", timeout=10)
        if results:
            print()
            for r in results:
                print(f"  {r['key']}: {r['value']}")
        else:
            print()
            _diagnose(diag, "get_info")


def cmd_upload(args) -> None:
    """OTA wireless upload."""
    project_dir = Path(args.project_dir).resolve()
    if not (project_dir / "platformio.ini").exists():
        print(f"[error] No platformio.ini in {project_dir}")
        sys.exit(1)

    target_ip  = args.ip
    target_host = args.hostname

    # ── Resolve target IP ─────────────────────────────────────────────────
    if not target_ip and target_host:
        print(f"[mdns] Resolving {target_host}.local …")
        target_ip = resolve_hostname_mdns(target_host)
        if target_ip:
            print(f"[mdns] Resolved → {target_ip}")
        else:
            print(f"[error] Could not resolve '{target_host}' via mDNS.")
            sys.exit(1)

    if not target_ip and args.port:
        # Ask the board directly over USB serial
        port = args.port or _pick_port()
        if not port:
            sys.exit(1)
        print(f"\n[serial] Querying board on {port} for its IP…")
        results, diag = serial_command(port, "get_info", timeout=args.timeout)
        info = {r["key"]: r["value"] for r in results}

        if args.mac and "MAC" in info:
            if info["MAC"].upper() != args.mac.upper():
                print(f"[error] MAC mismatch: found {info['MAC']}, expected {args.mac}")
                sys.exit(1)

        target_ip   = info.get("IP")
        target_host = target_host or info.get("HOSTNAME")

        if not target_ip:
            # Fall back to boot-log listening
            print("[serial] No [CMD] response; listening for boot log…")
            boot = read_boot_info(port, timeout=args.timeout)
            target_ip   = boot.get("ip")
            target_host = target_host or boot.get("hostname")

        if not target_ip:
            print("[error] Could not determine target IP. Aborting.")
            sys.exit(1)

    if not target_ip:
        print("[error] Specify --ip, --hostname, or --port. See --help.")
        sys.exit(1)

    print(f"\n[info] Target hostname : {target_host or '(unknown)'}")
    print(f"[info] Target IP       : {target_ip}")

    rc = pio_run(
        env=args.env,
        project_dir=project_dir,
        upload_port=target_ip,
        hostname=target_host,   # keep the hostname consistent on re-flash
    )

    if rc == 0:
        print("\n✅  OTA upload succeeded!")
    else:
        print(f"\n❌  OTA upload failed (exit {rc}).")
        sys.exit(rc)


# ═══════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════

def _add_project_arg(p):
    p.add_argument("--project-dir", "-d", default=".",
                   help="PlatformIO project directory (default: cwd).")

def _add_timeout_arg(p, default=CMD_TIMEOUT):
    p.add_argument("--timeout", "-t", type=int, default=default,
                   help=f"Serial read timeout in seconds (default: {default}).")

def _add_port_arg(p):
    p.add_argument("--port", "-p",
                   help="Serial port (e.g. /dev/ttyUSB0, COM3). Auto-detected if omitted.")

def main():
    parser = argparse.ArgumentParser(
        prog="esp32_ota.py",
        description="ESP32 OTA helper: check, scan, flash, and upload wirelessly.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── check ─────────────────────────────────────────────────────────────
    p_check = sub.add_parser("check", help="Query a USB-connected board via serial commands")
    _add_port_arg(p_check)
    _add_timeout_arg(p_check)
    p_check.add_argument(
        "--cmd", default="get_info",
        choices=["get_info", "get_ip", "get_mac", "get_hostname", "help"],
        help="Command to send (default: get_info).",
    )

    # ── scan ──────────────────────────────────────────────────────────────
    p_scan = sub.add_parser("scan", help="Discover OTA boards on the network via mDNS")
    p_scan.add_argument(
        "--pattern", "-f",
        help="Wildcard filter, e.g. 'esp32-blink-*'. Shows all if omitted.",
    )
    p_scan.add_argument(
        "--timeout", type=float, default=4.0,
        help="mDNS browse duration in seconds (default: 4).",
    )

    # ── flash ─────────────────────────────────────────────────────────────
    p_flash = sub.add_parser("flash", help="USB flash (first upload or re-flash)")
    _add_port_arg(p_flash)
    _add_timeout_arg(p_flash)
    _add_project_arg(p_flash)
    p_flash.add_argument(
        "--hostname",
        help="OTA hostname to bake into this board (e.g. esp32-blink-1). "
             "Must be unique per board on the same network.",
    )
    p_flash.add_argument(
        "--env", default=USB_ENV,
        help=f"PlatformIO environment (default: {USB_ENV}).",
    )
    p_flash.add_argument(
        "--verify", action="store_true",
        help="After flashing, query the board over serial to confirm the hostname.",
    )

    # ── upload ────────────────────────────────────────────────────────────
    p_upload = sub.add_parser("upload", help="Wireless OTA upload")
    _add_port_arg(p_upload)
    _add_timeout_arg(p_upload, default=15)
    _add_project_arg(p_upload)
    p_upload.add_argument(
        "--ip",
        help="Target IP address (skip mDNS resolution).",
    )
    p_upload.add_argument(
        "--hostname",
        help="Board hostname (resolves via mDNS to get IP). "
             "Also re-bakes the hostname into the new firmware.",
    )
    p_upload.add_argument(
        "--mac",
        help="Expected MAC; used to verify the right board when reading from --port.",
    )
    p_upload.add_argument(
        "--env", default=OTA_ENV,
        help=f"PlatformIO environment (default: {OTA_ENV}).",
    )

    args = parser.parse_args()

    dispatch = {
        "check":  cmd_check,
        "scan":   cmd_scan,
        "flash":  cmd_flash,
        "upload": cmd_upload,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
