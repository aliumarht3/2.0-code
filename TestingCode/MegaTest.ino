// LEVEL_FINAL_COMBINED.ino
// GoHijau Smart Control — Normal LED + Global Ultrasonic + Turbidity & Junk Tank

#include <NewPing.h>

// -----------------------------
// Pin Configuration
// -----------------------------
#define RED_LED 9
#define GREEN_LED 8
#define DOOR_LOCK 22
#define PUMP_RELAY 24
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

// --- NEW HARDWARE PINS ---
#define TURBIDITY_PIN A0
#define ULTRASONIC_JUNK_TRIG 4
#define ULTRASONIC_JUNK_ECHO 5
#define DIVERTER_RELAY 28 // Relay to switch flow to the junk tank

// -----------------------------
// Constants
// -----------------------------
#define MAX_DISTANCE 200
#define SMALL_TANK_THRESHOLD 10
#define RESERVOIR_HIGH 20
#define RESERVOIR_HIGH_HIGH 13
#define JUNK_TANK_THRESHOLD 15  // Cm from top before junk tank is considered full
#define FINAL_WEIGHT_THRESHOLD 0.25

NewPing ultrasonicSmall(ULTRASONIC_SMALL_TRIG, ULTRASONIC_SMALL_ECHO, MAX_DISTANCE);
NewPing ultrasonicRes(ULTRASONIC_RES_TRIG, ULTRASONIC_RES_ECHO, MAX_DISTANCE);
NewPing ultrasonicJunk(ULTRASONIC_JUNK_TRIG, ULTRASONIC_JUNK_ECHO, MAX_DISTANCE); // New sensor

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
bool overflowActive = false;  
bool globalOverflowDetected = false; 
bool waitingForPump = false;
unsigned long ledFreezeUntil = 0;
bool technicianMode = false;
bool pythonReady = false;

// -----------------------------
// Keep LED red while waiting for pump handshake
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

// -----------------------------
// Setup
// -----------------------------
void setup() {
  Serial.begin(9600);

  pinMode(RED_LED, OUTPUT);
  pinMode(GREEN_LED, OUTPUT);
  pinMode(DOOR_LOCK, OUTPUT);
  pinMode(PUMP_RELAY, OUTPUT);
  pinMode(DOOR_SENSOR_TOP, INPUT_PULLUP);
  pinMode(DOOR_SENSOR_GPIO2, INPUT_PULLUP);
  pinMode(DOOR_SENSOR_GPIO3, INPUT_PULLUP);
  pinMode(PUMP_GPIO2, OUTPUT);
  pinMode(DOOR_LOCK_2, OUTPUT);
  pinMode(DOOR_LOCK_3, OUTPUT);
  pinMode(DIVERTER_RELAY, OUTPUT); // Init Diverter

  // Normal LED logic
  digitalWrite(RED_LED, HIGH);     
  digitalWrite(GREEN_LED, LOW);    
  digitalWrite(DOOR_LOCK, HIGH);   
  digitalWrite(PUMP_RELAY, LOW);
  digitalWrite(PUMP_GPIO2, LOW);
  digitalWrite(DOOR_LOCK_2, HIGH);
  digitalWrite(DOOR_LOCK_3, HIGH);
  digitalWrite(DIVERTER_RELAY, LOW); 

  Serial.println("=== GoHijau LEVEL_FINAL_COMBINED — Advanced Sensors ===");
  Serial.println("=== Waiting for Python Ready signal ===");
}

