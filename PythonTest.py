#------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
                                                                        #       GO-HIJAU      #
#------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
from signalrcore.hub_connection_builder import HubConnectionBuilder
import serial
import time
import json
import requests
import logging
import threading
import sys
import select
import os
import socket

# ------------------------------
# PYTHON SOFTWARE WATCHDOG
# ------------------------------
class Watchdog:
    def __init__(self, timeout=120, pre_restart_callback=None):
        self.timeout = timeout
        self.pre_restart_callback = pre_restart_callback
        self.last_kick = time.time()
        self.active = True
        threading.Thread(target=self._monitor, daemon=True).start()

    def kick(self):
        self.last_kick = time.time()

    def stop(self):
        self.active = False

    def _monitor(self):
        while self.active:
            if time.time() - self.last_kick > self.timeout:
                print("[WATCHDOG] Main logic stuck. Restarting Python…")

                try:
                    if self.pre_restart_callback:
                        self.pre_restart_callback()
                except:
                    pass

                python = sys.executable
                os.execv(python, [python] + sys.argv)

            time.sleep(0.5)

# ------------------------------
# SERIAL CONFIGURATION (MOCKED FOR UI TESTING)
# ------------------------------
class DummySerial:
    def __init__(self): 
        self.in_waiting = False
        self.last_command = ""
        
    def flushInput(self): pass
    def reset_input_buffer(self): pass
    
    def write(self, data): 
        # Store the command so we know what to reply to
        self.last_command = data.decode(errors='ignore').strip()
        self.in_waiting = True 
        
    def readline(self): 
        self.in_waiting = False
        # If asked about PSU, return a healthy voltage string
        if self.last_command == "check_psu":
            return b"PSU:OK,12.05V,5.01V\n"
        # Default reply for door locks and everything else
        return b"door_closed\n"
        
    def close(self): pass
    def flush(self): pass

# ------------------------------
# HARDWARE INITIALIZATION (FIXED)
# ------------------------------
uno_lock = threading.Lock()

# Global timers required by the collector loop
auto_off_timer = None
door_off_timer = None

try:
    # IMPORTANT: Update these COM ports to match your machine!
    uno_ser = serial.Serial('COM3', 9600, timeout=1) 
    mega_ser = serial.Serial('COM4', 9600, timeout=1)
    print("✅ Serial connected successfully.")
except serial.SerialException as e:
    print(f"⚠️ Serial connection error: {e}")
    print("⚠️ Falling back to DummySerial for testing...")
    uno_ser = DummySerial()
    mega_ser = DummySerial()

# ------------------------------
# AUTO TARE AT PROGRAM STARTUP
# ------------------------------
print("[STARTUP] Sending tare command to UNO...")

with uno_lock:
    uno_ser.write(b"t\n")

tared = False
start = time.time()

while time.time() - start < 2:   # wait max 2 sec
    with uno_lock:
        if uno_ser.in_waiting:
            msg = uno_ser.readline().decode().strip()
            if msg == "TARED":
                print("[STARTUP] UNO TARED successfully.")
                tared = True
                break
    time.sleep(0.05)

if not tared:
    print("⚠️ [STARTUP] No TARED reply — continuing anyway.")
with uno_lock:
    uno_ser.reset_input_buffer()

# # ------------------------------
# PYTHON READY HANDSHAKE (UNO)
# ------------------------------
print("[STARTUP] Sending PYTHON_READY to UNO...")
with uno_lock:
    uno_ser.write(b"PYTHON_READY\n")
time.sleep(0.2)

# clear any UNO reply text so weight reading won't crash
with uno_lock:
    uno_ser.reset_input_buffer()

# API ENDPOINT
# ------------------------------
QR_VALIDATE_URL = "https://services.gohijau.org/api/Qr/verify"
FINAL_SUBMIT_URL = "https://services.gohijau.org/api/Qr/complete/pouring"
AUDIT_CREATE_URL = "https://services.gohijau.org/api/audit/machine/create"
FINAL_COLLECTOR_SUBMIT_URL = "https://services.gohijau.org/api/Qr/complete/collection"
OVERFLOW_URL = "https://services.gohijau.org/api/Qr/overflow"
# Change the real URLs to your local test environment
TELEMETRY_URL = "http://localhost:5137/api/machine/telemetry"
DIAGNOSTICS_URL = "http://localhost:5137/api/machine/diagnostics"

