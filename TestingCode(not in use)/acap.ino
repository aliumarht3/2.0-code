// LEVEL_FINAL_COMBINED_AUTO_DOOR.ino
// GoHijau Smart Control — with isolated automatic sliding door feature

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
// NEW AUTO DOOR HARDWARE
// ADJUST THESE YOURSELF LATER
// -----------------------------
#define DOOR_LIMIT_SWITCH   28   // separate closed limit switch
#define DOOR_MOTOR_OPEN_PIN 4    // motor reverse/open pin
#define DOOR_MOTOR_CLOSE_PIN 5   // motor forward/close pin

// -----------------------------
// Constants
// -----------------------------
#define MAX_DISTANCE 200
#define SMALL_TANK_THRESHOLD 10
#define RESERVOIR_HIGH 20
#define RESERVOIR_HIGH_HIGH 13
#define FINAL_WEIGHT_THRESHOLD 0.25

// -----------------------------
// AUTO DOOR TUNING
// ADJUST THESE YOURSELF LATER
// -----------------------------
#define AUTO_DOOR_OPEN_PWM        180
#define AUTO_DOOR_CLOSE_PWM       170
#define AUTO_DOOR_OPEN_TIMEOUT_MS 8000UL
#define AUTO_DOOR_CLOSE_TIMEOUT_MS 8000UL

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
bool overflowActive = false;
bool globalOverflowDetected = false;
bool waitingForPump = false;
unsigned long ledFreezeUntil = 0;
bool technicianMode = false;
bool pythonReady = false;

// -----------------------------
// NEW AUTO DOOR STATES
// -----------------------------
enum AutoDoorState {
  AUTO_DOOR_CLOSED,
  AUTO_DOOR_OPENING,
  AUTO_DOOR_OPEN,
  AUTO_DOOR_CLOSING,
  AUTO_DOOR_FAULT
};

AutoDoorState autoDoorState = AUTO_DOOR_FAULT;
unsigned long autoDoorStartTime = 0;

// -----------------------------
// Helper: Keep LED red during handshake
// -----------------------------
void keepLedRed() {
  if (waitingForPump || millis() < ledFreezeUntil) {
    digitalWrite(RED_LED, LOW);
    digitalWrite(GREEN_LED, HIGH);
  }
}

