#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from evdev import InputDevice, ecodes

DS4_PATH = "/dev/input/event4"   # Ajusta si tu ruta cambia

def main():
    dev = InputDevice(DS4_PATH)

    print(f"Using device: {dev.path} ({dev.name})")
    print("Moving controls... (Ctrl+C to exit) \n")

    estado = {}
    last_print = 0.0
    PRINT_INTERVAL = 0.1  # segundos

    # Tomar control exclusivo del dispositivo
    try:
        dev.grab()
    except PermissionError:
        print("No se pudo hacer grab() (probablemente falta sudo).")

    try:
        # read_loop() bloquea esperando eventos, pero es estable
        for event in dev.read_loop():
            # Guardar último valor de cada código
            if event.type == ecodes.EV_ABS:
                estado[event.code] = event.value
            elif event.type == ecodes.EV_KEY:
                estado[event.code] = event.value

            # ¿Ya toca imprimir?
            now = time.time()
            if now - last_print >= PRINT_INTERVAL:
                last_print = now

                print("------ ESTADO ACTUAL ------")
                for code, value in estado.items():
                    nombre = ecodes.ABS.get(code)
                    if nombre is None:
                        nombre = ecodes.KEY.get(code, f"CODE_{code}")
                    print(f"{nombre:12} = {value}")
                print("----------------------------\n")

    except KeyboardInterrupt:
        print("Saliendo...")

    except OSError as e:
        # Pasa si desconectas el control en caliente
        print(f"\nError de dispositivo: {e}. ¿Se desconectó el DS4?")

    finally:
        try:
            dev.ungrab()
        except:
            pass


if __name__ == "__main__":
    main()