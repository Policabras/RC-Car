#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// =====================================================
// UART principal con Raspberry / pipeline MQTT
// IMPORTANTE:
// - Este Serial se usa para RECIBIR comandos y ENVIAR telemetría.
// - NO metas Serial.print de debug fuera de sendTelemetry().
// =====================================================
static const long SERIAL_BAUD = 115200;

// =====================================================
// OPCIONES
// =====================================================
// false = mantiene el mapeo viejo que ya funcionaba:
//         v_cmd = newV
//         w_cmd = newW
// true  = usa el mapeo cruzado del otro código:
//         v_cmd = -newW
//         w_cmd = newV
static const bool USE_CROSSED_DRIVE_MAPPING = true;

// Escala PWM de tracción y flippers
static const float DRIVE_PWM_SCALE   = 1.00f;
static const float FLIPPER_PWM_SCALE = 0.80f;

// =====================================================
// I2C: ESP32 -> TCA9548A -> PCA9685 / AS5600
// =====================================================
static const int I2C_SDA = 5;
static const int I2C_SCL = 18;

static const uint8_t TCA_ADDR    = 0x70;
static const uint8_t TCA_CHANNEL = 0;   // PCA9685
static const uint8_t PCA_ADDR    = 0x40;

// AS5600 en canales 1 y 2 del TCA
static const uint8_t AS5600_ADDR  = 0x36;
static const uint8_t ENC_LEFT_CH  = 1;
static const uint8_t ENC_RIGHT_CH = 2;

Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(PCA_ADDR);

// =====================================================
// BTS7960 PINS - TRACCIÓN PRINCIPAL
// =====================================================
// Motor izquierdo
const int RPWM_L = 25;
const int LPWM_L = 26;

// Motor derecho
const int RPWM_R = 12;
const int LPWM_R = 13;

// Enables por software
const int REN_L = 32;
const int LEN_L = 33;
const int REN_R = 27;
const int LEN_R = 14;

// =====================================================
// BTS7960 PINS - FLIPPERS (1 BTS)
// =====================================================
const int FLIPPER_RPWM = 19;
const int FLIPPER_LPWM = 21;
const int FLIPPER_REN  = 22;
const int FLIPPER_LEN  = 23;

// Si el sentido quedó al revés, cambia esto
const bool FLIPPER_INVERTED = true;

// =====================================================
// PWM CONFIG
// =====================================================
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

// =====================================================
// CONTROL GENERAL
// =====================================================
int v_cmd = 0;
int w_cmd = 0;
int f_cmd = 0;

int base_cmd  = 0;
int elbow_cmd = 0;
int wrist_cmd = 0;
int grip_cmd  = 0;

unsigned long lastPacketTime = 0;
const unsigned long FAILSAFE_MS = 300;

// =====================================================
// PID DE VELOCIDAD + ENCODERS AS5600
// =====================================================
const unsigned long DRIVE_CONTROL_PERIOD_MS = 20;
const int DRIVE_CMD_DEADBAND = 20;

// Ajusta esto a la velocidad máxima real de tu rueda
// cuando el comando es 1000.
const float MAX_WHEEL_RPM = 150.0f;

// Si una rueda reporta signo al revés, cambia a true.
const bool LEFT_ENCODER_INVERTED  = false;
const bool RIGHT_ENCODER_INVERTED = false;

// Filtro simple para estabilizar RPM medida.
const float SPEED_FILTER_ALPHA = 0.35f;

// Compensación mínima para vencer fricción estática.
const int DRIVE_MIN_EFFECTIVE_CMD = 180;

struct PIDController {
  float kp;
  float ki;
  float kd;

  float prevError;
  float integral;

  float outMin;
  float outMax;
};

struct AS5600WheelState {
  bool initialized;
  uint16_t raw;
  float angleDeg;
  float speedRpm;
};

// PID más conservador para arrancar sin matar el movimiento
PIDController pidLeft  = {2.0f, 5.0f, 0.02f, 0.0f, 0.0f, -300.0f, 300.0f};
PIDController pidRight = {2.0f, 5.0f, 0.02f, 0.0f, 0.0f, -300.0f, 300.0f};

AS5600WheelState encLeft  = {false, 0, 0.0f, 0.0f};
AS5600WheelState encRight = {false, 0, 0.0f, 0.0f};

float leftTargetRpm  = 0.0f;
float rightTargetRpm = 0.0f;

