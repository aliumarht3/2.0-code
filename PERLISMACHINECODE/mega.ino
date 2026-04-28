// LEVEL_FINAL_COMBINED.ino
// GoHijau Smart Control â Normal LED logic + Global Ultrasonic Full Indicator

#include <NewPing.h>

// -----------------------------
// Pin Configuration
// -----------------------------
#define RED_LED 9
#define GREEN_LED 8
#define DOOR_LOCK 22
#define PUMP_RELAY 24
#define TURBIDITY_PIN A0
#define ULTRASONIC_SMALL_TRIG 10
#define ULTRASONIC_SMALL_ECHO 11
#define ULTRASONIC_RES_TRIG 12
#define ULTRASONIC_RES_ECHO 13
#define DOOR_SENSOR_TOP 23
#define DOOR_SENSOR_GPIO2 7
#define DOOR_SENSOR_GPIO3 6
#define PUMP_GPIO2 25
#define DOOR_LOCK_2 26
#define DOOR_LOCK_3 27

// -----------------------------
// Constants
// -----------------------------
#define MAX_DISTANCE 200
#define SMALL_TANK_THRESHOLD 10
#define RESERVOIR_HIGH 20
#define RESERVOIR_HIGH_HIGH 13
#define FINAL_WEIGHT_THRESHOLD 0.25

NewPing ultrasonicSmall(ULTRASONIC_SMALL_TRIG, ULTRASONIC_SMALL_ECHO, MAX_DISTANCE);
NewPing ultrasonicRes(ULTRASONIC_RES_TRIG, ULTRASONIC_RES_ECHO, MAX_DISTANCE);

// -----------------------------
// State Variables
// -----------------------------
bool pouringActive = false;
bool transferInProgress = false;
bool doorOpenedSinceUnlock = false;
bool cycleActive = false;
bool collectorModeActive = false;
bool ledBlinkState = false;
unsigned long lastBlinkTime = 0;
const unsigned long blinkInterval = 500;
const int TURBIDITY_SAMPLES = 10;
const int TURBIDITY_SAMPLE_DELAY_MS = 5;
bool overflowActive = false;  // for LED lock state
bool globalOverflowDetected = false; // new global LED indicator flag
bool waitingForPump = false;
unsigned long ledFreezeUntil = 0;
bool technicianMode = false;
bool pythonReady = false;
// -----------------------------
// Keep LED red while waiting for pump handshake
// -----------------------------
void keepLedRed() {
  // Keep LED red if waiting or within freeze window
  if (waitingForPump || millis() < ledFreezeUntil) {
    digitalWrite(RED_LED, LOW);
    digitalWrite(GREEN_LED, HIGH);
  }
}
// -----------------------------
// Helper: Keep LED red during handshake
// -----------------------------
void forceRedWhileWaiting() {
  if (waitingForPump) {
    // ð´ Keep LED Red during waiting handshake period
    digitalWrite(RED_LED, HIGH);
    digitalWrite(GREEN_LED, LOW);
  }
}

int readTurbidityRaw() {
  long sum = 0;

  for (int i = 0; i < TURBIDITY_SAMPLES; i++) {
    sum += analogRead(TURBIDITY_PIN);
    delay(TURBIDITY_SAMPLE_DELAY_MS);
  }

  return (int)(sum / TURBIDITY_SAMPLES);  // 0â1023
}
// -----------------------------
// Setup
// -----------------------------
void setup() {
  Serial.begin(9600);

  pinMode(RED_LED, OUTPUT);
  pinMode(GREEN_LED, OUTPUT);
  pinMode(DOOR_LOCK, OUTPUT);
  pinMode(TURBIDITY_PIN, INPUT);
  pinMode(PUMP_RELAY, OUTPUT);
  pinMode(DOOR_SENSOR_TOP, INPUT_PULLUP);
  pinMode(DOOR_SENSOR_GPIO2, INPUT_PULLUP);
  pinMode(DOOR_SENSOR_GPIO3, INPUT_PULLUP);
  pinMode(PUMP_GPIO2, OUTPUT);
  pinMode(DOOR_LOCK_2, OUTPUT);
  pinMode(DOOR_LOCK_3, OUTPUT);

  // Normal LED logic
  digitalWrite(RED_LED, HIGH);     // Red ON (standby)
  digitalWrite(GREEN_LED, LOW);    // Green OFF
  digitalWrite(DOOR_LOCK, HIGH);   // Locked
  digitalWrite(PUMP_RELAY, LOW);
  digitalWrite(PUMP_GPIO2, LOW);
  digitalWrite(DOOR_LOCK_2, HIGH);
  digitalWrite(DOOR_LOCK_3, HIGH);

  Serial.println("=== GoHijau LEVEL_FINAL_COMBINED â Normal LED + Global Overflow ===");
  Serial.println("=== GoHijau LEVEL_FINAL_COMBINED â Waiting for Python Ready signal ===");
}

