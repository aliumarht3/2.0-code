def hardware_startup_diagnosis(tared_status):
    """
    Standalone hardware startup diagnosis.

    Output style:
    - Load cell / doors: ✅ or ❌
    - Ultrasonic sensors: detailed state text
    """

    print("[HARDWARE STARTUP DIAGNOSIS] Starting...")

    def ask_mega(command, timeout=1.5):
        try:
            mega_ser.reset_input_buffer()
        except:
            pass

        mega_ser.write((command + "\n").encode())
        mega_ser.flush()

        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                if mega_ser.in_waiting:
                    line = mega_ser.readline().decode(errors="ignore").strip()
                    if line:
                        return line
            except:
                pass
            time.sleep(0.05)

        return None

    results = {
        "load_cell": {
            "reply": "TARED" if tared_status else "NO_TARED_REPLY",
            "display": "✅" if tared_status else "❌"
        },
        "door_top": {
            "reply": None,
            "display": "❌"
        },
        "ultrasonic_small": {
            "reply": None,
            "display": "UNKNOWN"
        },
        "ultrasonic_res": {
            "reply": None,
            "display": "UNKNOWN"
        },
        "door_gpio2": {
            "reply": None,
            "display": "❌"
        },
        "door_gpio3": {
            "reply": None,
            "display": "❌"
        }
    }

    # 1. Top door sensor
    reply = ask_mega("get_door_state")
    results["door_top"]["reply"] = reply
    if reply == "door_closed":
        results["door_top"]["display"] = "✅"
    else:
        results["door_top"]["display"] = "❌"

    # 2. Ultrasonic small
    reply = ask_mega("CHECK_ULTRASONIC_SMALL")
    results["ultrasonic_small"]["reply"] = reply

    if reply == "CHECK_ULTRASONIC_SMALL:OK":
        results["ultrasonic_small"]["display"] = "✅"
    elif reply == "CHECK_ULTRASONIC_SMALL:OVERFLOW":
        results["ultrasonic_small"]["display"] = "OVERFLOW"
    elif reply == "CHECK_ULTRASONIC_SMALL:NO_READING":
        results["ultrasonic_small"]["display"] = "NOT WORKING"
    else:
        results["ultrasonic_small"]["display"] = "UNKNOWN"

    # 3. Ultrasonic reservoir
    reply = ask_mega("CHECK_ULTRASONIC_RES")
    results["ultrasonic_res"]["reply"] = reply

    if reply == "CHECK_ULTRASONIC_RES:OK":
        results["ultrasonic_res"]["display"] = "✅"
    elif reply == "CHECK_ULTRASONIC_RES:HIGH":
        results["ultrasonic_res"]["display"] = "HIGH"
    elif reply == "CHECK_ULTRASONIC_RES:HIGH_HIGH":
        results["ultrasonic_res"]["display"] = "HIGH HIGH"
    elif reply == "CHECK_ULTRASONIC_RES:NO_READING":
        results["ultrasonic_res"]["display"] = "NOT WORKING"
    else:
        results["ultrasonic_res"]["display"] = "UNKNOWN"

    # 4. Door GPIO2
    reply = ask_mega("CHECK_DOOR_GPIO2")
    results["door_gpio2"]["reply"] = reply
    if reply == "CHECK_DOOR_GPIO2:CLOSED":
        results["door_gpio2"]["display"] = "✅"
    else:
        results["door_gpio2"]["display"] = "❌"

    # 5. Door GPIO3
    reply = ask_mega("CHECK_DOOR_GPIO3")
    results["door_gpio3"]["reply"] = reply
    if reply == "CHECK_DOOR_GPIO3:CLOSED":
        results["door_gpio3"]["display"] = "✅"
    else:
        results["door_gpio3"]["display"] = "❌"

    print("[HARDWARE STARTUP DIAGNOSIS] Completed.")
    for item, info in results.items():
        print(f" - {item}: {info['display']} ({info['reply']})")

    return results