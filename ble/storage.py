"""Dataset persistence: writes decoded packet IQ captures to disk.

Writing runs in a dedicated thread with a bounded queue, so slow storage can
never block the signal processing pipeline.
"""

import os
import queue
import threading

import numpy as np


def make_dataset_filename(parsed, ts):
    """Build a filesystem-safe dataset filename from packet metadata."""
    mac = "".join(c if c.isalnum() else "_" for c in parsed.get("mac", "unknown"))
    return f"{int(ts * 1000)}_{mac}_{parsed['pdu_type']}.npy"


class DatasetWriter:
    """Background .npy writer for decoded packet captures."""

    def __init__(self, dataset_dir, queue_size=100):
        self.dataset_dir = dataset_dir
        os.makedirs(dataset_dir, exist_ok=True)
        self._queue = queue.Queue(maxsize=queue_size)
        self._errors = []
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def enqueue(self, fname, iq):
        """Queue an IQ array for writing. Rarely drops on prolonged overload."""
        try:
            self._queue.put_nowait((fname, iq))
        except queue.Full:
            with self._lock:
                self._errors.append("DatasetWriter queue full, packet dropped")

    @property
    def errors(self):
        with self._lock:
            return list(self._errors[-5:])

    def _loop(self):
        while True:
            fname, iq = self._queue.get()
            try:
                np.save(os.path.join(self.dataset_dir, fname), iq)
            except Exception as ex:     # noqa: BLE001 - keep the writer alive
                with self._lock:
                    self._errors.append(f"save: {type(ex).__name__}: {ex}")
