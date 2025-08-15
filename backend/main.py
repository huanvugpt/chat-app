from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import json
import os
import glob
import uuid
from typing import Set, Dict, Optional

app = FastAPI()
templates = Jinja2Templates(directory="backend/templates")

# ===== Paths =====
DATA_DIR = "backend/data"
USERS_DIR = "users"
ACCOUNTS_FILE = os.path.join(USERS_DIR, "accounts.json")
TOKENS_FILE = os.path.join(USERS_DIR, "token.json")  # yêu cầu đặt tên token.json

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(USERS_DIR, exist_ok=True)

# ===== In-memory =====
clients: Set[WebSocket] = set()
like_state: Dict[str, set] = {}  # msg_id -> set(usernames)


# ---------- Accounts / Tokens helpers ----------
def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_accounts_file():
    """Tạo accounts.json mặc định nếu chưa có."""
    if not os.path.exists(ACCOUNTS_FILE):
        # đơn giản: map username -> password (plain). Có thể thay bằng hash sau.
        _write_json(ACCOUNTS_FILE, {"admin": "admin123"})


def load_accounts() -> Dict[str, str]:
    ensure_accounts_file()
    data = _read_json(ACCOUNTS_FILE, {})
    # Chuẩn hóa chỉ lấy mapping str->str
    safe = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str):
            safe[k.strip()] = v
    return safe


def check_credentials(username: str, password: str) -> bool:
    accounts = load_accounts()
    pw = accounts.get(username.strip())
    return pw is not None and pw == password


def load_tokens() -> Dict[str, dict]:
    return _read_json(TOKENS_FILE, {})


def save_tokens(tokens: Dict[str, dict]):
    _write_json(TOKENS_FILE, tokens)


def issue_token(username: str) -> dict:
    tokens = load_tokens()
    token = uuid.uuid4().hex
    expires = datetime.utcnow() + timedelta(hours=24)
    tokens[token] = {
        "username": username,
        "expires": expires.isoformat() + "Z"
    }
    save_tokens(tokens)
    return {"token": token, "expires": int(expires.timestamp() * 1000)}


def verify_token(token: str) -> Optional[dict]:
    if not token:
        return None
    tokens = load_tokens()
    info = tokens.get(token)
    if not info:
        return None
    # kiểm tra hạn
    try:
        exp = datetime.fromisoformat(info["expires"].replace("Z", ""))
    except Exception:
        return None
    if datetime.utcnow() > exp:
        # hết hạn -> xóa
        tokens.pop(token, None)
        save_tokens(tokens)
        return None
    return info  # {"username": "...", "expires": "...Z"}


# ---------- Chat storage ----------
def get_today_file():
    return os.path.join(DATA_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.json")


def save_message(message: dict):
    """Chỉ lưu tin nhắn text (image không lưu)."""
    file_path = get_today_file()
    if not os.path.exists(file_path):
        _write_json(file_path, [])
    data = _read_json(file_path, [])
    if not isinstance(data, list):
        data = []
    data.append(message)
    _write_json(file_path, data)


def load_recent_messages(minutes=15):
    """Tải tin nhắn gần đây hôm nay, đảm bảo đủ id/likes/realUser."""
    file_path = get_today_file()
    if not os.path.exists(file_path):
        return []
    data = _read_json(file_path, [])
    cutoff = datetime.now() - timedelta(minutes=minutes)
    res = []
    for msg in data:
        ts = msg.get("timestamp")
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        if dt <= cutoff:
            continue

        # Bổ sung trường còn thiếu
        if "id" not in msg:
            msg["id"] = uuid.uuid4().hex
        if "likes" not in msg or not isinstance(msg["likes"], list):
            msg["likes"] = []
        if "realUser" not in msg:
            # fallback: nếu file cũ chưa có realUser, lấy theo user nếu trùng username sẽ vẫn ok ở đa số case
            msg["realUser"] = msg.get("realUser") or msg.get("user") or "unknown"

        # init like_state
        like_state.setdefault(msg["id"], set(msg["likes"]))
        res.append(msg)
    return res


def cleanup_old_files(days=1):
    cutoff = datetime.now() - timedelta(days=days)
    for file in glob.glob(os.path.join(DATA_DIR, "*.json")):
        try:
            file_date = datetime.strptime(os.path.basename(file).replace(".json", ""), "%Y-%m-%d")
            if file_date < cutoff:
                os.remove(file)
                print(f"[CLEANUP] Deleted old file: {file}")
        except ValueError:
            pass


# ---------- HTTP endpoints ----------
@app.get("/", response_class=HTMLResponse)
async def get_chat_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/login")
async def login(payload: dict):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        return {"ok": False, "error": "Thiếu username hoặc password"}

    if check_credentials(username, password):
        t = issue_token(username)
        return {
            "ok": True,
            "user": username,
            "token": t["token"],
            "expires": t["expires"]
        }
    return {"ok": False, "error": "Sai username hoặc password"}


@app.post("/check-token")
async def check_token(payload: dict):
    token = (payload.get("token") or "").strip()
    info = verify_token(token)
    if not info:
        return {"ok": False}
    # có thể refresh nhẹ (tùy), ở đây giữ nguyên hạn
    expires_dt = datetime.fromisoformat(info["expires"].replace("Z", ""))
    return {
        "ok": True,
        "user": info["username"],
        "expires": int(expires_dt.timestamp() * 1000)
    }


# ---------- WebSocket ----------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token", "")
    info = verify_token(token)
    if not info:
        await websocket.close(code=4401)
        return

    real_username = info["username"]  # danh tính thật từ token

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

            # ===== Like toggle =====
            if data.get("type") == "like":
                msg_id = data.get("msg_id")
                if not msg_id:
                    continue
                bucket = like_state.setdefault(msg_id, set())
                # dùng real_username từ token để chống giả mạo
                if real_username in bucket:
                    bucket.remove(real_username)
                else:
                    bucket.add(real_username)

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

            # ===== Tin nhắn thường =====
            now = datetime.now()
            message = {
                "id": uuid.uuid4().hex,
                "time": now.strftime("%H:%M:%S"),
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                # user: tên hiển thị client gửi lên (có thể rỗng)
                "user": (data.get("user") or real_username).strip(),
                # realUser: username thật để căn trái/phải chuẩn
                "realUser": real_username,
                "text": data.get("text", "") or "",
                "image": data.get("image"),  # base64 data URL hoặc None
                "likes": []
            }

            # init like bucket
            like_state[message["id"]] = set()

            # Chỉ lưu text
            if not message["image"]:
                save_message(message)
                cleanup_old_files(days=1)

            # broadcast
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
