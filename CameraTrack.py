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

        # stream
        self.stream = None
        self.pts = 0
        # self._stream_queue = asyncio.Queue(maxsize=1)
        self._stream_queue = deque(maxlen=3)
        self._record_queue = queue.Queue()
        self.loop = asyncio.get_running_loop()
        self._reader_thread = None
        self._recorder_thread = None

    
    def _start_watchdog(self):
        logger.info('starting watchdog')
        self._watchdog_task = asyncio.create_task(self._watchdog())

    
    async def _watchdog(self):
        while True:
            _prev_connected = self.connected
            self.connected = self._status()
            State.camera_connected = self.connected
            if (_prev_connected != self.connected):
                logger.info(f'camera {'connected' if self.connected else 'disconnected'}')
                if self.connected:
                    await asyncio.sleep(2)
                    self._start_stream()
                else:
                    await asyncio.sleep(2)
                    self._stop_stream()
            # print(_prev_connected, self.connected, self.streaming)
            if (self.connected and not self.streaming):
                self._stop_stream()
                await asyncio.sleep(1)
                self._start_stream()
            await asyncio.sleep(5)

    
    def _status(self):
        if os.path.exists('/dev/v4l/by-id'):
            output = os.popen('ls -l /dev/v4l/by-id').read()
            for line in output.splitlines():
                if CAMERA_NAME in line:
                    return True
        else:
            return False
        
    
    def _start_stream(self):
        logger.info('starting stream')
        try:
            for i in range(5):
                self.stream = cv2.VideoCapture(self._device_name)
                if self.stream.isOpened():
                    logger.info('started stream')
                    self.streaming = True
                    self._reader_thread = Thread(target=self._read_frames, daemon=True)
                    self._reader_thread.start()
                    break
                time.sleep(0.2)
            else:
                logger.info('failed to open stream')
                self.streaming = False
        except Exception as e:
            logger.info(f'error starting stream: {e}')
            self.streaming = False


    def _stop_stream(self):
        if self.stream:
            try:
                if self.stream.isOpened():
                    self.stream.release()
                    logger.info("stream stopped")
            except Exception as e:
                logger.info(f'error stopping stream: {e}')
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1)
        self.stream = None
        self.streaming = False


    def _read_frames(self):
        while self.streaming and self.stream.isOpened():
            ret, frame = self.stream.read()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                if np.all(frame == 0):
                    pass
                    # logger.info('blank frame read, check hardware connections and power')
                    # self.streaming = False
            else:
                logger.info('error reading frame, ret is None')
                frame = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
                self.streaming = False
            try:
                # self._stream_queue.put_nowait(frame)
                self._stream_queue.append(frame)
            # except asyncio.QueueFull:
            #     logger.info('queue full, oldest frame dropped')
            #     _bin_frame = self._stream_queue.get_nowait()
            #     self._stream_queue.put_nowait(frame)
            except queue.Full:
                logger.info('queue full')
            except Exception as e:
                logger.info(f'error queueing stream frame: {e}')
            if self.recording:
                try:
                    self._record_queue.put(frame, timeout=0.1)
                except Exception as e:
                    logger.info(f'error queueing record frame: {e}')

    
    def _write_frames(self, path: str):
        try:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(
                path,
                fourcc,
                CAMERA_FPS,
                (CAMERA_WIDTH, CAMERA_HEIGHT)
            )
        except:
            logging.error('Error setting up Video Writer')
        

        if not writer.isOpened():
            logger.error("failed to open VideoWriter")
            return

        logger.info("saving frames")
        self.saving = True

        while self.recording or not self._record_queue.empty():
            try:
                frame = self._record_queue.get(timeout=1)
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)  # Convert RGB -> BGR (IMPORTANT!!)
                h, w = frame.shape[:2]
                if (w, h) != (CAMERA_WIDTH, CAMERA_HEIGHT):
                    frame = cv2.resize(frame, (CAMERA_WIDTH, CAMERA_HEIGHT))
                writer.write(frame)

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"error writing frame: {e}")

        writer.release()
        logger.info("video saved")
        self.saving = False
        # send message to update UI

    
    def start_record(self, path):
        logger.info('start recording')
        if self.recording:
            return
        self._recorder_thread = Thread(
            target=self._write_frames,
            args=(path,),
            daemon=True
        )
        try:
            self._recorder_thread.start()
        except Exception as e:
            logger.info(f'error starting recorder thread: {e}')
        self.recording = True


    def stop_record(self):
        logger.info('stop recording')
        if self._recorder_thread and self._recorder_thread.is_alive():
            self._recorder_thread.join(timeout=2)
        self.recording = False

    
    async def recv(self):
        pts, time_base = await self.next_timestamp()

        try:
            if self.connected and self.streaming:
                # data = await self._stream_queue.get()
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
        
    
    def __del__(self):       
        if self._watchdog_task:
            self._watchdog_task.cancel()
            self._watchdog_task = None
        self._stop_stream()
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