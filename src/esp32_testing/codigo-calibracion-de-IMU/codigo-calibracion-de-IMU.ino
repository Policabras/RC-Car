#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

const char* ssid = "INFINITUM7F1E";
const char* password = "XZKjB7bvkt";
const char* mqtt_server = "192.168.1.230";

WiFiClient espClient;
PubSubClient client(espClient);

Adafruit_MPU6050 mpu;

float theta = 0;
float gyroOffsetZ = 0;

unsigned long lastTime = 0;

void setup_wifi() {
  Serial.println("Conectando WiFi...");

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nWiFi conectado");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());
}

void reconnect() {
  while (!client.connected()) {
    Serial.println("Conectando MQTT...");

    if (client.connect("ESP32IMU")) {
      Serial.println("MQTT conectado");
    } else {
      Serial.print("Error MQTT: ");
      Serial.println(client.state());
      delay(2000);
    }
  }
}

void calibrarGyro() {
  Serial.println("Calibrando gyro... no mover sensor");

  float suma = 0;
  const int muestras = 2000;

  for (int i = 0; i < muestras; i++) {
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);

    suma += g.gyro.z;
    delay(2);
  }

  gyroOffsetZ = suma / muestras;

  Serial.print("Offset Z = ");
  Serial.println(gyroOffsetZ, 8);
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("Iniciando I2C...");

  Wire.begin(8, 9);
  Wire.setClock(100000);

  delay(500);

  Serial.println("Iniciando MPU6050...");

  if (!mpu.begin(0x68, &Wire)) {
    Serial.println("MPU6050 no encontrada");
    while (1);
  }

  Serial.println("MPU6050 lista");

  mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
  mpu.setGyroRange(MPU6050_RANGE_250_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

  calibrarGyro();

  setup_wifi();

  client.setServer(mqtt_server, 1883);

  lastTime = millis();
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }

  client.loop();

  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  unsigned long currentTime = millis();
  float dt = (currentTime - lastTime) / 1000.0;
  lastTime = currentTime;

  float gyroZ = g.gyro.z - gyroOffsetZ;

  // zona muerta anti drift
  if (abs(gyroZ) < 0.01) {
    gyroZ = 0;
  }

  theta += gyroZ * dt * 57.2958;

  String payload = "{\"theta\":" + String(theta, 2) + "}";

  bool ok = client.publish("robot/imu", payload.c_str());

  if (ok) {
    Serial.println(payload);
  } else {
    Serial.println("Error envio MQTT");
  }

  delay(50);
}