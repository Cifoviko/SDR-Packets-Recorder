"""Offline IQ source: replay of a recorded capture file.

Supported formats:
- .npy        -- numpy array of complex64/complex128 (as saved by scripts/capture_iq.py)
- .sc16       -- raw interleaved int16 I/Q (sc16), full-scale = 32768
- .fc32       -- raw complex64 float32 I/Q

Replay can be paced to realtime (default) and looped (default), which makes it
a drop-in replacement for the live USRP source when no hardware is attached.
"""

import os
import time

import numpy as np

from .. import config
from .base import Chunk, Source

CHUNK_SIZE = 16384        # samples per yielded chunk


class IQFileSource(Source):
    """Replay a recorded IQ file as if it were a live stream."""

    def __init__(self, path, samp_rate=config.SAMP_RATE, channel=37,
                 loop=True, realtime=True, speed=1.0):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"IQ file not found: {path}")
        self.path = path
        self.samp_rate = samp_rate
        self.channel = channel
        self.loop = loop
        self.realtime = realtime
        self.speed = speed
        self.description = (f"file replay: {os.path.basename(path)} "
                            f"({samp_rate / 1e6:.0f} MSPS, ch{channel}, loop={'on' if loop else 'off'})")

    def _load(self):
        ext = os.path.splitext(self.path)[1].lower()
        if ext == ".npy":
            return np.load(self.path).astype(np.complex64)
        if ext == ".sc16":
            raw = np.fromfile(self.path, dtype=np.int16)
            iq = raw[0::2].astype(np.float32) / 32768.0 + 1j * raw[1::2].astype(np.float32) / 32768.0
            return iq.astype(np.complex64)
        if ext == ".fc32":
            return np.fromfile(self.path, dtype=np.complex64)
        raise ValueError(f"unsupported IQ file extension {ext!r} "
                         f"(expected .npy, .sc16 or .fc32)")

    def chunks(self):
        samples = self._load()
        freq = config.channel_freq(self.channel)
        print(f"[*] File source started: {self.description}")
        while True:
            for off in range(0, len(samples), CHUNK_SIZE):
                chunk = samples[off: off + CHUNK_SIZE]
                if self.realtime:
                    time.sleep(len(chunk) / self.samp_rate / max(self.speed, 1e-6))
                yield Chunk(samples=chunk, channel=self.channel, frequency=freq)
            if not self.loop:
                return
