import logging
import json

import websockets

from Camera import CameraStream
from Microphone import MicrophoneStream


def get_cpu_temp():
    with open("/sys/class/thermal/thermal_zone0/temp") as f:
        temp = int(f.read()) / 1000
    return temp


async def handle_client(websocket):
    logging.basicConfig(level=logging.INFO)

    client_id = f'client_{id(websocket)}'
    logging.info(f'🔗  {client_id} connected')

    pc = None
    camera_track = None
    audio_track = None

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get('type', 'unknown')
                if msg_type == 'test':
                    print(data.get('data', 'unknown'))
                    if(data.get('data', 'unknown')) == 'ping':
                        await websocket.send(json.dumps({"type": "test", "data": "pong"}))
            except json.JSONDecodeError:
                logging.error('❌ Invalid JSON received')
    finally:
        logging.info(f'⛓️‍💥  {client_id} disconnected')
        logging.info(f'🧹  {client_id} cleanup')