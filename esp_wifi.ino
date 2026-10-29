/*
  ESP32 - 63-Channel Ejector & Indicator Tester (WiFi + WebSocket)
  ================================================================
  Same 74HC595 shift register control as esp.ino, but adds WiFi
  connectivity and a WebSocket server so the web UI can control
  channels wirelessly — no USB cable needed during operation.

  How it works:
    1. ESP32 connects to your WiFi network
    2. Starts a WebSocket server on port 81
    3. The web UI (hosted on Render) connects to ws://<ESP32_IP>:81
    4. Same binary protocol over WebSocket as serial

  Hardware Wiring (unchanged from esp.ino):
    - 74HC595 Pin 14 (Data / SER)    -> ESP32 GPIO 13
    - 74HC595 Pin 12 (Latch / RCLK)   -> ESP32 GPIO 12
    - 74HC595 Pin 11 (Clock / SRCLK)  -> ESP32 GPIO 14
    - 74HC595 Pin 16 (VCC)           -> ESP32 5V (or VIN)
    - 74HC595 Pin 10 (/MR / SRCLR)   -> ESP32 5V (Crucial!)
    - 74HC595 Pin 8  (GND)           -> ESP32 GND
    - 74HC595 Pin 13 (/OE)           -> ESP32 GND (Crucial!)

  Protocol (same byte commands via WebSocket or Serial):
    'P'        -> Status Ping
    'A'        -> ALL 63 Channels ON (Continuous)
    0 / 'R'/'S'-> ALL OFF
    'W'        -> Enable Watchdog (250ms auto-off)
    'X'        -> Disable Watchdog
    'T'        -> Diagnostic test IC1 (CH 01-08 ON)
    1..63      -> Channel ON
    101..163   -> Channel OFF

  Libraries Required (install via Arduino Library Manager):
    - WebSocketsServer by Markus Sattler
      (Search "WebSockets" by Links2004)
*/

#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsServer.h>
#include "driver/gpio.h"

// ============================================================
// >>>  CHANGE THESE TO YOUR WiFi CREDENTIALS  <<<
// ============================================================
const char* WIFI_SSID     = "YOUR_WIFI_NAME";      // <-- Your WiFi name
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";   // <-- Your WiFi password
// ============================================================

// Pin Configuration (unchanged)
constexpr uint8_t DATA_PIN   = 13;
constexpr uint8_t LATCH_PIN  = 12;
constexpr uint8_t CLOCK_PIN  = 14;
constexpr uint8_t STATUS_LED = 2;

constexpr uint8_t NUM_ICS      = 8;
constexpr uint8_t NUM_CHANNELS = 63;

// State
uint8_t  outputBytes[NUM_ICS]       = {0};
bool     active[NUM_CHANNELS + 1]   = {false};
uint32_t onSince[NUM_CHANNELS + 1]  = {0};
bool     watchdogEnabled            = false;
constexpr uint16_t WATCHDOG_MS      = 250;

// WebSocket server on port 81
WebSocketsServer webSocket(81);

// Track connected WebSocket clients for broadcasting responses
void broadcastMessage(const String& msg) {
  webSocket.broadcastTXT(msg);
  Serial.println(msg);  // Also echo to serial for debugging
}

// ========== SHIFT REGISTER FUNCTIONS (identical to esp.ino) ==========

void customShiftOut(uint8_t dataPin, uint8_t clockPin, uint8_t bitOrder, uint8_t val) {
  for (uint8_t i = 0; i < 8; ++i) {
    bool bitVal = (bitOrder == LSBFIRST) ? (val & (1 << i)) : (val & (1 << (7 - i)));
    digitalWrite(dataPin, bitVal ? HIGH : LOW);
    delayMicroseconds(10);
    digitalWrite(clockPin, HIGH);
    delayMicroseconds(12);
    digitalWrite(dataPin, LOW);
    delayMicroseconds(5);
    digitalWrite(clockPin, LOW);
    delayMicroseconds(12);
  }
}

