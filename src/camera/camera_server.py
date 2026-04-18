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

try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
except AttributeError:
    client = mqtt.Client()


def on_connect(client, userdata, *args, **kwargs):
    print(f"[MQTT] Conectado al broker {MQTT_BROKER}:{MQTT_PORT}")


def on_disconnect(client, userdata, *args, **kwargs):
    print("[MQTT] Desconectado del broker")


try:
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
except Exception:
    pass

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_start()

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

detector = cv2.QRCodeDetector()

if hasattr(detector, "setEpsX"):
    detector.setEpsX(0.2)

if hasattr(detector, "setEpsY"):
    detector.setEpsY(0.2)

if hasattr(detector, "setUseAlignmentMarkers"):
    detector.setUseAlignmentMarkers(True)

os.makedirs("qr_data", exist_ok=True)

# Último QR por cámara
last_qr = {}

# ==========================
# HELPERS
# ==========================
def safe_detect_and_decode(img):
    try:
        data, points, _ = detector.detectAndDecode(img)
        return data, points
    except cv2.error as e:
        print(f"[QR] OpenCV detectAndDecode error: {e}")
        return "", None


def detect_qr_with_fallbacks(frame):
    # 1) Original frame
    data, points = safe_detect_and_decode(frame)
    if points is not None and data:
        return data, points

    # 2) Original grayscale
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    data, points = safe_detect_and_decode(gray)
    if points is not None and data:
        return data, points

    # 3) Equalized grayscale
    gray_eq = cv2.equalizeHist(gray)
    data, points = safe_detect_and_decode(gray_eq)
    if points is not None and data:
        return data, points

    # 4) Upscaled grayscale passes for tiny QR
    for scale in (2.0, 3.0):
        zoom_gray = cv2.resize(
            gray,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC
        )

        data, points = safe_detect_and_decode(zoom_gray)
        if points is not None and data:
            return data, points / scale

        zoom_gray_eq = cv2.equalizeHist(zoom_gray)
        data, points = safe_detect_and_decode(zoom_gray_eq)
        if points is not None and data:
            return data, points / scale

    return "", None


# ==========================
# GENERADOR POR CAMARA
# ==========================
def gen_frames_cam(cam_id):
    global last_qr

    cap = caps[cam_id]

    while True:
        success, frame = cap.read()

        if not success or frame is None or frame.size == 0:
            continue

        data, points = detect_qr_with_fallbacks(frame)

        if points is not None and data:
            pts = points.reshape(-1, 2).astype(int)

            scale_x = 1.0
            scale_y = 1.0

            # Dibujar QR
            if len(pts) >= 4:
                for j in range(4):
                    pt1 = (int(pts[j][0] * scale_x), int(pts[j][1] * scale_y))
                    pt2 = (
                        int(pts[(j + 1) % 4][0] * scale_x),
                        int(pts[(j + 1) % 4][1] * scale_y)
                    )
                    cv2.line(frame, pt1, pt2, (0, 255, 0), 2)

                # Texto
                cv2.putText(
                    frame,
                    data,
                    (int(pts[0][0] * scale_x), int(pts[0][1] * scale_y) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2
                )

            # Evitar duplicados por cámara
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

                # Coordenadas reales
                pts_scaled = []
                for p in pts:
                    pts_scaled.append({
                        "x": int(p[0] * scale_x),
                        "y": int(p[1] * scale_y)
                    })

                # Dimensiones reales del frame
                frame_height, frame_width = frame.shape[:2]

                # Payload MQTT
                payload = {
                    "qr": data,
                    "camera": cam_id,
                    "points": pts_scaled,
                    "timestamp": datetime.now().isoformat(),
                    "frame_width": int(frame_width),
                    "frame_height": int(frame_height)
                }

                result = client.publish(MQTT_TOPIC, json.dumps(payload))
                result.wait_for_publish()

                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    print(f"[CAM {cam_id}] QR detectado y enviado a MQTT:", payload)
                else:
                    print(
                        f"[CAM {cam_id}] QR detectado pero FALLÓ envío MQTT. "
                        f"rc={result.rc} payload={payload}"
                    )

        # Enviar frame
        ret, buffer = cv2.imencode(".jpg", frame)
        if not ret:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
        )


# ==========================
# ROUTES VIDEO
# ==========================
@app.route("/video_feed/0")
def video_feed_0():
    return Response(
        gen_frames_cam(0),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/video_feed/1")
def video_feed_1():
    return Response(
        gen_frames_cam(1),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


# ==========================
# PAGINA PRINCIPAL
# ==========================
@app.route("/")
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
if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=5001, threaded=True)
    finally:
        client.loop_stop()
        client.disconnect()

        for cap in caps:
            try:
                cap.release()
            except Exception:
                pass