import os
import cv2
import psutil
import shutil
from fastapi import WebSocket
import asyncio
import logging
import base64
import State  # global variables


def get_capture_ls(capture_folder):
    logger = logging.getLogger("capture-ls")
    captures = [];
    for file in os.listdir(capture_folder):
        thumbnail = [[[]]]
        thumb_cap = cv2.VideoCapture(os.path.join(capture_folder, file))
        no_frames = thumb_cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if no_frames > 0:
            thumb_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, thumbnail = thumb_cap.read()
            if ret:
                _, buffer = cv2.imencode('.jpg', thumbnail)
                thumbnail64 = base64.b64encode(buffer).decode('utf-8')

        captures.append({'title': file, 'thumbnail': thumbnail64})
        thumb_cap.release()
    return captures

# [{'title': 'output.avi', 'thumbnail': ''}]


def get_cpu_temp() -> float:
    with open("/sys/class/thermal/thermal_zone0/temp") as f:
        temp = int(f.read()) / 1000
    return temp


def get_cpu_usage():
    return psutil.cpu_percent(interval=None)


def get_storage_usage():
    return {'used': shutil.disk_usage('/')[1], 'total': shutil.disk_usage('/')[0]}

# usage(total=30527090688, used=8122724352, free=21124800512)


async def remote_stats(ws: WebSocket):
    logger = logging.getLogger("remote-stats")
    try:
        while True:
            try:
                stats = {'type': 'remote-stats', 'cpu_temp': get_cpu_temp(), 'cpu_usage': get_cpu_usage(), 'storage_total': get_storage_usage()['total'], 'storage_used': get_storage_usage()['used']}
                try:
                    await ws.send_json(stats)
                except RuntimeError as e:
                    logger.info(f'ws closed not sending: {e}')
                await asyncio.sleep(1)
            except Exception as e:
                logger.info(f'remote stats exception: {e}')
    except asyncio.CancelledError:
        logger.warning('remote stats cancelled')
        pass
    except Exception:
        logger.warning('remote stats exception')


def delete_capture(path: str):
    logger = logging.getLogger("delete-capture")
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            logger.info(f'error deleting file {path}: {e}')
    else: 
        logger.info(f'error deleting file - file does not exist: {path}')