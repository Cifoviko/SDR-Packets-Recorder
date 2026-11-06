"""Processing pipeline: source stream -> burst detection -> BLE decoding.

Also contains the shared state objects used by the web layer:
- PacketStore: thread-safe ring buffer of decoded packet metadata
- Stats: thread-safe counters and error log
"""

import threading
import time

import numpy as np

from . import dsp
from . import config
from .storage import make_dataset_filename


class PacketStore:
    """Thread-safe ring buffer of decoded packet metadata dicts."""

    def __init__(self, cap=500):
        self._cap = cap
        self._items = []
        self._lock = threading.Lock()

    def add(self, msg):
        with self._lock:
            self._items.append(msg)
            if len(self._items) > self._cap:
                del self._items[: len(self._items) - self._cap]

    def latest(self, n=200):
        with self._lock:
            return list(reversed(self._items[-n:]))

    def __len__(self):
        with self._lock:
            return len(self._items)


class Stats:
    """Thread-safe application statistics snapshot."""

    def __init__(self):
        self._lock = threading.Lock()
        self._d = {
            "running": False,
            "source": "",
            "channel": 37,
            "bursts": 0,         # energy bursts detected
            "decoded": 0,        # packets with valid CRC
            "dropped": 0,        # chunks dropped by the source (overruns)
            "errors": [],
        }

    def set(self, key, value):
        with self._lock:
            self._d[key] = value

    def inc(self, key, n=1):
        with self._lock:
            self._d[key] += n

    def add_error(self, msg):
        with self._lock:
            self._d["errors"].append(msg)
            del self._d["errors"][:-20]

    def snapshot(self):
        with self._lock:
            out = dict(self._d)
            out["errors"] = out["errors"][-5:]
            out["total_messages"] = None    # filled in by the web layer
            return out


class Processor:
    """Consumes a Source and fills a PacketStore + DatasetWriter with decoded packets."""

    def __init__(self, source, store, writer, stats,
                 chunk=config.CHUNK, guard=config.GUARD, sps=config.SPS):
        self.source = source
        self.store = store
        self.writer = writer
        self.stats = stats
        self.chunk = chunk
        self.guard = guard
        self.sps = sps

    def run(self):
        """Blocking main loop. Runs until the source is exhausted or raises."""
        self.stats.set("running", True)
        self.stats.set("source", self.source.description)
        print(f"[*] Processor started on {self.source.description}")
        pending = []
        pending_len = 0
        try:
            for item in self.source.chunks():
                self.stats.set("channel", item.channel)
                if getattr(self.source, "dropped", None):
                    self.stats.set("dropped", self.source.dropped)
                pending.append(item.samples)
                pending_len += len(item.samples)
                if pending_len < self.chunk + self.guard:
                    continue

                buf = pending[0] if len(pending) == 1 else np.concatenate(pending)
                pending = []
                pending_len = 0

                consumed = self._process_window(buf, item.channel, item.frequency)
                if consumed:
                    tail = buf[consumed:]
                    pending = [tail]
                    pending_len = len(tail)
        except Exception as ex:     # noqa: BLE001 - report and stop; web layer stays alive
            self.stats.add_error(f"{type(ex).__name__}: {ex}")
            print(f"[!] Processor stopped with error: {ex}")
        finally:
            self.stats.set("running", False)

    def _process_window(self, buf, channel, freq):
        """Detect and decode all complete bursts in the buffer.

        Returns the number of samples that can be safely discarded.
        """
        sps = self.sps
        consumed = 0
        for s, e in dsp.detect_bursts(buf, min_len=50 * sps, max_len=1000 * sps,
                                      smooth=8 * sps, merge_gap=25 * sps, margin=16 * sps):
            if e + 100 > len(buf):
                continue                            # burst clipped by the buffer -> wait for its tail
            ss = max(0, s - 16 * sps)
            ee = min(len(buf), e + 16 * sps)
            self.stats.inc("bursts")
            parsed = dsp.decode_capture(buf[ss:ee], channel=channel, sps=sps)
            if parsed:
                self.stats.inc("decoded")
                self._save_packet(buf[ss:ee], parsed, channel, freq)
            consumed = max(consumed, ee)
        return consumed

    def _save_packet(self, iq, parsed, channel, freq):
        ts = time.time()
        fname = make_dataset_filename(parsed, ts)
        msg = {
            "timestamp": ts,
            "channel": channel,
            "frequency": freq,
            "pdu_type": parsed["pdu_type"],
            "mac": parsed["mac"],
            "length": parsed["length"],
            "payload": parsed["payload"],
            "iq_file": f"/dataset/{fname}",
            "iq_samples": int(len(iq)),
        }
        self.store.add(msg)
        self.writer.enqueue(fname, np.ascontiguousarray(iq, dtype=np.complex128))
