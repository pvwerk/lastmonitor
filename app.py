"""
Küchen-Lastmonitor – Webserver (FastAPI).

Liest per Hintergrund-Thread die Werte aus dem PLEXLOG PL 100 (Modbus TCP) und
stellt zwei Oberflächen bereit:
  /          -> Vollbild-Anzeige für den Küchenmonitor (Chromium-Kiosk)
  /settings  -> Einstellungen (von jedem Rechner im Netz erreichbar)

API:
  GET  /api/state    -> aktueller Messwert + berechneter Auslastungs-Status
  GET  /api/stream   -> Server-Sent-Events (Live-Push an die Anzeige)
  GET  /api/config   -> aktuelle Konfiguration
  POST /api/config   -> Konfiguration speichern
  POST /api/test     -> Verbindung mit gegebener Konfig testen
  GET  /api/remote-report/status -> Status des Fernwartungs-Selbstberichts

Fernwartung: sendet bei config.remote_report.enabled=true regelmäßig einen
Selbst-Bericht (IP, Modbus-Konfig, Live-Status) an api/external/device-report.js
im PVWERK-CRM, damit der Pi nach der Inbetriebnahme auch an einem anderen
Standort (anderes Netzwerk) aus der Ferne diagnostizierbar bleibt.
"""
import json
import os
import re
import sys
import subprocess
import threading
import time
import urllib.request
import urllib.parse
import urllib.error

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from modbus_reader import Reading, ModbusPoller, compute_grid_power, scan_registers

import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
EXAMPLE_PATH = os.path.join(BASE_DIR, "config.example.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")
BASELINE_PATH = os.path.join(BASE_DIR, "energy_baselines.json")
COSTS_PATH = os.path.join(BASE_DIR, "daily_costs.json")

_config_lock = threading.Lock()
_config = {}


def load_config():
    global _config
    path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else EXAMPLE_PATH
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    with _config_lock:
        _config = cfg
    return cfg


def get_config():
    with _config_lock:
        return json.loads(json.dumps(_config))  # tiefe Kopie


def save_config(cfg):
    global _config
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    with _config_lock:
        _config = cfg


_baselines = None


def _load_baselines():
    global _baselines
    if _baselines is None:
        try:
            with open(BASELINE_PATH, "r", encoding="utf-8") as f:
                _baselines = json.load(f)
        except Exception:
            _baselines = {}
    return _baselines


def _save_baselines():
    try:
        with open(BASELINE_PATH, "w", encoding="utf-8") as f:
            json.dump(_baselines, f)
    except Exception:
        pass


def energy_periods(gesamtertrag, gesamtverbrauch):
    """Woche/Monat = aktueller Gesamtzähler − Stand bei Perioden-Beginn.
    Beim ersten Sehen einer Woche/eines Monats wird der aktuelle Stand als
    Basis gespeichert (die erste Periode ist daher anteilig ab Mess-Start)."""
    out = {"week_ertrag": None, "week_verbrauch": None, "month_ertrag": None, "month_verbrauch": None}
    if gesamtertrag is None and gesamtverbrauch is None:
        return out
    now = datetime.datetime.now()
    iso = now.isocalendar()
    keys = {"week": f"{iso[0]}-W{iso[1]:02d}", "month": f"{now.year}-{now.month:02d}"}
    b = _load_baselines()
    changed = False
    for k, period in keys.items():
        rec = b.get(k)
        if not rec or rec.get("key") != period:
            b[k] = {"key": period, "ge": gesamtertrag, "gv": gesamtverbrauch}
            changed = True
    if changed:
        _save_baselines()

    def delta(cur, base):
        if cur is None or base is None:
            return None
        return max(0.0, round(cur - base, 1))

    out["week_ertrag"] = delta(gesamtertrag, b["week"].get("ge"))
    out["week_verbrauch"] = delta(gesamtverbrauch, b["week"].get("gv"))
    out["month_ertrag"] = delta(gesamtertrag, b["month"].get("ge"))
    out["month_verbrauch"] = delta(gesamtverbrauch, b["month"].get("gv"))
    return out


# --- Standby-Zeitfenster (Bildschirm-Anzeige AN/AUS je Wochentag) ------------
# Berechnet nur den Soll-Zustand; die Kiosk-Anzeige (display.js) pollt
# /api/standby-state und blendet außerhalb des Fensters selbst ab (schwarzer
# Vollbild-Overlay). Bewusst KEIN Hardware-DPMS/wlr-randr-Aufruf von hier aus:
# der Kiosk läuft unter Wayland (labwc) mit einem "Headless"-Ausgang – den
# abzuschalten bringt den gesamten Compositor zum Absturz (empirisch
# getestet am 09.07.2026, per Reboot wiederhergestellt). Software-Abblendung
# im bereits laufenden Browser ist der abstürzsichere Weg.
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_standby_state = {"should_be_on": None, "last_check": None}


