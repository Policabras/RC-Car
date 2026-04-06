# ESP32 differential odometry sender (serial -> Raspberry)

Este proyecto genera **odometría simulada** de un robot diferencial en una ESP32 y la envía por **serial** (una línea JSON por muestra) a la Raspberry.

La idea es que la Raspberry lea el puerto `/dev/ttyUSB*` o `/dev/ttyACM*` y meta cada línea al telemetry collector que ya tienes.

## Qué simula

- cinemática de robot diferencial
- encoders en cuadratura **X4** (mediante cuantización a `ENCODER_CPR_X4`)
- gyro Z tipo **MPU-9250** con bias y ruido
- fusión simple encoder + gyro para estimar `theta` y `wz`

## Formato enviado

Cada muestra sale así:

```json
{"device_id":"robot_r1","stream":"odom","sample_period_ms":20,"qos":0,"retain":false,"ts_source_ms":1712345678901,"seq":25,"payload":{"x":0.123456,"y":0.000000,"theta":0.010000,"vx":0.250000,"wz":0.000000,"left_ticks_delta":35,"right_ticks_delta":35,"gyro_z_dps":0.170000,"true_v":0.250000,"true_wz":0.000000}}
```

Eso coincide con el formato que espera tu collector serial JSON.

## Archivos

- `main/app_config.h`: parámetros del robot, encoder e IMU simulada
- `main/sim_robot.*`: genera la “verdad” del robot y las mediciones simuladas
- `main/odom_estimator.*`: estima odometría con encoder + gyro
- `main/serial_json.*`: empaqueta y manda por stdout
- `main/main.c`: loop principal a periodo fijo

## Build

```bash
idf.py set-target esp32
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

> Cambia `/dev/ttyUSB0` por tu puerto real.

## Integración con la Raspberry

En la Raspberry puedes ver el JSON con:

```bash
cat /dev/ttyUSB0
```

O con Python:

```bash
python -m serial.tools.miniterm /dev/ttyUSB0 115200
```

Y en tu collector:

```bash
SERIAL_PORTS=/dev/ttyUSB0
SERIAL_BAUDRATE=115200
```

## Próximo paso natural

Cuando quieras pasar de simulado a real:

1. sustituye `sim_robot_step()` por lectura real de encoders y del gyro
2. deja intactos `odom_update()` y `serial_json_send_odom()`
3. si tu IMU trae drift fuerte, agrega calibración al arranque

## Nota honesta

Este proyecto **simula** encoders e IMU; no está leyendo todavía el MPU-9250 real ni el PCNT real del encoder. Está hecho así para que primero cierres el flujo:

ESP32 -> serial -> Raspberry -> collector -> broker MQTT

Luego cambias la capa de adquisición sin tocar el formato de salida.
