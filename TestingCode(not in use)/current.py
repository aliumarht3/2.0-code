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
                print("[WATCHDOG] Main logic stuck. Restarting Pythonâ¦")

                try:
                    if self.pre_restart_callback:
                        self.pre_restart_callback()
                except:
                    pass

                python = sys.executable
                os.execv(python, [python] + sys.argv)

            time.sleep(0.5)

# ------------------------------
# SERIAL CONFIGURATION
# ------------------------------
UNO_PORT = '/dev/ttyACM1'
MEGA_PORT = '/dev/ttyACM0'
BAUD_RATE = 9600

mega_ser = serial.Serial(MEGA_PORT, BAUD_RATE, timeout=1)
uno_ser = serial.Serial(UNO_PORT, BAUD_RATE, timeout=1, dsrdtr=False)

uno_lock = threading.Lock()

# Let UNO boot and clear old serial data
time.sleep(2.5)
uno_ser.flushInput()
mega_ser.flushInput()

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
    print("â ï¸ [STARTUP] No TARED reply â continuing anyway.")
with uno_lock:
    uno_ser.reset_input_buffer()

# ------------------------------
# API ENDPOINT
# ------------------------------
QR_VALIDATE_URL = "https://services.gohijau.org/api/Qr/verify"
FINAL_SUBMIT_URL = "https://services.gohijau.org/api/Qr/complete/pouring"
AUDIT_CREATE_URL = "https://services.gohijau.org/api/audit/machine/create"
FINAL_COLLECTOR_SUBMIT_URL = "https://services.gohijau.org/api/Qr/complete/collection"
OVERFLOW_URL = "https://services.gohijau.org/api/Qr/overflow"

TOKEN = None
pin25_on = False  # Track pin 25 state
machine_id = "GO-000001"
status_enabled = True
auto_drain_active = False
# New global control flags for background auto-drain
customer_cycle_running = False
global_auto_drain_active = False
weight_read_in_progress = False
PUMP_TIMEOUT_SEC = 120 
pump_timer = None
pump_mode = None    # "normal" or "excess"
pump_timer_lock = threading.Lock()
# Door alarm monitor controls (only active while weight > 5kg)
alarm_monitor_active = False
door_monitor_thread = None
pump_timeout_reached = False



# ------------------------------
# BACKGROUND: SEND STATUS
# ------------------------------
def send_status_loop():
    global status_enabled
    while True:
        try:
            if status_enabled:
                hub_connection.send("SendStatus", ["GO-000001", "Active"])
                
        except Exception as e:
            print(f"[CLIENT] â ï¸ Failed to send status: {e}")
        time.sleep(5)

# ------------------------------
# SignalR Setup
# ------------------------------
hub_url = f"https://services.gohijau.org/machineHub?machineId={machine_id}"
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
    print("[CLIENT] â Connected to server")
    send_to_arduino("PYTHON_READY")     # ð§  Tell Arduino the program is running
    time.sleep(0.5)
    send_to_arduino("LED_GREEN_ON")     # ð¢ Turn on green LED (ready to scan)

def reconnect_forever():
    while True:
        try:
            print("[CLIENT] ð Reconnecting to SignalR...")
            hub_connection.start()
            print("[CLIENT] â Reconnected to SignalR")
            return
        except Exception as e:
            print(f"[CLIENT] â Reconnect failed: {e}")
            time.sleep(5)
            
def on_close():
    print("[CLIENT] â Disconnected from server")
    reconnect_forever()

    
def on_collector_end():
    print("[SERVER] CollectorEnd received. Stopping machine...")
    send_to_arduino("PIN25_OFF")
    pin25_on = False
    try:
        payload = {"token": TOKEN, "machineId":machine_id}
        r = requests.post(FINAL_COLLECTOR_SUBMIT_URL , json=payload)
    except Exception as e:
        print(f"â Failed to send Collection final data: {e}")

def on_receive_command(command):
    print(f"[COMMAND] Server says â {command}")
    match command[0]:
        case "CollectorEnd":
            on_collector_end()
    
hub_connection.on("ReceiveCommand", on_receive_command)    
hub_connection.on_open(on_open)
hub_connection.on_close(on_close)
hub_connection.start()
print("[CLIENT] ð§© Starting status thread...")
threading.Thread(target=send_status_loop, daemon=True).start()



