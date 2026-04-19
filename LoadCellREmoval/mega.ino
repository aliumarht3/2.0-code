// LEVEL_FINAL_COMBINED.ino
// GoHijau Smart Control – Normal LED + Global Ultrasonic + Turbidity & Junk Tank + Diagnostics

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
#define SMALL_TANK_THRESHOLD 8.5
#define RESERVOIR_HIGH 20
#define RESERVOIR_HIGH_HIGH 13
#define JUNK_TANK_THRESHOLD 15  
#define FINAL_WEIGHT_THRESHOLD 0.25

NewPing ultrasonicSmall(ULTRASONIC_SMALL_TRIG, ULTRASONIC_SMALL_ECHO, MAX_DISTANCE);
NewPing ultrasonicRes(ULTRASONIC_RES_TRIG, ULTRASONIC_RES_ECHO, MAX_DISTANCE);
NewPing ultrasonicJunk(ULTRASONIC_JUNK_TRIG, ULTRASONIC_JUNK_ECHO, MAX_DISTANCE); 

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
  pinMode(DIVERTER_RELAY, OUTPUT);
  
  // Normal LED logic
  digitalWrite(RED_LED, HIGH);
  digitalWrite(GREEN_LED, LOW);    
  digitalWrite(DOOR_LOCK, HIGH);   
  digitalWrite(PUMP_RELAY, LOW);
  digitalWrite(PUMP_GPIO2, LOW);
  digitalWrite(DOOR_LOCK_2, HIGH);
  digitalWrite(DOOR_LOCK_3, HIGH);
  digitalWrite(DIVERTER_RELAY, LOW);

  Serial.println("=== GoHijau LEVEL_FINAL_COMBINED – Advanced Sensors + Diagnostics ===");
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

    // --- Telemetry Request from Python ---
    else if (command == "get_telemetry") {
        int turbValue = analogRead(TURBIDITY_PIN);
        // --- FIXED: Added acoustic delays to prevent cross-talk ---
        float junkDist = ultrasonicJunk.ping_cm();
        delay(35); 
        float resDist = ultrasonicRes.ping_cm();
        
        Serial.print("telemetry:");
        Serial.print(turbValue); Serial.print(",");
        Serial.print(junkDist); Serial.print(",");
        Serial.println(resDist);
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
    }
    else if (command == "CHECK_ULTRASONIC_JUNK") {
      float junkDist = ultrasonicJunk.ping_cm();
      if (junkDist == 0) {
        Serial.println("CHECK_ULTRASONIC_JUNK:NO_READING");
      } else if (junkDist <= JUNK_TANK_THRESHOLD) {
        Serial.println("CHECK_ULTRASONIC_JUNK:OVERFLOW");
      } else {
        Serial.println("CHECK_ULTRASONIC_JUNK:OK");
      }
    }
    else if (command == "CHECK_DOOR_GPIO2") {
      int raw = digitalRead(DOOR_SENSOR_GPIO2);
      if (raw == LOW) Serial.println("CHECK_DOOR_GPIO2:CLOSED");
      else Serial.println("CHECK_DOOR_GPIO2:OPEN");
    }
    else if (command == "CHECK_DOOR_GPIO3") {
      int raw = digitalRead(DOOR_SENSOR_GPIO3);
      if (raw == LOW) Serial.println("CHECK_DOOR_GPIO3:CLOSED");
      else Serial.println("CHECK_DOOR_GPIO3:OPEN");
    }

    // Python LED control commands
    else if (command == "LED_GREEN_ON") {
      digitalWrite(RED_LED, HIGH);
      digitalWrite(GREEN_LED, LOW);
      Serial.println("LED_GREEN_ON_ACK");
    }
    else if (command == "LED_GREEN_OFF") {
      digitalWrite(GREEN_LED, HIGH);
      Serial.println("LED_GREEN_OFF_ACK");
    }

    // Customer Unlock Commands
    else if (command == "unlock" || command == "unlock_left" || command == "AUTO_DOOR_OPEN") {
      digitalWrite(DOOR_LOCK, LOW);
      digitalWrite(RED_LED, LOW);
      digitalWrite(GREEN_LED, HIGH);
      Serial.println("door_opened");
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
    
    // Lock / Stop Commands
    else if (command == "LOCK" || command == "AUTO_DOOR_CLOSE" || command == "DOOR_MOTOR_CLOSE") {
      digitalWrite(PUMP_RELAY, LOW);
      digitalWrite(DIVERTER_RELAY, LOW); 
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
    
    // Valve
    else if (command == "PIN25_ON") {
      digitalWrite(PUMP_GPIO2, HIGH);
      digitalWrite(DOOR_LOCK_2, LOW);
      collectorModeActive = true;
      Serial.println("– Pin 25 ON");
    }
    else if (command == "excess_pump_start") {
      digitalWrite(PUMP_RELAY, HIGH);
      Serial.println("excess_pump_started");
    }
    else if (command == "excess_pump_stop") {
      digitalWrite(PUMP_RELAY, LOW);
      Serial.println("excess_pump_stoped");
    }
    else if (command == "PIN25_OFF") {
      digitalWrite(PUMP_GPIO2, LOW);
      digitalWrite(DOOR_LOCK_2, HIGH);
      collectorModeActive = false;
      digitalWrite(RED_LED, LOW);
      digitalWrite(GREEN_LED, LOW);
      Serial.println("– Pin 25 OFF");
    }

    // --- ALIGNED DIAGNOSTIC/MANUAL TEST COMMANDS ---
    else if (command == "TEST_LOCK1_ON")  { digitalWrite(DOOR_LOCK, LOW);
      Serial.println("TEST_LOCK1_ON_ACK"); }
    else if (command == "TEST_LOCK1_OFF") { digitalWrite(DOOR_LOCK, HIGH);  Serial.println("TEST_LOCK1_OFF_ACK");
    }
    else if (command == "TEST_LOCK2_ON")  { digitalWrite(DOOR_LOCK_2, LOW); Serial.println("TEST_LOCK2_ON_ACK");
    }
    else if (command == "TEST_LOCK2_OFF") { digitalWrite(DOOR_LOCK_2, HIGH);Serial.println("TEST_LOCK2_OFF_ACK");
    }
    else if (command == "TEST_LOCK3_ON")  { digitalWrite(DOOR_LOCK_3, LOW); Serial.println("TEST_LOCK3_ON_ACK");
    }
    else if (command == "TEST_LOCK3_OFF") { digitalWrite(DOOR_LOCK_3, HIGH);Serial.println("TEST_LOCK3_OFF_ACK");
    }
    else if (command == "TEST_PUMP_ON")   { digitalWrite(PUMP_RELAY, HIGH); Serial.println("TEST_PUMP_ON_ACK");
    }
    else if (command == "TEST_PUMP_OFF")  { digitalWrite(PUMP_RELAY, LOW);  Serial.println("TEST_PUMP_OFF_ACK");
    }
    else if (command == "TEST_VALVE_ON")  { digitalWrite(PUMP_GPIO2, HIGH); Serial.println("TEST_VALVE_ON_ACK");
    }
    else if (command == "TEST_VALVE_OFF") { digitalWrite(PUMP_GPIO2, LOW);  Serial.println("TEST_VALVE_OFF_ACK");
    }
    
    // --- WIPER AND INTERNET DUMMY ACKS ---
    else if (command == "START_WIPER_ROUTINE" || command == "DUMMY_WIPER_ON") { Serial.println("WIPER_ON_ACK");
    }
    else if (command == "DUMMY_WIPER_OFF") { Serial.println("WIPER_OFF_ACK");
    }
    else if (command == "DUMMY_DOOR_MOTOR_ON") { Serial.println("MOTOR_ON_ACK");
    }
    else if (command == "DUMMY_DOOR_MOTOR_OFF") { Serial.println("MOTOR_OFF_ACK");
    }
    else if (command == "HAS_INTERNET") { Serial.println("INTERNET_OK");
    }
    else if (command == "NO_INTERNET") { Serial.println("INTERNET_NO");
    }

    else if (command == "get_led_status") {
      if (digitalRead(RED_LED) == LOW && digitalRead(GREEN_LED) == HIGH)
        Serial.println("LED_RED_ON");
      else if (digitalRead(GREEN_LED) == LOW && digitalRead(RED_LED) == HIGH)
        Serial.println("LED_GREEN_ON");
      else
        Serial.println("LED_UNKNOWN");
    }

    else if (command == "get_turbidity") {
      int turbidityRaw = analogRead(TURBIDITY_PIN);
      Serial.print("turbidity:");
      Serial.println(turbidityRaw);
    }

    // --- NEW: Gets distance of small tank for Python weight calculation ---
    else if (command == "get_small_dist") {
      float dist = readUltrasonicSmallSmoothed();
      Serial.print("small_dist:");
      Serial.println(dist);
    }
    
    else if (command.startsWith("weight:")) {
      if (transferInProgress) {
        float weight = command.substring(7).toFloat();
        if (weight <= FINAL_WEIGHT_THRESHOLD) {
          digitalWrite(PUMP_RELAY, LOW);
          digitalWrite(DIVERTER_RELAY, LOW);
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
  // Global Overflow Logic (Includes Junk Tank)
  // =============================================================
  static int overflowCount = 0;
  const int requiredSamples = 10; 
  static bool collectorCheckPending = false;
  static unsigned long collectorStartTime = 0;

  // --- FIXED: Added acoustic delays to prevent cross-talk ---
  float smallDist = ultrasonicSmall.ping_cm();
  delay(35);
  float resDist   = ultrasonicRes.ping_cm();
  delay(35);
  float junkDist  = ultrasonicJunk.ping_cm();

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
    // --- FIXED: Added acoustic delays here too ---
    smallDist = ultrasonicSmall.ping_cm();
    delay(35);
    resDist   = ultrasonicRes.ping_cm();
    delay(35);
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

  // Customer door logic
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
            Serial.println(">> No pump_now received – auto-starting after timeout.");
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

// -----------------------------
// Ultrasonic Smoothing Logic
// -----------------------------
float readUltrasonicSmallSmoothed() {
  const int SAMPLES = 7;
  const int SAMPLE_DELAY_MS = 30;
  float sum = 0;
  int validCount = 0;

  for (int i = 0; i < SAMPLES; i++) {
    float d = ultrasonicSmall.ping_cm();

    // Ignore 0s and anything beyond the physical constraints of the small tank
    if (d >= 2.0 && d <= 100.0) { 
      sum += d;
      validCount++;
    }
    delay(SAMPLE_DELAY_MS);
  }

  if (validCount == 0) return 0.0; // Return 0 if all readings fail
  return sum / validCount;
}