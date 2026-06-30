// Einstellungen laden, testen, speichern – inkl. Zähler-Editor und Register-Scanner.
const $ = (id) => document.getElementById(id);

const PROFILES = {
  nativ: {
    port: 503, function: "input", datatype: "int32", power_scale: 0.001,
    byte_order: "big", word_order: "big",
    registers: { power_total: 2, production: 0, power_l1: null, power_l2: null, power_l3: null, current_l1: null, current_l2: null, current_l3: null },
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
function collect() {
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
      registers: {
        power_total: intOrNull($("r_power_total").value) ?? 2,
        production: intOrNull($("r_production").value),
        power_l1: intOrNull($("r_power_l1").value),
        power_l2: intOrNull($("r_power_l2").value),
        power_l3: intOrNull($("r_power_l3").value),
        current_l1: intOrNull($("r_current_l1").value),
        current_l2: intOrNull($("r_current_l2").value),
        current_l3: intOrNull($("r_current_l3").value),
      },
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
    },
  };
}

function apply(cfg) {
  const m = cfg.modbus || {}, r = m.registers || {}, l = cfg.limits || {}, d = cfg.display || {};
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
  $("grid_mode").value = m.grid_mode || "register";
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
  updateVisibility();
}

function applyProfile(name) {
  const p = PROFILES[name];
  if (!p) return;
  $("port").value = p.port; $("function").value = p.function; $("datatype").value = p.datatype;
  $("power_scale").value = p.power_scale; $("byte_order").value = p.byte_order; $("word_order").value = p.word_order;
  setReg("r_power_total", p.registers.power_total); setReg("r_production", p.registers.production);
  setReg("r_power_l1", p.registers.power_l1); setReg("r_power_l2", p.registers.power_l2); setReg("r_power_l3", p.registers.power_l3);
  setReg("r_current_l1", p.registers.current_l1); setReg("r_current_l2", p.registers.current_l2); setReg("r_current_l3", p.registers.current_l3);
  updateVisibility();
}
function updateVisibility() {
  $("phaseCard").style.display = $("profile").value === "gateway" ? "" : "none";
}

// ---- Laden / Speichern / Test ----------------------------------------------
async function load() {
  try { const r = await fetch("/api/config"); apply(await r.json()); }
  catch (e) { setMsg("saveMsg", "Konfiguration konnte nicht geladen werden: " + e, false); }
}

$("profile").addEventListener("change", () => applyProfile($("profile").value));
$("btnAddMeter").addEventListener("click", () => addMeter({ type: "modbus" }));

$("btnSave").addEventListener("click", async () => {
  setMsg("saveMsg", "Speichere …", true);
  try {
    const r = await fetch("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collect()) });
    const res = await r.json();
    setMsg("saveMsg", res.ok ? "✓ Gespeichert. Die Anzeige übernimmt die Werte automatisch." : "Fehler beim Speichern.", !!res.ok);
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

load();
