// Einstellungen laden, testen, speichern.
const $ = (id) => document.getElementById(id);

const PROFILES = {
  nativ: {
    port: 503, function: "input", datatype: "int32", power_scale: 0.001,
    byte_order: "big", word_order: "big",
    registers: { power_total: 2, production: 0, power_l1: null, power_l2: null, power_l3: null,
                 current_l1: null, current_l2: null, current_l3: null },
    show_phases: false,
  },
  gateway: {
    port: 1502, function: "holding", datatype: "float32", power_scale: 1000,
    byte_order: "big", word_order: "big",
    registers: { power_total: 0, production: null, power_l1: 2, power_l2: 4, power_l3: 6,
                 current_l1: 30, current_l2: 32, current_l3: 34 },
    show_phases: true,
  },
};

function numOrNull(v) {
  if (v === "" || v === null || v === undefined) return null;
  const n = parseInt(v);
  return Number.isNaN(n) ? null : n;
}

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
        power_total: numOrNull($("r_power_total").value) ?? 2,
        production: numOrNull($("r_production").value),
        power_l1: numOrNull($("r_power_l1").value),
        power_l2: numOrNull($("r_power_l2").value),
        power_l3: numOrNull($("r_power_l3").value),
        current_l1: numOrNull($("r_current_l1").value),
        current_l2: numOrNull($("r_current_l2").value),
        current_l3: numOrNull($("r_current_l3").value),
      },
    },
    limits: {
      max_power_kw: parseFloat($("max_power_kw").value) || 43,
      warn_percent: parseFloat($("warn_percent").value) || 80,
      critical_percent: parseFloat($("critical_percent").value) || 95,
    },
    display: {
      title: $("d_title").value,
      warn_text: $("d_warn_text").value,
      critical_text: $("d_critical_text").value,
      show_phases: $("d_show_phases").checked,
    },
  };
}

function setReg(id, v) { $(id).value = (v === null || v === undefined) ? "" : v; }

function apply(cfg) {
  const m = cfg.modbus || {};
  const r = m.registers || {};
  const l = cfg.limits || {};
  const d = cfg.display || {};
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
  setReg("r_power_l1", r.power_l1);
  setReg("r_power_l2", r.power_l2);
  setReg("r_power_l3", r.power_l3);
  setReg("r_current_l1", r.current_l1);
  setReg("r_current_l2", r.current_l2);
  setReg("r_current_l3", r.current_l3);
  $("max_power_kw").value = l.max_power_kw ?? 43;
  $("warn_percent").value = l.warn_percent ?? 80;
  $("critical_percent").value = l.critical_percent ?? 95;
  $("d_title").value = d.title ?? "Küche – Netzbezug";
  $("d_warn_text").value = d.warn_text ?? "Achtung – Leistung beobachten";
  $("d_critical_text").value = d.critical_text ?? "STROM REDUZIEREN!";
  $("d_show_phases").checked = d.show_phases === true;
  $("poll_interval_s").value = cfg.poll_interval_s ?? 1;
  updateVisibility();
}

function applyProfile(name) {
  const p = PROFILES[name];
  if (!p) return; // custom: nichts überschreiben
  $("port").value = p.port;
  $("function").value = p.function;
  $("datatype").value = p.datatype;
  $("power_scale").value = p.power_scale;
  $("byte_order").value = p.byte_order;
  $("word_order").value = p.word_order;
  setReg("r_power_total", p.registers.power_total);
  setReg("r_production", p.registers.production);
  setReg("r_power_l1", p.registers.power_l1);
  setReg("r_power_l2", p.registers.power_l2);
  setReg("r_power_l3", p.registers.power_l3);
  setReg("r_current_l1", p.registers.current_l1);
  setReg("r_current_l2", p.registers.current_l2);
  setReg("r_current_l3", p.registers.current_l3);
  $("d_show_phases").checked = p.show_phases;
  updateVisibility();
}

function updateVisibility() {
  $("prodField").style.display = $("grid_mode").value === "calc" ? "" : "none";
  $("phaseCard").style.display = $("profile").value === "gateway" ? "" : "none";
}

async function load() {
  try {
    const r = await fetch("/api/config");
    apply(await r.json());
  } catch (e) {
    setMsg("saveMsg", "Konfiguration konnte nicht geladen werden: " + e, false);
  }
}

function setMsg(id, text, ok) {
  const el = $(id);
  el.textContent = text;
  el.className = "msg " + (ok ? "ok" : "err");
}

$("profile").addEventListener("change", () => applyProfile($("profile").value));
$("grid_mode").addEventListener("change", updateVisibility);

$("btnSave").addEventListener("click", async () => {
  setMsg("saveMsg", "Speichere …", true);
  try {
    const r = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collect()),
    });
    const res = await r.json();
    if (res.ok) setMsg("saveMsg", "✓ Gespeichert. Die Anzeige übernimmt die Werte automatisch.", true);
    else setMsg("saveMsg", "Fehler beim Speichern.", false);
  } catch (e) {
    setMsg("saveMsg", "Fehler: " + e, false);
  }
});

$("btnTest").addEventListener("click", async () => {
  setMsg("testMsg", "Teste Verbindung …", true);
  try {
    const r = await fetch("/api/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modbus: collect().modbus }),
    });
    const res = await r.json();
    if (res.ok) setMsg("testMsg", `✓ Verbindung OK – aktueller Netzbezug: ${res.power_kw} kW (Rohwert ${res.raw})`, true);
    else setMsg("testMsg", "✗ " + (res.error || "Fehlgeschlagen"), false);
  } catch (e) {
    setMsg("testMsg", "✗ Fehler: " + e, false);
  }
});

load();
