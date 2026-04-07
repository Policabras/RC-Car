import cv2
import os
from datetime import datetime
# from flask import Flask, Response
# from flask_cors import CORS

# app = Flask(__name__)
# CORS(app)

# URL del stream de la cámara IP
# Ejemplo:
# STREAM_URL = "http://192.168.1.50:8081/mjpeg"
STREAM_URL = "http://10.243.61.207:8081/mjpeg"

cap = cv2.VideoCapture(STREAM_URL)
# cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
# cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

detector = cv2.QRCodeDetector()

os.makedirs("qr_data", exist_ok=True)

last_qr = ""


def gen_frames():
    global last_qr

    while True:
        success, frame = cap.read()

        if not success:
            continue

        small = cv2.resize(frame, (320, 240))
        retval, decoded_info, points, _ = detector.detectAndDecodeMulti(small)

        if retval and points is not None:
            scale_x = frame.shape[1] / 320
            scale_y = frame.shape[0] / 240

            for i, data in enumerate(decoded_info):
                if data:
                    pts = points[i].astype(int)

                    for j in range(4):
                        pt1 = (int(pts[j][0] * scale_x), int(pts[j][1] * scale_y))
                        pt2 = (
                            int(pts[(j + 1) % 4][0] * scale_x),
                            int(pts[(j + 1) % 4][1] * scale_y)
                        )
                        cv2.line(frame, pt1, pt2, (0, 255, 0), 2)

                    cv2.putText(
                        frame,
                        data,
                        (int(pts[0][0] * scale_x), int(pts[0][1] * scale_y) - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        2
                    )

                    if data != last_qr:
                        last_qr = data

                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                        img_path = f"qr_data/{timestamp}.png"
                        txt_path = f"qr_data/{timestamp}.txt"

                        cv2.imwrite(img_path, frame)

                        with open(txt_path, "w", encoding="utf-8") as f:
                            f.write(data)

                        print(f"QR guardado: {data}")

        # Parte de visualización/stream comentada
        # ret, buffer = cv2.imencode('.jpg', frame)
        #
        # if not ret:
        #     continue
        #
        # frame_bytes = buffer.tobytes()
        #
        # yield (b'--frame\r\n'
        #        b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')


# @app.route('/video_feed')
# def video_feed():
#     return Response(
#         gen_frames(),
#         mimetype='multipart/x-mixed-replace; boundary=frame'
#     )

if __name__ == '__main__':
    try:
        gen_frames()
    finally:
        cap.release()
        # cv2.destroyAllWindows()
