from fastapi import WebSocket
from typing import List
import json

class ConnectionManager:
    """
    Manages active WebSocket connections to broadcast data to the UI.
    """
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accepts a new WebSocket connection and adds it to the pool."""
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WS] Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Removes a closed WebSocket connection from the pool."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"[WS] Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast_json(self, data: dict):
        """
        Sends a JSON object to all connected WebSockets.
        """
        # Create a copy of the list to avoid issues if a client disconnects during broadcast
        for connection in list(self.active_connections):
            try:
                await connection.send_json(data)
            except Exception as e:
                print(f"[WS] Error sending data to client: {e}")
                self.disconnect(connection)

# Global instance to be used in main.py
manager = ConnectionManager()
