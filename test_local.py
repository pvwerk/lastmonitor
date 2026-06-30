"""Lokaler Selbsttest: Dekodierung + Modbus-Lesepfad + Zähler + Scanner."""
import threading, time, struct
from modbus_reader import decode_value, compute_grid_power, read_register, scan_registers

def regs_from_int32(v, byte_order="big", word_order="big"):
    bo = ">" if byte_order == "big" else "<"
    hi, lo = struct.unpack(bo + "HH", struct.pack(bo + "i", v))
    return [hi, lo] if word_order == "big" else [lo, hi]

# 1) Dekodierung
assert decode_value(regs_from_int32(12345), "int32") == 12345
assert decode_value(regs_from_int32(-5200), "int32") == -5200          # Einspeisung
f_regs = list(struct.unpack(">HH", struct.pack(">f", 0.043)))
assert abs(decode_value(f_regs, "float32") - 0.043) < 1e-6
print("[OK] Dekodierung int32/float32")

# 2) Simulierter PLEXLOG
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext, ModbusSequentialDataBlock
from pymodbus.client import ModbusTcpClient

PORT = 15021
ir = [0]*20
ir[0:2] = regs_from_int32(6000)     # Reg 0 = PV-Erzeugung 6000 W
ir[2:4] = regs_from_int32(12000)    # Reg 2 = Verbrauch/Netzbezug 12000 W
ir[4:6] = regs_from_int32(4100)     # Reg 4 = Zähler Fritteuse 4100 W
ir[6:8] = regs_from_int32(7800)     # Reg 6 = Zähler Herd 7800 W
store = ModbusSlaveContext(ir=ModbusSequentialDataBlock(0, ir), zero_mode=True)
ctx = ModbusServerContext(slaves={1: store}, single=False)
threading.Thread(target=StartTcpServer, kwargs={"context": ctx, "address": ("127.0.0.1", PORT)}, daemon=True).start()
time.sleep(1.5)

client = ModbusTcpClient("127.0.0.1", port=PORT, timeout=3)
assert client.connect()

mb = {"function": "input", "datatype": "int32", "byte_order": "big", "word_order": "big",
      "grid_mode": "register", "registers": {"power_total": 2, "production": 0}}

grid = compute_grid_power(client, mb, 1)
assert grid == 12000, grid
print(f"[OK] Netzbezug Reg 2 = {grid} W -> {grid*0.001} kW")

prod = read_register(client, "input", "int32", 0, 1, "big", "big")
assert prod == 6000
print(f"[OK] Erzeugung Reg 0 = {prod} W; Gesamtverbrauch = {(grid+prod)*0.001} kW")

m1 = read_register(client, "input", "int32", 4, 1, "big", "big")
m2 = read_register(client, "input", "int32", 6, 1, "big", "big")
assert (m1, m2) == (4100, 7800)
print(f"[OK] Zähler: Fritteuse {m1*0.001} kW, Herd {m2*0.001} kW")

# Einspeisung-Fall
mb_feed = {"function": "input", "datatype": "int32", "byte_order": "big", "word_order": "big",
           "grid_mode": "calc", "registers": {"power_total": 2, "production": 0}}
# calc: Verbrauch(12000) - PV(6000) = 6000
assert compute_grid_power(client, mb_feed, 1) == 6000
print("[OK] grid_mode calc (Verbrauch - PV)")

# Scanner
mb_scan = {"host": "127.0.0.1", "port": PORT, "function": "input", "byte_order": "big", "word_order": "big", "power_scale": 0.001}
rows = scan_registers(mb_scan, 1, 0, 8)
addrs = {r["address"]: r.get("int32") for r in rows}
assert addrs.get(0) == 6000 and addrs.get(2) == 12000 and addrs.get(4) == 4100 and addrs.get(6) == 7800, addrs
print(f"[OK] Scanner liest {len(rows)} Register, Werte korrekt")

client.close()
print("\nALLE TESTS BESTANDEN")
