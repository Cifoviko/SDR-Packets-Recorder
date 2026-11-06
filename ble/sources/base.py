"""Base types for IQ signal sources."""

from dataclasses import dataclass

import numpy as np


@dataclass
class Chunk:
    """A piece of raw IQ stream tagged with its BLE channel."""
    samples: np.ndarray      # 1-D complex64 array
    channel: int             # BLE channel number (37/38/39 for advertising)
    frequency: float         # center frequency in Hz


class Source:
    """Base class for IQ sources. chunks() is a blocking generator of Chunk."""

    description = "abstract source"

    def chunks(self):
        """Yield Chunk objects. Runs until closed or forever."""
        raise NotImplementedError

    def close(self):
        """Stop the source and release hardware resources."""