unsigned long lastDriveControlMs = 0;

// =====================================================
// FLIPPER - TELEMETRÍA COMPATIBLE
// Nota:
// El flipper ahora es motor DC con BTS, no servo.
// No hay posición real sin encoder.
// Para no romper tu JSON viejo, mantenemos una
// "posición virtual" estimada solo para telemetría.
// =====================================================
const int FLIPPER_DEADBAND = 60;
const int FLIPPER_MAX_CMD  = 1000;

const int FLIPPER_MIN  = 0;
const int FLIPPER_MAX  = 180;
const int FLIPPER_HOME = 180;
const float FLIPPER_MAX_SPEED_DPS = 55.0f;

float flipperPos = FLIPPER_HOME;
unsigned long lastFlipperUpdate = 0;

// =====================================================
// PCA9685 canales del brazo
// =====================================================
static const uint8_t ARM_BASE_CH  = 2;
static const uint8_t ARM_ELBOW_CH = 3;
static const uint8_t ARM_WRIST_CH = 4;
static const uint8_t ARM_GRIP_CH  = 5;

// =====================================================
// CONFIG GENERAL DE SERVOS DEL BRAZO
// =====================================================
const int SERVO_PCA_MIN = 100;
const int SERVO_PCA_MAX = 520;
const float PCA_SERVO_FREQ = 50.0f;

// =====================================================
// BRAZO ROBÓTICO
// =====================================================
// Base
const int ARM_BASE_MIN  = 0;
const int ARM_BASE_MAX  = 180;
const int ARM_BASE_HOME = 90;

// Codo
const int ARM_ELBOW_MIN  = 0;
const int ARM_ELBOW_MAX  = 180;
const int ARM_ELBOW_HOME = 90;

// Muñeca
const int ARM_WRIST_MIN  = 0;
const int ARM_WRIST_MAX  = 180;
const int ARM_WRIST_HOME = 90;

// Garra
const int ARM_GRIP_MIN   = 0;
const int ARM_GRIP_MAX   = 180;
const int ARM_GRIP_HOME  = 90;

// Inversiones
const bool ARM_BASE_INVERTED  = false;
const bool ARM_ELBOW_INVERTED = false;
const bool ARM_WRIST_INVERTED = false;
const bool ARM_GRIP_INVERTED  = false;

// Velocidades máximas
const float ARM_BASE_MAX_SPEED_DPS  = 250.0f;
const float ARM_ELBOW_MAX_SPEED_DPS = 250.0f;
const float ARM_WRIST_MAX_SPEED_DPS = 250.0f;
const float ARM_GRIP_MAX_SPEED_DPS  = 300.0f;

// Posiciones
float basePos  = ARM_BASE_HOME;
float elbowPos = ARM_ELBOW_HOME;
float wristPos = ARM_WRIST_HOME;
float gripPos  = ARM_GRIP_HOME;

// Timing
unsigned long lastArmUpdate = 0;

// =====================================================
// TELEMETRÍA
// =====================================================
const char* DEVICE_ID = "pi_robot_01";
const char* STREAM_NAME = "actuators";
const unsigned long TELEMETRY_PERIOD_MS = 100;
unsigned long lastTelemetryMs = 0;

// =====================================================
// Helpers
// =====================================================
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

void tcaSelect(uint8_t channel) {
  if (channel > 7) return;
  Wire.beginTransmission(TCA_ADDR);
  Wire.write(1 << channel);
  Wire.endTransmission();
}

int applyInvert(int angle, bool inverted) {
  angle = clampInt(angle, 0, 180);
  return inverted ? (180 - angle) : angle;
}

int applyDriveMinCommand(int cmd) {
  cmd = clampInt(cmd, -1000, 1000);

  if (cmd == 0) return 0;

  int sign = (cmd > 0) ? 1 : -1;
  int mag = abs(cmd);

  if (mag < DRIVE_MIN_EFFECTIVE_CMD) {
    mag = DRIVE_MIN_EFFECTIVE_CMD;
  }

  return sign * mag;
}

// =====================================================
// Motores BTS
// =====================================================
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

