# ─────────────────────────────────────────────────────────────────────────────
#  ESP32 OTA build environment
#
#  What lives in the image (never needs re-download):
#    • Python 3.11 + pyserial + zeroconf
#    • PlatformIO CLI
#    • espressif32 platform + xtensa toolchain + Arduino framework
#
#  What is mounted at runtime by run.sh (edit freely, no rebuild needed):
#    • src/            C++ source files
#    • include/        Headers (config.h)
#    • platformio.ini  Build config
#    • esp32_ota.py    Python helper script
#
#  What lives in a named Docker volume (persists between runs):
#    • /project/.pio   Compiled object cache — unchanged files are NOT recompiled
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# ── System packages ───────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
        udev \
        # needed by some esp-idf / xtensa tools
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Python packages ───────────────────────────────────────────────────────────
RUN pip install --no-cache-dir \
        platformio \
        pyserial \
        zeroconf

# ── Pre-install ESP32 platform, toolchain, and Arduino framework ──────────────
#  This is the slow step (~10 min, ~1.5 GB download) but it only runs once
#  when building the image. Everything lands in /root/.platformio.
#
#  We run a dummy build against a minimal project so PlatformIO resolves and
#  caches all transitive package dependencies (framework, toolchain, libs).
RUN mkdir -p /tmp/pio-bootstrap/src && \
    echo '[env:esp32dev]\nplatform=espressif32\nboard=esp32dev\nframework=arduino' \
        > /tmp/pio-bootstrap/platformio.ini && \
    echo 'void setup(){} void loop(){}' \
        > /tmp/pio-bootstrap/src/main.cpp && \
    cd /tmp/pio-bootstrap && \
    pio run && \
    rm -rf /tmp/pio-bootstrap

# ── Working directory (source files are mounted here at runtime) ──────────────
WORKDIR /project

# ── Entry point ───────────────────────────────────────────────────────────────
#  run.sh appends the sub-command and its arguments, e.g.:
#    python /project/esp32_ota.py scan --pattern "esp32-blink-*"
ENTRYPOINT ["python3", "-u", "/project/esp32_ota.py"]
