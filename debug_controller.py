#!/usr/bin/env python3
"""
后台调试控制器  ·  端口 8081
- 与大屏（3000端口）完全独立，不抢占 NPU/CPU
- 调试模式关闭时：零资源占用
- 调试模式开启时：按需拉流 + YOLO 推理
"""
import os, sys, cv2, numpy as np, threading, queue, time, socket, json, logging
from datetime import datetime
from typing import Optional
from urllib.parse import unquote, urlparse
from dotenv import load_dotenv

# Bug3修复：RTSP 超时防死锁（必须在任何 VideoCapture 打开之前设置）
# 2秒连接超时，拒绝让断线通道阻塞整个 FastAPI 事件循环
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;2000000"

# ── FastAPI ───────────────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("请先执行: pip3 install fastapi uvicorn --break-system-packages")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("debug_ctrl")

# ── 从 config.json 加载摄像头配置 ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "model", "yolo11n.rknn")
load_dotenv(os.path.join(BASE_DIR, "app", ".env"))


def _database_config() -> dict:
    """将后端DATABASE_URL转换为mysql-connector参数，避免脚本保存数据库密码。"""
    value = os.getenv("DATABASE_URL", "")
    parsed = urlparse(value)
    if parsed.scheme not in ("mysql", "mariadb") or not parsed.hostname:
        raise HTTPException(500, "DATABASE_URL未配置或格式不正确")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/"),
    }

