#pragma once

// ------------------------------
// Transport / payload parameters
// ------------------------------
#define APP_DEVICE_ID            "robot_r1"
#define APP_STREAM_NAME          "odom"
#define APP_SAMPLE_PERIOD_MS     20
#define APP_QOS                  0
#define APP_RETAIN               0

// ------------------------------
// Differential robot geometry
// ------------------------------
#define APP_WHEEL_RADIUS_M       0.0325f
#define APP_WHEEL_BASE_M         0.1600f

// Encoder effective counts per wheel revolution in X4 mode.
// Example: 360 CPR mechanical quadrature => 1440 counts/rev in X4.
#define APP_ENCODER_CPR_X4       1440.0f

// ------------------------------
// Simulated IMU (MPU-9250-like gyro Z)
// ------------------------------
#define APP_IMU_GYRO_BIAS_DPS    0.18f
#define APP_IMU_GYRO_NOISE_DPS   0.35f
#define APP_IMU_BLEND_ALPHA      0.70f   // 0.0 = enc only, 1.0 = imu only

// ------------------------------
// Motion profile
// ------------------------------
#define APP_PROFILE_PERIOD_S     25.0f

// ------------------------------
// Serial output
// ------------------------------
// The ESP32 will emit one JSON line per sample through stdout.
// When connected to the Raspberry by USB-UART or USB Serial/JTAG,
// the Raspberry reads these lines from /dev/ttyUSB* or /dev/ttyACM*.
