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
# ISOLATED MANUAL PHYSICAL TESTS GLOBALS
# ------------------------------
manual_test_lock = threading.Lock()
manual_test_running = False
machine_mode = "IDLE"   # IDLE / BUSY / MANUAL_TEST

manual_test_status = {
    "name": None,
    "state": "IDLE"
}

MANUAL_TESTS = {
    "door_lock_1": ("TEST_LOCK1_ON", "TEST_LOCK1_OFF", 5),
    "door_lock_2": ("TEST_LOCK2_ON", "TEST_LOCK2_OFF", 5),
    "door_lock_3": ("TEST_LOCK3_ON", "TEST_LOCK3_OFF", 5),
    "pump":        ("TEST_PUMP_ON",  "TEST_PUMP_OFF",  5),
    "valve":       ("TEST_VALVE_ON", "TEST_VALVE_OFF", 10),
}

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

    def _monitor(self):
        while self.active:
            if time.time() - self.last_kick > self.timeout:
                print("[WATCHDOG] Main logic stuck. Restarting Python...")

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
        self.last_command = data.decode(errors='ignore').strip()
        self.in_waiting = True 
        
    def readline(self): 
        self.in_waiting = False
        if self.last_command == "check_psu":
            return b"PSU:OK,12.05V,5.01V\n"
        return b"door_closed\n"
        
    def close(self): pass
    def flush(self): pass

# ------------------------------
# HARDWARE INITIALIZATION
# ------------------------------
uno_lock = threading.Lock()
mega_lock = threading.Lock()

auto_off_timer = None
door_off_timer = None

try:
    # IMPORTANT: Update these COM ports to match your machine!
    uno_ser = serial.Serial('/dev/ttyACM1', 9600, timeout=1) 
    mega_ser = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
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

while time.time() - start < 2:
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

# ------------------------------
# PYTHON READY HANDSHAKE (UNO)
# ------------------------------
print("[STARTUP] Sending PYTHON_READY to UNO...")
with uno_lock:
    uno_ser.write(b"PYTHON_READY\n")
time.sleep(0.2)

with uno_lock:
    uno_ser.reset_input_buffer()

# API ENDPOINT
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
door_monitor_thread = None
pump_timeout_reached = False
MIN_POUR_WEIGHT = 0.100 # kg

mega_message_queue = []

internet_available = False
last_sent_internet_state = None
internet_lock = threading.Lock()

# ------------------------------
# TURBIDITY SETTINGS
# Adjust after calibration
# ------------------------------
TURBIDITY_GOOD_MAX = 450
TURBIDITY_POOR_MAX = 750
TURBIDITY_WATER_MAX = 200

# ------------------------------
# ARDUINO COMMUNICATION HELPER
# ------------------------------
def send_to_arduino(command, timeout=0.8):
    with mega_lock:
        try:
            mega_ser.reset_input_buffer()
        except:
            pass
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
            except Exception as e:
                pass
            time.sleep(0.05)
            
        print(f"[MEGA ACK] {command} -> (NO REPLY)")
        return None

# ------------------------------
# INTERACTIVE DIAGNOSTICS LOGIC (NEW)
# ------------------------------
def update_diagnostic_status(log_no, log_type, component, checking, status, action=""):
    payload = {
        "MachineId": machine_id,
        "Timestamp": time.time(),
        "No": log_no,
        "Type": log_type,
        "Component": component,
        "Checking": checking,
        "Status": status,
        "Action": action
    }
    
    # 1. ADD HEADERS TO BYPASS NGROK WARNING
    headers = {
        "Content-Type": "application/json",
        "ngrok-skip-browser-warning": "true" 
    }
    
    try:
        requests.post(DIAGNOSTICS_URL, json=payload, headers=headers, timeout=3)
    except Exception as e:
        print(f"⚠️ Failed to update diagnostic status for {component}: {e}")

def publish_manual_test_status(test_name, status):
    mapping = {
        "door_lock_1": "Door Lock",
        "door_lock_2": "Door Lock",
        "door_lock_3": "Door Lock",
        "pump": "Pump",
        "valve": "Valve"
    }
    comp_name = mapping.get(test_name, test_name)
    ui_status = "☑" if status == "DONE" else ("IN_PROGRESS" if status == "RUNNING" else "X")
    
    update_diagnostic_status(0, "Physical", comp_name, f"Manual Test: {status}", ui_status)


def run_online_diagnostics(tared_status=True):
    print("\n--- 🌐 STARTED ONLINE DIAGNOSTICS ---")
    
    # 1. Define structure mapping matching the Vue frontend
    # WARNING: The "comp" names here MUST perfectly match the names in the actual tests below!
    tests = [
        {"no": 1, "comp": "Has WiFi?", "chk": "Connecting to 8.8.8.8:53"},
        {"no": 2, "comp": "Weighing Tank (Ultrasonic)", "chk": "Object depth / Ultrasonic reading"},
        {"no": 3, "comp": "Weighing Tank (Load Cell)", "chk": "Weight / Load cell reading"},
        {"no": 4, "comp": "Barrel", "chk": "Storage level / Ultrasonic reading"},
        {"no": 5, "comp": "Filter #1", "chk": "Flow & Turbidity status"},
        {"no": 6, "comp": "Door Sensors", "chk": "Relay input / Security status"}
    ]

    # 2. Notify UI that tests are starting (This renders the IN_PROGRESS spinners)
    for test in tests:
        update_diagnostic_status(test["no"], "Online", test["comp"], test["chk"], "IN_PROGRESS")
        time.sleep(0.1)

    # ---------------------------------------------------------
    # ACTUAL HARDWARE & NETWORK TESTS
    # ---------------------------------------------------------

    # 1. WiFi Test (Using reliable Python sockets)
    try:
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        update_diagnostic_status(1, "Online", "Has WiFi?", "Connected", "☑")
    except Exception as e:
        update_diagnostic_status(1, "Online", "Has WiFi?", f"Error: {e}", "X")

    time.sleep(0.5)

    # 2. Ultrasonic (Weighing)
    try:
        us_small = send_to_arduino("CHECK_ULTRASONIC_SMALL")
        status_us_small = "☑" if us_small and "OK" in str(us_small) else "X"
        update_diagnostic_status(2, "Online", "Weighing Tank (Ultrasonic)", "Object depth / Ultrasonic reading", status_us_small, f"US Reading: {us_small}" if status_us_small=="X" else "")
    except Exception as e:
        update_diagnostic_status(2, "Online", "Weighing Tank (Ultrasonic)", f"Error: {e}", "X")

    time.sleep(0.5)

    # 3. Load Cell
    try:
        status_lc = "☑" if tared_status else "X"
        update_diagnostic_status(3, "Online", "Weighing Tank (Load Cell)", "Weight / Load cell reading", status_lc)
    except Exception as e:
        update_diagnostic_status(3, "Online", "Weighing Tank (Load Cell)", f"Error: {e}", "X")

    time.sleep(0.5)

    # 4. Barrel
    try:
        us_res = send_to_arduino("CHECK_ULTRASONIC_RES")
        status_us_res = "☑" if us_res and "OK" in str(us_res) else "X"
        update_diagnostic_status(4, "Online", "Barrel", "Storage level / Ultrasonic reading", status_us_res, f"Barrel Reading: {us_res}" if status_us_res=="X" else "")
    except Exception as e:
        update_diagnostic_status(4, "Online", "Barrel", f"Error: {e}", "X")

    time.sleep(0.5)

    # 5. Filter #1 / Turbidity (reading only)
    try:
        turbidity_val = get_turbidity_from_arduino()

        if turbidity_val is None:
            update_diagnostic_status(
                5,
                "Online",
                "Filter #1",
                "Flow & Turbidity status",
                "X",
                "No turbidity reading from Arduino"
            )
        elif not isinstance(turbidity_val, int):
            update_diagnostic_status(
                5,
                "Online",
                "Filter #1",
                "Flow & Turbidity status",
                "X",
                f"Invalid turbidity type: {type(turbidity_val).__name__}"
            )
        elif turbidity_val < 0 or turbidity_val > 1023:
            update_diagnostic_status(
                5,
                "Online",
                "Filter #1",
                "Flow & Turbidity status",
                "X",
                f"Out-of-range turbidity reading: {turbidity_val}"
            )
        else:
            update_diagnostic_status(
                5,
                "Online",
                "Filter #1",
                "Flow & Turbidity status",
                "☑",
                f"Turbidity Raw Reading: {turbidity_val}"
            )

    except Exception as e:
        update_diagnostic_status(
            5,
            "Online",
            "Filter #1",
            "Flow & Turbidity status",
            "X",
            f"Error: {e}"
        )

    time.sleep(0.5)

    # 6. Door Sensors
    try:
        door_top = send_to_arduino("get_door_state")
        door_2 = send_to_arduino("CHECK_DOOR_GPIO2")
        doors_ok = ("door_closed" in str(door_top)) and ("CLOSED" in str(door_2))
        update_diagnostic_status(6, "Online", "Door Sensors", "Relay input / Security status", "☑" if doors_ok else "X", "Check doors" if not doors_ok else "")
    except Exception as e:
        update_diagnostic_status(6, "Online", "Door Sensors", f"Error: {e}", "X")

    print("--- ONLINE DIAGNOSTICS COMPLETE ---\n")

