"""
Arduino Mega 2560 - 63-Channel Ejector & Indicator Tester GUI
============================================================
Physical hardware testing desktop application for 63 ejector indicators
controlled by an Arduino Mega 2560 via 8 cascaded 74HC595 shift registers.

Hardware Connections:
  Arduino Mega Pin 9 -> 74HC595 Pin 12 (RCLK / Latch)
  Arduino Mega Pin 8 -> 74HC595 Pin 14 (SER / Data)
  Arduino Mega Pin 6 -> 74HC595 Pin 11 (SRCLK / Clock)
  Arduino Mega GND   -> 74HC595 Pin 8  (GND)
  Arduino Mega 5V    -> 74HC595 Pin 16 (VCC - 5V Logic)
  74HC595 Pin 10     -> 5V (HIGH = not reset)
  74HC595 Pin 13     -> GND (LOW = outputs active)

Serial Protocol (115200 baud, 8N1):
  'A' / 'a'        : ALL 63 Channels ON (Continuous)
  0 / 'R' / 'S'    : ALL OFF
  1..63 (raw byte) : Channel ON
  101..163         : Channel OFF (channel + 100)
  '?' / 'P'        : Status Ping
  'T'              : Diagnostic Test IC1 (CH 1..8 ON)
"""

import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime

import serial
import serial.tools.list_ports

BAUD_OPTIONS = ("9600", "57600", "115200", "230400")
CHANNELS = 63
NUM_ICS = 8

# IC Bank Definitions: (bank_num, ic_label, start_ch, end_ch)
BANKS = [
    (1, "IC 1 (CH 01-08)", 1, 8),
    (2, "IC 2 (CH 09-16)", 9, 16),
    (3, "IC 3 (CH 17-24)", 17, 24),
    (4, "IC 4 (CH 25-32)", 25, 32),
    (5, "IC 5 (CH 33-40)", 33, 40),
    (6, "IC 6 (CH 41-48)", 41, 48),
    (7, "IC 7 (CH 49-56)", 49, 56),
    (8, "IC 8 (CH 57-63)", 57, 63),
]

PIN_NAMES = ("QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH")


class MegaEjectorTesterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Arduino Mega 2560 — 63-Channel Ejector & Indicator Tester")
        self.root.geometry("1200x820")
        self.root.minsize(980, 680)
        self.root.configure(bg="#0b0f17")

        # Serial State
        self.ser = None
        self.tx_lock = threading.Lock()
        self.reader_thread = None
        self.reader_running = False

        # Channel States
        self.commanded_states = [False] * CHANNELS
        self.buttons = {}
        self.pulse_after_ids = {}

        # Sequence Control
        self.sequence_running = False
        self.sequence_thread = None

        # Variables
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value="115200")
        self.pulse_ms = tk.IntVar(value=150)
        self.gap_ms = tk.IntVar(value=80)
        self.target_ch = tk.IntVar(value=1)
        self.selected_bank = tk.IntVar(value=1)
        self.mode = tk.StringVar(value="Pulse")
        self.status_var = tk.StringVar(value="Disconnected")
        self.active_var = tk.StringVar(value="Active: 0 / 63")
        self.watchdog_enabled = tk.BooleanVar(value=False)

        self.tx_count = 0
        self.rx_count = 0

        self._build_ui()
        self.refresh_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        # 1. TOP HEADER & PORT BAR
        top = tk.Frame(self.root, bg="#111827", padx=14, pady=10)
        top.pack(fill="x")

        tk.Label(top, text="ARDUINO MEGA 2560 (5V) — 63-CHANNEL EJECTOR TESTER",
                 font=("Segoe UI", 13, "bold"), fg="#38bdf8", bg="#111827").pack(side="left", padx=(0, 16))

        tk.Label(top, text="Port:", font=("Segoe UI", 9, "bold"),
                 fg="#9ca3af", bg="#111827").pack(side="left")
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=30, state="readonly")
        self.port_combo.pack(side="left", padx=5)

        tk.Button(top, text="Refresh", command=self.refresh_ports,
                  bg="#1f2937", fg="#f3f4f6", font=("Segoe UI", 9),
                  padx=8, pady=2, bd=0).pack(side="left", padx=3)

        tk.Label(top, text="Baud:", font=("Segoe UI", 9, "bold"),
                 fg="#9ca3af", bg="#111827").pack(side="left", padx=(10, 2))
        ttk.Combobox(top, textvariable=self.baud_var, values=BAUD_OPTIONS,
                     width=8, state="readonly").pack(side="left", padx=4)

        self.connect_btn = tk.Button(top, text="Connect", command=self.toggle_connection,
                                     bg="#059669", fg="white", font=("Segoe UI", 9, "bold"),
                                     padx=14, pady=3, bd=0)
        self.connect_btn.pack(side="left", padx=8)

        tk.Button(top, text="Ping (?)", command=self.ping_status,
                  bg="#374151", fg="white", font=("Segoe UI", 9),
                  padx=8, pady=3, bd=0).pack(side="left", padx=3)

        tk.Button(top, text="Test IC1 (T)", command=self.diag_test_ic1,
                  bg="#1e293b", fg="#38bdf8", font=("Segoe UI", 9, "bold"),
                  padx=8, pady=3, bd=1, relief="ridge").pack(side="left", padx=3)

        self.status_lbl = tk.Label(top, textvariable=self.status_var, font=("Segoe UI", 9, "bold"),
                                   fg="#ef4444", bg="#111827")
        self.status_lbl.pack(side="left", padx=8)

        # 2. CONTROLS BAR
        controls = tk.Frame(self.root, bg="#1f2937", padx=12, pady=8)
        controls.pack(fill="x", padx=8, pady=(4, 6))

        tk.Label(controls, text="Pulse (ms):", font=("Segoe UI", 9, "bold"),
                 fg="#d1d5db", bg="#1f2937").pack(side="left")
        tk.Spinbox(controls, from_=10, to=2000, increment=20,
                   textvariable=self.pulse_ms, width=5, font=("Segoe UI", 9)).pack(side="left", padx=4)

        tk.Label(controls, text="Gap (ms):", font=("Segoe UI", 9, "bold"),
                 fg="#d1d5db", bg="#1f2937").pack(side="left", padx=(8, 2))
        tk.Spinbox(controls, from_=10, to=2000, increment=20,
                   textvariable=self.gap_ms, width=5, font=("Segoe UI", 9)).pack(side="left", padx=4)

        tk.Label(controls, text="Mode:", font=("Segoe UI", 9, "bold"),
                 fg="#d1d5db", bg="#1f2937").pack(side="left", padx=(10, 2))
        tk.Radiobutton(controls, text="Pulse", variable=self.mode, value="Pulse",
                       fg="white", bg="#1f2937", selectcolor="#111827", activebackground="#1f2937").pack(side="left")
        tk.Radiobutton(controls, text="Toggle", variable=self.mode, value="Toggle",
                       fg="white", bg="#1f2937", selectcolor="#111827", activebackground="#1f2937").pack(side="left")

        # Channel Fire
        tk.Label(controls, text="Channel:", font=("Segoe UI", 9, "bold"),
                 fg="#d1d5db", bg="#1f2937").pack(side="left", padx=(12, 2))
        tk.Spinbox(controls, from_=1, to=CHANNELS, textvariable=self.target_ch,
                   width=4, font=("Segoe UI", 9)).pack(side="left", padx=4)
        tk.Button(controls, text="FIRE CH", command=self.fire_selected,
                  bg="#0284c7", fg="white", font=("Segoe UI", 9, "bold"),
                  padx=8, pady=2, bd=0).pack(side="left", padx=3)

        # Bank Test
        tk.Label(controls, text="Bank:", font=("Segoe UI", 9, "bold"),
                 fg="#d1d5db", bg="#1f2937").pack(side="left", padx=(10, 2))
        bank_combo = ttk.Combobox(controls, textvariable=self.selected_bank,
                                  values=list(range(1, 9)), width=3, state="readonly")
        bank_combo.pack(side="left", padx=2)
        tk.Button(controls, text="TEST BANK", command=self.test_selected_bank,
                  bg="#4f46e5", fg="white", font=("Segoe UI", 9, "bold"),
                  padx=8, pady=2, bd=0).pack(side="left", padx=3)

        # Sequential 1-63
        self.btn_chaser = tk.Button(controls, text="RUN ALL (1-63)", command=self.toggle_chaser,
                                    bg="#0d9488", fg="white", font=("Segoe UI", 9, "bold"),
                                    padx=10, pady=2, bd=0)
        self.btn_chaser.pack(side="left", padx=6)

        # RIGHT ACTIONS: ALL ON, STOP, WATCHDOG
        self.btn_stop = tk.Button(controls, text="🛑 STOP / ALL OFF", command=self.all_off,
                                  bg="#dc2626", fg="white", font=("Segoe UI", 10, "bold"),
                                  padx=14, pady=2, bd=0)
        self.btn_stop.pack(side="right", padx=4)

        self.btn_all_on = tk.Button(controls, text="⚡ ALL 63 ON", command=self.all_on_continuous,
                                    bg="#16a34a", fg="white", font=("Segoe UI", 10, "bold"),
                                    padx=14, pady=2, bd=0)
        self.btn_all_on.pack(side="right", padx=4)

        tk.Checkbutton(controls, text="Watchdog Auto-Off", variable=self.watchdog_enabled,
                       command=self.toggle_watchdog, fg="#d1d5db", bg="#1f2937",
                       selectcolor="#111827", activebackground="#1f2937",
                       font=("Segoe UI", 8)).pack(side="right", padx=6)

        # 3. MAIN BODY (PANED WINDOW)
        body = tk.PanedWindow(self.root, orient="horizontal", bg="#0b0f17", sashwidth=4)
        body.pack(fill="both", expand=True, padx=8, pady=4)

        # LEFT: 63 CHANNEL BUTTONS ORGANIZED BY IC BANK
        grid_container = tk.Frame(body, bg="#111827", padx=8, pady=8)
        body.add(grid_container, minsize=620)

        grid_header = tk.Frame(grid_container, bg="#111827")
        grid_header.pack(fill="x", pady=(0, 6))

        tk.Label(grid_header, text="PHYSICAL IC BANK & CHANNEL MATRIX",
                 font=("Segoe UI", 11, "bold"), fg="#f3f4f6", bg="#111827").pack(side="left")
        tk.Label(grid_header, text="(Mega Pin 9=Latch, Pin 8=Data, Pin 6=Clock | 5V Logic)",
                 font=("Segoe UI", 8), fg="#38bdf8", bg="#111827").pack(side="left", padx=8)

        grid_frame = tk.Frame(grid_container, bg="#111827")
        grid_frame.pack(fill="both", expand=True)

        for col in range(9):
            grid_frame.columnconfigure(col, weight=1 if col > 0 else 0)
        for row in range(8):
            grid_frame.rowconfigure(row, weight=1)

        # Build 8 rows corresponding to IC1..IC8
        for b_idx, (b_num, b_label, start_ch, end_ch) in enumerate(BANKS):
            bank_hdr = tk.Button(
                grid_frame,
                text=f"IC {b_num}\nTest",
                font=("Segoe UI", 8, "bold"),
                bg="#1e293b",
                fg="#38bdf8",
                activebackground="#334155",
                activeforeground="#ffffff",
                bd=1,
                relief="ridge",
                width=6,
                command=lambda b=b_num: self.test_bank(b)
            )
            bank_hdr.grid(row=b_idx, column=0, padx=(2, 6), pady=2, sticky="nsew")

            for pin_idx in range(8):
                ch = start_ch + pin_idx
                col_idx = pin_idx + 1
                if ch <= CHANNELS:
                    pin_name = PIN_NAMES[pin_idx]
                    btn = tk.Button(
                        grid_frame,
                        text=f"CH {ch:02d}\n{pin_name}: OFF",
                        font=("Segoe UI", 8, "bold"),
                        bg="#1e293b",
                        fg="#cbd5e1",
                        activebackground="#334155",
                        activeforeground="#ffffff",
                        bd=1,
                        relief="ridge",
                        command=lambda c=ch: self.channel_click(c)
                    )
                    btn.grid(row=b_idx, column=col_idx, padx=2, pady=2, sticky="nsew")
                    self.buttons[ch] = btn
                elif ch == 64:
                    res_btn = tk.Button(
                        grid_frame,
                        text="CH 64\nQH: RSVD",
                        font=("Segoe UI", 8),
                        bg="#0f172a",
                        fg="#64748b",
                        state="disabled",
                        bd=1,
                        relief="groove"
                    )
                    res_btn.grid(row=b_idx, column=col_idx, padx=2, pady=2, sticky="nsew")

        # RIGHT: SERIAL TERMINAL & HARDWARE STATUS
        side_frame = tk.Frame(body, bg="#111827", padx=8, pady=8)
        body.add(side_frame, minsize=320)

        status_card = tk.LabelFrame(side_frame, text=" Hardware Wiring Reference ",
                                    font=("Segoe UI", 9, "bold"), fg="#f8fafc", bg="#1e293b", padx=8, pady=6)
        status_card.pack(fill="x", pady=(0, 6))

        tk.Label(status_card, textvariable=self.active_var, font=("Segoe UI", 10, "bold"),
                 fg="#38bdf8", bg="#1e293b").pack(anchor="w")
        tk.Label(status_card, text="• Arduino Pin 9 -> 74HC595 Pin 12 (Latch)", font=("Segoe UI", 8), fg="#cbd5e1", bg="#1e293b").pack(anchor="w")
        tk.Label(status_card, text="• Arduino Pin 8 -> 74HC595 Pin 14 (Data)", font=("Segoe UI", 8), fg="#cbd5e1", bg="#1e293b").pack(anchor="w")
        tk.Label(status_card, text="• Arduino Pin 6 -> 74HC595 Pin 11 (Clock)", font=("Segoe UI", 8), fg="#cbd5e1", bg="#1e293b").pack(anchor="w")
        tk.Label(status_card, text="• 74HC595 Pin 10 -> 5V (HIGH = Not Reset)", font=("Segoe UI", 8, "bold"), fg="#4ade80", bg="#1e293b").pack(anchor="w")
        tk.Label(status_card, text="• 74HC595 Pin 13 -> GND (LOW = Outputs Active)", font=("Segoe UI", 8, "bold"), fg="#4ade80", bg="#1e293b").pack(anchor="w")

        log_hdr = tk.Frame(side_frame, bg="#111827")
        log_hdr.pack(fill="x", pady=(4, 2))

        tk.Label(log_hdr, text="SERIAL TELEMETRY LOG",
                 font=("Segoe UI", 9, "bold"), fg="#10b981", bg="#111827").pack(side="left")

        tk.Button(log_hdr, text="Clear Log", command=self.clear_log,
                  bg="#1f2937", fg="#d1d5db", font=("Segoe UI", 8),
                  padx=6, pady=1, bd=0).pack(side="right")

        self.log_box = scrolledtext.ScrolledText(side_frame, width=36,
                                                 font=("Consolas", 8), wrap="word",
                                                 bg="#080c14", fg="#e2e8f0", bd=0)
        self.log_box.pack(fill="both", expand=True)

        # 4. BOTTOM BAR
        bottom = tk.Frame(self.root, bg="#111827", padx=10, pady=4)
        bottom.pack(fill="x")

        tk.Label(bottom, text="Protocol: 'A'=ALL 63 ON | 0=ALL OFF | 1..63=CH ON | 101..163=CH OFF @ 115200 baud",
                 font=("Segoe UI", 8), fg="#6b7280", bg="#111827").pack(side="left")

        self.lbl_txrx = tk.Label(bottom, text="TX: 0 | RX: 0", font=("Segoe UI", 8),
                                 fg="#9ca3af", bg="#111827")
        self.lbl_txrx.pack(side="right")

    # --------------------------------------------------------------------------
    # SERIAL LOGGING & PORTS
    # --------------------------------------------------------------------------
    def log(self, message: str, tag: str = "INFO"):
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"[{stamp}] [{tag}] {message}\n"

        def append():
            self.log_box.insert("end", formatted)
            self.log_box.see("end")

        if threading.current_thread() is threading.main_thread():
            append()
        else:
            self.root.after(0, append)

    def clear_log(self):
        self.log_box.delete("1.0", "end")

    def refresh_ports(self):
        raw_ports = serial.tools.list_ports.comports()
        entries = []
        preferred_idx = -1
        keywords = ("mega", "2560", "arduino", "ch340", "cp210", "ftdi", "usb serial")

        for idx, p in enumerate(raw_ports):
            desc = f"{p.device} ({p.description})"
            entries.append(desc)
            desc_lower = p.description.lower()
            if preferred_idx == -1 and any(k in desc_lower for k in keywords) and "bluetooth" not in desc_lower:
                preferred_idx = idx

        self.port_combo["values"] = entries
        if entries:
            if preferred_idx >= 0:
                self.port_var.set(entries[preferred_idx])
            elif self.port_var.get() not in entries:
                self.port_var.set(entries[0])
        else:
            self.port_var.set("")
        self.log(f"Discovered {len(entries)} serial port(s)", "SYS")

    # --------------------------------------------------------------------------
    # CONNECTION MANAGEMENT
    # --------------------------------------------------------------------------
    def toggle_connection(self):
        if self.ser and self.ser.is_open:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        selection = self.port_var.get().strip()
        if not selection:
            messagebox.showwarning("Select Port", "Please select the Arduino Mega COM port.")
            return

        port = selection.split()[0].strip()

        try:
            self.ser = serial.Serial(port, int(self.baud_var.get()), timeout=0.1, write_timeout=1)
            # Allow Arduino Mega 2560 bootloader time to finish reset after opening port
            time.sleep(1.8)
            self.ser.reset_input_buffer()

            self.reader_running = True
            self.reader_thread = threading.Thread(target=self.read_loop, daemon=True)
            self.reader_thread.start()

            self.connect_btn.configure(text="Disconnect", bg="#dc2626")
            self.status_var.set(f"Connected: {port}")
            self.status_lbl.configure(fg="#10b981")
            self.log(f"Connected to {port} @ {self.baud_var.get()} baud", "SYS")

            # Send ping
            self.send_byte(ord("P"), "PING (P)")

        except Exception as exc:
            self.ser = None
            messagebox.showerror("Connection Failed", str(exc))
            self.log(f"Connection failure: {exc}", "ERR")

    def disconnect(self):
        self.sequence_running = False
        self.reader_running = False
        ser = self.ser
        self.ser = None

        if ser:
            try:
                ser.write(bytes([0]))
                ser.flush()
                ser.close()
            except Exception:
                pass

        self.connect_btn.configure(text="Connect", bg="#059669")
        self.status_var.set("Disconnected")
        self.status_lbl.configure(fg="#ef4444")
        self.log("Serial port disconnected", "SYS")

        for ch in range(1, CHANNELS + 1):
            self.set_visual(ch, False)

    def read_loop(self):
        while self.reader_running:
            ser = self.ser
            if not ser or not ser.is_open:
                break
            try:
                line = ser.readline()
                if line:
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if decoded:
                        self.rx_count += 1
                        self.root.after(0, self._update_counters)
                        self.log(decoded, "RX")
            except (serial.SerialException, OSError) as exc:
                if self.reader_running:
                    self.log(f"Serial reader exception: {exc}", "ERR")
                break

    def send_byte(self, value: int, description: str = None) -> bool:
        ser = self.ser
        if not ser or not ser.is_open:
            self.log("Transmission failed: Serial not connected", "ERR")
            return False

        try:
            with self.tx_lock:
                ser.write(bytes([value]))
                ser.flush()
            self.tx_count += 1
            self.root.after(0, self._update_counters)
            desc_text = f" — {description}" if description else ""
            char_repr = f"'{chr(value)}'" if 32 <= value <= 126 else f"{value}"
            self.log(f"TX byte {char_repr} (0x{value:02X}){desc_text}", "TX")
            return True
        except (serial.SerialException, OSError) as exc:
            self.log(f"TX write error: {exc}", "ERR")
            return False

    def _update_counters(self):
        self.lbl_txrx.config(text=f"TX: {self.tx_count} | RX: {self.rx_count}")

    def ping_status(self):
        if not self.send_byte(ord("P"), "STATUS PING (P)"):
            messagebox.showinfo("Status", "Cannot send ping: not connected.")

    def diag_test_ic1(self):
        """Sends 'T' command to turn on all 8 outputs of IC1."""
        if self.send_byte(ord("T"), "DIAGNOSTIC TEST (IC1 CH 01-08 ON)"):
            for ch in range(1, 9):
                self.set_visual(ch, True)

    # --------------------------------------------------------------------------
    # CHANNEL STATE & VISUALS
    # --------------------------------------------------------------------------
    def set_visual(self, ch: int, on: bool):
        if not (1 <= ch <= CHANNELS):
            return
        self.commanded_states[ch - 1] = on
        btn = self.buttons.get(ch)
        if btn:
            pin_name = PIN_NAMES[(ch - 1) % 8]
            if on:
                btn.configure(
                    text=f"CH {ch:02d}\n{pin_name}: ON",
                    bg="#10b981",
                    fg="#ffffff"
                )
            else:
                btn.configure(
                    text=f"CH {ch:02d}\n{pin_name}: OFF",
                    bg="#1e293b",
                    fg="#cbd5e1"
                )

        active_count = sum(self.commanded_states)
        self.active_var.set(f"Active: {active_count} / {CHANNELS}")

    def channel_click(self, ch: int):
        if self.mode.get() == "Toggle":
            new_state = not self.commanded_states[ch - 1]
            cmd_byte = ch if new_state else ch + 100
            desc = f"CH {ch} {'ON' if new_state else 'OFF'} (Toggle)"
            if self.send_byte(cmd_byte, desc):
                self.set_visual(ch, new_state)
        else:
            self.pulse_channel(ch)

    def pulse_channel(self, ch: int):
        duration = max(10, int(self.pulse_ms.get()))

        prev_timer = self.pulse_after_ids.pop(ch, None)
        if prev_timer:
            try:
                self.root.after_cancel(prev_timer)
            except Exception:
                pass

        if not self.send_byte(ch, f"CH {ch} ON (Pulse {duration}ms)"):
            return

        self.set_visual(ch, True)

        def turn_off():
            self.send_byte(ch + 100, f"CH {ch} OFF")
            self.set_visual(ch, False)
            self.pulse_after_ids.pop(ch, None)

        timer_id = self.root.after(duration, turn_off)
        self.pulse_after_ids[ch] = timer_id

    def fire_selected(self):
        try:
            ch = int(self.target_ch.get())
            if not 1 <= ch <= CHANNELS:
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showwarning("Invalid Channel", f"Select a channel between 1 and {CHANNELS}.")
            return
        self.channel_click(ch)

    # --------------------------------------------------------------------------
    # ALL ON / ALL OFF / SEQUENCES
    # --------------------------------------------------------------------------
    def all_on_continuous(self):
        """Commands all 63 channels to turn ON continuously."""
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Not Connected", "Connect to Arduino Mega first.")
            return

        self.sequence_running = False

        for ch, timer_id in list(self.pulse_after_ids.items()):
            try:
                self.root.after_cancel(timer_id)
            except Exception:
                pass
        self.pulse_after_ids.clear()

        if self.send_byte(ord("A"), "ALL 63 CHANNELS ON (Continuous)"):
            self.watchdog_enabled.set(False)
            for ch in range(1, CHANNELS + 1):
                self.set_visual(ch, True)
            self.active_var.set(f"Active: {CHANNELS} / {CHANNELS} (CONTINUOUS ON)")
            self.log("ALL 63 CHANNELS COMMANDED CONTINUOUSLY ON", "WARN")

    def all_off(self):
        """Commands all 63 channels to turn OFF immediately."""
        self.sequence_running = False

        for ch, timer_id in list(self.pulse_after_ids.items()):
            try:
                self.root.after_cancel(timer_id)
            except Exception:
                pass
        self.pulse_after_ids.clear()

        self.send_byte(0, "ALL OFF (Stop Signal)")

        for ch in range(1, CHANNELS + 1):
            self.set_visual(ch, False)

        self.log("ALL OFF executed; all 63 channels commanded OFF", "SYS")

    def toggle_watchdog(self):
        if not self.ser or not self.ser.is_open:
            return
        enabled = self.watchdog_enabled.get()
        cmd = ord("W") if enabled else ord("X")
        desc = "Enable Watchdog (250ms Auto-Off)" if enabled else "Disable Watchdog (Continuous Hold)"
        self.send_byte(cmd, desc)

    def toggle_chaser(self):
        if self.sequence_running:
            self.all_off()
        else:
            self.start_chaser()

    def start_chaser(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Not Connected", "Connect to Arduino Mega first.")
            return

        def worker():
            self.sequence_running = True
            self.root.after(0, lambda: self.btn_chaser.configure(text="STOP CHASER", bg="#ea580c"))
            self.log("Sequential 1-63 Chaser started", "SYS")

            for ch in range(1, CHANNELS + 1):
                if not self.sequence_running or not self.reader_running:
                    break

                duration = max(10, int(self.pulse_ms.get()))
                gap = max(10, int(self.gap_ms.get()))

                self.send_byte(ch, f"CH {ch} ON (Seq)")
                self.root.after(0, self.set_visual, ch, True)
                time.sleep(duration / 1000.0)

                self.send_byte(ch + 100, f"CH {ch} OFF (Seq)")
                self.root.after(0, self.set_visual, ch, False)
                time.sleep(gap / 1000.0)

            self.sequence_running = False
            self.root.after(0, lambda: self.btn_chaser.configure(text="RUN ALL (1-63)", bg="#0d9488"))
            self.log("Sequential Chaser completed/stopped", "SYS")

        self.sequence_thread = threading.Thread(target=worker, daemon=True)
        self.sequence_thread.start()

    def test_selected_bank(self):
        try:
            b_num = int(self.selected_bank.get())
            self.test_bank(b_num)
        except ValueError:
            pass

    def test_bank(self, bank_num: int):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Not Connected", "Connect to Arduino Mega first.")
            return

        if self.sequence_running:
            messagebox.showinfo("Busy", "A test sequence is already active. Stop it first.")
            return

        match = next((b for b in BANKS if b[0] == bank_num), None)
        if not match:
            return
        _, b_label, start_ch, end_ch = match

        def worker():
            self.sequence_running = True
            self.log(f"Starting test on {b_label} (CH {start_ch:02d}-{end_ch:02d})", "SYS")

            for ch in range(start_ch, end_ch + 1):
                if not self.sequence_running or not self.reader_running:
                    break

                duration = max(10, int(self.pulse_ms.get()))
                gap = max(10, int(self.gap_ms.get()))

                self.send_byte(ch, f"CH {ch} ON (Bank {bank_num})")
                self.root.after(0, self.set_visual, ch, True)
                time.sleep(duration / 1000.0)

                self.send_byte(ch + 100, f"CH {ch} OFF (Bank {bank_num})")
                self.root.after(0, self.set_visual, ch, False)
                time.sleep(gap / 1000.0)

            self.sequence_running = False
            self.log(f"Completed test on {b_label}", "SYS")

        threading.Thread(target=worker, daemon=True).start()

    def close(self):
        self.all_off()
        self.disconnect()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MegaEjectorTesterApp(root)
    root.mainloop()
