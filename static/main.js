/* =====================================================
   main.js — ML Training Dashboard client-side logic
   ===================================================== */

const socket = io();

// ─── State ────────────────────────────────────────────
let sessionTarget  = 0;
let sessionCurrent = 0;
let sessionActive  = false;

// ─── Chart ────────────────────────────────────────────
const chartColors = {
  byte_rate:            '#3b82f6',
  packet_rate:          '#8b5cf6',
  packet_size_variance: '#10b981',
  time_gap_variance:    '#f59e0b',
  time_gap_mean:        '#ef4444',
  packet_size_mean:     '#06b6d4',
};

const maxChartPoints = 30;
const chartData = {
  labels: [],
  datasets: [
    { label: 'Byte Rate',        data: [], borderColor: chartColors.byte_rate,            tension: .4, pointRadius: 1 },
    { label: 'Packet Rate',      data: [], borderColor: chartColors.packet_rate,          tension: .4, pointRadius: 1 },
    { label: 'Pkt-Size Var',     data: [], borderColor: chartColors.packet_size_variance, tension: .4, pointRadius: 1 },
    { label: 'Time-Gap Var',     data: [], borderColor: chartColors.time_gap_variance,    tension: .4, pointRadius: 1 },
    { label: 'Time-Gap Mean',    data: [], borderColor: chartColors.time_gap_mean,        tension: .4, pointRadius: 1 },
    { label: 'Pkt-Size Mean',    data: [], borderColor: chartColors.packet_size_mean,     tension: .4, pointRadius: 1 },
  ],
};

let netChart;

function initChart() {
  const ctx = document.getElementById('netChart').getContext('2d');
  netChart = new Chart(ctx, {
    type: 'line',
    data: chartData,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: {
          labels: { color: '#64748b', boxWidth: 10, font: { size: 10 } },
        },
      },
      scales: {
        x: { ticks: { color: '#64748b', font: { size: 9 }, maxTicksLimit: 6 },
             grid: { color: 'rgba(255,255,255,.04)' } },
        y: { ticks: { color: '#64748b', font: { size: 9 } },
             grid: { color: 'rgba(255,255,255,.04)' } },
      },
    },
  });
}

// ─── Helpers ──────────────────────────────────────────
function el(id) { return document.getElementById(id); }

function fmt(v, dec = 2) {
  if (v === null || v === undefined) return '—';
  return parseFloat(v).toFixed(dec);
}

function showToast(msg, duration = 3500) {
  const t = el('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), duration);
}

function updateProgress(current, target, active) {
  const pct = target > 0 ? Math.min((current / target) * 100, 100) : 0;
  el('progressFill').style.width  = pct + '%';
  el('progressCount').textContent = `${current} / ${target}`;
  el('progressLabel').textContent = active
    ? '🔴 Capturing…'
    : (current >= target && target > 0 ? '✅ Capture complete' : '⏸ Paused');
  el('stopBtn').disabled = !active;

  // Retrieve window_time from the input if we don't have it globally
  // In a real app, we'd use the state variable.
  const w = el('windowSizeInput') ? el('windowSizeInput').value : '—';
  el('activeWindowLabel').textContent = w + 's';
}

// ─── Session Control ───────────────────────────────────
async function startSession() {
  const rawTarget = el('targetInput').value.trim();
  const n = parseInt(rawTarget, 10);
  if (!n || n <= 0) { el('sessionHint').textContent = '⚠ Please enter a valid positive target number.'; return; }

  const rawWindow = el('windowSizeInput') ? el('windowSizeInput').value.trim() : '2';
  const w = parseFloat(rawWindow);
  if (!w || w <= 0) { el('sessionHint').textContent = '⚠ Please enter a valid positive window time in seconds.'; return; }

  const res  = await fetch('/api/session/start', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ target: n, window_time: w }),
  });
  const data = await res.json();
  if (data.success) {
    sessionTarget  = n;
    sessionCurrent = 0;
    sessionActive  = true;
    showDashboard();
    showToast(`✅ Session started — capturing ${n} samples (Window: ${w}s)`);
  } else {
    el('sessionHint').textContent = '⚠ ' + data.message;
  }
}

async function stopSession() {
  await fetch('/api/session/stop', { method: 'POST' });
  sessionActive = false;
  updateProgress(sessionCurrent, sessionTarget, false);
  showToast('⏹ Capture stopped manually');
}

async function restartSession() {
  if (!confirm('Restart will clear ALL stored records and return to the setup screen. Continue?')) return;
  await fetch('/api/session/restart', { method: 'POST' });
  // UI reset handled by session_restart socket event
}

