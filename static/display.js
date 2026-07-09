// Live-Anzeige für den Küchenmonitor.
// Bezieht den Zustand per Server-Sent-Events (/api/stream), Fallback Polling.

const GAUGE_LEN = 283; // Länge des Halbkreis-Pfads (π·90)

const el = {
  main: document.getElementById("main"),
  title: document.getElementById("title"),
  power: document.getElementById("power"),
  pct: document.getElementById("pct"),
  maxkw: document.getElementById("maxkw"),
  total: document.getElementById("total"),
  dir: document.getElementById("dir"),
  dirText: document.getElementById("dirText"),
  prod: document.getElementById("prod"),
  dayErtrag: document.getElementById("dayErtrag"),
  dayVerbrauch: document.getElementById("dayVerbrauch"),
  weekErtrag: document.getElementById("weekErtrag"),
  weekVerbrauch: document.getElementById("weekVerbrauch"),
  monthErtrag: document.getElementById("monthErtrag"),
  monthVerbrauch: document.getElementById("monthVerbrauch"),
  meterList: document.getElementById("meterList"),
  status: document.getElementById("status"),
  gaugeFill: document.getElementById("gaugeFill"),
  needle: document.getElementById("needle"),
  overlay: document.getElementById("overlay"),
  overlayText: document.getElementById("overlayText"),
  overlaySub: document.getElementById("overlaySub"),
  standbyOverlay: document.getElementById("standbyOverlay"),
  prodMini: document.getElementById("prodMini"),
  prodUnit: document.getElementById("prodUnit"),
  prodMiniUnit: document.getElementById("prodMiniUnit"),
  prodChart: document.getElementById("prodChart"),
  prodChartMini: document.getElementById("prodChartMini"),
  costTodayVerbrauch: document.getElementById("costTodayVerbrauch"),
  costTodayEigen: document.getElementById("costTodayEigen"),
  costTodayKosten: document.getElementById("costTodayKosten"),
  costPrevVerbrauch: document.getElementById("costPrevVerbrauch"),
  costPrevEigen: document.getElementById("costPrevEigen"),
  costPrevKosten: document.getElementById("costPrevKosten"),
};

let costsEnabled = false;

let cfgDisplay = { title: "Netzbezug", critical_text: "STROM REDUZIEREN!", warn_text: "" };

function fmt(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return Number(v).toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

// Erzeugung: unter 10 kW in Watt (ohne Nachkommastellen), sonst kW mit 2 Nachkommastellen.
function fmtProduction(kw) {
  if (kw === null || kw === undefined) return { text: "–", unit: "kW" };
  const v = Math.max(0, kw);
  if (v < 10) {
    return { text: Math.round(v * 1000).toLocaleString("de-DE"), unit: "W" };
  }
  return { text: fmt(v, 2), unit: "kW" };
}

// --- Erzeugungs-Diagramm (Verlauf, Canvas) -----------------------------------
const PROD_HISTORY_MAX = 60;
let prodHistory = [];
const PROD_CHART_COLOR = "#f5b50a"; // == --pv in style.css

function drawProdChart(canvas) {
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  if (rect.width < 4 || rect.height < 4) return; // (noch) nicht sichtbar
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(rect.width * dpr));
  const h = Math.max(1, Math.round(rect.height * dpr));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, w, h);

  const data = prodHistory;
  if (data.length < 2) return;
  const known = data.filter((v) => v !== null && v !== undefined);
  const max = Math.max(0.1, ...(known.length ? known : [0]));
  const pad = 3 * dpr;
  const xStep = (w - pad * 2) / (data.length - 1);
  const xFor = (i) => pad + i * xStep;
  const yFor = (v) => h - pad - (v / max) * (h - pad * 2);

  // Flächenfüllung unter der Linie
  ctx.beginPath();
  ctx.moveTo(xFor(0), h);
  data.forEach((v, i) => ctx.lineTo(xFor(i), v == null ? h : yFor(v)));
  ctx.lineTo(xFor(data.length - 1), h);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, PROD_CHART_COLOR + "50");
  grad.addColorStop(1, PROD_CHART_COLOR + "05");
  ctx.fillStyle = grad;
  ctx.fill();

  // Linie
  ctx.beginPath();
  let started = false;
  data.forEach((v, i) => {
    if (v === null || v === undefined) return;
    const px = xFor(i), py = yFor(v);
    if (!started) { ctx.moveTo(px, py); started = true; } else { ctx.lineTo(px, py); }
  });
  ctx.strokeStyle = PROD_CHART_COLOR;
  ctx.lineWidth = 2 * dpr;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.stroke();

  // aktueller Punkt (letzter Wert)
  for (let i = data.length - 1; i >= 0; i--) {
    if (data[i] === null || data[i] === undefined) continue;
    ctx.beginPath();
    ctx.arc(xFor(i), yFor(data[i]), 3 * dpr, 0, Math.PI * 2);
    ctx.fillStyle = PROD_CHART_COLOR;
    ctx.fill();
    break;
  }
}

