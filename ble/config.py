"""Global configuration constants for the BLE Passive Identifier application."""

import os

# Project root (parent of the ble package)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Default directories
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
SAMPLES_DIR = os.path.join(BASE_DIR, "samples")
STATIC_DIR = os.path.join(BASE_DIR, "web", "static")

# BLE advertising channels: (channel number, center frequency in Hz)
CHANNELS = ((37, 2.402e9), (38, 2.426e9), (39, 2.480e9))

# USRP settings
SAMP_RATE = 2e6          # 2 MSPS = 16 MB/s (stable even on weak USB hosts)
GAIN = 50
HOP_INTERVAL = 2.0       # seconds per channel (retune briefly drops the stream, so hop rarely)

# Demodulation settings
SPS = 2                  # samples per symbol at SAMP_RATE

# Processing window settings (in samples)
CHUNK = 16384            # samples per processing iteration
GUARD = 3000             # tail of the buffer left unprocessed (protection against clipped bursts)

# Web server
WEB_PORT = 5000


def channel_freq(channel):
    """Map a BLE channel number to its center frequency in Hz."""
    for ch, freq in CHANNELS:
        if ch == channel:
            return freq
    # Data channels: 2404 MHz + 2 MHz * (ch - 11)
    return 2.404e9 + (channel - 11) * 2e6
