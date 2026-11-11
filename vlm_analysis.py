"""
VLM 场景分析模块 · reCamera HTTP 版
- 视频帧来源：reCamera HTTP Snapshot API（192.168.42.1:1880/api/snapshot）
- 不再依赖 NVR RTSP，彻底消除 FFMPEG 死锁风险
- 调用本机 Docker 容器的 OpenAI 兼容接口（localhost:8002）
"""
import base64, json, os, threading
import cv2
import numpy as np
from urllib.request import urlopen, Request
from urllib.error import URLError

# ── reCamera 配置 ──────────────────────────────────────────────────────────────
RECAMERA_SNAPSHOT = "http://192.168.42.1:1880/api/snapshot"
SNAPSHOT_TIMEOUT  = 3   # HTTP 请求超时（秒）

# ── VLM API 配置 ───────────────────────────────────────────────────────────────
API_URL    = "http://localhost:8002/v1/chat/completions"
MODEL      = "rkllm-vision"
TIMEOUT    = 60
MAX_TOKENS = 150

# ── 并发保护 ───────────────────────────────────────────────────────────────────
_api_lock = threading.Lock()   # 本地VLM服务使用单请求串行推理
_LOCAL_SNAPSHOT = os.path.join(os.path.dirname(__file__), "app", "dist", "public", "snapshot", "latest.jpg")
_PHOTO_SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "photo", "channel_11")


def configure(nvr_cfg: dict):
    """兼容 main.py 热重载调用，VLM 已不使用 NVR，此函数保留为空操作。"""
    pass


def _decode_image(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return frame if frame is not None else None


def _read_frame_file(path: str) -> np.ndarray | None:
    try:
        with open(path, "rb") as f:
            return _decode_image(f.read())
    except Exception:
        return None


def _read_latest_photo_frame() -> np.ndarray | None:
    try:
        files = [
            os.path.join(_PHOTO_SNAPSHOT_DIR, name)
            for name in os.listdir(_PHOTO_SNAPSHOT_DIR)
            if name.lower().endswith((".jpg", ".jpeg", ".png"))
        ]
        if not files:
            return None
        return _read_frame_file(max(files, key=os.path.getmtime))
    except Exception:
        return None


# ── 帧获取（HTTP 快照，无 RTSP / 无 FFMPEG 死锁） ─────────────────────────────
def capture_frame() -> np.ndarray | None:
    """从 reCamera HTTP 接口获取最新快照帧。"""
    try:
        with urlopen(RECAMERA_SNAPSHOT, timeout=SNAPSHOT_TIMEOUT) as resp:
            data = resp.read()
        frame = _decode_image(data)
        if frame is not None:
            return frame
    except Exception:
        pass
    frame = _read_frame_file(_LOCAL_SNAPSHOT)
    if frame is not None:
        return frame
    return _read_latest_photo_frame()


def is_ready() -> bool:
    """探活：同时检查 VLM API 和 reCamera 是否可访问。"""
    try:
        urlopen("http://localhost:8002/v1/models", timeout=2)
        return True
    except Exception:
        return False


# ── VLM 推理 ──────────────────────────────────────────────────────────────────
def _frame_to_b64(frame_bgr: np.ndarray, quality: int = 85) -> str:
    _, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf).decode()


def analyze(person_count: int, frame_bgr: np.ndarray | None = None) -> str:
    """
    对 reCamera 当前快照执行本地VLM场景分析，返回中文场景描述。
    frame_bgr 可由调用方传入（测试用），为 None 时自动从 reCamera 拉取。
    """
    if frame_bgr is None:
        frame_bgr = capture_frame()
    if frame_bgr is None:
        return ""

    b64    = _frame_to_b64(frame_bgr)
    prompt = (f"这是室内公共区域的实时监控，当前有 {person_count} 位访客。"
              "请用1-2句生动温暖的话（50字以内）描述此刻的场景，如画面中有多桌顾客请分别描述各桌的状态。"
              "示例风格——"
              "一桌顾客专注敲键盘办公，另一桌围坐低声交流，咖啡厅静中有动，氛围惬意；"
              "角落里有人悠然翻书，中间几位正热烈讨论，整个空间洋溢着温暖而充实的气息。"
              "要求：语气积极正向，贴合画面，不描述性别，语言自然流畅。")
    payload = json.dumps({
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ]
        }],
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }).encode()

    req = Request(API_URL, data=payload,
                  headers={"Content-Type": "application/json"})
    try:
        with _api_lock:
            resp = json.loads(urlopen(req, timeout=TIMEOUT).read())
        return resp["choices"][0]["message"]["content"].strip()
    except (URLError, KeyError, json.JSONDecodeError):
        return ""
