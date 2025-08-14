from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import json
import os
import glob
from typing import Set

app = FastAPI()
templates = Jinja2Templates(directory="backend/templates")

# ===== Config =====
TOKEN = "chucmungsinhnhat"
DATA_DIR = "backend/data"
os.makedirs(DATA_DIR, exist_ok=True)

clients: Set[WebSocket] = set()


def get_today_file():
    """Trả về đường dẫn file json của ngày hôm nay"""
    return os.path.join(DATA_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.json")


def save_message(message):
    """Lưu tin nhắn text vào file ngày hôm nay"""
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
    """Tải tin nhắn gần đây (trong X phút) của hôm nay"""
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


def cleanup_old_files(days=7):
    """Xóa file cũ hơn X ngày"""
    cutoff = datetime.now() - timedelta(days=days)
    for file in glob.glob(os.path.join(DATA_DIR, "*.json")):
        try:
            file_date = datetime.strptime(os.path.basename(file).replace(".json", ""), "%Y-%m-%d")
            if file_date < cutoff:
                os.remove(file)
                print(f"[CLEANUP] Deleted old file: {file}")
        except ValueError:
            pass


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

    # Gửi tin nhắn gần đây cho client mới
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

            # Tin nhắn ảnh thì không lưu
            if not message["image"]:
                save_message(message)
                cleanup_old_files(days=1)

            # Gửi tin nhắn cho tất cả client
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
