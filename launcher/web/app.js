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

async function refreshApps() {
  const res = await fetch("/api/apps");
  apps = await res.json();
  if (!inSettings) renderGrid();
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

function renderGrid() {
  gridView.innerHTML = "";
  for (const app of apps) {
    const panel = document.createElement("div");
    panel.className = "panel" + (app.running ? " running" : "");
    panel.innerHTML = `
      <div class="well"><img src="/assets/icons/${app.icon}.svg" alt=""></div>
      <div class="name">${app.name}</div>
      <div class="note">${app.note}</div>
    `;
    panel.addEventListener("click", () => launchApp(app.name, panel));
    gridView.appendChild(panel);
  }
}

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
