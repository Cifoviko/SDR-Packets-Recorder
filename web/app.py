"""FastAPI web layer: REST API and static UI.

Pure presentation layer - all state is injected via create_app(), so this
module has no side effects and no hardware dependencies.
"""

import os

import numpy as np
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def create_app(store, stats, writer, processor, dataset_dir, static_dir):
    """Build the FastAPI application around shared state objects."""
    app = FastAPI(title="BLE Passive Identifier")

    # ------------------------------------------------------------------
    # Data endpoints
    # ------------------------------------------------------------------
    @app.get("/api/devices")
    def get_devices():
        """All observed devices aggregated by MAC address."""
        return store.devices()

    @app.get("/api/devices/{mac}/packets")
    def get_device_packets(mac: str, with_iq: bool = False, limit: int = 100, max_points: int = 512):
        """Packets of a single device, newest first.

        with_iq=true embeds downsampled raw I/Q arrays into every packet so the
        UI can render all signal plots in one request.
        """
        packets = [dict(m) for m in store.by_mac(mac, limit=limit)]
        if with_iq:
            for m in packets:
                safe = os.path.basename(m.get("iq_file", ""))
                path = os.path.join(dataset_dir, safe)
                if not os.path.isfile(path):
                    continue
                arr = np.load(path)
                stride = max(1, int(len(arr)) // max_points)
                x = arr[::stride]
                m["n_total"] = int(len(arr))
                m["i"] = [round(float(v), 5) for v in x.real]
                m["q"] = [round(float(v), 5) for v in x.imag]
        return packets

    @app.get("/api/messages")
    def get_messages():
        """All captured packets regardless of device, newest first."""
        return store.latest(200)

    @app.get("/api/stats")
    def get_stats():
        snap = stats.snapshot()
        snap["total_messages"] = len(store)
        snap["errors"] = snap["errors"] + [e for e in writer.errors if e not in snap["errors"]]
        return snap

    @app.get("/api/iq/{fname}")
    def get_iq_data(fname: str, max_points: int = 1024):
        """Raw IQ samples of a packet as JSON arrays (downsampled)."""
        safe = os.path.basename(fname)
        path = os.path.join(dataset_dir, safe)
        if not os.path.isfile(path):
            return {"error": "not found"}
        arr = np.load(path)
        stride = max(1, int(len(arr)) // max_points)
        x = arr[::stride]
        return {
            "n_total": int(len(arr)),
            "n": int(len(x)),
            "downsampled": stride > 1,
            "i": [round(float(v), 5) for v in x.real],
            "q": [round(float(v), 5) for v in x.imag],
        }

    @app.get("/dataset/{fname}")
    def get_dataset_file(fname: str):
        # basename() prevents path traversal outside the dataset directory
        safe = os.path.basename(fname)
        path = os.path.join(dataset_dir, safe)
        if not os.path.isfile(path):
            return {"error": "not found"}
        return FileResponse(path, media_type="application/octet-stream", filename=safe)

    # ------------------------------------------------------------------
    # Control endpoints
    # ------------------------------------------------------------------
    @app.post("/api/control/pause")
    def control_pause():
        processor.pause()
        return {"paused": True}

    @app.post("/api/control/resume")
    def control_resume():
        processor.resume()
        return {"paused": False}

    @app.post("/api/control/reset")
    def control_reset():
        """Drop all captured packets and delete dataset files."""
        store.clear()
        removed = 0
        for f in os.listdir(dataset_dir):
            if f.endswith(".npy"):
                os.remove(os.path.join(dataset_dir, f))
                removed += 1
        return {"reset": True, "files_removed": removed}

    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app
