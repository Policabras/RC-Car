import argparse
import asyncio
import atexit
import random
import threading

import carla
import numpy as np
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame

# =========================
# Configuración
# =========================
CARLA_HOST = "127.0.0.1"
CARLA_PORT = 2000

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8081

IMAGE_W = 640
IMAGE_H = 360
FOV = 90
SENSOR_TICK = 0.0

CAM_X = 1.8
CAM_Y = 0.0
CAM_Z = 1.4
CAM_PITCH = -5.0
CAM_YAW = 0.0
CAM_ROLL = 0.0

pcs = set()

frame_lock = threading.Lock()
latest_frame = None

client = None
world = None
vehicle = None
camera = None
spawned_vehicle = False


# =========================
# HTML incrustado
# =========================
INDEX_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Prueba WebRTC CARLA</title>
  <style>
    body {
      margin: 0;
      padding: 24px;
      background: #0b1020;
      color: #eaf0ff;
      font-family: Arial, sans-serif;
    }
    .wrap {
      max-width: 1100px;
      margin: 0 auto;
    }
    .card {
      background: #121a2f;
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 18px 50px rgba(0,0,0,0.35);
    }
    h1 {
      margin: 0 0 12px;
    }
    .top {
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }
    button {
      padding: 10px 14px;
      border-radius: 10px;
      border: 0;
      background: #2dd4bf;
      color: #05131b;
      font-weight: 700;
      cursor: pointer;
    }
    button:disabled {
      opacity: 0.65;
      cursor: not-allowed;
    }
    video {
      width: 100%;
      border-radius: 14px;
      background: #000;
      display: block;
      aspect-ratio: 16 / 9;
      object-fit: cover;
    }
    .meta {
      margin-top: 12px;
      color: #a8b3cf;
      font-size: 0.95rem;
      white-space: pre-wrap;
    }
    .ok { color: #22c55e; }
    .bad { color: #ef4444; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Prueba WebRTC CARLA</h1>

    <div class="top">
      <button id="startBtn">Iniciar video</button>
      <span id="statusText">Esperando conexión...</span>
    </div>

    <div class="card">
      <video id="video" autoplay playsinline muted></video>
      <div class="meta" id="meta">Listo para iniciar.</div>
    </div>
  </div>

  <script>
    const videoEl = document.getElementById("video");
    const metaEl = document.getElementById("meta");
    const statusText = document.getElementById("statusText");
    const startBtn = document.getElementById("startBtn");

    let pc = null;

    function setStatus(text, ok = false) {
      statusText.textContent = text;
      statusText.className = ok ? "ok" : "bad";
    }

    function waitForIceGatheringComplete(peer) {
      return new Promise((resolve) => {
        if (peer.iceGatheringState === "complete") {
          resolve();
          return;
        }

        function checkState() {
          if (peer.iceGatheringState === "complete") {
            peer.removeEventListener("icegatheringstatechange", checkState);
            resolve();
          }
        }

        peer.addEventListener("icegatheringstatechange", checkState);
      });
    }

    async function startWebRTC() {
      startBtn.disabled = true;
      setStatus("Conectando...", false);
      metaEl.textContent = "Creando RTCPeerConnection...";

      pc = new RTCPeerConnection({
        iceServers: [
          { urls: "stun:stun.l.google.com:19302" }
        ]
      });

      pc.addEventListener("icecandidateerror", (event) => {
        console.error("ICE candidate error:", event);
      });

      pc.addEventListener("iceconnectionstatechange", () => {
        console.log("iceConnectionState:", pc.iceConnectionState);
      });

      pc.addEventListener("icegatheringstatechange", () => {
        console.log("iceGatheringState:", pc.iceGatheringState);
      });

      pc.addEventListener("connectionstatechange", () => {
        const txt =
          `connection=${pc.connectionState}\\n` +
          `iceConnection=${pc.iceConnectionState}\\n` +
          `iceGathering=${pc.iceGatheringState}`;
        metaEl.textContent = txt;

        if (pc.connectionState === "connected") {
          setStatus("Video conectado", true);
        } else if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
          setStatus(`Estado: ${pc.connectionState}`, false);
        }
      });

      pc.ontrack = (event) => {
        videoEl.srcObject = event.streams[0];
      };

      pc.addTransceiver("video", { direction: "recvonly" });

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitForIceGatheringComplete(pc);

      const response = await fetch("/offer", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          sdp: pc.localDescription.sdp,
          type: pc.localDescription.type
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status} al pedir /offer`);
      }

      const answer = await response.json();
      await pc.setRemoteDescription(answer);

      setStatus("Oferta enviada. Esperando video...", false);
    }

    startBtn.addEventListener("click", async () => {
      try {
        await startWebRTC();
      } catch (err) {
        console.error(err);
        metaEl.textContent = `Error: ${err.message}`;
        setStatus("Error de conexión", false);
        startBtn.disabled = false;
      }
    });

    window.addEventListener("beforeunload", () => {
      if (pc) {
        pc.close();
      }
    });
  </script>
</body>
</html>
"""


# =========================
# CARLA
# =========================
def find_or_spawn_vehicle(world_obj):
    global spawned_vehicle

    vehicles = world_obj.get_actors().filter("vehicle.*")

    for v in vehicles:
        if v.attributes.get("role_name") == "hero":
            print(f"[CARLA] Usando hero: id={v.id}, type={v.type_id}")
            return v

    if len(vehicles) > 0:
        v = vehicles[0]
        print(f"[CARLA] No hay hero. Usando primer vehículo: id={v.id}, type={v.type_id}")
        return v

    print("[CARLA] No hay vehículos. Intentando spawnear uno...")
    blueprint_library = world_obj.get_blueprint_library()

    candidates = blueprint_library.filter("vehicle.tesla.model3")
    if not candidates:
        candidates = blueprint_library.filter("vehicle.*")

    if not candidates:
        raise RuntimeError("No encontré blueprints de vehículos.")

    bp = random.choice(candidates)
    if bp.has_attribute("role_name"):
        bp.set_attribute("role_name", "hero")

    spawn_points = world_obj.get_map().get_spawn_points()
    if not spawn_points:
        raise RuntimeError("No hay spawn points disponibles.")

    for sp in spawn_points:
        actor = world_obj.try_spawn_actor(bp, sp)
        if actor is not None:
            spawned_vehicle = True
            actor.set_autopilot(True)
            print(f"[CARLA] Vehículo creado: id={actor.id}, type={actor.type_id}")
            return actor

    raise RuntimeError("No pude spawnear un vehículo.")


def camera_callback(image):
    global latest_frame

    frame = np.frombuffer(image.raw_data, dtype=np.uint8)
    frame = frame.reshape((image.height, image.width, 4))
    frame = frame[:, :, :3].copy()  # BGRA -> BGR

    with frame_lock:
        latest_frame = frame


def setup_carla():
    global client, world, vehicle, camera

    print(f"[CARLA] Conectando a {CARLA_HOST}:{CARLA_PORT} ...")
    client = carla.Client(CARLA_HOST, CARLA_PORT)
    client.set_timeout(10.0)

    world = client.get_world()
    print("[CARLA] Conectado al mundo")

    vehicle = find_or_spawn_vehicle(world)

    bp = world.get_blueprint_library().find("sensor.camera.rgb")
    bp.set_attribute("image_size_x", str(IMAGE_W))
    bp.set_attribute("image_size_y", str(IMAGE_H))
    bp.set_attribute("fov", str(FOV))
    bp.set_attribute("sensor_tick", str(SENSOR_TICK))

    if bp.has_attribute("enable_postprocess_effects"):
        bp.set_attribute("enable_postprocess_effects", "false")

    transform = carla.Transform(
        carla.Location(x=CAM_X, y=CAM_Y, z=CAM_Z),
        carla.Rotation(pitch=CAM_PITCH, yaw=CAM_YAW, roll=CAM_ROLL),
    )

    camera = world.spawn_actor(bp, transform, attach_to=vehicle)
    camera.listen(camera_callback)

    print(f"[CARLA] Cámara creada: id={camera.id}")
    print(f"[HTTP] Backend WebRTC en http://{HTTP_HOST}:{HTTP_PORT}")
    print(f"[HTTP] En tu red local abre: http://192.168.0.222:{HTTP_PORT}")


def cleanup():
    global camera, vehicle

    print("\\n[CLEANUP] Cerrando recursos...")

    try:
        if camera is not None:
            try:
                camera.stop()
            except Exception:
                pass
            camera.destroy()
            print("[CLEANUP] Cámara destruida")
    except Exception as e:
        print(f"[CLEANUP] Error destruyendo cámara: {e}")

    try:
        if spawned_vehicle and vehicle is not None:
            vehicle.destroy()
            print("[CLEANUP] Vehículo destruido")
    except Exception as e:
        print(f"[CLEANUP] Error destruyendo vehículo: {e}")


atexit.register(cleanup)


# =========================
# WebRTC
# =========================
class CarlaVideoTrack(VideoStreamTrack):
    kind = "video"

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        frame = None
        while frame is None:
            with frame_lock:
                if latest_frame is not None:
                    frame = latest_frame.copy()
            if frame is None:
                await asyncio.sleep(0.005)

        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame


async def wait_for_ice_gathering_complete(pc):
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.1)


# =========================
# HTTP / AIOHTTP
# =========================
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
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def health(request):
    return web.json_response({"ok": True, "service": "camera_webrtc"})


async def offer(request):
    try:
        params = await request.json()
        print("[WebRTC] /offer recibido")

        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
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

        await pc.setRemoteDescription(offer)
        pc.addTrack(CarlaVideoTrack())

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        # Esperar a que junte candidatos ICE antes de responder
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


async def on_shutdown(app):
    coros = [pc.close() for pc in pcs]
    if coros:
        await asyncio.gather(*coros)
    pcs.clear()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HTTP_HOST)
    parser.add_argument("--port", type=int, default=HTTP_PORT)
    args = parser.parse_args()

    setup_carla()

    app = web.Application(middlewares=[cors_middleware])
    app.on_shutdown.append(on_shutdown)

    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_post("/offer", offer)
    app.router.add_options("/offer", offer_options)

    web.run_app(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()