function resetUI() {
  // Reset local state
  sessionTarget  = 0;
  sessionCurrent = 0;
  sessionActive  = false;

  // Clear table
  el('historyBody').innerHTML = '';
  el('recordCount').textContent = '0 rows';

  // Clear chart
  if (netChart) {
    chartData.labels = [];
    chartData.datasets.forEach(d => d.data = []);
    netChart.update();
  }

  // Clear network param cells
  ['n_byte_rate','n_packet_rate','n_pkt_size_var',
   'n_tgap_var','n_tgap_mean','n_pkt_size_mean'].forEach(id => el(id).textContent = '—');

  // Return to hero / setup screen
  el('dashboardMain').classList.remove('visible');
  el('heroSection').style.display = '';
  el('targetInput').value = '';
  if (el('windowSizeInput')) el('windowSizeInput').value = '';
  el('sessionHint').textContent = '';

  showToast('↺ Session restarted — enter a new target to begin');
}

function showDashboard() {
  el('heroSection').style.display  = 'none';
  el('dashboardMain').classList.add('visible');
  updateProgress(sessionCurrent, sessionTarget, sessionActive);
  if (!netChart) initChart();
  loadHistory();
}

// ─── History loader ────────────────────────────────────
async function loadHistory() {
  const res  = await fetch('/api/network/history?limit=100');
  const rows = await res.json();
  rows.forEach(r => addTableRow(r));
  el('recordCount').textContent = `${rows.length} rows`;
}

// ─── Table ────────────────────────────────────────────
const MAX_TABLE_ROWS = 300;

function addTableRow(r, prepend = false) {
  const tbody = el('historyBody');
  const tr    = document.createElement('tr');
  tr.innerHTML = `
    <td>${r.id}</td>
    <td>${fmt(r.byte_rate)}</td>
    <td>${fmt(r.packet_rate)}</td>
    <td>${fmt(r.packet_size_variance)}</td>
    <td>${fmt(r.time_gap_variance)}</td>
    <td>${fmt(r.time_gap_mean)}</td>
    <td>${fmt(r.packet_size_mean)}</td>
    <td>${r.timestamp}</td>
  `;
  if (prepend) {
    tbody.insertBefore(tr, tbody.firstChild);
    if (tbody.rows.length > MAX_TABLE_ROWS) tbody.deleteRow(tbody.rows.length - 1);
  } else {
    tbody.appendChild(tr);
  }

  const cnt = parseInt(el('recordCount').textContent) || 0;
  el('recordCount').textContent = `${cnt + (prepend ? 1 : 0)} rows`;
}

// ─── Chart update ─────────────────────────────────────
function pushChartPoint(r) {
  const label = r.timestamp.split(' ')[1] || '';
  chartData.labels.push(label);
  chartData.datasets[0].data.push(r.byte_rate);
  chartData.datasets[1].data.push(r.packet_rate);
  chartData.datasets[2].data.push(r.packet_size_variance);
  chartData.datasets[3].data.push(r.time_gap_variance);
  chartData.datasets[4].data.push(r.time_gap_mean);
  chartData.datasets[5].data.push(r.packet_size_mean);

  if (chartData.labels.length > maxChartPoints) {
    chartData.labels.shift();
    chartData.datasets.forEach(d => d.data.shift());
  }
  netChart.update();
}

// ─── Socket.IO events ─────────────────────────────────
socket.on('connect', () => {
  el('connDot').classList.add('ok');
  el('connLabel').textContent = 'Connected';
});

socket.on('disconnect', () => {
  el('connDot').classList.remove('ok');
  el('connLabel').textContent = 'Disconnected';
});

socket.on('session_update', (d) => {
  sessionActive  = d.active;
  sessionTarget  = d.target;
  sessionCurrent = d.current;
  
  if (d.window_time !== undefined) {
    // Optionally update the input field if not currently typing, 
    // or just store it for local calculations if needed.
    if (el('windowSizeInput') && document.activeElement !== el('windowSizeInput')) {
        el('windowSizeInput').value = d.window_time;
    }
  }

  if (el('dashboardMain').classList.contains('visible')) {
    updateProgress(d.current, d.target, d.active);
  }
  if (d.message) showToast(d.message);
});

socket.on('session_restart', () => {
  resetUI();
});

// ── Live network parameter update ──
socket.on('network_data', (r) => {
  // Update live param cells
  el('n_byte_rate').textContent    = fmt(r.byte_rate);
  el('n_packet_rate').textContent  = fmt(r.packet_rate);
  el('n_pkt_size_var').textContent = fmt(r.packet_size_variance);
  el('n_tgap_var').textContent     = fmt(r.time_gap_variance);
  el('n_tgap_mean').textContent    = fmt(r.time_gap_mean);
  el('n_pkt_size_mean').textContent= fmt(r.packet_size_mean);

  el('netBadge').textContent = '● Live';

  // Prepend to table and chart ONLY if capturing
  if (sessionActive && el('dashboardMain').classList.contains('visible') && r.id !== undefined) {
    addTableRow(r, true);
    const cnt = el('historyBody').rows.length;
    el('recordCount').textContent = `${cnt} rows`;
    if (netChart) pushChartPoint(r);
    
    sessionCurrent++;
    updateProgress(sessionCurrent, sessionTarget, sessionActive);
  }
});

