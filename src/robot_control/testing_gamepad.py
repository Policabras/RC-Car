#!/usr/bin/env python3
import pygame
import time

pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("❌ No hay controles conectados")
    exit()

js = pygame.joystick.Joystick(0)
js.init()

print(f"\n🎮 Control: {js.get_name()}")
print("Sigue las instrucciones...\n")

def wait_button_press(label):
    print(f"👉 Presiona el botón: {label}")
    while True:
        pygame.event.pump()
        for i in range(js.get_numbuttons()):
            if js.get_button(i):
                print(f"✅ {label} = botón índice {i}\n")
                time.sleep(0.5)
                return i

def wait_axis_move(label):
    print(f"👉 Mueve el eje: {label}")
    base = [js.get_axis(i) for i in range(js.get_numaxes())]

    while True:
        pygame.event.pump()
        for i in range(js.get_numaxes()):
            val = js.get_axis(i)
            if abs(val - base[i]) > 0.5:
                print(f"✅ {label} = eje índice {i} (valor={round(val,2)})\n")
                time.sleep(0.5)
                return i

# =========================
# MAPEO
# =========================
mapping = {}

# Botones principales
mapping["A"] = wait_button_press("A")
mapping["B"] = wait_button_press("B")
mapping["X"] = wait_button_press("X")
mapping["Y"] = wait_button_press("Y")

mapping["LB"] = wait_button_press("LB")
mapping["RB"] = wait_button_press("RB")

mapping["BACK"] = wait_button_press("BACK / SELECT")
mapping["START"] = wait_button_press("START / OPTIONS")

mapping["LS_CLICK"] = wait_button_press("CLICK STICK IZQ")
mapping["RS_CLICK"] = wait_button_press("CLICK STICK DER")

# Ejes
mapping["LX"] = wait_axis_move("STICK IZQ X")
mapping["LY"] = wait_axis_move("STICK IZQ Y")
mapping["RX"] = wait_axis_move("STICK DER X")
mapping["RY"] = wait_axis_move("STICK DER Y")

mapping["L2"] = wait_axis_move("GATILLO L2")
mapping["R2"] = wait_axis_move("GATILLO R2")

# Resultado final
print("\n=========================")
print("🎯 MAPEO FINAL")
print("=========================\n")

for k, v in mapping.items():
    print(f"{k:10} = {v}")

print("\n👉 Usa estos valores en tu .env\n")

js.quit()
pygame.quit()