TOKEN = None
pin25_on = False  
machine_id = "GO-000002"
status_enabled = True
auto_drain_active = False

customer_cycle_running = False
global_auto_drain_active = False
weight_read_in_progress = False

PUMP_TIMEOUT_SEC = 120 
pump_timer = None
pump_mode = None    
pump_timer_lock = threading.Lock()

alarm_monitor_active = False
door_monitor_thread = None
pump_timeout_reached = False
MIN_POUR_WEIGHT = 0.100 # kg

internet_available = False
last_sent_internet_state = None
internet_lock = threading.Lock()

TURBIDITY_LIMIT = 600 # Adjust this threshold based on sensor calibration

# ------------------------------
# NEW: TELEMETRY & VOLUME HELPERS
# ------------------------------
def calculate_ibc_volume(distance_cm):
    """Calculates liquid volume in a 500L IBC tank based on ultrasonic distance."""
    if distance_cm <= 0: return 0.0  
    TANK_HEIGHT = 100.0 # cm
    TANK_LENGTH = 120.0 # cm
    TANK_WIDTH = 80.0   # cm
    
    oil_depth = TANK_HEIGHT - distance_cm
    if oil_depth < 0: return 0.0 
    
    volume_liters = (TANK_LENGTH * TANK_WIDTH * oil_depth) / 1000.0
    return round(max(0.0, min(500.0, volume_liters)), 2)

def get_telemetry_from_arduino():
    """Polls Arduino Mega for sensor array data (Turbidity, Junk Dist, Res Dist)."""
    try:
        mega_ser.reset_input_buffer()
        mega_ser.write(b"get_telemetry\n")
        time.sleep(0.2)
        
        for _ in range(5): # Retry loop
            if mega_ser.in_waiting:
                line = mega_ser.readline().decode(errors="ignore").strip()
                if line.startswith("telemetry:"):
                    parts = line.replace("telemetry:", "").split(",")
                    if len(parts) == 3:
                        return {
                            "turbidity": int(parts[0]),
                            "junk_dist": float(parts[1]),
                            "res_dist": float(parts[2])
                        }
            time.sleep(0.1)
    except Exception as e:
        print(f"⚠️ Telemetry parse error: {e}")
        
    return {"turbidity": 0, "junk_dist": 0.0, "res_dist": 0.0}

def log_telemetry_to_dashboard(action_name, weight, volume, turbidity, junk_level):
    """Sends a complete snapshot of machine health to the dashboard silently."""
    payload = {
        "machineId": machine_id,
        "timestamp": time.time(),
        "event": action_name,
        "metrics": {
            "weightKg": weight,
            "mainTankVolumeLiters": volume,
            "turbidityValue": turbidity,
            "junkTankDistanceCm": junk_level
        }
    }
    try:
        threading.Thread(target=requests.post, args=(TELEMETRY_URL,), kwargs={'json': payload, 'timeout': 5}, daemon=True).start()
    except Exception as e:
        print(f"⚠️ Dashboard log thread failed: {e}")

# ------------------------------
# BACKGROUND: SEND STATUS
# ------------------------------
def send_status_loop():
    global status_enabled
    while True:
        try:
            if status_enabled:
                hub_connection.send("SendStatus", ["GO-000002", "Active"])
        except Exception as e:
            print(f"[CLIENT] ⚠️ Failed to send status: {e}")
        time.sleep(5)


# ------------------------------
# SignalR Setup
# ------------------------------
hub_url = f"http://localhost:5137/machineHub?machineId={machine_id}"
hub_connection = (
    HubConnectionBuilder()
    .with_url(hub_url)
    .with_automatic_reconnect({
        "type": "raw",
        "keep_alive_interval": 10,
        "reconnect_interval": 5,
        "max_attempts": 5
    })
    .configure_logging(logging.INFO)
    .build()
)

def on_open():
    print("[CLIENT] ✅ Connected to server")
    send_to_arduino("PYTHON_READY")
    time.sleep(0.5)
    send_to_arduino("LED_GREEN_ON")

def reconnect_forever():
    while True:
        try:
            print("[CLIENT] 🔌 Reconnecting to SignalR...")
            hub_connection.start()
            print("[CLIENT] ✅ Reconnected to SignalR")
            return
        except Exception as e:
            print(f"[CLIENT] ❌ Reconnect failed: {e}")
            time.sleep(5)
            
def on_close():
    print("[CLIENT] ❌ Disconnected from server")
    reconnect_forever()
    
