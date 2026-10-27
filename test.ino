/*
  ESP32 63-channel ejector tester using 8 cascaded 74HC595 ICs.
  IMPORTANT: Test with actuator power disconnected first.

  ESP32 -> all 74HC595:
    GPIO23 -> SER / DS pin 14 of IC1
    GPIO18 -> SRCLK / SH_CP pin 11 of all ICs
    GPIO27 -> RCLK / ST_CP pin 12 of all ICs
    3V3   -> SRCLR / MR pin 10 of all ICs (HIGH = not reset)
    GND   -> OE pin 13 of all ICs (LOW = outputs enabled)
    3V3   -> VCC pin 16 (only if suitable for downstream driver logic)
    GND   -> GND pin 8
    100 nF capacitor across VCC/GND at each IC
  Daisy chain: IC1 Q7' pin 9 -> IC2 SER pin 14, etc.

  Serial protocol, 115200 baud:
    1..63    = channel ON
    101..163 = channel OFF (channel + 100)
    0 / R    = all OFF
    ?        = status ping

  Safety: firmware watchdog turns each channel OFF after MAX_ON_MS.
  This is NOT a substitute for a physical emergency stop or correctly rated
  drivers.
*/
#include <Arduino.h>

constexpr uint8_t DATA_PIN = 23;
constexpr uint8_t CLOCK_PIN = 18;
constexpr uint8_t LATCH_PIN = 27;
constexpr uint8_t LED_PIN = 2;        // Built-in status LED on ESP32 DevKit
constexpr uint8_t NUM_ICS = 8;
constexpr uint8_t NUM_CHANNELS = 63; // Channel 64 deliberately reserved
constexpr uint16_t MAX_ON_MS = 250;  // GUI must use <= 200 ms

uint8_t outputBytes[NUM_ICS] = {0};
bool active[NUM_CHANNELS + 1] = {false};
uint32_t onSince[NUM_CHANNELS + 1] = {0};

// Paced shiftOut with microsecond timing to overcome ESP32 240MHz GPIO slew rate
// and bus capacitance across cascaded 74HC595 chips and breadboard jumper wires.
void customShiftOut(uint8_t dataPin, uint8_t clockPin, uint8_t bitOrder, uint8_t val) {
  for (uint8_t i = 0; i < 8; ++i) {
    bool bitVal = (bitOrder == LSBFIRST) ? (val & (1 << i)) : (val & (1 << (7 - i)));
    digitalWrite(dataPin, bitVal ? HIGH : LOW);
    delayMicroseconds(3); // Data setup time
    digitalWrite(clockPin, HIGH);
    delayMicroseconds(5); // Clock HIGH pulse width (handles capacitive loading)
    digitalWrite(clockPin, LOW);
    delayMicroseconds(3); // Clock LOW recovery time
  }
}

void writeRegisters() {
  digitalWrite(LATCH_PIN, LOW);
  delayMicroseconds(3);
  for (int8_t i = NUM_ICS - 1; i >= 0; --i) {
    customShiftOut(DATA_PIN, CLOCK_PIN, MSBFIRST, outputBytes[i]);
  }
  delayMicroseconds(3);
  digitalWrite(LATCH_PIN, HIGH);
  delayMicroseconds(10); // Generous latch pulse width to guarantee storage register capture
  digitalWrite(LATCH_PIN, LOW);
  delayMicroseconds(2);
}

bool watchdogEnabled = true;

void allOff() {
  for (uint8_t i = 0; i < NUM_ICS; ++i)
    outputBytes[i] = 0;
  for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
    active[ch] = false;
    onSince[ch] = 0;
  }
  writeRegisters();
}

void allOn() {
  for (uint8_t i = 0; i < NUM_ICS - 1; ++i) {
    outputBytes[i] = 0xFF; // Channels 1..56 ON
  }
  outputBytes[7] = 0x7F;   // Channels 57..63 ON (Bit 7 is CH 64 reserved = 0)
  for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
    active[ch] = true;
    onSince[ch] = millis();
  }
  writeRegisters();
}

