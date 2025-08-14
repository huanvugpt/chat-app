from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import json
import os
import glob
import uuid
from typing import Set, Dict

app = FastAPI()
templates = Jinja2Templates(directory="backend/templates")

# ===== Config =====
TOKEN = "chucmungsinhnhat"
DATA_DIR = "backend/data"
os.makedirs(DATA_DIR, exist_ok=True)

clients: Set[WebSocket] = set()

# Lưu trạng thái like trong RAM: msg_id -> set(usernames)
like_state: Dict[str, set] = {}


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
    """Tải tin nhắn gần đây (hôm nay) trong X phút; nếu thiếu id/likes thì bổ sung để client xử lý like."""
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
            # đảm bảo có id + likes
            if "id" not in msg:
                msg["id"] = uuid.uuid4().hex
            if "likes" not in msg or not isinstance(msg["likes"], list):
                msg["likes"] = []
            # init trạng thái like trong RAM nếu chưa có
            like_state.setdefault(msg["id"], set(msg["likes"]))
            res.append(msg)
    return res


def cleanup_old_files(days=1):
    """Xóa file cũ hơn X ngày (days=1 => chỉ giữ hôm nay)."""
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

    # Gửi lịch sử gần đây cho client mới
    for msg in load_recent_messages():
        try:
            await websocket.send_json(msg)
        except Exception:
            pass

    try:
        while True:
            data = await websocket.receive_json()

            # ===== Sự kiện LIKE (toggle) =====
            if data.get("type") == "like":
                msg_id = data.get("msg_id")
                user = data.get("user", "unknown")
                if not msg_id:
                    continue
                bucket = like_state.setdefault(msg_id, set())
                if user in bucket:
                    bucket.remove(user)
                else:
                    bucket.add(user)

                payload = {
                    "type": "like",
                    "msg_id": msg_id,
                    "likes": sorted(list(bucket))
                }
                # broadcast cập nhật like
                dead = []
                for client in clients:
                    try:
                        await client.send_json(payload)
                    except Exception:
                        dead.append(client)
                for d in dead:
                    clients.discard(d)
                continue

            # ===== Tin nhắn thường (text / image) =====
            message = {
                "id": uuid.uuid4().hex,
                "time": datetime.now().strftime("%H:%M:%S"),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user": data.get("user", "unknown"),
                "text": data.get("text", ""),
                "image": data.get("image"),  # base64 data URL hoặc None
                "likes": []
            }

            # init like bucket
            like_state[message["id"]] = set()

            # Text: lưu file; Ảnh: không lưu
            if not message["image"]:
                save_message(message)
                cleanup_old_files(days=1)

            # broadcast tới tất cả client
            dead = []
            for client in clients:
                try:
                    await client.send_json(message)
                except Exception:
                    dead.append(client)
            for d in dead:
                clients.discard(d)

    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(websocket)
