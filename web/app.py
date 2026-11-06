"""FastAPI web layer: REST API and static UI.

Pure presentation layer - all state is injected via create_app(), so this
module has no side effects and no hardware dependencies.
"""

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def create_app(store, stats, writer, dataset_dir, static_dir):
    """Build the FastAPI application around shared state objects."""
    app = FastAPI(title="BLE Passive Identifier")

    @app.get("/api/messages")
    def get_messages():
        return store.latest(200)

    @app.get("/api/stats")
    def get_stats():
        snap = stats.snapshot()
        snap["total_messages"] = len(store)
        snap["errors"] = snap["errors"] + [e for e in writer.errors if e not in snap["errors"]]
        return snap

    @app.get("/dataset/{fname}")
    def get_dataset_file(fname: str):
        # basename() prevents path traversal outside the dataset directory
        safe = os.path.basename(fname)
        path = os.path.join(dataset_dir, safe)
        if not os.path.isfile(path):
            return {"error": "not found"}
        return FileResponse(path, media_type="application/octet-stream", filename=safe)

    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app
