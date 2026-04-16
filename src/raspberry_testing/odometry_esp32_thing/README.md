# ESP32 + Arduino CLI en Raspberry Pi

## Descripción

Este proyecto utiliza Arduino CLI para compilar y subir código a un ESP32 desde una Raspberry Pi, permitiendo automatizar el flujo de desarrollo sin necesidad del entorno gráfico.

---

## Requisitos

* Raspberry Pi con Linux
* Conexión a internet
* ESP32
* Cable USB con soporte de datos

---

## Instalación de Arduino CLI

```bash
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
```

Verificar instalación:

```bash
arduino-cli version
```

---

## Configuración inicial

Inicializar configuración:

```bash
arduino-cli config init
```

Editar archivo de configuración:

```bash
nano ~/.arduino15/arduino-cli.yaml
```

Agregar:

```yaml
board_manager:
  additional_urls:
    - https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
```

---

## Instalación del core ESP32

```bash
arduino-cli core update-index
arduino-cli core install esp32:esp32@2.0.17
arduino-cli lib install "ESP32Servo"
```

---

## Instalación de librerías necesarias

```bash
arduino-cli lib install "Adafruit PWM Servo Driver Library"
arduino-cli lib install "Adafruit BusIO"
```

---

## Verificación de conexión del ESP32

```bash
arduino-cli board list
```

Ejemplo de salida:

```
/dev/ttyUSB0
```

---

## Compilación del proyecto

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 ruta/del/proyecto
```

---

## Subida de código al ESP32

```bash
arduino-cli upload \
  -p /dev/ttyUSB0 \
  --fqbn esp32:esp32:esp32 \
  --upload-property upload.speed=115200 \
  ruta/del/proyecto
```

---

## Uso de script automatizado

El proyecto incluye un script para automatizar la compilación y carga del firmware.

### Ubicación

El archivo se encuentra dentro del proyecto:

```
odometry_esp32_thing/upload_esp32.sh
```

---

### Permisos de ejecución

```bash
chmod +x odometry_esp32_thing/upload_esp32.sh
```

---

### Ejecución del script

Desde la raíz del proyecto:

```bash
./odometry_esp32_thing/upload_esp32.sh
```

---

## Permisos de acceso al puerto serial

```bash
sudo usermod -a -G dialout $USER
```

Se requiere reiniciar sesión después de ejecutar este comando.

---

## Problemas comunes

### Librerías faltantes

Instalar la librería requerida con:

```bash
arduino-cli lib install "Nombre Libreria"
```

---

### Error: chip stopped responding

Posibles causas:

* Cable USB defectuoso
* Energía insuficiente
* Puerto serial en uso por otro proceso
* Velocidad de carga elevada

---

### Recomendación

Utilizar una velocidad de carga de 115200:

```bash
--upload-property upload.speed=115200
```

---

## Depuración de puerto serial

```bash
dmesg | grep tty
```

---

## Flujo de trabajo recomendado

1. Compilar el proyecto
2. Subir el código al dispositivo
3. Validar comportamiento en el hardware

---

## Nota

Para proyectos más avanzados se recomienda automatizar el flujo mediante scripts y considerar actualizaciones OTA para evitar dependencia de conexión física.

---
