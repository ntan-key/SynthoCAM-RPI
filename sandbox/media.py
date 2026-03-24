import cv2
import time

cap = cv2.VideoCapture("/dev/video0")
i = 0
while i < 10:
    print(i)
    ret, frame = cap.read()
    if not ret:
        break
    print(ret)
    print(frame)
    # cv2.imshow("RunCam via EasierCAP", frame)
    time.sleep(0.1)
    i += 1
cap.release()
# cv2.destroyAllWindows()