// -----------------------------
// Main Loop
// -----------------------------
void loop() {
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
        digitalWrite(RED_LED, LOW);
        digitalWrite(GREEN_LED, HIGH);
      }
    }
    return; 
  }
  
  while (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command == "get_door_state") {
        int raw = digitalRead(DOOR_SENSOR_TOP);
        if (raw == LOW) Serial.println("door_closed");
        else Serial.println("door_opened");
        continue;   
    }

    // --- NEW: Telemetry Request from Python ---
    if (command == "get_telemetry") {
        int turbValue = analogRead(TURBIDITY_PIN);
        float junkDist = ultrasonicJunk.ping_cm();
        float resDist = ultrasonicRes.ping_cm();
        
        Serial.print("telemetry:");
        Serial.print(turbValue); Serial.print(",");
        Serial.print(junkDist); Serial.print(",");
        Serial.println(resDist);
        continue;
    }

    if (command == "LED_GREEN_ON") {
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
      digitalWrite(DIVERTER_RELAY, LOW); // Safe shutdown for diverter
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
      Serial.println("✅ Pin 25 ON");
    }
    else if (command == "excess_pump_start") {
      digitalWrite(PUMP_RELAY, HIGH);
      Serial.println("excess_pump_started");
    }
    else if (command == "excess_pump_stop") {
      digitalWrite(PUMP_RELAY, LOW);
      Serial.println("excess_pump_stoped");
    }
    // --- NEW: Divert Command ---
    else if (command == "divert_to_junk") {
      digitalWrite(DIVERTER_RELAY, HIGH); // Activate junk routing
      digitalWrite(PUMP_RELAY, HIGH);     // Turn on pump
      transferInProgress = true;
      waitingForPump = false;
      digitalWrite(GREEN_LED, HIGH);
      digitalWrite(RED_LED, LOW);
      Serial.println("diverting_to_junk");
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
      Serial.println("✅ Pin 25 OFF");
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
          digitalWrite(DIVERTER_RELAY, LOW); // Turn off diverter when drained
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

  // =============================================================
  // 🧠 Global Overflow Logic (Now includes Junk Tank)
  // =============================================================
  static int overflowCount = 0;
  const int requiredSamples = 10; 
  static bool collectorCheckPending = false;
  static unsigned long collectorStartTime = 0;

  float smallDist = ultrasonicSmall.ping_cm();
  float resDist   = ultrasonicRes.ping_cm();
  float junkDist  = ultrasonicJunk.ping_cm(); // Check junk tank

  // OVERFLOW if any of the three tanks hit their limit
  bool overflowNow = ((smallDist > 0 && smallDist <= SMALL_TANK_THRESHOLD) ||
                      (resDist > 0 && resDist <= RESERVOIR_HIGH_HIGH) ||
                      (junkDist > 0 && junkDist <= JUNK_TANK_THRESHOLD));

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

  if (collectorActive && collectorCheckPending && millis() - collectorStartTime >= 5000UL) {
    collectorCheckPending = false; 

    smallDist = ultrasonicSmall.ping_cm();
    resDist   = ultrasonicRes.ping_cm();
    junkDist  = ultrasonicJunk.ping_cm();

    bool stillOverflow = ((smallDist > 0 && smallDist <= SMALL_TANK_THRESHOLD) ||
                          (resDist > 0 && resDist <= RESERVOIR_HIGH_HIGH) ||
                          (junkDist > 0 && junkDist <= JUNK_TANK_THRESHOLD));

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

  // 3️⃣ Customer door logic
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

    // Trigger lock if Junk Tank overflows during a pour
    if (junkDist > 0 && junkDist <= JUNK_TANK_THRESHOLD) {
      Serial.println("overflow_junk_tank");
      pouringActive = false;
      lockDoor();
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

          unsigned long waitStart = millis();
          const unsigned long maxWait = 10000; 
          
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
              // Catch the divert command if sent immediately after door close
              else if (cmd == "divert_to_junk") {
                Serial.println("diverting_to_junk");
                digitalWrite(DIVERTER_RELAY, HIGH);
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

          if (!pumpStarted) {
            Serial.println("⚠️ No pump_now received — auto-starting after timeout.");
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
  digitalWrite(DIVERTER_RELAY, LOW); 
  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, HIGH);
}

void lockDoor2() {
  waitingForPump = true;         
  transferInProgress = false;    

  digitalWrite(DOOR_LOCK, HIGH);
  digitalWrite(DOOR_LOCK_2, HIGH);
  digitalWrite(DOOR_LOCK_3, HIGH);
  digitalWrite(DIVERTER_RELAY, LOW); 

  digitalWrite(RED_LED, LOW);
  digitalWrite(GREEN_LED, HIGH);

  Serial.println("doors_locked_waiting_for_pump");
}

void updateDoorIndicator() {
  if (cycleActive || collectorModeActive || waitingForPump) return;

  bool topDoorClosed   = (digitalRead(DOOR_SENSOR_TOP) == LOW);
  bool rightDoorClosed = (digitalRead(DOOR_SENSOR_GPIO2) == LOW);
  bool techDoorClosed  = (digitalRead(DOOR_SENSOR_GPIO3) == LOW);

  if (!topDoorClosed || !rightDoorClosed || !techDoorClosed) {
    digitalWrite(GREEN_LED, HIGH);
    digitalWrite(RED_LED, LOW);
  } 
  else {
    digitalWrite(GREEN_LED, LOW);
    digitalWrite(RED_LED, HIGH);
  }
}