def run_physical_diagnostics(component_name):
    # This MUST be at the very top of the function to prevent the SyntaxError
    global manual_test_running, machine_mode 
    
    print(f"\n--- 🛠️ MANUAL TEST TRIGGERED: {component_name} ---")
    
    # 1. SAFETY LOCK: Ensure machine is idle before running physical motor tests
    if machine_mode != "IDLE" or getattr(globals(), 'customer_cycle_running', False):
        print(f"⚠️ Machine is BUSY. Cannot safely test {component_name}.")
        return

    manual_test_running = True
    machine_mode = "MANUAL_TEST"

    try:
        # 2. Trigger hardware briefly for the technician to observe physically
        if component_name == "Pump":
            send_to_arduino("pump_now")
            time.sleep(3)
            send_to_arduino("LOCK") 
            
        elif component_name == "Door Lock":
            send_to_arduino("unlock")
            time.sleep(3)
            send_to_arduino("LOCK")
            
        elif component_name == "Valve":
            send_to_arduino("PIN25_ON")
            time.sleep(3)
            send_to_arduino("PIN25_OFF")
            
        elif component_name == "Wiper Motor":
            send_to_arduino("WIPER_ON") 
            time.sleep(3)
            send_to_arduino("WIPER_OFF")
            
        elif component_name == "Door Motor":
            send_to_arduino("DOOR_MOTOR_ON") 
            time.sleep(3)
            send_to_arduino("DOOR_MOTOR_OFF")
            
        elif component_name == "Qr Scanner":
            send_to_arduino("LED_GREEN_ON")
            time.sleep(2)
            send_to_arduino("LOCK")
            
        else:
            time.sleep(2)
            
        print(f"✅ Physical action for {component_name} finished. Awaiting manual UI check.")

    except Exception as e:
        print(f"⚠️ Error testing {component_name}: {e}")
        
    finally:
        # 4. Release the locks so normal machine operation can resume
        manual_test_running = False
        machine_mode = "IDLE"

# ------------------------------
# TELEMETRY & VOLUME HELPERS
# ------------------------------
def calculate_ibc_volume(distance_cm):
    if distance_cm <= 0: return 0.0  
    TANK_HEIGHT = 100.0
    TANK_LENGTH = 120.0
    TANK_WIDTH = 80.0
    
    oil_depth = TANK_HEIGHT - distance_cm
    if oil_depth < 0: return 0.0 
    
    volume_liters = (TANK_LENGTH * TANK_WIDTH * oil_depth) / 1000.0
    return round(max(0.0, min(500.0, volume_liters)), 2)

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
# ULTRASONIC WEIGHT CALIBRATION
# ------------------------------
# **CRITICAL:** Adjust SMALL_TANK_EMPTY_CM to the EXACT distance (in cm) 
# your ultrasonic sensor reads when the small tank is completely empty.
SMALL_TANK_EMPTY_CM = 29.0   
SMALL_TANK_FULL_CM = 8.6    # Matches Arduino's SMALL_TANK_THRESHOLD
MAX_OIL_KG = 10.0            # Max capacity at the FULL_CM mark

# ------------------------------
# ISOLATED MANUAL PHYSICAL TESTS GLOBALS
# ------------------------------
manual_test_lock = threading.Lock()
manual_test_running = False
wiper_running = False
machine_mode = "IDLE"   # IDLE / BUSY / MANUAL_TEST

manual_test_status = {
    "name": None,
    "state": "IDLE"
}

MANUAL_TESTS = {
    "door_lock_1": ("TEST_LOCK1_ON", "TEST_LOCK1_OFF", 5),
    "door_lock_2": ("TEST_LOCK2_ON", "TEST_LOCK2_OFF", 5),
    "door_lock_3": ("TEST_LOCK3_ON", "TEST_LOCK3_OFF", 5),
    "pump":        ("TEST_PUMP_ON",  "TEST_PUMP_OFF",  5),
    "valve":       ("TEST_VALVE_ON", "TEST_VALVE_OFF", 10),
}

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

    def _monitor(self):
        while self.active:
            if time.time() - self.last_kick > self.timeout:
                print("[WATCHDOG] Main logic stuck. Restarting Python...")

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
        self.last_command = data.decode(errors='ignore').strip()
        self.in_waiting = True 
        
    def readline(self): 
        self.in_waiting = False
        
        if self.last_command == "check_psu":
            return b"PSU:OK,12.05V,5.01V\n"
        elif self.last_command == "CHECK_ULTRASONIC_SMALL":
            return b"CHECK_ULTRASONIC_SMALL:OK\n"
        elif self.last_command == "CHECK_ULTRASONIC_RES":
            return b"CHECK_ULTRASONIC_RES:OK\n"
        elif self.last_command == "CHECK_DOOR_GPIO2":
            return b"CHECK_DOOR_GPIO2:CLOSED\n"
        elif self.last_command == "get_small_dist":
            return b"small_dist:35.0\n"
        
        return b"door_closed\n"
        
    def close(self): pass
    def flush(self): pass

# ------------------------------
# HARDWARE INITIALIZATION
# ------------------------------
mega_lock = threading.Lock()
auto_off_timer = None

try:
    # Removed uno_ser as the load cell is broken
    mega_ser = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
    print("? Serial connected successfully.")
except serial.SerialException as e:
    print(f"? Serial connection error: {e}")
    print("? Falling back to DummySerial for testing...")
    mega_ser = DummySerial()

# ------------------------------
# ARDUINO COMMUNICATION HELPER
# ------------------------------
def send_to_arduino(command, timeout=0.8):
    with mega_lock:
        try:
            mega_ser.reset_input_buffer()
        except:
            pass
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
            except Exception as e:
                pass
            time.sleep(0.05)
            
        print(f"[MEGA ACK] {command} -> (NO REPLY)")
        return None

# ------------------------------
# PYTHON READY HANDSHAKE (MEGA)
# ------------------------------
print("[STARTUP] Sending PYTHON_READY to MEGA...")
send_to_arduino("PYTHON_READY")
time.sleep(0.2)

