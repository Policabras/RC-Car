import cv2
import os
import json
from datetime import datetime
from flask import Flask, Response, render_template_string
from flask_cors import CORS
import paho.mqtt.client as mqtt

# ==========================
# MQTT CONFIG
# ==========================
MQTT_BROKER = "192.168.3.4"
MQTT_PORT = 1883
MQTT_TOPIC = "robot/qr"

client = mqtt.Client()
client.connect(MQTT_BROKER, MQTT_PORT, 60)

# ==========================
# FLASK
# ==========================
app = Flask(__name__)
CORS(app)

# ==========================
# CAMARAS IP
# ==========================
sources = [
    "http://192.168.3.16:8081/mjpeg/0",
    "http://192.168.3.16:8081/mjpeg/1"
]

caps = [cv2.VideoCapture(src) for src in sources]

# 🔥 Reducir lag entre cámaras
for cap in caps:
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

detector = cv2.QRCodeDetector()

# 🔥 Más sensibilidad para QR pequeños
detector.setEpsX(0.2)
detector.setEpsY(0.2)

os.makedirs("qr_data", exist_ok=True)

# Último QR por cámara
last_qr = {}

# ==========================
# GENERADOR POR CAMARA
# ==========================
def gen_frames_cam(cam_id):
    global last_qr

    cap = caps[cam_id]

    while True:
        success, frame = cap.read()

        if not success:
            continue

        # 🔥 Mejor resolución (más detalle)
        small = cv2.resize(frame, (960, 720))

        # ==========================
        # PREPROCESAMIENTO (CLAVE)
        # ==========================
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        gray = cv2.GaussianBlur(gray, (5,5), 0)

        # ==========================
        # DETECCIÓN MEJORADA
        # ==========================
        retval, points = detector.detect(gray)

        if retval and points is not None:

            data, _ = detector.decode(gray, points)

            if data:

                pts = points[0].astype(int)

                scale_x = frame.shape[1] / small.shape[1]
                scale_y = frame.shape[0] / small.shape[0]

                # Dibujar QR
                for j in range(4):
                    pt1 = (int(pts[j][0] * scale_x), int(pts[j][1] * scale_y))
                    pt2 = (int(pts[(j+1)%4][0] * scale_x), int(pts[(j+1)%4][1] * scale_y))
                    cv2.line(frame, pt1, pt2, (0,255,0), 2)

                # Texto
                cv2.putText(frame, data,
                            (int(pts[0][0]*scale_x), int(pts[0][1]*scale_y)-10),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.6,
                            (0,255,0),
                            2)

                # Evitar duplicados
                if data != last_qr.get(cam_id):
                    last_qr[cam_id] = data

                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                    # Guardar imagen
                    img_path = f"qr_data/cam{cam_id}_{timestamp}.png"
                    cv2.imwrite(img_path, frame)

                    # Guardar texto
                    txt_path = f"qr_data/cam{cam_id}_{timestamp}.txt"
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(data)

                    # Coordenadas escaladas
                    pts_scaled = []
                    for p in pts:
                        pts_scaled.append({
                            "x": int(p[0] * scale_x),
                            "y": int(p[1] * scale_y)
                        })

                    # MQTT payload
                    payload = {
                        "qr": data,
                        "camera": cam_id,
                        "points": pts_scaled,
                        "timestamp": datetime.now().isoformat()
                    }

                    client.publish(MQTT_TOPIC, json.dumps(payload))
                    print(f"[CAM {cam_id}] QR detectado:", payload)

        # ==========================
        # STREAM
        # ==========================
        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            continue

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

# ==========================
# ROUTES VIDEO
# ==========================
@app.route('/video_feed/0')
def video_feed_0():
    return Response(gen_frames_cam(0),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed/1')
def video_feed_1():
    return Response(gen_frames_cam(1),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# ==========================
# PAGINA PRINCIPAL
# ==========================
@app.route('/')
def index():
    return render_template_string("""
    <html>
    <head>
        <title>Multi Cámara QR</title>
    </head>
    <body>
        <h1>Streaming Cámaras con QR</h1>

        <div style="display: flex; gap: 20px;">
            <div>
                <h2>Cámara 0</h2>
                <img src="/video_feed/0" width="480">
            </div>

            <div>
                <h2>Cámara 1</h2>
                <img src="/video_feed/1" width="480">
            </div>
        </div>

    </body>
    </html>
    """)

# ==========================
# MAIN
# ==========================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)