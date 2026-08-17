import numpy as np 
import scipy
from scipy.signal import butter, iirnotch, tf2sos, sosfilt
import State


class AudioFilter:
    def __init__(self, sample_rate=48000, channels=1, notch_freq=8000, notch_freq2=15625):
        self.sample_rate = sample_rate
        self.channels = channels
        self.notch_freq = notch_freq
        self.notch_freq2 = notch_freq2
        self.sos = None
        self.zi = None
        self.expander = None


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

        self.expander = Expander(threshold_db=-50, ratio=4, attack_ms=3, release_ms=250, sample_rate=48000)

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
        
        gain = (State.volume / 100.0) * State.gain
        filtered *= gain
        filtered = self.expander.process(filtered)

        return filtered


class Expander:
    def __init__(self, threshold_db=-40.0, ratio=4, attack_ms=5, release_ms=100, sample_rate=48000):
        self.threshold_db = threshold_db
        self.ratio = ratio
        self.attack_coeff = np.exp(-1 / (sample_rate * attack_ms / 1000))
        self.release_coeff = np.exp(-1 / (sample_rate * release_ms / 1000))
        self.gain = 1
    

    def process(self, audio):
        rms = np.sqrt(np.mean(audio ** 2) + 1e-12)
        level_db = 20 * np.log10(rms)

        if level_db >= self.threshold_db:
            gain_db = 0.0
        else:
            gain_db = (level_db - self.threshold_db) * (self.ratio - 1)
        
        target_gain = 10 ** (gain_db / 20)

        if target_gain < self.gain:
            coeff = self.attack_coeff
        else:
            coeff = self.release_coeff

        self.gain = ( coeff * self.gain + (1 - coeff) * target_gain)
        return audio * self.gain