def _resolve_standby_window(days, weekday_idx, _depth=0):
    """Folgt 'same_as_prev'-Ketten rückwärts (zyklisch über die Woche, max. 7 Schritte)."""
    if _depth > 7:
        return None
    key = WEEKDAYS[weekday_idx % 7]
    rec = (days or {}).get(key) or {}
    if rec.get("same_as_prev"):
        return _resolve_standby_window(days, weekday_idx - 1, _depth + 1)
    on, off = rec.get("on"), rec.get("off")
    if not on or not off:
        return None
    return on, off


def _parse_hm(s):
    try:
        h, m = str(s).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def standby_is_on_now(cfg, now=None):
    """True = Bildschirm soll AN sein. Bei deaktiviertem Feature oder kaputter/fehlender
    Konfiguration bewusst immer True – Ausfallsicher (lieber dauerhaft an als versehentlich aus)."""
    sb = ((cfg.get("display") or {}).get("standby")) or {}
    if not sb.get("enabled"):
        return True
    now = now or datetime.datetime.now()
    window = _resolve_standby_window(sb.get("days"), now.weekday())
    if not window:
        return True
    on_m, off_m = _parse_hm(window[0]), _parse_hm(window[1])
    if on_m is None or off_m is None or on_m == off_m:
        return True
    cur_m = now.hour * 60 + now.minute
    if on_m < off_m:
        return on_m <= cur_m < off_m
    return cur_m >= on_m or cur_m < off_m  # Fenster über Mitternacht


def standby_loop():
    while True:
        try:
            cfg = get_config()
            _standby_state["should_be_on"] = standby_is_on_now(cfg)
            _standby_state["last_check"] = time.time()
        except Exception:
            pass
        time.sleep(15)


# --- Kosten (Verbrauch/Eigenverbrauch, Heute + Vortag) -----------------------
# Läuft unabhängig von der Anzeige weiter (auch wenn "auf Anzeige zeigen" aus
# ist) und integriert die Momentanleistungen selbst zu Tages-kWh, da das
# PLEXLOG dafür keine eigenen Register liefert (anders als Tagesertrag/
# -verbrauch, die direkt vom Gerät kommen). Eigenverbrauch = der Teil des
# Verbrauchs, der aus eigener PV-Erzeugung gedeckt wird = min(Erzeugung,
# Verbrauch) im Moment. Persistiert höchstens alle 60s (SD-Karten-Schonung),
# nicht bei jedem Tick.
_costs_lock = threading.Lock()
_costs_state = {
    "today": {"date": None, "verbrauch_kwh": 0.0, "eigenverbrauch_kwh": 0.0},
    "prev": {"date": None, "verbrauch_kwh": 0.0, "eigenverbrauch_kwh": 0.0},
}
_costs_last_tick = None
_costs_last_save = 0.0


