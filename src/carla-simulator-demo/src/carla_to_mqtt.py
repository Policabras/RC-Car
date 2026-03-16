import json
import math
import os
import random
import socket
import time

import carla
import paho.mqtt.client as mqtt


MQTT_HOST = "192.168.0.106"
MQTT_PORT = 1883
MQTT_TOPIC = "carla/robot01/dashboard"

CARLA_HOST = "localhost"
CARLA_PORT = 2000

PUBLISH_HZ = 10.0
PUBLISH_DT = 1.0 / PUBLISH_HZ

# Parámetros "robot"
TRACK_WIDTH_M = 0.30          # separación estimada entre ruedas
ENC_TICKS_PER_METER = 1200    # estimación para encoders
BATTERY_CAPACITY_WH = 240.0   # batería simulada
BATTERY_NOMINAL_V = 24.0
BATTERY_MIN_V = 21.0
BATTERY_MAX_V = 25.2
AMBIENT_TEMP_C = 27.0


def clamp(value, min_value, max_value):
    return max(min_value, min(value, max_value))


def norm_xy(v):
    return math.sqrt(v.x * v.x + v.y * v.y)


def format_hhmm(hours_remaining):
    total_minutes = max(0, int(hours_remaining * 60))
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}"


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[MQTT] Conectado rc={reason_code}")
    print(f"[MQTT] is_connected={client.is_connected()}")


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    print(f"[MQTT] Desconectado rc={reason_code}")


def on_log(client, userdata, level, buf):
    # Si quieres menos ruido, comenta esta línea
    # print(f"[MQTT-LOG] {buf}")
    pass


def find_hero_vehicle(world):
    vehicles = world.get_actors().filter("vehicle.*")
    print(f"[CARLA] Vehículos detectados: {len(vehicles)}")

    for v in vehicles:
        if v.attributes.get("role_name") == "hero":
            print(f"[CARLA] Vehículo hero encontrado: id={v.id}, type={v.type_id}")
            return v

    if len(vehicles) > 0:
        v = vehicles[0]
        print(f"[CARLA] No hay hero. Usando el primero: id={v.id}, type={v.type_id}")
        return v

    return None


def attach_imu_sensor(world, vehicle, sensor_state):
    bp_lib = world.get_blueprint_library()
    imu_bp = bp_lib.find("sensor.other.imu")

    # Ajustes suaves
    imu_bp.set_attribute("sensor_tick", str(PUBLISH_DT))

    imu_transform = carla.Transform(carla.Location(x=0.0, z=1.5))
    imu_sensor = world.spawn_actor(imu_bp, imu_transform, attach_to=vehicle)

    def imu_callback(data):
        sensor_state["imu_accel_x"] = data.accelerometer.x
        sensor_state["imu_accel_y"] = data.accelerometer.y
        sensor_state["imu_accel_z"] = data.accelerometer.z
        sensor_state["imu_gyro_x"] = data.gyroscope.x
        sensor_state["imu_gyro_y"] = data.gyroscope.y
        sensor_state["imu_gyro_z"] = data.gyroscope.z
        sensor_state["imu_yaw_rate"] = data.gyroscope.z  # rad/s

    imu_sensor.listen(imu_callback)
    print(f"[CARLA] IMU adjuntada: id={imu_sensor.id}")
    return imu_sensor


def attach_collision_sensor(world, vehicle, sensor_state):
    bp_lib = world.get_blueprint_library()
    col_bp = bp_lib.find("sensor.other.collision")
    col_transform = carla.Transform(carla.Location(x=0.0, z=1.5))
    col_sensor = world.spawn_actor(col_bp, col_transform, attach_to=vehicle)

    def collision_callback(event):
        impulse = event.normal_impulse
        intensity = math.sqrt(
            impulse.x * impulse.x +
            impulse.y * impulse.y +
            impulse.z * impulse.z
        )
        sensor_state["collision_count"] += 1
        sensor_state["last_collision_intensity"] = intensity
        sensor_state["last_collision_time"] = time.time()

    col_sensor.listen(collision_callback)
    print(f"[CARLA] Collision sensor adjuntado: id={col_sensor.id}")
    return col_sensor


def infer_mode(control, linear_speed):
    if control.reverse:
        return "REVERSE"
    if linear_speed < 0.05 and control.throttle < 0.05 and control.brake < 0.05:
        return "IDLE"
    if control.brake > 0.2:
        return "BRAKING"
    return "MANUAL"


def estimate_pwm_per_wheel(control):
    # Mezcla simple tipo robot diferencial
    direction = -1.0 if control.reverse else 1.0
    base = direction * (control.throttle * 100.0)
    steer_mix = control.steer * 35.0

    pwm_left = clamp(base - steer_mix, -100.0, 100.0)
    pwm_right = clamp(base + steer_mix, -100.0, 100.0)

    # si frena, bajamos agresivamente
    if control.brake > 0.01:
        brake_penalty = control.brake * 100.0
        pwm_left = clamp(pwm_left - brake_penalty, -100.0, 100.0)
        pwm_right = clamp(pwm_right - brake_penalty, -100.0, 100.0)

    return pwm_left, pwm_right


