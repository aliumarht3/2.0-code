#------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
#                                                                        GO-HIJAU      
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
# GLOBALS & WATCHDOG
# ------------------------------
manual_test_lock = threading.Lock()
manual_test_running = False
machine_mode = "IDLE"   

MANUAL_TESTS = {
    "door_lock_1": ("TEST_LOCK1_ON", "TEST_LOCK1_OFF", 5),
    "door_lock_2": ("TEST_LOCK2_ON", "TEST_LOCK2_OFF", 5),
    "door_lock_3": ("TEST_LOCK3_ON", "TEST_LOCK3_OFF", 5),
    "pump":        ("TEST_PUMP_ON",  "TEST_PUMP_OFF",  5),
    "valve":       ("TEST_VALVE_ON", "TEST_VALVE_OFF", 10),
}

class Watchdog:
    def __init__(self, timeout=120, pre_restart_callback=None):
        self.timeout = timeout
        self.pre_restart_callback = pre_restart_callback
        self.last_kick = time.time()
        self.active = True
        threading.Thread(target=self._monitor, daemon=True).start()

    def kick(self): self.last_kick = time.time()
    def _monitor(self):
        while self.active:
            if time.time() - self.last_kick > self.timeout:
                print("[WATCHDOG] Main logic stuck. Restarting Python...")
                try:
                    if self.pre_restart_callback: self.pre_restart_callback()
                except: pass
                python = sys.executable
                os.execv(python, [python] + sys.argv)
            time.sleep(0.5)

class DummySerial:
    def __init__(self): self.in_waiting = False
    def write(self, data): pass
    def readline(self): return b"door_closed\n"
    def reset_input_buffer(self): pass
    def flush(self): pass
    def close(self): pass

# ------------------------------
# HARDWARE INITIALIZATION
# ------------------------------
mega_lock = threading.Lock()
auto_off_timer = None

try:
    mega_ser = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
    print("✅ Mega connected successfully.")
    time.sleep(2.5)
except serial.SerialException as e:
    print(f"❌ Mega connection error: {e}")
    mega_ser = DummySerial()

try:
    uno_ser = serial.Serial('/dev/ttyACM1', 9600, timeout=1)
    print("✅ Uno (Load Cell) connected successfully.")
    time.sleep(2.5)
except serial.SerialException as e:
    print(f"❌ Uno connection error: {e}")
    uno_ser = DummySerial()

# ------------------------------
# API ENDPOINTS & CONSTANTS
# ------------------------------
QR_VALIDATE_URL = "https://services.gohijau.org/api/Qr/verify"
FINAL_SUBMIT_URL = "https://services.gohijau.org/api/Qr/complete/pouring"
AUDIT_CREATE_URL = "https://services.gohijau.org/api/audit/machine/create"
FINAL_COLLECTOR_SUBMIT_URL = "https://services.gohijau.org/api/Qr/complete/collection"
OVERFLOW_URL = "https://services.gohijau.org/api/Qr/overflow"
TELEMETRY_URL = "https://gallows-qualm-dazzler.ngrok-free.dev/api/machine/telemetry"
DIAGNOSTICS_URL = "https://gallows-qualm-dazzler.ngrok-free.dev/api/machine/diagnostics"

TOKEN = None
pin25_on = False  
machine_id = "GO-000001" 
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
pump_timeout_reached = False
MIN_POUR_WEIGHT = 0.100 # kg

mega_message_queue = []

internet_available = False
last_sent_internet_state = None
internet_lock = threading.Lock()

TURBIDITY_GOOD_MAX = 450
TURBIDITY_POOR_MAX = 750
TURBIDITY_WATER_MAX = 200

