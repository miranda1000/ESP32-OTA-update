# ESP32 OTA Blink

Blinks the built-in LED **N times**, then goes dark for **4 s**, forever.  
After the first USB flash, every subsequent upload is wireless over Wi-Fi.

---

## Project layout

```
esp32-ota-blink/
├── platformio.ini
├── include/secrets.h
├── include/config.h      ← only file you normally need to edit
├── src/main.cpp
└── esp32_ota.py          ← Python helper (check / scan / flash / upload)
```

---

## Quick start

### 1 — Configure

Edit **`include/secrets.h`**:

```cpp
#define WIFI_SSID     "YOUR_SSID"
#define WIFI_PASSWORD "YOUR_PASSWORD"
```

Set `LED_PIN` in `include/config.h` if your board's built-in LED isn't on GPIO 2.

### 2 — Install Python dependencies (once)

```bash
pip install pyserial zeroconf
```

### 3 — First USB flash (assigns a unique hostname)

```bash
python esp32_ota.py flash --port /dev/ttyUSB0 --hostname esp32-blink-1
```

The `--hostname` flag bakes the name into the firmware as a compiler define
(`-DOTA_HOSTNAME="esp32-blink-1"`), overriding the default in `config.h`.
**Every board on the same network must have a different hostname** —
duplicate mDNS names break OTA discovery.

Add `--verify` to query the board over serial right after flashing:

```bash
python esp32_ota.py flash --port /dev/ttyUSB0 --hostname esp32-blink-1 --verify
```

---

## Serial command protocol

Once the firmware is running you can query the board interactively from any
serial terminal at **115200 baud**, or via the Python `check` sub-command:

| Send      | Response                          |
|-----------|-----------------------------------|
| `get_ip`       | `[CMD] IP: 192.168.1.42`     |
| `get_mac`      | `[CMD] MAC: AA:BB:CC:DD:EE:FF` |
| `get_hostname` | `[CMD] HOSTNAME: esp32-blink-1` |
| `get_info`     | all three lines above          |
| `help`         | command list                   |

```bash
# Default: sends get_info
python esp32_ota.py check --port /dev/ttyUSB0

# Ask only for the IP
python esp32_ota.py check --port /dev/ttyUSB0 --cmd get_ip
```

---

## Scan the network

```bash
# Show all ArduinoOTA boards visible on the LAN
python esp32_ota.py scan

# Filter with a wildcard (fnmatch-style)
python esp32_ota.py scan --pattern "esp32-blink-*"

# Extend browse window if boards are slow to appear
python esp32_ota.py scan --timeout 8
```

Output:

```
[scan] Browsing _arduino._tcp.local.  (4 s)...
[scan] Filter: esp32-blink-*

  Hostname       IP               Port
  -------------  ---------------  ----
  esp32-blink-1  192.168.1.42     3232
  esp32-blink-2  192.168.1.87     3232

2 board(s) found.
```

---

## OTA upload (wireless, no USB needed)

Change `BLINK_COUNT` to 3 in `config.h`, then:

```bash
# By hostname — resolves via mDNS (most convenient)
python esp32_ota.py upload --hostname esp32-blink-1

# By direct IP
python esp32_ota.py upload --ip 192.168.1.42

# Ask the board over USB serial, then upload wirelessly
python esp32_ota.py upload --port /dev/ttyUSB0

# Verify MAC matches before uploading (safe with multiple boards)
python esp32_ota.py upload --port /dev/ttyUSB0 --mac AA:BB:CC:DD:EE:FF

# Plain PlatformIO CLI (no script needed)
pio run -e esp32_ota -t upload --upload-port 192.168.1.42
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Connection refused` | Board not on Wi-Fi; check SSID/password in `config.h` |
| mDNS won't resolve | Install avahi-daemon (Linux) or enable Bonjour (Windows) |
| Two boards, same hostname | Re-flash each with a unique `--hostname` |
| `Auth Failed` on OTA | `OTA_PASSWORD` mismatch; leave `""` to disable |
| LED on wrong pin | Change `LED_PIN` in `config.h` |
| `pio` not found | Add PlatformIO to PATH (`~/.platformio/penv/bin/` on Unix) |
