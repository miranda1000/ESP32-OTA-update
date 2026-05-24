#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  run.sh — build (if needed) and run the ESP32 OTA helper inside Docker
#
#  Usage:
#    ./run.sh [--build] <esp32_ota sub-command and args>
#
#  Examples:
#    ./run.sh check --port /dev/ttyUSB0
#    ./run.sh scan --pattern "esp32-blink-*"
#    ./run.sh flash --port /dev/ttyUSB0 --hostname esp32-blink-1
#    ./run.sh upload --hostname esp32-blink-1
#    ./run.sh --build scan          # force image rebuild, then scan
#
#  The Docker image is built automatically on first run, and only when you
#  pass --build explicitly after that.
#
#  Source files (src/, include/, platformio.ini, esp32_ota.py) are mounted
#  directly from this directory — edit them freely without rebuilding.
#
#  Compiled objects are kept in a named Docker volume so unchanged code is
#  never recompiled.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
IMAGE_NAME="esp32-ota-blink"
BUILD_VOLUME="esp32-ota-build"   # named volume → /project/.pio  (build cache)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Parse --build flag ────────────────────────────────────────────────────────
FORCE_BUILD=false
PASS_ARGS=()
for arg in "$@"; do
    if [[ "$arg" == "--build" ]]; then
        FORCE_BUILD=true
    else
        PASS_ARGS+=("$arg")
    fi
done

# ── Build image if needed ─────────────────────────────────────────────────────
image_exists() {
    docker image inspect "$IMAGE_NAME" &>/dev/null
}

if [[ "$FORCE_BUILD" == true ]]; then
    echo "[run.sh] --build requested — building Docker image..."
    docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"
elif ! image_exists; then
    echo "[run.sh] Image '$IMAGE_NAME' not found — building for the first time..."
    echo "[run.sh] (This takes ~10 min on first run; subsequent runs are instant)"
    docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"
else
    echo "[run.sh] Using existing image '$IMAGE_NAME'  (pass --build to rebuild)"
fi

# ── Detect serial ports ───────────────────────────────────────────────────────
DEVICE_FLAGS=()

detect_ports_linux() {
    local port
    shopt -s nullglob
    for port in /dev/ttyUSB* /dev/ttyACM*; do
        DEVICE_FLAGS+=("--device=$port:$port")
    done
    shopt -u nullglob
}

detect_ports_linux

if [[ ${#DEVICE_FLAGS[@]} -eq 0 ]]; then
    echo "[run.sh] No serial devices found (OK if not using serial features)"
else
    echo "[run.sh] Passing serial device(s): ${DEVICE_FLAGS[*]}"
fi

# ── Network mode ──────────────────────────────────────────────────────────────
# --network host is required on Linux for mDNS multicast (scan, --hostname).
NETWORK_FLAG="--network=host"

# ── TTY flag ──────────────────────────────────────────────────────────────────
# Use -it when running interactively (terminal attached), -i only in pipes/CI.
TTY_FLAG="-i"
[[ -t 0 && -t 1 ]] && TTY_FLAG="-it"

# ── Run ───────────────────────────────────────────────────────────────────────
echo "[run.sh] Running: esp32_ota.py ${PASS_ARGS[*]+"${PASS_ARGS[*]}"}"
echo ""

docker run --rm $TTY_FLAG \
    $NETWORK_FLAG \
    \
    `# ── Source mounts (live-updated, no rebuild needed) ──────────────────` \
    -v "$SCRIPT_DIR/src:/project/src:ro" \
    -v "$SCRIPT_DIR/include:/project/include:ro" \
    -v "$SCRIPT_DIR/platformio.ini:/project/platformio.ini:ro" \
    -v "$SCRIPT_DIR/esp32_ota.py:/project/esp32_ota.py:ro" \
    \
    `# ── Build cache (named volume, persists between runs) ─────────────────` \
    -v "$BUILD_VOLUME:/project/.pio" \
    \
    `# ── Serial devices ────────────────────────────────────────────────────` \
    "${DEVICE_FLAGS[@]+"${DEVICE_FLAGS[@]}"}" \
    \
    "$IMAGE_NAME" \
    "${PASS_ARGS[@]+"${PASS_ARGS[@]}"}"
