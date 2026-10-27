# 63-Channel Ejector & Indicator Tester

This repository contains firmware and desktop GUI controllers for testing 63 physical ejector indicators driven by cascaded 74HC595 shift registers.

---

## Hardware Configurations

### 1. Arduino Mega 2560 (5V Logic)
* **Firmware:** [`ard.ino`](ard.ino)
* **Desktop GUI:** [`ard.py`](ard.py)

#### Pin Connections:
* **Arduino Mega Pin 9** $\rightarrow$ 74HC595 Pin 12 (`RCLK` / Storage Latch Clock)
* **Arduino Mega Pin 8** $\rightarrow$ 74HC595 Pin 14 (`SER` / Serial Data In to IC1)
* **Arduino Mega Pin 6** $\rightarrow$ 74HC595 Pin 11 (`SRCLK` / Shift Register Clock)
* **Arduino Mega GND**   $\rightarrow$ 74HC595 Pin 8 (`GND`)
* **Arduino Mega 5V**    $\rightarrow$ 74HC595 Pin 16 (`VCC` - 5V Logic)
* **74HC595 Pin 10**     $\rightarrow$ Connect to **5V** (`SRCLR` / $\overline{\text{MR}}$ - Active LOW disabled)
* **74HC595 Pin 13**     $\rightarrow$ Connect to **GND** ($\overline{\text{OE}}$ - Outputs Enabled)

---

### 2. ESP32 (3.3V Logic)
* **Firmware:** [`test.ino`](test.ino)
* **Desktop GUI:** [`test.py`](test.py)

#### Pin Connections:
* **ESP32 GPIO 27** $\rightarrow$ 74HC595 Pin 12 (`RCLK` / Storage Latch Clock)
* **ESP32 GPIO 23** $\rightarrow$ 74HC595 Pin 14 (`SER` / Serial Data In to IC1)
* **ESP32 GPIO 18** $\rightarrow$ 74HC595 Pin 11 (`SRCLK` / Shift Register Clock)
* **ESP32 GPIO 2**  $\rightarrow$ Onboard Status LED
* **ESP32 GND**     $\rightarrow$ 74HC595 Pin 8 (`GND`)
* **ESP32 3.3V**    $\rightarrow$ 74HC595 Pin 16 (`VCC` - 3.3V Logic)
* **74HC595 Pin 10** $\rightarrow$ Connect to **3.3V** (`SRCLR` / $\overline{\text{MR}}$)
* **74HC595 Pin 13** $\rightarrow$ Connect to **GND** ($\overline{\text{OE}}$)

---

## 74HC595 Daisy Chain (All 8 ICs)
* **IC1 Pin 9** ($Q_7'$) $\rightarrow$ **IC2 Pin 14** (`SER`)
* **IC2 Pin 9** $\rightarrow$ **IC3 Pin 14**, continuing through **IC8**.
* Latch (Pin 12) and Clock (Pin 11) are wired in parallel across all 8 ICs.
* Place a **100 nF decoupling capacitor** across VCC and GND at each IC.

### Physical Mapping:
* **IC 1:** Channels 01 – 08 (Pins QA..QH)
* **IC 2:** Channels 09 – 16 (Pins QA..QH)
* **IC 3:** Channels 17 – 24 (Pins QA..QH)
* **IC 4:** Channels 25 – 32 (Pins QA..QH)
* **IC 5:** Channels 33 – 40 (Pins QA..QH)
* **IC 6:** Channels 41 – 48 (Pins QA..QH)
* **IC 7:** Channels 49 – 56 (Pins QA..QH)
* **IC 8:** Channels 57 – 63 (Pins QA..QG); **Channel 64 (Pin QH) is reserved**.

---

## Serial Protocol (115200 Baud, 8N1)

| Command | Byte Sent | Action |
| :--- | :--- | :--- |
| **ALL ON (Continuous)** | `'A'` (65 / 0x41) | Turns all 63 channels ON continuously (signals held) |
| **ALL OFF** | `0` (0x00) or `'R'` | Turns all 63 channels OFF immediately |
| **Channel ON** | `1` .. `63` | Turns Channel `n` ON |
| **Channel OFF** | `101` .. `163` | Turns Channel `n` OFF (`channel + 100`) |
| **Diagnostic Test** | `'T'` (84 / 0x54) | Turns ON all 8 channels of IC1 (`CH 01-08`) |
| **Status Ping** | `'P'` (80 / 0x50) | Inquires status / confirms liveness |

---

## Installation & Running

1. **Install Python Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run Arduino Mega Controller:**
   ```bash
   python ard.py
   ```

3. **Run ESP32 Controller:**
   ```bash
   python test.py
   ```
