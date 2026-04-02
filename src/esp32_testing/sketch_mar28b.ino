#include <Wire.h>
#include <MPU6050_light.h>

MPU6050 mpu(Wire);

void setup() {
  Serial.begin(115200);
  delay(2000);

  // ESP32-C3 I2C
  Wire.begin(8, 9);

  byte status = mpu.begin();

  if (status != 0) {
    Serial.println("{\"error\":\"mpu_not_detected\"}");
    while (true);
  }

  delay(1000);

  // Calibración inicial (sensor quieto)
  mpu.calcOffsets();

  Serial.println("{\"status\":\"ready\"}");
}

void loop() {
  mpu.update();

  // Ángulo Z en radianes
  float theta = mpu.getAngleZ() * PI / 180.0;

  Serial.print("{\"theta\":");
  Serial.print(theta, 4);
  Serial.println("}");

  delay(100);
}