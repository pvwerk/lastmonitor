"""
Modbus-TCP-Leser für PLEXLOG PL 100.

Unterstützt zwei Profile (in den Einstellungen umschaltbar):

1) "nativ"   – die native PLEXLOG-Modbus-Schnittstelle (Standard)
     Port 503, UnitID 1, Input Register (FC4), Datentyp int32, Werte in Watt.
     Adresse 0 = PV-Erzeugung, Adresse 2 = Verbrauch / Netzbezug.
     Netzbezug = Verbrauch(Reg 2) − PV(Reg 0); ohne PV reicht Reg 2 direkt.
     (Registerbelegung aus der produktiv genutzten evcc-Community-Integration,
      Quelle: github.com/evcc-io/evcc Discussion #11661.)

2) "gateway" – das OpenGateway-Profil (DynModbusTCP_Profil_26)
     Port 1502, UnitID 1, Holding Register (FC3), Datentyp float32, Werte in MW.
     Wirkleistung Reg 0, Phasen Reg 2/4/6, Ströme Reg 30/32/34.

Alle relevanten Parameter (Port, Funktionscode, Datentyp, Register, Skalierung,
Byte-/Wortreihenfolge) sind über die Konfiguration einstellbar, damit die exakte
Belegung am Gerät verifiziert/angepasst werden kann.
"""
import struct
import threading
import time

try:
    from pymodbus.client import ModbusTcpClient
except Exception:  # pragma: no cover - erst nach pip install vorhanden
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
    # int32 (Standard)
    return struct.unpack(bo + "i", raw)[0]


class Reading:
    """Letzter Messzustand – thread-sicher gelesen/geschrieben."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "online": False,
            "error": "Noch keine Verbindung",
            "ts": 0,
            "power_kw": None,        # Netzbezug gesamt (kW)
            "power_l1_kw": None,
            "power_l2_kw": None,
            "power_l3_kw": None,
            "current_l1_a": None,
            "current_l2_a": None,
            "current_l3_a": None,
            "channels": [],
        }

    def update(self, **kwargs):
        with self._lock:
            self._data.update(kwargs)
            self._data["ts"] = time.time()

    def snapshot(self):
        with self._lock:
            return dict(self._data)


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
        # Netzbezug = Verbrauch − PV-Erzeugung
        consumption = rd(reg.get("power_total", 2))
        production = rd(reg.get("production", 0))
        if consumption is None:
            return None
        return consumption - (production or 0)
    # Einzelregister (z. B. nativ Reg 2 = Verbrauch, oder Gateway Reg 0)
    return rd(reg.get("power_total", 2))


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

                def rd(addr):
                    return read_register(client, function, datatype, addr, unit, bo, wo)

                grid_raw = compute_grid_power(client, mb, unit)
                power_kw = None if grid_raw is None else sgn * grid_raw * scale

                # Phasen/Ströme nur, wenn Register hinterlegt sind (nativ: keine)
                p1 = rd(reg.get("power_l1")) if reg.get("power_l1") is not None else None
                p2 = rd(reg.get("power_l2")) if reg.get("power_l2") is not None else None
                p3 = rd(reg.get("power_l3")) if reg.get("power_l3") is not None else None
                i1 = rd(reg.get("current_l1")) if reg.get("current_l1") is not None else None
                i2 = rd(reg.get("current_l2")) if reg.get("current_l2") is not None else None
                i3 = rd(reg.get("current_l3")) if reg.get("current_l3") is not None else None

                channels = []
                for ch in cfg.get("channels", []) or []:
                    try:
                        val = rd(ch.get("register"))
                        ch_scale = float(ch.get("scale", 1.0))
                        channels.append({
                            "name": ch.get("name", f"Reg {ch.get('register')}"),
                            "unit": ch.get("unit", ""),
                            "value": None if val is None else val * ch_scale,
                        })
                    except Exception as ce:
                        channels.append({"name": ch.get("name", "?"), "unit": ch.get("unit", ""),
                                         "value": None, "error": str(ce)})

                self.reading.update(
                    online=True, error=None,
                    power_kw=power_kw,
                    power_l1_kw=None if p1 is None else sgn * p1 * scale,
                    power_l2_kw=None if p2 is None else sgn * p2 * scale,
                    power_l3_kw=None if p3 is None else sgn * p3 * scale,
                    current_l1_a=i1, current_l2_a=i2, current_l3_a=i3,
                    channels=channels,
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
