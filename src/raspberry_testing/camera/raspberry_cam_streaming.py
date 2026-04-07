import argparse
import asyncio
import atexit
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame


# Configuración
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8081

CAMERA_DEVICE = "/dev/video0"
IMAGE_W = 640
IMAGE_H = 480
CAMERA_FPS = 20
JPEG_QUALITY = 80

BASE_DIR = Path(__file__).resolve().parent

pcs = set()

frame_lock = threading.Lock()
latest_frame = None

camera_cap = None
capture_thread = None
capture_running = False


# Camera
def create_placeholder_frame(width, height, text="Esperando cámara..."):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(
        frame,
        text,
        (30, height // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return frame


def camera_capture_loop():
    global latest_frame, capture_running, camera_cap

    print("[CAM] Hilo de captura iniciado")

    while capture_running:
        if camera_cap is None or not camera_cap.isOpened():
            with frame_lock:
                latest_frame = create_placeholder_frame(
                    IMAGE_W, IMAGE_H, "Camara no disponible"
                )
            time.sleep(0.05)
            continue

        ret, frame = camera_cap.read()

        if not ret or frame is None:
            with frame_lock:
                latest_frame = create_placeholder_frame(
                    IMAGE_W, IMAGE_H, "Sin frames de la camara"
                )
            time.sleep(0.01)
            continue

        if frame.shape[1] != IMAGE_W or frame.shape[0] != IMAGE_H:
            frame = cv2.resize(frame, (IMAGE_W, IMAGE_H))

        with frame_lock:
            latest_frame = frame.copy()


def setup_camera(device):
    global camera_cap, capture_thread, capture_running, latest_frame

    print(f"[CAM] Abriendo cámara: {device}")

    if isinstance(device, str) and device.isdigit():
        device = int(device)

    camera_cap = cv2.VideoCapture(device, cv2.CAP_V4L2)

    if not camera_cap.isOpened():
        raise RuntimeError(f"No pude abrir la cámara: {device}")

    camera_cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    camera_cap.set(cv2.CAP_PROP_FRAME_WIDTH, IMAGE_W)
    camera_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, IMAGE_H)
    camera_cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
    camera_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    with frame_lock:
        latest_frame = create_placeholder_frame(
            IMAGE_W, IMAGE_H, "Inicializando cámara..."
        )

    capture_running = True
    capture_thread = threading.Thread(target=camera_capture_loop, daemon=True)
    capture_thread.start()

    print("[CAM] Cámara abierta correctamente")
    print("[CAM] Configuración real reportada por OpenCV:")
    print("       width      =", camera_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    print("       height     =", camera_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print("       fps        =", camera_cap.get(cv2.CAP_PROP_FPS))
    print("       buffersize =", camera_cap.get(cv2.CAP_PROP_BUFFERSIZE))

    print(f"[HTTP] Backend disponible en http://{HTTP_HOST}:{HTTP_PORT}")
    print("[HTTP] WebRTC:  http://IP_DE_TU_RASPBERRY:8081")
    print("[HTTP] MJPEG:   http://IP_DE_TU_RASPBERRY:8081/mjpeg")


def cleanup():
    global capture_running, camera_cap, capture_thread

    print("\n[CLEANUP] Cerrando recursos...")

    try:
        capture_running = False
        if capture_thread is not None and capture_thread.is_alive():
            capture_thread.join(timeout=2.0)
    except Exception as e:
        print(f"[CLEANUP] Error deteniendo hilo: {e}")

    try:
        if camera_cap is not None:
            camera_cap.release()
            print("[CLEANUP] Cámara liberada")
    except Exception as e:
        print(f"[CLEANUP] Error liberando cámara: {e}")


atexit.register(cleanup)


# WebRTC
class RaspberryCameraTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self):
        super().__init__()
        self._last_sent = 0.0
        self._frame_interval = 1.0 / CAMERA_FPS if CAMERA_FPS > 0 else 1.0 / 20.0

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        now = time.time()
        wait = self._frame_interval - (now - self._last_sent)
        if wait > 0:
            await asyncio.sleep(wait)

        frame = None
        while frame is None:
            with frame_lock:
                if latest_frame is not None:
                    frame = latest_frame.copy()

            if frame is None:
                await asyncio.sleep(0.001)

        self._last_sent = time.time()

        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame


async def wait_for_ice_gathering_complete(pc):
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.1)


# HTTP / AIOHTTP
@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=200)
    else:
        response = await handler(request)

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


async def index(request):
    return web.FileResponse(BASE_DIR / "index.html")


async def health(request):
    return web.json_response({"ok": True, "service": "raspberry_camera_webrtc"})


async def offer(request):
    try:
        params = await request.json()
        print("[WebRTC] /offer recibido")

        remote_offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
        pc = RTCPeerConnection()
        pcs.add(pc)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            print(f"[WebRTC] Connection state: {pc.connectionState}")
            print(f"[WebRTC] ICE connection state: {pc.iceConnectionState}")
            print(f"[WebRTC] ICE gathering state: {pc.iceGatheringState}")
            if pc.connectionState in ("failed", "closed", "disconnected"):
                await pc.close()
                pcs.discard(pc)

        await pc.setRemoteDescription(remote_offer)
        pc.addTrack(RaspberryCameraTrack())

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        await wait_for_ice_gathering_complete(pc)

        print("[WebRTC] SDP answer lista con candidatos ICE")

        return web.json_response(
            {
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
            }
        )

    except Exception as e:
        print(f"[WebRTC] Error en /offer: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def offer_options(request):
    return web.Response(status=200)


async def mjpeg_stream(request):
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "multipart/x-mixed-replace; boundary=frame",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Access-Control-Allow-Origin": "*",
        },
    )
    await response.prepare(request)

    try:
        while True:
            with frame_lock:
                if latest_frame is not None:
                    frame = latest_frame.copy()
                else:
                    frame = create_placeholder_frame(
                        IMAGE_W, IMAGE_H, "Esperando cámara..."
                    )

            ok, buffer = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
            )

            if ok:
                await response.write(b"--frame\r\n")
                await response.write(b"Content-Type: image/jpeg\r\n\r\n")
                await response.write(buffer.tobytes())
                await response.write(b"\r\n")

            await asyncio.sleep(1.0 / CAMERA_FPS if CAMERA_FPS > 0 else 0.05)

    except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
        pass
    except Exception as e:
        print(f"[MJPEG] Error: {e}")
    finally:
        try:
            await response.write_eof()
        except Exception:
            pass

    return response


async def on_shutdown(app):
    coros = [pc.close() for pc in pcs]
    if coros:
        await asyncio.gather(*coros)
    pcs.clear()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HTTP_HOST)
    parser.add_argument("--port", type=int, default=HTTP_PORT)
    parser.add_argument("--device", default=CAMERA_DEVICE, help="Ej: /dev/video0 o 0")
    args = parser.parse_args()

    setup_camera(args.device)

    app = web.Application(middlewares=[cors_middleware])
    app.on_shutdown.append(on_shutdown)

    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_post("/offer", offer)
    app.router.add_options("/offer", offer_options)
    app.router.add_get("/mjpeg", mjpeg_stream)

    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