# ------------------------------
# HARDWARE HELPERS
# ------------------------------
def send_to_arduino(command, timeout=0.8):
    with mega_lock:
        try: mega_ser.reset_input_buffer()
        except: pass
        mega_ser.write((command + "\n").encode())
        mega_ser.flush()
        end = time.time() + timeout
        while time.time() < end:
            try:
                if mega_ser.in_waiting: 
                    line = mega_ser.readline().decode(errors="ignore").strip()
                    if line:
                        print(f"[MEGA ACK] {command} -> {line}")
                        return line
            except: pass
            time.sleep(0.05)
        print(f"[MEGA ACK] {command} -> (NO REPLY)")
        return None

def is_tech_door_open():
    """Checks the Mega if the GPIO3 (Tech Door) sensor reads OPEN"""
    resp = send_to_arduino("CHECK_DOOR_GPIO3", timeout=1.0)
    if resp and "OPEN" in resp:
        return True
    return False

def classify_turbidity(raw_value):
    if raw_value is None or raw_value < 0: return "UNKNOWN"
    if raw_value <= TURBIDITY_GOOD_MAX: return "GOOD"
    elif raw_value <= TURBIDITY_POOR_MAX: return "POOR"
    else: return "WATER_CONTAMINATED"
    
def get_turbidity_from_arduino():
    try:
        with mega_lock:
            mega_ser.reset_input_buffer()
            mega_ser.write(b"get_turbidity\n")
            mega_ser.flush()
        time.sleep(0.15)
        for _ in range(5):
            with mega_lock:
                if mega_ser.in_waiting:
                    line = mega_ser.readline().decode(errors="ignore").strip()
                    if line.startswith("turbidity:"):
                        return int(line.replace("turbidity:", "").strip())
            time.sleep(0.1)
    except Exception as e: print(f"❌ Turbidity read error: {e}")
    return None

def log_telemetry_to_dashboard(action_name, weight, turbidity_raw, oil_quality):
    payload = {
        "machineId": machine_id,
        "timestamp": time.time(),
        "event": action_name,
        "metrics": {
            "weightKg": weight,
            "turbidityRaw": turbidity_raw,
            "oilQuality": oil_quality
        }
    }
    try:
        threading.Thread(target=requests.post, args=(TELEMETRY_URL,), kwargs={"json": payload, "timeout": 5}, daemon=True).start()
    except Exception as e:
        print(f"❌ Dashboard log thread failed: {e}")

# ------------------------------
# LOAD CELL BACKGROUND THREAD
# ------------------------------
current_weight = 0.0

def load_cell_reader_loop():
    global current_weight
    while True:
        try:
            if isinstance(uno_ser, DummySerial):
                time.sleep(1)
                continue
            if uno_ser.in_waiting:
                line = uno_ser.readline().decode(errors="ignore").strip()
                if line == "PYTHON_OK" or line == "TARE_START" or line == "TARED":
                    continue
                try:
                    val = float(line)
                    if -5.0 <= val <= 200.0:
                        current_weight = val
                except ValueError:
                    pass
            else:
                time.sleep(0.05)
        except Exception as e:
            time.sleep(0.5)

def get_weight_from_sensor(samples=None):
    return round(current_weight, 3)

# ------------------------------
# DIAGNOSTICS LOGIC
# ------------------------------
def update_diagnostic_status(log_no, log_type, component, checking, status, action=""):
    payload = {"MachineId": machine_id, "Timestamp": time.time(), "No": log_no, "Type": log_type, "Component": component, "Checking": checking, "Status": status, "Action": action}
    headers = {"Content-Type": "application/json", "ngrok-skip-browser-warning": "true"}
    try: requests.post(DIAGNOSTICS_URL, json=payload, headers=headers, timeout=3)
    except Exception as e: print(f"❌ Failed to update diagnostic status for {component}: {e}")

def publish_manual_test_status(test_name, status):
    mapping = {"door_lock_1": "Door Lock", "door_lock_2": "Door Lock", "door_lock_3": "Door Lock", "pump": "Pump", "valve": "Valve"}
    comp_name = mapping.get(test_name, test_name)
    ui_status = "✅" if status == "DONE" else ("IN_PROGRESS" if status == "RUNNING" else "❌")
    update_diagnostic_status(0, "Physical", comp_name, f"Manual Test: {status}", ui_status)

