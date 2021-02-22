import logging
import typing

import numpy as np
import onnxruntime

from .audio import inverse, transform
from .constants import VocoderModel, VocoderModelConfig

_LOGGER = logging.getLogger("hifi_gan")

# -----------------------------------------------------------------------------


class HiFiGanVocoder(VocoderModel):
    def __init__(self, config: VocoderModelConfig):
        super(HiFiGanVocoder, self).__init__(config)
        self.config = config

        _LOGGER.debug("Loading HiFi-GAN model from %s", config.model_path)
        self.generator = onnxruntime.InferenceSession(
            str(config.model_path), sess_options=config.session_options
        )

        self.mel_channels = 80
        self.max_wav_value = 32768.0

        # Initialize denoiser
        self.denoiser_strength = config.denoiser_strength
        self.bias_spec: typing.Optional[np.ndarray] = None

        if self.denoiser_strength > 0:
            _LOGGER.debug("Initializing denoiser")
            mel_zeros = np.zeros(shape=(1, self.mel_channels, 88), dtype=np.float32)
            bias_audio = self.generator.run(None, {"mel": mel_zeros})[0].squeeze(0)
            bias_spec, _ = transform(bias_audio)

            self.bias_spec = bias_spec[:, :, 0][:, :, None]

    def mels_to_audio(self, mels: np.ndarray) -> np.ndarray:
        """Convert mel spectrograms to WAV audio"""
        audio = self.generator.run(None, {"mel": mels})[0].squeeze(0)
        if self.denoiser_strength > 0:
            _LOGGER.debug("Running denoiser (strength=%s)", self.denoiser_strength)
            audio = self.denoise(audio)

        audio = audio * self.max_wav_value
        audio = audio.astype("int16")

        return audio.squeeze(0)

    def denoise(self, audio: np.ndarray) -> np.ndarray:
        assert self.bias_spec is not None

        audio_spec, audio_angles = transform(audio)
        audio_spec_denoised = audio_spec - (self.bias_spec * self.denoiser_strength)
        audio_spec_denoised = np.clip(audio_spec_denoised, a_min=0.0, a_max=None)
        audio_denoised = inverse(audio_spec_denoised, audio_angles)

        return audio_denoised
