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
};

let cfgDisplay = { title: "Netzbezug", critical_text: "STROM REDUZIEREN!", warn_text: "" };

function fmt(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return Number(v).toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function render(state) {
  const level = state.level || "offline";
  el.main.className = "layout level-" + level;
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

  // Erzeugung
  el.prod.textContent = (state.production_kw === null || state.production_kw === undefined)
    ? "–" : fmt(Math.max(0, state.production_kw), 1);

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
  loadStandbyState();
  setInterval(loadStandbyState, 20000);
  startStream();
}
