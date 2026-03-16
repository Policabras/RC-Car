import time
import math
import json
import paho.mqtt.client as mqtt

client = mqtt.Client()
client.connect("mosquitto", 1883, 60)

# Waypoints de tu archivo original
waypoints = [
    {"x":0, "y":0}, {"x":4, "y":0}, {"x":4, "y":3},
    {"x":1, "y":5}, {"x":-2, "y":3}, {"x":-3, "y":0},
    {"x":0, "y":-2}, {"x":0, "y":0}
]

x, y, current_target = 0.0, 0.0, 0
v = 0.1 # Velocidad

while True:
    target = waypoints[current_target]
    dx = target["x"] - x
    dy = target["y"] - y
    dist = math.sqrt(dx**2 + dy**2)

    if dist < 0.1:
        current_target = (current_target + 1) % len(waypoints)
    
    theta = math.atan2(dy, dx)
    x += v * math.cos(theta)
    y += v * math.sin(theta)

    payload = {"x": round(x, 2), "y": round(y, 2), "theta": theta}
    client.publish("robot/position", json.dumps(payload))
    
    time.sleep(0.1)