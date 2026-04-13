from __future__ import annotations

import argparse
import asyncio
import atexit
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame


# =========================================================
# Configuración general
# =========================================================
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8081

# OJO:
# video0/video1 = mismo dispositivo UVC Camera
# video2/video3 = Logitech C920
# Para dos cámaras físicas, usa normalmente video0 + video2
DEFAULT_CAMERA_0 = "/dev/video0"
DEFAULT_CAMERA_1 = "/dev/video4"

IMAGE_W = 640
IMAGE_H = 480
CAMERA_FPS = 20
JPEG_QUALITY = 80
REOPEN_INTERVAL_SEC = 2.0

BASE_DIR = Path(__file__).resolve().parent

pcs: set[RTCPeerConnection] = set()


# =========================================================
# Estado de cámara
# =========================================================
@dataclass
class CameraState:
    camera_id: str
    device: str | int
    label: str
    frame_lock: threading.Lock = field(default_factory=threading.Lock)
    latest_frame: np.ndarray | None = None
    cap: cv2.VideoCapture | None = None
    capture_thread: threading.Thread | None = None
    capture_running: bool = False
    available: bool = False
    last_error: str = ""
    last_open_attempt: float = 0.0


camera_states: dict[str, CameraState] = {}


# =========================================================
# Helpers
# =========================================================
def create_placeholder_frame(width: int, height: int, text: str = "Esperando cámara...") -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    cv2.rectangle(frame, (0, 0), (width - 1, height - 1), (80, 80, 80), 2)
    cv2.putText(
        frame,
        text,
        (20, height // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return frame


def normalize_device(device: str | int) -> str | int:
    if isinstance(device, str) and device.isdigit():
        return int(device)
    return device


def safe_release(cap: cv2.VideoCapture | None) -> None:
    if cap is None:
        return
    try:
        cap.release()
    except Exception:
        pass


def configure_capture(cap: cv2.VideoCapture) -> None:
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, IMAGE_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, IMAGE_H)
    cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)


def open_camera_capture(device: str | int) -> cv2.VideoCapture | None:
    """
    Intenta abrir la cámara con varios modos.
    Si falla uno, prueba el siguiente. Linux con V4L2 a veces se pone exquisito.
    """
    normalized_device = normalize_device(device)
    attempts: list[tuple[str, Any]] = []

    if isinstance(normalized_device, int):
        attempts.append(("V4L2-int", lambda: cv2.VideoCapture(normalized_device, cv2.CAP_V4L2)))
        attempts.append(("AUTO-int", lambda: cv2.VideoCapture(normalized_device)))
    else:
        attempts.append(("V4L2-path", lambda: cv2.VideoCapture(normalized_device, cv2.CAP_V4L2)))
        attempts.append(("AUTO-path", lambda: cv2.VideoCapture(normalized_device)))

    for mode_name, factory in attempts:
        cap: cv2.VideoCapture | None = None
        try:
            cap = factory()
            if cap is not None and cap.isOpened():
                configure_capture(cap)
                print(f"[CAM OPEN] Apertura exitosa con {mode_name}: {normalized_device}")
                return cap
        except Exception as exc:
            print(f"[CAM OPEN] Error con {mode_name} en {normalized_device}: {exc}")
        finally:
            if cap is not None and not cap.isOpened():
                safe_release(cap)

    return None


def get_camera_state(camera_id: str) -> CameraState:
    if camera_id not in camera_states:
        raise web.HTTPNotFound(
            text=f"Camera '{camera_id}' no existe. Usa 0 o 1."
        )
    return camera_states[camera_id]


# =========================================================
# Lógica de cámara
# =========================================================
def camera_capture_loop(camera_id: str) -> None:
    state = camera_states[camera_id]
    print(f"[CAM {camera_id}] Hilo de captura iniciado")

    while state.capture_running:
        if state.cap is None or not state.cap.isOpened():
            now = time.time()

            if now - state.last_open_attempt >= REOPEN_INTERVAL_SEC:
                state.last_open_attempt = now
                print(f"[CAM {camera_id}] Reintentando apertura: {state.device}")
                state.cap = open_camera_capture(state.device)

                if state.cap is not None and state.cap.isOpened():
                    state.available = True
                    state.last_error = ""
                    print(f"[CAM {camera_id}] Cámara recuperada correctamente")
                    print(f"[CAM {camera_id}] width      = {state.cap.get(cv2.CAP_PROP_FRAME_WIDTH)}")
                    print(f"[CAM {camera_id}] height     = {state.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)}")
                    print(f"[CAM {camera_id}] fps        = {state.cap.get(cv2.CAP_PROP_FPS)}")
                    print(f"[CAM {camera_id}] buffersize = {state.cap.get(cv2.CAP_PROP_BUFFERSIZE)}")
                else:
                    state.available = False
                    state.last_error = f"No pude abrir la cámara {camera_id}: {state.device}"

            with state.frame_lock:
                state.latest_frame = create_placeholder_frame(
                    IMAGE_W,
                    IMAGE_H,
                    f"Cam {camera_id} no disponible",
                )

            time.sleep(0.2)
            continue

        ret, frame = state.cap.read()

        if not ret or frame is None:
            state.available = False
            state.last_error = f"Sin frames de la cámara {camera_id}"

            with state.frame_lock:
                state.latest_frame = create_placeholder_frame(
                    IMAGE_W,
                    IMAGE_H,
                    f"Sin frames cam {camera_id}",
                )

            safe_release(state.cap)
            state.cap = None
            time.sleep(0.1)
            continue

        state.available = True
        state.last_error = ""

        if frame.shape[1] != IMAGE_W or frame.shape[0] != IMAGE_H:
            frame = cv2.resize(frame, (IMAGE_W, IMAGE_H))

        with state.frame_lock:
            state.latest_frame = frame.copy()


