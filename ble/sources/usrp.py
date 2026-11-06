"""Live IQ source: USRP B210 via UHD.

Receiving and channel hopping run in a dedicated thread that only drains the
USB stream into a queue; the consumer pulls chunks from the queue. This keeps
the USB FIFO from overflowing even when the processing thread is busy.
"""

import queue
import threading
import time

import numpy as np

from .. import config
from .base import Chunk, Source

RECV_BUF = 8192           # samples per recv() call
QUEUE_SIZE = 64           # ~0.25 s of buffered IQ at 2 MSPS
STREAM_ARGS = "num_recv_frames=256,recv_frame_size=16384"   # large USB FIFO tolerates CPU spikes


class UsrpSource(Source):
    """Live stream from a USRP B210 (antenna RX2)."""

    def __init__(self, device="type=b200", samp_rate=config.SAMP_RATE, gain=config.GAIN,
                 channels=config.CHANNELS, hop_interval=config.HOP_INTERVAL):
        self.device = device
        self.samp_rate = samp_rate
        self.gain = gain
        self.channels = tuple(channels)
        self.hop_interval = hop_interval
        self.description = f"USRP B210 @ {samp_rate / 1e6:.0f} MSPS, RX2, gain={gain}"
        self._queue = queue.Queue(maxsize=QUEUE_SIZE)
        self._dropped = 0
        self._stop = threading.Event()
        self._current_channel = self.channels[0][0]

    @property
    def dropped(self):
        """Number of chunks discarded because the consumer could not keep up."""
        return self._dropped

    @property
    def current_channel(self):
        return self._current_channel

    def chunks(self):
        import uhd   # imported lazily so the rest of the app works without UHD installed

        usrp = uhd.usrp.MultiUSRP(self.device)
        usrp.set_rx_rate(self.samp_rate, 0)
        usrp.set_rx_gain(self.gain, 0)
        usrp.set_rx_antenna("RX2", 0)

        st_args = uhd.usrp.StreamArgs("fc32", "sc16")
        st_args.channels = [0]
        st_args.args = STREAM_ARGS
        stream = usrp.get_rx_stream(st_args)

        stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.start_cont)
        stream_cmd.stream_now = True

        tmp = np.zeros(RECV_BUF, dtype=np.complex64)
        md = uhd.types.RXMetadata()
        freq_map = dict(self.channels)

        def recv_loop():
            stream.issue_stream_cmd(stream_cmd)
            last_hop = time.time()
            hop_idx = 0
            while not self._stop.is_set():
                if self.hop_interval and time.time() - last_hop > self.hop_interval:
                    hop_idx = (hop_idx + 1) % len(self.channels)
                    self._current_channel = self.channels[hop_idx][0]
                    usrp.set_rx_freq(uhd.types.TuneRequest(self.channels[hop_idx][1]), 0)
                    last_hop = time.time()
                n = stream.recv(tmp, md, 0.5)
                if n <= 0:
                    continue
                try:
                    self._queue.put_nowait(tmp[:n].copy())
                except queue.Full:
                    # consumer is behind: drop the oldest chunk to stay realtime
                    try:
                        self._queue.get_nowait()
                        self._dropped += 1
                        self._queue.put_nowait(tmp[:n].copy())
                    except queue.Empty:
                        pass

        threading.Thread(target=recv_loop, daemon=True).start()
        print(f"[*] USRP source started: {self.samp_rate / 1e6:.0f} MSPS, antenna RX2, gain={self.gain}")

        try:
            while not self._stop.is_set():
                try:
                    samples = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                ch = self._current_channel
                yield Chunk(samples=samples, channel=ch, frequency=freq_map.get(ch, 0.0))
        finally:
            self._stop.set()
            try:
                stream.issue_stream_cmd(uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont))
            except Exception:   # noqa: BLE001 - device may already be gone
                pass

    def close(self):
        self._stop.set()
