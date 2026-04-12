import cv2
import time
import asyncio
from fractions import Fraction
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame

pcs = set()

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

detector = cv2.QRCodeDetector()

qr_memoria = []
PERSISTENCIA = 0.25


class CameraTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self.counter = 0

    async def recv(self):
        global qr_memoria

        ret, frame = cap.read()

        if not ret:
            await asyncio.sleep(0.02)
            return await self.recv()

        ahora = time.time()

        small = cv2.resize(frame, (320,240))
        retval, decoded_info, points, _ = detector.detectAndDecodeMulti(small)

        nuevos_qr = []

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

                    nuevos_qr.append({
                        "data": data,
                        "bbox": scaled_pts,
                        "time": ahora
                    })

        qr_memoria = nuevos_qr

        for qr in qr_memoria:

            bbox = qr["bbox"]

            for j in range(4):
                pt1 = bbox[j]
                pt2 = bbox[(j+1)%4]
                cv2.line(frame, pt1, pt2, (0,255,0), 2)

            x = bbox[0][0]
            y = bbox[0][1] - 10

            cv2.putText(frame, qr["data"], (x,y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0,255,0), 2)

        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")

        self.counter += 1
        video_frame.pts = self.counter
        video_frame.time_base = Fraction(1, 30)

        return video_frame


async def index(request):
    with open("index.html", "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html")


async def offer(request):
    params = await request.json()

    pc = RTCPeerConnection()
    pcs.add(pc)

    track = CameraTrack()
    pc.addTrack(track)

    offer = RTCSessionDescription(
        sdp=params["sdp"],
        type=params["type"]
    )

    await pc.setRemoteDescription(offer)

    answer = await pc.createAnswer()

    await pc.setLocalDescription(answer)

    return web.json_response({
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type
    })


app = web.Application()
app.router.add_get("/", index)
app.router.add_post("/offer", offer)

web.run_app(app, host="127.0.0.1", port=8080)