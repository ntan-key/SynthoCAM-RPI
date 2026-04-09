import asyncio
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack, RTCIceCandidate, MediaStreamTrack, sdp

import logging
import json

import websockets
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError, ConnectionClosed


from old_code.Camera import CameraStreamTrack
from old_code.Microphone import MicrophoneStreamTrack

from old_code.ClientServer import serve_client

import os


def get_capture_ls():
    return os.listdir('./captures')


# def get_thumbnail_ls():
#     pass


async def handle_client(websocket):
    logging.basicConfig(level=logging.INFO)

    client_id = f'client_{id(websocket)}'
    logging.info(f'🔗  {client_id} connected')

    pc = None
    camera_track = None
    audio_track = None

    task = asyncio.create_task(serve_client(websocket))

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get('type', 'unknown')
                # payload = data.get('data', 'unknown')

                if msg_type == 'offer':
                    logging.info("🎬 Processing offer...")

                    try: 
                        pc = RTCPeerConnection()

                        camera_track = CameraStreamTrack()
                        audio_track = MicrophoneStreamTrack()

                        pc.addTrack(camera_track)
                        pc.addTrack(audio_track)
                        logging.info("📹🎤 Video and audio tracks added")

                        @pc.on("icecandidate")
                        async def on_ice(candidate):
                            if candidate:
                                try:
                                    await websocket.send(json.dumps({
                                    'type': 'ice-candidate',
                                    'candidate': {
                                    'candidate': candidate.candidate,
                                    'sdpMid': candidate.sdpMid,
                                    'sdpMLineIndex': candidate.sdpMLineIndex
                                    }
                                    }))
                                except Exception as e:
                                    logging.error(f"❌ ICE send failed: {e}")

                        @pc.on("connectionstatechange")
                        async def on_state():
                            state = pc.connectionState
                            logging.info(f"🔄 State: {state}")
                            if state == "connected":
                                logging.info("🎉 CONNECTED! Streaming video + audio!")
                            elif state == "failed":
                                logging.error("❌ Connection failed")

                        logging.info("📥 Setting remote description...")
                        offer = RTCSessionDescription(sdp=data['sdp'], type=data['type'])
                        await pc.setRemoteDescription(offer)
                        logging.info("✅ Remote description set")

                        logging.info("📤 Creating answer...")
                        answer = await pc.createAnswer()
                        await pc.setLocalDescription(answer)
                        logging.info("✅ Answer created")

                        response = {
                        'type': 'answer',
                        'sdp': pc.localDescription.sdp
                        }

                        # while pc.iceGatheringState != "complete":
                        #     await asyncio.sleep(0.1)
                        await websocket.send(json.dumps(response))
                        logging.info("✅ Answer sent successfully")

                        # @pc.on("icegatheringstatechange")
                        # async def on_ice_gathering():
                        #     logging.info(f"🧊 ICE gathering: {pc.iceGatheringState}")

                    except Exception as e:
                        logging.error(f"❌ Offer processing failed: {e}")
                        continue

                elif msg_type == 'ice-candidate' and pc:
                    try:
                        cand_data = data.get('candidate')
                        if cand_data and 'candidate' in cand_data:
                            candidate = sdp.candidate_from_sdp(cand_data['candidate'])
                            candidate.sdpMid = cand_data.get('sdpMid')
                            candidate.sdpMLineIndex = cand_data.get('sdpMLineIndex')
                        if pc.remoteDescription is not None:
                            await pc.addIceCandidate(candidate)
                            logging.debug("🧊 ICE candidate added")
                    except Exception as e:
                        logging.error(f"❌ ICE candidate error: {e}")

                # elif msg_type == 'file-req':
                #     if payload == 'all':
                #         
                #     pass

                elif msg_type == 'test':
                    print(data.get('data', 'unknown'))
                    if(data.get('data', 'unknown')) == 'ping':
                        await websocket.send(json.dumps({"type": "test", "data": "pong"}))

            except json.JSONDecodeError:
                logging.error('❌ Invalid JSON received')
    except (ConnectionClosedOK, ConnectionClosedError, ConnectionClosed):
        print('client disconnected mid-handshake')
    except Exception as e:
        logging.error(f"❌ Client handler error: {e}")
    finally:
        logging.info(f'⛓️‍💥  {client_id} disconnected')
        logging.info(f'🧹  {client_id} cleanup')
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if audio_track:
            audio_track.stop()
        if camera_track:
            camera_track.stop()
        if pc:
            try:
                await pc.close()
            except:
                pass