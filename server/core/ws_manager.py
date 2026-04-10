import json
from datetime import datetime

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        data = json.dumps(message, ensure_ascii=False)
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def broadcast_task_change(task_id: int, task_data: dict, action: str):
    await manager.broadcast({
        "type": "task_change",
        "action": action,
        "task_id": task_id,
        "task": task_data,
    })


async def broadcast_hb_log(line: str):
    await manager.broadcast({
        "type": "hb_log",
        "line": line,
        "timestamp": datetime.utcnow().isoformat(),
    })


async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except Exception:
        manager.disconnect(websocket)
