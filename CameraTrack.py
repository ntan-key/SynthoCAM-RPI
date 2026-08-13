from aiortc import VideoStreamTrack
import asyncio
from av import VideoFrame
from collections import deque
import cv2
import gc
import logging
import numpy as np
import os
import queue
import threading
import subprocess
import time

import State


# ls -l /dev/v4l/by-id
# CAMERA_NAME = 'usb-MACROSILICON_AV_TO_USB2.0_20150130-video-index0'
CAMERA_NAME = 'usb-MACROSILICON_USB_Video_20200909-video-index0'
# CAMERA_NAME = 'MACROSILICON'
# CAMERA_INDEX = 'index0'

# Camera settings
#CAMERA_WIDTH = 480      # 640
#CAMERA_HEIGHT = 320     # 480
#CAMERA_FPS = 30         # Unstable when changed to 15. May have to bin frames elsewhere.

CAMERA_WIDTH = 720
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
#CAMERA_FOURCC = 'MJPG'



logger = logging.getLogger('CameraTrack')


class CameraTrack(VideoStreamTrack):
    """
    CameraTrack aiortc VideoStreamTrack
    """
    kind = "video"

    def __init__(self):
        super().__init__()
        logger.info('*Created new CameraTrack*')
        self._device_name = f'/dev/v4l/by-id/{CAMERA_NAME}'
        
        # status variables
        self.connected = False
        self.streaming = False
        
        # connection watchdog
        logger.info('starting watchdog')
        self._watchdog_task = asyncio.create_task(self._watchdog())

        # camera stream
        self.stream = None

        # consecutive blank frame count to check for power loss 
        self._blank_count = 0

        # frame buffer
        # self._stream_queue = asyncio.Queue(maxsize=2)
        # self._stream_queue = deque(maxlen=2)    # Origional 
        self._stream_queue = deque(maxlen=1)  # Latest frames


        # asyncio
        self._loop = asyncio.get_running_loop()
        self._lock = asyncio.Lock()

        #threading
        self._reader_thread = None
        self._stop_event = threading.Event()
        self._last_age_log = 0.0            # Added - looking 


    
    async def _watchdog(self):
        await asyncio.sleep(0.2)
        try:
            while True:
                _curr_status = self._status()
                
                if _curr_status != self.connected:
                    self.connected = _curr_status
                    if not _curr_status: State.camera_status = "disconnected"
                    
                    logger.info(f'camera {'connected' if self.connected else 'disconnected'}')
                    
                    if self.connected:
                        await self._start_stream()
                    else:
                        self._stop_stream()
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info('watchdog cancelled')
        except Exception as e:
            logger.info(f'watchdog error: {e}')


    def _status(self):
        if os.path.exists('/dev/v4l/by-id'):
            # output = os.popen('ls -l /dev/v4l/by-id').read()
            result = subprocess.run(
                ["/bin/ls", "-l", "/dev/v4l/by-id"],
                capture_output=True,
                text=True
            )

            output = result.stdout
            for line in output.splitlines():
                # logger.info(line)         #tempory disabled to remove noise 
                if CAMERA_NAME in line:
                    return True
        else:
            return False


    async def _start_stream(self):
        logger.info('_start_stream()')
        self._stop_event.clear()

        async with self._lock:
            logger.info('starting stream')
                        
            while not self.streaming:
                try:
                    self.stream = cv2.VideoCapture(self._device_name)

                    ##self.stream.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*CAMERA_FOURCC))
                    self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)   # added to try to reduce stale frames / lag
                    self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
                    self.stream.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
                    self.stream.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                    actual_width = self.stream.get(cv2.CAP_PROP_FRAME_WIDTH)
                    actual_height = self.stream.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    actual_fps = self.stream.get(cv2.CAP_PROP_FPS)
                    actual_fourcc = int(self.stream.get(cv2.CAP_PROP_FOURCC))
                    fourcc_str = "".join([chr((actual_fourcc >> (8 * i)) & 0xFF) for i in range(4)])
                    logger.info(
                        f"camera negotiated: {actual_width:.0f}x{actual_height:.0f} @ {actual_fps:.1f} fps, fourcc={fourcc_str}"
                    )

                    ret, frame = self.stream.read()
                    if ret:
                        self.streaming = True
                    else: 
                        self.streaming = False
                except Exception as e:
                    logger.info(f'error opening stream: {e}') 
                    self.streaming = False
                await asyncio.sleep(0.2)

            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=0.5)
            self._reader_thread = None
                
            logger.info('started stream')
            self._reader_thread = threading.Thread(target=self._read_frames,daemon=True)
            self._reader_thread.start()


    def _stop_stream(self):
        logger.info('_stop_stream()')
        self._stop_event.set()
        self.streaming = False

        if self.stream:
            try:
                self.stream.release()
                logger.info("stream stopped")
            except Exception as e:
                logger.info(f'error stopping stream: {e}')
            self.stream = None

        # Drain queue
        self._stream_queue.clear()
        # while not self._stream_queue.empty():
        #     try:
        #         self._stream_queue.get_nowait()
        #     except:
        #         break

        gc.collect()

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=0.5)
        self._reader_thread = None        


    def _read_frames(self):
        logger.info('reading frames')
        while not self._stop_event.is_set() and self.stream:
            try:
                ret, frame = self.stream.read()
            except Exception as e:
                logger.info(f'error opening stream: {e}')
            if ret:
                # frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)   # Test no colour conversion 
                if not np.all(frame == 0):
                    self._blank_count = 0
                    State.camera_status = "connected"
                    captured_monotonic = time.monotonic()
                    captured_wall_ms = time.time() * 1000
                    State.latest_capture_ts_ms = captured_wall_ms

                    cv2.putText(
                        frame,
                        f"{captured_wall_ms:.0f}",
                        (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 0),
                        2,
                        cv2.LINE_AA,
                    )
                    try:
                        self._stream_queue.append((frame, captured_monotonic, captured_wall_ms))



