from aiortc import RTCPeerConnection, sdp, RTCSessionDescription
import logging
import asyncio

from CameraTrack import CameraTrack
from MicrophoneTrack import MicrophoneTrack


logger = logging.getLogger('MediaManager')


class MediaManager:
    def __init__(self):
        self.pc = RTCPeerConnection()
        self.camera_manager = CameraManager()
        self.microphone_track = MicrophoneTrack()


    def __del__(self):
        del self.microphone_track