def run_online_diagnostics():
    print("\n--- 🔍 STARTED ONLINE DIAGNOSTICS ---")
    tests = [
        {"no": 1, "comp": "Has WiFi?", "chk": "Connecting to 8.8.8.8:53"},
        {"no": 2, "comp": "Weighing Tank (Ultrasonic)", "chk": "Object depth / Ultrasonic reading"},
        {"no": 3, "comp": "Weighing Tank (Load Cell)", "chk": "Weight / Load cell reading"},
        {"no": 4, "comp": "Barrel", "chk": "Storage level / Ultrasonic reading"},
        {"no": 5, "comp": "Filter #1", "chk": "Flow & Turbidity status"},
        {"no": 6, "comp": "Door Sensors", "chk": "Relay input / Security status"}
    ]
    for test in tests:
        update_diagnostic_status(test["no"], "Online", test["comp"], test["chk"], "IN_PROGRESS")
        time.sleep(0.1)

    try:
        with socket.create_connection(("8.8.8.8", 53), timeout=3): pass
        update_diagnostic_status(1, "Online", "Has WiFi?", "Connected", "✅")
    except Exception as e:
        update_diagnostic_status(1, "Online", "Has WiFi?", f"Error: {e}", "❌")

    time.sleep(0.5)

    try:
        us_small = send_to_arduino("CHECK_ULTRASONIC_SMALL")
        status_us_small = "✅" if us_small and "OK" in str(us_small) else "❌"
        update_diagnostic_status(2, "Online", "Weighing Tank (Ultrasonic)", "Object depth / Ultrasonic reading", status_us_small, f"US Reading: {us_small}" if status_us_small=="❌" else "")
    except Exception as e:
        update_diagnostic_status(2, "Online", "Weighing Tank (Ultrasonic)", f"Error: {e}", "❌")

    time.sleep(0.5)

    try:
        test_weight = get_weight_from_sensor()
        status_lc = "✅" if test_weight is not None else "❌"
        update_diagnostic_status(3, "Online", "Weighing Tank (Load Cell)", "Weight / Load cell reading", status_lc, f"{test_weight} kg")
    except Exception as e:
        update_diagnostic_status(3, "Online", "Weighing Tank (Load Cell)", f"Error: {e}", "❌")

    time.sleep(0.5)

    try:
        us_res = send_to_arduino("CHECK_ULTRASONIC_RES")
        status_us_res = "✅" if us_res and "OK" in str(us_res) else "❌"
        update_diagnostic_status(4, "Online", "Barrel", "Storage level / Ultrasonic reading", status_us_res, f"Barrel Reading: {us_res}" if status_us_res=="❌" else "")
    except Exception as e:
        update_diagnostic_status(4, "Online", "Barrel", f"Error: {e}", "❌")

    time.sleep(0.5)

    try:
        turbidity_val = get_turbidity_from_arduino()
        if turbidity_val is None: update_diagnostic_status(5, "Online", "Filter #1", "Flow & Turbidity status", "❌", "No reading")
        else: update_diagnostic_status(5, "Online", "Filter #1", "Flow & Turbidity status", "✅", f"Raw: {turbidity_val}")
    except Exception as e:
        update_diagnostic_status(5, "Online", "Filter #1", "Flow & Turbidity status", "❌", f"Error: {e}")

    time.sleep(0.5)

    try:
        door_top = send_to_arduino("get_door_state")
        door_2 = send_to_arduino("CHECK_DOOR_GPIO3")
        doors_ok = ("door_closed" in str(door_top)) and ("CLOSED" in str(door_2))
        update_diagnostic_status(6, "Online", "Door Sensors", "Relay input / Security status", "✅" if doors_ok else "FAIL", "Check doors" if not doors_ok else "")
    except Exception as e:
        update_diagnostic_status(6, "Online", "Door Sensors", f"Error: {e}", "FAIL")
    print("--- ONLINE DIAGNOSTICS COMPLETE ---\n")

