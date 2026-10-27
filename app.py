"""
ESP32 Serial Controller & Monitor UI
Built with Python Tkinter and PySerial
"""

import threading
import time
import queue
import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports


class ESP32SerialApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 Serial Controller")
        self.root.geometry("720x560")
        self.root.minsize(640, 480)

        # Serial State
        self.ser = None
        self.is_connected = False
        self.read_thread = None
        self.stop_thread = threading.Event()
        self.msg_queue = queue.Queue()

        # Modern Color Palette
        self.colors = {
            "bg": "#121820",
            "card_bg": "#1a2332",
            "accent": "#00a8ff",
            "accent_hover": "#0090dd",
            "success": "#00e676",
            "danger": "#ff5252",
            "warning": "#ffd600",
            "text": "#f1f5f9",
            "text_muted": "#94a3b8",
            "log_bg": "#0f141c",
            "tx": "#38bdf8",
            "rx": "#4ade80",
            "sys": "#e2e8f0"
        }

        self.root.configure(bg=self.colors["bg"])
        self._init_styles()
        self._build_ui()

        # Start periodic queue polling for received serial data
        self.root.after(50, self._process_incoming_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Initial port scan
        self.refresh_ports()

    def _init_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=self.colors["bg"], foreground=self.colors["text"])
        style.configure("TLabel", background=self.colors["card_bg"], foreground=self.colors["text"], font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 12, "bold"), foreground=self.colors["accent"])
        style.configure("Muted.TLabel", foreground=self.colors["text_muted"], font=("Segoe UI", 9))
        
        style.configure("TCombobox", fieldbackground=self.colors["log_bg"], background=self.colors["card_bg"], foreground=self.colors["text"])
        style.map("TCombobox", fieldbackground=[("readonly", self.colors["log_bg"])], foreground=[("readonly", self.colors["text"])])

    def _build_ui(self):
        # Header / Title Bar
        header_frame = tk.Frame(self.root, bg=self.colors["bg"], pady=12, padx=16)
        header_frame.pack(fill=tk.X)

        title_lbl = tk.Label(
            header_frame,
            text="ESP32 Communication Console",
            font=("Segoe UI", 16, "bold"),
            fg=self.colors["text"],
            bg=self.colors["bg"]
        )
        title_lbl.pack(side=tk.LEFT)

        self.status_badge = tk.Label(
            header_frame,
            text="● Disconnected",
            font=("Segoe UI", 10, "bold"),
            fg=self.colors["danger"],
            bg=self.colors["bg"]
        )
        self.status_badge.pack(side=tk.RIGHT, padx=5)

        # Connection Card
        conn_frame = tk.Frame(self.root, bg=self.colors["card_bg"], bd=1, relief=tk.SOLID, padx=14, pady=12)
        conn_frame.pack(fill=tk.X, padx=16, pady=6)

        # Row 1: Port Selection & Baud Rate
        tk.Label(conn_frame, text="Serial Port:", bg=self.colors["card_bg"], fg=self.colors["text_muted"], font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
        self.port_combobox = ttk.Combobox(conn_frame, width=28, state="readonly")
        self.port_combobox.grid(row=0, column=1, sticky=tk.W, padx=6, pady=4)

        refresh_btn = tk.Button(
            conn_frame,
            text="🔄 Refresh",
            command=self.refresh_ports,
            bg="#2d3748",
            fg=self.colors["text"],
            activebackground="#4a5568",
            activeforeground="#ffffff",
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            font=("Segoe UI", 9)
        )
        refresh_btn.grid(row=0, column=2, padx=6, pady=4)

        tk.Label(conn_frame, text="Baud Rate:", bg=self.colors["card_bg"], fg=self.colors["text_muted"], font=("Segoe UI", 9, "bold")).grid(row=0, column=3, sticky=tk.W, padx=(16, 4), pady=4)
        self.baud_combobox = ttk.Combobox(conn_frame, width=12, state="readonly", values=["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.baud_combobox.set("115200")
        self.baud_combobox.grid(row=0, column=4, sticky=tk.W, padx=6, pady=4)

        self.connect_btn = tk.Button(
            conn_frame,
            text="Connect",
            command=self.toggle_connection,
            bg=self.colors["accent"],
            fg="#ffffff",
            activebackground=self.colors["accent_hover"],
            activeforeground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            bd=0,
            padx=16,
            pady=5,
            cursor="hand2"
        )
        self.connect_btn.grid(row=0, column=5, padx=(16, 0), pady=4)

        # Controls Card
        control_frame = tk.Frame(self.root, bg=self.colors["card_bg"], padx=14, pady=12)
        control_frame.pack(fill=tk.X, padx=16, pady=6)

        tk.Label(control_frame, text="Quick Commands:", bg=self.colors["card_bg"], fg=self.colors["text"], font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 6))

        btn_box = tk.Frame(control_frame, bg=self.colors["card_bg"])
        btn_box.pack(fill=tk.X, pady=(0, 10))

        self.btn_ping = tk.Button(
            btn_box,
            text="🔔 Send PING (Click Me!)",
            command=lambda: self.send_message("PING"),
            bg="#2563eb",
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            state=tk.DISABLED
        )
        self.btn_ping.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_status = tk.Button(
            btn_box,
            text="📊 Get ESP32 Status",
            command=lambda: self.send_message("STATUS"),
            bg="#334155",
            fg="#ffffff",
            activebackground="#475569",
            activeforeground="#ffffff",
            font=("Segoe UI", 9),
            bd=0,
            padx=12,
            pady=6,
            cursor="hand2",
            state=tk.DISABLED
        )
        self.btn_status.pack(side=tk.LEFT, padx=4)

        self.btn_hello = tk.Button(
            btn_box,
            text="👋 Say Hello",
            command=lambda: self.send_message("HELLO"),
            bg="#334155",
            fg="#ffffff",
            activebackground="#475569",
            activeforeground="#ffffff",
            font=("Segoe UI", 9),
            bd=0,
            padx=12,
            pady=6,
            cursor="hand2",
            state=tk.DISABLED
        )
        self.btn_hello.pack(side=tk.LEFT, padx=4)

        # Custom Message Row
        custom_box = tk.Frame(control_frame, bg=self.colors["card_bg"])
        custom_box.pack(fill=tk.X)

        tk.Label(custom_box, text="Custom Message:", bg=self.colors["card_bg"], fg=self.colors["text_muted"], font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 6))

        self.msg_entry = tk.Entry(
            custom_box,
            bg=self.colors["log_bg"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            font=("Segoe UI", 10),
            bd=1,
            relief=tk.FLAT
        )
        self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, ipady=4)
        self.msg_entry.bind("<Return>", lambda event: self.send_custom())

        self.btn_send = tk.Button(
            custom_box,
            text="Send",
            command=self.send_custom,
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            bd=0,
            padx=14,
            pady=4,
            cursor="hand2",
            state=tk.DISABLED
        )
        self.btn_send.pack(side=tk.LEFT, padx=(6, 0))

        # Log & Communication Display Card
        log_header = tk.Frame(self.root, bg=self.colors["bg"], padx=16)
        log_header.pack(fill=tk.X, pady=(6, 2))

        tk.Label(log_header, text="Serial Terminal Log:", font=("Segoe UI", 10, "bold"), fg=self.colors["text"], bg=self.colors["bg"]).pack(side=tk.LEFT)

        clear_btn = tk.Button(
            log_header,
            text="Clear Log",
            command=self.clear_log,
            bg="#1e293b",
            fg=self.colors["text_muted"],
            activebackground="#334155",
            activeforeground="#ffffff",
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
            font=("Segoe UI", 8)
        )
        clear_btn.pack(side=tk.RIGHT)

        log_frame = tk.Frame(self.root, bg=self.colors["card_bg"], padx=16)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 16))

        self.log_text = tk.Text(
            log_frame,
            bg=self.colors["log_bg"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            font=("Consolas", 10),
            bd=0,
            wrap=tk.WORD,
            padx=10,
            pady=10
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Log tags for coloring
        self.log_text.tag_config("TX", foreground=self.colors["tx"])
        self.log_text.tag_config("RX", foreground=self.colors["rx"])
        self.log_text.tag_config("SYS", foreground=self.colors["sys"])
        self.log_text.tag_config("ERR", foreground=self.colors["danger"])
        self.log_text.tag_config("TIME", foreground=self.colors["text_muted"])

        self._log_system("Application started. Select COM port and click Connect.")

    def refresh_ports(self):
        """Scans and updates available serial ports."""
        ports = serial.tools.list_ports.comports()
        port_list = []
        preferred_index = 0

        for i, p in enumerate(ports):
            desc = f"{p.device} - {p.description}"
            port_list.append(desc)
            # Heuristic for ESP32 / USB bridges (CH340, CP210x, FTDI)
            if any(k in p.description.lower() for k in ["cp210", "ch340", "ftdi", "uart", "usb serial", "esp"]):
                preferred_index = i

        self.port_combobox["values"] = port_list
        if port_list:
            self.port_combobox.current(preferred_index)
            self._log_system(f"Found {len(port_list)} serial port(s).")
        else:
            self.port_combobox.set("No COM ports found")
            self._log_system("No active COM ports detected. Please connect your ESP32.")

    def toggle_connection(self):
        """Connects or disconnects the serial port."""
        if not self.is_connected:
            selected_str = self.port_combobox.get()
            if not selected_str or "No COM ports" in selected_str:
                messagebox.showwarning("Warning", "Please select a valid COM port!")
                return

            port_device = selected_str.split(" - ")[0].strip()
            try:
                baud = int(self.baud_combobox.get())
            except ValueError:
                baud = 115200

            try:
                self.ser = serial.Serial(
                    port=port_device,
                    baudrate=baud,
                    timeout=1.0,
                    write_timeout=1.0
                )
                self.is_connected = True
                self.stop_thread.clear()
                self.read_thread = threading.Thread(target=self._serial_reader_worker, daemon=True)
                self.read_thread.start()

                # Update UI
                self.status_badge.config(text=f"● Connected ({port_device})", fg=self.colors["success"])
                self.connect_btn.config(text="Disconnect", bg=self.colors["danger"], activebackground="#e53935")
                self.port_combobox.config(state=tk.DISABLED)
                self.baud_combobox.config(state=tk.DISABLED)

                self.btn_ping.config(state=tk.NORMAL)
                self.btn_status.config(state=tk.NORMAL)
                self.btn_hello.config(state=tk.NORMAL)
                self.btn_send.config(state=tk.NORMAL)

                self._log_system(f"Connected to {port_device} at {baud} baud.")
            except Exception as e:
                self.is_connected = False
                self._log_error(f"Failed to connect to {port_device}: {str(e)}")
                messagebox.showerror("Connection Error", f"Could not open port {port_device}:\n{str(e)}")
        else:
            self._disconnect()

    def _disconnect(self):
        """Cleanly closes serial port and updates UI."""
        self.is_connected = False
        self.stop_thread.set()

        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass

        self.ser = None

        # Update UI
        self.status_badge.config(text="● Disconnected", fg=self.colors["danger"])
        self.connect_btn.config(text="Connect", bg=self.colors["accent"], activebackground=self.colors["accent_hover"])
        self.port_combobox.config(state="readonly")
        self.baud_combobox.config(state="readonly")

        self.btn_ping.config(state=tk.DISABLED)
        self.btn_status.config(state=tk.DISABLED)
        self.btn_hello.config(state=tk.DISABLED)
        self.btn_send.config(state=tk.DISABLED)

        self._log_system("Disconnected from serial port.")

    def _serial_reader_worker(self):
        """Background thread worker to continuously read incoming lines."""
        while not self.stop_thread.is_set() and self.ser and self.ser.is_open:
            try:
                if self.ser.in_waiting > 0:
                    raw_data = self.ser.readline()
                    if raw_data:
                        line = raw_data.decode("utf-8", errors="replace").strip()
                        if line:
                            self.msg_queue.put(("RX", line))
                else:
                    time.sleep(0.02)
            except (serial.SerialException, OSError) as e:
                if not self.stop_thread.is_set():
                    self.msg_queue.put(("ERR", f"Serial connection lost: {str(e)}"))
                    self.msg_queue.put(("DISCONNECT", None))
                break

    def _process_incoming_queue(self):
        """Polls the message queue and writes to the UI log."""
        while not self.msg_queue.empty():
            msg_type, content = self.msg_queue.get_nowait()
            if msg_type == "RX":
                self._log_rx(content)
            elif msg_type == "ERR":
                self._log_error(content)
            elif msg_type == "DISCONNECT":
                self._disconnect()

        # Re-schedule poll
        self.root.after(50, self._process_incoming_queue)

    def send_message(self, text):
        """Sends a text message followed by newline to the ESP32."""
        if not self.is_connected or not self.ser or not self.ser.is_open:
            messagebox.showwarning("Warning", "Serial port is not connected!")
            return

        clean_text = text.strip()
        if not clean_text:
            return

        try:
            payload = (clean_text + "\n").encode("utf-8")
            self.ser.write(payload)
            self._log_tx(clean_text)
        except Exception as e:
            self._log_error(f"Send failed: {str(e)}")

    def send_custom(self):
        """Handler for the custom message input box."""
        msg = self.msg_entry.get().strip()
        if msg:
            self.send_message(msg)
            self.msg_entry.delete(0, tk.END)

    def _get_timestamp(self):
        return time.strftime("%H:%M:%S")

    def _log_tx(self, message):
        self._append_log(f"[{self._get_timestamp()}] ", "TIME")
        self._append_log("TX ❯ ", "TX")
        self._append_log(f"{message}\n", "TX")

    def _log_rx(self, message):
        self._append_log(f"[{self._get_timestamp()}] ", "TIME")
        self._append_log("RX ❮ ", "RX")
        self._append_log(f"{message}\n", "RX")

    def _log_system(self, message):
        self._append_log(f"[{self._get_timestamp()}] ", "TIME")
        self._append_log(f"[SYS] {message}\n", "SYS")

    def _log_error(self, message):
        self._append_log(f"[{self._get_timestamp()}] ", "TIME")
        self._append_log(f"[ERR] {message}\n", "ERR")

    def _append_log(self, text, tag):
        self.log_text.insert(tk.END, text, tag)
        self.log_text.see(tk.END)

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)

    def _on_close(self):
        if self.is_connected:
            self._disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = ESP32SerialApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
