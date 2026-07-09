// Einstellungen laden, testen, speichern – inkl. Zähler-Editor und Register-Scanner.
const $ = (id) => document.getElementById(id);

const PROFILES = {
  nativ: {
    port: 503, function: "input", datatype: "int32", power_scale: 0.001,
    byte_order: "big", word_order: "big", grid_mode: "analyzer",
    registers: { power_total: 2, production: 0, analyzer: 19,
      tagesertrag: 4, tagesverbrauch: 6, gesamtertrag: 8, gesamtertrag_exp: 10, gesamtverbrauch: 11, gesamtverbrauch_exp: 13,
      power_l1: null, power_l2: null, power_l3: null, current_l1: null, current_l2: null, current_l3: null },
  },
  gateway: {
    port: 1502, function: "holding", datatype: "float32", power_scale: 1000,
    byte_order: "big", word_order: "big",
    registers: { power_total: 0, production: null, power_l1: 2, power_l2: 4, power_l3: 6, current_l1: 30, current_l2: 32, current_l3: 34 },
  },
};

function numOrNull(v) {
  if (v === "" || v === null || v === undefined) return null;
  const n = parseFloat(v);
  return Number.isNaN(n) ? null : n;
}
function intOrNull(v) {
  if (v === "" || v === null || v === undefined) return null;
  const n = parseInt(v);
  return Number.isNaN(n) ? null : n;
}
function setReg(id, v) { $(id).value = (v === null || v === undefined) ? "" : v; }
function setMsg(id, text, ok) { const e = $(id); e.textContent = text; e.className = "msg " + (ok ? "ok" : "err"); }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

// ---- Zähler-Editor ----------------------------------------------------------
function meterRowHtml(m) {
  m = m || {};
  return `<div class="meter-row">
    <div class="mr-head">
      <span class="mr-title">Zähler</span>
      <button type="button" class="btn-del btn-small" onclick="this.closest('.meter-row').remove()">Entfernen</button>
    </div>
    <div class="row">
      <div class="field" style="flex:2"><label>Name (frei wählbar)</label><input class="m-name" value="${esc(m.name || "")}" placeholder="z. B. Fritteuse" /></div>
      <div class="field"><label>Typ</label>
        <select class="m-type"><option value="modbus"${m.type === "modbus" ? " selected" : ""}>Modbus</option><option value="s0"${m.type === "s0" ? " selected" : ""}>S0</option></select>
      </div>
    </div>
    <div class="row">
      <div class="field"><label>Plexlog-Port</label><input class="m-port" value="${esc(m.port || "")}" placeholder="z. B. RS485-A / S0-1" /></div>
      <div class="field"><label>Modbus-Adresse</label><input class="m-addr" type="number" value="${m.address ?? ""}" placeholder="bei Modbus" /></div>
      <div class="field"><label>Register (Leistung)</label><input class="m-reg" type="number" value="${m.register ?? ""}" placeholder="Pflicht" /></div>
    </div>
    <div class="row">
      <div class="field"><label>Datentyp</label>
        <select class="m-dt"><option value="">wie Standard</option><option value="int32"${m.datatype === "int32" ? " selected" : ""}>int32</option><option value="uint32"${m.datatype === "uint32" ? " selected" : ""}>uint32</option><option value="float32"${m.datatype === "float32" ? " selected" : ""}>float32</option></select>
      </div>
      <div class="field"><label>Skalierung (Roh → kW)</label><input class="m-scale" type="number" step="0.000001" value="${m.scale ?? ""}" placeholder="wie Standard" /></div>
    </div>
  </div>`;
}
function addMeter(m) { $("meterEditor").insertAdjacentHTML("beforeend", meterRowHtml(m)); }
function renderMeters(list) {
  $("meterEditor").innerHTML = "";
  (list || []).forEach(addMeter);
}
function collectMeters() {
  const out = [];
  document.querySelectorAll(".meter-row").forEach(row => {
    const q = (s) => row.querySelector(s);
    const name = q(".m-name").value.trim();
    const reg = intOrNull(q(".m-reg").value);
    if (!name && reg === null) return; // leere Zeile überspringen
    out.push({
      name, type: q(".m-type").value,
      port: q(".m-port").value.trim() || null,
      address: intOrNull(q(".m-addr").value),
      register: reg,
      datatype: q(".m-dt").value || null,
      scale: numOrNull(q(".m-scale").value),
    });
  });
  return out;
}

