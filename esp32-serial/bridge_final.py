import serial
import json
import paho.mqtt.client as mqtt
import math
import time

# -----------------------------
# CONEXIÓN SERIAL ESP32
# -----------------------------
try:
    ser = serial.Serial("COM10", 115200, timeout=1)
    print("✅ Conectado a ESP32 en COM10")
except:
    print("❌ No se pudo abrir COM10")
    exit()

# -----------------------------
# MQTT
# -----------------------------
client = mqtt.Client()

try:
    client.connect("127.0.0.1", 1883, 60)
    client.loop_start() # Inicia el hilo de envío de datos
    print("✅ Conectado al Broker MQTT")
except Exception as e:
    print(f"❌ Error conectando al Broker: {e}")
    exit()  # <--- AGREGA ESTO
# -----------------------------
# VARIABLES DE MOVIMIENTO
# -----------------------------
x = 0.0
y = 0.0
v = 1.0   # velocidad visible

print("🚀 Bridge iniciado...\n")

# -----------------------------
# LOOP PRINCIPAL
# -----------------------------
while True:
    try:
        line = ser.readline().decode("utf-8").strip()

        if not line:
            continue

        # Mostrar exactamente lo que llega de ESP32
        print("SERIAL:", line)

        # Convertir JSON
        data = json.loads(line)

        theta = float(data["theta"])
        z = float(data["z"])

        # -----------------------------
        # MOVIMIENTO
        # -----------------------------
        dt = 0.1

        x += v * math.cos(theta) * dt
        y += v * math.sin(theta) * dt

        payload = {
            "x": round(x, 2),
            "y": round(y, 2),
            "theta": round(theta, 4),
            "z": round(z, 4)
        }

        # -----------------------------
        # MQTT
        # -----------------------------
        client.publish("robot/position", json.dumps(payload))

        print("MQTT:", payload)

    except json.JSONDecodeError:
        print("⚠️ JSON inválido:", line)

    except Exception as e:
        print("❌ Error:", e)

    time.sleep(0.05)