def run_physical_diagnostics(component_name):
    global manual_test_running, machine_mode 
    if machine_mode != "IDLE" or getattr(globals(), 'customer_cycle_running', False): return
    manual_test_running = True
    machine_mode = "MANUAL_TEST"
    try:
        if component_name == "Pump":
            send_to_arduino("excess_pump_start")
            time.sleep(5); send_to_arduino("excess_pump_stop")
        elif component_name == "Door Lock":
            send_to_arduino("unlock_tech")
            time.sleep(5); send_to_arduino("LOCK")
        elif component_name == "Wiper Motor":
            send_to_arduino("DUMMY_WIPER_ON") 
            time.sleep(3); send_to_arduino("DUMMY_WIPER_OFF")
        elif component_name == "Door Motor":
            send_to_arduino("AUTO_DOOR_OPEN") 
            time.sleep(8)
            send_to_arduino("AUTO_DOOR_CLOSE")
        elif component_name == "Valve":
            send_to_arduino("PIN25_ON")
            time.sleep(10); send_to_arduino("PIN25_OFF")
    except Exception as e: print(f"❌ Error testing {component_name}: {e}")
    finally:
        manual_test_running = False
        machine_mode = "IDLE"

# ------------------------------
# SIGNALR & STATUS
# ------------------------------
def send_status_loop():
    global status_enabled
    while True:
        try:
            if status_enabled: hub_connection.send("SendStatus", [machine_id, "Active"])
        except Exception as e: pass
        time.sleep(5)

hub_url = f"https://gallows-qualm-dazzler.ngrok-free.dev/machineHub?machineId={machine_id}"
hub_connection = (HubConnectionBuilder().with_url(hub_url).with_automatic_reconnect({"type": "raw", "keep_alive_interval": 10, "reconnect_interval": 5, "max_attempts": 5}).configure_logging(logging.INFO).build())

def on_open():
    print("[CLIENT] ✅ Connected to server")
    time.sleep(0.5); send_to_arduino("LED_GREEN_ON")

def reconnect_forever():
    while True:
        try: hub_connection.start(); return
        except: time.sleep(5)
            
def on_close(): reconnect_forever()

def on_receive_command(command):
    cmd = command[0] if isinstance(command, list) and command else command
    if cmd == "CollectorEnd":
        send_to_arduino("PIN25_OFF")
        global pin25_on; pin25_on = False
        requests.post(FINAL_COLLECTOR_SUBMIT_URL , json={"token": TOKEN, "machineId":machine_id}, timeout=5)
    elif cmd.startswith("ManualTest"):
        test_name = cmd.replace("ManualTest", "").lower()
        if test_name == "doorlock1": trigger_manual_physical_test("door_lock_1")
        elif test_name == "pump": trigger_manual_physical_test("pump")

def _manual_test_worker(test_name):
    global manual_test_running, machine_mode
    on_cmd, off_cmd, duration = MANUAL_TESTS[test_name]
    try:
        manual_test_running = True; machine_mode = "MANUAL_TEST"
        publish_manual_test_status(test_name, "RUNNING")
        if not send_to_arduino(on_cmd): return publish_manual_test_status(test_name, "FAILED")
        time.sleep(duration); send_to_arduino(off_cmd)
        publish_manual_test_status(test_name, "DONE")
    except: publish_manual_test_status(test_name, "FAILED")
    finally: manual_test_running = False; machine_mode = "IDLE"

def trigger_manual_physical_test(test_name):
    with manual_test_lock:
        if test_name not in MANUAL_TESTS: return "UNKNOWN_TEST"
        threading.Thread(target=_manual_test_worker, args=(test_name,), daemon=True).start()