// ---- Konfiguration sammeln / anwenden --------------------------------------
let _loadedRegisters = {};   // bewahrt Register, die nicht im UI stehen (Energie etc.)

function collect() {
  // Energie-/Sonderregister aus der geladenen Konfig erhalten, UI-Felder drüberlegen
  const registers = Object.assign({}, _loadedRegisters, {
    power_total: intOrNull($("r_power_total").value) ?? 2,
    production: intOrNull($("r_production").value),
    analyzer: intOrNull($("r_analyzer").value) ?? 19,
    power_l1: intOrNull($("r_power_l1").value),
    power_l2: intOrNull($("r_power_l2").value),
    power_l3: intOrNull($("r_power_l3").value),
    current_l1: intOrNull($("r_current_l1").value),
    current_l2: intOrNull($("r_current_l2").value),
    current_l3: intOrNull($("r_current_l3").value),
  });
  return {
    poll_interval_s: parseFloat($("poll_interval_s").value) || 1,
    modbus: {
      profile: $("profile").value,
      host: $("host").value.trim(),
      port: parseInt($("port").value) || 503,
      unit_id: parseInt($("unit_id").value) || 1,
      function: $("function").value,
      datatype: $("datatype").value,
      byte_order: $("byte_order").value,
      word_order: $("word_order").value,
      power_scale: parseFloat($("power_scale").value) || 0.001,
      invert_sign: $("invert_sign").checked,
      grid_mode: $("grid_mode").value,
      registers,
    },
    meters: collectMeters(),
    limits: {
      max_power_kw: parseFloat($("max_power_kw").value) || 43,
      warn_percent: parseFloat($("warn_percent").value) || 80,
      critical_percent: parseFloat($("critical_percent").value) || 95,
    },
    display: {
      title: $("d_title").value,
      warn_text: $("d_warn_text").value,
      critical_text: $("d_critical_text").value,
      standby: {
        enabled: $("standby_enabled").checked,
        days: collectStandbyDays(),
      },
    },
    sms: {
      enabled: $("sms_enabled").checked,
      provider: "seven",
      api_key: $("sms_api_key").value.trim(),
      sender: $("sms_sender").value.trim() || "Lastmonitor",
      phone_number: $("sms_phone").value.trim(),
      threshold_percent: numOrNull($("sms_threshold").value),
      cooldown_minutes: parseFloat($("sms_cooldown").value) || 15,
      notify_recovery: $("sms_notify_recovery").checked,
      notify_connection_loss: $("sms_notify_conn").checked,
      connection_loss_after_minutes: parseFloat($("sms_conn_after").value) || 3,
    },
  };
}

function apply(cfg) {
  const m = cfg.modbus || {}, r = m.registers || {}, l = cfg.limits || {}, d = cfg.display || {}, s = cfg.sms || {};
  _loadedRegisters = Object.assign({}, r);
  $("profile").value = m.profile || "nativ";
  $("host").value = m.host || "";
  $("port").value = m.port ?? 503;
  $("unit_id").value = m.unit_id ?? 1;
  $("function").value = m.function || "input";
  $("datatype").value = m.datatype || "int32";
  $("byte_order").value = m.byte_order || "big";
  $("word_order").value = m.word_order || "big";
  $("power_scale").value = m.power_scale ?? 0.001;
  $("invert_sign").checked = !!m.invert_sign;
  $("grid_mode").value = m.grid_mode || "analyzer";
  setReg("r_analyzer", r.analyzer ?? 19);
  setReg("r_power_total", r.power_total ?? 2);
  setReg("r_production", r.production ?? 0);
  setReg("r_power_l1", r.power_l1); setReg("r_power_l2", r.power_l2); setReg("r_power_l3", r.power_l3);
  setReg("r_current_l1", r.current_l1); setReg("r_current_l2", r.current_l2); setReg("r_current_l3", r.current_l3);
  renderMeters(cfg.meters);
  $("max_power_kw").value = l.max_power_kw ?? 43;
  $("warn_percent").value = l.warn_percent ?? 80;
  $("critical_percent").value = l.critical_percent ?? 95;
  $("d_title").value = d.title ?? "Netzbezug";
  $("d_warn_text").value = d.warn_text ?? "Achtung – Leistung beobachten";
  $("d_critical_text").value = d.critical_text ?? "STROM REDUZIEREN!";
  $("poll_interval_s").value = cfg.poll_interval_s ?? 1;
  const sb = d.standby || {};
  $("standby_enabled").checked = !!sb.enabled;
  renderStandbyDays(sb.days);
  $("sms_enabled").checked = !!s.enabled;
  $("sms_api_key").value = s.api_key || "";
  $("sms_sender").value = s.sender || "Lastmonitor";
  $("sms_phone").value = s.phone_number || "";
  $("sms_threshold").value = s.threshold_percent ?? "";
  $("sms_cooldown").value = s.cooldown_minutes ?? 15;
  $("sms_notify_recovery").checked = s.notify_recovery !== false;
  $("sms_notify_conn").checked = s.notify_connection_loss !== false;
  $("sms_conn_after").value = s.connection_loss_after_minutes ?? 3;
  updateVisibility();
}