# ------------------------------
# ARDUINO COMMUNICATION
# ------------------------------
def send_to_arduino(command):
    mega_ser.write((command + '\n').encode())
    time.sleep(0.1)
    return mega_ser.readline().decode().strip()

# ------------------------------
# WEIGHT READING
# ------------------------------
def get_weight_from_uno(samples=10):
    """
    Reads stable weight from UNO with noise filtering and median-based outlier removal.
    """
    global weight_read_in_progress
    weight_read_in_progress = True

    wd.kick()
    with uno_lock:
        uno_ser.reset_input_buffer()
        
    print("â³ Waiting for UNO to stabilize...")
    time.sleep(1.5)

    weights = []
    for _ in range(samples):
        wd.kick()
        try:
            # THREAD-SAFE READ from UNO
            with uno_lock:
                raw = uno_ser.readline()

            # if nothing was returned, skip this sample (avoid crashing)
            if not raw:
                print("â ï¸ UNO returned no data")
                continue

            line = raw.decode(errors='ignore').strip()
            if line:
                weight = float(line)
                weights.append(weight)
                print(f"UNO raw: {weight}")

        except Exception as e:
            print(f"â ï¸ Bad data: {e}")
        time.sleep(0.15)

    if not weights:
        print("â ï¸ No valid data from UNO.")
        weight_read_in_progress = False
        return 0.0

    # ð§® Step 1: Sort readings and find median
    weights.sort()
    median = weights[len(weights) // 2]

    # ð§¹ Step 2: Filter out outliers more than Â±0.1 kg from median
    filtered = [w for w in weights if abs(w - median) <= 0.05]
    if not filtered:
        print("â ï¸ All readings were outliers â using unfiltered data.")
        filtered = weights

    # ð§¾ Step 3: Take average of filtered data
    avg = round(sum(filtered) / len(filtered), 3)

    print(f"ð¦ Filtered weights: {filtered}")
    print(f"ð Final stable average: {avg} kg (median {median})")
    weight_read_in_progress = False
    return avg
# ------------------------------
# OVERFLOW
# ------------------------------
def create_machine_overflow(payload):
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(OVERFLOW_URL, json=payload, headers=headers)
        print(f"ð API Response: {response.status_code} - {response.text}")

        if response.status_code == 200:
            data = response.json()
            return True
        else:
            print("â Unexpected response code from API.")

    except Exception as e:
        print(f"â API Error: {e}")

    return False
# ------------------------------
# QR HANDLING
# ------------------------------
def wait_for_qr():
    print("ð· Waiting for QR scan...")

    while True:
        # Keep watchdog alive even when idle
        wd.kick()

        # Non-blocking keyboard check (1 second timeout)
        readable, _, _ = select.select([sys.stdin], [], [], 1)

        if readable:
            scanned = sys.stdin.readline().strip()
            if scanned:
                payload = {
                    "qrToken": TOKEN,
                    "machineId": machine_id,
                    "action": "QR Scanned."
                }
                create_machine_audit(payload)
                return scanned

        # Small sleep to reduce CPU usage
        time.sleep(0.1)

def send_qr_to_api(token):
    global TOKEN
    headers = {'Content-Type': 'application/json'}
    payload = {"token": token, "machineId":machine_id}
    try:
        print(f"ð¨ Sending token: {payload}")
        wd.kick()
        r = requests.post(QR_VALIDATE_URL, json=payload, headers=headers)
        print(f"ð API Response: {r.status_code} - {r.text}")
        if r.status_code == 200:
            data = r.json()
            success = data.get("success")
            if isinstance(success, str) and "PANEL" in success.upper():
                TOKEN = token
                return success.upper()
            elif success is True:
                TOKEN = token
                return (
                    data.get("panelType")
                    or data.get("role")
                    or data.get("panel")
                    or data.get("paneltype")
                )
    except Exception as e:
        print(f"â API Error: {e}")
    return None

# ------------------------------
# FINAL DATA SUBMIT
# ------------------------------
def send_final_data(oil_amount):
    payload = {"token": TOKEN, "oilAmount": round(oil_amount, 2), "machineId":machine_id}
    try:
        r = requests.post(FINAL_SUBMIT_URL, json=payload)
        print(f"â Final Data Sent: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"â Failed to send final data: {e}")

# ------------------------------
# PUMP
# ------------------------------
def monitor_and_stop_pump():
    """Continuously send weight data to Arduino until threshold met."""
    while True:
        weight = get_weight_from_uno()
        if weight is not None:
            send_to_arduino(f"weight:{weight}")
            print(f"âï¸ Sending weight: {weight} kg")
            if weight <= 0.2 or pump_timeout_reached:
                if pump_timeout_reached:
                    print("ð Pump timeout â treating as weight <= 0.2 kg.")

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
        response = requests.post(AUDIT_CREATE_URL, json=payload, headers=headers)
        print(f"ð API Response: {response.status_code} - {response.text}")

        if response.status_code == 200:
            data = response.json()
            return True
        else:
            print("â Unexpected response code from API.")

    except Exception as e:
        print(f"â API Error: {e}")

    return False

# ------------------------------
# SAFETY FEATURE
# ------------------------------
def start_pump_safety_timer(mode: str):
    global pump_timer, pump_mode, pump_timeout_reached
    with pump_timer_lock:
        pump_mode = mode
        pump_timeout_reached = False   # reset at pump start

        try:
            if pump_timer is not None:
                pump_timer.cancel()
        except:
            pass

        def timeout():
            global pump_timeout_reached, pump_mode
            pump_timeout_reached = True

            print(f"â° [PUMP TIMER] {PUMP_TIMEOUT_SEC}s exceeded â treating as empty (<0.2kg).")

            try:
                if pump_mode == "normal":
                    send_to_arduino("LOCK")
                elif pump_mode == "excess":
                    send_to_arduino("excess_pump_stop")
                    time.sleep(0.2)
                    send_to_arduino("LOCK")
            except Exception as e:
                print(f"â ï¸ [PUMP TIMER] Failed to stop pump: {e}")

        pump_timer = threading.Timer(PUMP_TIMEOUT_SEC, timeout)
        pump_timer.daemon = True
        pump_timer.start()
        print(f"[PUMP TIMER] Started safety timer ({PUMP_TIMEOUT_SEC}s, mode={mode}).")


def stop_pump_safety_timer():
    """Stop and clear the pump safety timer."""
    global pump_timer, pump_mode
    with pump_timer_lock:
        try:
            if pump_timer is not None:
                pump_timer.cancel()
                print("[PUMP TIMER] Stopped / cancelled.")
        except:
            pass
        pump_timer = None
        pump_mode = None
# ------------------------------
# AUTO-DRAIN
# ------------------------------
def run_global_auto_drain():
    """
    Runs the global auto-drain procedure:
    - starts pump via excess_pump_start
    - monitors weight until <= 0.25 kg
    - stops pump via excess_pump_stop and locks doors
    - does NOT call the API (Option B)
    """
    global pump_timeout_reached
    global global_auto_drain_active
    if global_auto_drain_active:
        return

    print("ð¨ [GLOBAL AUTO-DRAIN] Starting auto-drain due to weight > 5kg")
    global_auto_drain_active = True

    try:
        send_to_arduino("excess_pump_start")
        print("ð [GLOBAL AUTO-DRAIN] Sent excess_pump_start to Arduino")
        start_pump_safety_timer("excess")

        while True:
            wd.kick()
            w = get_weight_from_uno(samples=6)
            print(f"âï¸ [GLOBAL AUTO-DRAIN] Current weight: {w} kg")

            if w <= 0.25 or pump_timeout_reached:
                if pump_timeout_reached:
                    print("ð Pump timeout â treating as weight <= 0.25 kg.")
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
        print(f"â [GLOBAL AUTO-DRAIN] Exception: {e}")

    finally:
        global_auto_drain_active = False
        stop_pump_safety_timer()
        print("ð [GLOBAL AUTO-DRAIN] Finished and returned to idle")

# ------------------------------
# GLOBAL MONITOR WEIGHT
# ------------------------------
def global_auto_drain_monitor():
    """
    Background thread: read weight periodically and trigger global auto-drain
    when weight > 5.0 kg, but skip when a customer cycle is running or other flags are set.
    """
    print("ð°ï¸ [Monitor] Global auto-drain monitor thread started.")

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

            if w > 5.0:
                threading.Thread(target=run_global_auto_drain, daemon=True).start()

            time.sleep(1)

        except Exception as e:
            print(f"â [Monitor] Exception in global monitor: {e}")
            time.sleep(1)
 
# ------------------------------
# ALARM
# ------------------------------
def door_alarm_monitor_active():
    """
    Active-only door monitor:
    - runs while alarm_monitor_active == True
    - queries Mega for door state repeatedly
    - if 'door_closed' found -> send STOP_ALARM once and stop the monitor
    """
    global alarm_monitor_active
    print("[DoorMonitor] Started (active while weight > 5kg).")
    try:
        while alarm_monitor_active:
            wd.kick()
            try:
                mega_ser.reset_input_buffer()
                mega_ser.write(b"get_door_state\n")
                time.sleep(0.12)  # short wait for Mega to reply

                if mega_ser.in_waiting:
                    msg = mega_ser.readline().decode().strip()
                    print(f"[DoorMonitor] Mega reply: {msg}")

                    if msg == "door_closed":
                        print("ð Door closed detected â sending STOP_ALARM.")
                        try:
                            uno_ser.write(b"STOP_ALARM\n")
                            time.sleep(0.1) 
                        except Exception as e:
                            print(f"[DoorMonitor] Failed to send STOP_ALARM: {e}")
                        # stop monitor after successfully sending STOP_ALARM
                        alarm_monitor_active = False
                        break

            except Exception as e:
                print(f"[DoorMonitor] Error reading Mega: {e}")

            time.sleep(0.15)

    finally:
        alarm_monitor_active = False
        print("[DoorMonitor] Stopped.")

# ------------------------------
# Follow-up Cycle 
# ------------------------------           
def followup_cycle():
    """
    Follow-up cycle after the first auto-drain.
    Handles:
    - Waiting for door close
    - Auto-drain even while waiting if weight > 5kg
    - Final weight send to API
    - Pump / auto-drain until <=0.25kg
    """
    global pump_timeout_reached
    global status_enabled
    global alarm_monitor_active, door_monitor_thread

    print("ð [FOLLOW-UP] Starting new cycle after auto-drain...")
      # pause status pings
    alarm_monitor_active = False

    # 1) Unlock door so customer can close normally
    print("ð [FOLLOW-UP] Unlocking door for customer to close...")
    send_to_arduino("unlock")
    time.sleep(0.2)

    # 2) WAIT FOR DOOR CLOSED (with auto-drain while waiting)
    print("â³ [FOLLOW-UP] Waiting for door closed...")

    while True:
        wd.kick()

        # ---- Live weight monitoring while waiting ----
        w_live = get_weight_from_uno(samples=5)
        print(f"âï¸ [FOLLOW-UP] Live weight while waiting: {w_live} kg")

        # ð¨ If weight exceeds 5kg WHILE DOOR STILL OPEN â Auto-drain immediately
        if w_live > 5.0:
            print("ð¨ [FOLLOW-UP] Weight > 5kg while waiting â starting auto-drain")
            
            alarm_monitor_active = True
            if door_monitor_thread is None or not door_monitor_thread.is_alive():
                door_monitor_thread = threading.Thread(target=door_alarm_monitor_active, daemon=True)
                door_monitor_thread.start()
                print("[Followup] Door alarm monitor started (active while weight>5kg).")

            send_to_arduino("excess_pump_start")
            start_pump_safety_timer("excess")

            while True:
                wd.kick()
                wdrain = get_weight_from_uno(samples=5)
                send_to_arduino(f"weight:{wdrain}")
                print(f"ð [FOLLOW-UP] Auto-draining... {wdrain} kg")

                if wdrain <= 0.25 or pump_timeout_reached:
                    if pump_timeout_reached:
                        print("ð Pump timeout â treating as weight <= 0.25 kg.")
                    send_to_arduino("excess_pump_stop")
                    stop_pump_safety_timer()
                    alarm_monitor_active = False
                    send_to_arduino("LOCK")
                    break

                time.sleep(1)

        # ---- Check if door closed ----
        if mega_ser.in_waiting:
            msg = mega_ser.readline().decode().strip()
            if msg == "door_closed":
                print("ðª [FOLLOW-UP] Door closed.")
                break

        time.sleep(0.2)

    # 3) FINAL WEIGHT after the door closes
    print("âï¸ [FOLLOW-UP] Reading final weight after door closed...")
    w_final = get_weight_from_uno()
    print(f"ð [FOLLOW-UP] Final weight: {w_final} kg")

    # 4) Send this final weight to API
    send_final_data(w_final)

    # 5) Decide if normal pump or auto-drain again
    if w_final > 5.0:
        print("ð¨ [FOLLOW-UP] Final weight >5kg â starting FINAL auto-drain...")
        
        alarm_monitor_active = True
        if door_monitor_thread is None or not door_monitor_thread.is_alive():
            door_monitor_thread = threading.Thread(target=door_alarm_monitor_active, daemon=True)
            door_monitor_thread.start()
            print("[Followup-Final] Door alarm monitor started (active while weight>5kg).")
        send_to_arduino("excess_pump_start")
        start_pump_safety_timer("excess")

        while True:
            wd.kick()
            w2 = get_weight_from_uno(samples=5)
            send_to_arduino(f"weight:{w2}")
            print(f"ð [FOLLOW-UP] Final auto-drain... {w2} kg")

            if w2 <= 0.25 or pump_timeout_reached:

                print("ð¢ [FOLLOW-UP] Final auto-drain complete â stopping pump.")
                send_to_arduino("excess_pump_stop")
                
                send_to_arduino("LOCK")
                stop_pump_safety_timer()
                alarm_monitor_active = False

                
                break
            time.sleep(1)

    else:
        # Normal pump cycle
        print("âï¸ [FOLLOW-UP] Starting normal pump...")
        send_to_arduino("pump_now")
        start_pump_safety_timer("normal")
        
        

        while True:
            wd.kick()
            w2 = get_weight_from_uno(samples=5)
            send_to_arduino(f"weight:{w2}")
            print(f"ð [FOLLOW-UP] Pumping... {w2} kg")

            if w2 <= 0.25 or pump_timeout_reached:
                if pump_timeout_reached:
                    print("ð Pump timeout â treating as weight <= 0.25 kg.")
                stop_pump_safety_timer()
                send_to_arduino("LOCK")
                uno_ser.write(b"STOP_ALARM\n")
                alarm_monitor_active = False
                break

            time.sleep(1)

    status_enabled = True
    print("ð [FOLLOW-UP] Follow-up cycle COMPLETE.")

# ------------------------------
# Customer Panel Full Cycle (Original Logic + Pump Stop Fix)
# ------------------------------
def customer_cycle():
    """Behaves exactly like level10 logic, with auto pump stop"""
    global status_enabled, auto_drain_active, customer_cycle_running
    global alarm_monitor_active, door_monitor_thread
    customer_cycle_running = True
    
    
    print("[UNO] Sending tare command...")
    with uno_lock:
        uno_ser.write(b"t\n")


    print("[UNO] Waiting for TARED confirmation...")
    start = time.time()
    tared = False

    while time.time() - start < 3:
        wd.kick()

        # THREAD-SAFE READ FROM UNO
        with uno_lock:
            try:
                if uno_ser.in_waiting:
                    raw = uno_ser.readline()
                else:
                    raw = b""
            except Exception as e:
                print(f"â ï¸ Serial error during TARED read: {e}")
                raw = b""

        if not raw:
            time.sleep(0.05)
            continue

        try:
            msg = raw.decode(errors='ignore').strip()
            if msg == "TARED":
                print("[UNO] Confirmed TARED.")
                tared = True
                break
        except:
            continue

        time.sleep(0.05)

# ð¢ Retry once if no response
    if not tared:
        print("â  No TARED confirmation â retrying once...")
        with uno_lock:
            uno_ser.write(b"t\n")
    
        time.sleep(0.5)  # give UNO time to react again
        retry_start = time.time()
        while time.time() - retry_start < 3:
            wd.kick()

            with uno_lock:
                try:
                    if uno_ser.in_waiting:
                        raw = uno_ser.readline()
                    else:
                        raw = b""
                except Exception as e:
                    print(f"â ï¸ Serial error during TARED read (retry): {e}")
                    raw = b""

            if not raw:
                time.sleep(0.05)
                continue

            try:
                msg = raw.decode(errors='ignore').strip()
                if msg == "TARED":
                    print("[UNO] Second try confirmed tare.")
                    tared = True
                    break
            except:
                continue

    time.sleep(0.05)

    if not tared:
        print("â  Still no TARED confirmation. Continuing anyway.")
    else:
        print("â UNO tared successfully.")
    
    
    
    send_to_arduino("unlock")
    payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Customer verified - Top door unlock" }
    create_machine_audit(payload)
    print("ðª Top door unlocked (Customer Panel).")
    print("ð Waiting for door_opened...")
    door_opened = False
    start_time = time.time()
    timeout_open = 60

    while time.time() - start_time < timeout_open:
        wd.kick()
        if mega_ser.in_waiting:
            msg = mega_ser.readline().decode().strip()
            if msg == "door_opened":
                print("ð Arduino: door opened")
                door_opened = True
                break
        time.sleep(0.1)

    if not door_opened:
        payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Top door not opened by customer - lock engaged." }
        create_machine_audit(payload)
        print("â° Timeout: Door not opened.")
        send_to_arduino("LOCK")
        send_final_data(0.0)
        customer_cycle_running = False
        return

    print("â³ Waiting for door closed...")
    while True:
        wd.kick()
        weight_live = get_weight_from_uno()
        if weight_live is not None:
            print(f"âï¸ Live weight while pouring: {weight_live} kg")

            # If weight exceeds 5 KG before door closes -> AUTO DRAIN MODE
            if weight_live > 5.0:
                auto_drain_active = True
                print("ð¨ Weight exceeded 5kg! Starting immediate auto-drain mode...")

                # Log event
                payload = {"qrToken": TOKEN, "machineId": machine_id,
                        "action": f"Auto-drain triggered at {weight_live}kg before door closed"}
                create_machine_audit(payload)

                # SAFETY: lock door first (MEGA needs this)
                send_to_arduino("LOCK")
                time.sleep(0.3)
                
                # Start door alarm monitor (active only while alarm_monitor_active is True)
                
                alarm_monitor_active = True
                if door_monitor_thread is None or not door_monitor_thread.is_alive():
                    door_monitor_thread = threading.Thread(target=door_alarm_monitor_active, daemon=True)
                    door_monitor_thread.start()
                    print("[CustomerCycle] Door alarm monitor started (active while weight>5kg).")


                # Start pump immediately
                send_to_arduino("excess_pump_start")
                print("â¡ Pump started (Auto-drain before door closed).")
                start_pump_safety_timer("excess")

                # Monitor draining until <= 0.25kg
                while True:
                    wd.kick()
                    wdrain = get_weight_from_uno()
                    if wdrain is not None:
                        send_to_arduino(f"weight:{wdrain}")
                        print(f"âï¸ Draining... {wdrain} kg")

                        if wdrain <= 0.25:
                            print("ð¢ Drained to 0.25kg. Stopping pump.")
                            send_to_arduino("excess_pump_stop")
                            stop_pump_safety_timer()
                            
                             

                            payload = {"qrToken": TOKEN, "machineId": machine_id,
                                    "action": "Auto-drain complete (stopped at 0.25kg)"}
                            create_machine_audit(payload)
                            break

                    time.sleep(1)

                # SEND FIXED FINAL VALUE = 5.00 KG
                print("ð¤ Sending FIXED final value = 5.00 kg to API (auto-drain mode)")
                send_final_data(5.00)

                # Exit cycle â return to QR scanning
                print("ð Auto-drain finished â returning to main loop.")
                auto_drain_active = False
                
                
                print("ð Checking real door sensor state before followup...")

                mega_ser.reset_input_buffer()
                time.sleep(0.1)

                # Ask Mega for real door sensor state
                mega_ser.write(b"get_door_state\n")
                time.sleep(0.2)

                door_is_closed = None   # <-- IMPORTANT: start undefined

                # Try reading reply up to 10 times
                for _ in range(10):
                    if mega_ser.in_waiting:
                        msg = mega_ser.readline().decode().strip()
                        print(f"[Mega reply] {msg}")

                        if msg == "door_closed":
                            door_is_closed = True
                            break
                        elif msg == "door_opened":
                            door_is_closed = False
                            break

                    wd.kick()
                    time.sleep(0.1)

                # -------------- FINAL DECISION --------------
                if door_is_closed is None:
                    # Mega said NOTHING
                    print("â ï¸ Mega did not reply â assuming lid is ALREADY CLOSED.")
                    status_enabled = True
                    customer_cycle_running = False
                    alarm_monitor_active = False

                    return

                if door_is_closed:
                    print("â Lid is already CLOSED â skipping followup cycle.")
                    status_enabled = True
                    customer_cycle_running = False
                    alarm_monitor_active = False

                    return

                # else â door_opened
                print("ðª Lid is OPEN â running followup cycle...")
                followup_cycle()
                customer_cycle_running = False
                return
                
               

        if mega_ser.in_waiting:
            msg = mega_ser.readline().decode().strip()
            if msg == "door_closed":
                if auto_drain_active :
                    send_to_arduino("pump_now")
                    time.sleep(0.2)
                payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Machine started pumping." }
                create_machine_audit(payload)
                print("ð Arduino: door closed")
                print("âï¸ Reading weight from UNO...")
                w = get_weight_from_uno()
                if w < 0 :
                    w = 0
                print(f"ð Final Oil Amount: {w} kg")
                send_final_data(w)
                
                # â Tell Arduino it's safe to start the pump now
                send_to_arduino("pump_now")
                start_pump_safety_timer("normal")
                

                # ð¢ Added section â monitor weight until threshold reached
                print("ð Monitoring pump weight until below threshold...")
                while True:
                    wd.kick()
                    weight = get_weight_from_uno()
                    if weight is not None:
                        send_to_arduino(f"weight:{weight}")
                        print(f"âï¸ Sending weight: {weight} kg to Arduino")
                        if weight <= 0.2 or pump_timeout_reached:
                            if pump_timeout_reached:
                                print("ð Pump timeout â treating as weight <= 0.2 kg.")
                            payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :" Weight threshold reached . Machine-stoped pumping." }
                            create_machine_audit(payload)
                            print("â Weight threshold reached. Stopping pump.")
                            stop_pump_safety_timer()
                            send_to_arduino("LOCK")
                            break
                    time.sleep(1)
                # ð¢ End added section

                break
            elif msg.strip() == "overflow_confirmed":
                overflow_payload = {"token": TOKEN, "machineId" :machine_id}
                create_machine_overflow(overflow_payload)
                payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :f"Overflow Detected :{msg}" }
                create_machine_audit(payload)
                print(f"â ï¸  Detected: {msg}")
                send_to_arduino("LOCK")
                monitor_and_stop_pump()
                break
        time.sleep(0.2)
    
    auto_drain_active = False
    
    customer_cycle_running = False
    print("ð Cycle complete (Customer Panel).")

