import cv2

cam = cv2.VideoCapture(0)

ret, frame = cam.read()

print("Camera working:", ret)
