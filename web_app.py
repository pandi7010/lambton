"""
ESP32 63-Channel Ejector & Indicator Tester — Web Version (WiFi + WebSocket)
=============================================================================
Flask web server that serves a responsive HTML UI.

Connection Modes:
  1. WiFi WebSocket: ESP32 runs WebSocket server, browser connects via ws://
  2. USB Serial: Web Serial API fallback (Chrome only, for USB OTG)

Deploy to Render:
  - Build command: pip install -r requirements.txt
  - Start command: gunicorn web_app:app --bind 0.0.0.0:$PORT
"""

from flask import Flask, render_template_string

app = Flask(__name__)

HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>ESP32 63-Channel Ejector Tester</title>
<style>
  :root {
    --bg: #0b0f17;
    --card: #111827;
    --card2: #1e293b;
    --accent: #38bdf8;
    --green: #10b981;
    --red: #ef4444;
    --orange: #f97316;
    --purple: #8b5cf6;
    --text: #f3f4f6;
    --muted: #9ca3af;
    --dim: #6b7280;
    --on-bg: #10b981;
    --off-bg: #1e293b;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    overflow-x: hidden;
    -webkit-tap-highlight-color: transparent;
  }

  /* HEADER */
  .header {
    background: var(--card);
    padding: 12px 16px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    border-bottom: 1px solid #1f2937;
    position: sticky;
    top: 0;
    z-index: 100;
  }
  .header h1 {
    font-size: 15px;
    color: var(--accent);
    white-space: nowrap;
    flex-shrink: 0;
  }
  .status-badge {
    font-size: 12px;
    font-weight: 700;
    padding: 4px 12px;
    border-radius: 20px;
    background: #1f2937;
    color: var(--red);
    white-space: nowrap;
  }
  .status-badge.connected {
    color: var(--green);
    background: #064e3b;
  }

  .btn {
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
    color: white;
    touch-action: manipulation;
  }
  .btn:active { transform: scale(0.95); }
  .btn-connect { background: #059669; }
  .btn-connect.active { background: var(--red); }
  .btn-ping { background: #374151; }
  .btn-test { background: var(--card2); color: var(--accent); border: 1px solid #334155; }

  .header-right {
    margin-left: auto;
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }

  /* CONNECTION MODE SECTION */
  .conn-section {
    background: var(--card);
    padding: 12px 16px;
    border-bottom: 1px solid #1f2937;
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
  }
  .conn-mode-toggle {
    display: flex;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #374151;
  }
  .conn-mode-toggle button {
    background: #111827;
    color: var(--muted);
    border: none;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }
  .conn-mode-toggle button.active {
    background: var(--accent);
    color: #0c4a6e;
  }
  .wifi-input-group {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .wifi-input-group label {
    font-size: 12px;
    color: var(--muted);
    font-weight: 700;
  }
  .wifi-input-group input {
    background: #0f172a;
    border: 1px solid #374151;
    color: var(--text);
    padding: 7px 10px;
    border-radius: 6px;
    font-size: 13px;
    font-family: 'Consolas', monospace;
    width: 160px;
  }
  .wifi-input-group input::placeholder { color: var(--dim); }

  /* CONTROLS BAR */
  .controls {
    background: #1f2937;
    padding: 10px 16px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    border-bottom: 1px solid #374151;
  }
  .control-group {
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .control-group label {
    font-size: 12px;
    font-weight: 700;
    color: var(--muted);
  }
  .control-group input, .control-group select {
    background: #111827;
    border: 1px solid #374151;
    color: var(--text);
    padding: 5px 8px;
    border-radius: 4px;
    font-size: 13px;
    width: 70px;
  }

  .btn-action { font-size: 12px; padding: 6px 12px; }
  .btn-fire { background: #0284c7; }
  .btn-bank { background: #4f46e5; }
  .btn-chaser { background: #0d9488; }
  .btn-all-on { background: #16a34a; }
  .btn-stop { background: #dc2626; font-size: 13px; padding: 8px 16px; }

  .mode-toggle {
    display: flex;
    gap: 0;
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid #374151;
  }
  .mode-toggle button {
    background: #111827;
    color: var(--muted);
    border: none;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
  .mode-toggle button.active {
    background: var(--accent);
    color: #0c4a6e;
  }

  /* CHANNEL GRID */
  .grid-section { padding: 12px; }
  .grid-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
    flex-wrap: wrap;
  }
  .grid-header h2 { font-size: 14px; color: var(--text); }
  .grid-header .sub { font-size: 11px; color: var(--accent); }
  .active-counter {
    font-size: 13px;
    font-weight: 700;
    color: var(--accent);
    background: var(--card);
    padding: 4px 12px;
    border-radius: 20px;
    margin-left: auto;
  }

  .bank-row {
    display: flex;
    gap: 4px;
    margin-bottom: 4px;
    align-items: stretch;
  }
  .bank-label {
    min-width: 60px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--card2);
    color: var(--accent);
    font-size: 11px;
    font-weight: 700;
    border-radius: 6px;
    cursor: pointer;
    text-align: center;
    line-height: 1.3;
    border: 1px solid #334155;
    padding: 4px;
    flex-shrink: 0;
    transition: background 0.15s;
  }
  .bank-label:active { background: #334155; }

  .ch-btn {
    flex: 1;
    min-height: 52px;
    border: 1px solid #334155;
    border-radius: 6px;
    background: var(--off-bg);
    color: #cbd5e1;
    font-size: 11px;
    font-weight: 700;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    transition: all 0.12s;
    touch-action: manipulation;
    line-height: 1.2;
    user-select: none;
    -webkit-user-select: none;
  }
  .ch-btn .ch-num { font-size: 12px; }
  .ch-btn .ch-state { font-size: 10px; opacity: 0.8; }
  .ch-btn:active { transform: scale(0.93); }
  .ch-btn.on {
    background: var(--on-bg);
    color: white;
    border-color: #059669;
    box-shadow: 0 0 12px rgba(16, 185, 129, 0.3);
  }
  .ch-btn.disabled {
    background: #0f172a;
    color: #64748b;
    cursor: default;
    border-color: #1e293b;
  }

  /* LOG PANEL */
  .log-section { padding: 8px 12px 12px; }
  .log-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
  }
  .log-header h3 { font-size: 13px; color: var(--green); }
  .log-box {
    background: #080c14;
    border: 1px solid #1f2937;
    border-radius: 6px;
    padding: 10px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
    line-height: 1.5;
    max-height: 200px;
    overflow-y: auto;
    color: #e2e8f0;
    word-break: break-all;
  }
  .log-entry { margin-bottom: 2px; }
  .log-time { color: var(--dim); }
  .log-tx { color: var(--accent); }
  .log-rx { color: #4ade80; }
  .log-sys { color: #e2e8f0; }
  .log-err { color: var(--red); }
  .log-warn { color: var(--orange); }

  /* WIRING REFERENCE */
  .wiring-section { padding: 0 12px 12px; }
  .wiring-toggle {
    background: var(--card2);
    color: var(--text);
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 8px 14px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    width: 100%;
    text-align: left;
  }
  .wiring-content {
    background: var(--card2);
    border: 1px solid #334155;
    border-top: none;
    border-radius: 0 0 6px 6px;
    padding: 10px 14px;
    font-size: 11px;
    line-height: 1.8;
    display: none;
  }
  .wiring-content.show { display: block; }
  .wire-pin { color: #cbd5e1; }
  .wire-crucial { color: #4ade80; font-weight: 700; }

  /* BOTTOM BAR */
  .bottom-bar {
    background: var(--card);
    padding: 8px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 11px;
    color: var(--dim);
    border-top: 1px solid #1f2937;
    position: sticky;
    bottom: 0;
  }
  .counter { color: var(--muted); font-weight: 600; }

  /* Responsive */
  @media (max-width: 600px) {
    .header h1 { font-size: 13px; }
    .ch-btn { min-height: 44px; font-size: 10px; }
    .ch-btn .ch-num { font-size: 11px; }
    .bank-label { min-width: 44px; font-size: 10px; }
    .controls { padding: 8px 10px; }
    .btn { padding: 6px 10px; font-size: 12px; }
    .wifi-input-group input { width: 130px; }
  }
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <h1>⚡ ESP32 63-CH EJECTOR TESTER</h1>
  <span class="status-badge" id="statusBadge">● Disconnected</span>
  <div class="header-right">
    <button class="btn btn-connect" id="connectBtn" onclick="toggleConnection()">🔌 Connect</button>
    <button class="btn btn-ping" onclick="sendPing()">📡 Ping</button>
    <button class="btn btn-test" onclick="diagTestIC1()">🔬 Test IC1</button>
  </div>
</div>

<!-- CONNECTION MODE SECTION -->
<div class="conn-section">
  <div class="conn-mode-toggle">
    <button id="modeWifi" class="active" onclick="setConnMode('wifi')">📶 WiFi</button>
    <button id="modeUsb" onclick="setConnMode('usb')">🔌 USB Serial</button>
  </div>

  <!-- WiFi Settings -->
  <div id="wifiSettings" class="wifi-input-group">
    <label>ESP32 IP:</label>
    <input type="text" id="espIp" placeholder="192.168.1.100" value="">
    <label>Port:</label>
    <input type="number" id="espPort" value="81" style="width:60px">
  </div>

  <!-- USB Settings (hidden by default) -->
  <div id="usbSettings" class="wifi-input-group" style="display:none">
    <label>Baud:</label>
    <select id="baudRate" style="background:#0f172a;border:1px solid #374151;color:var(--text);padding:6px;border-radius:4px;font-size:13px;">
      <option value="9600">9600</option>
      <option value="57600">57600</option>
      <option value="115200" selected>115200</option>
      <option value="230400">230400</option>
    </select>
  </div>
</div>

<!-- CONTROLS -->
<div class="controls">
  <div class="control-group">
    <label>Pulse:</label>
    <input type="number" id="pulseMs" value="150" min="10" max="2000" step="20">
    <label>ms</label>
  </div>
  <div class="control-group">
    <label>Gap:</label>
    <input type="number" id="gapMs" value="80" min="10" max="2000" step="20">
    <label>ms</label>
  </div>
  <div class="control-group">
    <label>Mode:</label>
    <div class="mode-toggle">
      <button id="modePulse" class="active" onclick="setMode('pulse')">Pulse</button>
      <button id="modeToggleBt" onclick="setMode('toggle')">Toggle</button>
    </div>
  </div>
  <div class="control-group">
    <label>CH:</label>
    <input type="number" id="targetCh" value="1" min="1" max="63" style="width:50px">
    <button class="btn btn-action btn-fire" onclick="fireSelected()">FIRE</button>
  </div>
  <div class="control-group">
    <label>Bank:</label>
    <select id="bankSelect" style="background:#111827;border:1px solid #374151;color:var(--text);padding:5px;border-radius:4px;font-size:13px;width:50px;">
      <option>1</option><option>2</option><option>3</option><option>4</option>
      <option>5</option><option>6</option><option>7</option><option>8</option>
    </select>
    <button class="btn btn-action btn-bank" onclick="testSelectedBank()">TEST</button>
  </div>
  <button class="btn btn-action btn-chaser" id="chaserBtn" onclick="toggleChaser()">🔄 RUN 1-63</button>
  <button class="btn btn-action btn-all-on" onclick="allOnContinuous()">⚡ ALL ON</button>
  <button class="btn btn-stop" onclick="allOff()">🛑 STOP</button>
</div>

<!-- CHANNEL GRID -->
<div class="grid-section">
  <div class="grid-header">
    <h2>IC BANK & CHANNEL MATRIX</h2>
    <span class="sub">GPIO 13=Data, 12=Latch, 14=Clock</span>
    <span class="active-counter" id="activeCounter">Active: 0 / 63</span>
  </div>
  <div id="channelGrid"></div>
</div>

<!-- WIRING REFERENCE -->
<div class="wiring-section">
  <button class="wiring-toggle" onclick="this.nextElementSibling.classList.toggle('show')">
    📋 Hardware Wiring Reference ▼
  </button>
  <div class="wiring-content">
    <div class="wire-pin">• 74HC595 Pin 14 (Data/SER) → ESP32 GPIO 13</div>
    <div class="wire-pin">• 74HC595 Pin 12 (Latch/RCLK) → ESP32 GPIO 12</div>
    <div class="wire-pin">• 74HC595 Pin 11 (Clock/SRCLK) → ESP32 GPIO 14</div>
    <div class="wire-pin">• 74HC595 Pin 16 (VCC) → ESP32 5V (or VIN)</div>
    <div class="wire-crucial">• 74HC595 Pin 10 (/MR/SRCLR) → ESP32 5V (Crucial!)</div>
    <div class="wire-crucial">• 74HC595 Pin 13 (/OE) → ESP32 GND (Crucial!)</div>
    <div class="wire-pin">• 74HC595 Pin 8 (GND) → ESP32 GND</div>
  </div>
</div>

<!-- LOG -->
<div class="log-section">
  <div class="log-header">
    <h3>📟 SERIAL LOG</h3>
    <button class="btn" style="background:#1f2937;font-size:11px;padding:4px 10px;" onclick="clearLog()">Clear</button>
  </div>
  <div class="log-box" id="logBox"></div>
</div>

<!-- BOTTOM BAR -->
<div class="bottom-bar">
  <span id="protocolInfo">Protocol: 'A'=ALL ON | 0=ALL OFF | 1..63=CH ON | 101..163=CH OFF</span>
  <span class="counter" id="txrxCounter">TX: 0 | RX: 0</span>
</div>

<script>
// ========== STATE ==========
const CHANNELS = 63;
const PIN_NAMES = ['QA','QB','QC','QD','QE','QF','QG','QH'];
const BANKS = [
  {num:1, label:'IC 1', start:1, end:8},
  {num:2, label:'IC 2', start:9, end:16},
  {num:3, label:'IC 3', start:17, end:24},
  {num:4, label:'IC 4', start:25, end:32},
  {num:5, label:'IC 5', start:33, end:40},
  {num:6, label:'IC 6', start:41, end:48},
  {num:7, label:'IC 7', start:49, end:56},
  {num:8, label:'IC 8', start:57, end:63},
];

let connMode = 'wifi';  // 'wifi' or 'usb'
let ws = null;           // WebSocket for WiFi mode
let serialPort = null;   // Web Serial for USB mode
let serialWriter = null;
let serialReader = null;
let readableStreamClosed = null;

let channelStates = new Array(CHANNELS).fill(false);
let mode = 'pulse';
let txCount = 0, rxCount = 0;
let chaserRunning = false;
let chaserAbort = null;
let pulseTimers = {};

// ========== CONNECTION MODE ==========
function setConnMode(m) {
  connMode = m;
  document.getElementById('modeWifi').classList.toggle('active', m === 'wifi');
  document.getElementById('modeUsb').classList.toggle('active', m === 'usb');
  document.getElementById('wifiSettings').style.display = m === 'wifi' ? 'flex' : 'none';
  document.getElementById('usbSettings').style.display = m === 'usb' ? 'flex' : 'none';
}

// ========== BUILD GRID ==========
function buildGrid() {
  const grid = document.getElementById('channelGrid');
  grid.innerHTML = '';
  BANKS.forEach(bank => {
    const row = document.createElement('div');
    row.className = 'bank-row';
    const bankBtn = document.createElement('div');
    bankBtn.className = 'bank-label';
    bankBtn.innerHTML = `${bank.label}<br>Test`;
    bankBtn.onclick = () => testBank(bank.num);
    row.appendChild(bankBtn);

    for (let pin = 0; pin < 8; pin++) {
      const ch = bank.start + pin;
      const btn = document.createElement('button');
      if (ch <= CHANNELS) {
        btn.className = 'ch-btn';
        btn.id = `ch-${ch}`;
        btn.innerHTML = `<span class="ch-num">CH ${String(ch).padStart(2,'0')}</span><span class="ch-state">${PIN_NAMES[pin]}: OFF</span>`;
        btn.onclick = () => channelClick(ch);
      } else {
        btn.className = 'ch-btn disabled';
        btn.innerHTML = `<span class="ch-num">CH 64</span><span class="ch-state">QH: RSVD</span>`;
        btn.disabled = true;
      }
      row.appendChild(btn);
    }
    grid.appendChild(row);
  });
}

// ========== CONNECTION ==========
async function toggleConnection() {
  if (connMode === 'wifi') {
    ws ? disconnectWifi() : connectWifi();
  } else {
    serialPort ? await disconnectUsb() : await connectUsb();
  }
}

// ----- WiFi WebSocket -----
function connectWifi() {
  const ip = document.getElementById('espIp').value.trim();
  const port = document.getElementById('espPort').value.trim();
  if (!ip) {
    logMsg('Enter the ESP32 IP address first!', 'err');
    return;
  }

  const url = `ws://${ip}:${port}`;
  logMsg(`Connecting to ${url}...`, 'sys');

  ws = new WebSocket(url);

  ws.onopen = () => {
    logMsg(`WebSocket connected to ${url}`, 'sys');
    updateConnUI(true, `WiFi: ${ip}`);
  };

  ws.onmessage = (event) => {
    const msg = event.data.trim();
    if (msg) {
      rxCount++;
      updateCounters();
      logMsg(msg, 'rx');
    }
  };

  ws.onerror = (err) => {
    logMsg('WebSocket error — check IP and ensure ESP32 is on same network', 'err');
  };

  ws.onclose = () => {
    logMsg('WebSocket disconnected', 'sys');
    ws = null;
    updateConnUI(false);
  };
}

function disconnectWifi() {
  chaserRunning = false;
  if (chaserAbort) chaserAbort.abort();
  if (ws) {
    try { ws.send(new Uint8Array([0])); } catch(e) {}  // ALL OFF
    ws.close();
    ws = null;
  }
  updateConnUI(false);
  for (let ch = 1; ch <= CHANNELS; ch++) setVisual(ch, false);
}

// ----- USB Web Serial -----
async function connectUsb() {
  try {
    if (!('serial' in navigator)) {
      logMsg('Web Serial API not supported — use Chrome!', 'err');
      return;
    }
    serialPort = await navigator.serial.requestPort();
    const baudRate = parseInt(document.getElementById('baudRate').value);
    await serialPort.open({ baudRate });
    serialWriter = serialPort.writable.getWriter();
    startSerialReading();
    updateConnUI(true, 'USB Serial');
    logMsg(`USB Serial connected at ${baudRate} baud`, 'sys');
    await sleep(1200);
    await sendByte(0x50, 'PING (P)');
  } catch (err) {
    serialPort = null;
    logMsg(`USB connection failed: ${err.message}`, 'err');
  }
}

async function disconnectUsb() {
  chaserRunning = false;
  if (chaserAbort) chaserAbort.abort();
  try {
    if (serialWriter) {
      try { await serialWriter.write(new Uint8Array([0])); } catch(e) {}
      serialWriter.releaseLock();
      serialWriter = null;
    }
    if (serialReader) { try { await serialReader.cancel(); } catch(e) {} serialReader = null; }
    if (readableStreamClosed) { try { await readableStreamClosed; } catch(e) {} readableStreamClosed = null; }
    if (serialPort) { try { await serialPort.close(); } catch(e) {} serialPort = null; }
  } catch(e) {}
  updateConnUI(false);
  for (let ch = 1; ch <= CHANNELS; ch++) setVisual(ch, false);
  logMsg('USB disconnected', 'sys');
}

function startSerialReading() {
  const decoder = new TextDecoderStream();
  readableStreamClosed = serialPort.readable.pipeTo(decoder.writable);
  serialReader = decoder.readable.getReader();
  (async () => {
    try {
      while (true) {
        const { value, done } = await serialReader.read();
        if (done) break;
        if (value) {
          value.split('\n').forEach(line => {
            line = line.trim();
            if (line) { rxCount++; updateCounters(); logMsg(line, 'rx'); }
          });
        }
      }
    } catch (err) {
      if (serialPort) logMsg(`Read error: ${err.message}`, 'err');
    }
  })();
}

function updateConnUI(connected, label) {
  const btn = document.getElementById('connectBtn');
  const badge = document.getElementById('statusBadge');
  if (connected) {
    btn.textContent = '⛔ Disconnect';
    btn.classList.add('active');
    badge.textContent = `● ${label || 'Connected'}`;
    badge.classList.add('connected');
  } else {
    btn.textContent = '🔌 Connect';
    btn.classList.remove('active');
    badge.textContent = '● Disconnected';
    badge.classList.remove('connected');
  }
}

function isConnected() {
  return (connMode === 'wifi' && ws && ws.readyState === WebSocket.OPEN) ||
         (connMode === 'usb' && serialWriter);
}

// ========== SEND ==========
async function sendByte(value, description) {
  if (!isConnected()) {
    logMsg('Not connected', 'err');
    return false;
  }

  try {
    const data = new Uint8Array([value]);
    if (connMode === 'wifi') {
      ws.send(data);
    } else {
      await serialWriter.write(data);
    }
    txCount++;
    updateCounters();

    const charRepr = (value >= 32 && value <= 126) ? `'${String.fromCharCode(value)}'` : `${value}`;
    const desc = description ? ` — ${description}` : '';
    logMsg(`TX byte ${charRepr} (0x${value.toString(16).toUpperCase().padStart(2,'0')})${desc}`, 'tx');
    return true;
  } catch (err) {
    logMsg(`TX error: ${err.message}`, 'err');
    return false;
  }
}

// ========== CHANNEL CONTROLS ==========
function setVisual(ch, on) {
  if (ch < 1 || ch > CHANNELS) return;
  channelStates[ch - 1] = on;
  const btn = document.getElementById(`ch-${ch}`);
  if (!btn) return;
  const pinName = PIN_NAMES[(ch - 1) % 8];
  if (on) {
    btn.classList.add('on');
    btn.innerHTML = `<span class="ch-num">CH ${String(ch).padStart(2,'0')}</span><span class="ch-state">${pinName}: ON</span>`;
  } else {
    btn.classList.remove('on');
    btn.innerHTML = `<span class="ch-num">CH ${String(ch).padStart(2,'0')}</span><span class="ch-state">${pinName}: OFF</span>`;
  }
  const activeCount = channelStates.filter(s => s).length;
  document.getElementById('activeCounter').textContent = `Active: ${activeCount} / ${CHANNELS}`;
}

async function channelClick(ch) {
  if (mode === 'toggle') {
    const newState = !channelStates[ch - 1];
    const cmdByte = newState ? ch : ch + 100;
    if (await sendByte(cmdByte, `CH ${ch} ${newState ? 'ON' : 'OFF'} (Toggle)`)) {
      setVisual(ch, newState);
    }
  } else {
    await pulseChannel(ch);
  }
}

async function pulseChannel(ch) {
  const duration = Math.max(10, parseInt(document.getElementById('pulseMs').value) || 150);
  if (pulseTimers[ch]) { clearTimeout(pulseTimers[ch]); delete pulseTimers[ch]; }
  if (!await sendByte(ch, `CH ${ch} ON (Pulse ${duration}ms)`)) return;
  setVisual(ch, true);
  pulseTimers[ch] = setTimeout(async () => {
    await sendByte(ch + 100, `CH ${ch} OFF`);
    setVisual(ch, false);
    delete pulseTimers[ch];
  }, duration);
}

function fireSelected() {
  const ch = parseInt(document.getElementById('targetCh').value);
  if (ch >= 1 && ch <= CHANNELS) channelClick(ch);
}

function setMode(m) {
  mode = m;
  document.getElementById('modePulse').classList.toggle('active', m === 'pulse');
  document.getElementById('modeToggleBt').classList.toggle('active', m === 'toggle');
}

// ========== ALL ON / OFF ==========
async function allOnContinuous() {
  if (!isConnected()) { logMsg('Not connected', 'err'); return; }
  chaserRunning = false;
  if (chaserAbort) chaserAbort.abort();
  Object.keys(pulseTimers).forEach(ch => clearTimeout(pulseTimers[ch]));
  pulseTimers = {};
  if (await sendByte(0x41, 'ALL 63 CHANNELS ON (Continuous)')) {
    for (let ch = 1; ch <= CHANNELS; ch++) setVisual(ch, true);
    logMsg('ALL 63 CHANNELS COMMANDED CONTINUOUSLY ON', 'warn');
  }
}

async function allOff() {
  chaserRunning = false;
  if (chaserAbort) chaserAbort.abort();
  Object.keys(pulseTimers).forEach(ch => clearTimeout(pulseTimers[ch]));
  pulseTimers = {};
  await sendByte(0, 'ALL OFF (Stop Signal)');
  for (let ch = 1; ch <= CHANNELS; ch++) setVisual(ch, false);
  logMsg('ALL OFF — all 63 channels commanded OFF', 'sys');
}

// ========== BANK TEST & CHASER ==========
async function testBank(bankNum) {
  if (!isConnected()) { logMsg('Not connected', 'err'); return; }
  if (chaserRunning) { logMsg('Chaser running — stop it first', 'warn'); return; }
  const bank = BANKS.find(b => b.num === bankNum);
  if (!bank) return;
  chaserRunning = true;
  chaserAbort = new AbortController();
  logMsg(`Testing ${bank.label} (CH ${String(bank.start).padStart(2,'0')}-${String(bank.end).padStart(2,'0')})`, 'sys');
  const pulse = Math.max(10, parseInt(document.getElementById('pulseMs').value) || 150);
  const gap = Math.max(10, parseInt(document.getElementById('gapMs').value) || 80);
  try {
    for (let ch = bank.start; ch <= bank.end; ch++) {
      if (!chaserRunning) break;
      await sendByte(ch, `CH ${ch} ON (Bank ${bankNum})`);
      setVisual(ch, true);
      await abortableSleep(pulse, chaserAbort.signal);
      await sendByte(ch + 100, `CH ${ch} OFF (Bank ${bankNum})`);
      setVisual(ch, false);
      if (ch < bank.end) await abortableSleep(gap, chaserAbort.signal);
    }
  } catch(e) {}
  chaserRunning = false;
  logMsg(`Bank ${bankNum} test completed`, 'sys');
}

function testSelectedBank() { testBank(parseInt(document.getElementById('bankSelect').value)); }

async function toggleChaser() {
  if (chaserRunning) {
    chaserRunning = false;
    if (chaserAbort) chaserAbort.abort();
    allOff();
    document.getElementById('chaserBtn').textContent = '🔄 RUN 1-63';
    document.getElementById('chaserBtn').style.background = '#0d9488';
  } else {
    await startChaser();
  }
}

async function startChaser() {
  if (!isConnected()) { logMsg('Not connected', 'err'); return; }
  chaserRunning = true;
  chaserAbort = new AbortController();
  document.getElementById('chaserBtn').textContent = '⏹ STOP';
  document.getElementById('chaserBtn').style.background = '#ea580c';
  logMsg('Sequential 1-63 Chaser started', 'sys');
  const pulse = Math.max(10, parseInt(document.getElementById('pulseMs').value) || 150);
  const gap = Math.max(10, parseInt(document.getElementById('gapMs').value) || 80);
  try {
    for (let ch = 1; ch <= CHANNELS; ch++) {
      if (!chaserRunning) break;
      await sendByte(ch, `CH ${ch} ON (Seq)`);
      setVisual(ch, true);
      await abortableSleep(pulse, chaserAbort.signal);
      await sendByte(ch + 100, `CH ${ch} OFF (Seq)`);
      setVisual(ch, false);
      if (ch < CHANNELS) await abortableSleep(gap, chaserAbort.signal);
    }
  } catch(e) {}
  chaserRunning = false;
  document.getElementById('chaserBtn').textContent = '🔄 RUN 1-63';
  document.getElementById('chaserBtn').style.background = '#0d9488';
  logMsg('Chaser completed/stopped', 'sys');
}

// ========== COMMANDS ==========
async function sendPing() { await sendByte(0x50, 'STATUS PING (P)'); }
async function diagTestIC1() {
  if (await sendByte(0x54, 'DIAGNOSTIC TEST (IC1 CH 01-08 ON)')) {
    for (let ch = 1; ch <= 8; ch++) setVisual(ch, true);
  }
}

// ========== LOGGING ==========
function logMsg(message, tag) {
  const box = document.getElementById('logBox');
  const time = new Date().toTimeString().split(' ')[0];
  const ms = String(new Date().getMilliseconds()).padStart(3, '0');
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = `<span class="log-time">[${time}.${ms}]</span> <span class="log-${tag}">[${tag.toUpperCase()}] ${escapeHtml(message)}</span>`;
  box.appendChild(entry);
  box.scrollTop = box.scrollHeight;
  while (box.children.length > 200) box.removeChild(box.firstChild);
}

function clearLog() { document.getElementById('logBox').innerHTML = ''; }
function escapeHtml(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
function updateCounters() { document.getElementById('txrxCounter').textContent = `TX: ${txCount} | RX: ${rxCount}`; }

// ========== UTILITIES ==========
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function abortableSleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted','AbortError')); }, {once:true});
  });
}

// ========== INIT ==========
document.addEventListener('DOMContentLoaded', () => {
  buildGrid();

  // Try to load saved ESP32 IP from localStorage
  const savedIp = localStorage.getItem('esp32_ip');
  if (savedIp) document.getElementById('espIp').value = savedIp;

  // Save IP on change
  document.getElementById('espIp').addEventListener('change', (e) => {
    localStorage.setItem('esp32_ip', e.target.value.trim());
  });

  logMsg('Ready! Select WiFi or USB mode, then click Connect.', 'sys');
  logMsg('WiFi: Enter ESP32 IP address (shown in Serial Monitor after upload)', 'sys');
});
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
