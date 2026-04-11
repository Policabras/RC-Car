import pygame

pygame.init()
pygame.joystick.init()

count = pygame.joystick.get_count()
print(f"Controles detectados: {count}")

for i in range(count):
    js = pygame.joystick.Joystick(i)
    print(f"\nJoystick index: {i}")
    print(f"  instance_id: {js.get_instance_id()}")
    print(f"  name       : {js.get_name()}")
    print(f"  guid       : {js.get_guid()}")
    print(f"  axes       : {js.get_numaxes()}")
    print(f"  buttons    : {js.get_numbuttons()}")
    print(f"  hats       : {js.get_numhats()}")