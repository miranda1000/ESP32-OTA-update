#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include "config.h"
#include "secrets.h"

// ═══════════════════════════════════════════════════════════════════════════
//  Serial command protocol
// ═══════════════════════════════════════════════════════════════════════════
//
//  Send a command (terminated with \n) and the board replies on the same
//  serial port.  All reply lines start with "[CMD] " for easy parsing.
//
//  Commands        Response
//  ────────────    ───────────────────────────────────────────────────────
//  get_ip          [CMD] IP: 192.168.1.42
//  get_mac         [CMD] MAC: AA:BB:CC:DD:EE:FF
//  get_hostname    [CMD] HOSTNAME: esp32-blink-1
//  get_info        [CMD] MAC: ...  + IP: ...  + HOSTNAME: ...  (3 lines)
//  help            [CMD] HELP: get_ip | get_mac | get_hostname | get_info
//
//  Unknown command → [CMD] ERROR: unknown command '<cmd>'
// ═══════════════════════════════════════════════════════════════════════════

static void handleSerialCommands() {
    if (!Serial.available()) return;

    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toLowerCase();

    if (cmd.length() == 0) return;

    if (cmd == "get_ip") {
        Serial.printf("[CMD] IP: %s\r\n", WiFi.localIP().toString().c_str());

    } else if (cmd == "get_mac") {
        Serial.printf("[CMD] MAC: %s\r\n", WiFi.macAddress().c_str());

    } else if (cmd == "get_hostname") {
        Serial.printf("[CMD] HOSTNAME: %s\r\n", OTA_HOSTNAME);

    } else if (cmd == "get_info") {
        Serial.printf("[CMD] MAC: %s\r\n",      WiFi.macAddress().c_str());
        Serial.printf("[CMD] IP: %s\r\n",       WiFi.localIP().toString().c_str());
        Serial.printf("[CMD] HOSTNAME: %s\r\n", OTA_HOSTNAME);

    } else if (cmd == "help") {
        Serial.println(F("[CMD] HELP: get_ip | get_mac | get_hostname | get_info"));

    } else {
        Serial.printf("[CMD] ERROR: unknown command '%s'\r\n", cmd.c_str());
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  WiFi
// ═══════════════════════════════════════════════════════════════════════════

static void connectWiFi() {
    Serial.printf("\n[WiFi] Connecting to %s", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    uint8_t attempts = 0;
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print('.');
        if (++attempts > 40) {
            Serial.println(F("\n[WiFi] Timeout — restarting"));
            ESP.restart();
        }
    }
    Serial.println(F("\n[WiFi] Connected"));
    // Boot info printed once — also available on demand via get_info
    Serial.printf("[boot] MAC      : %s\r\n", WiFi.macAddress().c_str());
    Serial.printf("[boot] IP       : %s\r\n", WiFi.localIP().toString().c_str());
    Serial.printf("[boot] Hostname : %s\r\n", OTA_HOSTNAME);
    Serial.println(F("[boot] Type 'help' for serial commands"));
}

// ═══════════════════════════════════════════════════════════════════════════
//  OTA
// ═══════════════════════════════════════════════════════════════════════════

static void setupOTA() {
    ArduinoOTA.setHostname(OTA_HOSTNAME);
    if (strlen(OTA_PASSWORD) > 0) ArduinoOTA.setPassword(OTA_PASSWORD);

    ArduinoOTA.onStart([]() {
        String t = (ArduinoOTA.getCommand() == U_FLASH) ? "sketch" : "filesystem";
        Serial.printf("[OTA] Start: %s\r\n", t.c_str());
        digitalWrite(LED_PIN, LOW);
    });
    ArduinoOTA.onEnd([]()  { Serial.println(F("[OTA] Done — rebooting")); });
    ArduinoOTA.onProgress([](unsigned int p, unsigned int t) {
        Serial.printf("[OTA] %u%%\r", p * 100 / t);
    });
    ArduinoOTA.onError([](ota_error_t e) {
        const char* msg = "unknown";
        switch (e) {
            case OTA_AUTH_ERROR:    msg = "auth failed";    break;
            case OTA_BEGIN_ERROR:   msg = "begin failed";   break;
            case OTA_CONNECT_ERROR: msg = "connect failed"; break;
            case OTA_RECEIVE_ERROR: msg = "receive failed"; break;
            case OTA_END_ERROR:     msg = "end failed";     break;
        }
        Serial.printf("[OTA] Error: %s\r\n", msg);
    });

    ArduinoOTA.begin();
    Serial.printf("[OTA] Listening as \"%s\" (port 3232)\r\n", OTA_HOSTNAME);
}

// ═══════════════════════════════════════════════════════════════════════════
//  Blink state machine  (non-blocking — keeps OTA.handle() running)
// ═══════════════════════════════════════════════════════════════════════════

static void runBlinkPattern() {
    enum Phase : uint8_t { LED_ON, LED_OFF, DARK };
    static Phase    phase    = LED_ON;
    static uint8_t  count    = 0;
    static uint32_t lastTick = 0;

    uint32_t now = millis();
    switch (phase) {
        case LED_ON:
            if (count == 0 || now - lastTick >= (uint32_t)BLINK_OFF_MS) {
                digitalWrite(LED_PIN, HIGH);
                lastTick = now;
                phase = LED_OFF;
            }
            break;
        case LED_OFF:
            if (now - lastTick >= (uint32_t)BLINK_ON_MS) {
                digitalWrite(LED_PIN, LOW);
                lastTick = now;
                if (++count >= BLINK_COUNT) { count = 0; phase = DARK; }
                else phase = LED_ON;
            }
            break;
        case DARK:
            if (now - lastTick >= (uint32_t)DARK_MS) {
                lastTick = now;
                phase = LED_ON;
            }
            break;
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  Entry points
// ═══════════════════════════════════════════════════════════════════════════

void setup() {
    Serial.begin(115200);
    delay(300);
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);
    connectWiFi();
    setupOTA();
}

void loop() {
    ArduinoOTA.handle();      // must run every iteration
    handleSerialCommands();   // non-blocking: only acts if bytes are waiting
    runBlinkPattern();        // non-blocking state machine
}
