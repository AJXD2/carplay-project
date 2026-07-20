const gridView = document.getElementById("grid-view");
const settingsView = document.getElementById("settings-view");
const settingsBtn = document.getElementById("settings-btn");
const backBtn = document.getElementById("back-btn");
const datetimeEl = document.getElementById("datetime");
const volFill = document.getElementById("vol-fill");
const volTrack = document.getElementById("vol-track");
const volDown = document.getElementById("vol-down");
const volUp = document.getElementById("vol-up");
const dimBtn = document.getElementById("dim-btn");
const dimOverlay = document.getElementById("dim-overlay");
const toggle = document.getElementById("auto-launch-toggle");
const appPicker = document.getElementById("app-picker");
const saveBtn = document.getElementById("save-btn");
const toast = document.getElementById("toast");
const panelsEl = document.getElementById("panels");
const pagerEl = document.getElementById("pager");
const pgPrev = document.getElementById("pg-prev");
const pgNext = document.getElementById("pg-next");
const pgDots = document.getElementById("pg-dots");
const TILES_PER_PAGE = 4;

let apps = [];
let config = { default_app: null, auto_launch: false };
let pending = { default_app: null, auto_launch: false };
let inSettings = false;
let launching = false;

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
function ordinal(n) {
  if (n > 3 && n < 21) return n + "th";
  switch (n % 10) { case 1: return n + "st"; case 2: return n + "nd"; case 3: return n + "rd"; default: return n + "th"; }
}
function tick() {
  const now = new Date();
  const h24 = now.getHours();
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
  const ampm = h24 < 12 ? "AM" : "PM";
  const mins = String(now.getMinutes()).padStart(2, "0");
  datetimeEl.textContent = `${MONTHS[now.getMonth()]} ${ordinal(now.getDate())} ${now.getFullYear()} ${h12}:${mins} ${ampm}`;
}
tick();
setInterval(tick, 5000);

let gridSig = null;

async function refreshApps() {
  const res = await fetch("/api/apps");
  apps = await res.json();
  if (inSettings) return;
  // Only rebuild the grid when the set of apps changes; otherwise just
  // update the running-state borders in place, so a horizontal scroll
  // position isn't reset out from under the user every few seconds.
  const sig = apps.map((a) => a.name).join(",");
  if (sig !== gridSig) {
    gridSig = sig;
    renderGrid();
  } else {
    updateRunning();
  }
}

function updateRunning() {
  for (const app of apps) {
    const t = tiles.find((x) => x.name === app.name);
    if (t) t.running = app.running;
    const panel = panelsEl.querySelector(`.panel[data-name="${CSS.escape(app.name)}"]`);
    if (panel) panel.classList.toggle("running", app.running);
  }
}

async function refreshVolume() {
  const res = await fetch("/api/volume");
  const data = await res.json();
  volFill.style.height = Math.max(0, data.percent) + "%";
}

async function refreshDim() {
  const res = await fetch("/api/dim");
  const data = await res.json();
  setDimUI(data.dimmed);
}

function setDimUI(dimmed) {
  dimBtn.classList.toggle("active", dimmed);
  dimOverlay.classList.toggle("active", dimmed);
}

dimBtn.addEventListener("click", async () => {
  const nowActive = !dimBtn.classList.contains("active");
  setDimUI(nowActive); // immediate feedback while the backlight write happens
  const res = await fetch("/api/dim", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dimmed: nowActive }),
  });
  const data = await res.json();
  setDimUI(data.dimmed);
});

// The grid is paginated: 4 tiles per page, prev/next swap which 4 render.
// Explicit page rendering (rather than a horizontal scroll) avoids overlap
// math when the tile count isn't a multiple of 4.
let pageIdx = 0;
let tiles = [];

function buildTiles() {
  tiles = apps.map((a) => ({
    name: a.name, icon: a.icon, note: a.note, running: a.running,
    onClick: (panel) => launchApp(a.name, panel),
  }));
  // Devices is an in-page view (like Settings), not a spawned process, so
  // it's a synthetic tile rather than an entry in the backend APPS list.
  tiles.push({
    name: "Devices", icon: "devices", note: "manage paired phones",
    running: false, onClick: () => openDevices(),
  });
}