# ------------------------------
# Collector Panel Cycle (with auto-off timer)
# ------------------------------
def collector_cycle():
    """Collector Panel Logic (Updated):
    - First scan: only turns ON pin 25 and starts a 10-min auto-off timer
    - Second scan: turns OFF pin 25 manually
    - If 10 minutes pass without a second scan, auto-turns OFF pin 25
    """
    global pin25_on, status_enabled, auto_off_timer

    # ð¥ Pause status updates
    

    if not pin25_on:
        print("ð¢ Collector QR scanned â turning ON pin 25...")
        send_to_arduino("PIN25_ON")
        payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Collector verified - solenoid valve activated" }
        create_machine_audit(payload)
        print("â¡ Pin 25 ON (Collector mode active).")

        pin25_on = True

        # ð Start auto-off timer (10 minutes = 600 seconds)
        def auto_turn_off():
            global pin25_on
            if pin25_on:
                payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Auto-off timer expired - automatically turning OFF solenoid valve." }
                create_machine_audit(payload)
                print("â° Auto-off timer expired â turning OFF pin 25 automatically.")
                send_to_arduino("PIN25_OFF")
                pin25_on = False

        # If a previous timer exists, cancel it
        try:
            auto_off_timer.cancel()
        except:
            pass

        # Start new timer thread
        auto_off_timer = threading.Timer(600, auto_turn_off)
        auto_off_timer.daemon = True
        auto_off_timer.start()
        print("ð Auto-off timer (10 minutes) started.")

    else:
        # Second scan â manually turn off pin 25
        print("ð´ Collector QR scanned again â turning OFF pin 25...")
        send_to_arduino("PIN25_OFF")
        payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Collector verified â solenoid valve deactivated" }
        create_machine_audit(payload)
        print("â¡ Pin 25 OFF (Collector mode ended).")

        pin25_on = False

        # Cancel auto-off timer
        try:
            auto_off_timer.cancel()
            print("ð Auto-off timer cancelled.")
        except:
            pass

    # ð© Resume status updates
    

