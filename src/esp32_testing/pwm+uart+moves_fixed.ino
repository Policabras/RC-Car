#include <Arduino.h>

// ==============================
// UART con Raspberry
// ==============================
HardwareSerial RaspiSerial(2);  // UART2
static const int RXD2 = 16;
static const int TXD2 = 17;
static const long UART_BAUD = 115200;

// ==============================
// BTS7960 PINS
// ==============================
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

// ==============================
// PWM CONFIG
// ==============================
const int PWM_FREQ = 20000;
const int PWM_RES  = 8;   // 0..255

const int CH_RPWM_L = 0;
const int CH_LPWM_L = 1;
const int CH_RPWM_R = 2;
const int CH_LPWM_R = 3;

// ==============================
// CONTROL
// ==============================
int v_cmd = 0;   // avance/retroceso
int w_cmd = 0;   // giro

unsigned long lastPacketTime = 0;
const unsigned long FAILSAFE_MS = 300;

// ==============================
// Helpers
// ==============================
int clampInt(int x, int lo, int hi) {
  if (x < lo) return lo;
  if (x > hi) return hi;
  return x;
}

int map1000To255(int x) {
  x = abs(x);
  x = clampInt(x, 0, 1000);
  return map(x, 0, 1000, 0, 255);
}

void setMotorBTS(int pwmForwardChannel, int pwmBackwardChannel, int value) {
  value = clampInt(value, -1000, 1000);
  int pwm = map1000To255(value);

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

void stopAllMotors() {
  ledcWrite(CH_RPWM_L, 0);
  ledcWrite(CH_LPWM_L, 0);
  ledcWrite(CH_RPWM_R, 0);
  ledcWrite(CH_LPWM_R, 0);
}

// ==============================
// Parsear paquetes tipo <123,-456>
// ==============================
bool readPacket(int &v, int &w) {
  static String buffer = "";

  while (RaspiSerial.available()) {
    char c = (char)RaspiSerial.read();

    if (c == '<') {
      buffer = "";
    }
    else if (c == '>') {
      int commaIndex = buffer.indexOf(',');
      if (commaIndex > 0) {
        String vStr = buffer.substring(0, commaIndex);
        String wStr = buffer.substring(commaIndex + 1);

        v = vStr.toInt();
        w = wStr.toInt();
        return true;
      }
    }
    else {
      buffer += c;
    }
  }

  return false;
}

void setupPWM() {
  ledcSetup(CH_RPWM_L, PWM_FREQ, PWM_RES);
  ledcSetup(CH_LPWM_L, PWM_FREQ, PWM_RES);
  ledcSetup(CH_RPWM_R, PWM_FREQ, PWM_RES);
  ledcSetup(CH_LPWM_R, PWM_FREQ, PWM_RES);

  ledcAttachPin(RPWM_L, CH_RPWM_L);
  ledcAttachPin(LPWM_L, CH_LPWM_L);
  ledcAttachPin(RPWM_R, CH_RPWM_R);
  ledcAttachPin(LPWM_R, CH_LPWM_R);
}

void setup() {
  Serial.begin(115200);
  Serial.println("Monitor serial inicializado");

  RaspiSerial.begin(UART_BAUD, SERIAL_8N1, RXD2, TXD2);

  setupPWM();
  stopAllMotors();

  // Enables BTS7960
  pinMode(REN_L, OUTPUT); digitalWrite(REN_L, HIGH);
  pinMode(LEN_L, OUTPUT); digitalWrite(LEN_L, HIGH);
  pinMode(REN_R, OUTPUT); digitalWrite(REN_R, HIGH);
  pinMode(LEN_R, OUTPUT); digitalWrite(LEN_R, HIGH);

  lastPacketTime = millis();

  Serial.println("ESP32 listo. Esperando paquetes UART...");
}

void loop() {
  int newV, newW;

  if (readPacket(newV, newW)) {
    // =========================================
    // CORRECCION DE EJES
    // newW = avance/retroceso
    // newV = giro
    //
    // Se invierte avance porque estaba al revés
    // NO se invierte giro porque también estaba al revés
    // =========================================
    v_cmd = clampInt(-newW, -1000, 1000);
    w_cmd = clampInt(newV, -1000, 1000);

    lastPacketTime = millis();

    // Mezcla diferencial
    int left  = v_cmd - w_cmd;
    int right = v_cmd + w_cmd;

    left  = clampInt(left, -1000, 1000);
    right = clampInt(right, -1000, 1000);

    // Mandar a BTS
    setMotorBTS(CH_RPWM_L, CH_LPWM_L, left);
    setMotorBTS(CH_RPWM_R, CH_LPWM_R, right);

    Serial.print("RAW newV=");
    Serial.print(newV);
    Serial.print(" newW=");
    Serial.print(newW);

    Serial.print(" | v=");
    Serial.print(v_cmd);
    Serial.print(" w=");
    Serial.print(w_cmd);
    Serial.print(" | left=");
    Serial.print(left);
    Serial.print(" right=");
    Serial.println(right);
  }

  // Failsafe: si no llegan datos, parar
  if (millis() - lastPacketTime > FAILSAFE_MS) {
    stopAllMotors();
  }
}