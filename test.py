"""
ESP32 63-Channel Ejector & Indicator Tester
============================================
Physical hardware testing tool for 63 ejector indicators connected
through 8 cascaded 74HC595 shift registers.

Hardware Connections:
  ESP32 GPIO 23 -> SER / DS (Pin 14) of IC1
  ESP32 GPIO 18 -> SRCLK / SH_CP (Pin 11) of all 8 ICs
  ESP32 GPIO 27 -> RCLK / ST_CP (Pin 12) of all 8 ICs
  ESP32 GPIO 2  -> Onboard Status LED
  Daisy Chain   -> Pin 9 (Q7') of IC[n] to Pin 14 (SER) of IC[n+1]
  Pin 10 (SRCLR) -> 3.3V (HIGH = not reset)
  Pin 13 (OE)    -> GND (LOW = outputs enabled)
  Pin 16 (VCC)   -> Logic supply
  Pin 8 (GND)    -> Common logic ground

Serial Protocol (115200 baud, 8N1, Raw Bytes):
  Bytes 1..63    : Channel ON
  Bytes 101..163 : Channel OFF (channel + 100)
  Byte 0 / 'R'   : ALL OFF
  '?' / 'P'      : Status ping (responded with ACK: ESP32_ALIVE)

Safety:
  Firmware hardware watchdog turns channels OFF after 250 ms.
  GUI restricts pulse duration to 10..200 ms.
"""

import os
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
from datetime import datetime

import serial
import serial.tools.list_ports

BAUD_OPTIONS = ("9600", "57600", "115200", "230400")
CHANNELS = 63
NUM_ICS = 8
MAX_SAFE_PULSE_MS = 200  # Strictly capped below 250 ms firmware watchdog

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