def on_collector_end():
    print("[SERVER] CollectorEnd received. Stopping machine...")
    send_to_arduino("PIN25_OFF")
    global pin25_on
    pin25_on = False
    try:
        payload = {"token": TOKEN, "machineId":machine_id}
        requests.post(FINAL_COLLECTOR_SUBMIT_URL , json=payload, timeout=5)
    except Exception as e:
        print(f"❌ Failed to send Collection final data: {e}")

def on_receive_command(command):
    print(f"[COMMAND] Server says → {command}")
    match command[0]:
        case "CollectorEnd":
            on_collector_end()
    
hub_connection.on("ReceiveCommand", on_receive_command)    
hub_connection.on_open(on_open)
hub_connection.on_close(on_close)
hub_connection.start()
print("[CLIENT] 🧩 Starting status thread...")
threading.Thread(target=send_status_loop, daemon=True).start()

# ------------------------------
# ARDUINO COMMUNICATION
# ------------------------------
def send_to_arduino(command, timeout=0.8):
    try:
        mega_ser.reset_input_buffer()
    except:
        pass
    mega_ser.write((command + "\n").encode())
    mega_ser.flush()
    end = time.time() + timeout
    while time.time() < end:
        line = mega_ser.readline().decode(errors="ignore").strip()
        if line:
            print(f"[MEGA ACK] {command} -> {line}")
            return line
    print(f"[MEGA ACK] {command} -> (NO REPLY)")
    return None

# ------------------------------
# INTERNET CHECK
# ------------------------------
def check_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.create_connection((host, port), timeout=timeout)
        return True
    except OSError:
        return False

def internet_monitor_loop():
    global internet_available, last_sent_internet_state
    while True:
        try:
            state = check_internet()
            with internet_lock:
                internet_available = state
            if state != last_sent_internet_state:
                if state:
                    print("[INTERNET] ✅ Internet is back")
                    send_to_arduino("HAS_INTERNET")
                else:
                    print("[INTERNET] ❌ No internet")
                    send_to_arduino("NO_INTERNET")
                last_sent_internet_state = state
        except Exception as e:
            print(f"[INTERNET] Error: {e}")
        time.sleep(5)

