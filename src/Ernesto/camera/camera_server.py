import cv2
import os
from datetime import datetime
from flask import Flask, Response
from flask_cors import CORS
import paho.mqtt.client as mqtt

# ==========================
# MQTT
# ==========================
MQTT_BROKER = "192.168.1.230"   # cambia por la IP de tu computadora
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
# CÁMARA
# ==========================
cap = cv2.VideoCapture(0,  cv2.CAP_DSHOW)#, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

detector = cv2.QRCodeDetector()

os.makedirs("qr_data", exist_ok=True)

last_qr = ""

# ==========================
# STREAM + QR
# ==========================
def gen_frames():
    global last_qr

    while True:
        success, frame = cap.read()

        if not success:
            continue

        small = cv2.resize(frame, (640, 480))        
        retval, decoded_info, points, _ = detector.detectAndDecodeMulti(small)

        if retval and points is not None and len(points) > 0:
            scale_x = frame.shape[1] / 640
            scale_y = frame.shape[0] / 480

            for i, data in enumerate(decoded_info):
                if data:
                    pts = points[i].astype(int)

                    for j in range(4):
                        pt1 = (int(pts[j][0] * scale_x), int(pts[j][1] * scale_y))
                        pt2 = (int(pts[(j+1)%4][0] * scale_x), int(pts[(j+1)%4][1] * scale_y))
                        cv2.line(frame, pt1, pt2, (0,255,0), 2)

                    cv2.putText(frame, data,
                                (int(pts[0][0]*scale_x), int(pts[0][1]*scale_y)-10),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                (0,255,0),
                                2)

                    if data != last_qr:
                        last_qr = data

                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                        img_path = f"qr_data/{timestamp}.png"
                        txt_path = f"qr_data/{timestamp}.txt"

                        cv2.imwrite(img_path, frame)

                        with open(txt_path, "w", encoding="utf-8") as f:
                            f.write(data)

                        print(f"QR guardado: {data}")

                        # MQTT publish
                        client.publish(MQTT_TOPIC, data)

        ret, buffer = cv2.imencode('.jpg', frame)

        if not ret:
            continue

        frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# ==========================
# VIDEO ROUTE
# ==========================
@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# ==========================
# MAIN
# ==========================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)