# ------------------------------
# Technician Panel Cycle (Unlock All Doors with 20s Delay)
# ------------------------------
def technician_cycle():
    """Technician Panel Logic:
    - Unlocks ALL doors (Top, Right, and Technician)
    - Keeps them open for 20 seconds
    - Then locks everything automatically
    """
    global status_enabled

    print("ð§° Technician QR scanned - unlocking ALL doors for maintenance...")
     # Pause status updates

    # Step 1: Unlock all doors
    send_to_arduino("unlock")         # Top door
    send_to_arduino("unlock_right")   # Right door
    send_to_arduino("unlock_tech")    # Technician door
    payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Technician verified - all doors (Top, Left, and Right) unlocked." }
    create_machine_audit(payload)
    print("ðª All doors unlocked (Top, Right, and Technician).")

    # Step 2: Wait 20 seconds
    print("â³ Keeping doors open for 20 seconds...")
    start = time.time()
    while time.time() - start < 20:
        wd.kick()
        time.sleep(0.2)

    # Step 3: Lock all doors again
    send_to_arduino("LOCK")
    payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Auto-lock timer expired - all doors locked after 20 seconds." }
    create_machine_audit(payload)
    print("ð All doors locked after 20 seconds of maintenance mode.")

    # Step 4: Resume sending active status
    