def _load_costs():
    global _costs_state
    try:
        with open(COSTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _costs_lock:
            if isinstance(data.get("today"), dict):
                _costs_state["today"] = data["today"]
            if isinstance(data.get("prev"), dict):
                _costs_state["prev"] = data["prev"]
    except Exception:
        pass


def _save_costs():
    try:
        with _costs_lock:
            data = json.loads(json.dumps(_costs_state))
        with open(COSTS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def _enrich_costs_day(d, bezug_eur_kwh, pv_eur_kwh):
    v = float(d.get("verbrauch_kwh") or 0.0)
    e = min(float(d.get("eigenverbrauch_kwh") or 0.0), v)
    netzbezug = max(0.0, v - e)
    out = dict(d)
    out["verbrauch_kwh"] = round(v, 2)
    out["eigenverbrauch_kwh"] = round(e, 2)
    out["kosten_eur"] = round(netzbezug * bezug_eur_kwh + e * pv_eur_kwh, 2)
    return out


def costs_snapshot():
    cfg = get_config()
    cc = cfg.get("costs") or {}
    bezug = float(cc.get("bezug_eur_kwh", 0) or 0)
    pv = float(cc.get("pv_eur_kwh", 0) or 0)
    with _costs_lock:
        today = dict(_costs_state["today"])
        prev = dict(_costs_state["prev"])
    return {
        "show_on_display": bool(cc.get("show_on_display")),
        "bezug_eur_kwh": bezug,
        "pv_eur_kwh": pv,
        "today": _enrich_costs_day(today, bezug, pv),
        "prev": _enrich_costs_day(prev, bezug, pv),
    }


def cost_loop():
    global _costs_last_tick, _costs_last_save
    _load_costs()
    while True:
        try:
            now = time.time()
            today_key = datetime.date.today().isoformat()
            with _costs_lock:
                if _costs_state["today"].get("date") != today_key:
                    if _costs_state["today"].get("date") is not None:
                        _costs_state["prev"] = dict(_costs_state["today"])
                    _costs_state["today"] = {"date": today_key, "verbrauch_kwh": 0.0, "eigenverbrauch_kwh": 0.0}
                    _costs_last_tick = now  # kein Integrations-Sprung über den Tageswechsel hinweg
            snap = reading.snapshot()
            cons = snap.get("consumption_kw")
            prod = snap.get("production_kw")
            if _costs_last_tick is not None and cons is not None:
                # Bei Ausreißern (z. B. nach Verbindungsausfall) die Zeitspanne kappen,
                # statt einen künstlich hohen kWh-Sprung zu verbuchen.
                dt_h = max(0.0, min(now - _costs_last_tick, 120.0)) / 3600.0
                eigen_kw = max(0.0, min(prod or 0.0, cons))
                with _costs_lock:
                    _costs_state["today"]["verbrauch_kwh"] = float(_costs_state["today"].get("verbrauch_kwh") or 0.0) + max(0.0, cons) * dt_h
                    _costs_state["today"]["eigenverbrauch_kwh"] = float(_costs_state["today"].get("eigenverbrauch_kwh") or 0.0) + eigen_kw * dt_h
            _costs_last_tick = now
            if now - _costs_last_save > 60:
                _save_costs()
                _costs_last_save = now
        except Exception:
            pass
        time.sleep(5)


def compute_status(snapshot, cfg):
    """Auslastung + Ampelfarbe + Warnflag aus Messwert und Grenzwerten."""
    limits = cfg.get("limits", {})
    max_kw = float(limits.get("max_power_kw", 43) or 43)
    warn_pct = float(limits.get("warn_percent", 80))
    crit_pct = float(limits.get("critical_percent", 95))

    power = snapshot.get("power_kw")
    online = snapshot.get("online")

    state = {
        "online": online,
        "error": snapshot.get("error"),
        "power_kw": power,                              # Netzbezug, signiert
        "production_kw": snapshot.get("production_kw"), # Erzeugung (PV)
        "consumption_kw": snapshot.get("consumption_kw"), # Gesamtverbrauch
        "direction": None,                              # bezug | einspeisung
        "max_power_kw": max_kw,
        "warn_percent": warn_pct,
        "critical_percent": crit_pct,
        "percent": None,
        "level": "offline",        # offline | ok | warn | critical
        "meters": snapshot.get("meters", []),
        "tagesertrag_kwh": snapshot.get("tagesertrag_kwh"),
        "tagesverbrauch_kwh": snapshot.get("tagesverbrauch_kwh"),
        "phases_kw": [snapshot.get("power_l1_kw"), snapshot.get("power_l2_kw"), snapshot.get("power_l3_kw")],
        "currents_a": [snapshot.get("current_l1_a"), snapshot.get("current_l2_a"), snapshot.get("current_l3_a")],
        "ts": snapshot.get("ts"),
        "stale": (time.time() - (snapshot.get("ts") or 0)) > 10,
    }
    state.update(energy_periods(snapshot.get("gesamtertrag_kwh"), snapshot.get("gesamtverbrauch_kwh")))

    if not online or power is None:
        return state

    # Richtung: + = Bezug aus dem Netz, − = Einspeisung
    state["direction"] = "einspeisung" if power < -0.01 else "bezug"

    # Auslastung des Netzanschlusses: nur Bezug zählt (Einspeisung = 0 %)
    bezug = max(0.0, power)
    pct = (bezug / max_kw * 100.0) if max_kw > 0 else 0.0
    state["percent"] = round(pct, 1)
    if pct >= crit_pct:
        state["level"] = "critical"
    elif pct >= warn_pct:
        state["level"] = "warn"
    else:
        state["level"] = "ok"
    return state


# --- SMS-Benachrichtigung (seven.io) ------------------------------------------
# Jeder kann sich in den Einstellungen selbst einen eigenen seven.io-Account
# (app.seven.io/signup, 0,50 € Testguthaben) anlegen, dort einen API-Key holen
# und zusammen mit Telefonnummer + eigener Schwelle hier hinterlegen. Löst aus,
# wenn der Netzbezug (%) die Schwelle über-/unterschreitet — mit Cooldown gegen
# SMS-Spam, solange der kritische Zustand anhält.

def normalize_de_number(raw):
    """+49… / 0049… / 0…  ->  49…  (seven.io-Format, ohne führendes +)."""
    if not raw:
        return None
    s = re.sub(r"[^\d+]", "", str(raw))
    if s.startswith("+"):
        s = s[1:]
    elif s.startswith("00"):
        s = s[2:]
    elif s.startswith("0"):
        s = "49" + s[1:]
    if not re.fullmatch(r"\d{8,15}", s):
        return None
    return s


SEVEN_ERROR_MESSAGES = {
    "101": "Senden an mindestens einen Empfänger fehlgeschlagen.",
    "201": "Absendername ungültig (max. 11 Zeichen).",
    "202": "Telefonnummer ungültig.",
    "301": "Keine Telefonnummer angegeben.",
    "401": "Text zu lang.",
    "402": "Diese SMS wurde in den letzten 180 Sekunden bereits gesendet.",
    "403": "Tageslimit für diese Nummer erreicht.",
    "500": "Zu wenig Guthaben auf dem seven.io-Konto.",
    "600": "Fehler beim Versand bei seven.io.",
    "900": "API-Key ungültig — bitte in den seven.io-Einstellungen prüfen.",
    "901": "Signaturprüfung fehlgeschlagen.",
    "902": "Dieser API-Key hat keine Berechtigung für SMS-Versand.",
    "903": "Absender-IP ist bei seven.io nicht freigegeben.",
}


def seven_error_message(raw):
    code = raw.get("success") if isinstance(raw, dict) else raw
    return SEVEN_ERROR_MESSAGES.get(str(code), f"seven.io-Fehlercode: {code}")


def send_sms_seven(api_key, sender, to, text):
    """POST an die seven.io-API. Wirft bei Netzwerk-/HTTP-Fehlern eine Exception."""
    params = {"to": to, "text": text}
    if sender:
        params["from"] = sender
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        "https://gateway.seven.io/api/sms",
        data=data,
        headers={
            "X-Api-Key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw_text = resp.read().decode("utf-8")
    # seven.io liefert bei Erfolg ein JSON-Objekt ({"success":"100",...}),
    # bei Fehlern aber oft nur einen nackten JSON-String mit Fehlercode (z. B. "900"
    # = ungültiger API-Key) — also robust gegen beide Formen sein.
    try:
        body = json.loads(raw_text)
    except Exception:
        body = raw_text
    ok = isinstance(body, dict) and str(body.get("success")) == "100"
    return {"ok": ok, "raw": body}


_sms_state = {
    "last_sent_ts": 0.0, "last_result": None,   # nur für die Status-Anzeige in /settings
    "power_phase": None, "power_last_sent_ts": 0.0,
    "conn_phase": None, "conn_last_sent_ts": 0.0, "offline_since": None,
}
_sms_lock = threading.Lock()


def _sms_send_and_record(sms_cfg, text):
    """Schickt die SMS und merkt sich das Ergebnis für die Status-Anzeige.
    Cooldown-Zeitstempel pflegt der jeweilige Aufrufer selbst (getrennt je
    Alarmtyp, damit sich Leistungs- und Verbindungs-Alarme nicht gegenseitig
    den Cooldown zurücksetzen)."""
    api_key = (sms_cfg.get("api_key") or "").strip()
    phone = normalize_de_number(sms_cfg.get("phone_number"))
    if not api_key or not phone:
        return
    try:
        result = send_sms_seven(api_key, sms_cfg.get("sender") or "Lastmonitor", phone, text)
        if not result["ok"]:
            result["error"] = seven_error_message(result["raw"])
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    _sms_state["last_sent_ts"] = time.time()
    _sms_state["last_result"] = result


def sms_check(state, cfg):
    """Leistungs-Schwelle: einmal pro Tick prüfen und ggf. SMS verschicken."""
    sms_cfg = cfg.get("sms") or {}
    if not sms_cfg.get("enabled"):
        return
    if not state.get("online") or state.get("percent") is None:
        return

    threshold = float(sms_cfg.get("threshold_percent") or cfg.get("limits", {}).get("critical_percent", 95))
    cooldown_s = max(1.0, float(sms_cfg.get("cooldown_minutes") or 15)) * 60.0
    notify_recovery = sms_cfg.get("notify_recovery", True)
    pct = state["percent"]
    title = (cfg.get("display") or {}).get("title") or "Lastmonitor"
    now = time.time()

    with _sms_lock:
        was_over = _sms_state["power_phase"] == "over"
        is_over = pct >= threshold

        if is_over and not was_over:
            _sms_state["power_phase"] = "over"
            _sms_state["power_last_sent_ts"] = now
            _sms_send_and_record(sms_cfg, f"{title}: Netzbezug {pct:.0f}% (Schwelle {threshold:.0f}%) – bitte Verbrauch reduzieren.")
        elif is_over and was_over:
            # weiterhin kritisch -> nur nach Ablauf des Cooldowns erneut erinnern
            if now - _sms_state["power_last_sent_ts"] >= cooldown_s:
                _sms_state["power_last_sent_ts"] = now
                _sms_send_and_record(sms_cfg, f"{title}: weiterhin hoher Netzbezug ({pct:.0f}%).")
        elif not is_over and was_over:
            _sms_state["power_phase"] = "ok"
            if notify_recovery:
                _sms_state["power_last_sent_ts"] = now
                _sms_send_and_record(sms_cfg, f"{title}: Netzbezug wieder normal ({pct:.0f}%).")
        elif _sms_state["power_phase"] is None:
            _sms_state["power_phase"] = "ok"


def sms_check_connection(state, cfg):
    """Verbindung zum Messgerät (PLEXLOG): SMS, wenn die Verbindung länger als
    connection_loss_after_minutes weg ist — ohne Verbindung werden Überlast-
    Schwellen NICHT überwacht, das soll niemand unbemerkt verpassen. Danach
    Erinnerungen im gleichen Cooldown-Abstand wie beim Leistungs-Alarm, plus
    eine „wieder da"-SMS bei Rückkehr.
    Wichtiger Vorbehalt: Fällt das Internet selbst aus, kann in dem Moment
    KEINE SMS raus — das lässt sich technisch nicht umgehen. Sobald die
    Verbindung (Gerät + Internet) wieder da ist, kommt eine Nachricht."""
    sms_cfg = cfg.get("sms") or {}
    if not sms_cfg.get("enabled") or not sms_cfg.get("notify_connection_loss"):
        with _sms_lock:
            _sms_state["conn_phase"] = None
            _sms_state["offline_since"] = None
        return

    online = bool(state.get("online")) and not state.get("stale")
    after_s = max(0.5, float(sms_cfg.get("connection_loss_after_minutes") or 3)) * 60.0
    cooldown_s = max(1.0, float(sms_cfg.get("cooldown_minutes") or 15)) * 60.0
    notify_recovery = sms_cfg.get("notify_recovery", True)
    title = (cfg.get("display") or {}).get("title") or "Lastmonitor"
    now = time.time()

    with _sms_lock:
        was_offline = _sms_state["conn_phase"] == "offline"

        if not online:
            if _sms_state["offline_since"] is None:
                _sms_state["offline_since"] = now
            duration_min = (now - _sms_state["offline_since"]) / 60.0
            if (now - _sms_state["offline_since"]) < after_s:
                return  # noch innerhalb der Toleranz (kurzer Aussetzer) — kein Alarm
            if not was_offline:
                _sms_state["conn_phase"] = "offline"
                _sms_state["conn_last_sent_ts"] = now
                _sms_send_and_record(sms_cfg, f"{title}: Verbindung zum Messgerät seit {duration_min:.0f} Min. verloren — Überlast wird gerade NICHT überwacht!")
            elif now - _sms_state["conn_last_sent_ts"] >= cooldown_s:
                _sms_state["conn_last_sent_ts"] = now
                _sms_send_and_record(sms_cfg, f"{title}: Verbindung zum Messgerät weiterhin gestört (seit {duration_min:.0f} Min.).")
        else:
            if was_offline and notify_recovery:
                _sms_state["conn_last_sent_ts"] = now
                _sms_send_and_record(sms_cfg, f"{title}: Verbindung zum Messgerät wieder da.")
            _sms_state["conn_phase"] = "ok"
            _sms_state["offline_since"] = None


# --- Fernwartung: periodischer Selbst-Bericht -------------------------------
# Der Pi läuft nach der Inbetriebnahme an einem anderen Standort (nicht mehr
# im selben Netzwerk erreichbar). Damit Fernwartung/-diagnose während der
# Inbetriebnahme trotzdem möglich ist, schickt der Pi sich selbst regelmäßig
# einen vollständigen Status-Bericht an einen kleinen Endpoint im PVWERK-CRM
# (api/external/device-report.js, geteiltes Secret statt Login — der Pi ist
# kein CRM-Nutzer). Enthält bewusst ALLES, was für eine Ferndiagnose nötig
# ist (IP, Modbus-Konfiguration, Live-Status) — aber keine Geheimnisse
# (SMS-API-Key wird nur als "gesetzt: ja/nein" gemeldet, nicht im Klartext).
_report_state = {"last_sent_ts": 0.0, "last_ok": None, "last_error": None}
_process_start_ts = time.time()


def _local_ip():
    """Beste Schätzung der lokalen IP (ohne tatsächlich Daten zu senden)."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return None


def _device_id():
    """Stabile Geräte-Kennung: Raspberry-Pi-Seriennummer aus /proc/cpuinfo,
    sonst Hostname (z.B. beim lokalen Testen auf dem Mac)."""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("Serial"):
                    return "pi-" + line.split(":")[-1].strip()
    except Exception:
        pass
    import socket
    return socket.gethostname()


def build_self_report(cfg):
    """Vollständiger Selbst-Bericht für die Ferndiagnose."""
    import socket
    state = compute_status(reading.snapshot(), cfg)
    modbus_cfg = dict(cfg.get("modbus", {}))
    modbus_cfg.pop("registers", None)  # zu viele Details für den Kurz-Bericht
    sms_cfg = cfg.get("sms", {}) or {}
    return {
        "app_version": current_version(),
        "uptime_s": round(time.time() - _process_start_ts),
        "hostname": socket.gethostname(),
        "local_ip": _local_ip(),
        "modbus_config": modbus_cfg,
        "limits": cfg.get("limits", {}),
        "sms_configured": bool((sms_cfg.get("api_key") or "").strip()),
        "sms_enabled": bool(sms_cfg.get("enabled")),
        "status": {
            "online": state.get("online"),
            "error": state.get("error"),
            "power_kw": state.get("power_kw"),
            "level": state.get("level"),
            "stale": state.get("stale"),
            "last_reading_ts": state.get("ts"),
        },
        "report_generated_at": time.time(),
    }


def send_remote_report(report, rr_cfg):
    """POST an api/external/device-report.js. Wirft bei Fehlern eine Exception."""
    body = json.dumps({
        "device_source": rr_cfg.get("device_source") or "lastmonitor",
        "device_id": _device_id(),
        "report": report,
    }).encode("utf-8")
    endpoint = rr_cfg["endpoint"] + "?secret=" + urllib.parse.quote(rr_cfg.get("secret") or "")
    req = urllib.request.Request(
        endpoint, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def remote_report_loop():
    while True:
        try:
            cfg = get_config()
            rr_cfg = cfg.get("remote_report") or {}
            if rr_cfg.get("enabled") and rr_cfg.get("endpoint") and rr_cfg.get("secret"):
                report = build_self_report(cfg)
                try:
                    send_remote_report(report, rr_cfg)
                    _report_state["last_ok"] = time.time()
                    _report_state["last_error"] = None
                except Exception as e:
                    _report_state["last_error"] = str(e)
                _report_state["last_sent_ts"] = time.time()
        except Exception:
            pass
        interval = 300
        try:
            interval = float((get_config().get("remote_report") or {}).get("interval_s", 300) or 300)
        except Exception:
            pass
        time.sleep(max(30.0, interval))


def sms_monitor_loop():
    while True:
        try:
            cfg = get_config()
            state = compute_status(reading.snapshot(), cfg)
            sms_check(state, cfg)
            sms_check_connection(state, cfg)
        except Exception:
            pass
        time.sleep(15)


# --- App-Setup ---------------------------------------------------------------
app = FastAPI(title="Küchen-Lastmonitor")
reading = Reading()
poller = ModbusPoller(get_config, reading)


@app.on_event("startup")
def _startup():
    load_config()
    poller.start()
    threading.Thread(target=sms_monitor_loop, daemon=True).start()
    threading.Thread(target=remote_report_loop, daemon=True).start()
    threading.Thread(target=standby_loop, daemon=True).start()
    threading.Thread(target=cost_loop, daemon=True).start()


@app.on_event("shutdown")
def _shutdown():
    poller.stop()
    _save_costs()


@app.get("/")
def display():
    return FileResponse(os.path.join(STATIC_DIR, "display.html"))


@app.get("/settings")
def settings_page():
    return FileResponse(os.path.join(STATIC_DIR, "settings.html"))


@app.get("/api/state")
def api_state():
    return JSONResponse(compute_status(reading.snapshot(), get_config()))


@app.get("/api/standby-state")
def api_standby_state():
    cfg = get_config()
    sb = (cfg.get("display") or {}).get("standby") or {}
    now = datetime.datetime.now()
    window = _resolve_standby_window(sb.get("days"), now.weekday()) if sb.get("enabled") else None
    return JSONResponse({
        "enabled": bool(sb.get("enabled")),
        "should_be_on": _standby_state.get("should_be_on"),
        "today_window": {"on": window[0], "off": window[1]} if window else None,
        "last_check": _standby_state.get("last_check"),
    })


@app.get("/api/costs")
def api_costs():
    return JSONResponse(costs_snapshot())


# --- Auto-Reload der Kiosk-Anzeige nach Einstellungs-Änderungen --------------
# Die Anzeige (display.js) pollt /api/reload-token und lädt sich selbst neu,
# sobald sich der Wert ändert. Der Settings-Button "Speichern & neu laden"
# löst das über /api/reload aus – dadurch übernimmt der Chromium-Kiosk
# Layout-/Code-Änderungen automatisch, ohne dass jemand am Pi selbst
# eingreifen muss.
_reload_token = {"value": time.time()}


@app.get("/api/reload-token")
def api_reload_token():
    return JSONResponse({"token": _reload_token["value"]})


@app.post("/api/reload")
def api_trigger_reload():
    _reload_token["value"] = time.time()
    return JSONResponse({"ok": True, "token": _reload_token["value"]})


@app.get("/api/remote-report/status")
def api_remote_report_status():
    """Zeigt den Zustand des Selbst-Berichts in /settings an (letzter Versand, Fehler)."""
    return JSONResponse(_report_state)


@app.get("/api/stream")
def api_stream():
    def gen():
        last = None
        while True:
            cfg = get_config()
            state = compute_status(reading.snapshot(), cfg)
            payload = json.dumps(state)
            if payload != last:
                last = payload
                yield f"data: {payload}\n\n"
            else:
                yield ": keep-alive\n\n"
            time.sleep(float(cfg.get("poll_interval_s", 1.0) or 1.0))
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/config")
def api_get_config():
    return JSONResponse(get_config())


@app.post("/api/config")
async def api_set_config(request: Request):
    new_cfg = await request.json()
    # Bestehende Konfig als Basis, damit unbekannte Felder erhalten bleiben
    cfg = get_config()
    cfg.update(new_cfg)
    save_config(cfg)
    return JSONResponse({"ok": True, "config": cfg})


@app.post("/api/test")
async def api_test(request: Request):
    """Verbindung mit (optional übergebener) Konfig kurz testen."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    mb = (body.get("modbus") if isinstance(body, dict) else None) or get_config().get("modbus", {})
    try:
        from pymodbus.client import ModbusTcpClient
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"pymodbus fehlt: {e}"}, status_code=500)

    host = (mb.get("host") or "").strip()
    if not host:
        return JSONResponse({"ok": False, "error": "Keine IP-Adresse angegeben"}, status_code=400)
    port = int(mb.get("port", 503))
    unit = int(mb.get("unit_id", 1))
    scale = float(mb.get("power_scale", 0.001))
    sgn = -1.0 if mb.get("invert_sign") else 1.0
    client = ModbusTcpClient(host=host, port=port, timeout=3)
    try:
        if not client.connect():
            return JSONResponse({"ok": False, "error": f"Verbindung zu {host}:{port} fehlgeschlagen"})
        raw = compute_grid_power(client, mb, unit)
        if raw is None:
            return JSONResponse({"ok": False, "error": "Kein Wert gelesen"})
        return JSONResponse({"ok": True, "power_kw": round(sgn * raw * scale, 3), "raw": raw})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})
    finally:
        client.close()


