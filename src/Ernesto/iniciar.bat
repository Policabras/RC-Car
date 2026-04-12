@echo off

echo 🚀 Levantando infraestructura Docker...
docker-compose up -d --build

echo ⏳ Esperando MQTT...
timeout /t 10 /nobreak

echo 🐍 Ejecutando bridge serial...
start "BRIDGE" cmd /k "py esp32-serial\bridge_final.py"

echo 🎥 Ejecutando camara...
start "CAMERA" cmd /k "py camera\camera_server.py"

echo ⏳ Esperando backend...
timeout /t 5 /nobreak

echo 🌍 Abriendo dashboard...
start http://localhost:5173

echo 📜 Logs Docker:
docker-compose logs -f

echo 🛑 Cerrando cámara...
taskkill /FI "WINDOWTITLE eq CAMERA*" /T /F

echo 🛑 Cerrando bridge...
taskkill /FI "WINDOWTITLE eq BRIDGE*" /T /F