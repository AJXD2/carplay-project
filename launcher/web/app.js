// Kiosk frontend. Home is the CarPlay hero + a grid of tiles; everything
// that isn't a separate program (Info, Trip Calc, Logs, Phones, Settings) is
// an in-page view sharing the status strip, switched by showView().

const $ = (id) => document.getElementById(id);

async function getJSON(url) {
  const res = await fetch(url);
  return res.json();
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return res.json();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// -- clock -------------------------------------------------------------------
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// The Pi has no real-time clock: until it syncs over the network, the time
// is months stale. Show dashes rather than a confidently wrong clock.
let timeSynced = true;

function tick() {
  if (!timeSynced) {
    $("clock-time").textContent = "--:--";
    $("clock-ampm").textContent = "";
    $("clock-date").textContent = "Clock not set";
    $("strip-clock").textContent = "";
    return;
  }
  const now = new Date();
  const h = now.getHours() % 12 || 12;
  const m = String(now.getMinutes()).padStart(2, "0");
  const ampm = now.getHours() < 12 ? "AM" : "PM";
  $("clock-time").textContent = `${h}:${m}`;
  $("clock-ampm").textContent = ampm;
  $("clock-date").textContent = `${DAYS[now.getDay()]}, ${MONTHS[now.getMonth()]} ${now.getDate()}`;
  $("strip-clock").textContent = `${h}:${m} ${ampm}`;
}
tick();
setInterval(tick, 5000);

// -- home: status poll, tiles, launching -----------------------------------
let status = { apps: [], dongle_usb: true };
let launchingApp = null;

function renderStatus() {
  const running = Object.fromEntries(status.apps.map((a) => [a.name, a.running]));
  document.querySelectorAll(".tile[data-app]").forEach((tile) => {
    const name = tile.dataset.app;
    tile.classList.toggle("running", !!running[name]);
    tile.classList.toggle("launching", launchingApp === name);
  });

  const hero = document.querySelector(".hero");
  const heroState = $("hero-state");
  hero.classList.remove("warn");
  if (launchingApp === "CarPlay") heroState.textContent = "Starting…";
  else if (running.CarPlay) heroState.textContent = "Running";
  else if (!status.dongle_usb) {
    heroState.textContent = "Dongle not detected";
    hero.classList.add("warn");
  } else heroState.textContent = "Tap to start";

  const flappyState = document.querySelector('.tile[data-app="Flappy Bird"] .state');
  flappyState.textContent = launchingApp === "Flappy Bird" ? "Starting…" : running["Flappy Bird"] ? "Running" : "";

  const chip = $("dongle-chip");
  chip.hidden = status.dongle_usb;
  chip.textContent = "Dongle not detected";
}

async function refreshStatus() {
  try {
    status = await getJSON("/api/status");
  } catch (e) {
    return;
  }
  if (timeSynced !== status.time_synced) { timeSynced = status.time_synced; tick(); }
  renderStatus();
  if (!draggingVolume) setVolumeUI(status.volume);
  setDimUI(status.dimmed);
}

async function launchApp(name) {
  if (launchingApp) return;
  launchingApp = name;
  renderStatus();
  try {
    await postJSON("/api/launch", { name });
  } catch (e) {
    /* the next status poll shows the real state */
  } finally {
    launchingApp = null;
    refreshStatus();
  }
}

document.querySelectorAll(".tile").forEach((tile) => {
  tile.addEventListener("click", () => {
    if (tile.dataset.app) launchApp(tile.dataset.app);
    else if (tile.dataset.view) showView(tile.dataset.view);
  });
});

// -- night dim ---------------------------------------------------------------
function setDimUI(dimmed) {
  $("dim-btn").setAttribute("aria-pressed", dimmed ? "true" : "false");
  $("dim-overlay").classList.toggle("active", dimmed);
  document.body.classList.toggle("night", dimmed);
}

$("dim-btn").addEventListener("click", async () => {
  const next = $("dim-btn").getAttribute("aria-pressed") !== "true";
  setDimUI(next); // immediate feedback while the backlight write happens
  try {
    const data = await postJSON("/api/dim", { dimmed: next });
    setDimUI(data.dimmed);
  } catch (e) { /* keep the optimistic state */ }
});

// -- volume ------------------------------------------------------------------
// Drag anywhere on the (tall, invisible) track. Pointer events cover touch
// and mouse alike, and pointer capture keeps tracking if the finger slides
// off the bar.
const volTrack = $("vol-track");
let draggingVolume = false;
let lastSentVolume = null;
let volumeInFlight = false;
let queuedVolume = null;

function setVolumeUI(pct) {
  if (pct < 0) return;
  $("vol-fill").style.width = pct + "%";
  $("vol-value").textContent = pct;
}

async function sendVolume(body) {
  const data = await postJSON("/api/volume", body);
  if (!draggingVolume) setVolumeUI(data.percent);
  return data.percent;
}

// Only one request in flight while dragging; the latest position wins.
async function sendVolumePercent(pct) {
  if (pct === lastSentVolume) return;
  lastSentVolume = pct;
  if (volumeInFlight) { queuedVolume = pct; return; }
  volumeInFlight = true;
  try {
    await sendVolume({ percent: pct });
  } finally {
    volumeInFlight = false;
    if (queuedVolume !== null) {
      const q = queuedVolume;
      queuedVolume = null;
      lastSentVolume = null;
      sendVolumePercent(q);
    }
  }
}

function pctFromPointer(e) {
  const rect = volTrack.getBoundingClientRect();
  return Math.max(0, Math.min(100, Math.round(((e.clientX - rect.left) / rect.width) * 100)));
}

volTrack.addEventListener("pointerdown", (e) => {
  draggingVolume = true;
  volTrack.setPointerCapture(e.pointerId);
  const pct = pctFromPointer(e);
  setVolumeUI(pct);
  sendVolumePercent(pct);
});
volTrack.addEventListener("pointermove", (e) => {
  if (!draggingVolume) return;
  const pct = pctFromPointer(e);
  setVolumeUI(pct);
  sendVolumePercent(pct);
});
const endDrag = () => { draggingVolume = false; };
volTrack.addEventListener("pointerup", endDrag);
volTrack.addEventListener("pointercancel", endDrag);

$("vol-down").addEventListener("click", () => sendVolume({ delta: -5 }));
$("vol-up").addEventListener("click", () => sendVolume({ delta: 5 }));

// -- view router ------------------------------------------------------------
const VIEWS = {
  info: { title: "Info", el: "info-view", open: openInfo, close: closeInfo },
  trip: { title: "Trip Calc", el: "trip-view", open: openTrip, close: () => {} },
  logs: { title: "Logs", el: "logs-view", open: openLogs, close: closeLogs },
  devices: { title: "Paired phones", el: "devices-view", open: openDevices, close: closeDevices },
  settings: { title: "Settings", el: "settings-view", open: openSettings, close: () => {} },
};
let currentView = null;

// Replays an entrance animation on an element (removing and re-adding the
// class alone wouldn't restart it).
function animateIn(el, cls) {
  el.classList.remove("enter-forward", "enter-back");
  void el.offsetWidth;
  el.classList.add(cls);
}

function showView(name) {
  const v = VIEWS[name];
  if (!v) return;
  currentView = name;
  animateIn($(v.el), "enter-forward");
  animateIn(document.querySelector(".strip-view"), "enter-forward");
  $("home-view").classList.add("hidden");
  $("volume-bar").classList.add("hidden");
  document.querySelector(".strip-home").classList.add("hidden");
  document.querySelector(".strip-view").classList.remove("hidden");
  $("strip-clock").classList.remove("hidden");
  $("dongle-chip").classList.add("hidden");
  $("view-title").textContent = v.title;
  $(v.el).classList.remove("hidden");
  v.open();
}

function showHome() {
  if (currentView) {
    VIEWS[currentView].close();
    $(VIEWS[currentView].el).classList.add("hidden");
  }
  currentView = null;
  animateIn($("home-view"), "enter-back");
  animateIn($("volume-bar"), "enter-back");
  animateIn(document.querySelector(".strip-home"), "enter-back");
  $("home-view").classList.remove("hidden");
  $("volume-bar").classList.remove("hidden");
  document.querySelector(".strip-home").classList.remove("hidden");
  document.querySelector(".strip-view").classList.add("hidden");
  $("strip-clock").classList.add("hidden");
  $("dongle-chip").classList.remove("hidden");
  refreshStatus();
}

$("back-btn").addEventListener("click", showHome);

// -- info view ---------------------------------------------------------------
let infoTimer = null;
let micTimer = null;
let micActive = false;

function fmtBytes(n) {
  if (n == null) return "--";
  const gb = n / 1024 ** 3;
  return gb >= 10 ? `${gb.toFixed(0)} GB` : gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(n / 1024 ** 2)} MB`;
}

function fmtUptime(s) {
  if (s == null) return "--";
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

function setGauge(id, { value, sub, level }) {
  const g = $(id);
  g.classList.toggle("warn", level === "warn");
  g.classList.toggle("bad", level === "bad");
  const valueEl = g.querySelector(".g-value");
  const num = valueEl.querySelector(".num");
  if (num) num.textContent = value;
  else valueEl.textContent = value;
  g.querySelector(".g-sub").textContent = sub || "";
}

function renderInfo(d) {
  const t = d.temp_c;
  setGauge("g-temp", {
    value: t == null ? "--" : t.toFixed(1),
    sub: t == null ? "" : t >= 80 ? "Too hot, throttling likely" : t >= 70 ? "Running warm" : "Normal",
    level: t >= 80 ? "bad" : t >= 70 ? "warn" : null,
  });
  const th = d.throttle || {};
  const now = (th.flags || []).find((f) => f.endsWith("now"));
  setGauge("g-power", {
    value: th.ok == null ? "Unknown" : now ? "Low voltage" : "Good",
    sub: th.ok == null ? "vcgencmd unavailable" : now || (th.flags.length ? th.flags[0] : "No undervoltage since boot"),
    level: now ? "bad" : th.flags && th.flags.length ? "warn" : null,
  });
  setGauge("g-dongle", {
    value: d.dongle_usb ? "Connected" : "Not detected",
    sub: d.dongle_usb ? (d.carplay_running ? "CarPlay running" : "CarPlay not running") : "Check the USB cable",
    level: d.dongle_usb ? null : "bad",
  });

  const wifi = d.wlan0 ? (d.wifi_ssid ? `${d.wlan0} on ${d.wifi_ssid}` : d.wlan0) : "Not connected";
  const facts = [
    ["Uptime", fmtUptime(d.uptime_s)],
    ["Load", d.load && d.load.length ? d.load.map((x) => x.toFixed(2)).join("  ") : "--"],
    ["Memory", d.mem ? `${fmtBytes(d.mem.used)} of ${fmtBytes(d.mem.total)}` : "--"],
    ["SD card", d.sd ? `${fmtBytes(d.sd.used)} of ${fmtBytes(d.sd.total)}` : "--"],
    ["Ethernet", d.eth0 || "Not connected"],
    ["Wi-Fi", wifi],
    ["Cleared on reboot", d.overlay ? fmtBytes(d.overlay.used) : "--"],
    ["Host", d.hostname],
  ];
  $("info-list").innerHTML = facts
    .map(([k, v]) => `<div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd></div>`)
    .join("");
}

async function pollInfo() {
  try { renderInfo(await getJSON("/api/info")); } catch (e) { /* keep last */ }
}

// -60 dBFS maps to an empty meter, 0 dBFS to full.
const dbToPct = (db) => Math.max(0, Math.min(100, ((db + 60) / 60) * 100));

async function pollMic() {
  if (!micActive) return;
  try {
    const m = await getJSON("/api/mic");
    if (m.ok) {
      $("mic-fill").style.width = dbToPct(m.rms_db) + "%";
      $("mic-peak").style.left = dbToPct(m.peak_db) + "%";
      $("mic-db").textContent = `${Math.round(m.peak_db)} dB`;
    } else {
      $("mic-fill").style.width = "0%";
      $("mic-db").textContent = "No input";
    }
  } catch (e) { /* ignore */ }
  if (micActive) micTimer = setTimeout(pollMic, 400);
}

function openInfo() {
  pollInfo();
  infoTimer = setInterval(pollInfo, 2000);
  micActive = true;
  pollMic();
}

function closeInfo() {
  clearInterval(infoTimer);
  clearTimeout(micTimer);
  micActive = false;
}

// -- trip calc ---------------------------------------------------------------
let trip = null;
let tripSaveTimer = null;

const fmt = (v, digits = 0) => v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

const COST_FIELDS = [
  { key: "distance_mi", label: "Distance", unit: "mi", step: 5, digits: 0, alt: (v) => `${fmt(v * 1.60934, 1)} km` },
  { key: "mpg", label: "Fuel economy", unit: "mpg", step: 1, digits: 0, alt: (v) => (v > 0 ? `${fmt(235.215 / v, 1)} L/100 km` : "") },
  { key: "gallons_price", label: "Fuel price", unit: "$/gal", step: 0.05, digits: 2, alt: (v) => `$${fmt(v / 3.78541, 2)} per liter` },
];

const CONVERT_FIELDS = [
  { key: "speed_mph", label: "Speed", unit: "mph", step: 5, digits: 0, alt: (v) => `${fmt(v * 1.60934, 0)} km/h` },
  { key: "distance_mi", label: "Distance", unit: "mi", step: 1, digits: 0, alt: (v) => `${fmt(v * 1.60934, 1)} km` },
  { key: "gallons_price", label: "Fuel price", unit: "$/gal", step: 0.05, digits: 2, alt: (v) => `$${fmt(v / 3.78541, 2)} per liter` },
  { key: "temp_f", label: "Temperature", unit: "°F", step: 1, digits: 0, signed: true, alt: (v) => `${fmt(((v - 32) * 5) / 9, 1)} °C` },
];

function buildSteppers(containerId, fields) {
  const box = $(containerId);
  box.innerHTML = "";
  for (const f of fields) {
    const row = document.createElement("div");
    row.className = "stepper";
    row.innerHTML = `
      <button class="icon-btn round" aria-label="Decrease ${f.label}"><svg><use href="#i-minus"/></svg></button>
      <div class="stepper-body">
        <span class="stepper-label">${f.label}</span>
        <span class="stepper-value"><span class="v"></span><span class="unit">${f.unit}</span></span>
        <span class="stepper-alt"></span>
      </div>
      <button class="icon-btn round" aria-label="Increase ${f.label}"><svg><use href="#i-plus"/></svg></button>`;
    const [minus, plus] = row.querySelectorAll("button");
    holdRepeat(minus, () => bump(f, -1));
    holdRepeat(plus, () => bump(f, 1));
    f.row = row;
    box.appendChild(row);
  }
}

// Press-and-hold repeats, accelerating, so big changes don't take 40 taps.
function holdRepeat(btn, fn) {
  let timer = null;
  let delay;
  const stop = () => { clearTimeout(timer); timer = null; };
  const loop = () => { fn(); delay = Math.max(50, delay * 0.8); timer = setTimeout(loop, delay); };
  btn.addEventListener("pointerdown", (e) => {
    btn.setPointerCapture(e.pointerId);
    fn();
    delay = 380;
    timer = setTimeout(loop, delay);
  });
  btn.addEventListener("pointerup", stop);
  btn.addEventListener("pointercancel", stop);
  btn.addEventListener("lostpointercapture", stop);
}

function bump(f, dir) {
  let v = Math.round((trip[f.key] + dir * f.step) * 100) / 100;
  if (!f.signed) v = Math.max(0, v);
  trip[f.key] = v;
  renderTrip();
  clearTimeout(tripSaveTimer);
  tripSaveTimer = setTimeout(() => postJSON("/api/trip", trip).catch(() => {}), 800);
}

function renderTrip() {
  for (const f of [...COST_FIELDS, ...CONVERT_FIELDS]) {
    if (!f.row) continue;
    const v = trip[f.key];
    f.row.querySelector(".v").textContent = fmt(v, f.digits);
    f.row.querySelector(".stepper-alt").textContent = f.alt(v);
  }
  const gallons = trip.mpg > 0 ? trip.distance_mi / trip.mpg : 0;
  $("cost-total").textContent = `$${fmt(gallons * trip.gallons_price, 2)}`;
  $("cost-gallons").textContent = trip.mpg > 0
    ? `${fmt(gallons, 2)} gallons of fuel for ${fmt(trip.distance_mi)} miles`
    : "Set fuel economy to estimate";
}

async function openTrip() {
  if (!trip) {
    buildSteppers("cost-steppers", COST_FIELDS);
    buildSteppers("convert-steppers", CONVERT_FIELDS);
  }
  try { trip = await getJSON("/api/trip"); } catch (e) { return; }
  renderTrip();
}

document.querySelectorAll("#trip-view .seg").forEach((seg) => {
  seg.addEventListener("click", () => {
    document.querySelectorAll("#trip-view .seg").forEach((s) => s.classList.toggle("active", s === seg));
    $("trip-cost").classList.toggle("hidden", seg.dataset.tab !== "cost");
    $("trip-convert").classList.toggle("hidden", seg.dataset.tab !== "convert");
    animateIn($(seg.dataset.tab === "cost" ? "trip-cost" : "trip-convert"),
      seg.dataset.tab === "cost" ? "enter-back" : "enter-forward");
  });
});

// -- logs --------------------------------------------------------------------
const logBody = $("log-body");
let logSource = "launcher";
let logTimer = null;

const atBottom = () => logBody.scrollHeight - logBody.scrollTop - logBody.clientHeight < 24;

async function loadLogs(forceBottom) {
  const stick = forceBottom || atBottom();
  let d;
  try { d = await getJSON(`/api/logs?source=${logSource}`); } catch (e) { return; }
  const text = d.lines && d.lines.length ? d.lines.join("\n") : "Nothing logged yet.";
  if (logBody.textContent !== text) {
    logBody.textContent = text;
    if (stick) logBody.scrollTop = logBody.scrollHeight;
  }
  $("log-bottom").classList.toggle("hidden", atBottom());
}

logBody.addEventListener("scroll", () => $("log-bottom").classList.toggle("hidden", atBottom()));
$("log-bottom").addEventListener("click", () => {
  logBody.scrollTop = logBody.scrollHeight;
});

document.querySelectorAll("#logs-view .seg").forEach((seg) => {
  seg.addEventListener("click", () => {
    logSource = seg.dataset.source;
    document.querySelectorAll("#logs-view .seg").forEach((s) => s.classList.toggle("active", s === seg));
    logBody.textContent = "";
    loadLogs(true);
  });
});

function openLogs() {
  loadLogs(true);
  logTimer = setInterval(() => loadLogs(false), 3000);
}

function closeLogs() {
  clearInterval(logTimer);
}

// -- settings ----------------------------------------------------------------
let config = { default_app: null, auto_launch: false };
let toastTimer = null;

const CHOICES = [
  { name: "CarPlay", icon: "i-carplay" },
  { name: "Flappy Bird", icon: "i-flappy" },
];

function renderSettings() {
  $("auto-launch-toggle").setAttribute("aria-checked", config.auto_launch ? "true" : "false");
  const picker = $("app-picker");
  picker.classList.toggle("disabled", !config.auto_launch);
  picker.innerHTML = "";
  for (const c of CHOICES) {
    const btn = document.createElement("button");
    btn.className = "choice";
    btn.setAttribute("role", "radio");
    btn.setAttribute("aria-checked", config.default_app === c.name ? "true" : "false");
    btn.innerHTML = `<svg><use href="#${c.icon}"/></svg><span>${c.name}</span>`;
    btn.addEventListener("click", () => saveSettings({ ...config, default_app: c.name }));
    picker.appendChild(btn);
  }
}

function showToast(text, fail) {
  const t = $("toast");
  t.textContent = text;
  t.classList.toggle("fail", !!fail);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 1800);
}

// Settings apply the moment they're tapped; there's no separate Save step.
async function saveSettings(next) {
  const prev = config;
  config = next;
  renderSettings();
  try {
    const data = await postJSON("/api/config", next);
    if (!data.ok) throw new Error();
    showToast("Saved");
  } catch (e) {
    config = prev;
    renderSettings();
    showToast("Couldn't save. Try again.", true);
  }
}

$("auto-launch-toggle").addEventListener("click", () => {
  const on = !config.auto_launch;
  saveSettings({ auto_launch: on, default_app: config.default_app || (on ? "CarPlay" : null) });
});

async function openSettings() {
  try { config = await getJSON("/api/config"); } catch (e) { /* show last known */ }
  renderSettings();
}

// -- paired phones (dongle web panel) ----------------------------------------
// Opening this view makes the backend borrow wlan0 to join the dongle's AP
// (shown as a loading skeleton); leaving it hands wlan0 back.
const devicesContent = $("devices-content");
const devMonitor = $("dev-monitor");

let inDevices = false;
let devicesPoll = null;
let confirmOpen = false;      // a per-row "Remove?" confirm is showing
let lastDevSig = null;        // skip list rebuilds when nothing changed
let busy = false;             // a remove/forget request is in flight

function openDevices() {
  inDevices = true;
  lastDevSig = null;
  renderConnecting();
  loadDevices();
  devicesPoll = setInterval(loadDevices, 2500);
}

function closeDevices() {
  inDevices = false;
  if (devicesPoll) { clearInterval(devicesPoll); devicesPoll = null; }
  devMonitor.textContent = "";
  // best-effort: give wlan0 back to the home network
  fetch("/api/devices/disconnect", { method: "POST" }).catch(() => {});
}

async function loadDevices() {
  if (!inDevices || busy) return;
  let d;
  try {
    d = await getJSON("/api/devices");
  } catch (e) {
    if (inDevices) renderError("The launcher isn't responding.");
    return;
  }
  if (!inDevices) return;
  if (d.state === "connecting" || d.state === "idle") renderConnecting();
  else if (d.state === "error") renderError(d.error || "Couldn't reach the dongle.");
  else if (d.state === "ready") renderReady(d.devices || [], d.monitor || {});
}

function renderConnecting() {
  devMonitor.textContent = "Joining the dongle's Wi-Fi…";
  lastDevSig = null;
  devicesContent.innerHTML = `<div class="dev-skel"></div><div class="dev-skel"></div><div class="dev-skel"></div>`;
}

function renderError(msg) {
  devMonitor.textContent = "";
  lastDevSig = null;
  devicesContent.innerHTML = `
    <div class="dev-error">${escapeHtml(msg)}<br>Make sure the dongle is powered, then try again.</div>
    <button class="dev-btn retry" id="dev-retry">Try again</button>`;
  $("dev-retry").addEventListener("click", () => {
    renderConnecting();
    loadDevices();
  });
}

function renderReady(devices, monitor) {
  if (typeof monitor.CpuTemp === "number") {
    const t = Math.round(monitor.CpuTemp);
    const cpu = Math.round(monitor.CpuRate ?? 0);
    const mem = Math.round(monitor.MemRate ?? 0);
    devMonitor.textContent = `Dongle is at ${t}°C, CPU ${cpu}%, memory ${mem}%`;
  } else {
    devMonitor.textContent = "";
  }
  // don't rebuild the list mid-confirm, or if the device set is unchanged
  const sig = devices.map((x) => x.id).join(",");
  if (confirmOpen || sig === lastDevSig) return;
  lastDevSig = sig;

  if (devices.length === 0) {
    devicesContent.innerHTML = `<div class="dev-hint">No phones are paired with the dongle.<br>Pair one from the phone's CarPlay settings.</div>`;
    return;
  }
  devicesContent.innerHTML = "";
  for (const dev of devices) {
    const row = document.createElement("div");
    row.className = "dev-row";
    row.innerHTML = `
      <svg class="dev-ico"><use href="#i-devices"/></svg>
      <div class="dev-meta">
        <div class="dev-name">${escapeHtml(dev.name || "Unnamed phone")}</div>
        <div class="dev-mac">${escapeHtml(dev.id)}</div>
      </div>
      <div class="dev-actions"></div>`;
    buildRemoveButton(row.querySelector(".dev-actions"), dev);
    devicesContent.appendChild(row);
  }
  const forget = document.createElement("button");
  forget.className = "dev-btn forget-all";
  forget.textContent = "Forget all phones";
  forget.addEventListener("click", () => confirmForgetAll(devices));
  devicesContent.appendChild(forget);
}