# ------------------------------
# Main Program
# ------------------------------
def main():
    global pin25_on, wd
    def pre_restart():
        print("[WATCHDOG] Sending LOCK before restart")
        try: send_to_arduino("LOCK")
        except: pass

    wd = Watchdog(timeout=120, pre_restart_callback=pre_restart)
    threading.Thread(target=global_auto_drain_monitor, daemon=True).start()
    print("[MAIN] Global auto-drain monitor started.")

    while True:
        wd.kick()
        token = wait_for_qr()
        panel_type = send_qr_to_api(token)
        if not panel_type:
            print("â Invalid QR token.")
            continue
        print(f"ð¢ QR Validated as {panel_type}")

        # ---------- CUSTOMER PANEL (Top Door, Original Logic) ----------
        if panel_type == "CUSTOMERPANEL":
            print("ð Checking LED status before customer cycle...")
            mega_ser.reset_input_buffer()
            mega_ser.write(b"get_led_status\n")
            time.sleep(0.3)
            led_status = mega_ser.readline().decode().strip()
            print(f"ð¡ LED status: {led_status}")

            if led_status == "LED_RED_ON":
                payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Customer cycle blocked - issue detected (door open or tank full)" }
                create_machine_audit(payload)
                print("ð« Customer cycle blocked â Red LED is ON (system locked).")
                send_to_arduino("LOCK")  # Ensure safety state
                continue
            else:
                payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Customer QR scanned" }
                create_machine_audit(payload)
                customer_cycle()

        # ---------- COLLECTOR PANEL ----------
        elif panel_type == "COLLECTORPANEL":
            payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Collector QR scanned" }
            create_machine_audit(payload)
            collector_cycle()

        # ---------- TECHNICIAN PANEL ----------
        elif panel_type == "TECHNICIANPANEL":
            payload = {"qrToken": TOKEN, "machineId" :machine_id, "action" :"Technician QR scanned" }
            create_machine_audit(payload)
            technician_cycle()

        # ---------- UNKNOWN ----------
        else:
            print("â ï¸ Unknown panel type.")
            send_to_arduino("LOCK")

        print("\nð Ready for next user...\n")
        time.sleep(2)

# ------------------------------
# Entry Point
# ------------------------------
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nð Program stopped by user.")
        mega_ser.close()
        uno_ser.close()