void writeRegisters() {
  digitalWrite(LATCH_PIN, LOW);
  digitalWrite(CLOCK_PIN, LOW);
  delayMicroseconds(5);
  for (int8_t i = NUM_ICS - 1; i >= 0; --i) {
    customShiftOut(DATA_PIN, CLOCK_PIN, MSBFIRST, outputBytes[i]);
  }
  digitalWrite(DATA_PIN, LOW);
  digitalWrite(CLOCK_PIN, LOW);
  delayMicroseconds(10);
  digitalWrite(LATCH_PIN, HIGH);
  delayMicroseconds(20);
  digitalWrite(LATCH_PIN, LOW);
  delayMicroseconds(10);
}

void allOff() {
  for (uint8_t i = 0; i < NUM_ICS; ++i) outputBytes[i] = 0;
  for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
    active[ch] = false;
    onSince[ch] = 0;
  }
  writeRegisters();
  digitalWrite(STATUS_LED, LOW);
}

void allOn() {
  for (uint8_t i = 0; i < NUM_ICS - 1; ++i) outputBytes[i] = 0xFF;
  outputBytes[7] = 0x7F;  // CH 57-63 ON, CH 64 reserved
  for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
    active[ch] = true;
    onSince[ch] = millis();
  }
  writeRegisters();
  digitalWrite(STATUS_LED, HIGH);
}

void setChannel(uint8_t ch, bool on) {
  if (ch < 1 || ch > NUM_CHANNELS) return;
  const uint8_t idx = ch - 1;
  const uint8_t ic  = idx / 8;
  const uint8_t bit = idx % 8;
  if (on) {
    outputBytes[ic] |= uint8_t(1U << bit);
    active[ch]  = true;
    onSince[ch] = millis();
  } else {
    outputBytes[ic] &= uint8_t(~(1U << bit));
    active[ch]  = false;
    onSince[ch] = 0;
  }
}

// ========== COMMAND PROCESSOR (shared by Serial & WebSocket) ==========

void processCommand(uint8_t b) {
  bool changed = false;

  if (b == 'P') {
    broadcastMessage("ACK: ESP32_ALIVE");
    digitalWrite(STATUS_LED, HIGH);
    delay(30);
    digitalWrite(STATUS_LED, LOW);
  }
  else if (b == 'A') {
    watchdogEnabled = false;
    allOn();
    broadcastMessage("ACK: ALL 63 ON (CONTINUOUS)");
  }
  else if (b == 0 || b == 'R' || b == 'S') {
    allOff();
    broadcastMessage("ACK: ALL OFF");
  }
  else if (b == 'W') {
    watchdogEnabled = true;
    broadcastMessage("ACK: WATCHDOG ENABLED (250MS AUTO-OFF)");
  }
  else if (b == 'X') {
    watchdogEnabled = false;
    broadcastMessage("ACK: WATCHDOG DISABLED (CONTINUOUS HOLD)");
  }
  else if (b == 'T') {
    for (uint8_t ch = 1; ch <= 8; ++ch) setChannel(ch, true);
    changed = true;
    broadcastMessage("ACK: DIAGNOSTIC TEST - IC1 (CH 01-08) ON");
  }
  else if (b >= 1 && b <= NUM_CHANNELS) {
    setChannel(b, true);
    changed = true;
    broadcastMessage("ACK: CH " + String(b) + " ON");
  }
  else if (b >= 101 && b <= 100 + NUM_CHANNELS) {
    uint8_t ch = b - 100;
    setChannel(ch, false);
    changed = true;
    broadcastMessage("ACK: CH " + String(ch) + " OFF");
  }
  else if (b != '\r' && b != '\n' && b != ' ') {
    broadcastMessage("WARN: UNKNOWN CMD " + String(b));
  }

  if (changed) {
    writeRegisters();
    bool anyActive = false;
    for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
      if (active[ch]) { anyActive = true; break; }
    }
    digitalWrite(STATUS_LED, anyActive ? HIGH : LOW);
  }
}

// ========== WEBSOCKET EVENT HANDLER ==========