hub_connection.on("ReceiveCommand", on_receive_command)  
hub_connection.on("RunOnlineDiagnostics", lambda args: threading.Thread(target=run_online_diagnostics, daemon=True).start() if args and args[0]==machine_id else None)
hub_connection.on("RunPhysicalDiagnostics", lambda args: threading.Thread(target=run_physical_diagnostics, args=(args[1],), daemon=True).start() if args and args[0]==machine_id else None)
hub_connection.on_open(on_open)
hub_connection.on_close(on_close)

# ------------------------------
# INTERNET CHECK
# ------------------------------
def check_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout): return True
    except OSError: return False

def internet_monitor_loop():
    global internet_available, last_sent_internet_state
    while True:
        try:
            state = check_internet()
            with internet_lock: internet_available = state
            if state != last_sent_internet_state:
                if state: send_to_arduino("HAS_INTERNET")
                else: send_to_arduino("NO_INTERNET")
                last_sent_internet_state = state
        except: pass
        time.sleep(5)

# ------------------------------
# API HELPERS
# ------------------------------
def create_machine_overflow(payload):
    try: requests.post(OVERFLOW_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=5)
    except: pass

def create_machine_audit(payload):
    try: requests.post(AUDIT_CREATE_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=5)
    except: pass

def send_final_data(oil_amount):
    try: requests.post(FINAL_SUBMIT_URL, json={"token": TOKEN, "oilAmount": round(oil_amount, 2), "machineId":machine_id}, timeout=5)
    except: pass

# ------------------------------
# QR HANDLING
# ------------------------------
def wait_for_qr():
    print("⏳ Waiting for QR scan...")
    scanned_str = ""
    
    # NEW: Flush any pending ghost/accidental scans from the buffer before waiting
    if sys.platform == 'win32':
        import msvcrt
        while msvcrt.kbhit(): msvcrt.getwch()
    else:
        # Quickly read and discard any unread lines in the stdin buffer
        while select.select([sys.stdin], [], [], 0)[0]:
            sys.stdin.readline()

    if sys.platform == 'win32':
        import msvcrt
        while True:
            wd.kick()
            if manual_test_running: time.sleep(0.2); continue
            if msvcrt.kbhit():
                char = msvcrt.getwche()
                if char in ('\r', '\n'):
                    if not scanned_str.strip(): continue # Ignore empty enter keys
                    if is_tech_door_open():
                        print("🚫 Tech door is OPEN. QR scan ignored.")
                        scanned_str = ""
                        continue
                    return scanned_str.strip()
                else: 
                    scanned_str += char
            time.sleep(0.1)
    else:
        while True:
            wd.kick()
            if manual_test_running: time.sleep(0.2); continue
            readable, _, _ = select.select([sys.stdin], [], [], 1)
            if readable:
                scanned = sys.stdin.readline().strip()
                if scanned:
                    if is_tech_door_open():
                        print("🚫 Tech door is OPEN. QR scan ignored.")
                        continue
                    return scanned
            time.sleep(0.1)