def _build_cameras() -> list:
    """
    从 config.json 构建摄像头列表。
    camera_ip = 摄像头真实 IP（在线检测 :80 用）
    ip        = NVR IP（RTSP 推流地址用，不变）
    """
    cfg_file = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        with open(cfg_file, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as exc:
        log.warning(f"config.json 读取失败: {exc}，使用默认值")
        cfg = {}
    nvr      = cfg.get("nvr", {})
    nvr_ip   = nvr.get("ip",       "")
    nvr_port = nvr.get("port",     554)
    username = nvr.get("username", "admin")
    password = (nvr.get("passwords") or [""])[0]
    cameras  = []
    for ch in cfg.get("channels", []):
        ch_id     = ch["id"]
        area      = ch.get("area",      f"通道{ch_id:02d}")
        camera_ip = ch.get("camera_ip", nvr_ip)
        mode      = ch.get("mode",      "yolo")
        is_recam = mode in ("recamera_yolo", "recamera_yolo_vlm")
        cameras.append({
            "id":           ch_id,
            "channel":      ch_id,
            "name":         f"CH{ch_id:02d}",
            "area":         area,
            "camera_ip":    camera_ip,        # 物理摄像头 IP（用于显示和 RTSP 在线检测）
            "recamera_url": ch.get("recamera_url", ""),  # HTTP 源（recamera 模式用）
            "ip":           camera_ip,
            "port":         554,
            "user":         username,
            "password":     password,
            "sub_stream":   "102",
            "main_stream":  "101",
            "type":         "recamera" if is_recam else "hikvision",
            "mode":         mode,
        })
    return cameras

CAMERAS = _build_cameras()
N_CH    = len(CAMERAS)

# ── 全局状态 ──────────────────────────────────────────────────────────────────
debug_mode  = False          # 调试总开关
active_ch   = None           # 当前选中通道
readers: dict  = {}          # RTSPReader 实例缓存
infer_engine   = None        # YOLO 推理引擎（按需加载/销毁）
state_lock     = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════════
# reCamera HTTP Snapshot 读取器（第14路专用）
# ═══════════════════════════════════════════════════════════════════════════════
class ReCameraReader:
    """以固定频率轮询 reCamera /api/snapshot，存入帧队列"""
    def __init__(self, url: str, fps: float = 10):
        self.url   = url
        self.interval = 1.0 / fps
        self.queue = queue.Queue(maxsize=2)
        self._run  = False
        self._thr  = None
        self.ok    = False

    def start(self):
        self._run = True
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop(self):
        self._run = False

    def _loop(self):
        import urllib.request as ur
        while self._run:
            t0 = time.time()
            try:
                with ur.urlopen(self.url, timeout=3) as resp:
                    data = resp.read()
                arr  = np.frombuffer(data, np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    self.ok = True
                    if self.queue.full():
                        try: self.queue.get_nowait()
                        except queue.Empty: pass
                    try: self.queue.put_nowait(frame)
                    except queue.Full: pass
            except Exception:
                self.ok = False
            elapsed = time.time() - t0
            time.sleep(max(0, self.interval - elapsed))

    def get(self, timeout=0.5):
        try:    return self.queue.get(timeout=timeout)
        except queue.Empty: return None


# ═══════════════════════════════════════════════════════════════════════════════
# RTSP 读流器（单例 + 帧队列 + 跳帧保护）
# ═══════════════════════════════════════════════════════════════════════════════
class RTSPReader:
    def __init__(self, url: str, maxq: int = 2):
        self.url   = url
        self.queue = queue.Queue(maxsize=maxq)
        self._thr  = None
        self._run  = False
        self.ok    = False

    def start(self):
        self._run = True
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop(self):
        self._run = False

    def _open_cap(self) -> cv2.VideoCapture:
        """带超时参数打开 RTSP 流，防止断线时永久阻塞。"""
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # Bug3修复：设置连接与读取超时（毫秒），避免 cap.read() 死锁
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2000)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
        return cap

    def _loop(self):
        cap = self._open_cap()
        self.ok = cap.isOpened()
        while self._run:
            ret, frame = cap.read()
            if not ret:
                self.ok = False
                time.sleep(1.0)   # 断线后等 1s 再重试，避免 CPU 空转
                cap.release()
                cap = self._open_cap()
                self.ok = cap.isOpened()
                continue
            self.ok = True
            # 跳帧：队列满则丢弃旧帧，始终保持最新帧
            if self.queue.full():
                try: self.queue.get_nowait()
                except queue.Empty: pass
            try: self.queue.put_nowait(frame)
            except queue.Full: pass
        cap.release()

    def get(self, timeout=0.5) -> Optional[np.ndarray]:
        try:    return self.queue.get(timeout=timeout)
        except queue.Empty: return None


# ═══════════════════════════════════════════════════════════════════════════════
# YOLO 推理引擎（NPU，按需加载/卸载）
# ═══════════════════════════════════════════════════════════════════════════════
class YOLOEngine:
    IN_SZ = 640
    CONF  = 0.25
    IOU   = 0.45

    def __init__(self, model_path: str):
        from rknnlite.api import RKNNLite
        self.rknn = RKNNLite()
        if self.rknn.load_rknn(model_path) != 0:
            raise RuntimeError(f"加载模型失败: {model_path}")
        if self.rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_AUTO) != 0:
            raise RuntimeError("NPU 运行时初始化失败")
        self.lock = threading.Lock()
        log.info("✓ YOLO 引擎已加载 (NPU)")

    def release(self):
        try: self.rknn.release()
        except: pass
        log.info("✓ YOLO 引擎已释放 (NPU 资源归还)")

    def _preprocess(self, bgr: np.ndarray):
        img  = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = img.shape[:2]
        scale = self.IN_SZ / max(h, w)
        nh, nw = int(h * scale), int(w * scale)
        resized = cv2.resize(img, (nw, nh))
        pad_x = (self.IN_SZ - nw) // 2
        pad_y = (self.IN_SZ - nh) // 2
        canvas = np.zeros((self.IN_SZ, self.IN_SZ, 3), dtype=np.uint8)
        canvas[pad_y:pad_y+nh, pad_x:pad_x+nw] = resized
        return np.expand_dims(canvas, 0), scale, pad_x, pad_y

    def infer(self, bgr: np.ndarray) -> list:
        """返回 [{x1,y1,x2,y2,score,label}, ...] 原图坐标"""
        inp, scale, px, py = self._preprocess(bgr)
        with self.lock:
            outs = self.rknn.inference(inputs=[inp])
        # 解析 YOLOv11 输出（简化版，仅 person 类别 idx=0）
        boxes, scores = [], []
        for head in outs:
            head = head.reshape(-1, head.shape[-1])
            for row in head:
                obj_s  = row[4]
                cls_s  = row[5:]
                person = obj_s * cls_s[0]
                if person < self.CONF:
                    continue
                cx, cy, bw, bh = row[:4]
                x1 = int((cx - bw/2 - px) / scale)
                y1 = int((cy - bh/2 - py) / scale)
                x2 = int((cx + bw/2 - px) / scale)
                y2 = int((cy + bh/2 - py) / scale)
                boxes.append([x1, y1, x2, y2])
                scores.append(float(person))
        if not boxes:
            return []
        # 简单 NMS
        idxs = cv2.dnn.NMSBoxes(boxes, scores, self.CONF, self.IOU)
        result = []
        h, w = bgr.shape[:2]
        for i in (idxs.flatten() if len(idxs) else []):
            x1,y1,x2,y2 = boxes[i]
            result.append({"x1": max(0,x1), "y1": max(0,y1),
                           "x2": min(w,x2), "y2": min(h,y2),
                           "score": round(scores[i], 3), "label": "person"})
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════════
def rtsp_url(cam: dict, stream="sub") -> str:
    key  = "sub_stream" if stream == "sub" else "main_stream"
    code = cam[key]
    return f"rtsp://{cam['user']}:{cam['password']}@{cam['ip']}:{cam['port']}/Streaming/Channels/{code}"

