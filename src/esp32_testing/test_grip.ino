#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <ESP32Servo.h>

// ==============================
// UART con Raspberry
// ==============================
HardwareSerial RaspiSerial(2);
static const int RXD2 = 16;
static const int TXD2 = 17;
static const long UART_BAUD = 115200;

// ==============================
// I2C: ESP32 -> TCA9548A -> PCA9685 / AS5600
// ==============================
static const int I2C_SDA = 5;
static const int I2C_SCL = 18;

static const uint8_t TCA_ADDR = 0x70;

// PCA9685 en canal 0 del TCA
static const uint8_t TCA_CHANNEL_PCA = 0;
static const uint8_t PCA_ADDR = 0x40;

// AS5600 en canales 1 y 2 del TCA
static const uint8_t AS5600_ADDR = 0x36;
static const uint8_t ENC_LEFT_CH = 1;
static const uint8_t ENC_RIGHT_CH = 2;

Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(PCA_ADDR);

// ==============================
// BTS7960 PINS - TRACCIÓN PRINCIPAL
// ==============================
const int RPWM_L = 25;
const int LPWM_L = 26;

const int RPWM_R = 12;
const int LPWM_R = 13;

const int REN_L = 32;
const int LEN_L = 33;
const int REN_R = 27;
const int LEN_R = 14;

// ==============================
// BTS7960 PINS - FLIPPERS (1 BTS)
// ==============================
const int FLIPPER_RPWM = 19;
const int FLIPPER_LPWM = 21;
const int FLIPPER_REN  = 22;
const int FLIPPER_LEN  = 23;

// Si el sentido quedó al revés, cambia esto
const bool FLIPPER_INVERTED = true;

// ==============================
// PWM CONFIG
// ==============================
const int PWM_FREQ = 20000;
const int PWM_RES  = 8;

// Tracción principal
const int CH_RPWM_L = 4;
const int CH_LPWM_L = 5;
const int CH_RPWM_R = 6;
const int CH_LPWM_R = 7;

// Flippers
const int CH_FLIPPER_RPWM = 0;
const int CH_FLIPPER_LPWM = 1;

// Escalas
const float DRIVE_PWM_SCALE   = 0.85f;
const float FLIPPER_PWM_SCALE = 0.80f;

// Deadband flippers
const int FLIPPER_DEADBAND = 60;
const int FLIPPER_MAX_CMD  = 1000;

// ==============================
// PCA9685 canales del brazo
// ==============================
static const uint8_t ARM_BASE_CH  = 2;
static const uint8_t ARM_ELBOW_CH = 3;
static const uint8_t ARM_WRIST_CH = 4;

// ==============================
// GRIPPER DIRECTO AL ESP32
// ==============================
static const int ARM_GRIP_PIN = 6;   // cambia este pin si quieres otro
Servo gripServo;

// Para muchos servos normales esto funciona bien
const int SERVO_US_MIN = 500;
const int SERVO_US_MAX = 2400;
const int SERVO_HZ = 50;

// ==============================
// CONFIG GENERAL DE SERVOS DEL BRAZO
// ==============================
const int SERVO_PCA_MIN = 100;
const int SERVO_PCA_MAX = 520;
const float PCA_SERVO_FREQ = 50.0f;

// ==============================
// BRAZO ROBÓTICO
// ==============================
const int ARM_BASE_MIN  = 0;
const int ARM_BASE_MAX  = 180;
const int ARM_BASE_HOME = 90;

const int ARM_ELBOW_MIN  = 0;
const int ARM_ELBOW_MAX  = 180;
const int ARM_ELBOW_HOME = 0;

const int ARM_WRIST_MIN  = 0;
const int ARM_WRIST_MAX  = 180;
const int ARM_WRIST_HOME = 10;

const int ARM_GRIP_MIN   = 0;
const int ARM_GRIP_MAX   = 180;
const int ARM_GRIP_HOME  = 90;

const bool ARM_BASE_INVERTED  = false;
const bool ARM_ELBOW_INVERTED = false;
const bool ARM_WRIST_INVERTED = false;
const bool ARM_GRIP_INVERTED  = false;