def setup_single_camera(camera_id: str, device: str | int, label: str) -> None:
    state = CameraState(
        camera_id=camera_id,
        device=normalize_device(device),
        label=label,
    )
    camera_states[camera_id] = state

    with state.frame_lock:
        state.latest_frame = create_placeholder_frame(
            IMAGE_W,
            IMAGE_H,
            f"Inicializando cam {camera_id}...",
        )

    print(f"[CAM {camera_id}] Intentando abrir cámara: {state.device}")
    state.cap = open_camera_capture(state.device)

    if state.cap is not None and state.cap.isOpened():
        state.available = True
        state.last_error = ""
        print(f"[CAM {camera_id}] Cámara abierta correctamente")
        print(f"[CAM {camera_id}] width      = {state.cap.get(cv2.CAP_PROP_FRAME_WIDTH)}")
        print(f"[CAM {camera_id}] height     = {state.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)}")
        print(f"[CAM {camera_id}] fps        = {state.cap.get(cv2.CAP_PROP_FPS)}")
        print(f"[CAM {camera_id}] buffersize = {state.cap.get(cv2.CAP_PROP_BUFFERSIZE)}")
    else:
        state.available = False
        state.last_error = f"No pude abrir la cámara {camera_id}: {state.device}"
        print(f"[CAM {camera_id}] AVISO: {state.last_error}")
        print(f"[CAM {camera_id}] El servicio seguirá vivo con placeholder")

    state.capture_running = True
    state.capture_thread = threading.Thread(
        target=camera_capture_loop,
        args=(camera_id,),
        daemon=True,
    )
    state.capture_thread.start()


def setup_cameras(device0: str | int, device1: str | int) -> None:
    setup_single_camera("0", device0, "Cámara delantera")
    setup_single_camera("1", device1, "Cámara trasera")

    print(f"[HTTP] Backend disponible en http://{HTTP_HOST}:{HTTP_PORT}")
    print("[HTTP] MJPEG cam 0: http://IP_DE_TU_RASPBERRY:8081/mjpeg/0")
    print("[HTTP] MJPEG cam 1: http://IP_DE_TU_RASPBERRY:8081/mjpeg/1")
    print("[HTTP] WebRTC cam 0: POST http://IP_DE_TU_RASPBERRY:8081/offer/0")
    print("[HTTP] WebRTC cam 1: POST http://IP_DE_TU_RASPBERRY:8081/offer/1")


def cleanup() -> None:
    print("\n[CLEANUP] Cerrando recursos...")

    for camera_id, state in camera_states.items():
        try:
            state.capture_running = False
            if state.capture_thread is not None and state.capture_thread.is_alive():
                state.capture_thread.join(timeout=2.0)
        except Exception as exc:
            print(f"[CLEANUP] Error deteniendo hilo cam {camera_id}: {exc}")

        try:
            safe_release(state.cap)
            print(f"[CLEANUP] Cámara {camera_id} liberada")
        except Exception as exc:
            print(f"[CLEANUP] Error liberando cámara {camera_id}: {exc}")


atexit.register(cleanup)


# =========================================================
# WebRTC
# =========================================================
class RaspberryCameraTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self, camera_id: str):
        super().__init__()
        self.camera_id = camera_id
        self._last_sent = 0.0
        self._frame_interval = 1.0 / CAMERA_FPS if CAMERA_FPS > 0 else 1.0 / 20.0

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()

        now = time.time()
        wait = self._frame_interval - (now - self._last_sent)
        if wait > 0:
            await asyncio.sleep(wait)

        state = get_camera_state(self.camera_id)

        frame = None
        while frame is None:
            with state.frame_lock:
                if state.latest_frame is not None:
                    frame = state.latest_frame.copy()

            if frame is None:
                await asyncio.sleep(0.001)

        self._last_sent = time.time()

        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame


async def wait_for_ice_gathering_complete(pc: RTCPeerConnection) -> None:
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.1)


