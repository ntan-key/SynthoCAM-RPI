import os
import logging
import asyncio
import numpy as np
import cv2
from aiortc import VideoStreamTrack
from av import VideoFrame
from threading import Thread
import queue 
from collections import deque
import time
import threading

import State


# ls -l /dev/v4l/by-id
CAMERA_NAME = 'usb-MACROSILICON_AV_TO_USB2.0_20150130-video-index0'

# Camera settings
# CAMERA_WIDTH = 640
CAMERA_WIDTH = 480
# CAMERA_HEIGHT = 480
CAMERA_HEIGHT = 320
CAMERA_FPS = 30


logger = logging.getLogger('CameraTrack')


class CameraTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self):
        super().__init__()
        logger.info('*Created new CameraTrack*')
        
        # status variables
        self.connected = False
        self.streaming = False
        self.recording = False
        self.saving = False
        self._device_name = f'/dev/v4l/by-id/{CAMERA_NAME}'
        
        # connection watchdog
        self._watchdog_task = None
        self._start_watchdog()

        # stream watchdog
        self._watchdog_stream_task = None

        # stream
        self.stream = None
        self.pts = 0
        # self._stream_queue = asyncio.Queue(maxsize=1)
        self._stream_queue = deque(maxlen=3)
        self._record_queue = queue.Queue()
        self.loop = asyncio.get_running_loop()
        self._reader_thread = None
        self._recorder_thread = None
        self._restart_lock = asyncio.Lock()

    
    def _start_watchdog(self):
        logger.info('starting watchdog')
        logger.info(id(self))
        self._watchdog_task = asyncio.create_task(self._watchdog())

    
    async def _watchdog(self):
        while True:
            _prev_connected = self.connected
            self.connected = self._status()
            State.camera_connected = self.connected
            # logger.info(f'watchdog:_prev_connected: {_prev_connected}, self.connected: {self.connected}, self.streaming: {self.streaming}')
            if (_prev_connected != self.connected):
                # logger.info('watchdog:_prev_connected != self.connected')
                logger.info(f'camera {'connected' if self.connected else 'disconnected'}')
                if self.connected:
                    await asyncio.sleep(2)
                    await self._start_stream()
                else:
                    await asyncio.sleep(2)
                    self._stop_stream()
            await asyncio.sleep(5)

    
    def _status(self):
        if os.path.exists('/dev/v4l/by-id'):
            output = os.popen('ls -l /dev/v4l/by-id').read()
            for line in output.splitlines():
                if CAMERA_NAME in line:
                    return True
        else:
            return False
        
    
    # async def _start_stream(self):
    #     logger.info('starting stream')
    #     if self.streaming:
    #         logger.info('starting stream skipped - already streaming')
    #     else:
    #         try:
    #             for i in range(5):
    #                 try:
    #                     self.stream = cv2.VideoCapture(self._device_name)
    #                 except Exception as e:
    #                     logger.info(f'stream open exception: {e}')
    #                 if self.stream.isOpened():
    #                     logger.info('started stream')
    #                     self.streaming = True
    #                     self._reader_thread = Thread(target=self._read_frames, daemon=True)
    #                     self._reader_thread.start()
    #                     break
    #                 await asyncio.sleep(0.2)
    #             else:
    #                 logger.info('failed to open stream')
    #                 self.streaming = False
    #         except Exception as e:
    #             logger.info(f'error starting stream: {e}')
    #             self.streaming = False


    async def _start_stream(self):
        logger.info('starting stream')
        
        if self.stream:
            logger.info('stream already open')
        
        else:
            while not self.streaming:
                try:
                    self.stream = cv2.VideoCapture(self._device_name)
                    self.streaming = True
                except Exception as e:
                    logger.info(f'error opening stream: {e}') 
                    self.streaming = False
                await asyncio.sleep(0.2)
                
            logger.info('started stream')
            self._reader_thread = Thread(target=self._read_frames,daemon=True)
            self._reader_thread.start()


    # def _stop_stream(self):
    #     if self.stream:
    #         try:
    #             if self.stream.isOpened():
    #                 self.stream.release()
    #                 logger.info("stream stopped")
    #         except Exception as e:
    #             logger.info(f'error stopping stream: {e}')
    #     if self._reader_thread and self._reader_thread.is_alive():
    #         self._reader_thread.join(timeout=1)
    #     self.stream = None
    #     self.streaming = False


    def _stop_stream(self):
        if self.stream:
            if self.stream.isOpened():
                try:
                    self.stream.release()
                    logger.info("stream stopped")
                except Exception as e:
                    logger.info(f'error stopping stream: {e}')
        self.stream = None
        if self._reader_thread:
            if self._reader_thread.is_alive():
                self._reader_thread.join(timeout=1)
        self._reader_thread = None


    # def _read_frames(self):
    #     while self.streaming and self.stream.isOpened():
    #         ret, frame = self.stream.read()
    #         if ret:
    #             frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    #             if np.all(frame == 0):
    #                 pass
    #                 logger.info('blank frame read, check hardware connections and power')
    #                 # self.streaming = False
    #         else:
    #             logger.info('error reading frame, ret is None')
    #             frame = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
    #             self.streaming = False
    #         try:
    #             # self._stream_queue.put_nowait(frame)
    #             self._stream_queue.append(frame)
    #         # except asyncio.QueueFull:
    #         #     logger.info('queue full, oldest frame dropped')
    #         #     _bin_frame = self._stream_queue.get_nowait()
    #         #     self._stream_queue.put_nowait(frame)
    #         except queue.Full:
    #             logger.info('queue full')
    #         except Exception as e:
    #             logger.info(f'error queueing stream frame: {e}')
    #         if self.recording:
    #             try:
    #                 self._record_queue.put(frame, timeout=0.1)
    #             except Exception as e:
    #                 logger.info(f'error queueing record frame: {e}')


    def _read_frames(self):
        logger.info('reading frames')
        if self.stream:
            while self.stream.isOpened():
                try:
                    ret, frame = self.stream.read()
                except Exception as e:
                    logger.info(f'error opening stream: {e}')
                if ret:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    if not np.all(frame == 0):
                        try:
                            self._stream_queue.append(frame)
                        except queue.Full:
                            logger.info('queue full')
                        except Exception as e:
                            logger.info(f'error queueing stream frame: {e}')
                        if self.recording:
                            try:
                                self._record_queue.put(frame, timeout=0.1)
                            except Exception as e:
                                logger.info(f'error queueing record frame: {e}')
                    else:
                        logger.info('blank frame read')
                        # await self._restart_stream()
                
                else:
                    logger.info('ret is None')
                    # await self._restart_stream()
                    asyncio.run_coroutine_threadsafe(
                        self._restart_stream(),
                        self.loop
                    )


    async def _restart_stream(self):
        async with self._restart_lock:
            logger.info('restarting stream')
            self._stop_stream()
            await asyncio.sleep(2)
            await self._start_stream()

    
    async def recv(self):
        pts, time_base = await self.next_timestamp()

        try:
            if self.connected and self.streaming:
                data = self._stream_queue[-1] if self._stream_queue else np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
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
    # def __del__(self):       
        logger.info('stop()')
        # if self._watchdog_task:
        #     self._watchdog_task.cancel()
        #     self._watchdog_task = None
        # self._stop_stream()
        self.connected = False


# Drain queue

# while not self._stream_queue.empty():
#     try:
#         self._stream_queue.get_nowait()
#     except:
#         break

# Put frame in asyncio queue without blocking
# try:
#     self._stream_queue.put_nowait(frame)
# except asyncio.QueueFull:
#     # drop old frames to maintain low latency
#     _ = self._stream_queue.get_nowait()
#     self._stream_queue.put_nowait(frame)