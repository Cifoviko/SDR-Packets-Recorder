"""Synthetic IQ source: generates a realistic BLE advertising environment.

The stream consists of a noise floor plus GFSK-modulated advertising packets
with valid CRC and whitening, random static MAC addresses, plausible AD
structures, random carrier offset and amplitude. Everything is produced by the
same DSP code that decodes real traffic, so the full pipeline is exercised.
"""

import time

import numpy as np

from .. import config
from .. import dsp
from .base import Chunk, Source

CHUNK_SIZE = 16384        # samples per yielded chunk

_COMPANY_IDS = (0x0006, 0x004C, 0x00E0, 0x00F0, 0x0075, 0x02E5)  # Microsoft, Apple, Google, ...
_SERVICE_UUIDS = (0xF1FE, 0xFEAA, 0x180F, 0xFFF9)


class SyntheticSource(Source):
    """Generate fake but fully valid BLE advertising traffic."""

    def __init__(self, samp_rate=config.SAMP_RATE, sps=config.SPS, channel=37,
                 hop=False, hop_interval=config.HOP_INTERVAL,
                 packets_per_sec=30.0, noise_amp=0.01, realtime=True, seed=None):
        self.samp_rate = samp_rate
        self.sps = sps
        self.channel = channel
        self.hop = hop
        self.hop_interval = hop_interval
        self.packets_per_sec = packets_per_sec
        self.noise_amp = noise_amp
        self.realtime = realtime
        self.seed = seed
        self.description = (f"synthetic BLE traffic (~{packets_per_sec:.0f} pkt/s, "
                            f"ch{channel}{' + hop' if hop else ''})")

    # ------------------------------------------------------------------
    def _build_ad_data(self, rng):
        """Random plausible advertising data (AD structures), max 31 bytes."""
        parts = bytearray(b"\x02\x01\x06")                    # flags
        while len(parts) < 28:
            kind = rng.integers(0, 3)
            if kind == 0:                                     # manufacturer specific
                comp = int(rng.choice(_COMPANY_IDS))
                body = rng.integers(0, 256, 8, dtype=np.uint8)
                ad = bytes([len(body) + 2, 0xFF, comp & 0xFF, comp >> 8]) + bytes(body)
            elif kind == 1:                                   # service data, 16-bit UUID
                uuid = int(rng.choice(_SERVICE_UUIDS))
                body = rng.integers(0, 256, 4, dtype=np.uint8)
                ad = bytes([len(body) + 2, 0x16, uuid & 0xFF, uuid >> 8]) + bytes(body)
            else:                                             # complete local name
                name = f"DEV-{int(rng.integers(1000, 9999))}".encode()
                ad = bytes([len(name) + 1, 0x09]) + name
            if len(parts) + len(ad) > 31:
                break
            parts += ad
        return bytes(parts)

    def _build_packet(self, rng, channel):
        """Build one valid advertising packet (bits in transmission order)."""
        pdu_type = int(rng.choice([0, 0, 0, 2, 2, 4, 7], p=[0.3, 0.2, 0.1, 0.15, 0.1, 0.05, 0.1]))
        if pdu_type == 7:                                     # ADV_EXT_IND-like payload
            payload = bytes(rng.integers(0, 256, int(rng.integers(8, 24)), dtype=np.uint8))
        else:
            adva = bytearray(rng.integers(0, 256, 6, dtype=np.uint8))
            adva[0] |= 0xC0                                   # static random address marker
            payload = bytes(adva) + self._build_ad_data(rng)
        pdu = bytes([pdu_type, len(payload)]) + payload
        crc = dsp.crc24(pdu)
        crc_bytes = crc.to_bytes(3, "little")
        whitened = dsp.whiten_bytes(pdu + crc_bytes, channel)
        return dsp.PREAMBLE_BITS + dsp.AA_BITS + dsp.bytes_to_bits(whitened)

    # ------------------------------------------------------------------
    def chunks(self):
        rng = np.random.default_rng(self.seed)
        freq_map = dict(config.CHANNELS)
        print(f"[*] Synthetic source started: {self.description}")
        next_packet_at = rng.exponential(1.0 / self.packets_per_sec)
        t = 0.0
        last_hop = time.time()
        channel = self.channel
        while True:
            duration = CHUNK_SIZE / self.samp_rate
            chunk = (self.noise_amp / np.sqrt(2) *
                     (rng.standard_normal(CHUNK_SIZE) + 1j * rng.standard_normal(CHUNK_SIZE))
                     ).astype(np.complex64)

            # schedule all packets that start inside this chunk
            while next_packet_at < t + duration:
                offset = int((next_packet_at - t) * self.samp_rate)
                bits = self._build_packet(rng, channel)
                sig = dsp.modulate_gfsk(bits, self.sps, self.samp_rate)
                amp = float(rng.uniform(0.03, 0.12))
                cfo = 2j * np.pi * float(rng.uniform(-60e3, 60e3)) / self.samp_rate
                n = min(len(sig), CHUNK_SIZE - offset)
                chunk[offset: offset + n] += amp * sig[:n] * np.exp(cfo * np.arange(n))
                next_packet_at += float(rng.exponential(1.0 / self.packets_per_sec))

            if self.hop and time.time() - last_hop > self.hop_interval:
                idx = [c for c, _ in config.CHANNELS].index(channel)
                channel = config.CHANNELS[(idx + 1) % len(config.CHANNELS)][0]
                last_hop = time.time()

            yield Chunk(samples=chunk, channel=channel,
                        frequency=freq_map.get(channel, config.channel_freq(channel)))
            t += duration
            if self.realtime:
                time.sleep(duration)