const float ARM_BASE_MAX_SPEED_DPS  = 250.0f;
const float ARM_ELBOW_MAX_SPEED_DPS = 250.0f;
const float ARM_WRIST_MAX_SPEED_DPS = 250.0f;
const float ARM_GRIP_MAX_SPEED_DPS  = 300.0f;

// ==============================
// CONTROL
// ==============================
int v_cmd = 0;
int w_cmd = 0;
int f_cmd = 0;

int base_cmd  = 0;
int elbow_cmd = 0;
int wrist_cmd = 0;
int grip_cmd  = 0;

// Posiciones del brazo
float basePos  = ARM_BASE_HOME;
float elbowPos = ARM_ELBOW_HOME;
float wristPos = ARM_WRIST_HOME;
float gripPos  = ARM_GRIP_HOME;

unsigned long lastPacketTime = 0;
unsigned long lastArmUpdate  = 0;
unsigned long lastDebugPrint = 0;

const unsigned long FAILSAFE_MS = 300;
const unsigned long DEBUG_PRINT_MS = 300;

// ==============================
// ENCODERS AS5600
// ==============================
// v = (delta_deg / dt_s) * 0.000498
const float K_VEL_MS_PER_DEGPS = 0.000498f;

float angleLeftDeg = 0.0f;
float angleRightDeg = 0.0f;
float prevAngleLeftDeg = 0.0f;
float prevAngleRightDeg = 0.0f;

float velLeftMS = 0.0f;
float velRightMS = 0.0f;

uint16_t rawLeft = 0;
uint16_t rawRight = 0;

bool leftEncoderOnline  = false;
bool rightEncoderOnline = false;

unsigned long lastEncoderUpdate = 0;
bool encodersInitialized = false;

// ==============================
// DEBUG FLIPPERS
// ==============================
int dbg_flipper_cmd_raw = 0;
int dbg_flipper_cmd_applied = 0;
int dbg_flipper_pwm_r = 0;
int dbg_flipper_pwm_l = 0;
const char* dbg_flipper_dir = "STOP";

// ==============================
// Helpers
// ==============================
int clampInt(int x, int lo, int hi) {
  if (x < lo) return lo;
  if (x > hi) return hi;
  return x;
}

float clampFloat(float x, float lo, float hi) {
  if (x < lo) return lo;
  if (x > hi) return hi;
  return x;
}

int map1000To255(int x) {
  x = abs(x);
  x = clampInt(x, 0, 1000);
  return map(x, 0, 1000, 0, 255);
}

int map1000To255Scaled(int x, float scale) {
  int pwm = map1000To255(x);
  pwm = (int)(pwm * scale);
  return clampInt(pwm, 0, 255);
}

uint16_t angleToPCA(int angle) {
  angle = clampInt(angle, 0, 180);
  return (uint16_t)map(angle, 0, 180, SERVO_PCA_MIN, SERVO_PCA_MAX);
}

int applyInvert(int angle, bool inverted) {
  angle = clampInt(angle, 0, 180);
  return inverted ? (180 - angle) : angle;
}

void tcaSelect(uint8_t channel) {
  if (channel > 7) return;
  Wire.beginTransmission(TCA_ADDR);
  Wire.write(1 << channel);
  Wire.endTransmission();
}

// ==============================
// DEBUG PRINT FLIPPERS
// ==============================
void printFlipperDebug() {
  Serial.println("----- DEBUG FLIPPERS -----");

  Serial.print("f_cmd raw UART: ");
  Serial.println(dbg_flipper_cmd_raw);

  Serial.print("f_cmd aplicado: ");
  Serial.println(dbg_flipper_cmd_applied);

  Serial.print("Direccion: ");
  Serial.println(dbg_flipper_dir);

  Serial.print("RPWM pin GPIO: ");
  Serial.print(FLIPPER_RPWM);
  Serial.print(" | duty ledcRead: ");
  Serial.print(ledcRead(CH_FLIPPER_RPWM));
  Serial.print(" | duty esperado: ");
  Serial.print(dbg_flipper_pwm_r);
  Serial.print(" | digitalRead instantaneo: ");
  Serial.println(digitalRead(FLIPPER_RPWM));

  Serial.print("LPWM pin GPIO: ");
  Serial.print(FLIPPER_LPWM);
  Serial.print(" | duty ledcRead: ");
  Serial.print(ledcRead(CH_FLIPPER_LPWM));
  Serial.print(" | duty esperado: ");
  Serial.print(dbg_flipper_pwm_l);
  Serial.print(" | digitalRead instantaneo: ");
  Serial.println(digitalRead(FLIPPER_LPWM));

  Serial.print("REN pin GPIO ");
  Serial.print(FLIPPER_REN);
  Serial.print(" = ");
  Serial.println(digitalRead(FLIPPER_REN));

  Serial.print("LEN pin GPIO ");
  Serial.print(FLIPPER_LEN);
  Serial.print(" = ");
  Serial.println(digitalRead(FLIPPER_LEN));

  Serial.println("--------------------------");
}

