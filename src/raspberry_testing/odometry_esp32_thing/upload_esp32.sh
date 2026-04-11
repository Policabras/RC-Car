#!/bin/bash

# ==========================================================

# Script: upload_esp32.sh

# Descripción:

# Detiene el servicio que utiliza el puerto serial,

# compila y sube el firmware al ESP32, y posteriormente

# restablece el servicio.

# ==========================================================

set -e

# ==========================================================

# CONFIGURACIÓN

# ==========================================================

PORT="/dev/ttyUSB0"
FQBN="esp32:esp32:esp32"
PROJECT_DIR="odometry_esp32_thing"
UPLOAD_SPEED="115200"
SERVICE_NAME="telemetry-collector.service"

# ==========================================================

# VALIDACIÓN DE ENTORNO

# ==========================================================

echo "[INFO] Verificando disponibilidad del puerto: ${PORT}"

if [ ! -e "${PORT}" ]; then
echo "[ERROR] El puerto ${PORT} no está disponible."
exit 1
fi

# ==========================================================

# DETENER SERVICIO

# ==========================================================

echo "[INFO] Deteniendo servicio ${SERVICE_NAME}..."
sudo systemctl stop ${SERVICE_NAME}

# ==========================================================

# COMPILACIÓN

# ==========================================================

echo "[INFO] Iniciando compilación del proyecto..."
cd ..

arduino-cli compile --fqbn ${FQBN} ${PROJECT_DIR}

echo "[INFO] Compilación finalizada correctamente."

# ==========================================================

# CARGA DE FIRMWARE

# ==========================================================

echo "[INFO] Iniciando carga de firmware al dispositivo..."

#arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32 --upload-property upload.speed=115200 odometry_esp32_thing/

arduino-cli upload -p ${PORT} --fqbn ${FQBN} --upload-property upload.speed=${UPLOAD_SPEED} ${PROJECT_DIR}

echo "[INFO] Carga completada correctamente."

# ==========================================================

# REINICIAR SERVICIO

# ==========================================================

echo "[INFO] Iniciando servicio ${SERVICE_NAME}..."
sudo systemctl start ${SERVICE_NAME}

# ==========================================================

# FIN

# ==========================================================

echo "[INFO] Proceso finalizado correctamente."
