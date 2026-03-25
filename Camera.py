from aiortc import VideoStreamTrack
import cv2
import logging
import numpy as np
import asyncio
from av import VideoFrame


# Configuration
CAMERA_DEVICE = 0 # Change if your camera is on different device
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
WEBSOCKET_PORT = 8765


# global recording
# recording = False

logger = logging.getLogger("pi-streamer")

# try:
#     fourcc = cv2.VideoWriter_fourcc(*'XVID')
#     vw = cv2.VideoWriter('output.avi', fourcc , 20.0, (480, 320))
# except:
#     logging.error('Error setting up Video Writer')


class CameraStreamTrack(VideoStreamTrack):
    kind = "video"
    
    def __init__(self):
        super().__init__()
        self.cap = None
        self.frame_count = 0
        self._init_camera()

    def _init_camera(self):
        try:
            self.cap = cv2.VideoCapture(CAMERA_DEVICE)
            # self.cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
            if self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
                self.cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                logging.info("✅ Camera ready")
            else:
                logging.warning("⚠️ Camera not available, using test pattern")
                self.cap = None
        except Exception as e:
            logging.error(f"Camera error: {e}")
            self.cap = None

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        if self.cap and self.cap.isOpened():
            # ret, frame = self.cap.read()
            ret, frame = await asyncio.get_event_loop().run_in_executor(None, self.cap.read)
            # if recording:
            #     try:
            #         vw.write(frame)
            #     except:
            #         logging.error('Error writing frame')
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            else:
                frame = self._test_pattern()
        else:
            frame = self._test_pattern()

        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base

        return video_frame

    def _test_pattern(self):
        """Generate test pattern if camera fails"""
        self.frame_count += 1
        frame = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)

        # Gradient background
        for y in range(CAMERA_HEIGHT):
            frame[y, :] = [y//2, 100, 200 - y//3]

        # Moving circle
        x = int((self.frame_count * 3) % CAMERA_WIDTH)
        y = int(CAMERA_HEIGHT // 2 + 50 * np.sin(self.frame_count * 0.1))
        cv2.circle(frame, (x, y), 20, (255, 255, 0), -1)

        # Text overlay
        cv2.putText(frame, "LIVE TEST PATTERN", (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.putText(frame, f"Frame: {self.frame_count}", (20, 80),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        return frame

    def stop(self):
        if self.cap:
            self.cap.release()
            logging.info("📹 Camera released")