# API ENDPOINT
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
door_monitor_thread = None
pump_timeout_reached = False
MIN_POUR_WEIGHT = 0.100 # kg

internet_available = False
last_sent_internet_state = None
internet_lock = threading.Lock()

# ------------------------------
# INTERACTIVE DIAGNOSTICS LOGIC
# ------------------------------
def update_diagnostic_status(log_no, log_type, component, checking, status, action=""):
    payload = {
        "MachineId": machine_id,
        "Timestamp": time.time(),
        "No": log_no,
        "Type": log_type,
        "Component": component,
        "Checking": checking,
        "Status": status,
        "Action": action
    }
    
    headers = {
        "Content-Type": "application/json",
        "ngrok-skip-browser-warning": "true" 
    }
    
    try:
        requests.post(DIAGNOSTICS_URL, json=payload, headers=headers, timeout=3)
    except Exception as e:
        print(f"? Failed to update diagnostic status for {component}: {e}")

def publish_manual_test_status(test_name, status):
    mapping = {
        "door_lock_1": "Door Lock",
        "door_lock_2": "Door Lock",
        "door_lock_3": "Door Lock",
        "pump": "Pump",
        "valve": "Valve"
    }
    comp_name = mapping.get(test_name, test_name)
    ui_status = "?" if status == "DONE" else ("IN_PROGRESS" if status == "RUNNING" else "?")
    
    update_diagnostic_status(0, "Physical", comp_name, f"Manual Test: {status}", ui_status)


# ------------------------------
# TURBIDITY HELPERS
# ------------------------------
def classify_turbidity(raw_value):
    """Convert raw turbidity into a quality label."""
    if raw_value is None or raw_value < 0:
        return "UNKNOWN"

    if raw_value <= TURBIDITY_GOOD_MAX:
        return "GOOD"
    elif raw_value <= TURBIDITY_POOR_MAX:
        return "POOR"
    else:
        return "WATER_CONTAMINATED"
    
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
                else:
                    line = ""

            if line.startswith("turbidity:"):
                raw = line.replace("turbidity:", "").strip()
                return int(raw)

            time.sleep(0.1)

    except Exception as e:
        print(f"? Turbidity read error: {e}")

    return None


def run_online_diagnostics():
    print("\n--- ? STARTED ONLINE DIAGNOSTICS ---")
    
    tests = [
        {"no": 1, "comp": "Has WiFi?", "chk": "Connecting to 8.8.8.8:53"},
        {"no": 2, "comp": "Weighing Tank (Ultrasonic)", "chk": "Object depth / Ultrasonic reading"},
        {"no": 3, "comp": "Weighing Tank (Estimated Weight)", "chk": "Weight / Ultrasonic conversion"},
        {"no": 4, "comp": "Barrel", "chk": "Storage level / Ultrasonic reading"},
        {"no": 5, "comp": "Filter #1", "chk": "Flow & Turbidity status"},
        {"no": 6, "comp": "Door Sensors", "chk": "Relay input / Security status"}
    ]

    for test in tests:
        update_diagnostic_status(test["no"], "Online", test["comp"], test["chk"], "IN_PROGRESS")
        time.sleep(0.1)

    # 1. WiFi Test
    try:
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        update_diagnostic_status(1, "Online", "Has WiFi?", "Connected", "?")
    except Exception as e:
        update_diagnostic_status(1, "Online", "Has WiFi?", f"Error: {e}", "?")

    time.sleep(0.5)

    # 2. Ultrasonic (Weighing)
    try:
        us_small = send_to_arduino("CHECK_ULTRASONIC_SMALL")
        status_us_small = "?" if us_small and ("OK" in str(us_small) or "NO_READING" in str(us_small)) else "?"
        update_diagnostic_status(2, "Online", "Weighing Tank (Ultrasonic)", "Object depth / Ultrasonic reading", status_us_small, f"US Reading: {us_small}" if status_us_small=="?" else "")
    except Exception as e:
        update_diagnostic_status(2, "Online", "Weighing Tank (Ultrasonic)", f"Error: {e}", "?")

    time.sleep(0.5)

    # 3. Estimated Weight (Replaces Load Cell Check)
    try:
        test_weight = get_weight_from_sensor(samples=2)
        status_lc = "?" if test_weight is not None else "?"
        update_diagnostic_status(3, "Online", "Weighing Tank (Estimated Weight)", "Weight / Ultrasonic conversion", status_lc)
    except Exception as e:
        update_diagnostic_status(3, "Online", "Weighing Tank (Estimated Weight)", f"Error: {e}", "?")

    time.sleep(0.5)

    # 4. Barrel
    try:
        us_res = send_to_arduino("CHECK_ULTRASONIC_RES")
        status_us_res = "?" if us_res and ("OK" in str(us_res) or "NO_READING" in str(us_res)) else "?"
        update_diagnostic_status(4, "Online", "Barrel", "Storage level / Ultrasonic reading", status_us_res, f"Barrel Reading: {us_res}" if status_us_res=="?" else "")
    except Exception as e:
        update_diagnostic_status(4, "Online", "Barrel", f"Error: {e}", "?")

    time.sleep(0.5)

     # 5. Filter #1 / Turbidity (reading only)
    try:
        turbidity_val = get_turbidity_from_arduino()

        if turbidity_val is None:
            update_diagnostic_status(5, "Online", "Filter #1", "Flow & Turbidity status", "?", "No turbidity reading from Arduino")
        elif not isinstance(turbidity_val, int):
            update_diagnostic_status(5, "Online", "Filter #1", "Flow & Turbidity status", "?", f"Invalid turbidity type: {type(turbidity_val).__name__}")
        elif turbidity_val < 0 or turbidity_val > 1023:
            update_diagnostic_status(5, "Online", "Filter #1", "Flow & Turbidity status", "?", f"Out-of-range turbidity reading: {turbidity_val}")
        else:
            update_diagnostic_status(5, "Online", "Filter #1", "Flow & Turbidity status", "?", f"Turbidity Raw Reading: {turbidity_val}")

    except Exception as e:
        update_diagnostic_status(5, "Online", "Filter #1", "Flow & Turbidity status", "?", f"Error: {e}")

    time.sleep(0.5)

    # 6. Door Sensors
    try:
        door_top = send_to_arduino("get_door_state")
        door_2 = send_to_arduino("CHECK_DOOR_GPIO3")
        doors_ok = ("door_closed" in str(door_top)) and ("CLOSED" in str(door_2))
        update_diagnostic_status(6, "Online", "Door Sensors", "Relay input / Security status", "?" if doors_ok else "?", "Check doors" if not doors_ok else "")
    except Exception as e:
        update_diagnostic_status(6, "Online", "Door Sensors", f"Error: {e}", "?")

    print("--- ONLINE DIAGNOSTICS COMPLETE ---\n")

def run_physical_diagnostics(component_name):
    global manual_test_running, machine_mode 
    
    print(f"\n--- ? MANUAL TEST TRIGGERED: {component_name} ---")
    
    if machine_mode != "IDLE" or getattr(globals(), 'customer_cycle_running', False):
        print(f"? Machine is BUSY. Cannot safely test {component_name}.")
        return

    manual_test_running = True
    machine_mode = "MANUAL_TEST"

    try:
        if component_name == "Pump":
            send_to_arduino("excess_pump_start")
            time.sleep(5)
            send_to_arduino("excess_pump_stop")
            
        elif component_name == "Door Lock":
            send_to_arduino("unlock_tech")
            time.sleep(5) 
            send_to_arduino("LOCK")
            
        elif component_name == "Wiper Motor":
            send_to_arduino("DUMMY_WIPER_ON") 
            time.sleep(3)
            send_to_arduino("DUMMY_WIPER_OFF")
            
        elif component_name == "Door Motor":
            send_to_arduino("DUMMY_DOOR_MOTOR_ON") 
            time.sleep(3)
            send_to_arduino("DUMMY_DOOR_MOTOR_OFF")
            
        elif component_name == "Valve":
            send_to_arduino("PIN25_ON")
            time.sleep(10)
            send_to_arduino("PIN25_OFF")
            
        else:
            time.sleep(2)
            
        print(f"? Physical action for {component_name} finished. Awaiting manual UI check.")

    except Exception as e:
        print(f"? Error testing {component_name}: {e}")
        
    finally:
        manual_test_running = False
        machine_mode = "IDLE"