function pageCount() {
  return Math.max(1, Math.ceil(tiles.length / TILES_PER_PAGE));
}

function renderGrid() {
  buildTiles();
  renderPage();
}

function renderPage() {
  pageIdx = Math.max(0, Math.min(pageCount() - 1, pageIdx));
  panelsEl.innerHTML = "";
  const start = pageIdx * TILES_PER_PAGE;
  for (const t of tiles.slice(start, start + TILES_PER_PAGE)) {
    const panel = document.createElement("div");
    panel.className = "panel" + (t.running ? " running" : "");
    panel.dataset.name = t.name;
    panel.innerHTML = `
      <div class="well"><img src="/assets/icons/${t.icon}.svg" alt=""></div>
      <div class="name">${t.name}</div>
      <div class="note">${t.note}</div>
    `;
    panel.addEventListener("click", () => t.onClick(panel));
    panelsEl.appendChild(panel);
  }
  buildPager();
}

function buildPager() {
  const n = pageCount();
  pagerEl.classList.toggle("hidden", n <= 1);
  pgDots.innerHTML = "";
  for (let i = 0; i < n; i++) {
    const dot = document.createElement("div");
    dot.className = "dot" + (i === pageIdx ? " active" : "");
    dot.addEventListener("click", () => { pageIdx = i; renderPage(); });
    pgDots.appendChild(dot);
  }
  pgPrev.disabled = pageIdx <= 0;
  pgNext.disabled = pageIdx >= n - 1;
}

pgPrev.addEventListener("click", () => { pageIdx -= 1; renderPage(); });
pgNext.addEventListener("click", () => { pageIdx += 1; renderPage(); });

async function launchApp(name, panel) {
  if (launching) return;
  launching = true;
  panel.classList.add("launching");
  const noteEl = panel.querySelector(".note");
  const prevNote = noteEl.textContent;
  noteEl.textContent = "Launching...";
  try {
    await fetch("/api/launch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  } finally {
    launching = false;
    noteEl.textContent = prevNote;
    panel.classList.remove("launching");
    refreshApps();
  }
}

function openSettings() {
  inSettings = true;
  pending = { default_app: config.default_app, auto_launch: config.auto_launch };
  document.querySelector(".sidebar").classList.add("hidden");
  gridView.classList.add("hidden");
  settingsView.classList.remove("hidden");
  renderSettings();
}

function closeSettings() {
  inSettings = false;
  settingsView.classList.add("hidden");
  document.querySelector(".sidebar").classList.remove("hidden");
  gridView.classList.remove("hidden");
}

settingsBtn.addEventListener("click", openSettings);
backBtn.addEventListener("click", closeSettings);

function renderSettings() {
  toggle.setAttribute("aria-checked", pending.auto_launch ? "true" : "false");

  appPicker.innerHTML = "";
  for (const app of apps) {
    const row = document.createElement("div");
    row.className = "picker-row" + (pending.default_app === app.name ? " selected" : "");
    row.innerHTML = `<img src="/assets/icons/${app.icon}.svg" alt=""><span class="name">${app.name}</span>`;
    row.addEventListener("click", () => {
      pending.default_app = app.name;
      renderSettings();
    });
    appPicker.appendChild(row);
  }
}

toggle.addEventListener("click", () => {
  pending.auto_launch = !pending.auto_launch;
  renderSettings();
});

saveBtn.addEventListener("click", async () => {
  const res = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(pending),
  });
  const data = await res.json();
  if (data.ok) config = { ...pending };
  toast.textContent = data.ok ? "Saved" : "Save failed";
  toast.className = "toast " + (data.ok ? "ok" : "fail");
  setTimeout(() => toast.classList.add("hidden"), 1500);
});

// -- Devices view: manage the dongle's paired phones over its web panel.
// Opening it makes the backend borrow wlan0 to join the dongle's AP (shown
// as a "Connecting" skeleton); leaving it hands wlan0 back.
const devicesView = document.getElementById("devices-view");
const devicesBackBtn = document.getElementById("devices-back-btn");
const devicesContent = document.getElementById("devices-content");
const devMonitor = document.getElementById("dev-monitor");

