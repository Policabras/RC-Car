import time
import math
import json
import serial
import paho.mqtt.client as mqtt

# --- CONFIGURACIÓN ---
PORT = "COM10"
BAUD = 115200
V = 0.5  # Velocidad (Aumenta esto si no ves movimiento)

client = mqtt.Client()
client.connect("localhost", 1883, 60)

try:
    ser = serial.Serial(PORT, BAUD, timeout=1)
    print(f"✅ Conectado a ESP32 en {PORT}")
except Exception as e:
    print(f"❌ Error: No se pudo abrir {PORT}. ¿Está el Monitor Serie de Arduino abierto?")
    exit()

# Posición inicial
x, y = 0.0, 0.0
theta = 0.0

while True:
    # 1. Leer ángulo real del ESP32
    if ser.in_waiting:
        try:
            line = ser.readline().decode('utf-8').strip()
            data = json.loads(line)
            theta = data["theta"]
        except:
            continue

    # 2. Calcular nueva posición basada en el ángulo real
    # Si theta cambia, el robot dejará de ir en línea recta
    x += V * math.cos(theta) * 0.1 # 0.1 por el sleep
    y += V * math.sin(theta) * 0.1

    # 3. Publicar
    payload = {
        "x": round(x, 2),
        "y": round(y, 2),
        "theta": theta
    }
    
    client.publish("robot/position", json.dumps(payload))
    print(f"Enviando -> X: {payload['x']}, Y: {payload['y']}, Angle: {payload['theta']}")

    time.sleep(0.1)