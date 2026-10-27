"""ESP32 63-channel 74HC595 ejector tester.

Install dependency: python -m pip install pyserial
Run: python ejector_test_63_final.py

Serial protocol: ON=1..63, OFF=101..163, all-off=0, ping='?'.
This app is a test UI, not a safety-rated industrial controller.
"""
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime
import serial
import serial.tools.list_ports

CHANNELS = 63
BAUD_OPTIONS = ("9600", "57600", "115200", "230400")
MAX_GUI_PULSE_MS = 200  # Keep below firmware's 250 ms watchdog

class EjectorTester:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 63-Channel Ejector Tester")
        self.root.geometry("1180x800")
        self.root.minsize(950, 650)
        self.root.configure(bg="#15191e")
        self.ser = None
        self.read_thread = None
        self.read_stop = threading.Event()
        self.states = [False] * CHANNELS
        self.buttons = {}
        self.after_ids = set()
        self.sequence_running = False
        self.sequence_channel = 1
        self.pulse_ms = tk.IntVar(value=100)
        self.gap_ms = tk.IntVar(value=80)
        self.target = tk.IntVar(value=1)
        self.mode = tk.StringVar(value="PULSE")
        self._build_ui()
        self.refresh_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        top = tk.Frame(self.root, bg="#202830", padx=12, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="63-CHANNEL EJECTOR TESTER", bg="#202830", fg="#50e3c2",
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        self.port = ttk.Combobox(top, width=12, state="readonly")
        self.port.pack(side="left", padx=(18, 4))
        tk.Button(top, text="Refresh", command=self.refresh_ports).pack(side="left", padx=3)
        self.baud = ttk.Combobox(top, width=9, state="readonly", values=BAUD_OPTIONS)
        self.baud.set("115200")
        self.baud.pack(side="left", padx=4)
        self.connect_btn = tk.Button(top, text="CONNECT", command=self.toggle_connection,
                                     bg="#167d68", fg="white", padx=12)
        self.connect_btn.pack(side="left", padx=6)
        self.status = tk.Label(top, text="DISCONNECTED", bg="#202830", fg="#ff7777")
        self.status.pack(side="left", padx=8)

        controls = tk.Frame(self.root, bg="#20242a", padx=10, pady=8)
        controls.pack(fill="x", padx=8, pady=8)
        tk.Label(controls, text="Pulse (ms)", bg="#20242a", fg="white").pack(side="left")
        tk.Spinbox(controls, from_=10, to=MAX_GUI_PULSE_MS, increment=10,
                   textvariable=self.pulse_ms, width=6).pack(side="left", padx=5)
        tk.Label(controls, text="Gap (ms)", bg="#20242a", fg="white").pack(side="left", padx=(10, 0))
        tk.Spinbox(controls, from_=10, to=2000, increment=10,
                   textvariable=self.gap_ms, width=6).pack(side="left", padx=5)
        tk.Label(controls, text="Click mode", bg="#20242a", fg="white").pack(side="left", padx=(10, 4))
        ttk.Radiobutton(controls, text="Pulse", variable=self.mode, value="PULSE").pack(side="left")
        ttk.Radiobutton(controls, text="Toggle", variable=self.mode, value="TOGGLE").pack(side="left")
        tk.Label(controls, text="Channel", bg="#20242a", fg="white").pack(side="left", padx=(10, 3))
        tk.Spinbox(controls, from_=1, to=63, textvariable=self.target, width=4).pack(side="left")
        tk.Button(controls, text="FIRE", command=self.fire_target, bg="#087eae", fg="white").pack(side="left", padx=5)
        tk.Button(controls, text="START CHASER", command=self.start_chaser, bg="#435d9b", fg="white").pack(side="left", padx=5)
        tk.Button(controls, text="STOP / ALL OFF", command=self.stop_all, bg="#b3261e", fg="white").pack(side="right", padx=4)

        body = tk.Frame(self.root, bg="#15191e")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        grid_wrap = tk.Frame(body, bg="#15191e")
        grid_wrap.pack(side="left", fill="both", expand=True)
        for col in range(7): grid_wrap.columnconfigure(col, weight=1)
        for ch in range(1, CHANNELS + 1):
            btn = tk.Button(grid_wrap, text=f"CH {ch:02d}\nOFF", height=2,
                            bg="#303943", fg="white", command=lambda c=ch: self.channel_click(c))
            btn.grid(row=(ch-1)//7, column=(ch-1)%7, sticky="nsew", padx=2, pady=2)
            self.buttons[ch] = btn
        side = tk.Frame(body, bg="#0e1216", width=300)
        side.pack(side="right", fill="y", padx=(8, 0))
        side.pack_propagate(False)
        tk.Label(side, text="SERIAL LOG", bg="#0e1216", fg="#50e3c2",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=6, pady=5)
        self.logbox = scrolledtext.ScrolledText(side, width=38, bg="#080a0c", fg="#d6e0e8",
                                                font=("Consolas", 8), wrap="word")
        self.logbox.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        self.active_label = tk.Label(self.root, text="Active channels: 0 / 63", anchor="w",
                                     bg="#202830", fg="white", padx=10, pady=5)
        self.active_label.pack(fill="x", side="bottom")

    def log(self, message):
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.logbox.insert("end", f"[{stamp}] {message}\n")
        self.logbox.see("end")

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port["values"] = ports
        if ports and not self.port.get(): self.port.current(0)
        self.log("Ports: " + (", ".join(ports) if ports else "none detected"))

    def toggle_connection(self):
        if self.ser and self.ser.is_open:
            self.stop_all()
            self.read_stop.set()
            try: self.ser.close()
            except serial.SerialException: pass
            self.ser = None
            self.connect_btn.config(text="CONNECT", bg="#167d68")
            self.status.config(text="DISCONNECTED", fg="#ff7777")
            self.log("Disconnected")
            return
        port = self.port.get().strip()
        if not port:
            messagebox.showwarning("No port", "Select the ESP32 serial port first.")
            return
        try:
            self.ser = serial.Serial(port, int(self.baud.get()), timeout=0.1, write_timeout=0.5)
            time.sleep(1.8)  # ESP32 may reset when serial opens
            self.ser.reset_input_buffer()
            self.ser.write(b"\x00")
            self.ser.flush()
            self.read_stop.clear()
            self.read_thread = threading.Thread(target=self.read_serial, daemon=True)
            self.read_thread.start()
            self.connect_btn.config(text="DISCONNECT", bg="#b3261e")
            self.status.config(text=f"CONNECTED: {port}", fg="#50e3c2")
            self.log(f"Connected to {port} at {self.baud.get()} baud; ALL OFF sent")
        except (serial.SerialException, ValueError) as exc:
            self.ser = None
            messagebox.showerror("Connection failed", str(exc))
            self.log(f"ERROR: {exc}")

    def read_serial(self):
        while not self.read_stop.is_set():
            ser = self.ser
            if not ser or not ser.is_open: break
            try:
                line = ser.readline()
                if line:
                    text = line.decode("utf-8", errors="replace").strip()
                    if text: self.root.after(0, lambda s=text: self.log("RX " + s))
            except (serial.SerialException, OSError):
                break

    def send_bytes(self, values):
        if not self.ser or not self.ser.is_open:
            self.log("ERROR: not connected")
            return False
        try:
            payload = bytes(values)
            self.ser.write(payload)
            self.ser.flush()
            self.log("TX " + " ".join(str(v) for v in values))
            return True
        except (serial.SerialException, OSError) as exc:
            self.log(f"TX ERROR: {exc}")
            return False

    def _track_after(self, callback, delay_ms):
        holder = {}
        def run():
            self.after_ids.discard(holder.get("id"))
            callback()
        holder["id"] = self.root.after(delay_ms, run)
        self.after_ids.add(holder["id"])

    def set_visual(self, ch, on):
        self.states[ch-1] = on
        self.buttons[ch].config(text=f"CH {ch:02d}\n{'ON' if on else 'OFF'}",
                                bg=("#25a56a" if on else "#303943"))
        self.active_label.config(text=f"Active channels: {sum(self.states)} / 63")

    def channel_click(self, ch):
        if self.mode.get() == "TOGGLE":
            new_state = not self.states[ch-1]
            if self.send_bytes([ch if new_state else ch+100]): self.set_visual(ch, new_state)
        else:
            self.pulse_channel(ch)

    def pulse_channel(self, ch):
        if not self._connected(): return
        duration = self._pulse_duration()
        if self.send_bytes([ch]):
            self.set_visual(ch, True)
            self._track_after(lambda: self.turn_off(ch), duration)

    def turn_off(self, ch):
        if self.send_bytes([ch+100]): self.set_visual(ch, False)
        else: self.set_visual(ch, False)

    def fire_target(self):
        try: ch = int(self.target.get())
        except (ValueError, tk.TclError): return
        if 1 <= ch <= CHANNELS: self.pulse_channel(ch)

    def _pulse_duration(self):
        try: value = int(self.pulse_ms.get())
        except (ValueError, tk.TclError): value = 100
        value = max(10, min(MAX_GUI_PULSE_MS, value))
        self.pulse_ms.set(value)
        return value

    def start_chaser(self):
        if not self._connected(): return
        if self.sequence_running:
            self.sequence_running = False
            self.log("Chaser stop requested")
            return
        self.sequence_running = True
        self.sequence_channel = 1
        self.log("Chaser started")
        self._chaser_step()

    def _chaser_step(self):
        if not self.sequence_running: return
        if self.sequence_channel > CHANNELS:
            self.sequence_running = False
            self.log("Chaser complete")
            return
        ch = self.sequence_channel
        if not self.send_bytes([ch]):
            self.sequence_running = False
            return
        self.set_visual(ch, True)
        pulse = self._pulse_duration()
        try: gap = max(10, min(2000, int(self.gap_ms.get())))
        except (ValueError, tk.TclError): gap = 80
        def off_then_next():
            self.turn_off(ch)
            self.sequence_channel += 1
            self._track_after(self._chaser_step, gap)
        self._track_after(off_then_next, pulse)

    def stop_all(self):
        self.sequence_running = False
        for aid in list(self.after_ids):
            try: self.root.after_cancel(aid)
            except tk.TclError: pass
        self.after_ids.clear()
        # Send ALL OFF after cancelling scheduled pulse/sequence callbacks.
        self.send_bytes([0])
        for ch in range(1, CHANNELS+1): self.set_visual(ch, False)
        self.log("STOP: all outputs commanded OFF")

    def _connected(self):
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Not connected", "Connect to the ESP32 first.")
            return False
        return True

    def close(self):
        try:
            if self.ser and self.ser.is_open:
                self.stop_all()
                time.sleep(0.05)
        finally:
            self.read_stop.set()
            if self.ser:
                try: self.ser.close()
                except serial.SerialException: pass
            self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = EjectorTester(root)
    root.mainloop()
