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

import State


# ls -l /dev/v4l/by-id
CAMERA_NAME = 'usb-MACROSILICON_AV_TO_USB2.0_20150130-video-index0'

# Camera settings
CAMERA_WIDTH = 480  # 640
CAMERA_HEIGHT = 320  # 480
CAMERA_FPS = 30


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
        self._stream_queue = deque(maxlen=2)

        # asyncio
        self._loop = asyncio.get_running_loop()
        self._lock = asyncio.Lock()

        #threading
        self._reader_thread = None
        self._stop_event = threading.Event()

    
    async def _watchdog(self):
        await asyncio.sleep(2)
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
            output = os.popen('ls -l /dev/v4l/by-id').read()
            for line in output.splitlines():
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
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                if not np.all(frame == 0):
                    self._blank_count = 0
                    State.camera_status = "connected"
                    try:
                        self._stream_queue.append(frame)
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
                data = self._stream_queue[-1]
                # data = await self._stream_queue.get()
            else:
                data = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
            frame = VideoFrame.from_ndarray(data, format="rgb24")
            frame.pts = pts
            frame.time_base = time_base
            return frame
        except Exception as e:
            logger.info(f'video data error returning blank frame: {e}')
            blank = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
            frame = VideoFrame.from_ndarray(blank, format="rgb24")
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