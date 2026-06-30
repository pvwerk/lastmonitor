"""Lokaler Selbsttest: Dekodierung + Modbus-Lesepfad gegen simulierten PLEXLOG."""
import threading
import time

from modbus_reader import decode_value, compute_grid_power

# ---- 1) Dekodierung (rein rechnerisch) -------------------------------------
def regs_from_int32(v, byte_order="big", word_order="big"):
    import struct
    bo = ">" if byte_order == "big" else "<"
    raw = struct.pack(bo + "i", v)
    hi, lo = struct.unpack(bo + "HH", raw)
    return [hi, lo] if word_order == "big" else [lo, hi]

assert decode_value(regs_from_int32(12345), "int32") == 12345, "int32 +"
assert decode_value(regs_from_int32(-2000), "int32") == -2000, "int32 - (Einspeisung)"
assert decode_value(regs_from_int32(50000), "int32") == 50000, "int32 50kW"
# float32 Gateway-Profil
import struct
f_regs = list(struct.unpack(">HH", struct.pack(">f", 0.043)))  # 0.043 MW = 43 kW
assert abs(decode_value(f_regs, "float32") - 0.043) < 1e-6, "float32"
print("[OK] Dekodierung int32/float32 korrekt")

# ---- 2) Lesepfad gegen simulierten PLEXLOG ---------------------------------
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext, ModbusSequentialDataBlock
from pymodbus.client import ModbusTcpClient

PORT = 15020
# Input-Register füllen: Adr 0/1 = PV (0 W), Adr 2/3 = Verbrauch (12345 W)
ir_values = [0] * 10
pv = regs_from_int32(0)
cons = regs_from_int32(12345)
ir_values[0], ir_values[1] = pv
ir_values[2], ir_values[3] = cons

store = ModbusSlaveContext(ir=ModbusSequentialDataBlock(0, ir_values), zero_mode=True)
context = ModbusServerContext(slaves={1: store}, single=False)

server_thread = threading.Thread(
    target=StartTcpServer, kwargs={"context": context, "address": ("127.0.0.1", PORT)}, daemon=True
)
server_thread.start()
time.sleep(1.5)  # Server hochfahren lassen

client = ModbusTcpClient("127.0.0.1", port=PORT, timeout=3)
assert client.connect(), "Verbindung zum Test-Server fehlgeschlagen"

# a) Direktregister (Küche ohne PV): power_total = Reg 2
mb_direct = {"function": "input", "datatype": "int32", "byte_order": "big", "word_order": "big",
             "grid_mode": "register", "registers": {"power_total": 2}}
raw = compute_grid_power(client, mb_direct, 1)
assert raw == 12345, f"Direktregister erwartet 12345, war {raw}"
print(f"[OK] Direktregister (Reg 2) = {raw} W -> {raw * 0.001} kW")

# b) Berechnung Verbrauch - PV
mb_calc = {"function": "input", "datatype": "int32", "byte_order": "big", "word_order": "big",
           "grid_mode": "calc", "registers": {"power_total": 2, "production": 0}}
raw2 = compute_grid_power(client, mb_calc, 1)
assert raw2 == 12345, f"Calc erwartet 12345, war {raw2}"
print(f"[OK] Verbrauch - PV = {raw2} W")

client.close()
print("\nALLE TESTS BESTANDEN")
