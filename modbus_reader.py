"""
Modbus-TCP-Leser für PLEXLOG PL 100.

Liest in einem Hintergrund-Thread:
  - Netzbezug (signiert: + = Bezug, − = Einspeisung)
  - Erzeugung (PV)
  - beliebig viele Zusatz-Zähler (S0 / Modbus, am Plexlog angeschlossen)
und berechnet den Gesamtverbrauch (= Netzbezug + Erzeugung).

Profile (in den Einstellungen umschaltbar):
  - "nativ"   : Port 503, Input Register (FC4), int32, Watt.
                Reg 0 = PV-Erzeugung, Reg 2 = Verbrauch/Netzbezug.
                (Belegung aus produktiv genutzter evcc-Integration,
                 github.com/evcc-io/evcc Discussion #11661.)
  - "gateway" : Port 1502, Holding (FC3), float32, MW. Wirkleistung Reg 0,
                Phasen 2/4/6, Ströme 30/32/34.

Die genauen Register angeschlossener S0-/Modbus-Zähler stehen in der
Plexlog-Datei „PLOpenGateway_Definitionen.xlsx" (auf Anfrage bei info@plexlog.de)
bzw. lassen sich mit scan_registers() am Gerät empirisch ermitteln.
"""
import struct
import threading
import time

try:
    from pymodbus.client import ModbusTcpClient
except Exception:  # pragma: no cover
    ModbusTcpClient = None


def _swap_words(regs, word_order):
    return [regs[1], regs[0]] if word_order == "little" else [regs[0], regs[1]]


def decode_value(regs, datatype="int32", byte_order="big", word_order="big"):
    """Zwei 16-bit-Register zu int32 / uint32 / float32 dekodieren."""
    if regs is None or len(regs) < 2:
        return None
    hi, lo = _swap_words(regs, word_order)
    bo = ">" if byte_order == "big" else "<"
    raw = struct.pack(bo + "HH", hi, lo)
    if datatype == "float32":
        return struct.unpack(bo + "f", raw)[0]
    if datatype == "uint32":
        return struct.unpack(bo + "I", raw)[0]
    return struct.unpack(bo + "i", raw)[0]


def read_register(client, function, datatype, address, unit, byte_order, word_order):
    """Einen Wert (32-bit, 2 Register) je nach Funktionscode lesen und dekodieren."""
    if address is None:
        return None
    address = int(address)
    if function == "holding":
        rr = client.read_holding_registers(address=address, count=2, slave=unit)
    else:  # "input" (FC4)
        rr = client.read_input_registers(address=address, count=2, slave=unit)
    if rr is None or rr.isError():
        raise IOError(f"Lesefehler Register {address}: {rr}")
    return decode_value(rr.registers, datatype, byte_order, word_order)