def estimate_power_use_w(control, linear_speed, angular_speed):
    # Modelo estimado para dashboard
    base_w = 18.0
    drive_w = 140.0 * control.throttle
    brake_w = 30.0 * control.brake
    steer_w = 18.0 * abs(control.steer)
    motion_w = 10.0 * linear_speed
    turn_w = 6.0 * abs(angular_speed)

    return max(8.0, base_w + drive_w + brake_w + steer_w + motion_w + turn_w)


def health_state(connection, battery_percent, last_collision_age_s):
    if not connection:
        return "LINK_DOWN"
    if battery_percent < 15.0:
        return "LOW_BATTERY"
    if last_collision_age_s < 3.0:
        return "IMPACT"
    if battery_percent < 35.0:
        return "WARNING"
    return "NOMINAL"


def main():
    client_id = f"carla_bridge_{socket.gethostname()}_{os.getpid()}"
    print(f"[INFO] Iniciando bridge CARLA -> MQTT client_id={client_id}")

    client_mqtt = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv311,
    )
    client_mqtt.on_connect = on_connect
    client_mqtt.on_disconnect = on_disconnect
    client_mqtt.on_log = on_log
    client_mqtt.reconnect_delay_set(min_delay=1, max_delay=10)

    # Si tu broker usa auth:
    # client_mqtt.username_pw_set("tu_usuario", "tu_password")

    print(f"[MQTT] Conectando a {MQTT_HOST}:{MQTT_PORT} ...")
    rc = client_mqtt.connect(MQTT_HOST, MQTT_PORT, 60)
    print(f"[MQTT] connect() rc={rc}")
    client_mqtt.loop_start()

    print(f"[CARLA] Conectando a {CARLA_HOST}:{CARLA_PORT} ...")
    client_carla = carla.Client(CARLA_HOST, CARLA_PORT)
    client_carla.set_timeout(10.0)

    world = client_carla.get_world()
    print("[CARLA] Conectado al mundo")

    vehicle = find_hero_vehicle(world)
    if vehicle is None:
        raise RuntimeError("No encontré un vehículo para publicar telemetría.")

    sensor_state = {
        "imu_accel_x": 0.0,
        "imu_accel_y": 0.0,
        "imu_accel_z": 0.0,
        "imu_gyro_x": 0.0,
        "imu_gyro_y": 0.0,
        "imu_gyro_z": 0.0,
        "imu_yaw_rate": 0.0,
        "collision_count": 0,
        "last_collision_intensity": 0.0,
        "last_collision_time": 0.0,
    }

    imu_sensor = attach_imu_sensor(world, vehicle, sensor_state)
    collision_sensor = attach_collision_sensor(world, vehicle, sensor_state)

    last_ts = time.time()
    last_publish_ts = last_ts
    counter = 0

    enc_left = 0
    enc_right = 0

    battery_energy_wh = BATTERY_CAPACITY_WH
    battery_temp_c = AMBIENT_TEMP_C + 2.0
    temp_mcu_c = AMBIENT_TEMP_C + 8.0
    signal_dbm = -48

    try:
        while True:
            loop_start = time.time()

            now = time.time()
            dt = now - last_ts if now > last_ts else PUBLISH_DT
            last_ts = now

            transform = vehicle.get_transform()
            velocity = vehicle.get_velocity()
            angular_velocity = vehicle.get_angular_velocity()
            control = vehicle.get_control()

            # Cinemática real de CARLA
            linear_speed = norm_xy(velocity)  # m/s
            angular_speed = math.radians(angular_velocity.z)  # rad/s aprox
            heading_deg = transform.rotation.yaw

            # Velocidades de rueda estimadas como robot diferencial
            left_wheel = linear_speed - (TRACK_WIDTH_M / 2.0) * angular_speed
            right_wheel = linear_speed + (TRACK_WIDTH_M / 2.0) * angular_speed

            # Encoders acumulados estimados
            enc_left += int(left_wheel * ENC_TICKS_PER_METER * dt)
            enc_right += int(right_wheel * ENC_TICKS_PER_METER * dt)

            # PWM por rueda estimado a partir del control
            pwm_left, pwm_right = estimate_pwm_per_wheel(control)

            # Modelo de energía/temperatura estimado
            power_use = estimate_power_use_w(control, linear_speed, angular_speed)
            battery_energy_wh = max(
                0.0,
                battery_energy_wh - (power_use * dt / 3600.0)
            )
            battery_percent = 100.0 * battery_energy_wh / BATTERY_CAPACITY_WH
            battery_voltage = BATTERY_MIN_V + (
                (BATTERY_MAX_V - BATTERY_MIN_V) * (battery_percent / 100.0)
            )
            battery_voltage = clamp(battery_voltage, BATTERY_MIN_V, BATTERY_MAX_V)
            battery_current = power_use / max(battery_voltage, 1e-6)
            current_total = battery_current

            hours_remaining = battery_energy_wh / max(power_use, 1e-6)
            battery_time = format_hhmm(hours_remaining)

            # Temperaturas con respuesta lenta
            target_battery_temp = AMBIENT_TEMP_C + 3.0 + (power_use * 0.030)
            target_mcu_temp = AMBIENT_TEMP_C + 10.0 + (power_use * 0.050)
            battery_temp_c += (target_battery_temp - battery_temp_c) * 0.08
            temp_mcu_c += (target_mcu_temp - temp_mcu_c) * 0.10

            # Señal simulada estable con pequeña variación
            signal_dbm += random.choice([-1, 0, 0, 0, 1])
            signal_dbm = int(clamp(signal_dbm, -72, -42))

            # Salud del sistema
            last_collision_age_s = (
                now - sensor_state["last_collision_time"]
                if sensor_state["last_collision_time"] > 0
                else 9999.0
            )
            health = health_state(
                client_mqtt.is_connected(),
                battery_percent,
                last_collision_age_s,
            )

            # Errores: usamos contador de colisiones
            errors = sensor_state["collision_count"]

            # Latencia estimada del bridge
            latency_ms = (now - last_publish_ts) * 1000.0
            last_publish_ts = now

            mode = infer_mode(control, linear_speed)

            payload = {
                # Top bar
                "connection": client_mqtt.is_connected(),
                "mode": mode,
                "lastUpdateS": round(dt, 3),

                # Gauges
                "linearSpeed": round(linear_speed, 3),
                "angularSpeed": round(angular_speed, 3),

                # Battery
                "batteryPercent": round(battery_percent, 1),
                "batteryTime": battery_time,
                "batteryVoltage": round(battery_voltage, 2),
                "batteryCurrent": round(battery_current, 2),
                "batteryTemp": round(battery_temp_c, 2),

                # Localization / low-level
                "posX": round(transform.location.x, 3),
                "posY": round(transform.location.y, 3),
                "headingDeg": round(heading_deg, 2),
                "tempMcu": round(temp_mcu_c, 2),
                "leftWheel": round(left_wheel, 3),
                "rightWheel": round(right_wheel, 3),

                # Health card
                "currentTotal": round(current_total, 2),
                "powerUse": round(power_use, 2),
                "latency": round(latency_ms, 1),
                "signal": signal_dbm,
                "health": health,

                # Diagnostics
                "pwmLeft": round(pwm_left, 1),
                "pwmRight": round(pwm_right, 1),
                "encLeft": int(enc_left),
                "encRight": int(enc_right),
                "imuYawRate": round(sensor_state["imu_yaw_rate"], 3),
                "errors": int(errors),

                # Extras por si luego los usas
                "imuAccelX": round(sensor_state["imu_accel_x"], 3),
                "imuAccelY": round(sensor_state["imu_accel_y"], 3),
                "imuAccelZ": round(sensor_state["imu_accel_z"], 3),
                "collisionCount": int(sensor_state["collision_count"]),
                "collisionIntensity": round(sensor_state["last_collision_intensity"], 3),
                "vehicleId": vehicle.id,
                "vehicleType": vehicle.type_id,
            }

            info = client_mqtt.publish(
                MQTT_TOPIC,
                json.dumps(payload),
                qos=0,
                retain=False,
            )

            counter += 1
            if counter % 10 == 0:
                print(
                    f"[PUB] connected={client_mqtt.is_connected()} "
                    f"rc={info.rc} "
                    f"mode={payload['mode']} "
                    f"v={payload['linearSpeed']} m/s "
                    f"w={payload['angularSpeed']} rad/s "
                    f"bat={payload['batteryPercent']}% "
                    f"pos=({payload['posX']}, {payload['posY']}) "
                    f"health={payload['health']}"
                )

            elapsed = time.time() - loop_start
            sleep_time = max(0.0, PUBLISH_DT - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[INFO] Cerrando bridge...")

    finally:
        try:
            if imu_sensor.is_listening:
                imu_sensor.stop()
        except Exception:
            pass

        try:
            if collision_sensor.is_listening:
                collision_sensor.stop()
        except Exception:
            pass

        try:
            imu_sensor.destroy()
        except Exception:
            pass

        try:
            collision_sensor.destroy()
        except Exception:
            pass

        client_mqtt.loop_stop()
        client_mqtt.disconnect()


if __name__ == "__main__":
    main()