// =====================================================
// AS5600
// =====================================================
bool readAS5600Raw(uint8_t tcaChannel, uint16_t &rawAngle) {
  tcaSelect(tcaChannel);

  Wire.beginTransmission(AS5600_ADDR);
  Wire.write(0x0C);  // RAW ANGLE HIGH
  if (Wire.endTransmission(false) != 0) {
    return false;
  }

  uint8_t n = Wire.requestFrom((int)AS5600_ADDR, 2);
  if (n != 2) {
    return false;
  }

  uint8_t highByte = Wire.read();
  uint8_t lowByte  = Wire.read();

  rawAngle = (((uint16_t)highByte << 8) | lowByte) & 0x0FFF;
  return true;
}

float rawToDegrees(uint16_t raw) {
  return (raw * 360.0f) / 4096.0f;
}

bool initWheelEncoder(AS5600WheelState &enc, uint8_t channel) {
  uint16_t raw;
  if (!readAS5600Raw(channel, raw)) {
    return false;
  }

  enc.raw = raw;
  enc.angleDeg = rawToDegrees(raw);
  enc.speedRpm = 0.0f;
  enc.initialized = true;
  return true;
}

bool updateWheelSpeedFromAS5600(
  AS5600WheelState &enc,
  uint8_t channel,
  bool inverted,
  float dt
) {
  if (dt <= 0.0f) return false;

  uint16_t raw;
  if (!readAS5600Raw(channel, raw)) {
    return false;
  }

  float angleDeg = rawToDegrees(raw);

  if (!enc.initialized) {
    enc.raw = raw;
    enc.angleDeg = angleDeg;
    enc.speedRpm = 0.0f;
    enc.initialized = true;
    return true;
  }

  float deltaDeg = angleDeg - enc.angleDeg;

  // Manejo de wrap 0°/360°
  if (deltaDeg > 180.0f) {
    deltaDeg -= 360.0f;
  } else if (deltaDeg < -180.0f) {
    deltaDeg += 360.0f;
  }

  if (inverted) {
    deltaDeg = -deltaDeg;
  }

  float measuredRpm = (deltaDeg / 360.0f) * (60.0f / dt);

  enc.speedRpm = (SPEED_FILTER_ALPHA * measuredRpm) +
                 ((1.0f - SPEED_FILTER_ALPHA) * enc.speedRpm);

  enc.raw = raw;
  enc.angleDeg = angleDeg;

  return true;
}

// =====================================================
// PID
// =====================================================
void resetPID(PIDController &pid) {
  pid.prevError = 0.0f;
  pid.integral = 0.0f;
}

void resetDrivePIDState() {
  resetPID(pidLeft);
  resetPID(pidRight);

  leftTargetRpm  = 0.0f;
  rightTargetRpm = 0.0f;

  encLeft.speedRpm  = 0.0f;
  encRight.speedRpm = 0.0f;
}

float computePID(PIDController &pid, float setpoint, float measurement, float dt) {
  float error = setpoint - measurement;

  pid.integral += error * dt;

  // Anti-windup simple
  if (pid.ki > 0.00001f) {
    float integralLimit = pid.outMax / pid.ki;
    pid.integral = clampFloat(pid.integral, -integralLimit, integralLimit);
  }

  float derivative = 0.0f;
  if (dt > 0.0f) {
    derivative = (error - pid.prevError) / dt;
  }

  float output =
      (pid.kp * error) +
      (pid.ki * pid.integral) +
      (pid.kd * derivative);

  output = clampFloat(output, pid.outMin, pid.outMax);
  pid.prevError = error;

  return output;
}

