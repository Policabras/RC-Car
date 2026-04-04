# Cámara WebRTC en Raspberry

## Archivos

* `raspberry_cam_streaming.py`: servidor de streaming WebRTC
* `index.html`: interfaz web
* `camera-stream.service`: servicio de systemd

## Requisitos

* Raspberry con cámara disponible en `/dev/video0`
* Entorno virtual en:

  * `/home/charly/projects/RC-Car/.venv`
* Dependencias instaladas dentro del entorno virtual

## Ejecutar manualmente

Desde esta carpeta:

```bash
cd /home/charly/projects/RC-Car/src/raspberry_testing/camera
/home/charly/projects/RC-Car/.venv/bin/python raspberry_cam_streaming.py --device /dev/video0
```

Luego abrir en el navegador:

```bash
http://IP_DE_LA_RASPBERRY:8081
```

## Levantar con systemd

Copiar el archivo del servicio:

```bash
sudo cp camera-stream.service /etc/systemd/system/camera-stream.service
```

Recargar y habilitar:

```bash
sudo systemctl daemon-reload
sudo systemctl enable camera-stream.service
sudo systemctl start camera-stream.service
```

## Verificar estado

```bash
sudo systemctl status camera-stream.service
```

## Ver logs en vivo

```bash
journalctl -u camera-stream.service -f
```

## Reiniciar servicio

```bash
sudo systemctl restart camera-stream.service
```

## Detener servicio

```bash
sudo systemctl stop camera-stream.service
```

## Nota

El archivo del servicio debe quedar en esta ruta:

```bash
/etc/systemd/system/camera-stream.service
```