function drawProdCharts() {
  drawProdChart(el.prodChart);
  drawProdChart(el.prodChartMini);
}

window.addEventListener("resize", drawProdCharts);

function render(state) {
  const level = state.level || "offline";
  el.main.className = "layout level-" + level + (costsEnabled ? " costs-on" : "");
  document.body.classList.toggle("crit", level === "critical");

  // Netzbezug (Betrag im Tacho)
  const power = state.power_kw;
  el.power.textContent = (power === null || power === undefined) ? "–" : fmt(Math.abs(power), 1);
  el.maxkw.textContent = fmt(state.max_power_kw, 0);

  // Auslastung + Tacho (nur Bezug)
  const pct = state.percent;
  el.pct.textContent = (pct === null || pct === undefined) ? "– %" : fmt(pct, 0) + " %";
  const frac = Math.max(0, Math.min(1, (pct || 0) / 100));
  el.gaugeFill.style.strokeDashoffset = String(GAUGE_LEN * (1 - frac));
  el.needle.style.transform = `rotate(${-90 + frac * 180}deg)`;

  // Gesamtverbrauch (kann negativ sein)
  el.total.textContent = (state.consumption_kw === null || state.consumption_kw === undefined)
    ? "– kW" : fmt(state.consumption_kw, 1) + " kW";

  // Richtung: Netzbezug / Einspeisung
  if (state.direction === "einspeisung") {
    el.dir.className = "dir einspeisung";
    el.dirText.textContent = "Einspeisung " + fmt(Math.abs(power), 1) + " kW";
  } else if (state.direction === "bezug") {
    el.dir.className = "dir bezug";
    el.dirText.textContent = "Netzbezug " + fmt(Math.abs(power), 1) + " kW";
  } else {
    el.dir.className = "dir";
    el.dirText.textContent = "–";
  }

  // Erzeugung (großes Feld + ggf. kleines Feld bei aktivierter Kosten-Anzeige)
  const prodFmt = fmtProduction(state.production_kw);
  el.prod.textContent = prodFmt.text;
  el.prodUnit.textContent = prodFmt.unit;
  el.prodMini.textContent = prodFmt.text;
  el.prodMiniUnit.textContent = prodFmt.unit;

  // Verlaufsdiagramm der Erzeugung
  prodHistory.push((state.production_kw === null || state.production_kw === undefined) ? null : Math.max(0, state.production_kw));
  if (prodHistory.length > PROD_HISTORY_MAX) prodHistory.shift();
  drawProdCharts();

  // Energie (Tag / Woche / Monat)
  const kwh = (v) => (v === null || v === undefined) ? "– kWh" : fmt(v, 1) + " kWh";
  el.dayErtrag.textContent = kwh(state.tagesertrag_kwh);
  el.dayVerbrauch.textContent = kwh(state.tagesverbrauch_kwh);
  el.weekErtrag.textContent = kwh(state.week_ertrag);
  el.weekVerbrauch.textContent = kwh(state.week_verbrauch);
  el.monthErtrag.textContent = kwh(state.month_ertrag);
  el.monthVerbrauch.textContent = kwh(state.month_verbrauch);

  // Optionale Zusatz-Zähler
  const meters = state.meters || [];
  if (!meters.length) {
    el.meterList.innerHTML = "";
  } else {
    el.meterList.innerHTML = meters.map(m => {
      if (m.error) {
        return `<div class="meter err"><div class="m-name">${esc(m.name)}</div><div class="m-val">Fehler</div></div>`;
      }
      return `<div class="meter">
        <div class="m-name">${esc(m.name)}</div>
        <div class="m-val">${fmt(m.kw, 2)} kW</div>
        <div class="m-tag">${esc(m.type || "")}</div>
      </div>`;
    }).join("");
  }

  // Status / Fehler
  if (!state.online) {
    el.status.className = "status err";
    el.status.textContent = "⚠ Keine Verbindung" + (state.error ? " – " + state.error : "");
  } else if (state.stale) {
    el.status.className = "status err";
    el.status.textContent = "⚠ Keine aktuellen Werte";
  } else {
    el.status.className = "status";
    el.status.textContent = level === "warn" ? (cfgDisplay.warn_text || "Achtung – Leistung beobachten")
      : level === "critical" ? "" : "Betrieb normal";
  }

  // Vollbild-Warnung
  if (level === "critical") {
    el.overlay.classList.remove("hidden");
    el.overlayText.textContent = cfgDisplay.critical_text || "STROM REDUZIEREN!";
    el.overlaySub.textContent = `${fmt(Math.abs(power), 1)} kW von ${fmt(state.max_power_kw, 0)} kW (${fmt(pct, 0)} %)`;
  } else {
    el.overlay.classList.add("hidden");
  }
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function loadDisplayConfig() {
  try {
    const r = await fetch("/api/config");
    const c = await r.json();
    if (c && c.display) {
      cfgDisplay = Object.assign(cfgDisplay, c.display);
      el.title.textContent = cfgDisplay.title || "Netzbezug";
      document.title = cfgDisplay.title || "Küchen-Lastmonitor";
    }
  } catch (e) { /* ignore */ }
}

// --- Auto-Reload: lädt die Anzeige neu, sobald in den Einstellungen auf
// "Speichern & neu laden" geklickt wurde ------------------------------------
let reloadToken = null;
async function checkReload() {
  try {
    const r = await fetch("/api/reload-token");
    const d = await r.json();
    if (reloadToken === null) { reloadToken = d.token; return; }
    if (d.token !== reloadToken) { location.reload(); }
  } catch (e) { /* ignore */ }
}

// --- Kosten (Verbrauch/Eigenverbrauch/Kosten, Heute + Vortag) ---------------
function euro(v) {
  return (v === null || v === undefined) ? "– €" : fmt(v, 2) + " €";
}
function kwhVal(v) {
  return (v === null || v === undefined) ? "– kWh" : fmt(v, 1) + " kWh";
}
async function loadCosts() {
  try {
    const r = await fetch("/api/costs");
    const c = await r.json();
    costsEnabled = !!c.show_on_display;
    const t = c.today || {}, p = c.prev || {};
    el.costTodayVerbrauch.textContent = kwhVal(t.verbrauch_kwh);
    el.costTodayEigen.textContent = kwhVal(t.eigenverbrauch_kwh);
    el.costTodayKosten.textContent = euro(t.kosten_eur);
    el.costPrevVerbrauch.textContent = kwhVal(p.verbrauch_kwh);
    el.costPrevEigen.textContent = kwhVal(p.eigenverbrauch_kwh);
    el.costPrevKosten.textContent = euro(p.kosten_eur);
    setTimeout(drawProdCharts, 50); // neu sichtbares Diagramm sofort zeichnen (Layout-Umschaltung)
  } catch (e) { /* ignore, alte Werte bleiben stehen */ }
}

// --- Standby-Zeitfenster: dunkelt außerhalb des Fensters komplett ab --------
async function loadStandbyState() {
  try {
    const r = await fetch("/api/standby-state");
    const s = await r.json();
    const shouldBeOn = s.enabled ? s.should_be_on !== false : true;
    el.standbyOverlay.classList.toggle("hidden", shouldBeOn);
  } catch (e) { /* ignore, Overlay-Zustand bleibt wie er ist */ }
}

let es = null, pollTimer = null;

function startStream() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  es = new EventSource("/api/stream");
  es.onmessage = (ev) => { try { render(JSON.parse(ev.data)); } catch (e) {} };
  es.onerror = () => {
    if (es) { es.close(); es = null; }
    if (!pollTimer) {
      pollTimer = setInterval(pollOnce, 1500);
      setTimeout(() => { if (!es) startStream(); }, 8000);
    }
  };
}

