import os
import pickle
import unittest

import numpy as np

import advoc.audioio as audioio
import advoc.spectral as spectral


AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'audio')
WAV_MONO = os.path.join(AUDIO_DIR, 'mono.wav')
WAV_MONO_R9Y9 = os.path.join(AUDIO_DIR, 'mono_22k_r9y9.pkl')


class TestSpectralModule(unittest.TestCase):

  def setUp(self):
    _, self.wav_mono_44 = audioio.decode_audio(WAV_MONO, fastwav=True)
    _, self.wav_mono_22 = audioio.decode_audio(WAV_MONO, fs=22050)
    _, self.wav_mono_24 = audioio.decode_audio(WAV_MONO, fs=24000)


  def test_stft(self):
    X = spectral.stft(self.wav_mono_44, 1024, 256)

  def test_r9y9(self):
    with open(WAV_MONO_R9Y9, 'rb') as f:
      r9y9_melspec = pickle.load(f)
    r9y9_melspec = np.swapaxes(r9y9_melspec, 0, 1)[:, :, np.newaxis]

    melspec = spectral.waveform_to_r9y9_feats(self.wav_mono_22)

    self.assertTrue(np.array_equal(melspec, r9y9_melspec), 'not equal r9y9')

if __name__ == '__main__':
  unittest.main()