function applyProfile(name) {
  const p = PROFILES[name];
  if (!p) return;
  _loadedRegisters = Object.assign({}, _loadedRegisters, p.registers); // Energie-Register übernehmen
  $("port").value = p.port; $("function").value = p.function; $("datatype").value = p.datatype;
  $("power_scale").value = p.power_scale; $("byte_order").value = p.byte_order; $("word_order").value = p.word_order;
  if (p.grid_mode) $("grid_mode").value = p.grid_mode;
  setReg("r_analyzer", p.registers.analyzer ?? 19);
  setReg("r_power_total", p.registers.power_total); setReg("r_production", p.registers.production);
  setReg("r_power_l1", p.registers.power_l1); setReg("r_power_l2", p.registers.power_l2); setReg("r_power_l3", p.registers.power_l3);
  setReg("r_current_l1", p.registers.current_l1); setReg("r_current_l2", p.registers.current_l2); setReg("r_current_l3", p.registers.current_l3);
  updateVisibility();
}
function updateVisibility() {
  $("phaseCard").style.display = $("profile").value === "gateway" ? "" : "none";
  const mode = $("grid_mode").value;
  $("analyzerField").style.display = mode === "analyzer" ? "" : "none";
  $("totalField").style.display = mode === "analyzer" ? "none" : "";
}

// ---- Standby-Zeitfenster -----------------------------------------------------
const WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const WEEKDAY_LABELS = { mon: "Montag", tue: "Dienstag", wed: "Mittwoch", thu: "Donnerstag", fri: "Freitag", sat: "Samstag", sun: "Sonntag" };

function standbyDayRowHtml(key, rec) {
  rec = rec || {};
  const same = !!rec.same_as_prev;
  return `<div class="row standby-day" data-day="${key}" style="align-items:end;flex-wrap:wrap">
    <div class="field" style="flex:0 0 100px"><label>${WEEKDAY_LABELS[key]}</label></div>
    <div class="field" style="flex:0 0 130px"><label>AN von</label><input class="sd-on" type="time" value="${esc(rec.on || "06:00")}" ${same ? "disabled" : ""} /></div>
    <div class="field" style="flex:0 0 130px"><label>bis</label><input class="sd-off" type="time" value="${esc(rec.off || "22:00")}" ${same ? "disabled" : ""} /></div>
    <div class="field toggle" style="flex:0 0 130px"><input class="sd-same" type="checkbox" ${same ? "checked" : ""} /><label style="margin:0">wie Vortag</label></div>
  </div>`;
}
function renderStandbyDays(days) {
  const el = $("standbyDays");
  el.innerHTML = WEEKDAY_KEYS.map(k => standbyDayRowHtml(k, (days || {})[k])).join("");
  el.querySelectorAll(".standby-day").forEach(row => {
    const same = row.querySelector(".sd-same");
    const on = row.querySelector(".sd-on"), off = row.querySelector(".sd-off");
    same.addEventListener("change", () => { on.disabled = off.disabled = same.checked; });
  });
}
function collectStandbyDays() {
  const out = {};
  document.querySelectorAll(".standby-day").forEach(row => {
    out[row.dataset.day] = {
      on: row.querySelector(".sd-on").value || "06:00",
      off: row.querySelector(".sd-off").value || "22:00",
      same_as_prev: row.querySelector(".sd-same").checked,
    };
  });
  return out;
}
async function loadStandbyStatus() {
  try {
    const r = await fetch("/api/standby-state");
    const s = await r.json();
    let txt = s.enabled
      ? (s.should_be_on ? "Aktuell: Bildschirm AN" : "Aktuell: Bildschirm AUS (Standby)")
      : "Standby-Zeitfenster ist deaktiviert – Bildschirm läuft durchgehend.";
    if (s.today_window) txt += ` · heutiges Fenster: ${s.today_window.on}–${s.today_window.off} Uhr`;
    if (s.last_error) txt += ` · Fehler: ${s.last_error}`;
    $("standbyStatus").textContent = txt;
  } catch (e) { /* Status ist nur Zusatzinfo, still ignorieren */ }
}