// -----------------------------
// Main Loop
// -----------------------------
void loop() {
  // ð§  Wait until Python program tells Arduino it's ready
  if (!pythonReady) {
    digitalWrite(RED_LED, LOW);    // Keep red LED ON
    digitalWrite(GREEN_LED, HIGH);   // Keep green LED OFF
    delay(200);
    
    // Check if Python sends "PYTHON_READY"
    if (Serial.available()) {
      String cmd = Serial.readStringUntil('\n');
      cmd.trim();
      if (cmd == "PYTHON_READY") {
        pythonReady = true;
        Serial.println("PYTHON_READY_ACK");
        digitalWrite(RED_LED, LOW);
        digitalWrite(GREEN_LED, HIGH);
      }
    }
    return; // â Don't run any other code until Python is ready
  }
  
  // 1ï¸â£ Handle commands from Python
  while (Serial.available()) {

    String command = Serial.readStringUntil('\n');
    command.trim();

    // ------------------------------------
    // PRIORITY COMMAND: get_door_state
    // Always reply immediately
    // ------------------------------------
    if (command == "get_door_state") {

        int raw = digitalRead(DOOR_SENSOR_TOP);

        if (raw == LOW)
            Serial.println("door_closed");
        else
            Serial.println("door_opened");

        continue;   // â VERY IMPORTANT
    }

        // ------------------------------------
    // HARDWARE STARTUP DIAGNOSIS COMMANDS
    // On-demand only
    // ------------------------------------
    else if (command == "CHECK_ULTRASONIC_SMALL") {
      float smallDist = ultrasonicSmall.ping_cm();

      if (smallDist == 0) {
        Serial.println("CHECK_ULTRASONIC_SMALL:NO_READING");
      } 
      else if (smallDist <= SMALL_TANK_THRESHOLD) {
        Serial.println("CHECK_ULTRASONIC_SMALL:OVERFLOW");
      } 
      else {
        Serial.println("CHECK_ULTRASONIC_SMALL:OK");
      }
    }

    else if (command == "CHECK_ULTRASONIC_RES") {
      float resDist = ultrasonicRes.ping_cm();

      if (resDist == 0) {
        Serial.println("CHECK_ULTRASONIC_RES:NO_READING");
      } 
      else if (resDist <= RESERVOIR_HIGH_HIGH) {
        Serial.println("CHECK_ULTRASONIC_RES:HIGH_HIGH");
      } 
      else if (resDist <= RESERVOIR_HIGH) {
        Serial.println("CHECK_ULTRASONIC_RES:HIGH");
      } 
      else {
        Serial.println("CHECK_ULTRASONIC_RES:OK");
      }
    }

    else if (command == "CHECK_DOOR_GPIO2") {
      int raw = digitalRead(DOOR_SENSOR_GPIO2);

      if (raw == LOW)
        Serial.println("CHECK_DOOR_GPIO2:CLOSED");
      else
        Serial.println("CHECK_DOOR_GPIO2:OPEN");
    }

    else if (command == "CHECK_DOOR_GPIO3") {
      int raw = digitalRead(DOOR_SENSOR_GPIO3);

      if (raw == LOW)
        Serial.println("CHECK_DOOR_GPIO3:CLOSED");
      else
        Serial.println("CHECK_DOOR_GPIO3:OPEN");
    }
    else if (command == "TEST_LOCK1_ON") {
      digitalWrite(DOOR_LOCK, LOW);
      Serial.println("TEST_LOCK1_ON_ACK");
    }
    else if (command == "TEST_LOCK1_OFF") {
      digitalWrite(DOOR_LOCK, HIGH);
      Serial.println("TEST_LOCK1_OFF_ACK");
    }

    else if (command == "TEST_LOCK2_ON") {
      digitalWrite(DOOR_LOCK_2, LOW);
      Serial.println("TEST_LOCK2_ON_ACK");
    }
    else if (command == "TEST_LOCK2_OFF") {
      digitalWrite(DOOR_LOCK_2, HIGH);
      Serial.println("TEST_LOCK2_OFF_ACK");
    }

    else if (command == "TEST_LOCK3_ON") {
      digitalWrite(DOOR_LOCK_3, LOW);
      Serial.println("TEST_LOCK3_ON_ACK");
    }
    else if (command == "TEST_LOCK3_OFF") {
      digitalWrite(DOOR_LOCK_3, HIGH);
      Serial.println("TEST_LOCK3_OFF_ACK");
    }

    else if (command == "TEST_PUMP_ON") {
      digitalWrite(PUMP_RELAY, HIGH);
      Serial.println("TEST_PUMP_ON_ACK");
    }
    else if (command == "TEST_PUMP_OFF") {
      digitalWrite(PUMP_RELAY, LOW);
      Serial.println("TEST_PUMP_OFF_ACK");
    }

    else if (command == "TEST_VALVE_ON") {
      digitalWrite(PUMP_GPIO2, HIGH);
      Serial.println("TEST_VALVE_ON_ACK");
    }
    else if (command == "TEST_VALVE_OFF") {
      digitalWrite(PUMP_GPIO2, LOW);
      Serial.println("TEST_VALVE_OFF_ACK");
    }
    else if (command == "get_turbidity") {
      int turbidityRaw = readTurbidityRaw();
      Serial.print("turbidity:");
      Serial.println(turbidityRaw);
    }
    else if (command == "get_us_dist") {
      float dist = ultrasonicSmall.ping_cm();
      Serial.print("us_dist:");
      Serial.println(dist);
    }

    // ✅ Python LED control commands
    else if (command == "LED_GREEN_ON") {
      digitalWrite(RED_LED, HIGH);
      digitalWrite(GREEN_LED, LOW);
      Serial.println("LED_GREEN_ON_ACK");
    }
    else if (command == "LED_GREEN_OFF") {
      digitalWrite(GREEN_LED, HIGH);
      Serial.println("LED_GREEN_OFF_ACK");
    }

  


    if (command == "unlock" || command == "unlock_left") {
      digitalWrite(DOOR_LOCK, LOW);
      digitalWrite(RED_LED, LOW);
      digitalWrite(GREEN_LED, HIGH);
      Serial.println("door_opened_left");
      pouringActive = true;
      doorOpenedSinceUnlock = false;
      cycleActive = true;
    }

    else if (command == "unlock_right") {
      digitalWrite(DOOR_LOCK_2, LOW);
      digitalWrite(RED_LED, LOW);
      digitalWrite(GREEN_LED, HIGH);
      Serial.println("door_opened_right");
      pouringActive = true;
      doorOpenedSinceUnlock = false;
      cycleActive = true;
    }

    else if (command == "unlock_tech") {
      digitalWrite(DOOR_LOCK_3, LOW);
      digitalWrite(RED_LED, LOW);
      digitalWrite(GREEN_LED, HIGH);
      Serial.println("door_opened_tech");
      technicianMode = true;
      doorOpenedSinceUnlock = false;
      cycleActive = true;
      
    }

    else if (command == "LOCK") {
      digitalWrite(PUMP_RELAY, LOW);
      digitalWrite(DOOR_LOCK, HIGH);
      digitalWrite(DOOR_LOCK_2, HIGH);
      digitalWrite(DOOR_LOCK_3, HIGH);
      digitalWrite(GREEN_LED, HIGH);
      digitalWrite(RED_LED, LOW);
      pouringActive = false;
      transferInProgress = false;
      cycleActive = false;
      technicianMode = false;
      Serial.println("doors_locked");
    }

    else if (command == "PIN25_ON") {
      digitalWrite(PUMP_GPIO2, HIGH);
      digitalWrite(DOOR_LOCK_2, LOW);
      collectorModeActive = true;
      Serial.println("â Pin 25 ON â Collector mode active, LEDs blinking");
    }
    else if (command == "excess_pump_start") {
      digitalWrite(PUMP_RELAY, HIGH);
      Serial.println("excess_pump_started");
    }
    else if (command == "excess_pump_stop") {
      digitalWrite(PUMP_RELAY, LOW);
      Serial.println("excess_pump_stoped");
    }

    else if (command == "COLLECTOR_DOOR_OFF") {
      digitalWrite(DOOR_LOCK_2, HIGH);
      Serial.println("DOOR OFF");
    }

    else if (command == "PIN25_OFF") {
      digitalWrite(PUMP_GPIO2, LOW);
      digitalWrite(DOOR_LOCK_2, HIGH);
      collectorModeActive = false;
      digitalWrite(RED_LED, LOW);
      digitalWrite(GREEN_LED, LOW);
      Serial.println("â Pin 25 OFF â Collector mode ended, LEDs stopped");
    }

    else if (command == "get_led_status") {
      if (digitalRead(RED_LED) == LOW && digitalRead(GREEN_LED) == HIGH)
        Serial.println("LED_RED_ON");
      else if (digitalRead(GREEN_LED) == LOW && digitalRead(RED_LED) == HIGH)
        Serial.println("LED_GREEN_ON");
      else
        Serial.println("LED_UNKNOWN");
    }

    else if (command.startsWith("weight:")) {
      if (transferInProgress) {
        float weight = command.substring(7).toFloat();
        if (weight <= FINAL_WEIGHT_THRESHOLD) {
          digitalWrite(PUMP_RELAY, LOW);
          Serial.println("transfer_done");
          transferInProgress = false;
          digitalWrite(GREEN_LED, LOW);
          digitalWrite(RED_LED, HIGH);
        }
      }
    }
  }
  if (technicianMode) {
    delay(100);
    return;
  }
  // 2ï¸â£ Always-on Ultrasonic Overflow Check (global LED indicator)
  // 2ï¸â£ Always-on Ultrasonic Overflow Check (global LED indicator)
// =============================================================
// This block keeps the LED + Serial messages consistent.
// It will ONLY send "overflow_confirmed" to Python when
// the ultrasonic sensors detect a true overflow (not when
// LED is red due to door lock or technician mode).

// =============================================================
// ð§  Overflow Logic â 10-sample confirm + 10s delay recheck after Pin25_ON
// =============================================================

// =============================================================
// Overflow logic with DOOR priority (no early return)
// - Locks LED red during pouring/cycle
// - 10-sample confirm for overflow
// - When PIN25 ON: immediate green, wait 10s, then recheck
// =============================================================

static int overflowCount = 0;
const int requiredSamples = 10; // 10 consistent readings to confirm
static bool collectorCheckPending = false;
static unsigned long collectorStartTime = 0;

// --- read sensors early (but do NOT block other logic) ---
float smallDist = ultrasonicSmall.ping_cm();
float resDist   = ultrasonicRes.ping_cm();

bool overflowNow = ((smallDist > 0 && smallDist <= SMALL_TANK_THRESHOLD) ||
                    (resDist > 0 && resDist <= RESERVOIR_HIGH_HIGH));

// --- 10-sample smoothing ---
if (overflowNow) {
  if (overflowCount < requiredSamples) overflowCount++;
} else {
  if (overflowCount > 0) overflowCount--;
}

// --- confirm overflow after stable readings ---
if (overflowCount >= requiredSamples) {
  globalOverflowDetected = true;
}

// --- DOOR PRIORITY: if pouring or cycle active, LED must be RED but continue loop ---
bool doorPriority = (pouringActive || cycleActive);
if (doorPriority) {
  digitalWrite(RED_LED, LOW);   // red ON (active low)
  digitalWrite(GREEN_LED, HIGH);
  // note: NO return here â allow door events and other logic to run
}

// --- Collector / Pin25 handling ---
bool collectorActive = (digitalRead(PUMP_GPIO2) == HIGH);

if (collectorActive && !collectorCheckPending && globalOverflowDetected) {
  // collector just turned on and we were in overflow: immediately show green while waiting
  digitalWrite(RED_LED, HIGH);   // red OFF
  digitalWrite(GREEN_LED, LOW);  // green ON
  collectorStartTime = millis();
  collectorCheckPending = true;
}

// after 10s of collector being active, re-check sensors once
if (collectorActive && collectorCheckPending &&
    millis() - collectorStartTime >= 5000UL) {

  collectorCheckPending = false; // only do once per collector cycle

  // re-read sensors
  smallDist = ultrasonicSmall.ping_cm();
  resDist   = ultrasonicRes.ping_cm();
  bool stillOverflow = ((smallDist > 0 && smallDist <= SMALL_TANK_THRESHOLD) ||
                        (resDist > 0 && resDist <= RESERVOIR_HIGH_HIGH));

  if (stillOverflow) {
    // still overflow -> lock red
    globalOverflowDetected = true;
    digitalWrite(RED_LED, LOW);
    digitalWrite(GREEN_LED, HIGH);
  } else {
    // cleared -> show green and reset counters
    globalOverflowDetected = false;
    overflowCount = 0;
    digitalWrite(RED_LED, HIGH);
    digitalWrite(GREEN_LED, LOW);
  }
}

// reset pending flag when collector is off
if (!collectorActive) {
  collectorCheckPending = false;
}

// --- Final LED decision when nothing else has forced it ---
// If doorPriority was true we already set LED to red above.
// Otherwise follow overflow state.
if (!doorPriority) {
  if (globalOverflowDetected) {
    digitalWrite(RED_LED, LOW);
    digitalWrite(GREEN_LED, HIGH);
  } else {
    digitalWrite(RED_LED, HIGH);
    digitalWrite(GREEN_LED, LOW);
  }
}
  // 3ï¸â£ Customer door logic (same as version 1)
  if (pouringActive) {
    if (smallDist > 0 && smallDist <= SMALL_TANK_THRESHOLD) {
      Serial.println("overflow_small_tank");
      pouringActive = false;
      lockDoor();
    }

    if (resDist > 0) {
      if (resDist <= RESERVOIR_HIGH_HIGH) {
        Serial.println("overflow_res_high_high");
        pouringActive = false;
        lockDoor();
      } else if (resDist <= RESERVOIR_HIGH) {
        Serial.println("overflow_res_high");
      }
    }

    if (!doorOpenedSinceUnlock) {
      if (digitalRead(DOOR_SENSOR_TOP) == HIGH) {
        Serial.println("door_opened");
        doorOpenedSinceUnlock = true;
      }
    } 
 else if (!transferInProgress && digitalRead(DOOR_SENSOR_TOP) == LOW) {
  unsigned long doorCloseStart = millis();
  while (digitalRead(DOOR_SENSOR_TOP) == LOW) {
    if (millis() - doorCloseStart >= 4000) {
      Serial.println("door_closed");
      pouringActive = false;
      lockDoor2();
      waitingForPump = true;
      ledFreezeUntil = millis() + 3000;  // keep LED red for 3 s after door closes

// ð§  Wait for Python to say "pump_now" instead of a fixed delay
      unsigned long waitStart = millis();
      const unsigned long maxWait = 10000; // 10s safety timeout
      
      bool pumpStarted = false;

  while (millis() - waitStart < maxWait) {
    if (Serial.available()) {
      String cmd = Serial.readStringUntil('\n');
      cmd.trim();
      if (cmd == "pump_now") {
        Serial.println("start_transfer");
        digitalWrite(PUMP_RELAY, HIGH);
        transferInProgress = true;
        waitingForPump = false;
        digitalWrite(GREEN_LED, HIGH);
        digitalWrite(RED_LED, LOW);
        pumpStarted = true;
        break;
    }
  }
  delay(50);
}

// safety fallback if Python never responds
  if (!pumpStarted) {
    Serial.println("â ï¸ No pump_now received â auto-starting after timeout.");
    Serial.println("start_transfer");
    digitalWrite(PUMP_RELAY, HIGH);
    transferInProgress = true;
}
      break;
    }
    delay(100);
  }
}
  }

  // ð LED blinking for collector mode
  if (collectorModeActive) {
    unsigned long currentTime = millis();
    if (currentTime - lastBlinkTime >= blinkInterval) {
      ledBlinkState = !ledBlinkState;
      digitalWrite(RED_LED, ledBlinkState);
      digitalWrite(GREEN_LED, ledBlinkState);
      lastBlinkTime = currentTime;
    }
  } else if (!globalOverflowDetected && !waitingForPump) {
    updateDoorIndicator();
  }
 // ð§  Force LED red while waiting for pump handshake
  keepLedRed();
  delay(100);
}