// ==============================
// DEBUG PRINT ENCODERS
// ==============================
void printEncoderDebug() {
  Serial.println("----- DEBUG ENCODERS -----");

  Serial.print("LEFT online: ");
  Serial.println(leftEncoderOnline ? "SI" : "NO");
  Serial.print("LEFT raw: ");
  Serial.println(rawLeft);
  Serial.print("LEFT deg: ");
  Serial.println(angleLeftDeg, 2);
  Serial.print("LEFT vel (m/s): ");
  Serial.println(velLeftMS, 4);

  Serial.println();

  Serial.print("RIGHT online: ");
  Serial.println(rightEncoderOnline ? "SI" : "NO");
  Serial.print("RIGHT raw: ");
  Serial.println(rawRight);
  Serial.print("RIGHT deg: ");
  Serial.println(angleRightDeg, 2);
  Serial.print("RIGHT vel (m/s): ");
  Serial.println(velRightMS, 4);

  Serial.println("--------------------------");
}

// ==============================
// Motores BTS
// ==============================
void setMotorBTS(int pwmForwardChannel, int pwmBackwardChannel, int value, float scale = 1.0f) {
  value = clampInt(value, -1000, 1000);
  int pwm = map1000To255Scaled(value, scale);

  if (value > 0) {
    ledcWrite(pwmForwardChannel, pwm);
    ledcWrite(pwmBackwardChannel, 0);
  } else if (value < 0) {
    ledcWrite(pwmForwardChannel, 0);
    ledcWrite(pwmBackwardChannel, pwm);
  } else {
    ledcWrite(pwmForwardChannel, 0);
    ledcWrite(pwmBackwardChannel, 0);
  }
}

void stopDriveMotors() {
  ledcWrite(CH_RPWM_L, 0);
  ledcWrite(CH_LPWM_L, 0);
  ledcWrite(CH_RPWM_R, 0);
  ledcWrite(CH_LPWM_R, 0);
}

// ==============================
// FLIPPERS CON 1 BTS
// ==============================
void writeFlippersMotor(int cmd) {
  dbg_flipper_cmd_raw = cmd;

  cmd = clampInt(cmd, -FLIPPER_MAX_CMD, FLIPPER_MAX_CMD);

  if (FLIPPER_INVERTED) cmd = -cmd;
  if (abs(cmd) < FLIPPER_DEADBAND) cmd = 0;

  dbg_flipper_cmd_applied = cmd;

  if (cmd > 0) {
    int pwm = map1000To255Scaled(cmd, FLIPPER_PWM_SCALE);
    ledcWrite(CH_FLIPPER_RPWM, pwm);
    ledcWrite(CH_FLIPPER_LPWM, 0);

    dbg_flipper_pwm_r = pwm;
    dbg_flipper_pwm_l = 0;
    dbg_flipper_dir = "RPWM activo";
  } else if (cmd < 0) {
    int pwm = map1000To255Scaled(cmd, FLIPPER_PWM_SCALE);
    ledcWrite(CH_FLIPPER_RPWM, 0);
    ledcWrite(CH_FLIPPER_LPWM, pwm);

    dbg_flipper_pwm_r = 0;
    dbg_flipper_pwm_l = pwm;
    dbg_flipper_dir = "LPWM activo";
  } else {
    ledcWrite(CH_FLIPPER_RPWM, 0);
    ledcWrite(CH_FLIPPER_LPWM, 0);

    dbg_flipper_pwm_r = 0;
    dbg_flipper_pwm_l = 0;
    dbg_flipper_dir = "STOP";
  }
}

