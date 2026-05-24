# ESP32 OTA Blink

Blinks the built-in LED **N times**, then goes dark for **4 s**, forever.  
After the first USB flash, every subsequent upload is wireless over Wi-Fi.

---

## Project layout

```
esp32-ota-blink/
├── platformio.ini
├── include/
│   ├── secrets.h          ← WiFi credentials (git-ignored, you create this)
│   ├── secrets.h.example  ← template to copy from
│   └── config.h           ← everything else (blink count, LED pin, hostname)
├── src/main.cpp
└── esp32_ota.py           ← Python helper (check / scan / flash / upload)
```

---

## Quick start

### 1 — Add your WiFi credentials

Copy the example file and fill it in:

```bash
cp include/secrets.h.example include/secrets.h
```

Then edit `include/secrets.h`:

```cpp
#define WIFI_SSID     "your-network-name"
#define WIFI_PASSWORD "your-password"
```

`secrets.h` is listed in `.gitignore` and will never be committed.  
`secrets.h.example` (with placeholder values) is safe to commit.

### 2 — Tweak settings (optional)

Edit `include/config.h` for anything else:

```cpp
#define BLINK_COUNT  2    // ← number of blinks per cycle
#define LED_PIN      2    // ← GPIO for built-in LED (DevKit=2, LOLIN D32=5)
```

### 3 — Install dependencies

#### [Recommended] Using Docker

Install Docker on Linux.

#### Without using the `run.sh` script

```bash
pip install pyserial zeroconf
```

### 4 — First USB flash (assigns a unique hostname)

```bash
./run.sh flash --port /dev/ttyUSB0 --hostname esp32-blink-1
```

The `--hostname` flag bakes the name into the firmware as a compiler define,
overriding the default in `config.h`. **Every board on the same network must
have a different hostname** — duplicate mDNS names break OTA discovery.

Add `--verify` to query the board over serial right after flashing:

```bash
./run.sh flash --port /dev/ttyUSB0 --hostname esp32-blink-1 --verify
```

---

## Serial command protocol

Once the firmware is running you can query the board interactively from any
serial terminal at **115200 baud**, or via the `check` sub-command:

| Send           | Response                        |
|----------------|---------------------------------|
| `get_ip`       | `[CMD] IP: 192.168.1.42`        |
| `get_mac`      | `[CMD] MAC: AA:BB:CC:DD:EE:FF`  |
| `get_hostname` | `[CMD] HOSTNAME: esp32-blink-1` |
| `get_info`     | all three lines above           |
| `help`         | command list                    |

```bash
./run.sh check --port /dev/ttyUSB0           # sends get_info by default
./run.sh check --port /dev/ttyUSB0 --cmd get_ip
```

---

## Scan the network

```bash
./run.sh scan                              # all ArduinoOTA boards on the LAN
./run.sh scan --pattern "esp32-blink-*"   # wildcard filter
./run.sh scan --timeout 8                 # extend browse window
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

Change `BLINK_COUNT` to 3 in `config.h`, then pick whichever targeting method
is most convenient:

```bash
# By MAC address — resolved via local ARP cache (no mDNS, no USB)
./run.sh upload --mac 80:F3:DA:54:DB:E0

# By hostname — resolved via mDNS
./run.sh upload --hostname esp32-blink-1

# By direct IP
./run.sh upload --ip 192.168.1.42

# Ask the board over USB serial, then upload wirelessly
./run.sh upload --port /dev/ttyUSB0

# Plain PlatformIO CLI (no script needed)
pio run -e esp32_ota -t upload --upload-port 192.168.1.42
```

Target resolution priority (first match wins):

| Method | How | Requirement |
|---|---|---|
| `--mac` | ARP cache lookup | Board must have sent traffic recently |
| `--hostname` | mDNS browse | zeroconf on host |
| `--ip` | Direct | Know the IP |
| `--port` | Ask board over serial | USB cable |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `fatal error: secrets.h: No such file` | Copy `secrets.h.example` → `secrets.h` |
| WiFi connecting to `YOUR_SSID` | You forgot to edit `secrets.h` |
| `Connection refused` on OTA | Board not on Wi-Fi; check `secrets.h` credentials |
| MAC not found in ARP cache | Ping the board first: `ping 192.168.1.x` or use `--hostname` |
| mDNS won't resolve | Install avahi-daemon (Linux) or enable Bonjour (Windows) |
| Two boards, same hostname | Re-flash each with a unique `--hostname` |
| `Auth Failed` on OTA | `OTA_PASSWORD` mismatch; leave `""` to disable |
| LED on wrong pin | Change `LED_PIN` in `config.h` |
| `pio` not found | Add PlatformIO to PATH (`~/.platformio/penv/bin/` on Unix) |
