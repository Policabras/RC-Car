from evdev import InputDevice, list_devices

objetivo = "Wireless Controller"

encontrado = None
for path in list_devices():
    dev = InputDevice(path)
    print(f"{path} -> {dev.name}")
    if objetivo.lower() in dev.name.lower():
        encontrado = path

if encontrado:
    print(f"\nControl encontrado en: {encontrado}")
else:
    print("\nNo se encontró el control")