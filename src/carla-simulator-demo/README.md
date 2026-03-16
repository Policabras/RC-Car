# README — Flujo básico de ejecución de CARLA

Este documento describe el flujo mínimo para levantar **CARLA**, habilitar el control del vehículo, enviar telemetría por **MQTT** y transmitir la cámara por **WebRTC**.

La secuencia recomendada es la siguiente:

1. Iniciar el simulador de **CARLA**.
2. *(Opcional)* Generar tráfico.
3. Ejecutar el control manual.
4. Ejecutar `game_sir_carla.py` para control con mando de videojuego.
5. Ejecutar `carla_to_mqtt.py` para publicar datos hacia **Mosquitto**.
6. Ejecutar `camera_webrtc.py` para hacer streaming de la cámara de CARLA.

---

## Requisitos previos

Antes de comenzar, asegúrate de contar con lo siguiente:

* **CARLA** instalado correctamente.
* Python y dependencias del proyecto ya configuradas.
* Ambiente virtual disponible.
* Un broker **Mosquitto** activo si vas a usar `carla_to_mqtt.py`.
* Ejecutar los scripts desde la carpeta correcta del proyecto.
* Mantener abierta la terminal donde se inicia el servidor de CARLA.

---

## Estructura general de trabajo

### Terminal 1 — Iniciar CARLA

Desde la carpeta del simulador, ejecutar:

```bash
cd ~/projects/RC-Car/src/carla-simulator-demo/simulators
./CarlaUE4.sh -quality-level=Low -RenderOffScreen
```

### Terminal 2 — Scripts de Python

Activar el ambiente virtual y moverse a la carpeta de ejemplos:

```bash
cd ~/projects/RC-Car/src/carla-simulator-demo/.venv/bin
source activate
cd ~/projects/RC-Car/src/carla-simulator-demo/simulators/PythonAPI/examples
```

> A partir de aquí, los scripts siguientes se ejecutan desde esta misma carpeta, salvo que alguno esté ubicado en otra ruta.

---

## 1. Iniciar el simulador de CARLA

```bash
./CarlaUE4.sh -quality-level=Low -RenderOffScreen
```

### ¿Qué hace este comando?

* Inicia el servidor de **CARLA**.
* Usa calidad gráfica baja para reducir consumo de recursos.
* Ejecuta el simulador sin renderizar en pantalla (`RenderOffScreen`).

Esto es útil cuando el objetivo principal es probar control, telemetría o integración con otros módulos sin gastar GPU a lo loco.

---

## 2. Generar tráfico *(opcional)*

Con el ambiente virtual activado y dentro de `PythonAPI/examples`, ejecutar:

```bash
python3 generate_traffic.py
```

### ¿Qué hace este comando?

* Inserta vehículos y tráfico automático dentro del entorno.
* Permite probar escenarios más realistas.

### Cuándo usarlo

* Cuando quieres validar percepción, navegación o telemetría con vehículos alrededor.
* Cuando quieres probar interacción con tráfico realista.

### Cuándo omitirlo

* Cuando buscas una prueba simple y controlada.
* Cuando deseas depurar control manual sin ruido adicional.

---

## 3. Ejecutar el control manual

```bash
python3 manual_control.py
```

### ¿Qué hace este comando?

* Abre la interfaz de control manual de CARLA.
* Permite conducir un vehículo dentro del simulador.
* Suele ser el punto de entrada para verificar que el servidor y el cliente están comunicándose bien.

---

## 4. Ejecutar `game_sir_carla.py`

```bash
python3 game_sir_carla.py
```

### ¿Qué hace este comando?

* Permite controlar el vehículo usando un **control de videojuego**.
* Extiende o complementa el flujo de manejo manual, según la lógica implementada en tu proyecto.

### Recomendación

Antes de correr este script, verifica que:

* El simulador ya esté activo.
* El vehículo ya esté disponible en la escena.
* El control o joystick sea reconocido por el sistema.

---

## 5. Ejecutar `carla_to_mqtt.py`

```bash
python3 carla_to_mqtt.py
```

### ¿Qué hace este comando?

* Lee datos desde CARLA.
* Publica esos datos hacia un broker MQTT, en este caso **Mosquitto**.
* Sirve para desacoplar el simulador de otros módulos consumidores, como dashboards, sistemas de monitoreo o servicios backend.

### Importante

Antes de ejecutarlo, valida que:

