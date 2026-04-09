import subprocess


class Recorder:
    def __init__(self):
        self.process = None

    def start(self, path):
        self.process = subprocess.Popen([
            "ffmpeg",
            "-y",
            "-f", "v4l2",
            "-i", "/dev/video0",
            "-f", "alsa",
            "-i", "default",
            "-c:v", "libx264",
            "-c:a", "aac",
            path
        ])

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process.wait()