@app.post("/api/sms/test")
async def api_sms_test(request: Request):
    """Test-SMS mit der (ggf. noch ungespeicherten) Konfig aus dem Formular senden."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    sms_cfg = (body.get("sms") if isinstance(body, dict) else None) or get_config().get("sms", {})
    api_key = (sms_cfg.get("api_key") or "").strip()
    phone = normalize_de_number(sms_cfg.get("phone_number"))
    if not api_key:
        return JSONResponse({"ok": False, "error": "Kein seven.io-API-Key hinterlegt."})
    if not phone:
        return JSONResponse({"ok": False, "error": "Ungültige Telefonnummer."})
    try:
        result = send_sms_seven(api_key, sms_cfg.get("sender") or "Lastmonitor", phone,
                                 "Test-SMS vom Küchen-Lastmonitor – die Benachrichtigung ist eingerichtet.")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8"))
        except Exception:
            detail = str(e)
        return JSONResponse({"ok": False, "error": f"seven.io HTTP {e.code}", "detail": detail})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})
    if result["ok"]:
        return JSONResponse({"ok": True, "balance": result["raw"].get("balance")})
    return JSONResponse({"ok": False, "error": seven_error_message(result["raw"]), "detail": result["raw"]})


@app.get("/api/sms/status")
def api_sms_status():
    with _sms_lock:
        s = dict(_sms_state)
    s["last_sent_at"] = (
        datetime.datetime.fromtimestamp(s["last_sent_ts"]).strftime("%d.%m.%Y %H:%M:%S")
        if s.get("last_sent_ts") else None
    )
    return JSONResponse(s)


@app.post("/api/scan")
async def api_scan(request: Request):
    """Liest einen Registerbereich am Gerät (zum Auffinden von Zähler-Registern)."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    mb = (body.get("modbus") if isinstance(body, dict) else None) or get_config().get("modbus", {})
    unit = int(mb.get("unit_id", 1))
    start = int(body.get("start", 0))
    count = int(body.get("count", 20))           # Anzahl 32-bit-Werte
    function = body.get("function")               # optional override
    count = max(1, min(count, 64))                # Sicherheitslimit
    if not (mb.get("host") or "").strip():
        return JSONResponse({"ok": False, "error": "Keine IP-Adresse angegeben"}, status_code=400)
    try:
        rows = scan_registers(mb, unit, start, count, function=function)
        scale = float(mb.get("power_scale", 0.001))
        for r in rows:
            if "int32" in r:
                r["kw_int32"] = round(r["int32"] * scale, 3)
        return JSONResponse({"ok": True, "rows": rows, "scale": scale})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------------