* El broker **Mosquitto** esté levantado.
* La IP, puerto y tópicos MQTT estén configurados correctamente.
* CARLA y el vehículo ya estén corriendo.

---

## 6. Ejecutar `camera_webrtc.py`

```bash
python3 camera_webrtc.py
```

### ¿Qué hace este comando?

* Captura la cámara del entorno de CARLA.
* Transmite el video mediante **WebRTC**.
* Permite visualizar el stream desde otro cliente o interfaz web, dependiendo de tu implementación.

### Recomendación

Ejecutarlo al final del flujo evita confusiones al depurar. Primero aseguras simulación, luego control, luego datos, y al final video. Como debe ser: primero que el carro ande, luego ya lo presumes en streaming.

---

## Orden recomendado de ejecución

```text
1. ./CarlaUE4.sh -quality-level=Low -RenderOffScreen
2. python3 generate_traffic.py          # opcional
3. python3 manual_control.py
4. python3 game_sir_carla.py
5. python3 carla_to_mqtt.py
6. python3 camera_webrtc.py
```

---

## Flujo rápido de arranque

### Terminal 1

```bash
cd ~/projects/RC-Car/src/carla-simulator-demo/simulators
./CarlaUE4.sh -quality-level=Low -RenderOffScreen
```

### Terminal 2

```bash
cd ~/projects/RC-Car/src/carla-simulator-demo/.venv/bin
source activate
cd ~/projects/RC-Car/src/carla-simulator-demo/simulators/PythonAPI/examples
python3 generate_traffic.py
```

### Terminal 3

```bash
cd ~/projects/RC-Car/src/carla-simulator-demo/.venv/bin
source activate
cd ~/projects/RC-Car/src/carla-simulator-demo/simulators/PythonAPI/examples
python3 manual_control.py
```

### Terminal 4

```bash
cd ~/projects/RC-Car/src/carla-simulator-demo/.venv/bin
source activate
cd ~/projects/RC-Car/src/carla-simulator-demo/simulators/PythonAPI/examples
python3 game_sir_carla.py
```

### Terminal 5

```bash
cd ~/projects/RC-Car/src/carla-simulator-demo/.venv/bin
source activate
cd ~/projects/RC-Car/src/carla-simulator-demo/simulators/PythonAPI/examples
python3 carla_to_mqtt.py
```

### Terminal 6

```bash
cd ~/projects/RC-Car/src/carla-simulator-demo/.venv/bin
source activate
cd ~/projects/RC-Car/src/carla-simulator-demo/simulators/PythonAPI/examples
python3 camera_webrtc.py
```

---

## Problemas comunes

### CARLA no responde

Verifica que la terminal del servidor siga activa y que no haya fallado al iniciar.

### `manual_control.py` no conecta

Confirma que CARLA ya esté levantado y escuchando en el puerto esperado.

### No se publica nada en MQTT

Revisa:

* Que **Mosquitto** esté corriendo.
* Que la configuración del broker sea correcta.
* Que el script `carla_to_mqtt.py` esté apuntando al host y puerto adecuados.

### No hay stream de cámara

Verifica:

* Que el vehículo y la cámara hayan sido creados correctamente.
* Que `camera_webrtc.py` no tenga conflicto de puertos.
* Que el cliente receptor de WebRTC esté correctamente configurado.

### El control de videojuego no funciona

Asegúrate de que el mando esté detectado por el sistema operativo antes de correr `game_sir_carla.py`.

---

## Notas importantes

* Mantén abiertas todas las terminales necesarias durante la ejecución.
* Si uno de los procesos falla, los demás pueden quedar vivos pero inútiles, como junta sin café.
* Si cambias de carpeta antes de ejecutar scripts, valida siempre la ruta actual.
* Si algún script depende de variables de entorno o archivos de configuración, revisa eso antes de culpar a CARLA.

---

## Resumen corto

```bash
# Terminal 1
cd ~/projects/RC-Car/src/carla-simulator-demo/simulators
./CarlaUE4.sh -quality-level=Low -RenderOffScreen

# Terminal 2
cd ~/projects/RC-Car/src/carla-simulator-demo/.venv/bin
source activate
cd ~/projects/RC-Car/src/carla-simulator-demo/simulators/PythonAPI/examples
python3 generate_traffic.py   # opcional

# Terminal 3
python3 manual_control.py

# Terminal 4
python3 game_sir_carla.py

# Terminal 5
python3 carla_to_mqtt.py

# Terminal 6
python3 camera_webrtc.py
```
