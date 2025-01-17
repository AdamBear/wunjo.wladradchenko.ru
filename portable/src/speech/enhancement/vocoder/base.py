import os
import numpy as np
import torch.nn as nn
import torch
import librosa

from speech.enhancement.vocoder.model.generator import Generator
from speech.enhancement.tools.wav import read_wave, save_wave
from speech.enhancement.tools.pytorch_util import check_cuda_availability, try_tensor_cuda, tensor2numpy
from speech.enhancement.vocoder.model.util import load_checkpoint, load_try, tr_normalize, linear_to_mel, pre, amp_to_db, normalize, tr_amp_to_db, tr_pre
from speech.enhancement.vocoder.config import Config


class Vocoder(nn.Module):
    def __init__(self, sample_rate, model_vocoder_path):
        super(Vocoder, self).__init__()
        Config.refresh(sample_rate)
        self.rate = sample_rate
        if(not os.path.exists(model_vocoder_path)):
            raise RuntimeError("Error 1: The checkpoint for synthesis module / vocoder (model.ckpt-1490000_trimed) is not found in ~/.wunjo/rtvc/general. \
                                By default the checkpoint should be download automatically by this program. Something bad may happened. Apologies for the inconvenience.\
                                But don't worry! Alternatively you can download it directly from Zenodo: https://zenodo.org/record/5600188/files/model.ckpt-1490000_trimed.pt?download=1")
        self._load_pretrain(model_vocoder_path)
        self.weight_torch = Config.get_mel_weight_torch(percent=1.0)[
            None, None, None, ...
        ]

    def _load_pretrain(self, pth):
        self.model = Generator(Config.cin_channels)
        checkpoint = load_checkpoint(pth, torch.device("cpu"))
        load_try(checkpoint["generator"], self.model)
        self.model.eval()
        self.model.remove_weight_norm()
        self.model.remove_weight_norm()
        for p in self.model.parameters():
            p.requires_grad = False


    def forward(self, mel, cuda=False):
        """
        :param non normalized mel spectrogram: [batchsize, 1, t-steps, n_mel]
        :return: [batchsize, 1, samples]
        """
        assert mel.size()[-1] == 128
        check_cuda_availability(cuda=cuda)
        self.model = try_tensor_cuda(self.model, cuda=cuda)
        mel = try_tensor_cuda(mel, cuda=cuda)
        self.weight_torch = self.weight_torch.type_as(mel)
        mel = mel / self.weight_torch
        mel = tr_normalize(tr_amp_to_db(torch.abs(mel)) - 20.0)
        mel = tr_pre(mel[:, 0, ...])
        wav_re = self.model(mel)
        return wav_re

    def oracle(self, fpath, out_path, cuda=False):
        check_cuda_availability(cuda=cuda)
        self.model = try_tensor_cuda(self.model, cuda=cuda)
        wav = read_wave(fpath, sample_rate=self.rate)[..., 0]
        wav = wav / np.max(np.abs(wav))
        stft = np.abs(
            librosa.stft(
                wav,
                hop_length=Config.hop_length,
                win_length=Config.win_size,
                n_fft=Config.n_fft,
            )
        )
        mel = linear_to_mel(stft)
        mel = normalize(amp_to_db(np.abs(mel)) - 20)
        mel = pre(np.transpose(mel, (1, 0)))
        mel = try_tensor_cuda(mel, cuda=cuda)
        with torch.no_grad():
            wav_re = self.model(mel)
            save_wave(tensor2numpy(wav_re * 2**15), out_path, sample_rate=self.rate)
