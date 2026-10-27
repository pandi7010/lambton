/*
  Arduino Mega 2560 - 63-Channel Ejector & Indicator Tester
  ========================================================
  Controls 63 physical ejector indicator lights through 8 cascaded
  74HC595 shift registers using 5V logic.

  Hardware Wiring (Arduino Mega 2560 -> 74HC595):
    - Arduino Pin 9   -> IC Pin 12 (RCLK / ST_CP - Storage Latch Clock)
    - Arduino Pin 8   -> IC Pin 14 (SER / DS - Serial Data In)
    - Arduino Pin 6   -> IC Pin 11 (SRCLK / SH_CP - Shift Register Clock)
    - Arduino GND     -> IC Pin 8 (GND - Logic Ground)
    - Arduino 5V      -> IC Pin 16 (VCC - 5V Logic Supply)

  CRITICAL 74HC595 Hardware Requirements:
    - IC Pin 10 (SRCLR / MR) -> Connect to 5V (HIGH = not reset)
    - IC Pin 13 (OE)         -> Connect to GND (LOW = outputs enabled)
    - Daisy-chaining         -> IC1 Pin 9 (Q7') -> IC2 Pin 14 (SER), etc.
    - Decoupling             -> 100 nF capacitor between Pin 16 and Pin 8 at each IC

  Serial Protocol (115200 baud, 8N1):
    'A' / 'a'        -> ALL 63 Channels ON (Continuous)
    0 / 'R' / 'S'    -> ALL OFF
    1..63 (raw byte) -> Turn Channel n ON
    101..163         -> Turn Channel n OFF (channel + 100)
    'T' / 't'        -> Diagnostic test: Turn ON IC1 (CH 1..8)
    '?' / 'P'        -> Status Ping
*/

#include <Arduino.h>

// User Specified Mega 2560 Pin Configuration
constexpr uint8_t LATCH_PIN = 9;   // Arduino Pin 9 -> 74HC595 Pin 12 (RCLK)
constexpr uint8_t DATA_PIN = 8;    // Arduino Pin 8 -> 74HC595 Pin 14 (SER)
constexpr uint8_t CLOCK_PIN = 6;   // Arduino Pin 6 -> 74HC595 Pin 11 (SRCLK)
constexpr uint8_t STATUS_LED = 13; // Mega 2560 onboard LED

constexpr uint8_t NUM_ICS = 8;
constexpr uint8_t NUM_CHANNELS = 63; // Channels 1..63 used; channel 64 reserved

uint8_t outputBytes[NUM_ICS] = {0};
bool active[NUM_CHANNELS + 1] = {false};
uint32_t onSince[NUM_CHANNELS + 1] = {0};
bool watchdogEnabled = false;        // Default to continuous hold for testing
constexpr uint16_t WATCHDOG_MS = 250;

// Shift out bits with microsecond setup and pulse times for reliable transmission
void customShiftOut(uint8_t dataPin, uint8_t clockPin, uint8_t bitOrder, uint8_t val) {
  for (uint8_t i = 0; i < 8; ++i) {
    bool bitVal = (bitOrder == LSBFIRST) ? (val & (1 << i)) : (val & (1 << (7 - i)));
    digitalWrite(dataPin, bitVal ? HIGH : LOW);
    delayMicroseconds(2);
    digitalWrite(clockPin, HIGH);
    delayMicroseconds(4);
    digitalWrite(clockPin, LOW);
    delayMicroseconds(2);
  }
}

void writeRegisters() {
  digitalWrite(LATCH_PIN, LOW);
  delayMicroseconds(2);
  // Shift from IC8 down to IC1 so the first byte shifted ends up in IC8
  for (int8_t i = NUM_ICS - 1; i >= 0; --i) {
    customShiftOut(DATA_PIN, CLOCK_PIN, MSBFIRST, outputBytes[i]);
  }
  delayMicroseconds(2);
  digitalWrite(LATCH_PIN, HIGH);
  delayMicroseconds(10); // Generous latch pulse for 8 ICs
  digitalWrite(LATCH_PIN, LOW);
  delayMicroseconds(2);
}

void allOff() {
  for (uint8_t i = 0; i < NUM_ICS; ++i) {
    outputBytes[i] = 0;
  }
  for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
    active[ch] = false;
    onSince[ch] = 0;
  }
  writeRegisters();
  digitalWrite(STATUS_LED, LOW);
}