void webSocketEvent(uint8_t clientNum, WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      Serial.printf("[WS] Client #%u disconnected\n", clientNum);
      break;

    case WStype_CONNECTED:
      {
        IPAddress ip = webSocket.remoteIP(clientNum);
        Serial.printf("[WS] Client #%u connected from %s\n", clientNum, ip.toString().c_str());
        webSocket.sendTXT(clientNum, "ACK: ESP32_WIFI_CONNECTED");
      }
      break;

    case WStype_TEXT:
      // Text commands: process first byte
      if (length > 0) {
        processCommand(payload[0]);
      }
      break;

    case WStype_BIN:
      // Binary commands: process each byte
      for (size_t i = 0; i < length; i++) {
        processCommand(payload[i]);
      }
      break;

    default:
      break;
  }
}

// ========== SETUP ==========

void setup() {
  // GPIO setup (same as original)
  digitalWrite(DATA_PIN, LOW);
  digitalWrite(CLOCK_PIN, LOW);
  digitalWrite(LATCH_PIN, LOW);
  digitalWrite(STATUS_LED, LOW);

  pinMode(DATA_PIN, OUTPUT);
  pinMode(CLOCK_PIN, OUTPUT);
  pinMode(LATCH_PIN, OUTPUT);
  pinMode(STATUS_LED, OUTPUT);

  gpio_set_drive_capability((gpio_num_t)DATA_PIN,  GPIO_DRIVE_CAP_0);
  gpio_set_drive_capability((gpio_num_t)CLOCK_PIN, GPIO_DRIVE_CAP_0);
  gpio_set_drive_capability((gpio_num_t)LATCH_PIN, GPIO_DRIVE_CAP_0);

  Serial.begin(115200);
  allOff();

  // ---- WiFi Connection ----
  Serial.println();
  Serial.println("================================");
  Serial.println("ESP32 63-CH Ejector Tester WiFi");
  Serial.println("================================");
  Serial.printf("Connecting to WiFi: %s", WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  // Blink LED while connecting
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    digitalWrite(STATUS_LED, !digitalRead(STATUS_LED));
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✓ WiFi Connected!");
    Serial.print("  IP Address: ");
    Serial.println(WiFi.localIP());
    Serial.println("  WebSocket:  ws://" + WiFi.localIP().toString() + ":81");
    Serial.println("================================");

    // Blink rapidly 3 times to signal success
    for (int i = 0; i < 6; i++) {
      digitalWrite(STATUS_LED, !digitalRead(STATUS_LED));
      delay(150);
    }
    digitalWrite(STATUS_LED, LOW);
  } else {
    Serial.println("\n✗ WiFi connection FAILED!");
    Serial.println("  Check SSID and password in the code.");
    Serial.println("  Serial control still works via USB.");
    Serial.println("================================");
  }

  // ---- Start WebSocket Server ----
  webSocket.begin();
  webSocket.onEvent(webSocketEvent);

  Serial.println("ESP32_63CH_EJECTOR_TESTER_READY");
  Serial.println("Pins: Data=GPIO13, Latch=GPIO12, Clock=GPIO14 | 8x 74HC595");
}

// ========== LOOP ==========

void loop() {
  // Handle WebSocket connections
  webSocket.loop();

  // Handle Serial commands (USB still works for debugging)
  while (Serial.available() > 0) {
    uint8_t b = uint8_t(Serial.read());
    processCommand(b);
  }

  // Safety watchdog
  if (watchdogEnabled) {
    const uint32_t now = millis();
    bool watchdogChanged = false;
    for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
      if (active[ch] && uint32_t(now - onSince[ch]) >= WATCHDOG_MS) {
        setChannel(ch, false);
        watchdogChanged = true;
        broadcastMessage("WARN: CH " + String(ch) + " watchdog OFF");
      }
    }
    if (watchdogChanged) {
      writeRegisters();
      bool anyActive = false;
      for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
        if (active[ch]) { anyActive = true; break; }
      }
      digitalWrite(STATUS_LED, anyActive ? HIGH : LOW);
    }
  }
}
