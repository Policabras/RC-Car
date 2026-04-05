# Telemetry Collector para Raspberry

## En lo siguiente se explica lo que hace el telemetry collector
- Escucha telemetría local por UDP JSON.
- Genera telemetría local de la Raspberry con `psutil`.
- Guarda todo primero en SQLite (`outbox`).
- Publica asíncronamente al broker MQTT remoto.
- Si el broker se cae, la cola local sigue acumulando y reintenta después.

## Instalación rápida
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
mkdir -p /opt/telemetry_collector
cp -r . /opt/telemetry_collector
cd /opt/telemetry_collector

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env
python main.py
```

## Formato esperado por UDP
```json
{
  "device_id": "robot_r1",
  "stream": "odom",
  "sample_period_ms": 20,
  "qos": 0,
  "retain": false,
  "ts_source_ms": 1775312345123,
  "seq": 18273,
  "payload": {
    "x": 1.234,
    "y": 0.552,
    "theta": 0.873,
    "vx": 0.21,
    "wz": 0.05
  }
}
```

## Prueba rápida
En una terminal:
```bash
source .venv/bin/activate
python main.py
```

En otra:
```bash
python - <<'PY'
import json
import socket
import time

msg = {
    "device_id": "robot_r1",
    "stream": "odom",
    "sample_period_ms": 20,
    "qos": 0,
    "retain": False,
    "ts_source_ms": int(time.time() * 1000),
    "seq": 1,
    "payload": {
        "x": 1.0,
        "y": 0.1,
        "theta": 0.2,
        "vx": 0.3,
        "wz": 0.05
    }
}

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(json.dumps(msg).encode(), ("127.0.0.1", 9100))
print("sent")
PY
```

## Topics típicos
- `telemetry/pi_robot_01/system`
- `telemetry/pi_robot_01/status`
- `telemetry/robot_r1/odom`
- `telemetry/robot_r1/cmd`

## Instalar como servicio systemd
```bash
sudo cp telemetry-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable telemetry-collector
sudo systemctl start telemetry-collector
sudo systemctl status telemetry-collector
```

## LOGS
journalctl -u telemetry-collector.service -f