def send_qr_to_api(qr_token):
    global TOKEN
    payload = {"token": qr_token, "machineId": machine_id}
    try:
        wd.kick()
        response = requests.post(QR_VALIDATE_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            success = data.get("success")
            if isinstance(success, str) and "PANEL" in success.upper():
                TOKEN = qr_token; return success.upper()
            elif success is True or success is None:
                TOKEN = qr_token
                return data.get("panelType") or data.get("role") or data.get("panel") or data.get("paneltype")
    except: pass
    return None

# ------------------------------
# PUMP SAFETY & AUTO-DRAIN
# ------------------------------
def start_pump_safety_timer(mode: str):
    global pump_timer, pump_mode, pump_timeout_reached
    with pump_timer_lock:
        pump_mode = mode; pump_timeout_reached = False  
        try:
            if pump_timer is not None: pump_timer.cancel()
        except: pass
        def timeout():
            global pump_timeout_reached, pump_mode
            pump_timeout_reached = True
            try:
                send_to_arduino("excess_pump_stop")
                time.sleep(0.2)
                send_to_arduino("LOCK")
            except: pass
        pump_timer = threading.Timer(PUMP_TIMEOUT_SEC, timeout); pump_timer.daemon = True; pump_timer.start()

def stop_pump_safety_timer():
    global pump_timer, pump_mode
    with pump_timer_lock:
        try:
            if pump_timer is not None: pump_timer.cancel()
        except: pass
        pump_timer = None; pump_mode = None

def monitor_and_stop_pump():
    while True:
        weight = get_weight_from_sensor()
        if weight is not None:
            send_to_arduino(f"weight:{weight}")
            if weight <= 0.2 or pump_timeout_reached:
                stop_pump_safety_timer(); 
                send_to_arduino("excess_pump_stop")
                send_to_arduino("LOCK")
                break
        time.sleep(1)

def run_global_auto_drain():
    global pump_timeout_reached, global_auto_drain_active
    if global_auto_drain_active: return
    global_auto_drain_active = True
    try:
        send_to_arduino("excess_pump_start")
        start_pump_safety_timer("excess")
        while True:
            wd.kick()
            w = get_weight_from_sensor()
            if w <= 0.25 or pump_timeout_reached:
                send_to_arduino("excess_pump_stop"); stop_pump_safety_timer(); send_to_arduino("LOCK"); break
            try: send_to_arduino(f"weight:{w}")
            except: pass
            time.sleep(1)
    except: pass
    finally:
        global_auto_drain_active = False; stop_pump_safety_timer()

def global_auto_drain_monitor():
    while True:
        try:
            wd.kick()
            if customer_cycle_running or auto_drain_active or weight_read_in_progress:
                time.sleep(0.8); continue
            w = get_weight_from_sensor()
            if w is not None and w > 10.0: threading.Thread(target=run_global_auto_drain, daemon=True).start()
        except: pass
        time.sleep(1)

# ------------------------------
# PANELS / CYCLES
# ------------------------------
def customer_cycle():
    global status_enabled, auto_drain_active, customer_cycle_running
    customer_cycle_running = True
    print("🚀 Starting customer cycle...")
    
    send_to_arduino("unlock")
    create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Customer verified - Top door unlock"})
    
    door_opened = False
    start_time = time.time()
    
    while time.time() - start_time < 60:
        wd.kick()
        if mega_message_queue:
            if mega_message_queue.pop(0) == "door_opened": door_opened = True; break
        if mega_ser.in_waiting:
            msg = mega_ser.readline().decode(errors="ignore").strip()
            if msg == "door_opened": door_opened = True; break
            elif msg: mega_message_queue.append(msg)
        time.sleep(0.1)

    if not door_opened:
        create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Top door not opened - lock engaged."})
        send_to_arduino("LOCK"); send_final_data(0.0)
        customer_cycle_running = False
        return

    last_weight = 0.0
    stable_time_start = time.time()
    motor_close_triggered = False

    while True:
        wd.kick()
        weight_live = get_weight_from_sensor()
        
        if weight_live is not None:
            print(f"⚖️ Live weight while pouring: {weight_live} kg")
            
            if weight_live > 10.0:
                auto_drain_active = True
                create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": f"Auto-drain triggered at {weight_live}kg"})
                send_to_arduino("LOCK")
                time.sleep(0.30)
                send_final_data(w)
                send_to_arduino("excess_pump_start")
                start_pump_safety_timer("normal")

                while True:
                    wd.kick()
                    weight = get_weight_from_sensor()
                    if weight is not None:
                        # Send to mega just in case they update the arduino software in the future
                        send_to_arduino(f"weight:{weight}")
                        if weight <= 0.2 or pump_timeout_reached:
                            create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Machine stopped pumping."})
                            send_to_arduino("excess_pump_stop")
                            stop_pump_safety_timer()
                            send_to_arduino("LOCK")
                            
                            # NEW: Tell the Mega the machine is ready for the next user
                            time.sleep(0.5)
                            send_to_arduino("LED_GREEN_ON")
                            
                            break
                    time.sleep(1)
                break

            if not motor_close_triggered:
                if abs(weight_live - last_weight) > 0.05: 
                    stable_time_start = time.time(); last_weight = weight_live
                elif (time.time() - stable_time_start > 15 and weight_live >= MIN_POUR_WEIGHT) or (time.time() - start_time > 120):
                    send_to_arduino("AUTO_DOOR_CLOSE"); motor_close_triggered = True

        msg = mega_message_queue.pop(0) if mega_message_queue else (mega_ser.readline().decode(errors="ignore").strip() if mega_ser.in_waiting else None)

        if msg:
            if msg == "door_closed" or msg == "doors_locked":
                if auto_drain_active: send_to_arduino("excess_pump_start"); time.sleep(0.2)
                create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Machine door closed."})
                
                w = get_weight_from_sensor()
                if w is None or w < 0: w = 0
                
                if w < MIN_POUR_WEIGHT:
                    create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": f"No oil poured ({w} kg) - Pump skipped"})
                    send_final_data(0.0); send_to_arduino("LOCK"); customer_cycle_running = False
                    return

                turbidity_val = get_turbidity_from_arduino()
                oil_quality = "UNKNOWN" if turbidity_val is None else classify_turbidity(turbidity_val)
                
                create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": f"Oil quality classified as {oil_quality}"})
                log_telemetry_to_dashboard("Customer Pour Completed", w, turbidity_val if turbidity_val else -1, oil_quality)

                # TRIGGER NORMAL PUMP TRANSFER
                send_final_data(w)
                send_to_arduino("excess_pump_start") 
                start_pump_safety_timer("normal")

                while True:
                    wd.kick()
                    weight = get_weight_from_sensor()
                    if weight is not None:
                        # Send to mega just in case they update the arduino software in the future
                        send_to_arduino(f"weight:{weight}")
                        if weight <= 0.2 or pump_timeout_reached:
                            create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Machine stopped pumping."})
                            send_to_arduino("excess_pump_stop")
                            stop_pump_safety_timer()
                            send_to_arduino("LOCK")
                            break
                    time.sleep(1)
                break
            elif msg.strip() == "overflow_confirmed":
                create_machine_overflow({"token": TOKEN, "machineId": machine_id})
                create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": f"Overflow Detected :{msg}"})
                send_to_arduino("LOCK"); monitor_and_stop_pump()
                break
        time.sleep(0.2)
    
    auto_drain_active = False; customer_cycle_running = False

def tare_scale():
    """Sends the tare command to the Uno to zero the scale."""
    try:
        if not isinstance(uno_ser, DummySerial):
            uno_ser.write(b"t\n")
            uno_ser.flush()
            print("⚖️ Taring scale to 0.000 kg...")
            time.sleep(0.5) # Give the Uno a moment to process the tare
    except Exception as e:
        print(f"❌ Failed to tare scale: {e}")

def collector_cycle():
    global pin25_on, auto_off_timer
    if not pin25_on:
        send_to_arduino("PIN25_ON")
        create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Collector verified - solenoid valve activated"})
        pin25_on = True
        def auto_turn_off():
            global pin25_on
            if pin25_on:
                send_to_arduino("PIN25_OFF"); create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Auto-off expired"})
                pin25_on = False
        try: auto_off_timer.cancel()
        except: pass
        auto_off_timer = threading.Timer(600, auto_turn_off); auto_off_timer.daemon = True; auto_off_timer.start()
    else:
        send_to_arduino("PIN25_OFF")
        create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Collector verified - solenoid valve deactivated"})
        pin25_on = False
        try: auto_off_timer.cancel()
        except: pass

def technician_cycle():
    send_to_arduino("unlock_tech")    
    create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Technician verified - tech door unlocked."})
    start = time.time() 
    while time.time() - start < 20: wd.kick(); time.sleep(0.2)
    send_to_arduino("LOCK")
    create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Auto-lock timer expired. Tech door locked."})

# ------------------------------
# Main Logic Loop
# ------------------------------
def main():
    global wd, TOKEN, machine_mode 
    wd = Watchdog(timeout=120, pre_restart_callback=lambda: send_to_arduino("LOCK"))
    
    # START ONLY THE LOAD CELL READER THREAD (Safe to run early)
    threading.Thread(target=load_cell_reader_loop, daemon=True).start()

    print("🔌 Initiating Arduino Handshake...")
    connected = False
    
    # Send handshake to Uno
    try: uno_ser.write(b"PYTHON_READY\n")
    except: pass
    
    # Wait intelligently for the Mega to complete its potential 10-second boot safety sequence
    while not connected:
        with mega_lock:
            try:
                mega_ser.reset_input_buffer()
                mega_ser.write(b"PYTHON_READY\n")
                mega_ser.flush()
            except: pass
            
        end = time.time() + 2
        while time.time() < end:
            try:
                if mega_ser.in_waiting:
                    line = mega_ser.readline().decode(errors="ignore").strip()
                    if line: 
                        print(f"[MEGA BOOT] {line}")
                    if line == "PYTHON_READY_ACK":
                        connected = True
                        break
            except: pass
            time.sleep(0.1)
            
        if not connected:
            print("⏳ Waiting for Mega safety boot sequence to finish...")

    time.sleep(0.5)

    # ==========================================
    # HANDSHAKE COMPLETE! NOW START BACKGROUND TASKS
    # ==========================================
    threading.Thread(target=internet_monitor_loop, daemon=True).start()
    threading.Thread(target=global_auto_drain_monitor, daemon=True).start()
    threading.Thread(target=send_status_loop, daemon=True).start()

    # Start SignalR Server Connection
    try: hub_connection.start()
    except: threading.Thread(target=reconnect_forever, daemon=True).start()

    # Run diagnostics immediately on boot
    run_online_diagnostics()

    while True:
        wd.kick()
        if manual_test_running: time.sleep(0.2); continue

        machine_mode = "IDLE"
        TOKEN = wait_for_qr()
        machine_mode = "BUSY"

        tare_scale()

        try:
            create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "QR Scanned."})
            panel_type = send_qr_to_api(TOKEN)
            
            # NEW: Normalize the panel_type to avoid case-mismatch bugs
            if panel_type and isinstance(panel_type, str):
                panel_type = panel_type.strip().upper()

            if not panel_type: 
                print(f"⚠️ API rejected the QR token or returned empty. Token: {TOKEN}")
                continue

            if panel_type == "CUSTOMERPANEL":
                create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Customer QR scanned"})
                customer_cycle()

            elif panel_type == "COLLECTORPANEL":
                create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Collector QR scanned"})
                collector_cycle()

            elif panel_type == "TECHNICIANPANEL":
                create_machine_audit({"qrToken": TOKEN, "machineId": machine_id, "action": "Technician QR scanned"})
                technician_cycle()
            else:
                # NEW: Log what panel type actually caused the lock
                print(f"⚠️ Unknown panel type received: '{panel_type}'. Locking doors.")
                send_to_arduino("LOCK")
            time.sleep(2)

        finally:
            machine_mode = "IDLE"

# ------------------------------
# Program Entry Point
# ------------------------------
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ Program stopped by user.")
        try: mega_ser.close()
        except: pass
        try: uno_ser.close()
        except: pass