void stopFlippers() {
  ledcWrite(CH_FLIPPER_RPWM, 0);
  ledcWrite(CH_FLIPPER_LPWM, 0);

  dbg_flipper_cmd_applied = 0;
  dbg_flipper_pwm_r = 0;
  dbg_flipper_pwm_l = 0;
  dbg_flipper_dir = "STOP";
}

// ==============================
// PCA9685 / BRAZO
// ==============================
void writeServoPCA(uint8_t channel, int angle, bool inverted = false) {
  int finalAngle = applyInvert(angle, inverted);
  uint16_t pulse = angleToPCA(finalAngle);

  tcaSelect(TCA_CHANNEL_PCA);
  pca.setPWM(channel, 0, pulse);
}

void writeGripServoDirect(int angle, bool inverted = false) {
  int finalAngle = applyInvert(angle, inverted);
  finalAngle = clampInt(finalAngle, 0, 180);
  gripServo.write(finalAngle);
}

void writeArm() {
  writeServoPCA(ARM_BASE_CH,  (int)basePos,  ARM_BASE_INVERTED);
  writeServoPCA(ARM_ELBOW_CH, (int)elbowPos, ARM_ELBOW_INVERTED);
  writeServoPCA(ARM_WRIST_CH, (int)wristPos, ARM_WRIST_INVERTED);

  // Gripper directo al ESP32
  writeGripServoDirect((int)gripPos, ARM_GRIP_INVERTED);
}

void updateArmJoint(float &pos, int cmd, float maxSpeedDps, int minAngle, int maxAngle, float dt) {
  if (abs(cmd) < 60) cmd = 0;

  float speedDps = (cmd / 1000.0f) * maxSpeedDps;
  pos += speedDps * dt;
  pos = clampFloat(pos, minAngle, maxAngle);
}

void setupPCA() {
  tcaSelect(TCA_CHANNEL_PCA);
  pca.begin();
  pca.setOscillatorFrequency(27000000);
  pca.setPWMFreq(PCA_SERVO_FREQ);

  delay(50);
}

void setupGripServo() {
  ESP32PWM::allocateTimer(0);
  gripServo.setPeriodHertz(SERVO_HZ);
  gripServo.attach(ARM_GRIP_PIN, SERVO_US_MIN, SERVO_US_MAX);

  delay(50);
}

void updateArm() {
  unsigned long now = millis();

  if (lastArmUpdate == 0) {
    lastArmUpdate = now;
    return;
  }

  float dt = (now - lastArmUpdate) / 1000.0f;
  if (dt <= 0.0f) return;

  lastArmUpdate = now;

  updateArmJoint(basePos,  base_cmd,  ARM_BASE_MAX_SPEED_DPS,  ARM_BASE_MIN,  ARM_BASE_MAX,  dt);
  updateArmJoint(elbowPos, elbow_cmd, ARM_ELBOW_MAX_SPEED_DPS, ARM_ELBOW_MIN, ARM_ELBOW_MAX, dt);
  updateArmJoint(wristPos, wrist_cmd, ARM_WRIST_MAX_SPEED_DPS, ARM_WRIST_MIN, ARM_WRIST_MAX, dt);
  updateArmJoint(gripPos,  grip_cmd,  ARM_GRIP_MAX_SPEED_DPS,  ARM_GRIP_MIN,  ARM_GRIP_MAX,  dt);

  writeArm();
}

// ==============================
// AS5600
// ==============================
bool readAS5600Raw(uint8_t tcaChannel, uint16_t &rawOut) {
  rawOut = 0;

  tcaSelect(tcaChannel);

  Wire.beginTransmission(AS5600_ADDR);
  Wire.write(0x0C);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }

  uint8_t requested = Wire.requestFrom((int)AS5600_ADDR, 2);
  if (requested != 2 || Wire.available() < 2) {
    return false;
  }

  uint16_t highByte = Wire.read();
  uint16_t lowByte  = Wire.read();

  rawOut = ((highByte << 8) | lowByte) & 0x0FFF;
  return true;
}