void allOn() {
  // Turn ON channels 1..56 (IC1 through IC7, all 8 bits = 0xFF)
  for (uint8_t i = 0; i < NUM_ICS - 1; ++i) {
    outputBytes[i] = 0xFF;
  }
  // IC8: Channels 57..63 ON (bits 0..6 = 1), Channel 64 (bit 7) reserved = 0
  outputBytes[7] = 0x7F;

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
  const uint8_t ic = idx / 8;
  const uint8_t bit = idx % 8;
  if (on) {
    outputBytes[ic] |= uint8_t(1U << bit);
    active[ch] = true;
    onSince[ch] = millis();
  } else {
    outputBytes[ic] &= uint8_t(~(1U << bit));
    active[ch] = false;
    onSince[ch] = 0;
  }
}

void setup() {
  digitalWrite(DATA_PIN, LOW);
  digitalWrite(CLOCK_PIN, LOW);
  digitalWrite(LATCH_PIN, LOW);
  digitalWrite(STATUS_LED, LOW);

  pinMode(DATA_PIN, OUTPUT);
  pinMode(CLOCK_PIN, OUTPUT);
  pinMode(LATCH_PIN, OUTPUT);
  pinMode(STATUS_LED, OUTPUT);

  Serial.begin(115200);
  allOff();

  Serial.println("ARDUINO_MEGA_63CH_READY");
  Serial.println("Pins: Latch=9, Data=8, Clock=6 | 8x 74HC595 (5V Logic)");
}

void loop() {
  bool changed = false;

  while (Serial.available() > 0) {
    const uint8_t b = uint8_t(Serial.read());

    // 1. Status Ping (Uppercase 'P' = 80; avoids '?' which is 63 / CH 63 ON, and 'p' which is 112 / CH 12 OFF)
    if (b == 'P') {
      Serial.println("ACK: MEGA_ALIVE");
      digitalWrite(STATUS_LED, HIGH);
      delay(30);
      digitalWrite(STATUS_LED, LOW);
    }
    // 2. ALL 63 ON Continuous (Uppercase 'A' = 65)
    else if (b == 'A') {
      watchdogEnabled = false; // Hold continuous signal
      allOn();
      changed = false;
      Serial.println("ACK: ALL 63 ON (CONTINUOUS)");
    }
    // 3. ALL OFF (0 or uppercase 'R'/'S'; avoids 'r'=114 / CH 14 OFF and 's'=115 / CH 15 OFF)
    else if (b == 0 || b == 'R' || b == 'S') {
      allOff();
      changed = false;
      Serial.println("ACK: ALL OFF");
    }
    // 4. Watchdog Controls (Uppercase 'W' = 87 Enable, 'X' = 88 Disable; avoids 'w'=119 / CH 19 OFF)
    else if (b == 'W') {
      watchdogEnabled = true;
      Serial.println("ACK: WATCHDOG ENABLED (250MS AUTO-OFF)");
    } else if (b == 'X') {
      watchdogEnabled = false;
      Serial.println("ACK: WATCHDOG DISABLED (CONTINUOUS HOLD)");
    }
    // 5. Diagnostic Test: IC 1 (Uppercase 'T' = 84; avoids 't'=116 / CH 16 OFF)
    else if (b == 'T') {
      for (uint8_t ch = 1; ch <= 8; ++ch) {
        setChannel(ch, true);
      }
      changed = true;
      Serial.println("ACK: DIAGNOSTIC TEST - IC1 (CH 01-08) ON");
    }
    // 6. Individual Channel ON (1..63)
    else if (b >= 1 && b <= NUM_CHANNELS) {
      setChannel(b, true);
      changed = true;
      Serial.print("ACK: CH ");
      Serial.print(b);
      Serial.println(" ON");
    }
    // 7. Individual Channel OFF (101..163)
    else if (b >= 101 && b <= 100 + NUM_CHANNELS) {
      const uint8_t ch = b - 100;
      setChannel(ch, false);
      changed = true;
      Serial.print("ACK: CH ");
      Serial.print(ch);
      Serial.println(" OFF");
    }
    else {
      // Ignore newlines / carriage returns
      if (b != '\r' && b != '\n' && b != ' ') {
        Serial.print("WARN: UNKNOWN CMD ");
        Serial.println(b);
      }
    }
  }

  if (changed) {
    writeRegisters();
    bool anyActive = false;
    for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
      if (active[ch]) { anyActive = true; break; }
    }
    digitalWrite(STATUS_LED, anyActive ? HIGH : LOW);
  }

  // Safety watchdog if enabled
  if (watchdogEnabled) {
    const uint32_t now = millis();
    bool watchdogChanged = false;
    for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
      if (active[ch] && uint32_t(now - onSince[ch]) >= WATCHDOG_MS) {
        setChannel(ch, false);
        watchdogChanged = true;
        Serial.print("WARN: CH ");
        Serial.print(ch);
        Serial.println(" watchdog OFF");
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
