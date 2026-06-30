// Live-Anzeige für den Küchenmonitor.
// Bezieht den Zustand per Server-Sent-Events (/api/stream) und fällt bei
// Verbindungsabbruch automatisch auf Polling (/api/state) zurück.

const GAUGE_LEN = 283; // Länge des Halbkreis-Pfads (π·90)

const el = {
  main: document.getElementById("main"),
  title: document.getElementById("title"),
  power: document.getElementById("power"),
  pct: document.getElementById("pct"),
  maxkw: document.getElementById("maxkw"),
  phases: document.getElementById("phases"),
  status: document.getElementById("status"),
  gaugeFill: document.getElementById("gaugeFill"),
  needle: document.getElementById("needle"),
  overlay: document.getElementById("overlay"),
  overlayText: document.getElementById("overlayText"),
  overlaySub: document.getElementById("overlaySub"),
};

let cfgDisplay = { title: "Küche – Netzbezug", critical_text: "STROM REDUZIEREN!", warn_text: "", show_phases: true };

function fmt(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return Number(v).toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function render(state) {
  const level = state.level || "offline";
  el.main.className = "screen level-" + level;
  document.body.classList.toggle("crit", level === "critical");

  // Leistung
  el.power.textContent = state.power_kw === null || state.power_kw === undefined
    ? "–" : fmt(Math.max(0, state.power_kw), 1);
  el.maxkw.textContent = fmt(state.max_power_kw, 0);

  // Prozent + Tacho
  const pct = state.percent;
  el.pct.textContent = (pct === null || pct === undefined) ? "– %" : fmt(pct, 0) + " %";
  const frac = Math.max(0, Math.min(1, (pct || 0) / 100));
  el.gaugeFill.style.strokeDashoffset = String(GAUGE_LEN * (1 - frac));
  el.needle.style.transform = `rotate(${-90 + frac * 180}deg)`;

  // Phasen
  if (cfgDisplay.show_phases && state.phases_kw && state.phases_kw.some(v => v !== null)) {
    el.phases.style.display = "flex";
    el.phases.innerHTML = state.phases_kw.map((p, i) => {
      const cur = state.currents_a ? state.currents_a[i] : null;
      return `<div class="phase">
        <div class="p-name">L${i + 1}</div>
        <div class="p-val">${fmt(p === null ? null : Math.max(0, p), 1)} kW</div>
        <div class="p-cur">${cur === null || cur === undefined ? "" : fmt(cur, 0) + " A"}</div>
      </div>`;
    }).join("");
  } else {
    el.phases.style.display = "none";
  }

  // Status / Fehler
  if (!state.online) {
    el.status.className = "status err";
    el.status.textContent = "⚠ Keine Verbindung zum PLEXLOG" + (state.error ? " – " + state.error : "");
  } else if (state.stale) {
    el.status.className = "status err";
    el.status.textContent = "⚠ Keine aktuellen Werte (Datenstrom unterbrochen)";
  } else {
    el.status.className = "status";
    el.status.textContent = level === "warn" ? (cfgDisplay.warn_text || "Achtung – Leistung beobachten")
      : level === "critical" ? "" : "Betrieb normal";
  }

  // Vollbild-Warnung
  if (level === "critical") {
    el.overlay.classList.remove("hidden");
    el.overlayText.textContent = cfgDisplay.critical_text || "STROM REDUZIEREN!";
    el.overlaySub.textContent = `${fmt(state.power_kw, 1)} kW von ${fmt(state.max_power_kw, 0)} kW (${fmt(pct, 0)} %)`;
  } else {
    el.overlay.classList.add("hidden");
  }
}

async function loadDisplayConfig() {
  try {
    const r = await fetch("/api/config");
    const c = await r.json();
    if (c && c.display) {
      cfgDisplay = Object.assign(cfgDisplay, c.display);
      el.title.textContent = cfgDisplay.title || "Küche – Netzbezug";
      document.title = cfgDisplay.title || "Küchen-Lastmonitor";
    }
  } catch (e) { /* ignore */ }
}

let es = null;
let pollTimer = null;

function startStream() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  es = new EventSource("/api/stream");
  es.onmessage = (ev) => {
    try { render(JSON.parse(ev.data)); } catch (e) { /* ignore */ }
  };
  es.onerror = () => {
    // SSE gestört -> auf Polling umschalten und später erneut SSE versuchen
    if (es) { es.close(); es = null; }
    if (!pollTimer) {
      pollTimer = setInterval(pollOnce, 1500);
      setTimeout(() => { if (!es) startStream(); }, 8000);
    }
  };
}

async function pollOnce() {
  try {
    const r = await fetch("/api/state");
    render(await r.json());
  } catch (e) {
    render({ online: false, error: "Server nicht erreichbar", level: "offline" });
  }
}

// Konfig periodisch neu laden (Titel/Texte/Phasen-Schalter können sich ändern)
loadDisplayConfig();
setInterval(loadDisplayConfig, 30000);
startStream();
