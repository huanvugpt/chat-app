from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import json
import os
from typing import Set

app = FastAPI()
templates = Jinja2Templates(directory="backend/templates")

# ===== Config =====
TOKEN = "chucmungsinhnhat"
DATA_DIR = "backend/data"
os.makedirs(DATA_DIR, exist_ok=True)

clients: Set[WebSocket] = set()

def get_today_file():
    return os.path.join(DATA_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.json")

def save_message(message):
    file_path = get_today_file()
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
    with open(file_path, "r+", encoding="utf-8") as f:
        try:
            data = json.load(f)
            if not isinstance(data, list):
                data = []
        except json.JSONDecodeError:
            data = []
        data.append(message)
        f.seek(0)
        f.truncate(0)
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_recent_messages(minutes=15):
    file_path = get_today_file()
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return []
    cutoff = datetime.now() - timedelta(minutes=minutes)
    res = []
    for msg in data:
        ts = msg.get("timestamp")
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        if dt > cutoff:
            res.append(msg)
    return res

@app.post("/check-token")
async def check_token(payload: dict):
    return {"valid": payload.get("token") == TOKEN}

@app.get("/", response_class=HTMLResponse)
async def get_chat_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if token != TOKEN:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    clients.add(websocket)

    for msg in load_recent_messages():
        try:
            await websocket.send_json(msg)
        except Exception:
            pass

    try:
        while True:
            data = await websocket.receive_json()
            message = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user": data.get("user", "unknown"),
                "text": data.get("text", ""),
                "image": data.get("image")  # có thể là None
            }

            # Nếu muốn ảnh KHÔNG lưu => chỉ lưu nếu không phải ảnh
            if not message["image"]:
                save_message(message)

            dead = []
            for client in clients:
                try:
                    await client.send_json(message)
                except Exception:
                    dead.append(client)
            for d in dead:
                clients.remove(d)

    except WebSocketDisconnect:
        pass
    finally:
        if websocket in clients:
            clients.remove(websocket)