// ── Live sensor data (NOT stored) ──
socket.on('sensor_data', (d) => {
  // Ultrasonic
  if (d.ultrasonic) {
    el('ultrasonic_dist').textContent = fmt(d.ultrasonic.distance, 1);
  }

  // Vibration
  if (d.vibration) {
    el('vibration_val').textContent = fmt(d.vibration.value, 3);
  }

  // DHT-11
  if (d.temperature !== undefined) el('temperature').textContent = fmt(d.temperature, 1);
  if (d.humidity    !== undefined) el('humidity').textContent    = fmt(d.humidity, 1) + ' %';

  // IR sensor
  if (d.ir !== undefined) {
    const detected = !!d.ir.detected;
    el('irLabel').textContent = detected ? '🔴 Presence' : '⚪ No Presence';
  }
});

// ─── HTTP Polling (Vercel Compatibility Fallback) ──────
function startPolling() {
  console.log("Starting HTTP polling...");
  setInterval(async () => {
    try {
      const res = await fetch('/api/latest');
      const data = await res.json();
      
      // Update sensor data
      if (data.sensor && Object.keys(data.sensor).length > 0) {
        updateSensorUI(data.sensor);
      }
      
      // Update network data
      if (data.network && Object.keys(data.network).length > 0) {
        updateNetworkUI(data.network);
      }
      
      // Update session status
      if (data.session) {
        updateSessionUI(data.session);
      }
    } catch (err) {
      console.warn("Polling error:", err);
    }
  }, 2000);
}

function updateSensorUI(d) {
  // Ultrasonic
  if (d.ultrasonic) el('ultrasonic_dist').textContent = fmt(d.ultrasonic.distance, 1);
  // Vibration
  if (d.vibration) el('vibration_val').textContent = fmt(d.vibration.value, 3);
  // DHT-11
  if (d.temperature !== undefined) el('temperature').textContent = fmt(d.temperature, 1);
  if (d.humidity    !== undefined) el('humidity').textContent    = fmt(d.humidity, 1) + ' %';
  // IR sensor
  if (d.ir !== undefined) {
    const detected = !!d.ir.detected;
    el('irLabel').textContent = detected ? '🔴 Presence' : '⚪ No Presence';
  }
}

function updateNetworkUI(r) {
  // Update live param cells
  el('n_byte_rate').textContent    = fmt(r.byte_rate);
  el('n_packet_rate').textContent  = fmt(r.packet_rate);
  el('n_pkt_size_var').textContent = fmt(r.packet_size_variance);
  el('n_tgap_var').textContent     = fmt(r.time_gap_variance);
  el('n_tgap_mean').textContent    = fmt(r.time_gap_mean);
  el('n_pkt_size_mean').textContent= fmt(r.packet_size_mean);

  el('netBadge').textContent = '● Live';

  // Check if this record is already in the table to avoid duplicates
  // This is simple: just compare IDs or timestamps
  if (sessionActive && el('dashboardMain').classList.contains('visible') && r.id !== undefined) {
    const tableRows = el('historyBody').rows;
    let found = false;
    for (let i = 0; i < Math.min(tableRows.length, 5); i++) {
        if (tableRows[i].cells[0].textContent == r.id) {
            found = true;
            break;
        }
    }
    if (!found) {
        addTableRow(r, true);
        const cnt = el('historyBody').rows.length;
        el('recordCount').textContent = `${cnt} rows`;
        if (netChart) pushChartPoint(r);
        
        sessionCurrent++; // Note: this might be inaccurate with polling if we miss points
        updateProgress(sessionCurrent, sessionTarget, sessionActive);
    }
  }
}

function updateSessionUI(d) {
  sessionActive  = d.active;
  sessionTarget  = d.target;
  sessionCurrent = d.current;
  
  if (el('dashboardMain').classList.contains('visible')) {
    updateProgress(d.current, d.target, d.active);
  }
}

// ─── On load: check for existing session ─────────────
window.addEventListener('DOMContentLoaded', async () => {
  const res  = await fetch('/api/session/status');
  const data = await res.json();
  if (data.active) {
    sessionActive  = data.active;
    sessionTarget  = data.target;
    sessionCurrent = data.current;
    showDashboard();
  }
  
  // Start polling regardless of Socket.IO connection status
  startPolling();
});