# Software-Version / Update / Downgrade (über GitHub)
# ---------------------------------------------------------------------------
def _git(args, timeout=120):
    try:
        return subprocess.run(["git"] + args, cwd=BASE_DIR, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        r = subprocess.CompletedProcess(args, 1, "", str(e))
        return r


def _current_branch():
    r = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    b = (r.stdout or "").strip()
    return b if b and b != "HEAD" else "main"


def current_version():
    r = _git(["log", "-1", "--format=%h|%ci|%s"])
    if r.returncode != 0 or not r.stdout.strip():
        return {"hash": None, "date": None, "subject": "unbekannt", "error": (r.stderr or "").strip()}
    h, date, subj = r.stdout.strip().split("|", 2)
    return {"hash": h, "date": date[:16], "subject": subj, "branch": _current_branch()}


def _recent_versions(n=6):
    branch = _current_branch()
    _git(["fetch", "--quiet", "origin"], timeout=30)
    # Versionshistorie vom Remote (zeigt immer die neuesten, egal welcher Stand lokal ausgecheckt ist)
    r = _git(["log", "-n", str(n), "--format=%h|%ci|%s", "origin/" + branch])
    if r.returncode != 0:
        r = _git(["log", "-n", str(n), "--format=%h|%ci|%s"])
    out = []
    for line in (r.stdout or "").strip().splitlines():
        try:
            h, date, subj = line.split("|", 2)
            out.append({"hash": h, "date": date[:16], "subject": subj})
        except ValueError:
            pass
    return out


def _pip_install():
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                        os.path.join(BASE_DIR, "requirements.txt")],
                       cwd=BASE_DIR, capture_output=True, text=True, timeout=300)
    except Exception:
        pass