let inDevices = false;
let devicesPoll = null;
let confirmOpen = false;      // a per-row "Remove?" confirm is showing
let lastDevSig = null;        // skip list rebuilds when nothing changed
let busy = false;             // a remove/forget request is in flight

function openDevices() {
  inDevices = true;
  lastDevSig = null;
  document.querySelector(".sidebar").classList.add("hidden");
  gridView.classList.add("hidden");
  devicesView.classList.remove("hidden");
  renderConnecting();
  loadDevices();
  devicesPoll = setInterval(loadDevices, 2500);
}

function closeDevices() {
  inDevices = false;
  if (devicesPoll) { clearInterval(devicesPoll); devicesPoll = null; }
  devicesView.classList.add("hidden");
  document.querySelector(".sidebar").classList.remove("hidden");
  gridView.classList.remove("hidden");
  devMonitor.textContent = "";
  // best-effort: give wlan0 back to the home network
  fetch("/api/devices/disconnect", { method: "POST" }).catch(() => {});
}

devicesBackBtn.addEventListener("click", closeDevices);

async function loadDevices() {
  if (!inDevices || busy) return;
  let d;
  try {
    const res = await fetch("/api/devices");
    d = await res.json();
  } catch (e) {
    if (inDevices) renderError("launcher backend unreachable");
    return;
  }
  if (!inDevices) return;
  if (d.state === "connecting" || d.state === "idle") {
    renderConnecting();
  } else if (d.state === "error") {
    renderError(d.error || "could not reach the dongle");
  } else if (d.state === "ready") {
    renderReady(d.devices || [], d.monitor || {});
  }
}

function renderConnecting() {
  devMonitor.textContent = "";
  lastDevSig = null;
  devicesContent.innerHTML = `
    <div class="dev-hint">Connecting to dongle Wi-Fi...</div>
    <div class="dev-skel"></div><div class="dev-skel"></div><div class="dev-skel"></div>`;
}

function renderError(msg) {
  devMonitor.textContent = "";
  lastDevSig = null;
  devicesContent.innerHTML = `
    <div class="dev-error">${escapeHtml(msg)}</div>
    <button class="dev-btn retry" id="dev-retry">Retry</button>`;
  document.getElementById("dev-retry").addEventListener("click", () => {
    renderConnecting();
    loadDevices();
  });
}

function renderReady(devices, monitor) {
  // status strip in the header
  if (typeof monitor.CpuTemp === "number") {
    const t = Math.round(monitor.CpuTemp);
    const cpu = Math.round(monitor.CpuRate ?? 0);
    const mem = Math.round(monitor.MemRate ?? 0);
    devMonitor.textContent = `dongle ${t}°C · cpu ${cpu}% · mem ${mem}%`;
  }
  // don't rebuild the list mid-confirm, or if the device set is unchanged
  const sig = devices.map((x) => x.id).join(",");
  if (confirmOpen || sig === lastDevSig) return;
  lastDevSig = sig;

  if (devices.length === 0) {
    devicesContent.innerHTML = `<div class="dev-hint">No paired devices.</div>`;
    return;
  }
  devicesContent.innerHTML = "";
  for (const dev of devices) {
    const row = document.createElement("div");
    row.className = "dev-row";
    row.innerHTML = `
      <img class="dev-ico" src="/assets/icons/devices.svg" alt="">
      <div class="dev-meta">
        <div class="dev-name">${escapeHtml(dev.name || "Unknown")}</div>
        <div class="dev-mac">${escapeHtml(dev.id)}</div>
      </div>
      <div class="dev-actions"></div>`;
    buildRemoveButton(row.querySelector(".dev-actions"), dev);
    devicesContent.appendChild(row);
  }
  const forget = document.createElement("button");
  forget.className = "dev-btn forget-all";
  forget.textContent = "Forget all devices";
  forget.addEventListener("click", () => confirmForgetAll(devices));
  devicesContent.appendChild(forget);
}

