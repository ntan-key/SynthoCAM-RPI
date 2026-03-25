import json
import asyncio
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError, ConnectionClosed

import psutil
import shutil


def get_cpu_temp() -> float:
    with open("/sys/class/thermal/thermal_zone0/temp") as f:
        temp = int(f.read()) / 1000
    return temp


async def serve_client(websocket):
    try:
        await websocket.send(json.dumps({"type": "store_tot", "data": shutil.disk_usage('/')[0]}))  # only send once
        while True:
            try:
                await websocket.send(json.dumps({"type": "cpu_temp", "data": get_cpu_temp()}))
                await websocket.send(json.dumps({"type": "cpu_use", "data": psutil.cpu_percent(interval=1)}))
                await websocket.send(json.dumps({"type": "store_use", "data": shutil.disk_usage('/')[1]}))
            except (ConnectionClosedOK, ConnectionClosedError, ConnectionClosed):
                break
            await asyncio.sleep(0.5)
    except Exception as e:
        print(f'CPU temp task ended: {e}')