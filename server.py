
import asyncio
import os
import sys
import contextlib
import logging

import cv2
import pyaudio

import websockets

from ClientHandler import handle_client


logging.basicConfig(level=logging.INFO)

# ls -l /dev/v4l/by-id
CAMERA_NAME = 'usb-MACROSILICON_AV_TO_USB2.0_20150130-video-index0'
# ls -l /dev/snd/by-id
MICROPHONE_NAME = 'usb-KTMicro_KT_USB_Audio_2021-07-19-0000-0000-0000--00'

RPI_IP = '192.168.0.131'
WEBSOCKET_PORT = 5927

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


def find_camera(camera_name='') -> int:
    device_id = -1
    found = False
    output = os.popen('ls -l /dev/v4l/by-id').read()
    for line in output.splitlines():
        if camera_name in line:
            device_id = int(line.split(' -> ../../video')[1])
            logging.info(f'📽️  Camera found: {device_id}')
            found = True
    if not found:
        logging.warning(f'⚠️  Camera not found')
    return device_id


def test_camera(device=-1):
    if device >= 0:
        try:
            cap = cv2.VideoCapture(device)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    logging.info(f'✅  Camera working: {frame.shape}')
                else:
                    logging.warning('⚠️  Camera detected but cannot read frame')
                cap.release()
            else:
                logging.warning(f'⚠️  OpenCV cannot open device')
        except:
            logging.error(f'❌  OpenCV cannot create capture: cv2.VideoCapture({device})')


def find_microphone(mic_name='') -> int:
    device_id = -1
    found = False
    output = os.popen('ls -l /dev/snd/by-id').read()
    for line in output.splitlines():
        if mic_name in line:
            card_id = int(line.split(' -> ../')[1].replace('controlC',''))
            found = True
            with suppress_alsa_stderr():
                p = pyaudio.PyAudio()
                for i in range(p.get_device_count()):
                    try:
                        info = p.get_device_info_by_index(i)
                        if info.get('maxInputChannels',0) > 0:
                            if f'(hw:{card_id},' in info.get('name', 'Unknown'):
                                device_id = i
                    except:
                        continue
    if found:
        logging.info(f'🎙️  Microphone found: {device_id}')
    else:
        logging.warning(f'⚠️  Microphone not found')
    return device_id


def test_microphone(device=-1):
    try:
        with suppress_alsa_stderr():
            p = pyaudio.PyAudio()

        with suppress_alsa_stderr():
            test_stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=48000,
            input=True,
            input_device_index=device,
            frames_per_buffer=960 # 20ms at 48kHz
            )
        logging.info(f'✅  Microphone working: {test_stream.is_active()}')
        test_stream.close
    except:
        logging.warning('⚠️  Microphone cannot be opened')


async def main():
    logging.info('⚡  SynthoCAM Raspberry Pi Server Launched')
    print('-' * 55)

    camera_id = find_camera(CAMERA_NAME)
    if camera_id >= 0:
        test_camera(camera_id)
    print('-' * 55)
    
    mic_id = find_microphone(MICROPHONE_NAME)
    if mic_id >= 0:
        test_microphone(mic_id)
    print('-' * 55)
    
    logging.info(f'🔄️  Starting server on port: {WEBSOCKET_PORT}')
    try:
        server = await websockets.serve(handle_client, RPI_IP, WEBSOCKET_PORT)
        logging.info(f'🔗  Server connected')
        logging.info(f'🌐  Connect from web browser')
    except:
        logging.warning(f'⚠️  Server could not start')
    print('-' * 55)

    try:
        await server.wait_closed()
    except asyncio.CancelledError:
        logging.info(f'🔄️  Server shutting down')
        server.close()
        await server.wait_closed()
        logging.info(f'⛓️‍💥  Server disconnected')
    

if __name__ == "__main__":
    asyncio.run(main())