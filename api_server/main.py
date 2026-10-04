import asyncio
import json
import zmq
import zmq.asyncio
import numpy as np
import concurrent.futures
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from processing.ble_parser import BleDecoder
from .ws_manager import manager

app = FastAPI(title="BLE SDR Analyzer API")

# Process pool for CPU-bound tasks (Scapy parsing)
process_pool = concurrent.futures.ProcessPoolExecutor(max_workers=4)

def decode_task(packet_bytes: bytes, iq_bytes: bytes) -> dict:
    """Synchronous function for the Process Pool."""
    iq_array = np.frombuffer(iq_bytes, dtype=np.complex64).tolist()
    return BleDecoder.parse_packet(packet_bytes, iq_array)

async def zmq_listener_task():
    """Listens to SDR data via ZMQ and broadcasts parsed packets via WebSockets."""
    context = zmq.asyncio.Context()
    socket = context.socket(zmq.SUB)
    socket.connect("tcp://127.0.0.1:5555")
    socket.setsockopt_string(zmq.SUBSCRIBE, "")

    print("[API] ZMQ Listener connected. Waiting for raw data...")
    loop = asyncio.get_running_loop()

    while True:
        multipart_msg = await socket.recv_multipart()
        
        if len(multipart_msg) == 3:
            meta_bytes, packet_bytes, iq_bytes = multipart_msg
            meta = json.loads(meta_bytes.decode('utf-8'))
            
            # В decode_task передаем np.ndarray вместо list для производительности
            iq_array = np.frombuffer(iq_bytes, dtype=np.complex64)
            result = await loop.run_in_executor(
                process_pool, 
                BleDecoder.parse_packet, 
                meta, packet_bytes, iq_array
            )
            
            # Broadcast to all connected UI clients if parsing was successful
            if result.get("status") == "ok":
                await manager.broadcast_json(result)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(zmq_listener_task())

@app.on_event("shutdown")
def shutdown_event():
    process_pool.shutdown()

# WebSocket endpoint for the UI
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # We only send data to the client, but we must keep reading to detect disconnects
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Serve the Frontend UI
# We mount the 'ui' directory at the root
app.mount("/static", StaticFiles(directory="ui"), name="static")

@app.get("/")
async def read_index():
    """Serve the main HTML file."""
    return FileResponse("ui/index.html")

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "api_server.main:app", 
        host="127.0.0.1", 
        port=8000, 
        reload=True 
    )
    