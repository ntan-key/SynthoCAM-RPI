from aiortc import RTCPeerConnection, sdp, RTCSessionDescription
from aiortc.contrib.media import MediaRecorder, MediaRelay
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, WebSocketException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import uvicorn
import asyncio
import logging
import json
import os
import cv2
import base64

from Task import get_capture_ls, remote_stats, delete_capture
from MicrophoneTrack import MicrophoneTrack
from CameraTrack import CameraTrack
import State
from pydantic import BaseModel
from contextlib import asynccontextmanager


CAPTURE_FOLDER = './captures'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('server')

relay = MediaRelay()


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     logger.info('FastAPI app startup')
#     app.state.camera_track = CameraTrack()
#     app.state.audio_track = MicrophoneTrack()

#     yield

#     logger.info('FastAPI app shutdown')
#     if hasattr(app.state, "camera_track"):
#         app.state.camera_track.stop()
#         app.state.audio_track._stop()


app = FastAPI()
# app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173",
                   "https://localhost:5173",
                   "http://192.168.0.131:5173",
                   "https://192.168.0.131:5173",
                   "http://192.168.0.146:5173",
                   "https://192.168.0.146:5173",
                   "http://10.42.0.1:5173",
                   "https://10.42.0.1:5173",
                   "http://synthocam.local:5173",
                   "https://synthocam.local:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# HTTP Requests


@app.get("/")
async def home():
    return {
        "status": "home"
        }


@app.get("/capture/list")
async def capture_list():
    return {
        "capture_list": get_capture_ls(CAPTURE_FOLDER)
        }


@app.get("/capture/download")
async def capture_download(title: str):
    logger.info(title)
    if os.path.exists:
        return FileResponse(
            path=os.path.join(CAPTURE_FOLDER, title),
            media_type="video/mp4",
            filename=title
        )


class CaptureDeleteRequest(BaseModel):
    title: str


@app.post("/capture/delete")
async def capture_delete(req: CaptureDeleteRequest):
    logger.info(req)
    delete_capture(os.path.join(CAPTURE_FOLDER, req.title))
    return {'status': 'ok'}


# Websocket Handling