def get_channel_info(ch: int):
    """Returns (ic_index_1_based, pin_name, description)."""
    if not (1 <= ch <= 64):
        return 0, "N/A", "Invalid"
    idx = ch - 1
    ic_num = (idx // 8) + 1
    pin = PIN_NAMES[idx % 8]
    if ch == 64:
        return ic_num, pin, "Channel 64 (Deliberately Reserved)"
    return ic_num, pin, f"IC {ic_num} - {pin} (Pin {idx % 8})"


class MappingVerificationDialog(tk.Toplevel):
    """
    Operator-assisted verification dialog to systematically verify
    each of the 63 physical lights. Records physical test results.
    """
    def __init__(self, parent, tester):
        super().__init__(parent)
        self.tester = tester
        self.title("Physical Light Mapping Verification Wizard")
        self.geometry("780x640")
        self.minsize(700, 520)
        self.configure(bg="#0f172a")

        self.current_ch = tk.IntVar(value=1)
        # Results: ch -> "PASS" | "FAIL" | "PENDING"
        self.results = {ch: "PENDING" for ch in range(1, CHANNELS + 1)}

        self._build_ui()
        self._update_display()

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg="#1e293b", padx=16, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="PHYSICAL OUTPUT VERIFICATION WIZARD",
                 font=("Segoe UI", 13, "bold"), fg="#38bdf8", bg="#1e293b").pack(anchor="w")
        tk.Label(hdr, text="Test each physical indicator light step-by-step and record operator confirmation.",
                 font=("Segoe UI", 9), fg="#94a3b8", bg="#1e293b").pack(anchor="w")

        # Current Channel Card
        card = tk.LabelFrame(self, text=" Current Test Target ",
                             font=("Segoe UI", 10, "bold"), fg="#f8fafc", bg="#1e293b", padx=16, pady=12)
        card.pack(fill="x", padx=16, pady=10)

        info_frame = tk.Frame(card, bg="#1e293b")
        info_frame.pack(fill="x")

        self.lbl_target = tk.Label(info_frame, text="CH 01", font=("Segoe UI", 24, "bold"),
                                   fg="#38bdf8", bg="#1e293b", width=6)
        self.lbl_target.pack(side="left", padx=(0, 20))

        details = tk.Frame(info_frame, bg="#1e293b")
        details.pack(side="left", fill="x", expand=True)

        self.lbl_ic_pin = tk.Label(details, text="Hardware: IC 1, Pin QA",
                                   font=("Segoe UI", 11, "bold"), fg="#f1f5f9", bg="#1e293b")
        self.lbl_ic_pin.pack(anchor="w")

        self.lbl_status = tk.Label(details, text="Status: PENDING TEST",
                                   font=("Segoe UI", 10), fg="#fbbf24", bg="#1e293b")
        self.lbl_status.pack(anchor="w", pady=(2, 0))

        # Test Action Buttons
        btn_box = tk.Frame(card, bg="#1e293b", pady=8)
        btn_box.pack(fill="x")

        tk.Button(btn_box, text="⚡ Pulse Output", command=self._pulse_current,
                  bg="#0284c7", fg="white", font=("Segoe UI", 10, "bold"),
                  padx=12, pady=5, bd=0).pack(side="left", padx=4)

        tk.Button(btn_box, text="🔄 Toggle State", command=self._toggle_current,
                  bg="#475569", fg="white", font=("Segoe UI", 10),
                  padx=10, pady=5, bd=0).pack(side="left", padx=4)

        tk.Button(btn_box, text="✔ Confirm PASS (Light ON)", command=self._mark_pass,
                  bg="#16a34a", fg="white", font=("Segoe UI", 10, "bold"),
                  padx=12, pady=5, bd=0).pack(side="left", padx=(16, 4))

        tk.Button(btn_box, text="✖ Mark FAIL (No Light)", command=self._mark_fail,
                  bg="#dc2626", fg="white", font=("Segoe UI", 10, "bold"),
                  padx=12, pady=5, bd=0).pack(side="left", padx=4)

        # Navigation
        nav_box = tk.Frame(card, bg="#1e293b")
        nav_box.pack(fill="x", pady=(6, 0))

        tk.Button(nav_box, text="<< Prev Channel", command=self._prev_ch,
                  bg="#334155", fg="white", font=("Segoe UI", 9), padx=10, bd=0).pack(side="left")
        tk.Button(nav_box, text="Next Channel >>", command=self._next_ch,
                  bg="#334155", fg="white", font=("Segoe UI", 9), padx=10, bd=0).pack(side="left", padx=6)

        self.lbl_progress = tk.Label(nav_box, text="Progress: 0 / 63 Verified",
                                     font=("Segoe UI", 9), fg="#94a3b8", bg="#1e293b")
        self.lbl_progress.pack(side="right")

        # Overview Table / Checklist
        tbl_frame = tk.LabelFrame(self, text=" Channel Verification Checklist ",
                                  font=("Segoe UI", 10, "bold"), fg="#f8fafc", bg="#1e293b", padx=10, pady=8)
        tbl_frame.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        self.tree = ttk.Treeview(tbl_frame, columns=("channel", "ic", "pin", "status", "timestamp"),
                                 show="headings", height=8)
        self.tree.heading("channel", text="Channel")
        self.tree.heading("ic", text="IC Chip")
        self.tree.heading("pin", text="IC Pin")
        self.tree.heading("status", text="Verification Status")
        self.tree.heading("timestamp", text="Verified At")

        self.tree.column("channel", width=70, anchor="center")
        self.tree.column("ic", width=70, anchor="center")
        self.tree.column("pin", width=90, anchor="center")
        self.tree.column("status", width=140, anchor="center")
        self.tree.column("timestamp", width=160, anchor="center")

        scrollbar = ttk.Scrollbar(tbl_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._on_tree_select)

        # Populate checklist table
        for ch in range(1, CHANNELS + 1):
            ic_num, pin, _ = get_channel_info(ch)
            self.tree.insert("", "end", iid=str(ch),
                             values=(f"CH {ch:02d}", f"IC {ic_num}", pin, "PENDING", "-"))

        # Footer Actions
        ftr = tk.Frame(self, bg="#0f172a", padx=16, pady=6)
        ftr.pack(fill="x")

        tk.Button(ftr, text="📄 Export Verification Report (.txt)", command=self._export_report,
                  bg="#334155", fg="white", font=("Segoe UI", 9), padx=10, pady=4, bd=0).pack(side="left")

        tk.Button(ftr, text="Close", command=self.destroy,
                  bg="#475569", fg="white", font=("Segoe UI", 9), padx=12, pady=4, bd=0).pack(side="right")

    def _update_display(self):
        ch = self.current_ch.get()
        ic_num, pin, _ = get_channel_info(ch)
        st = self.results.get(ch, "PENDING")

        self.lbl_target.config(text=f"CH {ch:02d}")
        self.lbl_ic_pin.config(text=f"Physical Route: IC {ic_num} ({PIN_NAMES[(ch-1)%8]}), Shift Register #{ic_num}")

        color_map = {"PASS": "#4ade80", "FAIL": "#f87171", "PENDING": "#fbbf24"}
        self.lbl_status.config(text=f"Operator Status: {st}", fg=color_map.get(st, "#f8fafc"))

        passed = sum(1 for v in self.results.values() if v == "PASS")
        failed = sum(1 for v in self.results.values() if v == "FAIL")
        self.lbl_progress.config(text=f"Pass: {passed} | Fail: {failed} | Pending: {CHANNELS - passed - failed} / {CHANNELS}")

        # Update Treeview selection
        if self.tree.exists(str(ch)):
            self.tree.selection_set(str(ch))
            self.tree.see(str(ch))

    def _pulse_current(self):
        ch = self.current_ch.get()
        self.tester.pulse_channel(ch)

    def _toggle_current(self):
        ch = self.current_ch.get()
        self.tester.channel_click(ch)

    def _mark_pass(self):
        ch = self.current_ch.get()
        self.results[ch] = "PASS"
        stamp = datetime.now().strftime("%H:%M:%S")
        ic_num, pin, _ = get_channel_info(ch)
        self.tree.item(str(ch), values=(f"CH {ch:02d}", f"IC {ic_num}", pin, "PASS (Verified)", stamp))
        self._next_ch()

    def _mark_fail(self):
        ch = self.current_ch.get()
        self.results[ch] = "FAIL"
        stamp = datetime.now().strftime("%H:%M:%S")
        ic_num, pin, _ = get_channel_info(ch)
        self.tree.item(str(ch), values=(f"CH {ch:02d}", f"IC {ic_num}", pin, "FAIL (No Output)", stamp))
        self._next_ch()

    def _next_ch(self):
        curr = self.current_ch.get()
        if curr < CHANNELS:
            self.current_ch.set(curr + 1)
        self._update_display()

    def _prev_ch(self):
        curr = self.current_ch.get()
        if curr > 1:
            self.current_ch.set(curr - 1)
        self._update_display()

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if sel:
            try:
                ch = int(sel[0])
                self.current_ch.set(ch)
                self._update_display()
            except ValueError:
                pass

    def _export_report(self):
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Save Verification Report",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=f"ejector_mapping_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        if not filename:
            return

        passed = sum(1 for v in self.results.values() if v == "PASS")
        failed = sum(1 for v in self.results.values() if v == "FAIL")
        pending = CHANNELS - passed - failed

        lines = [
            "===========================================================",
            "  ESP32 63-CHANNEL EJECTOR & INDICATOR VERIFICATION REPORT",
            "===========================================================",
            f"Generated At : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Total Tested : {CHANNELS} Channels across 8 Cascaded 74HC595 ICs",
            f"Summary      : PASS: {passed} | FAIL: {failed} | PENDING: {pending}",
            "-----------------------------------------------------------",
            f"{'Channel':<10} {'IC Chip':<10} {'IC Pin':<10} {'Result':<18} {'Notes'}",
            "-----------------------------------------------------------",
        ]
        for ch in range(1, CHANNELS + 1):
            ic_num, pin, _ = get_channel_info(ch)
            res = self.results.get(ch, "PENDING")
            note = "Physical light verified ON" if res == "PASS" else ("NO LIGHT / FAILED" if res == "FAIL" else "Not tested")
            lines.append(f"CH {ch:02d}      IC {ic_num:<7} {pin:<10} {res:<18} {note}")

        lines.extend([
            "-----------------------------------------------------------",
            "Hardware Route Notes:",
            "  Channel 64 (IC8, Pin QH) is deliberately reserved.",
            "  Test completed with operator visual confirmation.",
            "===========================================================",
        ])

        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            messagebox.showinfo("Export Successful", f"Report saved to:\n{filename}", parent=self)
        except Exception as err:
            messagebox.showerror("Export Failed", str(err), parent=self)