// ---- Laden / Speichern / Test ----------------------------------------------
async function load() {
  try { const r = await fetch("/api/config"); apply(await r.json()); }
  catch (e) { setMsg("saveMsg", "Konfiguration konnte nicht geladen werden: " + e, false); }
  loadStandbyStatus();
}

$("profile").addEventListener("change", () => applyProfile($("profile").value));
$("grid_mode").addEventListener("change", updateVisibility);
$("btnAddMeter").addEventListener("click", () => addMeter({ type: "modbus" }));

$("btnSave").addEventListener("click", async () => {
  setMsg("saveMsg", "Speichere …", true);
  try {
    const r = await fetch("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collect()) });
    const res = await r.json();
    setMsg("saveMsg", res.ok ? "✓ Gespeichert. Die Anzeige übernimmt die Werte automatisch." : "Fehler beim Speichern.", !!res.ok);
    setTimeout(loadStandbyStatus, 1000);
  } catch (e) { setMsg("saveMsg", "Fehler: " + e, false); }
});

$("btnTest").addEventListener("click", async () => {
  setMsg("testMsg", "Teste Verbindung …", true);
  try {
    const r = await fetch("/api/test", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ modbus: collect().modbus }) });
    const res = await r.json();
    setMsg("testMsg", res.ok ? `✓ Verbindung OK – Netzbezug: ${res.power_kw} kW (Rohwert ${res.raw})` : "✗ " + (res.error || "Fehlgeschlagen"), !!res.ok);
  } catch (e) { setMsg("testMsg", "✗ Fehler: " + e, false); }
});

$("btnSmsTest").addEventListener("click", async () => {
  setMsg("smsTestMsg", "Sende Test-SMS …", true);
  try {
    const r = await fetch("/api/sms/test", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sms: collect().sms }) });
    const res = await r.json();
    setMsg("smsTestMsg", res.ok ? "✓ SMS gesendet" + (res.balance != null ? ` (Guthaben: ${res.balance} €)` : "") : "✗ " + (res.error || "Fehlgeschlagen"), !!res.ok);
  } catch (e) { setMsg("smsTestMsg", "✗ Fehler: " + e, false); }
  loadSmsStatus();
});

async function loadSmsStatus() {
  try {
    const s = await (await fetch("/api/sms/status", { cache: "no-store" })).json();
    if (!s.last_sent_at) { $("smsStatus").textContent = "Bisher keine SMS versendet."; return; }
    const ok = s.last_result && s.last_result.ok;
    $("smsStatus").innerHTML = `Letzte SMS: ${esc(s.last_sent_at)} — ${ok ? "✓ erfolgreich" : "✗ fehlgeschlagen (" + esc((s.last_result && (s.last_result.error || JSON.stringify(s.last_result.raw))) || "?") + ")"}`;
  } catch (e) { /* still ok */ }
}