@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket):
    pc = None
    recorder = None
    camera_track = None
    audio_track = None
    # camera_track = ws.app.state.camera_track
    # audio_track = ws.app.state.audio_track

    logger = logging.getLogger('websocket')
    
    await ws.accept()  # accept WebSocket handshake if a new client connects otherwise FastAPI rejects with 403
    pc = RTCPeerConnection()  # create new peer connection


    # @pc.on("icecandidate")  # fires for every candidate as discovered, and a final time where candidate=None to signal end of gathering
    # async def on_ice_candidate(candidate):
    #     logger = logging.getLogger('peer-connection')
    #     # Every time I discover a new way for someone to reach me, send info to other peer so they can try connecting to it
    #     if candidate:  # don't fire on final candidate=None
    #         try:
    #             await ws.send(json.dumps({
    #             'type': 'ice-candidate',
    #             'candidate': {
    #             'candidate': candidate.candidate,
    #             'sdpMid': candidate.sdpMid,
    #             'sdpMLineIndex': candidate.sdpMLineIndex
    #             }
    #             }))
    #         except Exception as e:
    #             logger.error('failed to send ice candidate')                                     

    # @pc.on("connectionstatechange")
    # async def on_connection_state_change():
    #     logger = logging.getLogger('peer-connection')
    #     logger.info(f"state: {pc.connectionState}")
    #     if pc.connectionState == "checking":
    #         logger.info("checking - testing candidates")
    #     elif pc.connectionState == "connected":
    #         logger.info("connected - working pair found")
    #     elif pc.connectionState == "completed":
    #         logger.info("completed - fully established")
    #     elif pc.connectionState == "failed":
    #         logger.error("connection failed")
    

    remote_stats_task = asyncio.create_task(remote_stats(ws))
    video_filename = None

    try:
        while True:
            data = await ws.receive_json()

            if data['type'] == "heartbeat":
                await ws.send_json({
                    "type": "heartbeat-response"
                })
            
            elif data['type'] == "recording-start":
                video_filename = data['filename']
                video_filepath = os.path.join(CAPTURE_FOLDER, video_filename)
                logger.info(f'recording to file: {video_filename}')
                recorder = MediaRecorder(video_filepath)
                if audio_track:
                    recorder.addTrack(audio_track)
                    # recorder.addTrack(relay.subscribe(audio_track))
                if camera_track:
                    recorder.addTrack(camera_track)
                    # recorder.addTrack(relay.subscribe(camera_track))
                if recorder:
                    await recorder.start()
                    logger.info('recorder start')
                
            elif data['type'] == "recording-end":
                logger.info('recording ended')
                if recorder:
                    await recorder.stop()
                    thumb_cap = cv2.VideoCapture(video_filepath)
                    no_frames = thumb_cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    if no_frames > 0:
                        thumb_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, thumbnail = thumb_cap.read()
                        if ret:
                            _, buffer = cv2.imencode('.jpg', thumbnail)
                            thumbnail64 = base64.b64encode(buffer).decode('utf-8')
                    thumb_cap.release()
                    await ws.send_json({
                        "type": "recording-saved",
                        "filename": video_filename,
                        "thumbnail": thumbnail64
                    })

            
            # WebRTC Peer Connection Handling


            elif data['type'] == "offer":
                logger.info('offer')
                try:
                    logger.info('offer processing')

                    # camera_track = ws.app.state.camera_track
                    # audio_track = ws.app.state.audio_track

                    camera_track = CameraTrack()
                    audio_track = MicrophoneTrack()

                    @pc.on("icecandidate")  # fires for every candidate as discovered, and a final time where candidate=None to signal end of gathering
                    async def on_ice_candidate(candidate):
                        logger = logging.getLogger('peer-connection')
                        # Every time I discover a new way for someone to reach me, send info to other peer so they can try connecting to it
                        if candidate:  # don't fire on final candidate=None
                            try:
                                await ws.send(json.dumps({
                                'type': 'ice-candidate',
                                'candidate': {
                                'candidate': candidate.candidate,
                                'sdpMid': candidate.sdpMid,
                                'sdpMLineIndex': candidate.sdpMLineIndex
                                }
                                }))
                            except Exception as e:
                                logger.error('failed to send ice candidate')                                     

                    @pc.on("connectionstatechange")
                    async def on_connection_state_change():
                        logger = logging.getLogger('peer-connection')
                        logger.info(f"state: {pc.connectionState}")
                        if pc.connectionState == "checking":
                            logger.info("checking - testing candidates")
                        elif pc.connectionState == "connected":
                            logger.info("connected - working pair found")
                        elif pc.connectionState == "completed":
                            logger.info("completed - fully established")
                        elif pc.connectionState == "failed":
                            logger.error("connection failed")
                    
                    offer = RTCSessionDescription(sdp=data['sdp'], type=data['type'])
                    await pc.setRemoteDescription(offer)
                    logger.info("remote description set")

                    for t in pc.getTransceivers():
                        if t.kind == "audio":
                            t.direction = "sendonly"
                            t.sender.replaceTrack(audio_track)
                            # t.sender.replaceTrack(relay.subscribe(audio_track))

                        elif t.kind == "video":
                            t.direction = "sendonly"
                            t.sender.replaceTrack(camera_track)
                            # t.sender.replaceTrack(relay.subscribe(camera_track))

                    # # pc.addTrack(audio_track)
                    # audio_transceiver = pc.addTransceiver("audio", direction="sendonly")
                    # audio_transceiver.sender.replaceTrack(audio_track)
                    # logger.info("audio track added")
                    # # pc.addTrack(camera_track)
                    # video_transceiver = pc.addTransceiver("video", direction="sendonly")
                    # video_transceiver.sender.replaceTrack(camera_track)
                    # logger.info('video track added')

                    answer = await pc.createAnswer()
                    await pc.setLocalDescription(answer)
                    logger.info("answer created")

                    response = {
                    'type': 'answer',
                    'sdp': pc.localDescription.sdp
                    }

                    await ws.send_json(response)
                    logger.info("answer sent")

                except Exception as e:
                    logger.exception(f'offer processing error: {e}')
                    continue

            elif data['type'] == "ice-candidate" and pc:
                logger = logging.getLogger('peer-connection')
                try:
                    cand_data = data.get('candidate')
                    if cand_data and 'candidate' in cand_data:
                        candidate = sdp.candidate_from_sdp(cand_data['candidate'])
                        candidate.sdpMid = cand_data.get('sdpMid')
                        candidate.sdpMLineIndex = cand_data.get('sdpMLineIndex')
                    if pc.remoteDescription is not None:
                        await pc.addIceCandidate(candidate)
                        logger.debug("ice candidate added")
                except Exception as e:
                    logger.error(f"ice candidate error: {e}")

    
    except WebSocketDisconnect:
        logger.info('websocketdisconnect')
        remote_stats_task.cancel()

    except WebSocketException:
        logger.info('websocketexception')

    finally:
        if pc:
            try:
                await pc.close()
            except:
                pass


# uvicorn server-fastapi:app --host 0.0.0.0 --port 8000 --reload
# http://localhost:8000/
# http://192.168.0.131:8000