#   Old verions - gave bad lag time data - really long values
#                    # captured_at = time.monotonic()
#                    captured_at = time.time() * 1000  # This version for total logging
#                    State.latest_capture_ts_ms = captured_at
#                    cv2.putText(
#                        frame,
#                        f"{captured_at:.3f}",
#                        (10, 30),
#                        cv2.FONT_HERSHEY_SIMPLEX, 
#                        0.7,
#                        (0, 255, 0),
#                        2,
#                        cv2.LINE_AA,
#                    )

#                    try:
#                        #self._stream_queue.append(frame)  # Origional
#                        self._stream_queue.append((frame, time.monotonic()))   # test storing timesamp with frame to calc lag. 

                        # self._stream_queue.put_nowait(frame)
                    except queue.Full:
                        logger.info('queue full')
                    # except asyncio.QueueFull:
                    #     logger.info('queue full, oldest frame dropped')
                    #     _bin_frame = self._stream_queue.get_nowait()
                    #     self._stream_queue.put_nowait(frame)
                    except Exception as e:
                        logger.info(f'error queueing stream frame: {e}')
                else:
                    # this is caused be loss of power to the camera
                    # when power is reconnected, the stream will continue
                    self._blank_count += 1
                    if self._blank_count == 20:
                        logger.info(f'power disconnected')
                        State.camera_status = "no power"
                        self._stream_queue.clear()  # clear queue to prevent displaying last frame frozen
            else:
                # this is caused by usb partially disconnecting
                # requires the stream to restart
                logger.info('ret is None')
                State.camera_status = "no data"
                self._stop_event.set()
                self.streaming = False
                asyncio.run_coroutine_threadsafe(
                    self._restart_stream(),
                    self._loop
                )


    async def _restart_stream(self):
        logger.info('restarting stream')
        self._stop_stream()
        self._stop_event.set()
        self.streaming = False
        self.stream = None
        await asyncio.sleep(1)
        await self._start_stream()

    

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        try:
            if self.connected and self.streaming and self._stream_queue:
                data, captured_monotonic, captured_wall_ms = self._stream_queue[-1]
                age_ms = (time.monotonic() - captured_monotonic) * 1000
                State.video_frame_age_ms = round(age_ms, 1)

                now = time.monotonic()
                if now - self._last_age_log >= 1.0:
                    # logger.info(f'frame age at recv: {age_ms:.1f} ms, capture wall ts: {captured_wall_ms:.0f}, pts = {pts}, time_base = {time_base}')
                    self._last_age_log = now
            else:
                data = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)

            frame = VideoFrame.from_ndarray(data, format="bgr24")
            frame.pts = pts
            frame.time_base = time_base
            return frame

        except Exception as e:
            logger.info(f'video data error returning blank frame: {e}')
            blank = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
            frame = VideoFrame.from_ndarray(blank, format="bgr24")
            frame.pts = pts
            frame.time_base = time_base
            return frame



    def stop(self):    
        logger.info('stop()')

        self.stream = None
        self.streaming = False

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=0.5)

        if self._watchdog_task:
            self._watchdog_task.cancel()
            self._watchdog_task = None

        gc.collect()