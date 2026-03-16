import asyncio
import json
import logging
from collections import deque
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager

# --- Lifespan Handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the UDP server in the background
    udp_task = asyncio.create_task(start_udp_listener())
    yield
    # We could cleanly cancel the task here on shutdown if needed
    udp_task.cancel()

# Create FastAPI app
app = FastAPI(title="TowerMic Detections Visualizer", lifespan=lifespan)

# Set up logging for web
logger = logging.getLogger("web")
logger.setLevel(logging.INFO)

# History buffer: holds the last N detections to immediately send to new clients
HISTORY_MAX = 100
history = deque(maxlen=HISTORY_MAX)

# Active WebSocket connections
active_connections: list[WebSocket] = []

# Resolve paths
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
BG_IMAGE_PATH = STATIC_DIR / "background.png"

# Mount static files (will serve index.html)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def get_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>index.html not found</h1>", status_code=404)
    with open(index_path, "r") as f:
        return HTMLResponse(content=f.read(), status_code=200)

@app.get("/background")
async def get_background():
    if not BG_IMAGE_PATH.exists():
        return HTMLResponse("<h1>Background image not found</h1>", status_code=404)
    return FileResponse(BG_IMAGE_PATH)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    logger.info(f"Client connected. Active: {len(active_connections)}")
    try:
        if history:
            await websocket.send_text(json.dumps({
                "type": "history",
                "data": list(history)
            }))
            
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        logger.info(f"Client disconnected. Active: {len(active_connections)}")


# --- UDP Listener for incoming detections from main.py ---

class DetectionUDPProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data, addr):
        try:
            # Decode JSON payload sent by main.py
            msg = json.loads(data.decode('utf-8'))
            
            # Store in history buffer
            history.append(msg)
            
            # Prepare WS payload
            payload = json.dumps({"type": "live", "data": msg})
            
            # Broadcast to all connected WebSockets
            disconnected = []
            for connection in active_connections:
                try:
                    # Fire and forget sending
                    asyncio.create_task(connection.send_text(payload))
                except Exception as e:
                    disconnected.append(connection)
                    
            for connection in disconnected:
                if connection in active_connections:
                    active_connections.remove(connection)
                    
        except Exception as e:
            logger.error(f"Error processing UDP packet from {addr}: {e}")

async def start_udp_listener():
    loop = asyncio.get_running_loop()
    logger.info("Starting UDP listener on port 9001 for internal detections...")
    # Listen on all interfaces on port 9001
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DetectionUDPProtocol(),
        local_addr=('0.0.0.0', 9001)
    )

def run_server():
    """
    Starts the Uvicorn server blockingly.
    """
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="warning")

if __name__ == "__main__":
    run_server()