# =========================================================
# HTTP / AIOHTTP
# =========================================================
@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=200)
    else:
        response = await handler(request)

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


async def index(request: web.Request) -> web.Response:
    html = """
    <html>
      <head>
        <title>Raspberry Multi Camera</title>
        <style>
          body { font-family: Arial, sans-serif; background:#0b1020; color:#fff; padding:20px; }
          a { color:#7dd3fc; }
          .card { background:#121a2f; padding:16px; border-radius:12px; margin-bottom:12px; }
        </style>
      </head>
      <body>
        <h1>Raspberry Multi Camera Streaming</h1>
        <div class="card">
          <p><a href="/health">/health</a></p>
          <p><a href="/mjpeg/0">/mjpeg/0</a></p>
          <p><a href="/mjpeg/1">/mjpeg/1</a></p>
        </div>
      </body>
    </html>
    """
    return web.Response(text=html, content_type="text/html")


async def health(request: web.Request) -> web.Response:
    cameras: dict[str, dict[str, Any]] = {}

    for camera_id, state in camera_states.items():
        cameras[camera_id] = {
            "label": state.label,
            "device": str(state.device),
            "available": state.available,
            "opened": bool(state.cap is not None and state.cap.isOpened()),
            "thread_alive": bool(
                state.capture_thread is not None and state.capture_thread.is_alive()
            ),
            "last_error": state.last_error,
        }

    return web.json_response(
        {
            "ok": True,
            "service": "raspberry_camera_multi",
            "cameras": cameras,
        }
    )


async def offer(request: web.Request) -> web.Response:
    camera_id = request.match_info.get("camera_id", "0")
    get_camera_state(camera_id)

    try:
        params = await request.json()
        print(f"[WebRTC] /offer/{camera_id} recibido")

        remote_offer = RTCSessionDescription(
            sdp=params["sdp"],
            type=params["type"],
        )

        pc = RTCPeerConnection()
        pcs.add(pc)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            print(f"[WebRTC {camera_id}] Connection state: {pc.connectionState}")
            print(f"[WebRTC {camera_id}] ICE connection state: {pc.iceConnectionState}")
            print(f"[WebRTC {camera_id}] ICE gathering state: {pc.iceGatheringState}")

            if pc.connectionState in ("failed", "closed", "disconnected"):
                await pc.close()
                pcs.discard(pc)

        await pc.setRemoteDescription(remote_offer)
        pc.addTrack(RaspberryCameraTrack(camera_id))

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        await wait_for_ice_gathering_complete(pc)

        print(f"[WebRTC] SDP answer lista para cámara {camera_id}")

        return web.json_response(
            {
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
                "camera_id": camera_id,
            }
        )

    except Exception as exc:
        print(f"[WebRTC] Error en /offer/{camera_id}: {exc}")
        return web.json_response({"error": str(exc)}, status=500)


async def offer_options(request: web.Request) -> web.Response:
    return web.Response(status=200)


async def mjpeg_stream(request: web.Request) -> web.StreamResponse:
    camera_id = request.match_info.get("camera_id", "0")
    state = get_camera_state(camera_id)

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
            with state.frame_lock:
                if state.latest_frame is not None:
                    frame = state.latest_frame.copy()
                else:
                    frame = create_placeholder_frame(
                        IMAGE_W,
                        IMAGE_H,
                        f"Esperando cámara {camera_id}...",
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
    except Exception as exc:
        print(f"[MJPEG {camera_id}] Error: {exc}")
    finally:
        try:
            await response.write_eof()
        except Exception:
            pass

    return response


async def on_shutdown(app: web.Application) -> None:
    coros = [pc.close() for pc in pcs]
    if coros:
        await asyncio.gather(*coros)
    pcs.clear()


# =========================================================
# Main
# =========================================================
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HTTP_HOST)
    parser.add_argument("--port", type=int, default=HTTP_PORT)
    parser.add_argument(
        "--device0",
        default=DEFAULT_CAMERA_0,
        help="Primera cámara física. Ej: /dev/video0",
    )
    parser.add_argument(
        "--device1",
        default=DEFAULT_CAMERA_1,
        help="Segunda cámara física. Ej: /dev/video2",
    )
    args = parser.parse_args()

    setup_cameras(args.device0, args.device1)

    app = web.Application(middlewares=[cors_middleware])
    app.on_shutdown.append(on_shutdown)

    app.router.add_get("/", index)
    app.router.add_get("/health", health)

    # WebRTC
    app.router.add_post("/offer", offer)  # default -> cámara 0
    app.router.add_post("/offer/{camera_id}", offer)
    app.router.add_options("/offer", offer_options)
    app.router.add_options("/offer/{camera_id}", offer_options)

    # MJPEG
    app.router.add_get("/mjpeg", mjpeg_stream)  # default -> cámara 0
    app.router.add_get("/mjpeg/{camera_id}", mjpeg_stream)

    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