// -----------------------------
// Helper Functions
// -----------------------------
void lockDoor() {
  waitingForPump = false;
  digitalWrite(DOOR_LOCK, HIGH);
  digitalWrite(DOOR_LOCK_2, HIGH);
  digitalWrite(DOOR_LOCK_3, HIGH);
  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, HIGH);
}
// -----------------------------
// Special lockDoor2 â keeps LED red until pump starts
// -----------------------------
void lockDoor2() {
  waitingForPump = true;         // Tell system we're waiting for pump
  transferInProgress = false;    // Ensure pump isn't active yet

  digitalWrite(DOOR_LOCK, HIGH);
  digitalWrite(DOOR_LOCK_2, HIGH);
  digitalWrite(DOOR_LOCK_3, HIGH);

  // ð´ Force LED stay red (do not allow green)
  digitalWrite(RED_LED, LOW);
  digitalWrite(GREEN_LED, HIGH);

  Serial.println("doors_locked_waiting_for_pump");
}

void updateDoorIndicator() {
  if (cycleActive || collectorModeActive || waitingForPump) return;

  bool topDoorClosed   = (digitalRead(DOOR_SENSOR_TOP) == LOW);
  bool techDoorClosed  = (digitalRead(DOOR_SENSOR_GPIO3) == LOW);

  if (!topDoorClosed || !techDoorClosed) {
    digitalWrite(GREEN_LED, HIGH);
    digitalWrite(RED_LED, LOW);
  } 
  else {
    digitalWrite(GREEN_LED, LOW);
    digitalWrite(RED_LED, HIGH);
  }
}