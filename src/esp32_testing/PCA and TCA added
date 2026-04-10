#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

#define SDA_PIN 5
#define SCL_PIN 18

#define TCA_ADDR    0x70
#define TCA_CHANNEL 0

#define PCA_ADDR 0x40
Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(PCA_ADDR);

#define SERVO_CH 2
#define SERVO_MIN    100
#define SERVO_CENTER 310
#define SERVO_MAX    520

void tcaSelect(uint8_t channel) {
  if (channel > 7) return;
  Wire.beginTransmission(TCA_ADDR);
  Wire.write(1 << channel);
  Wire.endTransmission();
}

void setServoRaw(uint16_t pulse) {
  pulse = constrain(pulse, 50, 600);
  tcaSelect(TCA_CHANNEL);
  pca.setPWM(SERVO_CH, 0, pulse);

  Serial.print("Pulso enviado: ");
  Serial.println(pulse);
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000);

  tcaSelect(TCA_CHANNEL);
  delay(20);

  pca.begin();
  pca.setOscillatorFrequency(27000000);
  pca.setPWMFreq(50);

  delay(500);

  Serial.println("Prueba TCA + PCA + Servo lista");
  setServoRaw(SERVO_CENTER);
  delay(1500);
}

void loop() {
  setServoRaw(SERVO_MIN);
  delay(2000);

  setServoRaw(SERVO_CENTER);
  delay(2000);

  setServoRaw(SERVO_MAX);
  delay(2000);

  setServoRaw(SERVO_CENTER);
  delay(2000);
}