void updateDriveControl() {
  unsigned long now = millis();

  if (lastDriveControlMs == 0) {
    lastDriveControlMs = now;
    return;
  }

  unsigned long elapsedMs = now - lastDriveControlMs;
  if (elapsedMs < DRIVE_CONTROL_PERIOD_MS) {
    return;
  }

  lastDriveControlMs = now;
  float dt = elapsedMs / 1000.0f;

  // ===============================
  // Base original que ya funcionaba
  // ===============================
  int leftBase  = clampInt(v_cmd - w_cmd, -1000, 1000);
  int rightBase = clampInt(v_cmd + w_cmd, -1000, 1000);

  if (abs(leftBase) < DRIVE_CMD_DEADBAND)  leftBase = 0;
  if (abs(rightBase) < DRIVE_CMD_DEADBAND) rightBase = 0;

  // Target de velocidad estimado
  leftTargetRpm  = (leftBase  / 1000.0f) * MAX_WHEEL_RPM;
  rightTargetRpm = (rightBase / 1000.0f) * MAX_WHEEL_RPM;

  bool leftOk  = updateWheelSpeedFromAS5600(encLeft, ENC_LEFT_CH, LEFT_ENCODER_INVERTED, dt);
  bool rightOk = updateWheelSpeedFromAS5600(encRight, ENC_RIGHT_CH, RIGHT_ENCODER_INVERTED, dt);

  // Si falla encoder, vuelve al modo original open-loop
  if (!leftOk || !rightOk) {
    setMotorBTS(CH_RPWM_L, CH_LPWM_L, leftBase, DRIVE_PWM_SCALE);
    setMotorBTS(CH_RPWM_R, CH_LPWM_R, rightBase, DRIVE_PWM_SCALE);
    return;
  }

  int leftCorrection = 0;
  int rightCorrection = 0;

  if (leftBase == 0) {
    resetPID(pidLeft);
  } else {
    leftCorrection = (int)computePID(pidLeft, leftTargetRpm, encLeft.speedRpm, dt);
  }

  if (rightBase == 0) {
    resetPID(pidRight);
  } else {
    rightCorrection = (int)computePID(pidRight, rightTargetRpm, encRight.speedRpm, dt);
  }

  // Feedforward + corrección PID
  int leftOutput  = clampInt(leftBase  + leftCorrection, -1000, 1000);
  int rightOutput = clampInt(rightBase + rightCorrection, -1000, 1000);

  // Compensación de fricción estática
  leftOutput  = applyDriveMinCommand(leftOutput);
  rightOutput = applyDriveMinCommand(rightOutput);

  setMotorBTS(CH_RPWM_L, CH_LPWM_L, leftOutput, DRIVE_PWM_SCALE);
  setMotorBTS(CH_RPWM_R, CH_LPWM_R, rightOutput, DRIVE_PWM_SCALE);
}

// =====================================================
// FLIPPERS CON BTS
// =====================================================
void writeFlippersMotor(int cmd) {
  cmd = clampInt(cmd, -FLIPPER_MAX_CMD, FLIPPER_MAX_CMD);

  if (FLIPPER_INVERTED) cmd = -cmd;
  if (abs(cmd) < FLIPPER_DEADBAND) cmd = 0;

  if (cmd > 0) {
    int pwm = map1000To255Scaled(cmd, FLIPPER_PWM_SCALE);
    ledcWrite(CH_FLIPPER_RPWM, pwm);
    ledcWrite(CH_FLIPPER_LPWM, 0);
  } else if (cmd < 0) {
    int pwm = map1000To255Scaled(cmd, FLIPPER_PWM_SCALE);
    ledcWrite(CH_FLIPPER_RPWM, 0);
    ledcWrite(CH_FLIPPER_LPWM, pwm);
  } else {
    ledcWrite(CH_FLIPPER_RPWM, 0);
    ledcWrite(CH_FLIPPER_LPWM, 0);
  }
}

void stopFlippers() {
  ledcWrite(CH_FLIPPER_RPWM, 0);
  ledcWrite(CH_FLIPPER_LPWM, 0);
}

// =====================================================
// Estimación virtual de posición de flipper
// SOLO para mantener compatibilidad en telemetría
// =====================================================
void updateFlipperTelemetryEstimate() {
  unsigned long now = millis();

  if (lastFlipperUpdate == 0) {
    lastFlipperUpdate = now;
    return;
  }

  float dt = (now - lastFlipperUpdate) / 1000.0f;
  if (dt <= 0.0f) return;

  lastFlipperUpdate = now;

  int cmd = f_cmd;
  if (abs(cmd) < FLIPPER_DEADBAND) cmd = 0;

  float speedDps = (cmd / 1000.0f) * FLIPPER_MAX_SPEED_DPS;
  flipperPos += speedDps * dt;
  flipperPos = clampFloat(flipperPos, FLIPPER_MIN, FLIPPER_MAX);
}

// =====================================================
// Escritura PCA9685
// =====================================================
void writeServoPCA(uint8_t channel, int angle, bool inverted = false) {
  int finalAngle = applyInvert(angle, inverted);
  uint16_t pulse = angleToPCA(finalAngle);

  tcaSelect(TCA_CHANNEL);
  pca.setPWM(channel, 0, pulse);
}

