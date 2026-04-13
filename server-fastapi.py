from aiortc import RTCPeerConnection, sdp, RTCSessionDescription
from aiortc.contrib.media import MediaRecorder
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, WebSocketException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import uvicorn
import asyncio
import logging
import json
import os

from Task import get_capture_ls, remote_stats, delete_capture
from MicrophoneTrack import MicrophoneTrack
from CameraTrack import CameraTrack
import State
from pydantic import BaseModel


CAPTURE_FOLDER = './captures'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('server')

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://192.168.0.131:5173"],
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


@app.websocket('/')
async def ws_endpoint(ws: WebSocket):

    pc = None
    camera_track = None
    audio_track = None
    recorder = None

    logger = logging.getLogger('websocket')
    
    await ws.accept()  # accept WebSocket handshake if a new client connects otherwise FastAPI rejects with 403
    pc = RTCPeerConnection()  # create new peer connection
    
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
                State.record = True
                # if pc and camera_track and audio_track:
                #     camera_track.start_record(os.path.join(CAPTURE_FOLDER, video_filename))
                recorder = MediaRecorder(video_filepath)
                if audio_track:
                    recorder.addTrack(audio_track)
                if camera_track:
                    recorder.addTrack(camera_track)
                if recorder:
                    await recorder.start()
                    logger.info('recorder start')
                
            elif data['type'] == "recording-end":
                logger.info('recording ended')
                State.record = False
                # if pc and camera_track and audio_track:
                #     camera_track.stop_record()
                #     while camera_track.saving:
                #         pass
                #     await ws.send_json({
                #         "type": "recording-saved",
                #         "filename": video_filename,
                #         "thumbnail": []
                #     })
                if recorder:
                    await recorder.stop()
                    await ws.send_json({
                        "type": "recording-saved",
                        "filename": video_filename,
                        "thumbnail": []
                    })

            
            # WebRTC Peer Connection Handling


            elif data['type'] == "offer":
                logger.info('offer')
                try:
                    logger.info('offer processing')

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

                    # @pc.on("track")
                    # def on_track(track):
                    #     recorder.addTrack(track)
                    #     logger.info('recorder added track')

                    for t in pc.getTransceivers():
                        if t.kind == "audio":
                            t.direction = "sendonly"
                            t.sender.replaceTrack(audio_track)

                        elif t.kind == "video":
                            t.direction = "sendonly"
                            t.sender.replaceTrack(camera_track)

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
        if audio_track:
            audio_track.stop()
        if camera_track:
            camera_track.stop()
        if pc:
            try:
                await pc.close()
            except:
                pass


# uvicorn server-fastapi:app --host 0.0.0.0 --port 8000 --reload
# http://localhost:8000/
# http://192.168.0.131:8000


# INFO:peer-connection:state: failed
# ERROR:peer-connection:connection failed
# INFO:peer-connection:state: failed
# ERROR:peer-connection:connection failed