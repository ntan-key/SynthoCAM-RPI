import numpy as np 
import scipy
from scipy.signal import butter, iirnotch, tf2sos, sosfilt
import State


class AudioFilter:
    def __init__(self, sample_rate=48000, channels=1, volume=100, gain=3.0, notch_freq=8000, notch_freq2=15625):
        self.sample_rate = sample_rate
        self.channels = channels
        self.volume = volume
        self.gain = gain
        self.notch_freq = notch_freq
        self.notch_freq2 = notch_freq2
        self.sos = None
        self.zi = None


    def build_filters(self):
        high_pass = butter(2, State.lower_cutoff, btype="highpass", fs=self.sample_rate, output="sos")
        
        low_pass = butter(2, State.upper_cutoff, btype="lowpass", fs=self.sample_rate, output="sos")
        # added for sharper cuttoff
        low_pass2 = butter(2, State.upper_cutoff, btype="lowpass", fs=self.sample_rate, output="sos")
        
        # try to remove video /constant frequency noise(s)
        b, a = iirnotch(self.notch_freq, 2, fs=self.sample_rate)  # added to remove ~8Khz
        notch1 = tf2sos(b, a)

        # try to remove video /constant frequency noise(s) - PAL video horizontal scan freq
        b, a = iirnotch(self.notch_freq2, 3, fs=self.sample_rate)
        notch2 = tf2sos(b, a)

        self.sos = np.vstack([high_pass, low_pass, low_pass2, notch1, notch2])
        self.zi = np.zeros((self.sos.shape[0], 2, self.channels), dtype=np.float32)

        # // Expander (soft noise gate) to reduce realatively backgound to signal noise... (WIP)
        # const compressor = audioContext.createDynamicsCompressor();
        # compressor.threshold.value = -50;
        # compressor.knee.value = 20;
        # compressor.ratio.value = 4;
        # compressor.attack.value = 0.003;
        # compressor.release.value = 0.25;


    def process(self, audio):
        self.build_filters()
        audio = np.asarray(audio, dtype=np.float32)

        filtered, self.zi = sosfilt(self.sos, audio, axis=0, zi=self.zi)
        
        gain = (self.volume / 100.0) * self.gain
        filtered *= gain

        return filtered
