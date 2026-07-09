// Büro-Übersicht: aktuelle Werte, Energie, Kosten, alle Zähler, Lastspitzen –
// alles auf einer Seite, live aktualisiert. Kein Standby/Vollbild-Zwang.
const $ = (id) => document.getElementById(id);

function fmt(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return Number(v).toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function kw(v, digits = 2) { return (v === null || v === undefined) ? "–" : fmt(v, digits) + " kW"; }
function kwh(v) { return (v === null || v === undefined) ? "–" : fmt(v, 1) + " kWh"; }
function euro(v) { return (v === null || v === undefined) ? "–" : fmt(v, 2) + " €"; }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function renderState(state) {
  $("oPower").textContent = kw(state.power_kw);
  $("oProd").textContent = kw(state.production_kw);
  $("oCons").textContent = kw(state.consumption_kw);
  $("oPct").textContent = (state.percent === null || state.percent === undefined) ? "– %" : fmt(state.percent, 0) + " %";

  const dir = $("oDir");
  if (state.direction === "einspeisung") {
    dir.className = "odir einspeisung";
    dir.textContent = "Einspeisung " + fmt(Math.abs(state.power_kw), 1) + " kW";
  } else if (state.direction === "bezug") {
    dir.className = "odir bezug";
    dir.textContent = "Bezug " + fmt(Math.abs(state.power_kw), 1) + " kW";
  } else {
    dir.className = "odir";
    dir.textContent = "–";
  }

  $("oDayE").textContent = kwh(state.tagesertrag_kwh);
  $("oDayV").textContent = kwh(state.tagesverbrauch_kwh);
  $("oWeekE").textContent = kwh(state.week_ertrag);
  $("oWeekV").textContent = kwh(state.week_verbrauch);
  $("oMonthE").textContent = kwh(state.month_ertrag);
  $("oMonthV").textContent = kwh(state.month_verbrauch);

  const status = $("officeStatus");
  if (!state.online) {
    status.className = "office-status err";
    status.textContent = "⚠ Keine Verbindung" + (state.error ? " – " + state.error : "");
  } else if (state.stale) {
    status.className = "office-status err";
    status.textContent = "⚠ Keine aktuellen Werte";
  } else {
    status.className = "office-status";
    status.textContent = "Verbunden – Betrieb normal";
  }

  const meters = state.meters || [];
  const mEl = $("oMeters");
  if (!meters.length) {
    mEl.innerHTML = '<p class="ohint">Keine Zähler konfiguriert (Einstellungen → Zähler).</p>';
  } else {
    mEl.innerHTML = meters.map((m) => {
      if (m.error) {
        return `<div class="ometer err"><div class="om-name">${esc(m.name)}</div><div class="om-val">Fehler</div></div>`;
      }
      return `<div class="ometer">
        <div class="om-name">${esc(m.name)}</div>
        <div class="om-val">${fmt(m.kw, 2)} kW</div>
        <div class="om-tag">${esc(m.type || "")}</div>
      </div>`;
    }).join("");
  }
}

async function loadCosts() {
  try {
    const r = await fetch("/api/costs");
    const c = await r.json();
    const t = c.today || {}, p = c.prev || {};
    $("oCostTodayV").textContent = kwh(t.verbrauch_kwh);
    $("oCostTodayE").textContent = kwh(t.eigenverbrauch_kwh);
    $("oCostTodayK").textContent = euro(t.kosten_eur);
    $("oCostPrevV").textContent = kwh(p.verbrauch_kwh);
    $("oCostPrevE").textContent = kwh(p.eigenverbrauch_kwh);
    $("oCostPrevK").textContent = euro(p.kosten_eur);
    $("oCostHint").textContent = `Bezugskosten ${fmt(c.bezug_eur_kwh, 2)} €/kWh · PV-Strom-Kosten ${fmt(c.pv_eur_kwh, 2)} €/kWh` +
      (c.show_on_display ? "" : " · auf der Küchen-Anzeige aktuell ausgeblendet");
  } catch (e) { /* ignore */ }
}

async function loadPeaks() {
  try {
    const r = await fetch("/api/peaks");
    const p = await r.json();
    $("oPeakToday").textContent = kw(p.today_peak_kw, 1);
    $("oPeakAvg").textContent = kw(p.today_avg_kw, 1);
    $("oPeakYear").textContent = kw(p.year_peak_kw, 1);
  } catch (e) { /* ignore */ }
}

async function loadDisplayConfig() {
  try {
    const r = await fetch("/api/config");
    const c = await r.json();
    const title = (c.display && c.display.title) || "Netzbezug";
    $("officeTitle").textContent = "Büro-Übersicht – " + title;
    document.title = "Büro-Übersicht – " + title;
  } catch (e) { /* ignore */ }
}

let es = null, pollTimer = null;
function startStream() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  es = new EventSource("/api/stream");
  es.onmessage = (ev) => { try { renderState(JSON.parse(ev.data)); } catch (e) {} };
  es.onerror = () => {
    if (es) { es.close(); es = null; }
    if (!pollTimer) {
      pollTimer = setInterval(pollOnce, 2000);
      setTimeout(() => { if (!es) startStream(); }, 8000);
    }
  };
}
async function pollOnce() {
  try { const r = await fetch("/api/state"); renderState(await r.json()); }
  catch (e) { renderState({ online: false, error: "Server nicht erreichbar", meters: [] }); }
}

loadDisplayConfig();
setInterval(loadDisplayConfig, 30000);
loadCosts();
setInterval(loadCosts, 30000);
loadPeaks();
setInterval(loadPeaks, 30000);
startStream();