function buildRemoveButton(container, dev) {
  container.innerHTML = "";
  const btn = document.createElement("button");
  btn.className = "dev-btn remove";
  btn.textContent = "Remove";
  btn.addEventListener("click", () => {
    confirmOpen = true;
    container.innerHTML = "";
    const yes = document.createElement("button");
    yes.className = "dev-btn confirm-yes";
    yes.textContent = "Remove?";
    yes.addEventListener("click", () => removeDevice(dev, container));
    const no = document.createElement("button");
    no.className = "dev-btn confirm-no";
    no.textContent = "Cancel";
    no.addEventListener("click", () => { confirmOpen = false; buildRemoveButton(container, dev); });
    container.appendChild(yes);
    container.appendChild(no);
  });
  container.appendChild(btn);
}

async function removeDevice(dev, container) {
  busy = true;
  container.innerHTML = `<span class="dev-working">Removing...</span>`;
  try {
    const res = await fetch("/api/devices/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mac: dev.id }),
    });
    const data = await res.json();
    if (!data.ok) container.innerHTML = `<span class="dev-working fail">Failed</span>`;
  } catch (e) {
    container.innerHTML = `<span class="dev-working fail">Failed</span>`;
  } finally {
    busy = false;
    confirmOpen = false;
    lastDevSig = null; // force a fresh list on next poll
    loadDevices();
  }
}

async function confirmForgetAll(devices) {
  const forget = devicesContent.querySelector(".forget-all");
  if (!forget || forget.dataset.armed !== "1") {
    if (forget) { forget.dataset.armed = "1"; forget.textContent = "Tap again to forget ALL"; }
    setTimeout(() => { if (forget) { forget.dataset.armed = "0"; forget.textContent = "Forget all devices"; } }, 3000);
    return;
  }
  busy = true;
  confirmOpen = false;
  devicesContent.innerHTML = `<div class="dev-hint">Removing ${devices.length} devices...</div>`;
  for (const dev of devices) {
    try {
      await fetch("/api/devices/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mac: dev.id }),
      });
    } catch (e) { /* keep going; the final reload shows the real state */ }
  }
  busy = false;
  lastDevSig = null;
  loadDevices();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

volDown.addEventListener("click", async () => {
  const res = await fetch("/api/volume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ delta: -5 }),
  });
  const data = await res.json();
  volFill.style.height = Math.max(0, data.percent) + "%";
});

volUp.addEventListener("click", async () => {
  const res = await fetch("/api/volume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ delta: 5 }),
  });
  const data = await res.json();
  volFill.style.height = Math.max(0, data.percent) + "%";
});

// Drag-to-set on the track itself. Pointer events cover touch and mouse
// alike (Chromium's pointer-event handling is exactly the reliable stack
// this whole rewrite exists to use), and pointer capture keeps the drag
// tracking even if a finger slides outside the track's narrow width.
let draggingVolume = false;
let lastSentVolume = null;

function pctFromPointer(e) {
  const rect = volTrack.getBoundingClientRect();
  const pct = ((rect.bottom - e.clientY) / rect.height) * 100;
  return Math.max(0, Math.min(100, Math.round(pct)));
}

async function sendVolumePercent(pct) {
  if (pct === lastSentVolume) return;
  lastSentVolume = pct;
  const res = await fetch("/api/volume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ percent: pct }),
  });
  const data = await res.json();
  volFill.style.height = Math.max(0, data.percent) + "%";
}

volTrack.addEventListener("pointerdown", (e) => {
  draggingVolume = true;
  volTrack.setPointerCapture(e.pointerId);
  const pct = pctFromPointer(e);
  volFill.style.height = pct + "%"; // immediate visual feedback
  sendVolumePercent(pct);
});
volTrack.addEventListener("pointermove", (e) => {
  if (!draggingVolume) return;
  const pct = pctFromPointer(e);
  volFill.style.height = pct + "%";
  sendVolumePercent(pct);
});
volTrack.addEventListener("pointerup", (e) => {
  draggingVolume = false;
  volTrack.releasePointerCapture(e.pointerId);
});
volTrack.addEventListener("pointercancel", () => {
  draggingVolume = false;
});

async function init() {
  const cfgRes = await fetch("/api/config");
  config = await cfgRes.json();
  await refreshApps();
  await refreshVolume();
  await refreshDim();
}

init();
setInterval(refreshApps, 3000);
setInterval(refreshVolume, 4000);