def check_online(ip: str, port: int = 554, timeout: float = 1.5) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        r = s.connect_ex((ip, port))
        s.close()
        return r == 0
    except:
        return False

def encode_jpeg(frame: np.ndarray, quality: int = 70) -> bytes:
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes()

def mjpeg_frame(data: bytes) -> bytes:
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI 应用
# ═══════════════════════════════════════════════════════════════════════════════
app = FastAPI(title="AI 调试控制器", docs_url=None, redoc_url=None)

class CameraUpdate(BaseModel):
    ip:         Optional[str]  = None
    port:       Optional[int]  = None
    user:       Optional[str]  = None
    password:   Optional[str]  = None
    sub_stream: Optional[str]  = None   # 可编辑子码流路径（如 012 或完整路径）

class DebugToggle(BaseModel):
    enabled: bool

class StatsInput(BaseModel):
    total: int   # 目标总客流基数
    year:  int   # 目标本年客流基数
    month: int   # 目标本月客流基数
    week:  int   # 目标本周客流基数

# ── 调试模式开关 ──────────────────────────────────────────────────────────────
@app.post("/api/debug/toggle")
def toggle_debug(body: DebugToggle):
    global debug_mode, active_ch, readers, infer_engine
    with state_lock:
        debug_mode = body.enabled
        if not debug_mode:
            # 关闭：销毁所有流读取器 + 卸载 YOLO，彻底释放资源
            for r in readers.values():
                r.stop()
            readers.clear()
            active_ch = None
            if infer_engine:
                infer_engine.release()
                infer_engine = None
            log.info("调试模式已关闭 — 全量算力归还大屏")
        else:
            log.info("调试模式已开启")
    return {"debug": debug_mode}

@app.get("/api/debug/status")
def get_status():
    return {"debug": debug_mode, "active_ch": active_ch,
            "streams": list(readers.keys())}

# ── 摄像头管理 ────────────────────────────────────────────────────────────────
def _cam_online(cam: dict) -> bool:
    """
    reCamera: TCP 探测 :1880（轻量，不拉快照，避免并发超时）。
    海康 RTSP: TCP 探测 :554。
    """
    if cam.get("type") == "recamera":
        url = cam.get("recamera_url", "")
        if not url:
            return False
        from urllib.parse import urlparse
        p = urlparse(url)
        return check_online(p.hostname or "192.168.42.1", p.port or 1880)
    return check_online(cam["camera_ip"], 554)


@app.get("/api/cameras")
def list_cameras():
    result = []
    for cam in CAMERAS:
        online = _cam_online(cam)
        result.append({**cam, "online": online,
                        "rtsp_sub": rtsp_url(cam, "sub")})
    return result

@app.get("/api/cameras/{ch}/status")
def camera_status(ch: int):
    if not 1 <= ch <= N_CH:
        raise HTTPException(404, "通道不存在")
    cam    = CAMERAS[ch - 1]
    online = _cam_online(cam)
    return {"channel": ch, "online": online,
            "camera_ip": cam["camera_ip"]}

@app.patch("/api/cameras/{ch}")
def update_camera(ch: int, body: CameraUpdate):
    total = N_CH
    if not 1 <= ch <= total:
        raise HTTPException(404, "通道不存在")
    cam = CAMERAS[ch - 1]
    if body.ip:         cam["ip"]         = body.ip
    if body.port:       cam["port"]       = body.port
    if body.user:       cam["user"]       = body.user
    if body.password:   cam["password"]   = body.password
    if body.sub_stream: cam["sub_stream"] = body.sub_stream
    # 如果正在读这一路，重启读取器（让新子码流生效）
    if ch in readers:
        readers[ch].stop()
        del readers[ch]
    return {"ok": True, "camera": cam}

# ── 选择通道（启动对应流读取器）────────────────────────────────────────────────
@app.post("/api/channels/{ch}/select")
def select_channel(ch: int):
    global active_ch
    if not debug_mode:
        raise HTTPException(403, "请先开启调试模式")
    total = N_CH
    if not 1 <= ch <= total:
        raise HTTPException(404, "通道不存在")
    with state_lock:
        if active_ch and active_ch != ch and active_ch in readers:
            readers[active_ch].stop()
            del readers[active_ch]
        active_ch = ch
        if ch not in readers:
            cam = CAMERAS[ch - 1]
            if cam.get("type") == "recamera":
                snap_url = cam.get("recamera_url", "http://192.168.42.1:1880/api/snapshot")
                reader   = ReCameraReader(snap_url, fps=5)
            else:
                reader = RTSPReader(rtsp_url(cam, "sub"))
            reader.start()
            readers[ch] = reader
    return {"ok": True, "channel": ch}

