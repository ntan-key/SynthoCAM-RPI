import os
import sys
import contextlib
import asyncio
import logging
import numpy as np
import fractions
import sounddevice as sd
from aiortc import MediaStreamTrack
from av.audio.frame import AudioFrame
from collections import deque

import State


# ls -l /dev/snd/by-id
MICROPHONE_NAME = 'usb-KTMicro_KT_USB_Audio_2021-07-19-0000-0000-0000--00'
# python3 -m sounddevice
SD_NAME = 'KT USB Audio'

# Audio settings
AUDIO_SAMPLE_RATE = 48000
# AUDIO_SAMPLE_RATE = 16000
AUDIO_CHUNK = 960  # 20ms at 48kHz
# AUDIO_CHUNK = 2048
AUDIO_CHANNELS = 1

logger = logging.getLogger('MicrophoneTrack')


@contextlib.contextmanager
def suppress_alsa_stderr():
    stderr_fileno = sys.stderr.fileno()
    old_stderr_fd = os.dup(stderr_fileno)
    try:
        with open(os.devnull, 'w') as fnull:
            os.dup2(fnull.fileno(), stderr_fileno)
        yield
    finally:
        os.dup2(old_stderr_fd, stderr_fileno)
        os.close(old_stderr_fd)


class MicrophoneTrack(MediaStreamTrack):
    kind = "audio"
    
    def __init__(self):
        super().__init__()
        logger.info('*Created new MicrophoneTrack*')
       
        # status variables
        self.connected = False
        self.streaming = False
        self._device_index = -1
        
        # connection watchdog
        self._watchdog_task = None
        self._start_watchdog()

        # stream
        self.stream = None
        self.pts = 0
        self._stream_queue = asyncio.Queue(maxsize=1)
        self.loop = asyncio.get_running_loop()
        

    def _start_watchdog(self):
        logger.info('starting watchdog')
        self._watchdog_task = asyncio.create_task(self._watchdog())


    async def _watchdog(self):
        while True:
            _prev_connected = self.connected
            self.connected = self._status()
            State.microphone_connected = self.connected
            if (_prev_connected != self.connected):
                logger.info(f'microphone {'connected' if self.connected else 'disconnected'}')
                if self.connected:
                    await asyncio.sleep(2)
                    self._device_index = self._sd_index()
                    self._start_stream()
                else:
                    self._stop_stream()
            await asyncio.sleep(5)


    def _status(self):
        if os.path.exists('/dev/snd/by-id'):
            output = os.popen('ls -l /dev/snd/by-id').read()
            for line in output.splitlines():
                if MICROPHONE_NAME in line:
                    return True
        else:
            return False
        

    def _sd_index(self):
        if self.connected:
            sd._terminate()
            sd._initialize()
            for device in sd.query_devices():
                if SD_NAME in device['name']:
                    self._device_index = device['index']
                    logger.info(f'sound device {device['name']} connected')
                    return device['index']
                else:
                    continue
        logger.info('sound device not found')
        return -1


    def _start_stream(self):
        if ((self._device_index >= 0) and (self.stream is None)):
            self.stream = sd.InputStream(
                dtype='int16',
                channels=AUDIO_CHANNELS,
                samplerate=AUDIO_SAMPLE_RATE,
                blocksize=AUDIO_CHUNK,
                device=self._device_index,
                callback=self._stream_callback
            )
            try:
                self.stream.start()
                logger.info('started stream')
            except Exception as e:
                logger.info(f'error starting stream: {e}')
            self.streaming = self.stream.active


    def _stop_stream(self):
        if self.stream:
            try:
                if self.stream.active:
                    self.stream.stop()   
                self.stream.close()
                logger.info("stream stopped")
            except:
                pass
        self.stream = None
        self.streaming = False


    def _stream_callback(self, indata, frames, time, status):
        if status:
            logger.info(f'stream status: {status}')
        try:
            self.loop.call_soon_threadsafe(
                self._safe_put,
                indata.copy()
            )
            # await self._stream_queue.put(indata.copy())
        except asyncio.QueueFull:
            logger.info('queue full')
            pass

    def _safe_put(self, data):
        try:
            self._stream_queue.put_nowait(data)
        except asyncio.QueueFull:
            try:
                self._stream_queue.get_nowait()  # drop oldest audio frame
            except asyncio.QueueEmpty:
                logger.info('queue full exception, but queue empty')
            try:
                self._stream_queue.put_nowait(data)
            except asyncio.QueueFull:
                logger.info('queue full again')
    

    async def recv(self):
        try:
            if self.connected and self.streaming:
                data = await self._stream_queue.get()
            else:
                data = np.zeros(AUDIO_CHUNK, dtype=np.int16).tobytes()
            frame = AudioFrame(format="s16", layout="mono", samples=AUDIO_CHUNK)
            frame.sample_rate = AUDIO_SAMPLE_RATE
            frame.planes[0].update(data)
            frame.pts = self.pts
            frame.time_base = fractions.Fraction(1, AUDIO_SAMPLE_RATE)
            self.pts += AUDIO_CHUNK
            return frame

        except Exception as e:
            logger.info(f'audio data error returning silent frame: {e}')
            silence = np.zeros(AUDIO_CHUNK, dtype=np.int16).tobytes()
            frame = AudioFrame(format="s16", layout="mono", samples=AUDIO_CHUNK)
            frame.sample_rate = AUDIO_SAMPLE_RATE
            frame.planes[0].update(silence)
            frame.pts = self.pts
            frame.time_base = fractions.Fraction(1, AUDIO_SAMPLE_RATE)
            self.pts += AUDIO_CHUNK
            return frame


    def stop(self):       
    # def __del__(self):       
        if self._watchdog_task:
            self._watchdog_task.cancel()
            self._watchdog_task = None
        self._stop_stream()
        self.connected = False
        self._device_index = -1