float rawToDegrees(uint16_t raw) {
  return (raw * 360.0f) / 4096.0f;
}

float computeLinearVelocityMS(float currentDeg, float previousDeg, float dtSec) {
  float delta = currentDeg - previousDeg;

  if (delta > 180.0f) delta -= 360.0f;
  if (delta < -180.0f) delta += 360.0f;

  return -(delta / dtSec) * K_VEL_MS_PER_DEGPS;
}

void setupEncoders() {
  leftEncoderOnline  = readAS5600Raw(ENC_LEFT_CH, rawLeft);
  rightEncoderOnline = readAS5600Raw(ENC_RIGHT_CH, rawRight);

  if (leftEncoderOnline) {
    prevAngleLeftDeg = rawToDegrees(rawLeft);
    angleLeftDeg = prevAngleLeftDeg;
  } else {
    prevAngleLeftDeg = 0.0f;
    angleLeftDeg = 0.0f;
  }

  if (rightEncoderOnline) {
    prevAngleRightDeg = rawToDegrees(rawRight);
    angleRightDeg = prevAngleRightDeg;
  } else {
    prevAngleRightDeg = 0.0f;
    angleRightDeg = 0.0f;
  }

  velLeftMS = 0.0f;
  velRightMS = 0.0f;

  lastEncoderUpdate = millis();
  encodersInitialized = true;
}

void updateEncoders() {
  if (!encodersInitialized) return;

  unsigned long now = millis();
  float dtSec = (now - lastEncoderUpdate) / 1000.0f;

  if (dtSec <= 0.0f) return;

  lastEncoderUpdate = now;

  uint16_t newRawLeft = 0;
  uint16_t newRawRight = 0;

  leftEncoderOnline  = readAS5600Raw(ENC_LEFT_CH, newRawLeft);
  rightEncoderOnline = readAS5600Raw(ENC_RIGHT_CH, newRawRight);

  if (leftEncoderOnline) {
    rawLeft = newRawLeft;
    angleLeftDeg = rawToDegrees(rawLeft);
    velLeftMS = computeLinearVelocityMS(angleLeftDeg, prevAngleLeftDeg, dtSec);
    prevAngleLeftDeg = angleLeftDeg;
  } else {
    velLeftMS = 0.0f;
  }

  if (rightEncoderOnline) {
    rawRight = newRawRight;
    angleRightDeg = rawToDegrees(rawRight);
    velRightMS = computeLinearVelocityMS(angleRightDeg, prevAngleRightDeg, dtSec);
    prevAngleRightDeg = angleRightDeg;
  } else {
    velRightMS = 0.0f;
  }
}

// ==============================
// Parsear paquetes tipo
// <v,w,f,base,elbow,wrist,grip>
// ==============================
bool readPacket(int &v, int &w, int &f, int &base, int &elbow, int &wrist, int &grip) {
  static String buffer = "";

  while (RaspiSerial.available()) {
    char c = (char)RaspiSerial.read();

    if (c == '<') {
      buffer = "";
    } else if (c == '>') {
      int values[7] = {0};
      int idx = 0;
      int start = 0;

      for (int i = 0; i <= buffer.length(); i++) {
        if (i == buffer.length() || buffer[i] == ',') {
          if (idx < 7) {
            values[idx++] = buffer.substring(start, i).toInt();
          }
          start = i + 1;
        }
      }

      if (idx == 7) {
        v     = values[0];
        w     = values[1];
        f     = values[2];
        base  = values[3];
        elbow = values[4];
        wrist = values[5];
        grip  = values[6];
        return true;
      }
    } else {
      buffer += c;
    }
  }

  return false;
}

