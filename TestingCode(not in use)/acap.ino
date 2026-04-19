#include <NewPing.h>

// =====================================================
// RESERVOIR ULTRASONIC CALIBRATION SKETCH
// For one sensor only: ULTRASONIC_RES
// =====================================================

// -----------------------------
// Pin Configuration
// -----------------------------
#define ULTRASONIC_RES_TRIG 12
#define ULTRASONIC_RES_ECHO 13

// -----------------------------
// Sensor Limits
// -----------------------------
#define MAX_DISTANCE 200
#define RES_MIN_VALID_CM 2.0
#define RES_MAX_VALID_CM 200.0

// -----------------------------
// Calibration Constants
// CHANGE THESE LATER AFTER HAND TEST
// -----------------------------
#define RES_EMPTY_CM 80.0     // distance when tank is low/empty
#define RES_FULL_CM 10.0      // distance when tank is full/safe max

#define RES_WARNING_CM 20.0   // high warning zone
#define RES_CRITICAL_CM 13.0  // high-high / overflow warning

// -----------------------------
// Smoothing Settings
// -----------------------------
const int RES_SAMPLES = 7;
const int RES_SAMPLE_DELAY_MS = 30;

// -----------------------------
// Live Output
// -----------------------------
bool liveMode = false;
unsigned long lastLivePrint = 0;
const unsigned long LIVE_INTERVAL_MS = 1000;

// -----------------------------
// Object
// -----------------------------
NewPing ultrasonicRes(ULTRASONIC_RES_TRIG, ULTRASONIC_RES_ECHO, MAX_DISTANCE);

// =====================================================
// Helper Functions
// =====================================================

float readUltrasonicResRawCm() {
  float sum = 0;
  int validCount = 0;

  for (int i = 0; i < RES_SAMPLES; i++) {
    float d = ultrasonicRes.ping_cm();

    if (d >= RES_MIN_VALID_CM && d <= RES_MAX_VALID_CM) {
      sum += d;
      validCount++;
    }

    delay(RES_SAMPLE_DELAY_MS);
  }

  if (validCount == 0) return -1.0;
  return sum / validCount;
}

int reservoirLevelPercent(float distanceCm) {
  if (distanceCm < 0) return -1;

  float clamped = distanceCm;
  if (clamped > RES_EMPTY_CM) clamped = RES_EMPTY_CM;
  if (clamped < RES_FULL_CM)  clamped = RES_FULL_CM;

  // Sensor is at top:
  // bigger distance = lower water
  // smaller distance = higher water
  float pct = ((RES_EMPTY_CM - clamped) / (RES_EMPTY_CM - RES_FULL_CM)) * 100.0;

  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;

  return (int)(pct + 0.5);
}

String reservoirWarningState(float distanceCm) {
  if (distanceCm < 0) return "NO_READING";
  if (distanceCm <= RES_CRITICAL_CM) return "HIGH_HIGH";
  if (distanceCm <= RES_WARNING_CM)  return "HIGH";
  return "NORMAL";
}

String reservoirBand10(float distanceCm) {
  int pct = reservoirLevelPercent(distanceCm);
  if (pct < 0) return "NO_READING";
  if (pct >= 100) return "100";
  if (pct >= 90) return "90";
  if (pct >= 80) return "80";
  if (pct >= 70) return "70";
  if (pct >= 60) return "60";
  if (pct >= 50) return "50";
  if (pct >= 40) return "40";
  if (pct >= 30) return "30";
  if (pct >= 20) return "20";
  if (pct >= 10) return "10";
  return "0";
}

void printReservoirReport(float d) {
  int pct = reservoirLevelPercent(d);
  String state = reservoirWarningState(d);
  String band = reservoirBand10(d);

  Serial.print("RES_REPORT:");
  Serial.print("RAW_CM=");
  Serial.print(d, 1);
  Serial.print(",LEVEL=");
  Serial.print(pct);
  Serial.print("%");
  Serial.print(",BAND=");
  Serial.print(band);
  Serial.print("%");
  Serial.print(",STATE=");
  Serial.println(state);
}

// =====================================================
// Setup
// =====================================================

void setup() {
  Serial.begin(9600);
  Serial.println("=== Reservoir Ultrasonic Calibration Mode ===");
  Serial.println("Commands:");
  Serial.println("  GET_RES_RAW");
  Serial.println("  GET_RES_STATUS");
  Serial.println("  CHECK_ULTRASONIC_RES");
  Serial.println("  LIVE_RES_ON");
  Serial.println("  LIVE_RES_OFF");
}

// =====================================================
// Loop
// =====================================================

void loop() {
  // -------- Serial Commands --------
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command == "GET_RES_RAW") {
      float d = readUltrasonicResRawCm();
      Serial.print("ULTRASONIC_RES_RAW:");
      Serial.println(d, 1);
    }

    else if (command == "GET_RES_STATUS") {
      float d = readUltrasonicResRawCm();
      printReservoirReport(d);
    }

    else if (command == "CHECK_ULTRASONIC_RES") {
      float d = readUltrasonicResRawCm();

      if (d < 0) {
        Serial.println("CHECK_ULTRASONIC_RES:NO_READING");
      } else {
        String state = reservoirWarningState(d);
        int pct = reservoirLevelPercent(d);

        Serial.print("CHECK_ULTRASONIC_RES:");
        if (state == "NORMAL") {
          Serial.print("OK");
        } else {
          Serial.print(state);
        }

        Serial.print(",RAW_CM=");
        Serial.print(d, 1);
        Serial.print(",LEVEL=");
        Serial.print(pct);
        Serial.println("%");
      }
    }

    else if (command == "LIVE_RES_ON") {
      liveMode = true;
      Serial.println("LIVE_RES_ON_ACK");
    }

    else if (command == "LIVE_RES_OFF") {
      liveMode = false;
      Serial.println("LIVE_RES_OFF_ACK");
    }
  }

  // -------- Live Mode --------
  if (liveMode && millis() - lastLivePrint >= LIVE_INTERVAL_MS) {
    lastLivePrint = millis();
    float d = readUltrasonicResRawCm();
    printReservoirReport(d);
  }
}