void forceRedWhileWaiting() {
  if (waitingForPump) {
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
  return (int)(sum / TURBIDITY_SAMPLES);
}

// -----------------------------
// NEW AUTO DOOR HELPERS
// -----------------------------
bool limitSwitchActive() {
  return digitalRead(DOOR_LIMIT_SWITCH) == LOW;   // INPUT_PULLUP
}

bool gpio3ClosedConfirm() {
  return digitalRead(DOOR_SENSOR_GPIO3) == LOW;   // INPUT_PULLUP
}

bool gpio2OpenConfirm() {
  return digitalRead(DOOR_SENSOR_GPIO2) == LOW;   // INPUT_PULLUP
}

bool topOpenConfirm() {
  return digitalRead(DOOR_SENSOR_TOP) == LOW;     // INPUT_PULLUP
}

bool isAutoDoorClosed() {
  return limitSwitchActive() && gpio3ClosedConfirm();
}

bool isAutoDoorOpen() {
  return gpio2OpenConfirm() && topOpenConfirm();
}

void autoDoorMotorStop() {
  analogWrite(DOOR_MOTOR_OPEN_PIN, 0);
  analogWrite(DOOR_MOTOR_CLOSE_PIN, 0);
}

void autoDoorMotorOpen() {
  analogWrite(DOOR_MOTOR_CLOSE_PIN, 0);
  analogWrite(DOOR_MOTOR_OPEN_PIN, AUTO_DOOR_OPEN_PWM);
}

void autoDoorMotorClose() {
  analogWrite(DOOR_MOTOR_OPEN_PIN, 0);
  analogWrite(DOOR_MOTOR_CLOSE_PIN, AUTO_DOOR_CLOSE_PWM);
}

void startAutoDoorOpen() {
  if (autoDoorState == AUTO_DOOR_OPEN || autoDoorState == AUTO_DOOR_OPENING) return;

  autoDoorStartTime = millis();
  autoDoorMotorOpen();
  autoDoorState = AUTO_DOOR_OPENING;

  Serial.println("door_opening");
}

void startAutoDoorClose() {
  if (autoDoorState == AUTO_DOOR_CLOSED || autoDoorState == AUTO_DOOR_CLOSING) return;

  autoDoorStartTime = millis();
  autoDoorMotorClose();
  autoDoorState = AUTO_DOOR_CLOSING;

  Serial.println("door_closing");
}

void updateAutoDoor() {
  switch (autoDoorState) {

    case AUTO_DOOR_OPENING:
      if (millis() - autoDoorStartTime > AUTO_DOOR_OPEN_TIMEOUT_MS) {
        autoDoorMotorStop();
        autoDoorState = AUTO_DOOR_FAULT;
        Serial.println("door_fault_open_timeout");
      }
      else if (isAutoDoorOpen()) {
        autoDoorMotorStop();
        autoDoorState = AUTO_DOOR_OPEN;
        Serial.println("door_opened");
      }
      break;

    case AUTO_DOOR_CLOSING:
      if (millis() - autoDoorStartTime > AUTO_DOOR_CLOSE_TIMEOUT_MS) {
        autoDoorMotorStop();
        autoDoorState = AUTO_DOOR_FAULT;
        Serial.println("door_fault_close_timeout");
      }
else if (isAutoDoorClosed()) {
  autoDoorMotorStop();
  autoDoorState = AUTO_DOOR_CLOSED;

  pouringActive = false;
  cycleActive = false;
  transferInProgress = false;
  waitingForPump = true;
  ledFreezeUntil = millis() + 3000;

  Serial.println("door_closed");
}
      break;

    case AUTO_DOOR_CLOSED:
    case AUTO_DOOR_OPEN:
    case AUTO_DOOR_FAULT:
    default:
      break;
  }
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

  // NEW auto door hardware
  pinMode(DOOR_LIMIT_SWITCH, INPUT_PULLUP);
  pinMode(DOOR_MOTOR_OPEN_PIN, OUTPUT);
  pinMode(DOOR_MOTOR_CLOSE_PIN, OUTPUT);

  // Normal LED logic
  digitalWrite(RED_LED, HIGH);
  digitalWrite(GREEN_LED, LOW);
  digitalWrite(DOOR_LOCK, HIGH);
  digitalWrite(PUMP_RELAY, LOW);
  digitalWrite(PUMP_GPIO2, LOW);
  digitalWrite(DOOR_LOCK_2, HIGH);
  digitalWrite(DOOR_LOCK_3, HIGH);

  autoDoorMotorStop();

  if (isAutoDoorClosed()) {
    autoDoorState = AUTO_DOOR_CLOSED;
  } else if (isAutoDoorOpen()) {
    autoDoorState = AUTO_DOOR_OPEN;
  } else {
    autoDoorState = AUTO_DOOR_FAULT;
  }

  Serial.println("=== GoHijau LEVEL_FINAL_COMBINED — Normal LED + Global Overflow ===");
  Serial.println("=== GoHijau LEVEL_FINAL_COMBINED — Waiting for Python Ready signal ===");
}

// -----------------------------
// Main Loop
// -----------------------------
void loop() {
  // Wait until Python tells Arduino it's ready
  if (!pythonReady) {
    digitalWrite(RED_LED, LOW);
    digitalWrite(GREEN_LED, HIGH);
    delay(200);

    if (Serial.available()) {
      String cmd = Serial.readStringUntil('\n');
      cmd.trim();
      if (cmd == "PYTHON_READY") {
        pythonReady = true;
        Serial.println("PYTHON_READY_ACK");
        digitalWrite(RED_LED, HIGH);
        digitalWrite(GREEN_LED, LOW);
      }
    }
    return;
  }

  // -----------------------------
  // Handle commands from Python
  // -----------------------------
  while (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    // ------------------------------------
    // NEW AUTO DOOR FEATURE
    // ------------------------------------
    else if (command == "AUTO_DOOR_OPEN") {
      startAutoDoorOpen();
      continue;
    }

    else if (command == "AUTO_DOOR_CLOSE") {
      startAutoDoorClose();
      continue;
    }

    else if (command == "AUTO_DOOR_STATUS") {
      if (isAutoDoorClosed()) {
        Serial.println("door_closed");
      } else if (isAutoDoorOpen()) {
        Serial.println("door_opened");
      } else if (autoDoorState == AUTO_DOOR_FAULT) {
        Serial.println("door_fault");
      } else {
        Serial.println("door_moving");
      }
      continue;
    }

    else if (command == "pump_now") {
      if (waitingForPump && !transferInProgress) {
        Serial.println("start_transfer");
        digitalWrite(PUMP_RELAY, HIGH);
        transferInProgress = true;
        waitingForPump = false;
        digitalWrite(GREEN_LED, HIGH);
        digitalWrite(RED_LED, LOW);
      } else {
        Serial.println("pump_now_ignored");
      }
      continue;
    }

    // ------------------------------------
    // HARDWARE STARTUP DIAGNOSIS COMMANDS
    // ------------------------------------
    else if (command == "CHECK_ULTRASONIC_SMALL") {
      float smallDist = ultrasonicSmall.ping_cm();

      if (smallDist == 0) {
        Serial.println("CHECK_ULTRASONIC_SMALL:NO_READING");
      } else if (smallDist <= SMALL_TANK_THRESHOLD) {
        Serial.println("CHECK_ULTRASONIC_SMALL:OVERFLOW");
      } else {
        Serial.println("CHECK_ULTRASONIC_SMALL:OK");
      }
      continue;
    }

    else if (command == "CHECK_ULTRASONIC_RES") {
      float resDist = ultrasonicRes.ping_cm();

      if (resDist == 0) {
        Serial.println("CHECK_ULTRASONIC_RES:NO_READING");
      } else if (resDist <= RESERVOIR_HIGH_HIGH) {
        Serial.println("CHECK_ULTRASONIC_RES:HIGH_HIGH");
      } else if (resDist <= RESERVOIR_HIGH) {
        Serial.println("CHECK_ULTRASONIC_RES:HIGH");
      } else {
        Serial.println("CHECK_ULTRASONIC_RES:OK");
      }
      continue;
    }

    else if (command == "CHECK_DOOR_GPIO2") {
      int raw = digitalRead(DOOR_SENSOR_GPIO2);
      if (raw == LOW) Serial.println("CHECK_DOOR_GPIO2:CLOSED");
      else Serial.println("CHECK_DOOR_GPIO2:OPEN");
      continue;
    }

    else if (command == "CHECK_DOOR_GPIO3") {
      int raw = digitalRead(DOOR_SENSOR_GPIO3);
      if (raw == LOW) Serial.println("CHECK_DOOR_GPIO3:CLOSED");
      else Serial.println("CHECK_DOOR_GPIO3:OPEN");
      continue;
    }

    // ------------------------------------
    // MANUAL PHYSICAL TEST COMMANDS
    // ------------------------------------
    else if (command == "TEST_LOCK1_ON") {
      digitalWrite(DOOR_LOCK, LOW);
      Serial.println("TEST_LOCK1_ON_ACK");
      continue;
    }
    else if (command == "TEST_LOCK1_OFF") {
      digitalWrite(DOOR_LOCK, HIGH);
      Serial.println("TEST_LOCK1_OFF_ACK");
      continue;
    }

    else if (command == "TEST_LOCK2_ON") {
      digitalWrite(DOOR_LOCK_2, LOW);
      Serial.println("TEST_LOCK2_ON_ACK");
      continue;
    }
    else if (command == "TEST_LOCK2_OFF") {
      digitalWrite(DOOR_LOCK_2, HIGH);
      Serial.println("TEST_LOCK2_OFF_ACK");
      continue;
    }

    else if (command == "TEST_LOCK3_ON") {
      digitalWrite(DOOR_LOCK_3, LOW);
      Serial.println("TEST_LOCK3_ON_ACK");
      continue;
    }
    else if (command == "TEST_LOCK3_OFF") {
      digitalWrite(DOOR_LOCK_3, HIGH);
      Serial.println("TEST_LOCK3_OFF_ACK");
      continue;
    }

    else if (command == "TEST_PUMP_ON") {
      digitalWrite(PUMP_RELAY, HIGH);
      Serial.println("TEST_PUMP_ON_ACK");
      continue;
    }
    else if (command == "TEST_PUMP_OFF") {
      digitalWrite(PUMP_RELAY, LOW);
      Serial.println("TEST_PUMP_OFF_ACK");
      continue;
    }

    else if (command == "TEST_VALVE_ON") {
      digitalWrite(PUMP_GPIO2, HIGH);
      Serial.println("TEST_VALVE_ON_ACK");
      continue;
    }
    else if (command == "TEST_VALVE_OFF") {
      digitalWrite(PUMP_GPIO2, LOW);
      Serial.println("TEST_VALVE_OFF_ACK");
      continue;
    }

    else if (command == "get_turbidity") {
      int turbidityRaw = readTurbidityRaw();
      Serial.print("turbidity:");
      Serial.println(turbidityRaw);
      continue;
    }

    // ------------------------------------
    // Existing LED commands
    // ------------------------------------
    if (command == "LED_GREEN_ON") {
      digitalWrite(RED_LED, HIGH);
      digitalWrite(GREEN_LED, LOW);
      Serial.println("LED_GREEN_ON_ACK");
    }
    else if (command == "LED_GREEN_OFF") {
      digitalWrite(GREEN_LED, HIGH);
      Serial.println("LED_GREEN_OFF_ACK");
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
      Serial.println("✅ Pin 25 ON — Collector mode active, LEDs blinking");
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
      Serial.println("✅ Pin 25 OFF — Collector mode ended, LEDs stopped");
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
    updateAutoDoor();
    delay(100);
    return;
  }

  // -----------------------------
  // Always-on Ultrasonic Overflow Check
  // -----------------------------
  static int overflowCount = 0;
  const int requiredSamples = 10;
  static bool collectorCheckPending = false;
  static unsigned long collectorStartTime = 0;

  float smallDist = ultrasonicSmall.ping_cm();
  float resDist   = ultrasonicRes.ping_cm();

  bool overflowNow = ((smallDist > 0 && smallDist <= SMALL_TANK_THRESHOLD) ||
                      (resDist > 0 && resDist <= RESERVOIR_HIGH_HIGH));

  if (overflowNow) {
    if (overflowCount < requiredSamples) overflowCount++;
  } else {
    if (overflowCount > 0) overflowCount--;
  }

  if (overflowCount >= requiredSamples) {
    globalOverflowDetected = true;
  }

  bool doorPriority = (pouringActive || cycleActive);
  if (doorPriority) {
    digitalWrite(RED_LED, LOW);
    digitalWrite(GREEN_LED, HIGH);
  }

  bool collectorActive = (digitalRead(PUMP_GPIO2) == HIGH);

  if (collectorActive && !collectorCheckPending && globalOverflowDetected) {
    digitalWrite(RED_LED, HIGH);
    digitalWrite(GREEN_LED, LOW);
    collectorStartTime = millis();
    collectorCheckPending = true;
  }

  if (collectorActive && collectorCheckPending &&
      millis() - collectorStartTime >= 5000UL) {

    collectorCheckPending = false;

    smallDist = ultrasonicSmall.ping_cm();
    resDist   = ultrasonicRes.ping_cm();
    bool stillOverflow = ((smallDist > 0 && smallDist <= SMALL_TANK_THRESHOLD) ||
                          (resDist > 0 && resDist <= RESERVOIR_HIGH_HIGH));

    if (stillOverflow) {
      globalOverflowDetected = true;
      digitalWrite(RED_LED, LOW);
      digitalWrite(GREEN_LED, HIGH);
    } else {
      globalOverflowDetected = false;
      overflowCount = 0;
      digitalWrite(RED_LED, HIGH);
      digitalWrite(GREEN_LED, LOW);
    }
  }

  if (!collectorActive) {
    collectorCheckPending = false;
  }

  if (!doorPriority) {
    if (globalOverflowDetected) {
      digitalWrite(RED_LED, LOW);
      digitalWrite(GREEN_LED, HIGH);
    } else {
      digitalWrite(RED_LED, HIGH);
      digitalWrite(GREEN_LED, LOW);
    }
  }

  // -----------------------------
  // OLD / EXISTING customer door logic
  // Kept for compatibility with old Python flow
  // -----------------------------
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
          ledFreezeUntil = millis() + 3000;
          break;
        }
        delay(100);
      }
    }
  }

  // -----------------------------
  // Collector LED blinking
  // -----------------------------
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

  // NEW auto door state machine
  updateAutoDoor();

  keepLedRed();
  updateAutoDoor();
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

void lockDoor2() {
  waitingForPump = true;
  transferInProgress = false;

  digitalWrite(DOOR_LOCK, HIGH);
  digitalWrite(DOOR_LOCK_2, HIGH);
  digitalWrite(DOOR_LOCK_3, HIGH);

  digitalWrite(RED_LED, LOW);
  digitalWrite(GREEN_LED, HIGH);

  Serial.println("doors_locked_waiting_for_pump");
}

void updateDoorIndicator() {
  if (cycleActive || collectorModeActive || waitingForPump) return;

  // Updated to reflect NEW separate closed logic
  bool mainDoorClosed = isAutoDoorClosed();

  if (!mainDoorClosed) {
    digitalWrite(GREEN_LED, HIGH);
    digitalWrite(RED_LED, LOW);
  }
  else {
    digitalWrite(GREEN_LED, LOW);
    digitalWrite(RED_LED, HIGH);
  }
}