# ── MJPEG 原始流 ──────────────────────────────────────────────────────────────
@app.get("/api/stream/{ch}/raw")
def stream_raw(ch: int):
    if not debug_mode:
        raise HTTPException(403, "调试模式已关闭")
    if ch not in readers:
        raise HTTPException(404, "请先选择该通道")

    # Bug1修复：channel=ch 显式捕获，防止多请求并发时 ch 被后期绑定到其他通道
    def gen(channel=ch):
        while debug_mode and channel in readers:
            frame = readers[channel].get()
            if frame is None:
                time.sleep(0.05)
                continue
            frame = cv2.resize(frame, (854, 480))
            yield mjpeg_frame(encode_jpeg(frame, quality=65))

    return StreamingResponse(gen(),
        media_type="multipart/x-mixed-replace; boundary=frame")

# ── MJPEG AI 推理流（Bug4修复：不再初始化 NPU，读 main.py 共享结果文件）────────
# RK3576 NPU 运行时为独占资源，main.py 已全权占用。
# debug_controller 通过读取 /tmp/yolo_results.json（main.py 每轮写入）
# 将区域人数叠加在实时视频帧上，完全消除 rknn.init_runtime() 冲突。
_RESULTS_FILE = "/tmp/yolo_results.json"

@app.get("/api/stream/{ch}/ai")
def stream_ai(ch: int):
    if not debug_mode:
        raise HTTPException(403, "调试模式已关闭")
    if ch not in readers:
        raise HTTPException(404, "请先选择该通道")

    INFER_API = "http://127.0.0.1:8082/infer"
    INFER_EVERY = 8   # 每 8 帧触发一次推理（相当于约 0.5~1s 刷新一次检测框）

    # Bug1修复：channel=ch 显式捕获，确保多并发请求通道不互串
    def gen(channel=ch):
        import urllib.request as ur
        frame_idx  = 0
        last_boxes = []
        last_count = -1
        last_ts    = ""
        last_infer_ms = 0

        while debug_mode and channel in readers:
            frame = readers[channel].get()
            if frame is None:
                time.sleep(0.05)
                continue

            frame = cv2.resize(frame, (854, 480))
            dw, dh = 854, 480
            frame_idx += 1

            # ── 每 INFER_EVERY 帧调用一次实时推理接口 ─────────────────────────
            if frame_idx % INFER_EVERY == 1:
                t_infer = time.perf_counter()
                try:
                    with ur.urlopen(f"{INFER_API}/{channel}", timeout=3) as r:
                        data = json.loads(r.read())
                    last_count = data.get("count", -1)
                    last_boxes = data.get("boxes", [])
                    last_ts    = data.get("ts", "")[:19]
                    last_infer_ms = int((time.perf_counter() - t_infer) * 1000)
                except Exception:
                    last_count = -1

            # ── 绘制检测框 ─────────────────────────────────────────────────────
            for b in last_boxes:
                if len(b) < 4:
                    continue
                x1 = int(b[0] * dw);  y1 = int(b[1] * dh)
                x2 = int(b[2] * dw);  y2 = int(b[3] * dh)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 80), 2)
                cv2.putText(frame, "person", (x1, max(y1 - 6, 0)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 80), 2)

            # ── 顶部信息条 ─────────────────────────────────────────────────────
            if last_count >= 0:
                clr   = (0, 255, 80)
                label = f"[YOLO] CH{channel:02d}: {last_count} person(s)  ({last_infer_ms}ms)"
            else:
                clr   = (80, 80, 200)
                label = f"[YOLO] CH{channel:02d}: connecting..."
            cv2.rectangle(frame, (0, 0), (520, 44), (0, 0, 0), -1)
            cv2.putText(frame, label, (8, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.85, clr, 2)
            if last_ts:
                cv2.putText(frame, f"Inferred: {last_ts}", (8, 472),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 160), 1)
            yield mjpeg_frame(encode_jpeg(frame, quality=65))

    return StreamingResponse(gen(),
        media_type="multipart/x-mixed-replace; boundary=frame")


