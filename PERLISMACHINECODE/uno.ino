#include "HX711.h"

#define DOUT  A2
#define CLK   A3
#define BUZZER_PIN 4

HX711 scale;

float calibration_factor = 100463.935;
unsigned long lastBeepTime = 0;
unsigned long lastSendTime = 0;
const unsigned long SEND_INTERVAL = 200; // 200 ms = 5 Hz
bool buzzerState = false;

// Python handshake flag
bool pythonReady = false;
// Serial buffer for commands
String rxBuf = "";

static inline void buzzerOff() { digitalWrite(BUZZER_PIN, HIGH); } // ACTIVE-LOW
static inline void buzzerOn()  { digitalWrite(BUZZER_PIN, LOW);  } // ACTIVE-LOW

void setup() {
  Serial.begin(9600);
  scale.begin(DOUT, CLK);
  scale.set_scale(calibration_factor);
  pinMode(BUZZER_PIN, OUTPUT);
  buzzerOff(); // Default OFF at boot
}

void loop() {

  // -------------------------
  // SERIAL COMMAND HANDLING
  // -------------------------
  while (Serial.available()) {
    char c = (char)Serial.read();
    rxBuf += c;

    if (rxBuf.length() > 80) rxBuf.remove(0, rxBuf.length() - 80);
    
    // Detect PYTHON_READY
    if (!pythonReady && rxBuf.indexOf("PYTHON_READY") >= 0) {
      pythonReady = true;
      Serial.println("PYTHON_OK");
      rxBuf = ""; 
    }

    // TARE command support
    if (c == 't' || c == 'T') {
      Serial.println("TARE_START");
      scale.tare();
      delay(300);
      Serial.println("TARED");
    }

    if (c == '\n' || c == '\r') {
      rxBuf = "";
    }
  }

  float weight = scale.get_units();

  // -------------------------
  // BUZZER LOGIC (9.5kg - 10kg)
  // -------------------------
  if (!pythonReady) {
    buzzerOff();
  } else {
    if (weight >= 10.0) {
      // SOLID ON at 10.0 kg
      buzzerOn();
    }
    else if (weight >= 9.5) {
      // Beep faster as weight moves from 9.5kg to 10.0kg
      float interval = 400.0 - ((weight - 9.5) * 700.0);
      if (interval < 60) interval = 60;

      unsigned long now = millis();
      if (now - lastBeepTime >= interval) {
        buzzerState = !buzzerState;
        if (buzzerState) buzzerOn();
        else buzzerOff();
        lastBeepTime = now;
      }
    }
    else {
      buzzerOff();
    }
  }

  // -------------------------
  // WEIGHT STREAM OUTPUT
  // -------------------------
  if (millis() - lastSendTime >= SEND_INTERVAL) {
    lastSendTime = millis();
    Serial.println(weight, 3);
  }
}