// =====================================================
// BRAZO ROBÓTICO
// =====================================================
void writeArm() {
  writeServoPCA(ARM_BASE_CH,  (int)basePos,  ARM_BASE_INVERTED);
  writeServoPCA(ARM_ELBOW_CH, (int)elbowPos, ARM_ELBOW_INVERTED);
  writeServoPCA(ARM_WRIST_CH, (int)wristPos, ARM_WRIST_INVERTED);
  writeServoPCA(ARM_GRIP_CH,  (int)gripPos,  ARM_GRIP_INVERTED);
}

void updateArmJoint(float &pos, int cmd, float maxSpeedDps, int minAngle, int maxAngle, float dt) {
  if (abs(cmd) < 60) cmd = 0;

  float speedDps = (cmd / 1000.0f) * maxSpeedDps;
  pos += speedDps * dt;
  pos = clampFloat(pos, minAngle, maxAngle);
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

// =====================================================
// Parsear paquetes tipo
// <v,w,f,base,elbow,wrist,grip>
// leyendo desde Serial
// =====================================================
bool readPacket(int &v, int &w, int &f, int &base, int &elbow, int &wrist, int &grip) {
  static String buffer = "";

  while (Serial.available()) {
    char c = (char)Serial.read();

    if (c == '<') {
      buffer = "";
    }
    else if (c == '>') {
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
    }
    else {
      buffer += c;
    }
  }

  return false;
}

// =====================================================
// Telemetría JSON por Serial
// Formato compatible con el código viejo
// =====================================================
void sendTelemetry() {
  unsigned long now = millis();

  if (now - lastTelemetryMs < TELEMETRY_PERIOD_MS) {
    return;
  }
  lastTelemetryMs = now;

  int leftMixed  = clampInt(v_cmd - w_cmd, -1000, 1000);
  int rightMixed = clampInt(v_cmd + w_cmd, -1000, 1000);

  Serial.print("{\"device_id\":\"");
  Serial.print(DEVICE_ID);
  Serial.print("\",\"stream\":\"");
  Serial.print(STREAM_NAME);
  Serial.print("\",\"sample_period_ms\":");
  Serial.print(TELEMETRY_PERIOD_MS);
  Serial.print(",\"ts_source_ms\":");
  Serial.print(now);
  Serial.print(",\"payload\":{");

  Serial.print("\"v_cmd\":");
  Serial.print(v_cmd);
  Serial.print(",\"w_cmd\":");
  Serial.print(w_cmd);
  Serial.print(",\"f_cmd\":");
  Serial.print(f_cmd);

  Serial.print(",\"base_cmd\":");
  Serial.print(base_cmd);
  Serial.print(",\"elbow_cmd\":");
  Serial.print(elbow_cmd);
  Serial.print(",\"wrist_cmd\":");
  Serial.print(wrist_cmd);
  Serial.print(",\"grip_cmd\":");
  Serial.print(grip_cmd);

  // Compatibilidad con el JSON viejo
  Serial.print(",\"flipper_pos\":");
  Serial.print((int)flipperPos);

  Serial.print(",\"base_pos\":");
  Serial.print((int)basePos);
  Serial.print(",\"elbow_pos\":");
  Serial.print((int)elbowPos);
  Serial.print(",\"wrist_pos\":");
  Serial.print((int)wristPos);
  Serial.print(",\"grip_pos\":");
  Serial.print((int)gripPos);

  Serial.print(",\"left_mix\":");
  Serial.print(leftMixed);
  Serial.print(",\"right_mix\":");
  Serial.print(rightMixed);

  Serial.print(",\"left_target_rpm\":");
  Serial.print(leftTargetRpm, 2);
  Serial.print(",\"right_target_rpm\":");
  Serial.print(rightTargetRpm, 2);
  Serial.print(",\"left_speed_rpm\":");
  Serial.print(encLeft.speedRpm, 2);
  Serial.print(",\"right_speed_rpm\":");
  Serial.print(encRight.speedRpm, 2);
  Serial.print(",\"left_enc_raw\":");
  Serial.print(encLeft.raw);
  Serial.print(",\"right_enc_raw\":");
  Serial.print(encRight.raw);

  Serial.print(",\"link_ok\":");
  Serial.print((millis() - lastPacketTime <= FAILSAFE_MS) ? "true" : "false");

  Serial.println("}}");
}

// =====================================================
// Setup PWM motores
// =====================================================
void setupPWM() {
  // Tracción
  ledcSetup(CH_RPWM_L, PWM_FREQ, PWM_RES);
  ledcSetup(CH_LPWM_L, PWM_FREQ, PWM_RES);
  ledcSetup(CH_RPWM_R, PWM_FREQ, PWM_RES);
  ledcSetup(CH_LPWM_R, PWM_FREQ, PWM_RES);

  ledcAttachPin(RPWM_L, CH_RPWM_L);
  ledcAttachPin(LPWM_L, CH_LPWM_L);
  ledcAttachPin(RPWM_R, CH_RPWM_R);
  ledcAttachPin(LPWM_R, CH_LPWM_R);

  // Flippers
  ledcSetup(CH_FLIPPER_RPWM, PWM_FREQ, PWM_RES);
  ledcSetup(CH_FLIPPER_LPWM, PWM_FREQ, PWM_RES);

  ledcAttachPin(FLIPPER_RPWM, CH_FLIPPER_RPWM);
  ledcAttachPin(FLIPPER_LPWM, CH_FLIPPER_LPWM);
}

// =====================================================
// Setup PCA9685
// =====================================================
void setupPCA() {
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(100000);

  tcaSelect(TCA_CHANNEL);
  pca.begin();
  pca.setOscillatorFrequency(27000000);
  pca.setPWMFreq(PCA_SERVO_FREQ);

  delay(50);

  flipperPos = FLIPPER_HOME;
  basePos    = ARM_BASE_HOME;
  elbowPos   = ARM_ELBOW_HOME;
  wristPos   = ARM_WRIST_HOME;
  gripPos    = ARM_GRIP_HOME;

  writeArm();
}

// =====================================================
// Setup encoders AS5600
// =====================================================
void setupAS5600Encoders() {
  initWheelEncoder(encLeft, ENC_LEFT_CH);
  initWheelEncoder(encRight, ENC_RIGHT_CH);
}

// =====================================================
// Setup
// =====================================================
void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(300);

  setupPWM();
  stopDriveMotors();
  stopFlippers();

  // Enables BTS7960 tracción
  pinMode(REN_L, OUTPUT); digitalWrite(REN_L, HIGH);
  pinMode(LEN_L, OUTPUT); digitalWrite(LEN_L, HIGH);
  pinMode(REN_R, OUTPUT); digitalWrite(REN_R, HIGH);
  pinMode(LEN_R, OUTPUT); digitalWrite(LEN_R, HIGH);

  // Enables BTS7960 flippers
  pinMode(FLIPPER_REN, OUTPUT); digitalWrite(FLIPPER_REN, HIGH);
  pinMode(FLIPPER_LEN, OUTPUT); digitalWrite(FLIPPER_LEN, HIGH);

  setupPCA();
  setupAS5600Encoders();
  resetDrivePIDState();

  lastPacketTime      = millis();
  lastFlipperUpdate   = millis();
  lastArmUpdate       = millis();
  lastTelemetryMs     = 0;
  lastDriveControlMs  = millis();
}

