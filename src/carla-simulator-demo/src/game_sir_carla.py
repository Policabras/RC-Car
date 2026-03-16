import random
import time
import pygame
import carla

HOST = "127.0.0.1"
PORT = 2000

# Ajusta estos índices según lo que te arroje joy_probe.py
AXIS_STEER = 0        # normalmente stick izquierdo horizontal
AXIS_THROTTLE = 5     # normalmente RT
AXIS_BRAKE = 4        # normalmente LT

BTN_REVERSE = 1       # normalmente B
BTN_HANDBRAKE = 0     # normalmente A
BTN_AUTOPILOT = 7     # normalmente Start
BTN_QUIT = 6          # normalmente Back/Select

DEADZONE = 0.08

def apply_deadzone(value, deadzone=DEADZONE):
    return 0.0 if abs(value) < deadzone else value

def trigger_to_01(raw_value):
    # típico en mandos donde el gatillo va de -1 (suelto) a 1 (presionado)
    return max(0.0, min(1.0, (raw_value + 1.0) / 2.0))

def get_or_spawn_vehicle(world):
    vehicles = world.get_actors().filter("vehicle.*")

    for v in vehicles:
        if v.attributes.get("role_name") == "hero":
            return v

    blueprint_library = world.get_blueprint_library()
    bp = random.choice(blueprint_library.filter("vehicle.*"))
    spawn_points = world.get_map().get_spawn_points()
    vehicle = world.try_spawn_actor(bp, random.choice(spawn_points))
    if vehicle is None:
        raise RuntimeError("No se pudo spawnear vehículo.")
    return vehicle

def main():
    client = carla.Client(HOST, PORT)
    client.set_timeout(10.0)

    world = client.get_world()
    vehicle = get_or_spawn_vehicle(world)
    vehicle.set_autopilot(False)

    pygame.init()
    pygame.joystick.init()

    if pygame.joystick.get_count() == 0:
        raise RuntimeError("No se detectó ningún control.")

    joy = pygame.joystick.Joystick(0)
    joy.init()

    print(f"Control detectado: {joy.get_name()}")
    print("B = reverse | A = handbrake | Start = autopilot | Back = salir")

    autopilot = False
    last_buttons = {}

    try:
        while True:
            pygame.event.pump()

            steer_raw = joy.get_axis(AXIS_STEER)
            throttle_raw = joy.get_axis(AXIS_THROTTLE)
            brake_raw = joy.get_axis(AXIS_BRAKE)

            steer = apply_deadzone(steer_raw)
            throttle = trigger_to_01(throttle_raw)
            brake = trigger_to_01(brake_raw)

            reverse_pressed = joy.get_button(BTN_REVERSE)
            handbrake_pressed = joy.get_button(BTN_HANDBRAKE)
            autopilot_pressed = joy.get_button(BTN_AUTOPILOT)
            quit_pressed = joy.get_button(BTN_QUIT)

            if quit_pressed:
                print("Saliendo...")
                break

            # Toggle autopilot con flanco
            if autopilot_pressed and not last_buttons.get("autopilot", 0):
                autopilot = not autopilot
                vehicle.set_autopilot(autopilot)
                print(f"Autopilot: {'ON' if autopilot else 'OFF'}")

            last_buttons["autopilot"] = autopilot_pressed

            if not autopilot:
                control = carla.VehicleControl()
                control.throttle = throttle
                control.brake = brake
                control.steer = max(-1.0, min(1.0, steer))
                control.reverse = bool(reverse_pressed)
                control.hand_brake = bool(handbrake_pressed)
                vehicle.apply_control(control)

            time.sleep(0.05)

    finally:
        pygame.quit()

if __name__ == "__main__":
    main()