# ------------------------------
# TELEMETRY & VOLUME HELPERS
# ------------------------------
def calculate_ibc_volume(distance_cm):
    if distance_cm <= 0: return 0.0  
    TANK_HEIGHT = 100.0
    TANK_LENGTH = 120.0
    TANK_WIDTH = 80.0
    
    oil_depth = TANK_HEIGHT - distance_cm
    if oil_depth < 0: return 0.0 
    
    volume_liters = (TANK_LENGTH * TANK_WIDTH * oil_depth) / 1000.0
    return round(max(0.0, min(500.0, volume_liters)), 2)

def get_telemetry_from_arduino():
    try:
        mega_ser.reset_input_buffer()
        mega_ser.write(b"get_telemetry\n")
        time.sleep(0.2)
        
        for _ in range(5):
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
        print(f"? Telemetry parse error: {e}")
        
    return {"turbidity": 0, "junk_dist": 0.0, "res_dist": 0.0}

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
            print(f"[CLIENT] ? Failed to send status: {e}")
        time.sleep(5)

# ------------------------------
# SignalR Setup
# ------------------------------
hub_url = f"https://gallows-qualm-dazzler.ngrok-free.dev/machineHub?machineId={machine_id}"
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
    print("[CLIENT] ? Connected to server")
    send_to_arduino("PYTHON_READY")
    time.sleep(0.5)
    send_to_arduino("LED_GREEN_ON")

def reconnect_forever():
    while True:
        try:
            print("[CLIENT] ? Reconnecting to SignalR...")
            hub_connection.start()
            print("[CLIENT] ? Reconnected to SignalR")
            return
        except Exception as e:
            print(f"[CLIENT] ? Reconnect failed: {e}")
            time.sleep(5)
            
def on_close():
    print("[CLIENT] ?? Disconnected from server. Reconnecting in background...")
    threading.Thread(target=reconnect_forever, daemon=True).start()
    
def on_collector_end():
    print("[SERVER] CollectorEnd received. Stopping machine...")
    send_to_arduino("PIN25_OFF")
    global pin25_on
    pin25_on = False
    try:
        payload = {"token": TOKEN, "machineId":machine_id}
        requests.post(FINAL_COLLECTOR_SUBMIT_URL , json=payload, timeout=5)
    except Exception as e:
        print(f"? Failed to send Collection final data: {e}")

def on_receive_command(command):
    print(f"[COMMAND] Server says ? {command}")
    cmd = command[0] if isinstance(command, list) and command else command

    match cmd:
        case "CollectorEnd":
            on_collector_end()
            
        case "ManualTestDoorLock1":
            result = trigger_manual_physical_test("door_lock_1")
            publish_manual_test_status("door_lock_1", result)

        case "ManualTestDoorLock2":
            result = trigger_manual_physical_test("door_lock_2")
            publish_manual_test_status("door_lock_2", result)

        case "ManualTestDoorLock3":
            result = trigger_manual_physical_test("door_lock_3")
            publish_manual_test_status("door_lock_3", result)

        case "ManualTestPump":
            result = trigger_manual_physical_test("pump")
            publish_manual_test_status("pump", result)

        case "ManualTestValve":
            result = trigger_manual_physical_test("valve")
            publish_manual_test_status("valve", result)
        
        case _:
            print(f"[COMMAND] Unknown command received: {cmd}")

def _can_run_manual_test():
    return (
        machine_mode == "IDLE"
        and not manual_test_running
        and not getattr(globals(), 'customer_cycle_running', False)
        and not getattr(globals(), 'auto_drain_active', False)
        and not getattr(globals(), 'global_auto_drain_active', False)
        and not getattr(globals(), 'weight_read_in_progress', False)
        and not getattr(globals(), 'pin25_on', False)
    )

def _manual_test_worker(test_name):
    global manual_test_running, machine_mode

    on_cmd, off_cmd, duration = MANUAL_TESTS[test_name]
    try:
        manual_test_running = True
        machine_mode = "MANUAL_TEST"
        publish_manual_test_status(test_name, "RUNNING")

        ack_on = send_to_arduino(on_cmd) 
        if not ack_on:
            publish_manual_test_status(test_name, "FAILED")
            return

        time.sleep(duration)

        send_to_arduino(off_cmd)
        publish_manual_test_status(test_name, "DONE")
    except Exception as e:
        print(f"[MANUAL TEST] {test_name} error: {e}")
        publish_manual_test_status(test_name, "FAILED")
    finally:
        manual_test_running = False
        machine_mode = "IDLE"

def trigger_manual_physical_test(test_name):
    with manual_test_lock:
        if test_name not in MANUAL_TESTS:
            return "UNKNOWN_TEST"
        if not _can_run_manual_test():
            return "BUSY"
        threading.Thread(target=_manual_test_worker, args=(test_name,), daemon=True).start()
        return "RUNNING"

def on_run_online(args):
    if args and args[0] == machine_id:
        threading.Thread(target=run_online_diagnostics, daemon=True).start()

def on_run_physical(args):
    if args and args[0] == machine_id:
        threading.Thread(target=run_physical_diagnostics, args=(args[1],), daemon=True).start()

def on_signalr_error(message):
    print(f"[CLIENT] ? SignalR Error: {message}")
    
hub_connection.on("ReceiveCommand", on_receive_command)  
hub_connection.on("RunOnlineDiagnostics", on_run_online)
hub_connection.on("RunPhysicalDiagnostics", on_run_physical)
  
hub_connection.on_open(on_open)
hub_connection.on_close(on_close)
hub_connection.on_error(on_signalr_error)

try:
    print("[CLIENT] ? Attempting to connect to SignalR...")
    hub_connection.start()
except Exception as e:
    print(f"[CLIENT] ? Initial connection failed: {e}")
    threading.Thread(target=reconnect_forever, daemon=True).start()

print("[CLIENT] ? Starting status thread...")
threading.Thread(target=send_status_loop, daemon=True).start()

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
                    print("[INTERNET] ? Internet is back")
                    send_to_arduino("HAS_INTERNET")
                else:
                    print("[INTERNET] ? No internet")
                    send_to_arduino("NO_INTERNET")
                last_sent_internet_state = state
        except Exception as e:
            print(f"[INTERNET] Error: {e}")
        time.sleep(5)