// ==============================
// Setup PWM
// ==============================
void setupPWM() {
  ledcSetup(CH_RPWM_L, PWM_FREQ, PWM_RES);
  ledcSetup(CH_LPWM_L, PWM_FREQ, PWM_RES);
  ledcSetup(CH_RPWM_R, PWM_FREQ, PWM_RES);
  ledcSetup(CH_LPWM_R, PWM_FREQ, PWM_RES);

  ledcAttachPin(RPWM_L, CH_RPWM_L);
  ledcAttachPin(LPWM_L, CH_LPWM_L);
  ledcAttachPin(RPWM_R, CH_RPWM_R);
  ledcAttachPin(LPWM_R, CH_LPWM_R);

  ledcSetup(CH_FLIPPER_RPWM, PWM_FREQ, PWM_RES);
  ledcSetup(CH_FLIPPER_LPWM, PWM_FREQ, PWM_RES);

  ledcAttachPin(FLIPPER_RPWM, CH_FLIPPER_RPWM);
  ledcAttachPin(FLIPPER_LPWM, CH_FLIPPER_LPWM);
}

// ==============================
// SETUP
// ==============================
void setup() {
  Serial.begin(115200);
  Serial.println("Monitor serial inicializado");

  RaspiSerial.begin(UART_BAUD, SERIAL_8N1, RXD2, TXD2);

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);

  setupPWM();

  stopDriveMotors();
  stopFlippers();

  pinMode(REN_L, OUTPUT); digitalWrite(REN_L, HIGH);
  pinMode(LEN_L, OUTPUT); digitalWrite(LEN_L, HIGH);
  pinMode(REN_R, OUTPUT); digitalWrite(REN_R, HIGH);
  pinMode(LEN_R, OUTPUT); digitalWrite(LEN_R, HIGH);

  pinMode(FLIPPER_REN, OUTPUT); digitalWrite(FLIPPER_REN, HIGH);
  pinMode(FLIPPER_LEN, OUTPUT); digitalWrite(FLIPPER_LEN, HIGH);

  setupPCA();
  setupGripServo();
  setupEncoders();

  basePos  = ARM_BASE_HOME;
  elbowPos = ARM_ELBOW_HOME;
  wristPos = ARM_WRIST_HOME;
  gripPos  = ARM_GRIP_HOME;

  writeArm();

  lastPacketTime = millis();
  lastArmUpdate  = millis();
  lastDebugPrint = millis();

  Serial.println("ESP32 listo. Esperando paquetes UART...");
  printFlipperDebug();
  printEncoderDebug();
}

// ==============================
// LOOP
// ==============================
void loop() {
  int newV, newW, newF, newBase, newElbow, newWrist, newGrip;

  if (readPacket(newV, newW, newF, newBase, newElbow, newWrist, newGrip)) {
    v_cmd = clampInt(-newW, -1000, 1000);
    w_cmd = clampInt(newV, -1000, 1000);
    f_cmd = clampInt(newF, -1000, 1000);

    base_cmd  = clampInt(newBase, -1000, 1000);
    elbow_cmd = clampInt(newElbow, -1000, 1000);
    wrist_cmd = clampInt(newWrist, -1000, 1000);
    grip_cmd  = clampInt(newGrip, -1000, 1000);

    lastPacketTime = millis();

    int left  = clampInt(v_cmd - w_cmd, -1000, 1000);
    int right = clampInt(v_cmd + w_cmd, -1000, 1000);

    setMotorBTS(CH_RPWM_L, CH_LPWM_L, left,  DRIVE_PWM_SCALE);
    setMotorBTS(CH_RPWM_R, CH_LPWM_R, right, DRIVE_PWM_SCALE);

    writeFlippersMotor(f_cmd);

    Serial.print("RAW v=");
    Serial.print(newV);
    Serial.print(" w=");
    Serial.print(newW);
    Serial.print(" f=");
    Serial.print(newF);
    Serial.print(" base=");
    Serial.print(newBase);
    Serial.print(" elbow=");
    Serial.print(newElbow);
    Serial.print(" wrist=");
    Serial.print(newWrist);
    Serial.print(" grip=");
    Serial.println(newGrip);
  }

  updateArm();
  updateEncoders();

  if (millis() - lastPacketTime > FAILSAFE_MS) {
    stopDriveMotors();
    stopFlippers();

    f_cmd = 0;
    base_cmd = 0;
    elbow_cmd = 0;
    wrist_cmd = 0;
    grip_cmd = 0;
  }

  if (millis() - lastDebugPrint >= DEBUG_PRINT_MS) {
    lastDebugPrint = millis();
    printFlipperDebug();
    printEncoderDebug();
  }

  delay(2);
}
