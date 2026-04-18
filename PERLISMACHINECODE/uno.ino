#include "HX711.h"

#define DOUT A3
#define CLK  A2

HX711 scale;

void setup() {
  Serial.begin(9600);
  scale.begin(DOUT, CLK);   // default gain = 128, channel A
  Serial.println("HX711 raw test starting...");
}

void loop() {
  // Check whether HX711 is responding within 1 second
  if (scale.wait_ready_timeout(1000)) {
    long raw = scale.read();   // raw ADC value, no calibration needed for this test
    Serial.print("HX711 alive | raw = ");
    Serial.println(raw);
  } else {
    Serial.println("HX711 not responding / not ready");
  }

  delay(300);
}