// ---- Register-Scanner -------------------------------------------------------
let scanTimer = null, lastScan = {};
async function doScan() {
  const body = { modbus: collect().modbus, start: parseInt($("scanStart").value) || 0, count: parseInt($("scanCount").value) || 20, function: $("scanFn").value || undefined };
  try {
    const r = await fetch("/api/scan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const res = await r.json();
    if (!res.ok) { setMsg("scanMsg", "✗ " + (res.error || "Fehler"), false); return; }
    setMsg("scanMsg", "✓ gelesen", true);
    renderScan(res.rows);
  } catch (e) { setMsg("scanMsg", "✗ " + e, false); }
}
function renderScan(rows) {
  let html = `<table class="scan-table"><tr><th class="addr">Register</th><th>int32</th><th>kW (×Skal.)</th><th>float32</th></tr>`;
  rows.forEach(r => {
    const prev = lastScan[r.address];
    const changed = prev !== undefined && r.int32 !== undefined && prev !== r.int32;
    if (r.int32 !== undefined) lastScan[r.address] = r.int32;
    if (r.error) {
      html += `<tr><td class="addr">${r.address}</td><td colspan="3" style="color:#fca5a5;text-align:left">${esc(r.error)}</td></tr>`;
    } else {
      html += `<tr class="${changed ? "changed" : ""}"><td class="addr">${r.address}</td><td>${r.int32}</td><td>${r.kw_int32}</td><td>${r.float32}</td></tr>`;
    }
  });
  html += `</table>`;
  $("scanResult").innerHTML = html;
}
$("btnScan").addEventListener("click", doScan);
$("scanAuto").addEventListener("change", () => {
  if ($("scanAuto").checked) { lastScan = {}; doScan(); scanTimer = setInterval(doScan, 2000); }
  else if (scanTimer) { clearInterval(scanTimer); scanTimer = null; }
});

// ---- Software-Version / Update / Downgrade ---------------------------------
let _currentHash = null;

async function loadVersion() {
  try {
    const v = await (await fetch("/api/version", { cache: "no-store" })).json();
    _currentHash = v.hash;
    $("versionInfo").innerHTML = v.hash
      ? `Aktuelle Version: <b>${esc(v.hash)}</b> &nbsp;·&nbsp; ${esc(v.date || "")}<br><span style="color:#93c5fd">${esc(v.subject || "")}</span>`
      : "Version unbekannt (kein Git-Repo).";
    if (v.updates_available) {
      $("updateMsg").textContent = `Update verfügbar (${v.behind} neuer)`;
      $("updateMsg").className = "msg ok";
    } else {
      $("updateMsg").textContent = "Aktuell – kein Update nötig";
      $("updateMsg").className = "msg";
    }
  } catch (e) {
    $("versionInfo").textContent = "Version konnte nicht geladen werden.";
  }
}

async function loadVersions() {
  try {
    const data = await (await fetch("/api/versions", { cache: "no-store" })).json();
    const cur = data.current;
    const rows = (data.versions || []).map((v, i) => {
      const isCur = v.hash === cur;
      const right = isCur
        ? `<span class="vbadge cur">aktuell</span>`
        : `<button class="btn-ghost btn-small" onclick="rollbackTo('${esc(v.hash)}')">Auf diese Version</button>`;
      return `<div class="vrow ${isCur ? "current" : ""}">
        <div class="vmeta"><div class="vsubj">${esc(v.subject)}</div>
          <div class="vdate">${esc(v.hash)} · ${esc(v.date)}</div></div>
        ${right}</div>`;
    }).join("");
    $("versionList").innerHTML = rows || "Keine Historie verfügbar.";
  } catch (e) {
    $("versionList").textContent = "Historie konnte nicht geladen werden.";
  }
}

function waitAndReload(msgId) {
  setMsg(msgId, "Neustart läuft – Seite lädt automatisch neu …", true);
  let tries = 0;
  setTimeout(() => {
    const t = setInterval(async () => {
      tries++;
      try {
        const r = await fetch("/api/version", { cache: "no-store" });
        if (r.ok) { clearInterval(t); location.reload(); return; }
      } catch (e) { /* Server noch im Neustart */ }
      if (tries > 20) { clearInterval(t); location.reload(); }
    }, 1500);
  }, 4000);
}

$("btnUpdate").addEventListener("click", async () => {
  if (!confirm("Auf die neueste Version aktualisieren? Die Anzeige startet dabei kurz neu.")) return;
  setMsg("updateMsg", "Update wird eingespielt …", true);
  try {
    const res = await (await fetch("/api/update", { method: "POST" })).json();
    if (res.ok) waitAndReload("updateMsg");
    else setMsg("updateMsg", "✗ " + (res.error || "Fehler"), false);
  } catch (e) { setMsg("updateMsg", "✗ " + e, false); }
});

window.rollbackTo = async function (hash) {
  if (!confirm("Auf Version " + hash + " zurückwechseln? Die Anzeige startet dabei kurz neu.")) return;
  setMsg("updateMsg", "Wechsle auf " + hash + " …", true);
  try {
    const res = await (await fetch("/api/rollback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hash }) })).json();
    if (res.ok) waitAndReload("updateMsg");
    else setMsg("updateMsg", "✗ " + (res.error || "Fehler"), false);
  } catch (e) { setMsg("updateMsg", "✗ " + e, false); }
};

load();
loadVersion();
loadVersions();
loadSmsStatus();
