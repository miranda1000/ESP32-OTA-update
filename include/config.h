#pragma once

// ── OTA hostname ─────────────────────────────────────────────────────────────
// This can be overridden by a compiler -D flag without touching this file:
//   pio run --build-flag='-DOTA_HOSTNAME=\"esp32-blink-2\"'
// The Python script does this automatically via --hostname.
//
// ⚠ Every board on the same network MUST have a unique hostname —
//   duplicate mDNS names cause OTA discovery and upload to fail.
#ifndef OTA_HOSTNAME
#define OTA_HOSTNAME "esp32-blink"
#endif

// OTA password — leave "" to disable.
// If set, also uncomment upload_flags in platformio.ini.
#define OTA_PASSWORD  ""

// ── Hardware ─────────────────────────────────────────────────────────────────
// Built-in LED: most ESP32 DevKit = GPIO 2, LOLIN D32 = GPIO 5
#define LED_PIN 2

// ── Blink pattern ────────────────────────────────────────────────────────────
#define BLINK_COUNT  2     // ← change to 3 for the second OTA upload
#define BLINK_ON_MS  200
#define BLINK_OFF_MS 200
#define DARK_MS      4000