def _restart_later(delay=1.5):
    """Prozess nach kurzer Verzögerung neu starten (lädt den neuen Code).
    Re-exec funktioniert direkt; unter systemd sorgt Restart=always zusätzlich."""
    def go():
        time.sleep(delay)
        try:
            os.execv(sys.argv[0], sys.argv)
        except Exception:
            os._exit(0)  # Fallback: beenden -> systemd/Wrapper startet neu
    threading.Thread(target=go, daemon=True).start()


@app.get("/api/version")
def api_version():
    cur = current_version()
    branch = cur.get("branch") or "main"
    _git(["fetch", "--quiet", "origin"], timeout=30)
    behind = _git(["rev-list", "--count", "HEAD..origin/" + branch]).stdout.strip() or "0"
    cur["behind"] = behind
    cur["updates_available"] = behind not in ("", "0")
    return JSONResponse(cur)


@app.get("/api/versions")
def api_versions():
    return JSONResponse({"current": current_version().get("hash"), "versions": _recent_versions(6)})


@app.post("/api/update")
def api_update():
    branch = _current_branch()
    _git(["fetch", "origin"], timeout=60)
    r = _git(["reset", "--hard", "origin/" + branch])
    if r.returncode != 0:
        return JSONResponse({"ok": False, "error": (r.stderr or "git-Fehler").strip()}, status_code=500)
    _pip_install()
    ver = current_version()
    _restart_later()
    return JSONResponse({"ok": True, "message": "Update eingespielt – Neustart läuft.", "version": ver})


@app.post("/api/rollback")
async def api_rollback(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    h = (body.get("hash") if isinstance(body, dict) else None) or ""
    # Sicherheit: nur Hashes aus der jüngeren Historie zulassen
    allowed = {v["hash"] for v in _recent_versions(20)}
    if h not in allowed:
        return JSONResponse({"ok": False, "error": "Unbekannte Version."}, status_code=400)
    r = _git(["reset", "--hard", h])
    if r.returncode != 0:
        return JSONResponse({"ok": False, "error": (r.stderr or "git-Fehler").strip()}, status_code=500)
    _pip_install()
    _restart_later()
    return JSONResponse({"ok": True, "message": "Auf Version " + h + " zurückgesetzt – Neustart läuft."})


# Statische Assets (CSS/JS)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