class Reading:
    """Letzter Messzustand – thread-sicher gelesen/geschrieben."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "online": False,
            "error": "Noch keine Verbindung",
            "ts": 0,
            "power_kw": None,          # Netzbezug, signiert (+ Bezug / − Einspeisung)
            "production_kw": None,     # Erzeugung (PV), Summe
            "consumption_kw": None,    # Gesamtverbrauch = Netzbezug + Erzeugung
            "meters": [],              # [{name, type, kw}]
            "power_l1_kw": None, "power_l2_kw": None, "power_l3_kw": None,
            "current_l1_a": None, "current_l2_a": None, "current_l3_a": None,
        }

    def update(self, **kwargs):
        with self._lock:
            self._data.update(kwargs)
            self._data["ts"] = time.time()

    def snapshot(self):
        with self._lock:
            return dict(self._data)


def compute_grid_power(client, mb, unit):
    """Netzbezug (in der Geräte-Einheit, vor Skalierung) ermitteln."""
    function = mb.get("function", "input")
    datatype = mb.get("datatype", "int32")
    bo = mb.get("byte_order", "big")
    wo = mb.get("word_order", "big")
    reg = mb.get("registers", {})

    def rd(addr):
        return read_register(client, function, datatype, addr, unit, bo, wo)

    if mb.get("grid_mode") == "calc":
        consumption = rd(reg.get("power_total", 2))
        production = rd(reg.get("production", 0))
        if consumption is None:
            return None
        return consumption - (production or 0)
    return rd(reg.get("power_total", 2))


def scan_registers(mb, unit, start, count, function=None):
    """Liest einen Registerbereich und gibt je Adresse die dekodierten Werte
    (int32 + float32) zurück – zum empirischen Auffinden von Zähler-Registern.
    Liest paarweise (32-bit), Adressschritt 2."""
    if ModbusTcpClient is None:
        raise RuntimeError("pymodbus nicht installiert")
    host = (mb.get("host") or "").strip()
    port = int(mb.get("port", 503))
    function = function or mb.get("function", "input")
    bo = mb.get("byte_order", "big")
    wo = mb.get("word_order", "big")
    client = ModbusTcpClient(host=host, port=port, timeout=3)
    out = []
    try:
        if not client.connect():
            raise IOError(f"Verbindung zu {host}:{port} fehlgeschlagen")
        addr = int(start)
        end = int(start) + int(count) * 2
        while addr < end:
            row = {"address": addr}
            try:
                if function == "holding":
                    rr = client.read_holding_registers(address=addr, count=2, slave=unit)
                else:
                    rr = client.read_input_registers(address=addr, count=2, slave=unit)
                if rr is None or rr.isError():
                    row["error"] = str(rr)
                else:
                    row["int32"] = decode_value(rr.registers, "int32", bo, wo)
                    row["float32"] = round(decode_value(rr.registers, "float32", bo, wo), 4)
                    row["raw"] = list(rr.registers)
            except Exception as e:
                row["error"] = str(e)
            out.append(row)
            addr += 2
    finally:
        client.close()
    return out


class ModbusPoller(threading.Thread):
    """Pollt das PLEXLOG zyklisch und aktualisiert das Reading-Objekt."""

    def __init__(self, get_config, reading):
        super().__init__(daemon=True)
        self.get_config = get_config
        self.reading = reading
        self._stop = threading.Event()
        self._client = None
        self._client_key = None

    def stop(self):
        self._stop.set()

    def _ensure_client(self, host, port):
        key = (host, port)
        if self._client is not None and self._client_key == key:
            return self._client
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        if ModbusTcpClient is None:
            raise RuntimeError("pymodbus ist nicht installiert (pip install -r requirements.txt)")
        self._client = ModbusTcpClient(host=host, port=port, timeout=3)
        self._client_key = key
        return self._client

    def run(self):
        while not self._stop.is_set():
            cfg = self.get_config()
            mb = cfg.get("modbus", {})
            host = (mb.get("host") or "").strip()
            interval = float(cfg.get("poll_interval_s", 1.0) or 1.0)

            if not host:
                self.reading.update(online=False, error="Keine IP-Adresse hinterlegt")
                self._sleep(interval)
                continue

            try:
                port = int(mb.get("port", 503))
                unit = int(mb.get("unit_id", 1))
                function = mb.get("function", "input")
                datatype = mb.get("datatype", "int32")
                bo = mb.get("byte_order", "big")
                wo = mb.get("word_order", "big")
                scale = float(mb.get("power_scale", 0.001))   # W -> kW
                sgn = -1.0 if mb.get("invert_sign") else 1.0
                reg = mb.get("registers", {})

                client = self._ensure_client(host, port)
                if not client.connect():
                    raise IOError(f"Verbindung zu {host}:{port} fehlgeschlagen")

                def rd(addr, fn=None, dt=None):
                    return read_register(client, fn or function, dt or datatype, addr, unit, bo, wo)

                # Netzbezug (signiert)
                grid_raw = compute_grid_power(client, mb, unit)
                power_kw = None if grid_raw is None else sgn * grid_raw * scale

                # Erzeugung (PV)
                prod_addr = reg.get("production", 0)
                prod_raw = rd(prod_addr) if prod_addr is not None else None
                production_kw = None if prod_raw is None else abs(prod_raw) * scale

                # Gesamtverbrauch = Netzbezug + Erzeugung
                if power_kw is None:
                    consumption_kw = None
                else:
                    consumption_kw = power_kw + (production_kw or 0)

                # Zusatz-Zähler
                meters = []
                for m in cfg.get("meters", []) or []:
                    m_reg = m.get("register")
                    if m_reg is None:
                        meters.append({"name": m.get("name", "Zähler"), "type": m.get("type", "modbus"),
                                       "kw": None, "error": "kein Register"})
                        continue
                    try:
                        m_dt = m.get("datatype", datatype)
                        m_fn = m.get("function", function)
                        m_scale = float(m.get("scale", scale))
                        val = rd(m_reg, fn=m_fn, dt=m_dt)
                        meters.append({"name": m.get("name") or f"Reg {m_reg}",
                                       "type": m.get("type", "modbus"),
                                       "kw": None if val is None else val * m_scale})
                    except Exception as me:
                        meters.append({"name": m.get("name", "Zähler"), "type": m.get("type", "modbus"),
                                       "kw": None, "error": str(me)})

                # Phasen/Ströme (nur Gateway-Profil; native Register sind None)
                def rdopt(key):
                    a = reg.get(key)
                    return rd(a) if a is not None else None
                p1, p2, p3 = rdopt("power_l1"), rdopt("power_l2"), rdopt("power_l3")
                i1, i2, i3 = rdopt("current_l1"), rdopt("current_l2"), rdopt("current_l3")

                self.reading.update(
                    online=True, error=None,
                    power_kw=power_kw, production_kw=production_kw, consumption_kw=consumption_kw,
                    meters=meters,
                    power_l1_kw=None if p1 is None else sgn * p1 * scale,
                    power_l2_kw=None if p2 is None else sgn * p2 * scale,
                    power_l3_kw=None if p3 is None else sgn * p3 * scale,
                    current_l1_a=i1, current_l2_a=i2, current_l3_a=i3,
                )
            except Exception as e:
                self.reading.update(online=False, error=str(e))
                self._client_key = None
                if self._client is not None:
                    try:
                        self._client.close()
                    except Exception:
                        pass
                    self._client = None

            self._sleep(interval)

    def _sleep(self, seconds):
        end = time.time() + max(0.2, seconds)
        while time.time() < end and not self._stop.is_set():
            time.sleep(0.1)