# ------------------------------
# WEIGHT READING (ULTRASONIC ESTIMATION)
# ------------------------------
def get_weight_from_sensor(samples=3):
    global weight_read_in_progress
    weight_read_in_progress = True
    wd.kick()

    distances = []
    for _ in range(samples):
        wd.kick()
        with mega_lock:
            try:
                # 1. Safely read pending messages instead of deleting them!
                while mega_ser.in_waiting:
                    line = mega_ser.readline().decode(errors="ignore").strip()
                    if line:
                        if line.startswith("small_dist:"):
                            pass # Skip old/stale weight data
                        else:
                            mega_message_queue.append(line) # Save door statuses!

                # 2. Ask Mega for new distance
                mega_ser.write(b"get_small_dist\n")
                mega_ser.flush()
                
                start_wait = time.time()
                dist = None
                
                # 3. INCREASED TIMEOUT: The Arduino smoothing math takes ~380ms. 
                # 1.5 seconds guarantees we don't timeout and miss the data.
                while time.time() - start_wait < 1.5:
                    if mega_ser.in_waiting:
                        line = mega_ser.readline().decode(errors="ignore").strip()
                        if not line: continue
                        
                        if line.startswith("small_dist:"):
                            dist = float(line.replace("small_dist:", ""))
                            break
                        else:
                            # Save asynchronous updates (like door_closed)
                            mega_message_queue.append(line)
                            
                    time.sleep(0.02)
                
                if dist is not None and dist > 0:
                    distances.append(dist)
            except Exception as e:
                print(f"❌ Error reading ultrasonic weight: {e}")
        time.sleep(0.1)

    weight_read_in_progress = False

    if not distances:
        return 0.0

    distances.sort()
    median = distances[len(distances) // 2]
    filtered = [d for d in distances if abs(d - median) <= 3.0]
    if not filtered:
        filtered = distances
    avg_dist = sum(filtered) / len(filtered)

    if avg_dist >= SMALL_TANK_EMPTY_CM: return 0.0
    if avg_dist <= SMALL_TANK_FULL_CM: return MAX_OIL_KG

    ratio = (SMALL_TANK_EMPTY_CM - avg_dist) / (SMALL_TANK_EMPTY_CM - SMALL_TANK_FULL_CM)
    weight = ratio * MAX_OIL_KG
    return round(weight, 3)

# ------------------------------
# OVERFLOW
# ------------------------------
def create_machine_overflow(payload):
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(OVERFLOW_URL, json=payload, headers=headers, timeout=5)
        print(f"? API Response: {response.status_code} - {response.text}")
        if response.status_code == 200:
            return True
    except Exception as e:
        print(f"? API Error: {e}")
    return False

# ------------------------------
# SCHEDULED WIPER CYCLE
# ------------------------------
def wiper_monitor_loop():
    global wiper_running, machine_mode
    WIPER_INTERVAL_SEC = 4 * 60 * 60  # 4 hours in seconds

    while True:
        time.sleep(WIPER_INTERVAL_SEC)

        while machine_mode != "IDLE" or manual_test_running or getattr(globals(), 'customer_cycle_running', False):
            time.sleep(5)

        print("\n--- ? SCHEDULED WIPER CYCLE STARTED ---")
        wiper_running = True
        machine_mode = "BUSY"

        try:
            send_to_arduino("LOCK")
            time.sleep(0.5)

            send_to_arduino("START_WIPER_ROUTINE")

            print("? Wiper is running for 75 seconds...")
            
            for _ in range(15):
                wd.kick()
                time.sleep(5)

            print("? Wiper cycle complete.")
            
        except Exception as e:
            print(f"? Wiper cycle error: {e}")
            
        finally:
            wiper_running = False
            machine_mode = "IDLE"

# ------------------------------
# QR HANDLING
# ------------------------------
def wait_for_qr():
    print("? Waiting for QR scan...")
    
    if sys.platform == 'win32':
        import msvcrt
        scanned_str = ""
        while True:
            wd.kick()
            
            if manual_test_running or getattr(globals(), 'wiper_running', False):
                time.sleep(0.2)
                continue
            
            if msvcrt.kbhit():
                char = msvcrt.getwche()
                if char in ('\r', '\n'):
                    print()
                    if scanned_str:
                        return scanned_str
                else:
                    scanned_str += char
            time.sleep(0.1)
    else:
        while True:
            wd.kick()
            
            if manual_test_running or getattr(globals(), 'wiper_running', False):
                time.sleep(0.2)
                continue
            
            readable, _, _ = select.select([sys.stdin], [], [], 1)
            if readable:
                scanned = sys.stdin.readline().strip()
                if scanned:
                    return scanned
            time.sleep(0.1)

# ------------------------------
# SEND QR TO API
# ------------------------------
def send_qr_to_api(qr_token):
    global TOKEN
    headers = {'Content-Type': 'application/json'}
    
    # 1. Define the full payload including the machineId
    payload = {
        "token": qr_token, 
        "machineId": machine_id
    }
    
    try:
        print(f"📨 Sending token: {payload}")
        wd.kick()
        
        # 2. Pass 'payload' and 'headers' into the post request
        response = requests.post(QR_VALIDATE_URL, json=payload, headers=headers, timeout=5)
        print(f"🔁 API Response: {response.status_code} - {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            success = data.get("success")
            
            # 3. Robust parsing exactly as it was in LEVEL47.py
            if isinstance(success, str) and "PANEL" in success.upper():
                TOKEN = qr_token
                return success.upper()
            elif success is True or success is None:
                TOKEN = qr_token
                return (
                    data.get("panelType")
                    or data.get("role")
                    or data.get("panel")
                    or data.get("paneltype")
                )
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
        print(f"? Final Data Sent: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"? Failed to send final data: {e}")

# ------------------------------
# PUMP
# ------------------------------
def monitor_and_stop_pump():
    while True:
        weight = get_weight_from_sensor()
        if weight is not None:
            send_to_arduino(f"weight:{weight}")
            if weight <= 0.2 or pump_timeout_reached:
                if pump_timeout_reached:
                    print("? Pump timeout ? treating as weight <= 0.2 kg.")
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
        print(f"? API Error: {e}")
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
            print(f"? [PUMP TIMER] {PUMP_TIMEOUT_SEC}s exceeded.")
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
# AUTO-DRAIN
# ------------------------------
def run_global_auto_drain():
    global pump_timeout_reached, global_auto_drain_active
    if global_auto_drain_active: return

    print("?? [GLOBAL AUTO-DRAIN] Starting due to weight > 10kg")
    global_auto_drain_active = True

    try:
        send_to_arduino("excess_pump_start")
        start_pump_safety_timer("excess")

        while True:
            wd.kick()
            w = get_weight_from_sensor(samples=6)

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
        print(f"? [GLOBAL AUTO-DRAIN] Exception: {e}")

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
            
            w = get_weight_from_sensor(samples=5)
            if w is None:
                time.sleep(1)
                continue

            if w > 10.0:
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
# Customer Panel Full Cycle
# ------------------------------
def customer_cycle():
    global status_enabled, auto_drain_active, customer_cycle_running
    global alarm_monitor_active, door_monitor_thread
    customer_cycle_running = True
    
    print("🔄 Starting customer cycle...")
    start_time = time.time()

    send_to_arduino("unlock")
    payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Customer verified - Top door unlock" }
    create_machine_audit(payload)
    
    door_opened = False
    
    # Check both the Message Queue AND the Serial pipeline for door_opened
    while time.time() - start_time < 60:
        wd.kick()
        
        if mega_message_queue:
            msg = mega_message_queue.pop(0)
            if msg == "door_opened":
                door_opened = True
                break
                
        if mega_ser.in_waiting:
            msg = mega_ser.readline().decode(errors="ignore").strip()
            if msg == "door_opened":
                door_opened = True
                break
            elif msg:
                mega_message_queue.append(msg)
                
        time.sleep(0.1)

    if not door_opened:
        payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Top door not opened - lock engaged." }
        create_machine_audit(payload)
        send_to_arduino("LOCK")
        send_final_data(0.0)
        customer_cycle_running = False
        return

    # ---------------------------------------------------------
    # POURING PHASE & INACTIVITY TIMER
    # ---------------------------------------------------------
    last_weight = 0.0
    stable_time_start = time.time()
    motor_close_triggered = False

    while True:
        wd.kick()
        weight_live = get_weight_from_sensor()
        
        if weight_live is not None:
            print(f"⚖️ Live weight while pouring: {weight_live} kg")
            
            # Emergency Auto-drain logic (Over 10kg)
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
                    wdrain = get_weight_from_sensor()
                    if wdrain is not None:
                        send_to_arduino(f"weight:{wdrain}")
                        if wdrain <= 0.25:
                            send_to_arduino("excess_pump_stop")
                            stop_pump_safety_timer()
                            payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Auto-drain complete"}
                            create_machine_audit(payload)
                            break
                    time.sleep(1)

                send_final_data(10.00)
                auto_drain_active = False
                
                status_enabled = True
                customer_cycle_running = False
                alarm_monitor_active = False
                return

            # Motorized Auto-Close Logic
            if not motor_close_triggered:
                if abs(weight_live - last_weight) > 0.05: 
                    stable_time_start = time.time() 
                    last_weight = weight_live
                elif (time.time() - stable_time_start > 15 and weight_live >= MIN_POUR_WEIGHT) or (time.time() - start_time > 120):
                    print("Pouring finished or timed out. Closing motorized door...")
                    send_to_arduino("AUTO_DOOR_CLOSE") 
                    motor_close_triggered = True

        # ---------------------------------------------------------
        # LISTEN FOR ARDUINO "DOOR_CLOSED" CONFIRMATION
        # ---------------------------------------------------------
        msg = None
        # Check queue first!
        if mega_message_queue:
            msg = mega_message_queue.pop(0)
        elif mega_ser.in_waiting:
            msg = mega_ser.readline().decode(errors="ignore").strip()

        if msg:
            if msg == "door_closed" or msg == "doors_locked":
                if auto_drain_active:
                    send_to_arduino("pump_now")
                    time.sleep(0.2)
                
                payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Machine door closed." }
                create_machine_audit(payload)
                
                w = get_weight_from_sensor()
                if w is None or w < 0 : w = 0
                
                print(f"📊 Final Estimated Amount: {w} kg")
                
                # Check if poured less than minimum
                if w < MIN_POUR_WEIGHT:
                    payload = {"qrToken": TOKEN, "machineId": machine_id, "action": f"No oil poured ({w} kg) — Pump skipped"}
                    create_machine_audit(payload)
                    send_final_data(0.0)
                    send_to_arduino("LOCK")
                    customer_cycle_running = False
                    alarm_monitor_active = False
                    return

                #------------------------------
                # TURBIDITY CHECK + QUALITY LOG
                # ------------------------------
                print("🔍 Checking oil quality (Turbidity)...")
                turbidity_val = get_turbidity_from_arduino()

                if turbidity_val is None:
                    print("⚠️ No turbidity reading received. Marking as UNKNOWN.")
                    turbidity_val = -1
                    oil_quality = "UNKNOWN"
                else:
                    oil_quality = classify_turbidity(turbidity_val)

                print(f"🧪 Turbidity Raw Value: {turbidity_val}")
                print(f"🧪 Oil Quality: {oil_quality}")

                payload = {"qrToken": TOKEN, "machineId": machine_id, "action": f"Oil quality classified as {oil_quality}"}
                create_machine_audit(payload)

                log_telemetry_to_dashboard("Customer Pour Completed", w, turbidity_val, oil_quality)

                # ------------------------------
                # NORMAL PUMP START
                # ------------------------------
                send_final_data(w)
                send_to_arduino("pump_now")
                start_pump_safety_timer("normal")

                print("🔄 Monitoring pump weight until empty...")
                while True:
                    wd.kick()
                    weight = get_weight_from_sensor()
                    if weight is not None:
                        send_to_arduino(f"weight:{weight}")
                        if weight <= 0.2 or pump_timeout_reached:
                            payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Machine stopped pumping."}
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
    global pin25_on, status_enabled, auto_off_timer

    if not pin25_on:
        send_to_arduino("PIN25_ON")
        payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Collector verified - solenoid valve activated"}
        create_machine_audit(payload)
        pin25_on = True

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
        payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Collector verified - solenoid valve deactivated"}
        create_machine_audit(payload)
        pin25_on = False
        try: auto_off_timer.cancel()
        except: pass


# Technician Panel Cycle 
# ------------------------------
def technician_cycle():
    global status_enabled  
    send_to_arduino("unlock_tech")    
    payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Technician verified - tech door unlocked." }
    create_machine_audit(payload)

    start = time.time() 
    while time.time() - start < 20:
        wd.kick()
        time.sleep(0.2)

    send_to_arduino("LOCK")
    payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Auto-lock timer expired. Tech door locked." }
    create_machine_audit(payload)

# ------------------------------
# Main Program
# ------------------------------
def main():
    global pin25_on, wd, TOKEN, machine_mode 
    
    def pre_restart():
        try: send_to_arduino("LOCK")
        except: pass

    wd = Watchdog(timeout=120, pre_restart_callback=pre_restart)
    threading.Thread(target=internet_monitor_loop, daemon=True).start()
    threading.Thread(target=global_auto_drain_monitor, daemon=True).start()
    threading.Thread(target=wiper_monitor_loop, daemon=True).start()

    run_online_diagnostics()

    while True:
        wd.kick()

        if manual_test_running:
            time.sleep(0.2)
            continue

        machine_mode = "IDLE"
        TOKEN = wait_for_qr()
        machine_mode = "BUSY"

        try:
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
                    payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Customer cycle blocked - issue detected"}
                    create_machine_audit(payload)
                    send_to_arduino("LOCK")
                    continue
                else:
                    payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Customer QR scanned"}
                    create_machine_audit(payload)
                    customer_cycle()

            elif panel_type == "COLLECTORPANEL":
                payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Collector QR scanned"}
                create_machine_audit(payload)
                collector_cycle()

            elif panel_type == "TECHNICIANPANEL":
                payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Technician QR scanned"}
                create_machine_audit(payload)
                technician_cycle()

            else:
                send_to_arduino("LOCK")

            time.sleep(2)

        finally:
            machine_mode = "IDLE"

# ------------------------------
# Entry Point
# ------------------------------
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n? Program stopped by user.")
        try:
            mega_ser.close()
        except:
            pass
            



def classify_turbidity(raw_value):
    """Convert raw turbidity into a quality label."""
    if raw_value is None or raw_value < 0:
        return "UNKNOWN"

    if raw_value <= TURBIDITY_GOOD_MAX:
        return "GOOD"
    elif raw_value <= TURBIDITY_POOR_MAX:
        return "POOR"
    else:
        return "WATER_CONTAMINATED"

# ------------------------------
# TELEMETRY LOGGING
# ------------------------------

def log_telemetry_to_dashboard(action_name, weight, turbidity_raw, oil_quality):
    """Send weight + oil quality info to dashboard."""
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
        threading.Thread(
            target=requests.post,
            args=(TELEMETRY_URL,),
            kwargs={"json": payload, "timeout": 5},
            daemon=True
        ).start()
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
hub_url = f"https://gallows-qualm-dazzler.ngrok-free.dev/machineHub?machineId={machine_id}"
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

    # Ensure command is parsed correctly
    cmd = command[0] if isinstance(command, list) and command else command

    match cmd:
        case "CollectorEnd":
            on_collector_end()
            
        # --- NEW MANUAL TEST COMMANDS ---
        case "ManualTestDoorLock1":
            result = trigger_manual_physical_test("door_lock_1")
            publish_manual_test_status("door_lock_1", result)

        case "ManualTestDoorLock2":
            result = trigger_manual_physical_test("door_lock_2")
            publish_manual_test_status("door_lock_2", result)

        case "ManualTestDoorLock3":
            result = trigger_manual_physical_test("door_lock_3")
            publish_manual_test_status("door_lock_3", result)

        case "ManualTestPump":
            result = trigger_manual_physical_test("pump")
            publish_manual_test_status("pump", result)

        case "ManualTestValve":
            result = trigger_manual_physical_test("valve")
            publish_manual_test_status("valve", result)
        # ---------------------------------
        
        case _:
            print(f"[COMMAND] Unknown command received: {cmd}")

def _can_run_manual_test():
    # Make sure your other globals are properly referenced here!
    return (
        machine_mode == "IDLE"
        and not manual_test_running
        and not getattr(globals(), 'customer_cycle_running', False)
        and not getattr(globals(), 'auto_drain_active', False)
        and not getattr(globals(), 'global_auto_drain_active', False)
        and not getattr(globals(), 'weight_read_in_progress', False)
        and not getattr(globals(), 'pin25_on', False)
    )

def _manual_test_worker(test_name):
    global manual_test_running, machine_mode

    on_cmd, off_cmd, duration = MANUAL_TESTS[test_name]
    try:
        manual_test_running = True
        machine_mode = "MANUAL_TEST"
        publish_manual_test_status(test_name, "RUNNING")

        ack_on = send_to_arduino(on_cmd) # Ensure your send_to_arduino function supports reading acks!
        if not ack_on:
            publish_manual_test_status(test_name, "FAILED")
            return

        time.sleep(duration)

        send_to_arduino(off_cmd)
        publish_manual_test_status(test_name, "DONE")
    except Exception as e:
        print(f"[MANUAL TEST] {test_name} error: {e}")
        publish_manual_test_status(test_name, "FAILED")
    finally:
        manual_test_running = False
        machine_mode = "IDLE"

def trigger_manual_physical_test(test_name):
    with manual_test_lock:
        if test_name not in MANUAL_TESTS:
            return "UNKNOWN_TEST"
        if not _can_run_manual_test():
            return "BUSY"
        threading.Thread(target=_manual_test_worker, args=(test_name,), daemon=True).start()
        return "RUNNING"

# NEW DIAGNOSTIC SIGNALR HOOKS
def on_run_online(args):
    if args and args[0] == machine_id:
        threading.Thread(target=run_online_diagnostics, args=(tared,), daemon=True).start()

def on_run_physical(args):
    if args and args[0] == machine_id:
        threading.Thread(target=run_physical_diagnostics, args=(args[1],), daemon=True).start()

def on_signalr_error(message):
    print(f"[CLIENT] ⚠️ SignalR Error: {message}")
    
hub_connection.on("ReceiveCommand", on_receive_command)  
hub_connection.on("RunOnlineDiagnostics", on_run_online)
hub_connection.on("RunPhysicalDiagnostics", on_run_physical)
  
hub_connection.on_open(on_open)
hub_connection.on_close(on_close)
hub_connection.on_error(on_signalr_error)

try:
    print("[CLIENT] 🔄 Attempting to connect to SignalR...")
    hub_connection.start()
except Exception as e:
    print(f"[CLIENT] ❌ Initial connection failed: {e}")
    threading.Thread(target=reconnect_forever, daemon=True).start()

print("[CLIENT] 🔄 Starting status thread...")
threading.Thread(target=send_status_loop, daemon=True).start()

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
# WEIGHT READING (ULTRASONIC ESTIMATION)
# ------------------------------
def get_weight_from_sensor(samples=3):
    global weight_read_in_progress
    weight_read_in_progress = True
    wd.kick()

    distances = []
    for _ in range(samples):
        wd.kick()
        with mega_lock:
            try:
                # Ask Mega for distance
                mega_ser.write(b"get_small_dist\n")
                mega_ser.flush()
                
                start_wait = time.time()
                dist = None
                while time.time() - start_wait < 0.4:
                    if mega_ser.in_waiting:
                        line = mega_ser.readline().decode(errors="ignore").strip()
                        if not line: continue
                        
                        if line.startswith("small_dist:"):
                            dist = float(line.replace("small_dist:", ""))
                            break
                        else:
                            # CRITICAL: Save door statuses or other logs so they aren't lost
                            mega_message_queue.append(line)
                            
                    time.sleep(0.02)
                
                if dist is not None and dist > 0:
                    distances.append(dist)
            except Exception as e:
                print(f"❌ Error reading ultrasonic weight: {e}")
        time.sleep(0.1)

    weight_read_in_progress = False

    if not distances:
        return 0.0

    # Sort and filter outliers
    distances.sort()
    median = distances[len(distances) // 2]
    filtered = [d for d in distances if abs(d - median) <= 3.0]
    if not filtered:
        filtered = distances
    avg_dist = sum(filtered) / len(filtered)

    # Convert distance to weight
    if avg_dist >= SMALL_TANK_EMPTY_CM: return 0.0
    if avg_dist <= SMALL_TANK_FULL_CM: return MAX_OIL_KG

    ratio = (SMALL_TANK_EMPTY_CM - avg_dist) / (SMALL_TANK_EMPTY_CM - SMALL_TANK_FULL_CM)
    weight = ratio * MAX_OIL_KG
    return round(weight, 3)

# ------------------------------
# OVERFLOW
# ------------------------------
def create_machine_overflow(payload):
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(OVERFLOW_URL, json=payload, headers=headers, timeout=5)
        print(f"🔍 API Response: {response.status_code} - {response.text}")
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
        import msvcrt
        scanned_str = ""
        while True:
            wd.kick()
            
            # --- ADDED: Ignore physical QR scans while technician is running a motor test ---
            if manual_test_running:
                time.sleep(0.2)
                continue
            # ------------------------------------------------------------------------------
            
            if msvcrt.kbhit():
                char = msvcrt.getwche()
                if char in ('\r', '\n'):
                    print()
                    if scanned_str:
                        return scanned_str
                else:
                    scanned_str += char
            time.sleep(0.1)
    else:
        while True:
            wd.kick()
            
            # --- ADDED: Ignore physical QR scans while technician is running a motor test ---
            if manual_test_running:
                time.sleep(0.2)
                continue
            # ------------------------------------------------------------------------------
            
            readable, _, _ = select.select([sys.stdin], [], [], 1)
            if readable:
                scanned = sys.stdin.readline().strip()
                if scanned:
                    return scanned
            time.sleep(0.1)

# ------------------------------
# SEND QR TO API
# ------------------------------
def send_qr_to_api(qr_token):
    global TOKEN
    headers = {'Content-Type': 'application/json'}
    payload = {
        "token": qr_token, 
        "machineId": machine_id
    }
    
    try:
        print(f"📨 Sending token: {payload}")
        wd.kick() # Kick watchdog right before network call
        
        # Added timeout=5 from the main script to prevent hanging on bad Wi-Fi
        response = requests.post(QR_VALIDATE_URL, json=payload, headers=headers, timeout=5)
        print(f"🔁 API Response: {response.status_code} - {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            success = data.get("success")
            panel_type = None
            
            # Robust parsing combined from your working version
            if isinstance(success, str) and "PANEL" in success.upper():
                panel_type = success.upper()
            elif success is True or success is None: 
                panel_type = (
                    data.get("panelType")
                    or data.get("role")
                    or data.get("panel")
                    or data.get("paneltype")
                )

            if panel_type:
                TOKEN = qr_token
                print(f"✅ QR Validated. Panel: {panel_type}")
                return panel_type
            else:
                print(f"❌ QR Validated but panel type missing in response: {data}")
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
        weight = get_weight_from_sensor()
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
            print(f"⏳ [PUMP TIMER] {PUMP_TIMEOUT_SEC}s exceeded.")
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
# AUTO-DRAIN
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
            w = get_weight_from_sensor(samples=6)

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
            
            w = get_weight_from_sensor(samples=5)
            if w is None:
                time.sleep(1)
                continue

            if w > 10.0:
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
# Follow-up Cycle
# ------------------------------           
def followup_cycle():
    global pump_timeout_reached, status_enabled
    global alarm_monitor_active, door_monitor_thread

    alarm_monitor_active = False
    send_to_arduino("unlock")
    time.sleep(0.2)

    while True:
        wd.kick()
        w_live = get_weight_from_sensor(samples=5)

        if w_live > 10.0:
            print("🚨 [FOLLOW-UP] Weight > 10kg while waiting — starting auto-drain")
            alarm_monitor_active = True
            if door_monitor_thread is None or not door_monitor_thread.is_alive():
                door_monitor_thread = threading.Thread(target=door_alarm_monitor_active, daemon=True)
                door_monitor_thread.start()

            send_to_arduino("excess_pump_start")
            start_pump_safety_timer("excess")

            while True:
                wd.kick()
                wdrain = get_weight_from_sensor(samples=5)
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

    w_final = get_weight_from_sensor()
    send_final_data(w_final)

    if w_final > 10.0:
        alarm_monitor_active = True
        if door_monitor_thread is None or not door_monitor_thread.is_alive():
            door_monitor_thread = threading.Thread(target=door_alarm_monitor_active, daemon=True)
            door_monitor_thread.start()
            
        send_to_arduino("excess_pump_start")
        start_pump_safety_timer("excess")

        while True:
            wd.kick()
            w2 = get_weight_from_sensor(samples=5)
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
            w2 = get_weight_from_sensor(samples=5)
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
# Customer Panel Full Cycle
# ------------------------------
def customer_cycle():
    global status_enabled, auto_drain_active, customer_cycle_running
    global alarm_monitor_active, door_monitor_thread
    customer_cycle_running = True
    
    print("🔄 Starting customer cycle...")
    start_time = time.time()

    send_to_arduino("unlock")
    payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Customer verified - Top door unlock" }
    create_machine_audit(payload)
    
    door_opened = False
    
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

    # ---------------------------------------------------------
    # POURING PHASE & INACTIVITY TIMER
    # ---------------------------------------------------------
    last_weight = 0.0
    stable_time_start = time.time()
    motor_close_triggered = False

    while True:
        wd.kick()
        weight_live = get_weight_from_sensor()
        
        if weight_live is not None:
            print(f"⚖️ Live weight while pouring: {weight_live} kg")
            
            # Emergency Auto-drain logic (Over 10kg)
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
                    wdrain = get_weight_from_sensor()
                    if wdrain is not None:
                        send_to_arduino(f"weight:{wdrain}")
                        if wdrain <= 0.25:
                            send_to_arduino("excess_pump_stop")
                            stop_pump_safety_timer()
                            payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Auto-drain complete"}
                            create_machine_audit(payload)
                            break
                    time.sleep(1)

                send_final_data(10.00)
                auto_drain_active = False
                
                status_enabled = True
                customer_cycle_running = False
                alarm_monitor_active = False
                return

            # Motorized Auto-Close Logic
            if not motor_close_triggered:
                if abs(weight_live - last_weight) > 0.05: 
                    stable_time_start = time.time() 
                    last_weight = weight_live
                elif (time.time() - stable_time_start > 15 and weight_live >= MIN_POUR_WEIGHT) or (time.time() - start_time > 120):
                    print("Pouring finished or timed out. Closing motorized door...")
                    send_to_arduino("AUTO_DOOR_CLOSE") 
                    motor_close_triggered = True

        # ---------------------------------------------------------
        # LISTEN FOR ARDUINO "DOOR_CLOSED" CONFIRMATION
        # ---------------------------------------------------------
        msg = None
        # Check queue first!
        if mega_message_queue:
            msg = mega_message_queue.pop(0)
        elif mega_ser.in_waiting:
            msg = mega_ser.readline().decode(errors="ignore").strip()

        if msg:
            if msg == "door_closed" or msg == "doors_locked":
                if auto_drain_active:
                    send_to_arduino("pump_now")
                    time.sleep(0.2)
                
                payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Machine door closed." }
                create_machine_audit(payload)
                
                w = get_weight_from_sensor()
                if w is None or w < 0 : w = 0
                
                print(f"📊 Final Estimated Amount: {w} kg")
                
                # Check if poured less than minimum
                if w < MIN_POUR_WEIGHT:
                    payload = {"qrToken": TOKEN, "machineId": machine_id, "action": f"No oil poured ({w} kg) — Pump skipped"}
                    create_machine_audit(payload)
                    send_final_data(0.0)
                    send_to_arduino("LOCK")
                    customer_cycle_running = False
                    alarm_monitor_active = False
                    return

                #------------------------------
                # TURBIDITY CHECK + QUALITY LOG
                # ------------------------------
                print("🔍 Checking oil quality (Turbidity)...")
                turbidity_val = get_turbidity_from_arduino()

                if turbidity_val is None:
                    print("⚠️ No turbidity reading received. Marking as UNKNOWN.")
                    turbidity_val = -1
                    oil_quality = "UNKNOWN"
                else:
                    oil_quality = classify_turbidity(turbidity_val)

                print(f"🧪 Turbidity Raw Value: {turbidity_val}")
                print(f"🧪 Oil Quality: {oil_quality}")

                payload = {"qrToken": TOKEN, "machineId": machine_id, "action": f"Oil quality classified as {oil_quality}"}
                create_machine_audit(payload)

                log_telemetry_to_dashboard("Customer Pour Completed", w, turbidity_val, oil_quality)

                # ------------------------------
                # NORMAL PUMP START
                # ------------------------------
                send_final_data(w)
                send_to_arduino("pump_now")
                start_pump_safety_timer("normal")

                print("🔄 Monitoring pump weight until empty...")
                while True:
                    wd.kick()
                    weight = get_weight_from_sensor()
                    if weight is not None:
                        send_to_arduino(f"weight:{weight}")
                        if weight <= 0.2 or pump_timeout_reached:
                            payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Machine stopped pumping."}
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
# Main Program
# ------------------------------
def main():
    # ADDED machine_mode here so Python updates the global state
    global pin25_on, wd, TOKEN, machine_mode 
    
    def pre_restart():
        try: send_to_arduino("LOCK")
        except: pass

    wd = Watchdog(timeout=120, pre_restart_callback=pre_restart)
    threading.Thread(target=internet_monitor_loop, daemon=True).start()
    threading.Thread(target=global_auto_drain_monitor, daemon=True).start()

    # Automatically run the new online diagnostics routine at program start
    run_online_diagnostics(tared)

    while True:
        wd.kick()

        # --- ADDED: Block QR scanning when running physical tests ---
        if manual_test_running:
            time.sleep(0.2)
            continue
        # ------------------------------------------------------------

        machine_mode = "IDLE"
        TOKEN = wait_for_qr()
        machine_mode = "BUSY"

        try:
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
                    payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Customer cycle blocked - issue detected"}
                    create_machine_audit(payload)
                    send_to_arduino("LOCK")
                    continue
                else:
                    payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Customer QR scanned"}
                    create_machine_audit(payload)
                    customer_cycle()

            elif panel_type == "COLLECTORPANEL":
                payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Collector QR scanned"}
                create_machine_audit(payload)
                collector_cycle()

            elif panel_type == "TECHNICIANPANEL":
                payload = {"qrToken": TOKEN, "machineId": machine_id, "action": "Technician QR scanned"}
                create_machine_audit(payload)
                technician_cycle()

            else:
                send_to_arduino("LOCK")

            time.sleep(2)

        finally:
            # Ensure the machine is always marked as IDLE when a cycle finishes or fails
            machine_mode = "IDLE"

if __name__ == "__main__":
    main()

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