async function pollOnce() {
  try { const r = await fetch("/api/state"); render(await r.json()); }
  catch (e) { render({ online: false, error: "Server nicht erreichbar", level: "offline" }); }
}

// --- Demo-Modus (?demo=ok|warn|critical|einspeisung) ------------------------
function demoState(level) {
  const max = 43;
  const demoMeters = [
    { name: "Fritteuse", type: "modbus", kw: 4.12 },
    { name: "Herd / Kochfeld", type: "modbus", kw: 7.84 },
    { name: "Spülmaschine", type: "s0", kw: 2.31 },
    { name: "Kühlhaus", type: "s0", kw: 1.87 },
    { name: "Konvektomat", type: "modbus", kw: 5.20 },
    { name: "Licht / Steckdosen", type: "s0", kw: 0.96 },
  ];
  const map = {
    ok:          { grid: 18.5, pct: 43, prod: 6.2,  dir: "bezug" },
    warn:        { grid: 35.8, pct: 83, prod: 2.1,  dir: "bezug" },
    critical:    { grid: 41.6, pct: 97, prod: 0.4,  dir: "bezug" },
    einspeisung: { grid: -5.2, pct: 0,  prod: 12.0, dir: "einspeisung" },
  };
  const d = map[level] || map.ok;
  return {
    online: true, error: null, stale: false,
    power_kw: d.grid, max_power_kw: max, percent: d.pct,
    level: level === "einspeisung" ? "ok" : level,
    direction: d.dir,
    production_kw: d.prod,
    consumption_kw: d.grid + d.prod,
    meters: [],
    tagesertrag_kwh: 36.8, tagesverbrauch_kwh: 24.3,
    week_ertrag: 184.2, week_verbrauch: 142.7,
    month_ertrag: 612.5, month_verbrauch: 488.1,
    ts: 0,
  };
}

const demo = new URLSearchParams(location.search).get("demo");
if (demo) {
  el.title.textContent = cfgDisplay.title;
  render(demoState(demo));
} else {
  loadDisplayConfig();
  setInterval(loadDisplayConfig, 30000);
  checkReload();
  setInterval(checkReload, 8000);
  loadStandbyState();
  setInterval(loadStandbyState, 20000);
  loadCosts();
  setInterval(loadCosts, 60000);
  startStream();
}