# ── 推理结果 JSON（轻量接口，读共享文件，零 NPU 占用）──────────────────────────
@app.get("/api/stream/{ch}/boxes")
def get_boxes(ch: int):
    if not debug_mode or ch not in readers:
        return {"boxes": [], "count": 0}
    try:
        with open(_RESULTS_FILE) as f:
            data = json.load(f)
        count = data.get("channels", {}).get(str(ch), 0)
        return {"boxes": [], "count": max(0, count),
                "area": (CAMERAS[ch-1].get("area","?") if 1<=ch<=len(CAMERAS) else "?"),
                "ts":   data.get("ts", "")}
    except Exception as exc:
        return {"boxes": [], "count": 0, "error": str(exc)}


# ═══════════════════════════════════════════════════════════════════════════════
# 前端 HTML（内嵌，无需额外文件）
# ═══════════════════════════════════════════════════════════════════════════════
HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>AI 后台调试控制器</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body { background:#0a0e1a; color:#e0f0ff; font-family:'Menlo',monospace; }
  .led { width:10px;height:10px;border-radius:50%;display:inline-block; }
  .led-on  { background:#4CAF50; box-shadow:0 0 6px #4CAF50; }
  .led-off { background:#ff3366; box-shadow:0 0 6px #ff3366; }
  .led-unk { background:#888; }
  input,select { background:#0f1e38; border:1px solid #2a4a6a;
    color:#e0f0ff; padding:4px 8px; border-radius:3px; width:100%; }
  table { border-collapse:collapse; width:100%; }
  th,td { border:1px solid #1a3a5a; padding:6px 10px; font-size:12px; }
  th { background:#0f1e38; color:#8BC34A; text-transform:uppercase; }
  video,img { width:100%; background:#000; min-height:180px; }
  .panel { background:#0d1829; border:1px solid rgba(139,195,74,.2);
    border-radius:4px; padding:16px; }
  .toggle { position:relative; display:inline-block; width:56px; height:28px; }
  .toggle input { opacity:0; width:0; height:0; }
  .slider { position:absolute; cursor:pointer; inset:0;
    background:#1a3a5a; border-radius:28px; transition:.3s; }
  .slider:before { content:""; position:absolute; width:22px; height:22px;
    left:3px; top:3px; background:#fff; border-radius:50%; transition:.3s; }
  input:checked + .slider { background:#4CAF50; }
  input:checked + .slider:before { transform:translateX(28px); }
</style>
</head>
<body class="p-6">

<!-- Header -->
<div class="flex items-center justify-between mb-6">
  <div>
    <h1 class="text-2xl font-bold text-[#8BC34A]">AI 后台调试控制器</h1>
    <p class="text-xs text-gray-400 mt-1">端口 8081 · 与大屏完全隔离</p>
  </div>
  <!-- 总开关 -->
  <div class="panel flex items-center gap-4">
    <div id="mode-label" class="text-sm text-gray-400">调试模式：<span id="mode-text" class="text-[#ff3366] font-bold">已关闭</span></div>
    <label class="toggle">
      <input type="checkbox" id="debug-switch" onchange="toggleDebug(this.checked)">
      <span class="slider"></span>
    </label>
  </div>
</div>

<div id="main" class="space-y-6">

  <!-- 需求 1：数据清洗 -->
  <div class="panel">
    <h2 class="text-[#8BC34A] font-bold mb-3">📊 客流数据清洗</h2>
    <div class="flex gap-4 items-end">
      <div class="text-sm text-gray-400">
        清除今日所有测试数据并将历史总量恢复准确值
      </div>
      <button onclick="cleanData()"
        class="px-4 py-2 bg-[#ff336630] border border-[#ff3366] text-[#ff3366] text-sm hover:bg-[#ff336650] whitespace-nowrap">
        ⚠ 清除今日测试数据
      </button>
    </div>
    <div id="clean-result" class="mt-2 text-xs text-gray-400"></div>
  </div>

  <!-- 客流基数设定 -->
  <div class="panel">
    <h2 class="text-[#8BC34A] font-bold mb-1">📈 客流基数设定</h2>
    <p class="text-xs text-gray-400 mb-4">输入目标基数后写入数据库，大屏将以此为起点，后续 YOLO 检测到的人数自动在基数上累加<br>
      约束：总客流 ≥ 本年 ≥ 本月 ≥ 本周</p>
    <div class="grid grid-cols-2 gap-3 mb-4" style="max-width:520px">
      <div>
        <label class="text-xs text-gray-400 block mb-1">总客流基数</label>
        <input type="number" id="stat-total" placeholder="例：360000">
      </div>
      <div>
        <label class="text-xs text-gray-400 block mb-1">本年客流基数</label>
        <input type="number" id="stat-year"  placeholder="例：46000">
      </div>
      <div>
        <label class="text-xs text-gray-400 block mb-1">本月客流基数</label>
        <input type="number" id="stat-month" placeholder="例：8000">
      </div>
      <div>
        <label class="text-xs text-gray-400 block mb-1">本周客流基数</label>
        <input type="number" id="stat-week"  placeholder="例：400">
      </div>
    </div>
    <div class="flex items-center gap-4">
      <button onclick="setStats()"
        class="px-4 py-2 bg-[#4CAF5030] border border-[#4CAF50] text-[#4CAF50] text-sm hover:bg-[#4CAF5050] whitespace-nowrap">
        ✓ 写入数据库
      </button>
      <span id="stats-result" class="text-xs text-gray-400"></span>
    </div>
  </div>

  <!-- 摄像头管理 -->
  <div class="panel">
    <div class="flex justify-between items-center mb-3">
      <h2 class="text-[#8BC34A] font-bold">📷 摄像头通道管理</h2>
      <button onclick="loadCameras()" class="text-xs px-3 py-1 border border-[#8BC34A30] text-[#8BC34A] hover:bg-[#8BC34A20]">
        刷新状态
      </button>
    </div>
    <div class="overflow-x-auto">
    <table id="cam-table">
      <thead>
        <tr><th>状态</th><th>通道</th><th>区域名称</th><th>摄像头真实IP</th><th>NVR端口</th>
            <th>用户名</th><th>密码</th><th>子码流路径（可编辑）</th><th>操作</th></tr>
      </thead>
      <tbody id="cam-body">
        <tr><td colspan="9" class="text-center text-gray-500">加载中...</td></tr>
      </tbody>
    </table>
    </div>
  </div>

  <!-- 双画面调试 -->
  <div class="panel" id="debug-panel">
    <h2 class="text-[#8BC34A] font-bold mb-3">🎬 双画面实时对比</h2>
    <div class="flex items-center gap-4 mb-4">
      <label class="text-sm text-gray-400">选择通道：</label>
      <select id="ch-select" onchange="selectChannel(this.value)" class="w-40">
        <option value="">-- 请选择 --</option>
      </select>
      <span id="stream-status" class="text-xs text-gray-500"></span>
    </div>
    <div class="grid grid-cols-2 gap-4">
      <div>
        <div class="text-xs text-gray-400 mb-1">
          <span class="text-white">画面 A</span> · 原始流（无 AI）
        </div>
        <img id="raw-img" src="" alt="等待选择通道..." class="rounded">
      </div>
      <div>
        <div class="text-xs text-gray-400 mb-1">
          <span class="text-[#4CAF50]">画面 B</span> · YOLO AI 推理流
        </div>
        <img id="ai-img" src="" alt="等待选择通道..." class="rounded">
      </div>
    </div>
    <div id="debug-off-msg" class="text-center text-gray-500 text-sm py-8">
      请先开启调试模式后选择通道
    </div>
  </div>

</div>

<script>
let debugOn = false;
let currentCh = null;

async function toggleDebug(on) {
  const r = await fetch('/api/debug/toggle', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({enabled: on})
  });
  const d = await r.json();
  debugOn = d.debug;
  document.getElementById('mode-text').textContent = debugOn ? '已开启' : '已关闭';
  document.getElementById('mode-text').className = debugOn ? 'text-[#4CAF50] font-bold' : 'text-[#ff3366] font-bold';
  document.getElementById('debug-off-msg').style.display = debugOn ? 'none' : 'block';
  if (!debugOn) {
    document.getElementById('raw-img').src = '';
    document.getElementById('ai-img').src = '';
    document.getElementById('stream-status').textContent = '';
    currentCh = null;
  }
}

async function loadCameras() {
  const r = await fetch('/api/cameras');
  const cams = await r.json();
  const tbody = document.getElementById('cam-body');
  const sel = document.getElementById('ch-select');
  // 清空下拉菜单（保留第一个占位）
  while (sel.options.length > 1) sel.remove(1);

  tbody.innerHTML = cams.map(cam => `
    <tr id="row-${cam.id}">
      <td class="text-center">
        <span class="led ${cam.online ? 'led-on' : 'led-off'}"
              title="${cam.type==='recamera'
                ? (cam.online ? '✓ Online  HTTP:1880  ' + cam.camera_ip : '✗ Offline  HTTP:1880  ' + cam.camera_ip)
                : (cam.online ? '✓ Online  TCP:554  ' + cam.camera_ip  : '✗ Offline  TCP:554  '  + cam.camera_ip)}"></span>
      </td>
      <td class="text-center font-mono">${String(cam.channel).padStart(2,'0')}</td>
      <td class="text-[#8BC34A]">${cam.area || cam.name}</td>
      <td class="font-mono text-[11px] text-cyan-300">${cam.camera_ip}</td>
      <td><input id="port-${cam.id}" value="${cam.port}" style="width:60px"></td>
      <td><input id="user-${cam.id}" value="${cam.user}" style="width:70px"></td>
      <td><input id="pwd-${cam.id}" value="${cam.password}" style="width:100px"></td>
      <td><input id="sub-${cam.id}" value="${cam.sub_stream}" style="width:70px"
           title="子码流路径，如 012 表示 /Streaming/Channels/012"></td>
      <td>
        <button onclick="saveCamera(${cam.id})"
          class="px-2 py-1 text-[11px] border border-[#8BC34A50] text-[#8BC34A] hover:bg-[#8BC34A20]">
          保存
        </button>
      </td>
    </tr>
  `).join('');

  cams.forEach(cam => {
    const opt = document.createElement('option');
    opt.value = cam.id;
    opt.textContent = `通道${String(cam.channel).padStart(2,'0')}·${cam.area||''} ${cam.online ? '✓在线' : '✗离线'}`;
    sel.appendChild(opt);
  });
}

async function saveCamera(id) {
  const body = {
    port:       parseInt(document.getElementById(`port-${id}`).value),
    user:       document.getElementById(`user-${id}`).value,
    password:   document.getElementById(`pwd-${id}`).value,
    sub_stream: document.getElementById(`sub-${id}`).value,
  };
  const r = await fetch(`/api/cameras/${id}`, {
    method:'PATCH', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)
  });
  const d = await r.json();
  if (d.ok) alert(`通道 ${id} 配置已更新`);
}

async function selectChannel(ch) {
  if (!ch || !debugOn) {
    alert('请先开启调试模式');
    document.getElementById('ch-select').value = '';
    return;
  }
  const r = await fetch(`/api/channels/${ch}/select`, {method:'POST'});
  if (!r.ok) { alert('选择通道失败'); return; }
  currentCh = ch;
  document.getElementById('stream-status').textContent = `通道 ${ch} 流媒体启动中...`;
  // 设置 MJPEG 图片源（浏览器自动处理多帧刷新）
  document.getElementById('raw-img').src = `/api/stream/${ch}/raw`;
  document.getElementById('ai-img').src  = `/api/stream/${ch}/ai`;
  document.getElementById('stream-status').textContent = `通道 ${ch} 直播中`;
}

async function cleanData() {
  if (!confirm('确认删除今日全部测试数据？此操作不可撤销。')) return;
  try {
    const r = await fetch('/api/data/clean-today', {method:'POST'});
    const d = await r.json();
    document.getElementById('clean-result').textContent =
      `✓ 已删除 ${d.deleted_flow} 条客流记录 | ${d.deleted_events} 条事件 | ${d.deleted_vlm} 条VLM日志`;
    document.getElementById('clean-result').className = 'mt-2 text-xs text-[#4CAF50]';
  } catch(e) {
    document.getElementById('clean-result').textContent = '清洗失败：' + e;
    document.getElementById('clean-result').className = 'mt-2 text-xs text-[#ff3366]';
  }
}

async function setStats() {
  const total = parseInt(document.getElementById('stat-total').value);
  const year  = parseInt(document.getElementById('stat-year').value);
  const month = parseInt(document.getElementById('stat-month').value);
  const week  = parseInt(document.getElementById('stat-week').value);
  const el    = document.getElementById('stats-result');
  if ([total, year, month, week].some(isNaN)) {
    el.textContent = '请填写全部四项数字'; el.className = 'text-xs text-[#ff3366]'; return;
  }
  try {
    const r = await fetch('/api/data/set-stats', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({total, year, month, week})
    });
    const d = await r.json();
    if (r.ok) {
      el.textContent = `✓ 写入成功，共插入 ${d.inserted} 条记录，大屏约 30 秒后刷新`;
      el.className = 'text-xs text-[#4CAF50]';
    } else {
      el.textContent = '错误：' + (d.detail || JSON.stringify(d));
      el.className = 'text-xs text-[#ff3366]';
    }
  } catch(e) {
    el.textContent = '请求失败：' + e; el.className = 'text-xs text-[#ff3366]';
  }
}

// 页面加载
loadCameras();
setInterval(loadCameras, 30000);  // 每30秒刷新状态灯
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
def index():
    return HTML

# ── 数据清洗 API ──────────────────────────────────────────────────────────────
@app.post("/api/data/clean-today")
def clean_today_data():
    try:
        import mysql.connector
    except ImportError:
        raise HTTPException(500, "mysql-connector 未安装")
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    conn = mysql.connector.connect(**_database_config())
    cur = conn.cursor()
    cur.execute("DELETE FROM person_flow_records WHERE DATE(timestamp) = %s", (today,))
    df = cur.rowcount
    cur.execute("DELETE FROM event_logs WHERE DATE(timestamp) = %s", (today,))
    de = cur.rowcount
    cur.execute("DELETE FROM vlm_logs WHERE DATE(timestamp) = %s", (today,))
    dv = cur.rowcount
    cur.execute("DELETE FROM daily_stats WHERE date = %s", (today,))
    cur.execute("UPDATE rooms SET current_count = 0")
    conn.commit(); cur.close(); conn.close()
    log.info(f"数据清洗完成: 删除 {df} 条客流记录")
    return {"ok": True, "deleted_flow": df, "deleted_events": de, "deleted_vlm": dv}


@app.post("/api/data/set-stats")
def set_stats(body: StatsInput):
    """
    设定客流基数。输入值直接写入数据库，后续 YOLO 检测数据在此基础上累加。
    按时间段拆分写入 person_flow_records，保证总/年/月/周四项查询各自正确。
    """
    try:
        import mysql.connector
    except ImportError:
        raise HTTPException(500, "mysql-connector 未安装")
    from datetime import date, datetime, timedelta

    t = body.total
    y = body.year
    m = body.month
    w = body.week

    # ── 参数校验 ─────────────────────────────────────────────────────────────
    errs = []
    if t < y: errs.append("总客流 ≥ 本年")
    if y < m: errs.append("本年 ≥ 本月")
    if errs: raise HTTPException(400, " | ".join(errs))

    # ── 计算时间边界 ──────────────────────────────────────────────────────────
    today       = date.today()
    month_start = date(today.year, today.month, 1)
    days_to_sun = (today.weekday() + 1) % 7       # 到上个周日的天数
    week_start  = today - timedelta(days=days_to_sun)

    # ── 按时段拆分，确保四项查询各自命中正确的记录 ─────────────────────────
    rows = []   # (count, datetime)

    if week_start < month_start:
        # 周跨越月边界（如6月1日周一，周从5月31日算起）
        # week_db >= month_db，否则无法区分
        if w < m: raise HTTPException(400,
            f"当前周({week_start})早于本月({month_start})，本周显示值需 ≥ 本月显示值 − {OFFSET['month']}")
        hist    = t - y           # 今年以前
        yr_only = y - w           # 今年但在周之前（1月-周前一天）
        wk_only = w - m           # 在周内但在本月前（周日当天）
        both    = m               # 本月内（同时在周内）
        if hist    > 0: rows.append((hist,    datetime(today.year - 1, 12, 31, 23, 0)))
        if yr_only > 0: rows.append((yr_only, datetime(today.year, 3, 15, 12, 0)))
        if wk_only > 0: rows.append((wk_only, datetime(week_start.year,  week_start.month,  week_start.day,  9, 0)))
        if both    > 0: rows.append((both,    datetime(today.year,       today.month,        today.day,       10, 0)))
    else:
        # 正常情况：周在本月内（月 ≥ 周）
        if m < w: raise HTTPException(400, "本月客流 ≥ 本周客流")
        hist     = t - y
        yr_only  = y - m
        mon_only = m - w
        wk_val   = w
        if hist     > 0: rows.append((hist,     datetime(today.year - 1, 12, 31, 23, 0)))
        if yr_only  > 0: rows.append((yr_only,  datetime(today.year, 3, 15, 12, 0)))
        if mon_only > 0:
            # 本月内、周之前某天
            pre_week_day = max(1, week_start.day - 1)
            rows.append((mon_only, datetime(today.year, today.month, pre_week_day, 10, 0)))
        if wk_val   > 0: rows.append((wk_val,   datetime(week_start.year, week_start.month, week_start.day, 9, 0)))

    # ── 写入数据库 ────────────────────────────────────────────────────────────
    conn = mysql.connector.connect(**_database_config())
    cur = conn.cursor()
    cur.execute("DELETE FROM person_flow_records WHERE room_name = '全区域'")
    for count, ts in rows:
        cur.execute(
            "INSERT INTO person_flow_records (count, event, timestamp, room_name, confidence)"
            " VALUES (%s, %s, %s, %s, %s)",
            (count, "person_count_changed", ts, "全区域", 0.9)
        )
    conn.commit()
    cur.close()
    conn.close()
    log.info(f"客流基数已设定: 总={body.total} 年={body.year} 月={body.month} 周={body.week}，插入 {len(rows)} 条")
    return {"ok": True, "inserted": len(rows)}


if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("DEBUG_HOST", "127.0.0.1"), port=8081,
                log_level="info", workers=1)
