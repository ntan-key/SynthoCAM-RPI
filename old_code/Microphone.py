from aiortc import MediaStreamTrack
import pyaudio
import logging
from av.audio.frame import AudioFrame
import fractions
import contextlib
import os
import sys
import asyncio
import numpy as np


# ls -l /dev/snd/by-id
MICROPHONE_NAME = 'usb-KTMicro_KT_USB_Audio_2021-07-19-0000-0000-0000--00'

logger = logging.getLogger("microphone")

# Audio settings
AUDIO_SAMPLE_RATE = 48000
AUDIO_CHUNK = 960  # 20ms at 48kHz
AUDIO_CHANNELS = 1


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


class MicrophoneStreamTrack(MediaStreamTrack):
    kind = "audio"


    def __init__(self):
        super().__init__()
        self.sample_rate = AUDIO_SAMPLE_RATE
        self.chunk = AUDIO_CHUNK
        self.channels = AUDIO_CHANNELS
        self.pts = 0
        self.time_base = fractions.Fraction(1, self.sample_rate)

        self.pa = None
        self.stream = None
        self.running = True
        self._init_audio()


    def _init_audio(self):
        try:
            with suppress_alsa_stderr():
                self.pa = pyaudio.PyAudio()

            input_device = self._find_input_device()

            if input_device is not None:
                with suppress_alsa_stderr():
                    self.stream = self.pa.open(
                    format=pyaudio.paInt16,
                    channels=self.channels,
                    rate=self.sample_rate,
                    input=True,
                    input_device_index=input_device,
                    frames_per_buffer=self.chunk
                    )
                logger.info(f"🎤 Audio input ready (device {input_device})")
            else:
                logger.warning("⚠️ No audio input found, using silence")
                self.stream = None

        except Exception as e:
            logger.error(f"❌ Audio input failed: {e}")
            self.stream = None


    def _find_input_device(self):
        if not self.pa:
            return None

        try:
            for i in range(self.pa.get_device_count()):
                try:
                    with suppress_alsa_stderr():
                        device_info = self.pa.get_device_info_by_index(i)

                    if device_info.get('maxInputChannels', 0) > 0:
                        device_name = device_info.get('name', 'Unknown')
                        if "KT" in device_name:
                            logger.info(f"Testing input device {i}: {device_name}")

                            try:
                                with suppress_alsa_stderr():
                                    test_stream = self.pa.open(
                                    format=pyaudio.paInt16,
                                    channels=self.channels,
                                    rate=self.sample_rate,
                                    input=True,
                                    input_device_index=i,
                                    frames_per_buffer=self.chunk
                                    )
                                test_stream.close()
                                logger.info(f"✅ Device {i} works: {device_name}")
                                return i
                            except:
                                continue
                except:
                    continue
        except Exception as e:
            logger.error(f"Error finding input device: {e}")

        return None
    

    def _reconnect(self):
        self._init_audio()


    async def recv(self):
        if not self.running:
            raise ConnectionError("Audio track stopped")

        try:
            if self.stream and self.running:
                with suppress_alsa_stderr():
                    # data = self.stream.read(self.chunk, exception_on_overflow=False)
                    data = await asyncio.get_event_loop().run_in_executor(None, lambda: self.stream.read(self.chunk, exception_on_overflow=False))
            else:
                data = np.zeros(self.chunk, dtype=np.int16).tobytes()

            frame = AudioFrame(format="s16", layout="mono", samples=self.chunk)
            frame.sample_rate = self.sample_rate
            frame.planes[0].update(data)
            frame.pts = self.pts
            frame.time_base = self.time_base
            self.pts += self.chunk

            return frame

        except Exception as e:
            logger.warning(f"Audio error: {e}")
            silence = np.zeros(self.chunk, dtype=np.int16).tobytes()
            frame = AudioFrame(format="s16", layout="mono", samples=self.chunk)
            frame.sample_rate = self.sample_rate
            frame.planes[0].update(silence)
            frame.pts = self.pts
            frame.time_base = self.time_base
            self.pts += self.chunk
            return frame


    def stop(self):
        self.running = False
        if self.stream:
            try:
                with suppress_alsa_stderr():
                    self.stream.stop_stream()   
                self.stream.close()
                logger.info("🎤 Audio input stopped")
            except:
                pass