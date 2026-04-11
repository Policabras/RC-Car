# Remote Control MQTT Publisher

## Descripción

Este módulo permite leer un control de videojuegos desde una computadora externa y publicar comandos por MQTT hacia el broker utilizado por el sistema del robot.

Este componente **no corre en la Raspberry** y **no se comunica por UART**. Su única responsabilidad es:

1. Detectar el control.
2. Leer los ejes y botones.
3. Convertir esas entradas a comandos del robot.
4. Publicar esos comandos al topic MQTT configurado.

La Raspberry, por su parte, ejecuta el `telemetry_collector`, que se suscribe a los comandos MQTT y los reenvía al ESP32 por serial.

---

## Ubicación sugerida dentro del repositorio

```text
raspberry_testing/
  telemetry_collector/
  remote_control/
    gamepad_mqtt_publisher.py
    requirements.txt
    .env.example
    README.md
```

---

## Requisitos

* Python 3.10 o superior
* Un control compatible con `evdev`
* Acceso al dispositivo `/dev/input/eventX`
* Conectividad de red hacia el broker MQTT

---

## Instalación

Entrar a la carpeta del módulo:

```bash
cd raspberry_testing/remote_control
```

Crear entorno virtual:

```bash
python3 -m venv .venv
```

Activarlo:

```bash
source .venv/bin/activate
```

Instalar dependencias:

```bash
pip install -r requirements.txt
```

---

## Dependencias

Contenido esperado de `requirements.txt`:

```text
evdev
paho-mqtt
```

---

## Configuración

Crear un archivo `.env` a partir de `.env.example`.

Ejemplo de `.env.example`:

```env
MQTT_HOST=192.168.1.106
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_CLIENT_ID=gamepad_mqtt_publisher
MQTT_COMMAND_TOPIC=telemetry/pi_robot_01/cmd
MQTT_QOS=0
FORCED_EVENT_PATH=/dev/input/event4
```

### Variables

* `MQTT_HOST`: dirección IP o hostname del broker MQTT.
* `MQTT_PORT`: puerto del broker.
* `MQTT_USERNAME`: usuario MQTT, si aplica.
* `MQTT_PASSWORD`: contraseña MQTT, si aplica.
* `MQTT_CLIENT_ID`: identificador del cliente MQTT.
* `MQTT_COMMAND_TOPIC`: topic donde se publican los comandos del robot.
* `MQTT_QOS`: calidad de servicio MQTT.
* `FORCED_EVENT_PATH`: dispositivo del control en Linux, por ejemplo `/dev/input/event4`.

---

## Ejecución

Con el entorno virtual activado y las variables definidas:

```bash
python gamepad_mqtt_publisher.py
```

Si prefieres exportar variables manualmente:

```bash
export MQTT_HOST=192.168.1.106
export MQTT_PORT=1883
export MQTT_COMMAND_TOPIC=telemetry/pi_robot_01/cmd
export FORCED_EVENT_PATH=/dev/input/event4
python gamepad_mqtt_publisher.py
```

---

## Flujo de arquitectura

```text
Control de videojuegos
    -> gamepad_mqtt_publisher.py
    -> Broker MQTT
    -> telemetry_collector en Raspberry
    -> RobotSerialBridge
    -> ESP32
```

---

## Topic utilizado

Este módulo publica normalmente en:

```text
telemetry/pi_robot_01/cmd
```

Ese topic debe coincidir con el valor de `ROBOT_COMMAND_TOPIC` configurado en la Raspberry dentro del `telemetry_collector`.

---

## Formato de publicación

El publicador envía un payload JSON con el estado completo del robot.

Ejemplo:

```json
{"v":0,"w":0,"f":0,"base":0,"elbow":0,"wrist":0,"grip":0}
```

Esto permite que la Raspberry siempre tenga un estado completo y pueda reenviarlo como paquete serial al ESP32.

---

## Mapeo de controles

El mapeo sugerido es el siguiente:

* `R2 / L2` -> avance y reversa (`v`)
* `stick izquierdo X` -> giro (`w`)
* `stick derecho Y` -> flipper (`f`)
* `stick derecho X` -> base del brazo (`base`)
* `stick izquierdo Y` -> codo (`elbow`)
* `D-pad arriba/abajo` -> muñeca (`wrist`)
* `cuadrado / círculo` -> garra (`grip`)
* `OPTIONS` sostenido 5 segundos -> apagado del equipo que ejecuta este script

---

## Frecuencia de envío

El publicador envía comandos a una frecuencia aproximada de **50 Hz**.

Esto permite que el `telemetry_collector` mantenga un flujo constante de comandos hacia el ESP32 y evita que el robot entre en failsafe por falta de actualización.

---

## Prueba del topic

Para validar que el publicador está enviando comandos correctamente, puedes suscribirte desde el broker:

```bash
docker exec -it mosquitto mosquitto_sub -h localhost -v -t 'telemetry/pi_robot_01/cmd'
```

Si el broker no corre en Docker, puedes probar directamente con:

```bash
mosquitto_sub -h 192.168.1.106 -v -t 'telemetry/pi_robot_01/cmd'
```

---

## Notas importantes

* Este módulo no reemplaza al `telemetry_collector`; lo complementa.
* Este módulo no debe publicar por UART.
* Este módulo no debe vivir dentro de `telemetry_collector` porque cumple otra responsabilidad.
* Si el control se desconecta, el script debe intentar recuperarse y volver a publicar estado seguro.
* Al salir del programa, se recomienda publicar ceros para dejar el robot en estado neutro.

---

## Ejemplo de uso recomendado

1. En la Raspberry corre el `telemetry_collector`.
2. En la laptop o computadora externa corre `gamepad_mqtt_publisher.py`.
3. El broker MQTT recibe los comandos.
4. La Raspberry toma esos comandos y los envía al ESP32.
5. El ESP32 ejecuta movimiento y responde con telemetría.

---

## Archivos esperados en este módulo

### `gamepad_mqtt_publisher.py`

Script principal que:

* detecta el control
* interpreta ejes y botones
* genera el comando completo del robot
* publica por MQTT

### `requirements.txt`

Dependencias Python del módulo.

### `.env.example`

Variables de entorno de ejemplo para conexión al broker y selección del dispositivo de entrada.

### `README.md`

Este documento.