# ------------------------------
# WEIGHT READING
# ------------------------------
def get_weight_from_uno(samples=10):
    global weight_read_in_progress
    weight_read_in_progress = True
    wd.kick()
    with uno_lock:
        uno_ser.reset_input_buffer()
        
    print("⏳ Waiting for UNO to stabilize...")
    time.sleep(1.5)

    weights = []
    for _ in range(samples):
        wd.kick()
        try:
            with uno_lock:
                raw = uno_ser.readline()
            if not raw:
                print("⚠️ UNO returned no data")
                continue
            line = raw.decode(errors='ignore').strip()
            if not line:
                continue
            try:
                weight = float(line)
            except ValueError:
                continue
            weights.append(weight)
        except Exception as e:
            print(f"⚠️ Bad data: {e}")
        time.sleep(0.15)

    if not weights:
        weight_read_in_progress = False
        return 0.0

    weights.sort()
    median = weights[len(weights) // 2]
    filtered = [w for w in weights if abs(w - median) <= 0.05]
    if not filtered:
        filtered = weights
    avg = round(sum(filtered) / len(filtered), 3)

    weight_read_in_progress = False
    return avg

# ------------------------------
# OVERFLOW
# ------------------------------
def create_machine_overflow(payload):
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(OVERFLOW_URL, json=payload, headers=headers, timeout=5)
        print(f"🔁 API Response: {response.status_code} - {response.text}")
        if response.status_code == 200:
            return True
    except Exception as e:
        print(f"❌ API Error: {e}")
    return False

# ------------------------------
# QR HANDLING
# ------------------------------
def wait_for_qr():
    print("📷 Waiting for QR scan...")
    
    if sys.platform == 'win32':
        # --- WINDOWS TESTING MODE ---
        import msvcrt
        scanned_str = ""
        while True:
            wd.kick()
            # Check if a key was pressed (non-blocking)
            if msvcrt.kbhit():
                char = msvcrt.getwche() # Read the character
                if char in ('\r', '\n'): # Enter key pressed
                    print()
                    if scanned_str:
                        # You can create audit here if needed, but since we update global TOKEN later,
                        # it's better to return the string so main() can process it.
                        return scanned_str
                else:
                    scanned_str += char
            time.sleep(0.1)
    else:
        # --- LINUX / PRODUCTION MODE ---
        while True:
            wd.kick()
            readable, _, _ = select.select([sys.stdin], [], [], 1)
            if readable:
                scanned = sys.stdin.readline().strip()
                if scanned:
                    return scanned
            time.sleep(0.1)

# ------------------------------
# SEND QR TO API (FIXED)
# ------------------------------
def send_qr_to_api(qr_token):
    """Validates the QR token with the backend and returns the panel type."""
    try:
        response = requests.post(QR_VALIDATE_URL, json={"token": qr_token}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            # Returns CUSTOMERPANEL, COLLECTORPANEL, or TECHNICIANPANEL
            print(f"✅ QR Validated. Panel: {data.get('panelType', 'UNKNOWN')}")
            return data.get("panelType") 
        else:
            print(f"❌ QR Validation failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ API Error during QR validation: {e}")
    return None

# ------------------------------
# FINAL DATA SUBMIT
# ------------------------------
def send_final_data(oil_amount):
    payload = {"token": TOKEN, "oilAmount": round(oil_amount, 2), "machineId":machine_id}
    try:
        r = requests.post(FINAL_SUBMIT_URL, json=payload, timeout=5)
        print(f"✅ Final Data Sent: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"❌ Failed to send final data: {e}")

# ------------------------------
# PUMP
# ------------------------------
def monitor_and_stop_pump():
    while True:
        weight = get_weight_from_uno()
        if weight is not None:
            send_to_arduino(f"weight:{weight}")
            if weight <= 0.2 or pump_timeout_reached:
                if pump_timeout_reached:
                    print("🛑 Pump timeout — treating as weight <= 0.2 kg.")
                stop_pump_safety_timer()
                send_to_arduino("LOCK")
                break
        time.sleep(1)

# ------------------------------
# CREATE AUDIT
# ------------------------------
def create_machine_audit(payload):
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(AUDIT_CREATE_URL, json=payload, headers=headers, timeout=5)
        if response.status_code == 200:
            return True
    except Exception as e:
        print(f"❌ API Error: {e}")
    return False

# ------------------------------
# SAFETY FEATURE
# ------------------------------
def start_pump_safety_timer(mode: str):
    global pump_timer, pump_mode, pump_timeout_reached
    with pump_timer_lock:
        pump_mode = mode
        pump_timeout_reached = False  

        try:
            if pump_timer is not None: pump_timer.cancel()
        except: pass

        def timeout():
            global pump_timeout_reached, pump_mode
            pump_timeout_reached = True
            print(f"⏰ [PUMP TIMER] {PUMP_TIMEOUT_SEC}s exceeded.")
            try:
                if pump_mode == "normal":
                    send_to_arduino("LOCK")
                elif pump_mode == "excess":
                    send_to_arduino("excess_pump_stop")
                    time.sleep(0.2)
                    send_to_arduino("LOCK")
            except Exception as e:
                pass

        pump_timer = threading.Timer(PUMP_TIMEOUT_SEC, timeout)
        pump_timer.daemon = True
        pump_timer.start()

def stop_pump_safety_timer():
    global pump_timer, pump_mode
    with pump_timer_lock:
        try:
            if pump_timer is not None: pump_timer.cancel()
        except: pass
        pump_timer = None
        pump_mode = None

# ------------------------------
# AUTO-DRAIN (UPDATED LIMIT)
# ------------------------------
def run_global_auto_drain():
    global pump_timeout_reached, global_auto_drain_active
    if global_auto_drain_active: return

    print("🚨 [GLOBAL AUTO-DRAIN] Starting due to weight > 10kg")
    global_auto_drain_active = True

    try:
        send_to_arduino("excess_pump_start")
        start_pump_safety_timer("excess")

        while True:
            wd.kick()
            w = get_weight_from_uno(samples=6)

            if w <= 0.25 or pump_timeout_reached:
                send_to_arduino("excess_pump_stop")
                stop_pump_safety_timer()
                send_to_arduino("LOCK")
                break

            try:
                send_to_arduino(f"weight:{w}")
            except Exception:
                pass
            time.sleep(1)

    except Exception as e:
        print(f"❌ [GLOBAL AUTO-DRAIN] Exception: {e}")

    finally:
        global_auto_drain_active = False
        stop_pump_safety_timer()

def global_auto_drain_monitor():
    while True:
        try:
            wd.kick()
            if customer_cycle_running or auto_drain_active:
                time.sleep(0.8)
                continue
            if weight_read_in_progress:
                time.sleep(0.5)
                continue
            
            w = get_weight_from_uno(samples=5)
            if w is None:
                time.sleep(1)
                continue

            if w > 10.0:  # UPDATED LIMIT
                threading.Thread(target=run_global_auto_drain, daemon=True).start()

            time.sleep(1)

        except Exception as e:
            time.sleep(1)
 
# ------------------------------
# ALARM
# ------------------------------
def door_alarm_monitor_active():
    global alarm_monitor_active
    try:
        mega_ser.reset_input_buffer()
        time.sleep(0.05)
        while alarm_monitor_active:
            wd.kick()
            try:
                mega_ser.write(b"get_door_state\n")
                time.sleep(0.12)  
                if mega_ser.in_waiting:
                    msg = mega_ser.readline().decode(errors="ignore").strip()
                    if msg == "door_closed":
                        alarm_monitor_active = False
                        break
            except Exception:
                pass
            time.sleep(0.15)
    finally:
        alarm_monitor_active = False

# ------------------------------
# Follow-up Cycle (UPDATED LIMIT)
# ------------------------------           
def followup_cycle():
    global pump_timeout_reached, status_enabled
    global alarm_monitor_active, door_monitor_thread

    alarm_monitor_active = False
    send_to_arduino("unlock")
    time.sleep(0.2)

    while True:
        wd.kick()
        w_live = get_weight_from_uno(samples=5)

        if w_live > 10.0: # UPDATED LIMIT
            print("🚨 [FOLLOW-UP] Weight > 10kg while waiting — starting auto-drain")
            alarm_monitor_active = True
            if door_monitor_thread is None or not door_monitor_thread.is_alive():
                door_monitor_thread = threading.Thread(target=door_alarm_monitor_active, daemon=True)
                door_monitor_thread.start()

            send_to_arduino("excess_pump_start")
            start_pump_safety_timer("excess")

            while True:
                wd.kick()
                wdrain = get_weight_from_uno(samples=5)
                send_to_arduino(f"weight:{wdrain}")

                if wdrain <= 0.25 or pump_timeout_reached:
                    send_to_arduino("excess_pump_stop")
                    stop_pump_safety_timer()
                    alarm_monitor_active = False
                    send_to_arduino("LOCK")
                    break
                time.sleep(1)

        if mega_ser.in_waiting:
            msg = mega_ser.readline().decode().strip()
            if msg == "door_closed": break
        time.sleep(0.2)

    w_final = get_weight_from_uno()
    send_final_data(w_final)

    if w_final > 10.0: # UPDATED LIMIT
        alarm_monitor_active = True
        if door_monitor_thread is None or not door_monitor_thread.is_alive():
            door_monitor_thread = threading.Thread(target=door_alarm_monitor_active, daemon=True)
            door_monitor_thread.start()
            
        send_to_arduino("excess_pump_start")
        start_pump_safety_timer("excess")

        while True:
            wd.kick()
            w2 = get_weight_from_uno(samples=5)
            send_to_arduino(f"weight:{w2}")

            if w2 <= 0.25 or pump_timeout_reached:
                send_to_arduino("excess_pump_stop")
                send_to_arduino("LOCK")
                stop_pump_safety_timer()
                alarm_monitor_active = False
                break
            time.sleep(1)

    else:
        send_to_arduino("pump_now")
        start_pump_safety_timer("normal")

        while True:
            wd.kick()
            w2 = get_weight_from_uno(samples=5)
            send_to_arduino(f"weight:{w2}")

            if w2 <= 0.25 or pump_timeout_reached:
                stop_pump_safety_timer()
                send_to_arduino("LOCK")
                uno_ser.write(b"STOP_ALARM\n")
                alarm_monitor_active = False
                break
            time.sleep(1)

    status_enabled = True

# ------------------------------
# Customer Panel Full Cycle (UPDATED)
# ------------------------------
def customer_cycle():
    global status_enabled, auto_drain_active, customer_cycle_running
    global alarm_monitor_active, door_monitor_thread
    customer_cycle_running = True
    
    with uno_lock: uno_ser.write(b"t\n")
    start = time.time()
    tared = False

    while time.time() - start < 3:
        wd.kick()
        with uno_lock:
            try:
                raw = uno_ser.readline() if uno_ser.in_waiting else b""
            except Exception:
                raw = b""
        if not raw:
            time.sleep(0.05)
            continue
        try:
            if raw.decode(errors='ignore').strip() == "TARED":
                tared = True
                break
        except: continue
        time.sleep(0.05)

    if not tared:
        with uno_lock: uno_ser.write(b"t\n")
        time.sleep(0.5) 
        retry_start = time.time()
        while time.time() - retry_start < 3:
            wd.kick()
            with uno_lock:
                try:
                    raw = uno_ser.readline() if uno_ser.in_waiting else b""
                except Exception:
                    raw = b""
            if not raw:
                time.sleep(0.05)
                continue
            try:
                if raw.decode(errors='ignore').strip() == "TARED":
                    tared = True
                    break
            except: continue

    send_to_arduino("unlock")
    payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Customer verified - Top door unlock" }
    create_machine_audit(payload)
    
    door_opened = False
    start_time = time.time()
    while time.time() - start_time < 60:
        wd.kick()
        if mega_ser.in_waiting:
            if mega_ser.readline().decode().strip() == "door_opened":
                door_opened = True
                break
        time.sleep(0.1)

    if not door_opened:
        payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Top door not opened - lock engaged." }
        create_machine_audit(payload)
        send_to_arduino("LOCK")
        send_final_data(0.0)
        customer_cycle_running = False
        return

    while True:
        wd.kick()
        weight_live = get_weight_from_uno()
        if weight_live is not None:
            # UPDATED LIMIT
            if weight_live > 10.0:
                auto_drain_active = True
                payload = {"qrToken": TOKEN, "machineId": machine_id, "action": f"Auto-drain triggered at {weight_live}kg"}
                create_machine_audit(payload)

                send_to_arduino("LOCK")
                time.sleep(0.30)
                send_to_arduino("pump_now")
                time.sleep(0.10)
                send_to_arduino("excess_pump_start")
                start_pump_safety_timer("excess")

                while True:
                    wd.kick()
                    wdrain = get_weight_from_uno()
                    if wdrain is not None:
                        send_to_arduino(f"weight:{wdrain}")
                        if wdrain <= 0.25:
                            send_to_arduino("excess_pump_stop")
                            stop_pump_safety_timer()
                            payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Auto-drain complete"}
                            create_machine_audit(payload)
                            break
                    time.sleep(1)

                send_final_data(10.00) # Updated static final value
                auto_drain_active = False
                
                mega_ser.reset_input_buffer()
                time.sleep(0.1)
                mega_ser.write(b"get_door_state\n")
                time.sleep(0.2)
                door_is_closed = None

                for _ in range(10):
                    if mega_ser.in_waiting:
                        msg = mega_ser.readline().decode().strip()
                        if msg == "door_closed":
                            door_is_closed = True
                            break
                        elif msg == "door_opened":
                            door_is_closed = False
                            break
                    wd.kick()
                    time.sleep(0.1)

                if door_is_closed is None or door_is_closed:
                    status_enabled = True
                    customer_cycle_running = False
                    alarm_monitor_active = False
                    return

                followup_cycle()
                customer_cycle_running = False
                return
                
        if mega_ser.in_waiting:
            msg = mega_ser.readline().decode().strip()
            if msg == "door_closed":
                if auto_drain_active:
                    send_to_arduino("pump_now")
                    time.sleep(0.2)
                
                payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Machine door closed." }
                create_machine_audit(payload)
                w = get_weight_from_uno()
                if w < 0 : w = 0
                
                if w < MIN_POUR_WEIGHT:
                    payload = {"qrToken": TOKEN, "machineId": machine_id, "action": f"No oil poured ({w} kg) — Pump skipped"}
                    create_machine_audit(payload)
                    send_final_data(0.0)
                    send_to_arduino("LOCK")
                    customer_cycle_running = False
                    alarm_monitor_active = False
                    return

                # ------------------------------
                # NORMAL PUMP START WITH TURBIDITY CHECK
                # ------------------------------
                print("🔍 Checking oil quality (Turbidity) and gathering telemetry...")
                telemetry = get_telemetry_from_arduino()
                turbidity_val = telemetry.get('turbidity', 0)
                volume_liters = calculate_ibc_volume(telemetry.get('res_dist', 0))
                junk_dist = telemetry.get('junk_dist', 0)

                # Log to the new Dashboard Endpoint
                log_telemetry_to_dashboard("Customer Pour Completed", w, volume_liters, turbidity_val, junk_dist)

                if turbidity_val > TURBIDITY_LIMIT:
                    print(f"🚫 Oil too dirty! Turbidity: {turbidity_val}. Diverting to Junk Tank.")
                    payload = {"qrToken": TOKEN, "machineId": machine_id, "action": f"Rejected: High Turbidity ({turbidity_val})"}
                    create_machine_audit(payload)
                    
                    send_to_arduino("divert_to_junk") 
                    start_pump_safety_timer("normal")
                    
                    # drain to junk
                    while True:
                        wd.kick()
                        weight = get_weight_from_uno()
                        if weight is not None:
                            send_to_arduino(f"weight:{weight}")
                            if weight <= 0.2 or pump_timeout_reached:
                                stop_pump_safety_timer()
                                send_to_arduino("LOCK")
                                break
                        time.sleep(1)
                        
                    send_final_data(0.0) # User gets 0kg since it was junk
                    customer_cycle_running = False
                    alarm_monitor_active = False
                    return

                # ------------------------------
                # NORMAL PUMP START
                # ------------------------------
                send_final_data(w)
                send_to_arduino("pump_now")
                start_pump_safety_timer("normal")

                while True:
                    wd.kick()
                    weight = get_weight_from_uno()
                    if weight is not None:
                        send_to_arduino(f"weight:{weight}")
                        if weight <= 0.2 or pump_timeout_reached:
                            payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :" Weight threshold reached . Machine-stoped pumping." }
                            create_machine_audit(payload)
                            stop_pump_safety_timer()
                            send_to_arduino("LOCK")
                            break
                    time.sleep(1)
                break
            
            elif msg.strip() == "overflow_confirmed":
                overflow_payload = {"token": TOKEN, "machineId" :machine_id}
                create_machine_overflow(overflow_payload)
                payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :f"Overflow Detected :{msg}" }
                create_machine_audit(payload)
                send_to_arduino("LOCK")
                monitor_and_stop_pump()
                break
        time.sleep(0.2)
    
    auto_drain_active = False
    customer_cycle_running = False

# ------------------------------
# Collector Panel Cycle
# ------------------------------
def collector_cycle():
    global pin25_on, status_enabled, auto_off_timer, door_off_timer

    if not pin25_on:
        send_to_arduino("PIN25_ON")
        payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Collector verified - solenoid valve activated"}
        create_machine_audit(payload)
        pin25_on = True

        def door_auto_off():
            if pin25_on:
                send_to_arduino("COLLECTOR_DOOR_OFF")
                payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Collector door auto-closed after 1 minute"}
                create_machine_audit(payload)

        try: door_off_timer.cancel()
        except: pass

        door_off_timer = threading.Timer(60, door_auto_off)
        door_off_timer.daemon = True
        door_off_timer.start()

        def auto_turn_off():
            global pin25_on
            if pin25_on:
                send_to_arduino("PIN25_OFF")
                payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Auto-off timer expired - solenoid valve turned OFF"}
                create_machine_audit(payload)
                pin25_on = False

        try: auto_off_timer.cancel()
        except: pass

        auto_off_timer = threading.Timer(600, auto_turn_off)
        auto_off_timer.daemon = True
        auto_off_timer.start()

    else:
        send_to_arduino("PIN25_OFF")
        payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Collector verified — solenoid valve deactivated"}
        create_machine_audit(payload)
        pin25_on = False
        try: auto_off_timer.cancel()
        except: pass
        try: door_off_timer.cancel()
        except: pass

# ------------------------------
# Technician Panel Cycle 
# ------------------------------
def technician_cycle():
    global status_enabled
    send_to_arduino("unlock")         
    send_to_arduino("unlock_right")   
    send_to_arduino("unlock_tech")    
    payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Technician verified - all doors unlocked." }
    create_machine_audit(payload)

    start = time.time()
    while time.time() - start < 20:
        wd.kick()
        time.sleep(0.2)

    send_to_arduino("LOCK")
    payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Auto-lock timer expired." }
    create_machine_audit(payload)


# ------------------------------
# UPDATED STARTUP DIAGNOSTICS
# ------------------------------
def run_startup_diagnostics():
    print("⚙️ [DIAGNOSTICS] Starting machine diagnostics...")
    
    def report(step, status, detail=""):
        print(f"   -> {step}: {status}")
        payload = {
            "machineId": machine_id,
            "timestamp": time.time(),
            "step": step,
            "status": status,
            "detail": detail
        }
        # Fire and forget - send to dashboard
        try:
            threading.Thread(target=requests.post, args=(DIAGNOSTICS_URL,), kwargs={'json': payload, 'timeout': 3}, daemon=True).start()
        except:
            pass 
            
    report("System Check", "IN_PROGRESS", "Initializing startup sequence...")
    time.sleep(1)

    # --- NEW TEST 0: PSU HEALTH CHECK ---
    report("PSU Health Test", "IN_PROGRESS", "Checking Power Supply Rails...")
    try:
        # Request PSU status from Mega
        mega_ser.write(b"check_psu\n")
        time.sleep(0.5)
        
        psu_status = "UNKNOWN"
        if mega_ser.in_waiting:
            # Expecting something like "PSU:OK,12.05V,5.01V"
            psu_status = mega_ser.readline().decode(errors="ignore").strip()
            
        if "PSU:OK" in psu_status:
            report("PSU Health Test", "PASSED", f"Voltage rails stable: {psu_status}")
        else:
            report("PSU Health Test", "FAILED", f"Power instability detected: {psu_status}")
            # Set LED to Red and halt if PSU is critical
            send_to_arduino("LED_RED_ON")
            # In a real scenario, you might want to sys.exit() here if power is unsafe
    except Exception as e:
        report("PSU Health Test", "ERROR", f"Could not communicate with PSU monitor: {e}")

    # --- TEST 1: DOOR LOCKS ---
    report("Door Locks Test", "IN_PROGRESS", "Testing solenoids (Unlock -> Lock)")
    send_to_arduino("unlock")
    time.sleep(1.5) 
    send_to_arduino("LOCK")
    time.sleep(1.5) 
    
    # Verify door state via Arduino
    try:
        mega_ser.reset_input_buffer()
        mega_ser.write(b"get_door_state\n")
        time.sleep(0.3)
        door_state = "UNKNOWN"
        for _ in range(5):
            if mega_ser.in_waiting:
                door_state = mega_ser.readline().decode(errors="ignore").strip()
                break
            time.sleep(0.1)
            
        if door_state == "door_closed":
            report("Door Locks Test", "PASSED", "Doors successfully locked and verified closed")
        else:
            report("Door Locks Test", "FAILED", f"Lock anomaly detected. State: '{door_state}'")
    except Exception as e:
        report("Door Locks Test", "ERROR", f"Serial comms failed during test: {e}")
        
    report("System Check", "COMPLETED", "Startup diagnostics finished. Machine ready.")

# ------------------------------
# Main Program
# ------------------------------
def main():
    global pin25_on, wd, TOKEN # <-- FIXED: Add global TOKEN
    def pre_restart():
        try: send_to_arduino("LOCK")
        except: pass

    wd = Watchdog(timeout=120, pre_restart_callback=pre_restart)
    threading.Thread(target=internet_monitor_loop, daemon=True).start()
    threading.Thread(target=global_auto_drain_monitor, daemon=True).start()

    # --- NEW: Run diagnostics before opening for business ---
    run_startup_diagnostics()

    while True:
        wd.kick()
        # Ensure the returned scan updates the global token for the audit APIs
        TOKEN = wait_for_qr() 
        
        # FIXED: Create audit events and log QR based on API response
        payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "QR Scanned."}
        create_machine_audit(payload)
        
        panel_type = send_qr_to_api(TOKEN)
        if not panel_type:
            continue

        if panel_type == "CUSTOMERPANEL":
            mega_ser.reset_input_buffer()
            mega_ser.write(b"get_led_status\n")
            time.sleep(0.3)
            led_status = mega_ser.readline().decode().strip()

            if led_status == "LED_RED_ON":
                payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Customer cycle blocked - issue detected" }
                create_machine_audit(payload)
                send_to_arduino("LOCK")  
                continue
            else:
                payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Customer QR scanned" }
                create_machine_audit(payload)
                customer_cycle()

        elif panel_type == "COLLECTORPANEL":
            payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Collector QR scanned" }
            create_machine_audit(payload)
            collector_cycle()

        elif panel_type == "TECHNICIANPANEL":
            payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Technician QR scanned" }
            create_machine_audit(payload)
            technician_cycle()

        else:
            send_to_arduino("LOCK")

        time.sleep(2)

# ------------------------------
# Entry Point
# ------------------------------
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Program stopped by user.")
        try:
            mega_ser.close()
            uno_ser.close()
        except:
            pass