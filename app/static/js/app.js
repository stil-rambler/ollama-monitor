/* Ollama Monitor - frontend logic */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const fmtBytes = (b) => {
  if (b == null) return "—";
  const gb = b / 1024 ** 3;
  return gb >= 1 ? gb.toFixed(1) + " ГБ" : (b / 1024 ** 2).toFixed(0) + " МБ";
};
const fmtMs = (ms) => {
  if (ms == null) return "—";
  return ms >= 1000 ? (ms / 1000).toFixed(1) + " с" : ms.toFixed(0) + " мс";
};
const fmtNsSpeed = (count, ns) => {
  if (count == null || ns == null || ns <= 0) return "—";
  return (count / (ns / 1e9)).toFixed(1);
};

let reqPage = 0;
let charts = {};
let speedHistory = [];
let gpuHistory = [];
let vramHistory = [];

/* ---------- Tabs ---------- */
$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.remove("active"));
    $$(".page").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $("#page-" + btn.dataset.page).classList.add("active");
  });
});

/* ---------- WebSocket ---------- */
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/monitor`);
  ws.onmessage = (ev) => {
    if (ev.data === "__ping__") return;
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "ollama_status_updated") renderOllamaStatus(msg.data);
      if (msg.type === "request_completed" || msg.type === "request_failed") refreshDashboard();
      if (msg.type === "gpu_updated") renderGpuLive(msg.data);
    } catch (e) { /* ignore */ }
  };
  ws.onclose = () => setTimeout(connectWS, 3000);
}
connectWS();

function renderOllamaStatus(status) {
  const el = $("#ollama-status");
  el.className = "status-pill " + (status.status === "healthy" ? "healthy" : "error");
  el.textContent = status.status === "healthy" ? `ONLINE · v${status.version}` : "OFFLINE";
}

/* ---------- Dashboard ---------- */
async function refreshDashboard() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    renderOllamaStatus(data.ollama);
    $("#dash-active").textContent = data.active_requests;
    $("#dash-gpu").textContent = data.gpu.length
      ? data.gpu.map((g) => `${g.gpu_name} · ${g.gpu_load}%`).join("<br>")
      : "нет данных";
    if (data.gpu.length) {
      const g = data.gpu[0];
      $("#dash-gpu").textContent = `${g.gpu_name} · ${g.gpu_load}%`;
      pushHistory(gpuHistory, g.gpu_load);
      pushHistory(vramHistory, g.used_vram / 1024 ** 3);
    }
  } catch (e) { /* server not ready */ }

  try {
    const res = await fetch("/api/statistics");
    const s = await res.json();
    $("#dash-total").textContent = s.total_requests || 0;
    $("#dash-gen-speed").textContent = s.average_generation_speed
      ? s.average_generation_speed.toFixed(1) + " tok/s" : "—";
  } catch (e) { /* ignore */ }

  try {
    const res = await fetch("/api/dashboard/");
    const d = await res.json();
    if (d.average_generation_speed) $("#dash-gen-speed").textContent = d.average_generation_speed + " tok/s";
    if (d.average_prompt_processing_speed) $("#dash-prompt-speed").textContent = d.average_prompt_processing_speed + " tok/s";
    if (d.average_response_time) $("#dash-response-time").textContent = d.average_response_time + " с";
    pushHistory(speedHistory, d.average_generation_speed || 0);
  } catch (e) { /* ignore */ }

  loadRecentRequests();
  loadLoadedModels();
  renderCharts();
}

function pushHistory(arr, value) {
  arr.push(value);
  if (arr.length > 60) arr.shift();
}

function makeChart(id, label, color) {
  if (charts[id]) { charts[id].destroy(); }
  const ctx = $("#" + id);
  if (!ctx) return;
  charts[id] = new Chart(ctx, {
    type: "line",
    data: { labels: [], datasets: [{ label, data: [], borderColor: color, backgroundColor: color + "22", fill: true, tension: 0.3, pointRadius: 0 }] },
    options: {
      responsive: true, maintainAspectRatio: true, aspectRatio: 2.6,
      scales: { x: { ticks: { color: "#8b98a5", maxTicksLimit: 8 } }, y: { ticks: { color: "#8b98a5" }, beginAtZero: true } },
      plugins: { legend: { display: false } },
    },
  });
}

function renderCharts() {
  const t = new Date().toLocaleTimeString();
  if (charts["chart-speed"]) {
    charts["chart-speed"].data.labels.push(t);
    charts["chart-speed"].data.datasets[0].data.push(speedHistory[speedHistory.length - 1] || 0);
    if (charts["chart-speed"].data.labels.length > 60) { charts["chart-speed"].data.labels.shift(); charts["chart-speed"].data.datasets[0].data.shift(); }
    charts["chart-speed"].update();
  }
  if (charts["chart-gpu"]) {
    charts["chart-gpu"].data.labels.push(t);
    charts["chart-gpu"].data.datasets[0].data.push(gpuHistory[gpuHistory.length - 1] || 0);
    if (charts["chart-gpu"].data.labels.length > 60) { charts["chart-gpu"].data.labels.shift(); charts["chart-gpu"].data.datasets[0].data.shift(); }
    charts["chart-gpu"].update();
  }
  if (charts["chart-vram"]) {
    charts["chart-vram"].data.labels.push(t);
    charts["chart-vram"].data.datasets[0].data.push(vramHistory[vramHistory.length - 1] || 0);
    if (charts["chart-vram"].data.labels.length > 60) { charts["chart-vram"].data.labels.shift(); charts["chart-vram"].data.datasets[0].data.shift(); }
    charts["chart-vram"].update();
  }
}

async function loadRecentRequests() {
  try {
    const res = await fetch("/api/requests/?limit=8");
    const rows = await res.json();
    const tbody = $("#table-recent tbody");
    tbody.innerHTML = rows.map((r) => `
      <tr>
        <td>${new Date(r.created_at).toLocaleTimeString()}</td>
        <td>${r.client_name || r.client_ip || "—"}</td>
        <td>${r.model_name || "—"}</td>
        <td><span class="status-badge status-${r.execution_status}">${r.execution_status}</span></td>
      </tr>`).join("");
  } catch (e) { /* ignore */ }
}

async function loadLoadedModels() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    const tbody = $("#table-loaded-models tbody");
    tbody.innerHTML = "";
    // loaded models come from /api/ps via monitor; fallback to model list
    const res2 = await fetch("/api/models/?limit=50");
    const models = await res2.json();
    tbody.innerHTML = models.slice(0, 8).map((m) => `
      <tr><td>${m.name}</td><td>${fmtBytes(m.size)}</td><td>—</td><td>—</td></tr>`).join("");
  } catch (e) { /* ignore */ }
}

/* ---------- Requests ---------- */
async function loadRequests() {
  const params = new URLSearchParams({ limit: "25", offset: String(reqPage * 25) });
  const status = $("#req-status").value;
  if (status) params.set("execution_status", status);
  const model = $("#req-model").value;
  if (model) params.set("model_name", model);
  const search = $("#req-search").value.trim();
  if (search) params.set("client_name", search);

  try {
    const res = await fetch("/api/requests/?" + params);
    const rows = await res.json();
    const tbody = $("#table-requests tbody");
    tbody.innerHTML = rows.map((r) => `
      <tr>
        <td>${new Date(r.created_at).toLocaleString()}</td>
        <td>${r.client_name || "—"}</td>
        <td>${r.model_name || "—"}</td>
        <td>${r.endpoint}</td>
        <td>${r.prompt_eval_count ?? "—"}</td>
        <td>${r.eval_count ?? "—"}</td>
        <td>${r.generation_speed != null ? r.generation_speed.toFixed(1) : "—"}</td>
        <td>${fmtMs(r.total_duration)}</td>
        <td><span class="status-badge status-${r.execution_status}">${r.execution_status}</span></td>
        <td><button class="btn" onclick="showRequestDetail('${r.id}')">🔍</button></td>
      </tr>`).join("");
    $("#req-page-info").textContent = `Стр. ${reqPage + 1}`;
  } catch (e) { console.error(e); }
}

async function showRequestDetail(id) {
  try {
    const res = await fetch("/api/requests/" + id);
    const r = await res.json();
    $("#modal-request-body").textContent = JSON.stringify(r, null, 2);
    $("#modal-request").hidden = false;
  } catch (e) { console.error(e); }
}

function closeRequestModal() {
  $("#modal-request").hidden = true;
}

async function loadModelFilter() {
  try {
    const res = await fetch("/api/models/?limit=100");
    const models = await res.json();
    $("#req-model").innerHTML = '<option value="">Модель: все</option>' +
      models.map((m) => `<option>${m.name}</option>`).join("");
  } catch (e) { /* ignore */ }
}

/* ---------- Models ---------- */
async function loadModels() {
  try {
    const res = await fetch("/api/models/?limit=100");
    const rows = await res.json();
    const tbody = $("#table-models tbody");
    tbody.innerHTML = rows.map((m) => `
      <tr>
        <td>${m.name}</td>
        <td>${m.total_requests || 0}</td>
        <td>${m.average_generation_speed != null ? m.average_generation_speed.toFixed(1) : "—"}</td>
        <td>${m.average_prompt_processing_speed != null ? m.average_prompt_processing_speed.toFixed(1) : "—"}</td>
        <td>${fmtMs(m.average_response_time)}</td>
        <td>${m.total_input_tokens || 0}</td>
        <td>${m.total_output_tokens || 0}</td>
        <td>${m.total_errors || 0}</td>
      </tr>`).join("");
    $("#cmp-model-a").innerHTML = rows.map((m) => `<option>${m.name}</option>`).join("");
    $("#cmp-model-b").innerHTML = rows.map((m) => `<option>${m.name}</option>`).join("");
  } catch (e) { /* ignore */ }
}

async function compareModels() {
  const a = $("#cmp-model-a").value, b = $("#cmp-model-b").value;
  if (!a || !b) return;
  const res = await fetch(`/api/models/${encodeURIComponent(a)}/comparisons?comparison_model=${encodeURIComponent(b)}`);
  const d = await res.json();
  const s1 = d.model1.statistics, s2 = d.model2.statistics;
  $("#compare-result").innerHTML = `
    <h3>Сравнение моделей</h3>
    <table class="table">
      <thead><tr><th>Показатель</th><th>${a}</th><th>${b}</th></tr></thead>
      <tbody>
        <tr><td>Запросы</td><td>${s1.total_requests}</td><td>${s2.total_requests}</td></tr>
        <tr><td>Ср. генерация (tok/s)</td><td>${s1.average_generation_speed}</td><td>${s2.average_generation_speed}</td></tr>
        <tr><td>Ср. обработка (tok/s)</td><td>${s1.average_prompt_processing_speed}</td><td>${s2.average_prompt_processing_speed}</td></tr>
        <tr><td>Ср. время ответа (с)</td><td>${s1.average_response_time}</td><td>${s2.average_response_time}</td></tr>
        <tr><td>Ошибки</td><td>${s1.error_count}</td><td>${s2.error_count}</td></tr>
      </tbody>
    </table>`;
}

/* ---------- GPU ---------- */
async function loadGpu() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    renderGpuLive(data.gpu);
  } catch (e) { /* ignore */ }
}

function renderGpuLive(gpus) {
  const cards = $("#gpu-cards");
  cards.innerHTML = (gpus || []).map((g) => `
    <div class="card gpu-card">
      <div class="card-label">GPU ${g.gpu_index} · ${g.gpu_name}</div>
      <div class="card-value">${g.gpu_load}%</div>
      <div class="gpu-bar"><div style="width:${g.gpu_load}%"></div></div>
      <div style="margin-top:8px;font-size:12px;color:var(--muted)">
        VRAM: ${fmtBytes(g.used_vram)} / ${fmtBytes(g.total_vram)}<br>
        Температура: ${g.temperature ?? "Н/Д"}°C · Питание: ${g.power_usage ?? "Н/Д"} Вт
      </div>
    </div>`).join("") || '<div class="card">Нет данных о GPU</div>';

  if (gpus && gpus.length) {
    const g = gpus[0];
    const t = new Date().toLocaleTimeString();
    const update = (id, val) => {
      const ch = charts[id];
      if (!ch) return;
      ch.data.labels.push(t);
      ch.data.datasets[0].data.push(val);
      if (ch.data.labels.length > 60) { ch.data.labels.shift(); ch.data.datasets[0].data.shift(); }
      ch.update();
    };
    update("chart-gpu-util", g.gpu_load);
    update("chart-gpu-vram", +(g.used_vram / 1024 ** 3).toFixed(2));
    update("chart-gpu-temp", g.temperature || 0);
    update("chart-gpu-power", g.power_usage || 0);
  }
}

/* ---------- Clients ---------- */
async function loadClients() {
  try {
    const res = await fetch("/api/clients/?limit=100");
    const rows = await res.json();
    $("#table-clients tbody").innerHTML = rows.map((c) => `
      <tr>
        <td>${c.client_ip}</td>
        <td>${c.client_name || "—"}</td>
        <td title="${c.user_agent || ""}">${(c.user_agent || "—").slice(0, 40)}</td>
        <td>${c.total_requests || 0}</td>
        <td>${c.last_active ? new Date(c.last_active).toLocaleString() : "—"}</td>
        <td>${(c.used_models || []).join(", ") || "—"}</td>
      </tr>`).join("");
  } catch (e) { /* ignore */ }
}

/* ---------- Logs ---------- */
async function loadLogs() {
  try {
    const level = $("#log-level").value;
    const url = "/api/logs?limit=200" + (level ? "&level=" + encodeURIComponent(level) : "");
    const res = await fetch(url);
    const logs = await res.json();
    $("#log-list").innerHTML = (logs.length
      ? logs.map((l) => `<div class="log-entry ${l.level}"><span class="ts">${l.timestamp}</span><span>[${l.source}]</span><span>${l.message}</span></div>`).join("")
      : '<div class="log-entry">Нет записей в буфере</div>');
  } catch (e) { $("#log-list").innerHTML = '<div class="log-entry ERROR">Не удалось загрузить логи</div>'; }
}

/* ---------- Settings ---------- */
async function loadSettings() {
  try {
    const res = await fetch("/api/config");
    const cfg = await res.json();
    $("#settings-config").textContent = Object.entries(cfg)
      .map(([k, v]) => `${k} = ${v}`)
      .join("\n");
  } catch (e) { $("#settings-config").textContent = "Не удалось загрузить настройки"; }
}

/* ---------- Event wiring ---------- */
$("#btn-refresh-req").addEventListener("click", () => { reqPage = 0; loadRequests(); });
$("#req-search").addEventListener("input", debounce(() => { reqPage = 0; loadRequests(); }, 400));
$("#req-status").addEventListener("change", () => { reqPage = 0; loadRequests(); });
$("#req-model").addEventListener("change", () => { reqPage = 0; loadRequests(); });
$("#req-prev").addEventListener("click", () => { if (reqPage > 0) { reqPage--; loadRequests(); } });
$("#req-next").addEventListener("click", () => { reqPage++; loadRequests(); });
$("#btn-compare").addEventListener("click", compareModels);
$("#btn-refresh-logs").addEventListener("click", loadLogs);
$("#log-level").addEventListener("change", loadLogs);

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/* ---------- Init ---------- */
window.addEventListener("DOMContentLoaded", () => {
  makeChart("chart-speed", "Скорость генерации", "#38bdf8");
  makeChart("chart-gpu", "Загрузка GPU", "#34d399");
  makeChart("chart-vram", "VRAM, ГБ", "#fbbf24");
  makeChart("chart-gpu-util", "GPU Utilization", "#34d399");
  makeChart("chart-gpu-vram", "VRAM, ГБ", "#38bdf8");
  makeChart("chart-gpu-temp", "Температура", "#f87171");
  makeChart("chart-gpu-power", "Питание", "#fbbf24");
  makeChart("chart-requests", "Запросы", "#38bdf8");

  refreshDashboard();
  loadRequests();
  loadModelFilter();
  loadModels();
  loadClients();
  loadLogs();
  loadSettings();
  loadGpu();

  setInterval(refreshDashboard, 5000);
  setInterval(loadRequests, 15000);
  setInterval(loadModels, 30000);
  setInterval(loadClients, 30000);
  setInterval(loadGpu, 5000);
});