function buildRemoveButton(container, dev) {
  container.innerHTML = "";
  const btn = document.createElement("button");
  btn.className = "dev-btn";
  btn.textContent = "Forget";
  btn.addEventListener("click", () => {
    confirmOpen = true;
    container.innerHTML = "";
    const yes = document.createElement("button");
    yes.className = "dev-btn confirm-yes";
    yes.textContent = "Forget phone";
    yes.addEventListener("click", () => removeDevice(dev, container));
    const no = document.createElement("button");
    no.className = "dev-btn";
    no.textContent = "Cancel";
    no.addEventListener("click", () => { confirmOpen = false; buildRemoveButton(container, dev); });
    container.appendChild(no);
    container.appendChild(yes);
  });
  container.appendChild(btn);
}

async function removeDevice(dev, container) {
  busy = true;
  container.innerHTML = `<span class="dev-working">Forgetting…</span>`;
  try {
    const data = await postJSON("/api/devices/remove", { mac: dev.id });
    if (!data.ok) container.innerHTML = `<span class="dev-working fail">Couldn't forget</span>`;
  } catch (e) {
    container.innerHTML = `<span class="dev-working fail">Couldn't forget</span>`;
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
    if (forget) { forget.dataset.armed = "1"; forget.textContent = `Tap again to forget all ${devices.length}`; }
    setTimeout(() => { if (forget) { forget.dataset.armed = "0"; forget.textContent = "Forget all phones"; } }, 3000);
    return;
  }
  busy = true;
  confirmOpen = false;
  devicesContent.innerHTML = `<div class="dev-hint">Forgetting ${devices.length} phones…</div>`;
  for (const dev of devices) {
    try {
      await postJSON("/api/devices/remove", { mac: dev.id });
    } catch (e) { /* keep going; the final reload shows the real state */ }
  }
  busy = false;
  lastDevSig = null;
  loadDevices();
}

// -- boot --------------------------------------------------------------------
refreshStatus();
setInterval(() => { if (!currentView) refreshStatus(); }, 2000);