void setChannel(uint8_t ch, bool on) {
  if (ch < 1 || ch > NUM_CHANNELS)
    return;
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
  // Keep outputs in a known state while pins are configured.
  digitalWrite(DATA_PIN, LOW);
  digitalWrite(CLOCK_PIN, LOW);
  digitalWrite(LATCH_PIN, LOW);
  digitalWrite(LED_PIN, LOW);
  pinMode(DATA_PIN, OUTPUT);
  pinMode(CLOCK_PIN, OUTPUT);
  pinMode(LATCH_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);

  Serial.begin(115200);
  allOff();
  Serial.println("ESP32_READY");
  Serial.println("INFO: 63-channel tester ready; channel 64 reserved");
}

void loop() {
  bool changed = false;
  while (Serial.available() > 0) {
    const uint8_t b = uint8_t(Serial.read());

    // 1. Check commands FIRST to prevent '?' (ASCII 63) colliding with channel 63
    if (b == '?' || b == 'P' || b == 'p') {
      Serial.println("ACK: ESP32_ALIVE");
      // Quick flash to confirm serial ping receipt
      digitalWrite(LED_PIN, HIGH);
      delay(20);
      digitalWrite(LED_PIN, LOW);
    } else if (b == 'A' || b == 'a') {
      watchdogEnabled = false; // Disable auto-off for continuous test
      allOn();
      changed = false;
      digitalWrite(LED_PIN, HIGH);
      Serial.println("ACK: ALL 63 ON (CONTINUOUS)");
    } else if (b == 0 || b == 'R' || b == 'r' || b == 'S' || b == 's') {
      watchdogEnabled = true; // Re-enable safety watchdog on ALL OFF
      allOff();
      changed = false;
      digitalWrite(LED_PIN, LOW);
      Serial.println("ACK: ALL OFF");
    } else if (b == 'W') {
      watchdogEnabled = true;
      Serial.println("ACK: WATCHDOG ENABLED (250MS AUTO-OFF)");
    } else if (b == 'w') {
      watchdogEnabled = false;
      Serial.println("ACK: WATCHDOG DISABLED (CONTINUOUS HOLD)");
    } else if (b == 'T' || b == 't') {
      Serial.println("ACK: DIAGNOSTIC TEST - TURNING ON CH 1..8 (IC1 QA..QH)");
      for (uint8_t ch = 1; ch <= 8; ++ch) {
        setChannel(ch, true);
      }
      changed = true;
      digitalWrite(LED_PIN, HIGH);
    } else if (b >= 1 && b <= NUM_CHANNELS) {
      setChannel(b, true);
      changed = true;
      digitalWrite(LED_PIN, HIGH);
      Serial.printf("ACK: CH %u ON\n", b);
    } else if (b >= 101 && b <= 100 + NUM_CHANNELS) {
      const uint8_t ch = b - 100;
      setChannel(ch, false);
      changed = true;
      Serial.printf("ACK: CH %u OFF\n", ch);
    } else {
      Serial.printf("WARN: UNKNOWN BYTE %u (0x%02X)\n", b, b);
    }
  }

  if (changed) {
    writeRegisters();
    // Update onboard LED based on whether any channel is active
    bool anyActive = false;
    for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
      if (active[ch]) { anyActive = true; break; }
    }
    digitalWrite(LED_PIN, anyActive ? HIGH : LOW);
  }

  if (watchdogEnabled) {
    const uint32_t now = millis();
    bool watchdogChanged = false;
    for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
      if (active[ch] && uint32_t(now - onSince[ch]) >= MAX_ON_MS) {
        setChannel(ch, false);
        watchdogChanged = true;
        Serial.printf("WARN: CH %u watchdog OFF\n", ch);
      }
    }

    if (watchdogChanged) {
      writeRegisters();
      bool anyActive = false;
      for (uint8_t ch = 1; ch <= NUM_CHANNELS; ++ch) {
        if (active[ch]) { anyActive = true; break; }
      }
      digitalWrite(LED_PIN, anyActive ? HIGH : LOW);
    }
  }
}
