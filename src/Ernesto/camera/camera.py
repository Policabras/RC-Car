import cv2
import time
from aiohttp import web
from aiortc import RTCPeerConnection, VideoStreamTrack
from av import VideoFrame

pcs = set()

cap = cv2.VideoCapture(0)

detector = cv2.QRCodeDetector()

ultimo_bbox = None
ultimo_qr = ""
ultimo_tiempo = 0
PERSISTENCIA = 0.25


class CameraTrack(VideoStreamTrack):
    async def recv(self):
        global ultimo_bbox, ultimo_qr, ultimo_tiempo

        ret, frame = cap.read()

        if ret:

            small = cv2.resize(frame, (320,240))

            retval, decoded_info, points, _ = detector.detectAndDecodeMulti(small)

            if retval and points is not None:

                scale_x = frame.shape[1] / 320
                scale_y = frame.shape[0] / 240

                for i, data in enumerate(decoded_info):

                    if data != "":
                        pts = points[i]

                        scaled_pts = []

                        for p in pts:
                            scaled_pts.append((
                                int(p[0] * scale_x),
                                int(p[1] * scale_y)
                            ))

                        ultimo_bbox = scaled_pts
                        ultimo_qr = data
                        ultimo_tiempo = time.time()

            if ultimo_bbox is not None and (time.time() - ultimo_tiempo < PERSISTENCIA):

                for j in range(4):
                    pt1 = ultimo_bbox[j]
                    pt2 = ultimo_bbox[(j+1)%4]
                    cv2.line(frame, pt1, pt2, (0,255,0), 2)

                x = ultimo_bbox[0][0]
                y = ultimo_bbox[0][1] - 10

                cv2.putText(frame, ultimo_qr, (x,y),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.8, (0,255,0), 2)

        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        return video_frame


async def offer(request):
    pc = RTCPeerConnection()
    pcs.add(pc)

    pc.addTrack(CameraTrack())

    return web.Response(text="WebRTC activo")


app = web.Application()
app.router.add_get("/", offer)

web.run_app(app, host="127.0.0.1", port=8080)