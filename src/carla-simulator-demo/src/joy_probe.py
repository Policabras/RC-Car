import pygame
import time

pygame.init()
pygame.joystick.init()

count = pygame.joystick.get_count()
if count == 0:
    raise SystemExit("No se detectó ningún joystick/control.")

joy = pygame.joystick.Joystick(0)
joy.init()

print(f"Nombre: {joy.get_name()}")
print(f"Ejes: {joy.get_numaxes()}")
print(f"Botones: {joy.get_numbuttons()}")
print("Mueve sticks, gatillos y botones. Ctrl+C para salir.\n")

try:
    while True:
        pygame.event.pump()

        axes = [round(joy.get_axis(i), 3) for i in range(joy.get_numaxes())]
        buttons = [joy.get_button(i) for i in range(joy.get_numbuttons())]

        print(f"\raxes={axes} buttons={buttons}", end="")
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\nListo.")
