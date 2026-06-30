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
"""
import json
import os
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from modbus_reader import Reading, ModbusPoller, compute_grid_power

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
EXAMPLE_PATH = os.path.join(BASE_DIR, "config.example.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")

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
        "power_kw": power,
        "max_power_kw": max_kw,
        "warn_percent": warn_pct,
        "critical_percent": crit_pct,
        "percent": None,
        "level": "offline",        # offline | ok | warn | critical
        "phases_kw": [snapshot.get("power_l1_kw"), snapshot.get("power_l2_kw"), snapshot.get("power_l3_kw")],
        "currents_a": [snapshot.get("current_l1_a"), snapshot.get("current_l2_a"), snapshot.get("current_l3_a")],
        "channels": snapshot.get("channels", []),
        "ts": snapshot.get("ts"),
        "stale": (time.time() - (snapshot.get("ts") or 0)) > 10,
    }

    if not online or power is None:
        return state

    # Nur Bezug ist relevant: negative Werte (Einspeisung) = 0 % Last
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


# --- App-Setup ---------------------------------------------------------------
app = FastAPI(title="Küchen-Lastmonitor")
reading = Reading()
poller = ModbusPoller(get_config, reading)


@app.on_event("startup")
def _startup():
    load_config()
    poller.start()


@app.on_event("shutdown")
def _shutdown():
    poller.stop()


@app.get("/")
def display():
    return FileResponse(os.path.join(STATIC_DIR, "display.html"))


@app.get("/settings")
def settings_page():
    return FileResponse(os.path.join(STATIC_DIR, "settings.html"))


@app.get("/api/state")
def api_state():
    return JSONResponse(compute_status(reading.snapshot(), get_config()))


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


# Statische Assets (CSS/JS)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