class EjectorTester:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 63-Channel Ejector & Indicator Tester")
        self.root.geometry("1200x820")
        self.root.minsize(980, 680)
        self.root.configure(bg="#0b0f17")

        # Serial & Threading State
        self.ser = None
        self.tx_lock = threading.Lock()
        self.reader_thread = None
        self.reader_running = False

        # Channel States (Commanded: False=OFF, True=ON)
        self.commanded_states = [False] * CHANNELS
        self.buttons = {}  # ch -> tk.Button
        self.pulse_after_ids = {}  # ch -> after_id (prevents race conditions)

        # Sequence Control
        self.sequence_running = False
        self.sequence_thread = None

        # Tkinter Variables
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value="115200")
        self.pulse_ms = tk.IntVar(value=100)
        self.gap_ms = tk.IntVar(value=80)
        self.target_ch = tk.IntVar(value=1)
        self.selected_bank = tk.IntVar(value=1)
        self.mode = tk.StringVar(value="Pulse")
        self.status_var = tk.StringVar(value="Disconnected")
        self.active_var = tk.StringVar(value="Commanded Active: 0 / 63")
        self.watchdog_enabled = tk.BooleanVar(value=True)

        self._build_ui()
        self.refresh_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        # 1. TOP HEADER & PORT BAR
        top = tk.Frame(self.root, bg="#111827", padx=14, pady=10)
        top.pack(fill="x")

        tk.Label(top, text="63-CHANNEL EJECTOR & INDICATOR TESTER",
                 font=("Segoe UI", 14, "bold"), fg="#38bdf8", bg="#111827").pack(side="left", padx=(0, 16))

        tk.Label(top, text="Port:", font=("Segoe UI", 9, "bold"),
                 fg="#9ca3af", bg="#111827").pack(side="left")
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=32, state="readonly")
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
                  padx=8, pady=3, bd=0).pack(side="left", padx=4)

        tk.Button(top, text="Test IC1 (T)", command=self.diag_test,
                  bg="#1e293b", fg="#38bdf8", font=("Segoe UI", 9, "bold"),
                  padx=8, pady=3, bd=1, relief="ridge").pack(side="left", padx=4)

        self.status_lbl = tk.Label(top, textvariable=self.status_var, font=("Segoe UI", 9, "bold"),
                                   fg="#ef4444", bg="#111827")
        self.status_lbl.pack(side="left", padx=8)

        # 2. CONTROLS BAR
        controls = tk.Frame(self.root, bg="#1f2937", padx=12, pady=8)
        controls.pack(fill="x", padx=8, pady=(4, 6))

        tk.Label(controls, text="Pulse (ms):", font=("Segoe UI", 9, "bold"),
                 fg="#d1d5db", bg="#1f2937").pack(side="left")
        self.pulse_spin = tk.Spinbox(controls, from_=10, to=MAX_SAFE_PULSE_MS, increment=10,
                                     textvariable=self.pulse_ms, width=5, font=("Segoe UI", 9))
        self.pulse_spin.pack(side="left", padx=4)

        tk.Label(controls, text="Gap (ms):", font=("Segoe UI", 9, "bold"),
                 fg="#d1d5db", bg="#1f2937").pack(side="left", padx=(8, 2))
        tk.Spinbox(controls, from_=10, to=2000, increment=10,
                   textvariable=self.gap_ms, width=6, font=("Segoe UI", 9)).pack(side="left", padx=4)

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

        # Verification Tool Button
        tk.Button(controls, text="📋 VERIFY MAPPING", command=self.open_verification_wizard,
                  bg="#d97706", fg="white", font=("Segoe UI", 9, "bold"),
                  padx=10, pady=2, bd=0).pack(side="left", padx=4)

        # STOP / ALL OFF Button
        self.btn_stop = tk.Button(controls, text="🛑 STOP / ALL OFF", command=self.stop_all,
                                  bg="#dc2626", fg="white", font=("Segoe UI", 10, "bold"),
                                  padx=14, pady=2, bd=0)
        self.btn_stop.pack(side="right", padx=4)

        # ALL 63 ON (Continuous) Button
        tk.Button(controls, text="⚡ ALL 63 ON", command=self.all_on_continuous,
                  bg="#16a34a", fg="white", font=("Segoe UI", 10, "bold"),
                  padx=12, pady=2, bd=0).pack(side="right", padx=4)

        # Watchdog Checkbox
        tk.Checkbutton(controls, text="Watchdog", variable=self.watchdog_enabled,
                       command=self.toggle_watchdog, fg="#d1d5db", bg="#1f2937",
                       selectcolor="#111827", activebackground="#1f2937",
                       font=("Segoe UI", 8)).pack(side="right", padx=4)

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
        tk.Label(grid_header, text="(Outputs mapped across 8 cascaded 74HC595 ICs; CH 64 reserved)",
                 font=("Segoe UI", 8), fg="#9ca3af", bg="#111827").pack(side="left", padx=8)

        grid_frame = tk.Frame(grid_container, bg="#111827")
        grid_frame.pack(fill="both", expand=True)

        for col in range(9):
            grid_frame.columnconfigure(col, weight=1 if col > 0 else 0)
        for row in range(8):
            grid_frame.rowconfigure(row, weight=1)

        # Build 8 rows corresponding to IC1..IC8
        for b_idx, (b_num, b_label, start_ch, end_ch) in enumerate(BANKS):
            # Bank Header Button on the left
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

            # 8 Output pins (QA..QH)
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
                    # Deliberately reserved channel 64
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

        # Status & Safety Card
        safety_card = tk.LabelFrame(side_frame, text=" Hardware & Safety Status ",
                                   font=("Segoe UI", 9, "bold"), fg="#f8fafc", bg="#1e293b", padx=8, pady=6)
        safety_card.pack(fill="x", pady=(0, 6))

        tk.Label(safety_card, textvariable=self.active_var, font=("Segoe UI", 10, "bold"),
                 fg="#38bdf8", bg="#1e293b").pack(anchor="w")

        tk.Label(safety_card, text="• Watchdog Limit: 250 ms max firmware continuous ON",
                 font=("Segoe UI", 8), fg="#94a3b8", bg="#1e293b").pack(anchor="w")
        tk.Label(safety_card, text="• GUI Pulse Limit: Capped at 200 ms for safe operation",
                 font=("Segoe UI", 8), fg="#94a3b8", bg="#1e293b").pack(anchor="w")
        tk.Label(safety_card, text="• Note: Buttons show commanded states; verify lights visually",
                 font=("Segoe UI", 8, "italic"), fg="#fbbf24", bg="#1e293b").pack(anchor="w")

        # Serial Log Header
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

        tk.Label(bottom, text="Protocol: Raw Byte (1..63=ON, 101..163=OFF, 0=ALL OFF, '?'=Ping) @ 115200 baud",
                 font=("Segoe UI", 8), fg="#6b7280", bg="#111827").pack(side="left")

        self.lbl_txrx = tk.Label(bottom, text="TX: 0 | RX: 0", font=("Segoe UI", 8),
                                 fg="#9ca3af", bg="#111827")
        self.lbl_txrx.pack(side="right")

        self.tx_count = 0
        self.rx_count = 0

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
        """Discovers serial ports and selects USB UART devices by default."""
        raw_ports = serial.tools.list_ports.comports()
        entries = []
        preferred_idx = -1
        usb_keywords = ("ch910", "cp210", "ch340", "ftdi", "uart", "usb", "esp")

        for idx, p in enumerate(raw_ports):
            desc = f"{p.device} ({p.description})"
            entries.append(desc)
            desc_lower = p.description.lower()
            if preferred_idx == -1 and any(k in desc_lower for k in usb_keywords) and "bluetooth" not in desc_lower:
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
            messagebox.showwarning("Select Port", "Please select the ESP32 COM port first.")
            return

        port = selection.split()[0].strip()

        try:
            self.ser = serial.Serial(port, int(self.baud_var.get()), timeout=0.1, write_timeout=1)
            # Crucial: deassert DTR/RTS so auto-reset doesn't hold ESP32 in reset/bootloader
            self.ser.dtr = False
            self.ser.rts = False

            # Wait for ESP32 boot
            time.sleep(1.2)
            self.ser.reset_input_buffer()

            self.reader_running = True
            self.reader_thread = threading.Thread(target=self.read_loop, daemon=True)
            self.reader_thread.start()

            self.connect_btn.configure(text="Disconnect", bg="#dc2626")
            self.status_var.set(f"Connected: {port}")
            self.status_lbl.configure(fg="#10b981")
            self.log(f"Connected to {port} @ {self.baud_var.get()} baud", "SYS")

            # Send initial status ping
            self.send_byte(ord("?"), "STATUS REQUEST (?)")

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
                # Issue best-effort ALL OFF before closing port
                ser.write(bytes([0]))
                ser.flush()
                ser.close()
            except Exception:
                pass

        self.connect_btn.configure(text="Connect", bg="#059669")
        self.status_var.set("Disconnected")
        self.status_lbl.configure(fg="#ef4444")
        self.log("Serial port disconnected", "SYS")

        # Reset visual state
        for ch in range(1, CHANNELS + 1):
            self.set_visual(ch, False)

    # --------------------------------------------------------------------------
    # SERIAL READER & WRITER (THREAD-SAFE)
    # --------------------------------------------------------------------------
    def read_loop(self):
        """Background thread that safely captures incoming telemetry from ESP32."""
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
        """Sends a single byte to the ESP32 in a thread-safe manner."""
        ser = self.ser
        if not ser or not ser.is_open:
            self.log("Transmission failed: Serial port not connected", "ERR")
            return False

        try:
            with self.tx_lock:
                ser.write(bytes([value]))
                ser.flush()
            self.tx_count += 1
            self.root.after(0, self._update_counters)
            desc_text = f" — {description}" if description else ""
            self.log(f"TX byte {value} (0x{value:02X}){desc_text}", "TX")
            return True
        except (serial.SerialException, OSError) as exc:
            self.log(f"TX write error: {exc}", "ERR")
            return False

    def _update_counters(self):
        self.lbl_txrx.config(text=f"TX: {self.tx_count} | RX: {self.rx_count}")

    def ping_status(self):
        """Sends a status inquiry ping '?' to verify ESP32 liveness."""
        if not self.send_byte(ord("?"), "STATUS PING (?)"):
            messagebox.showinfo("Status", "Cannot send ping: not connected.")

    def diag_test(self):
        """Sends 'T' command to turn on all 8 outputs of IC1 for hardware testing."""
        if not self.send_byte(ord("T"), "DIAGNOSTIC TEST (IC1 QA..QH ON)"):
            messagebox.showinfo("Status", "Cannot send diagnostic test: not connected.")
        else:
            for ch in range(1, 9):
                self.set_visual(ch, True)

    # --------------------------------------------------------------------------
    # CHANNEL STATE & VISUALS
    # --------------------------------------------------------------------------
    def set_visual(self, ch: int, on: bool):
        """Updates button color and label to reflect commanded state."""
        if not (1 <= ch <= CHANNELS):
            return
        self.commanded_states[ch - 1] = on
        btn = self.buttons.get(ch)
        if btn:
            pin_name = PIN_NAMES[(ch - 1) % 8]
            if on:
                btn.configure(
                    text=f"CH {ch:02d}\n{pin_name}: ON",
                    bg="#10b981",  # Vivid Emerald Green
                    fg="#ffffff"
                )
            else:
                btn.configure(
                    text=f"CH {ch:02d}\n{pin_name}: OFF",
                    bg="#1e293b",  # Dark Slate
                    fg="#cbd5e1"
                )

        active_count = sum(self.commanded_states)
        self.active_var.set(f"Commanded Active: {active_count} / {CHANNELS}")

    def channel_click(self, ch: int):
        """Handles direct user click on a channel button."""
        if self.mode.get() == "Toggle":
            new_state = not self.commanded_states[ch - 1]
            cmd_byte = ch if new_state else ch + 100
            desc = f"CH {ch} {'ON' if new_state else 'OFF'} (Toggle)"
            if self.send_byte(cmd_byte, desc):
                self.set_visual(ch, new_state)
        else:
            self.pulse_channel(ch)

    def pulse_channel(self, ch: int):
        """
        Pulses an individual channel with race-condition prevention.
        Uses native Tkinter after timers to avoid thread leakage.
        """
        # Strictly enforce safety pulse duration <= 200 ms
        raw_duration = int(self.pulse_ms.get())
        duration = max(10, min(MAX_SAFE_PULSE_MS, raw_duration))

        # Cancel any previous in-flight pulse for this exact channel
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
        """Fires the channel currently selected in the Spinbox."""
        try:
            ch = int(self.target_ch.get())
            if not 1 <= ch <= CHANNELS:
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showwarning("Invalid Channel", f"Select a channel between 1 and {CHANNELS}.")
            return
        self.channel_click(ch)

    # --------------------------------------------------------------------------
    # TESTING TOOLS & SEQUENCES
    # --------------------------------------------------------------------------
    def toggle_chaser(self):
        if self.sequence_running:
            self.stop_all()
        else:
            self.start_chaser()

    def start_chaser(self):
        """Sequentially pulses through channels 1 to 63 one-by-one."""
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Not Connected", "Connect to ESP32 before starting sequence.")
            return

        def worker():
            self.sequence_running = True
            self.root.after(0, lambda: self.btn_chaser.configure(text="STOP CHASER", bg="#ea580c"))
            self.log("Sequential 1-63 Chaser started", "SYS")

            for ch in range(1, CHANNELS + 1):
                if not self.sequence_running or not self.reader_running:
                    break

                duration = max(10, min(MAX_SAFE_PULSE_MS, int(self.pulse_ms.get())))
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
        """Sequentially pulses all channels inside a specific 74HC595 IC bank."""
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Not Connected", "Connect to ESP32 first.")
            return

        if self.sequence_running:
            messagebox.showinfo("Busy", "A test sequence is already active. Stop it first.")
            return

        # Find bank bounds
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

                duration = max(10, min(MAX_SAFE_PULSE_MS, int(self.pulse_ms.get())))
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

    def open_verification_wizard(self):
        """Opens the operator-guided physical mapping verification wizard."""
        MappingVerificationDialog(self.root, self)

    def all_on_continuous(self):
        """Commands all 63 channels to turn ON continuously without auto-off."""
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Not Connected", "Connect to ESP32 before sending commands.")
            return

        # Halt any running sequential chaser
        self.sequence_running = False

        # Clear any pending pulse timer rollbacks
        for ch, timer_id in list(self.pulse_after_ids.items()):
            try:
                self.root.after_cancel(timer_id)
            except Exception:
                pass
        self.pulse_after_ids.clear()

        # Transmit 'A' command (ALL 63 ON Continuous)
        if self.send_byte(ord("A"), "ALL 63 ON (Continuous Hold)"):
            self.watchdog_enabled.set(False)
            for ch in range(1, CHANNELS + 1):
                self.set_visual(ch, True)
            self.active_var.set(f"Commanded Active: {CHANNELS} / {CHANNELS} (CONTINUOUS ON)")
            self.log("ALL 63 CHANNELS COMMANDED CONTINUOUSLY ON (Signals Held)", "WARN")

    def toggle_watchdog(self):
        """Sends W/w command to enable/disable firmware 250ms watchdog."""
        if not self.ser or not self.ser.is_open:
            return
        enabled = self.watchdog_enabled.get()
        cmd = ord("W") if enabled else ord("w")
        desc = "ENABLE WATCHDOG (250ms Auto-Off)" if enabled else "DISABLE WATCHDOG (Continuous Hold)"
        self.send_byte(cmd, desc)

    def stop_all(self):
        """Immediately halts all test sequences and issues ALL OFF to ESP32."""
        self.sequence_running = False

        # Cancel all pending after-pulse callbacks
        for ch, timer_id in list(self.pulse_after_ids.items()):
            try:
                self.root.after_cancel(timer_id)
            except Exception:
                pass
        self.pulse_after_ids.clear()

        # Transmit high-priority ALL OFF byte (0)
        self.send_byte(0, "ALL OFF (Stop Signal)")

        # Re-enable watchdog tracking
        if hasattr(self, 'watchdog_enabled'):
            self.watchdog_enabled.set(True)

        # Clear UI commanded visual states immediately
        for ch in range(1, CHANNELS + 1):
            self.set_visual(ch, False)

        self.log("ALL OFF command executed; all operations stopped", "WARN")

    def close(self):
        self.stop_all()
        self.disconnect()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = EjectorTester(root)
    root.mainloop()