// =====================================================
// Loop
// =====================================================
void loop() {
  int newV, newW, newF, newBase, newElbow, newWrist, newGrip;

  if (readPacket(newV, newW, newF, newBase, newElbow, newWrist, newGrip)) {
    if (USE_CROSSED_DRIVE_MAPPING) {
      v_cmd = clampInt(-newW, -1000, 1000);
      w_cmd = clampInt(newV, -1000, 1000);
    } else {
      v_cmd = clampInt(newV, -1000, 1000);
      w_cmd = clampInt(newW, -1000, 1000);
    }

    f_cmd = clampInt(newF, -1000, 1000);

    base_cmd  = clampInt(newBase, -1000, 1000);
    elbow_cmd = clampInt(newElbow, -1000, 1000);
    wrist_cmd = clampInt(newWrist, -1000, 1000);
    grip_cmd  = clampInt(newGrip, -1000, 1000);

    lastPacketTime = millis();

    writeFlippersMotor(f_cmd);
  }

  updateDriveControl();
  updateFlipperTelemetryEstimate();
  updateArm();

  // Failsafe
  if (millis() - lastPacketTime > FAILSAFE_MS) {
    v_cmd = 0;
    w_cmd = 0;
    f_cmd = 0;
    base_cmd = 0;
    elbow_cmd = 0;
    wrist_cmd = 0;
    grip_cmd = 0;

    stopDriveMotors();
    stopFlippers();
    resetDrivePIDState();
  }

  // Telemetría JSON por el mismo Serial
  sendTelemetry();

  delay(2);
}