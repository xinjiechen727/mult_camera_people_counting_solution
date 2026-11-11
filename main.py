#!/usr/bin/env python3
"""
多路摄像头 · YOLOv11n行人检测 + 本地VLM场景分析  RK3576 NPU 生产模式
视频源：通道01-13 → YOLO实时统计（子码流 {ch:02d}2）
VLM源：通道14 → vlm_analysis.py 独立读取
配置：config.json 热加载，无需重启即可更新通道映射和NVR参数
"""
import os, cv2, numpy as np, threading, time, urllib.request, json
import http.server, socketserver, socket, base64
from datetime import datetime, timedelta
import vlm_analysis as vlm

# 防死锁：RTSP连接超时3秒
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;3000000"

# ── 路径 ──────────────────────────────────────────────────────────────────────
BASE        = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config.json")
MODEL       = os.path.join(BASE, "model", "yolo11n.rknn")
PHOTO_DIR              = os.path.join(BASE, "photo")
PHOTO_MAX_PER_CHANNEL  = 50   # 每路保留最新N张快照，防止磁盘满溢

# ── YOLO推理固定参数 ───────────────────────────────────────────────────────────
IN_SZ      = 640
CONF       = 0.25    # 正常场景置信度阈值
CONF_DARK  = 0.10    # 暗场景/深色衣物/坐姿背对镜头 — 宽松阈值提升召回
               # 0.10 可检出"黑衣坐姿后背朝镜头"等低置信目标
IOU        = 0.45
DARK_THR   = 120.0   # 均值亮度低于此值判定为暗场景（0-255）

# ── 全局配置状态（热加载安全） ────────────────────────────────────────────────
_cfg       = {}
_cfg_mtime = 0.0
_cfg_lock  = threading.Lock()
_photo_save_count: dict = {}  # 各通道照片保存计数（触发周期性清理）

# ── 热重载触发标志 ─────────────────────────────────────────────────────────────
_rebuild_needed = False
_rebuild_flag_lock = threading.Lock()
_last_vlm_emit_at = 0.0

def _load_config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)

def _apply_config(raw: dict):
    global _cfg, _cfg_mtime
    with _cfg_lock:
        _cfg = raw
        try:
            _cfg_mtime = os.path.getmtime(CONFIG_FILE)
        except OSError:
            pass
    vlm.configure(raw.get("nvr", {}))

def cfg() -> dict:
    with _cfg_lock:
        return dict(_cfg)

def yolo_channels() -> list:
    """返回所有做 YOLO 推理的通道（含 reCamera 和 VLM+YOLO 组合通道）。"""
    return [ch for ch in cfg().get("channels", [])
            if ch.get("mode") in ("yolo", "recamera_yolo", "recamera_yolo_vlm")]

def vlm_channel() -> dict | None:
    """返回做 VLM 分析的通道（含组合模式 recamera_yolo_vlm）。"""
    for ch in cfg().get("channels", []):
        if ch.get("mode") in ("vlm", "recamera_yolo_vlm"):
            return ch
    return None

# ── NPU（单实例 + 锁） ────────────────────────────────────────────────────────
rknn      = None
rknn_lock = threading.Lock()

# ── 每路 VideoCapture（键 = channel_id） ──────────────────────────────────────
caps      = {}
cap_locks = {}
print_lock = threading.Lock()

# ── 断线重连状态（防止重连阻塞导致线程/锁无限堆积） ──────────────────────────
_ch_reconnecting:   dict = {}   # ch_id -> bool，是否已有后台重连线程在跑
_ch_cooldown_until:  dict = {}  # ch_id -> 下次允许重连的时间戳
_reconnect_state_lock = threading.Lock()
_RECONNECT_COOLDOWN = 15.0   # 秒，避免对死摄像头反复发起重连

# ── reCamera 并发保护（同一设备不支持并发快照请求） ──────────────────────────
_recamera_host_locks: dict       = {}
_recamera_host_locks_lock        = threading.Lock()

def _recamera_lock(url: str) -> threading.Lock:
    host = url.split("/")[2]   # 取 host:port 部分作为锁 key
    with _recamera_host_locks_lock:
        if host not in _recamera_host_locks:
            _recamera_host_locks[host] = threading.Lock()
        return _recamera_host_locks[host]

# ── reCamera 快速推理循环共享结果 ─────────────────────────────────────────────
_recam_area_counts: dict = {}
_recam_lock              = threading.Lock()

# ── reCamera ID 追踪（防止同一人多次计数） ─────────────────────────────────────
_seen_recam_ids: set = set()
_seen_ids_date:  str = ''
_seen_ids_max:   int = 0          # 今日最大追踪 ID，用于检测设备重置
_SEEN_IDS_FILE       = "/tmp/yolo_seen_ids.json"  # 跨重启持久化

# ── 大屏 API ──────────────────────────────────────────────────────────────────
def _post(url: str, data: bytes):
    try:
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass

def _fetch_recamera_ids() -> dict | None:
    """从 reCamera /api/ids 获取当前追踪 ID 列表，返回 {count, ids, timestamp} 或 None。"""
    url = cfg().get("recamera_ids_url", "http://192.168.42.1:1880/api/ids")
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None

def _load_seen_ids():
    """从磁盘恢复今日 ID 追踪状态，防止 yolo-detector 重启后重复计数。"""
    global _seen_recam_ids, _seen_ids_date, _seen_ids_max
    try:
        with open(_SEEN_IDS_FILE) as f:
            data = json.load(f)
        if data.get("date") == datetime.now().strftime('%Y-%m-%d'):
            _seen_recam_ids = set(data.get("ids", []))
            _seen_ids_date  = data["date"]
            _seen_ids_max   = int(data.get("max_id", 0))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

_HEARTBEAT_DIR = "/tmp"

def _write_heartbeat(name: str):
    """供外部看门狗监控的心跳文件。每次主循环/reCamera循环跑完一轮就刷新一次时间戳。
    看门狗通过文件 mtime 判断对应循环是否卡死，与心跳文件内容无关，写入失败也不影响主流程。"""
    try:
        path = os.path.join(_HEARTBEAT_DIR, f"yolo_heartbeat_{name}")
        tmp  = f"{path}.tmp"
        with open(tmp, "w") as f:
            f.write(str(time.time()))
        os.replace(tmp, path)
    except Exception:
        pass


def _save_seen_ids():
    """原子写入今日 ID 追踪状态到磁盘。"""
    try:
        data = {"date": _seen_ids_date, "ids": list(_seen_recam_ids),
                "max_id": _seen_ids_max}
        tmp = _SEEN_IDS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, _SEEN_IDS_FILE)
    except Exception:
        pass

def _ws_reset_recamera_ids() -> bool:
    """
    对 reCamera 执行 WebSocket 断开重连，触发设备将追踪 ID 从 0 重新计数。
    研发确认：建立新 WebSocket 连接后 reCamera 会重置内部追踪 ID 计数器。
    """
    url = cfg().get("recamera_ids_url", "http://192.168.42.1:1880/api/ids")
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        host = p.hostname or "192.168.42.1"
        port = p.port or 1880
    except Exception:
        host, port = "192.168.42.1", 1880
    ws_path = "/ws/ids"
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((host, port))
        req = (f"GET {ws_path} HTTP/1.1\r\n"
               f"Host: {host}:{port}\r\n"
               "Upgrade: websocket\r\n"
               "Connection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n")
        s.sendall(req.encode())
        resp = b""
        s.settimeout(3)
        while b"\r\n\r\n" not in resp:
            chunk = s.recv(256)
            if not chunk:
                break
            resp += chunk
        ok = b"101" in resp
        # 发送 WebSocket close frame（opcode=0x8，masked）
        try:
            s.sendall(bytes([0x88, 0x80]) + os.urandom(4))
        except Exception:
            pass
        s.close()
        return ok
    except Exception:
        return False


def _recamera_id_reset_loop():
    """
    每日零点通过 WebSocket 断开重连重置 reCamera 追踪 ID 计数器，
    防止 ID 无限增长。同时清空本地 seen-ID 集合与持久化文件。
    """
    global _seen_recam_ids, _seen_ids_date, _seen_ids_max
    while True:
        now = datetime.now()
        # 等待到次日 00:00:05（留5秒余量，避免与 recamera_fast_loop 零点切换竞争）
        next_reset = now.replace(hour=0, minute=0, second=5, microsecond=0)
        if next_reset <= now:
            next_reset = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=5, microsecond=0)
        time.sleep((next_reset - datetime.now()).total_seconds())

        ok = _ws_reset_recamera_ids()
        _seen_recam_ids.clear()
        _seen_ids_date = datetime.now().strftime('%Y-%m-%d')
        _seen_ids_max  = 0
        _save_seen_ids()
        if ok:
            print("  ✓ reCamera 追踪 ID 已重置（WebSocket 断开重连）", flush=True)
        else:
            print("  ⚠ reCamera WebSocket 重置连接失败，已清空本地追踪状态", flush=True)


def _db_cleanup_loop():
    """每月1日凌晨01:00清理90天前的单区域明细记录，防止DB无限增长。
    保留全区域汇总行和近90天数据，不影响统计准确性。"""
    import urllib.request as _req
    while True:
        now = datetime.now()
        # 下一个月1日 01:00
        if now.month == 12:
            next_run = now.replace(year=now.year + 1, month=1, day=1,
                                   hour=1, minute=0, second=0, microsecond=0)
        else:
            next_run = now.replace(month=now.month + 1, day=1,
                                   hour=1, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run = next_run.replace(month=next_run.month % 12 + 1)
        time.sleep((next_run - datetime.now()).total_seconds())
        try:
            cutoff = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
            body = json.dumps({"cutoffDate": cutoff}).encode()
            req = _req.Request(
                "http://127.0.0.1:3000/api/trpc/footfall.archiveOldRecords",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _req.urlopen(req, timeout=30) as r:
                result = json.loads(r.read())
            print(f"  ✓ DB 清理完成（{cutoff} 前明细已归档）: {result}", flush=True)
        except Exception as e:
            print(f"  ⚠ DB 清理失败: {e}", flush=True)


def _in_operating_hours() -> bool:
    """当前北京时间是否在营业时段（08:00–22:00）。系统时区已设 Asia/Shanghai。"""
    h = datetime.now().hour
    return 8 <= h < 22


def report_room_counts(area_counts: dict, entry_counts: dict | None = None,
                       write_total: bool = False, no_entry_areas: set | None = None):
    """批量精准更新各区域实时人数到 footfall.reportRoomCounts。
    entry_counts: 有值时直接作为进入人次（reCamera ID追踪结果），优先于服务端差值。
    no_entry_areas: 这些区域传 entryCount=0，防止主循环对 reCamera 区域重复计数。
    write_total=True 时额外写一条全区域汇总行，仅主 YOLO 循环使用。
    """
    rooms = []
    for k, v in area_counts.items():
        room: dict = {"name": k, "count": v}
        if entry_counts is not None and k in entry_counts:
            room["entryCount"] = entry_counts[k]
        elif no_entry_areas is not None and k in no_entry_areas:
            room["entryCount"] = 0  # 告知服务端：此区域本次不计进入人次
        rooms.append(room)
    api = cfg().get("dashboard_api", "http://127.0.0.1:3000/api/trpc")
    _post(f"{api}/footfall.reportRoomCounts",
          json.dumps({"json": {"rooms": rooms, "writeTotal": write_total}}).encode())

def report_vlm(text: str, room: str):
    """VLM场景分析结果上报到 vlm.report"""
    api = cfg().get("dashboard_api", "http://127.0.0.1:3000/api/trpc")
    _post(f"{api}/vlm.report",
          json.dumps({"json": {
              "eventType": "analyze", "message": text, "roomName": room,
          }}).encode())

# ── RTSP 工具 ─────────────────────────────────────────────────────────────────
def _rtsp_url(ch_id: int, pwd: str) -> str:
    """
    直连摄像头 RTSP。
    优先使用通道级 rtsp_path（如主码流 /101），否则用全局 direct_path（子码流 /102）。
    """
    c      = cfg()
    ch_cfg = next((ch for ch in c.get("channels", []) if ch["id"] == ch_id), {})
    cam_ip = ch_cfg.get("camera_ip", c.get("nvr", {}).get("ip", ""))
    user   = c.get("nvr", {}).get("username", "admin")
    path   = ch_cfg.get("rtsp_path",
             c.get("rtsp", {}).get("direct_path", "/Streaming/Channels/102"))
    return f"rtsp://{user}:{pwd}@{cam_ip}:554{path}"

def _open_rtsp(ch_id: int) -> cv2.VideoCapture:
    """
    注意：超时属性必须在 open() 之前设置才会生效——cv2.VideoCapture(url, ...)
    构造函数会同步阻塞完成连接，之后再 set() 超时已经太晚（FFMPEG后端不会回溯应用）。
    黑洞路由（无响应、无RST）下旧写法可阻塞远超3秒，最长可达OS级TCP超时（数十到上百秒）。
    """
    pwds = cfg().get("nvr", {}).get("passwords", [])
    for pwd in pwds:
        cap = cv2.VideoCapture()
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 4000)
        if cap.open(_rtsp_url(ch_id, pwd), cv2.CAP_FFMPEG) and cap.isOpened():
            return cap
        cap.release()
    return cv2.VideoCapture()

# ── 初始化 ────────────────────────────────────────────────────────────────────
def init_rknn():
    global rknn
    from rknnlite.api import RKNNLite
    r = RKNNLite()
    if r.load_rknn(MODEL) != 0:
        raise RuntimeError(f"load_rknn 失败: {MODEL}")
    if r.init_runtime(core_mask=RKNNLite.NPU_CORE_AUTO) != 0:
        raise RuntimeError("init_runtime 失败，请确认 librknnrt.so 已安装")
    rknn = r
    print("  ✓ RKNN 运行时就绪 (core_mask=AUTO)")

def init_caps():
    global caps, cap_locks
    ok = 0
    rtsp_chs = [ch for ch in yolo_channels() if ch.get("mode") == "yolo"]
    for ch in rtsp_chs:
        ch_id = ch["id"]
        area  = ch.get("area", "?")
        ip    = ch.get("camera_ip", "?")
        cap   = _open_rtsp(ch_id)
        caps[ch_id]      = cap
        cap_locks[ch_id] = threading.Lock()
        if cap.isOpened():
            w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            print(f"  ✓ 通道{ch_id:02d}[{area}] ({ip})  {w}×{h}@{fps:.0f}fps")
            ok += 1
        else:
            print(f"  ✗ 通道{ch_id:02d}[{area}] ({ip})  连接失败（自动重连中）")
    # reCamera 通道：HTTP快照，无 VideoCapture，打印提示
    for ch in yolo_channels():
        if ch.get("mode") in ("recamera_yolo", "recamera_yolo_vlm"):
            mode_tag = "+VLM" if ch.get("mode") == "recamera_yolo_vlm" else ""
            print(f"  ✓ 通道{ch['id']:02d}[{ch.get('area','?')}]{mode_tag} "
                  f"(reCamera HTTP: {ch.get('recamera_url','?')})")
    print(f"\n  RTSP连接：{ok}/{len(rtsp_chs)} 路成功")

def validate_channel_mapping():
    """启动时打印通道→区域→IP精准映射核准表，供现场人员肉眼校对。"""
    print("\n  ── 通道映射核准表（请现场逐行核对） ───────────────────────────")
    for ch in cfg().get("channels", []):
        ch_id = ch["id"]
        area  = ch.get("area", "?")
        ip    = ch.get("camera_ip", "?")
        mode  = ch.get("mode", "yolo")
        if mode in ("recamera_yolo", "recamera_yolo_vlm"):
            tag = "YOLO+VLM" if mode == "recamera_yolo_vlm" else "YOLO"
            src = f"reCamera HTTP [{tag}]  {ch.get('recamera_url','?')}"
        elif mode == "vlm":
            src = f"VLM  reCamera HTTP  192.168.42.1:1880"
        else:
            path = cfg().get("rtsp", {}).get("direct_path", "/Streaming/Channels/102")
            src = f"直连 rtsp://{ip}:554{path}"
        print(f"  CH{ch_id:02d} → [{area:<8}] ({ip:<15}) {src}")
    print("  ─────────────────────────────────────────────────────────────\n")


def rebuild_caps():
    global caps, cap_locks
    for cap in caps.values():
        try: cap.release()
        except: pass
    caps.clear()
    cap_locks.clear()
    init_caps()
    init_photo_dirs()

def init_photo_dirs():
    for ch in yolo_channels():
        ch_dir = os.path.join(PHOTO_DIR, f"channel_{ch['id']:02d}")
        os.makedirs(ch_dir, exist_ok=True)
        # 启动时清理历史积累，只保留最新 PHOTO_MAX_PER_CHANNEL 张
        try:
            photos = sorted(f for f in os.listdir(ch_dir) if f.endswith('.jpg'))
            for old in photos[:-PHOTO_MAX_PER_CHANNEL]:
                os.remove(os.path.join(ch_dir, old))
        except OSError:
            pass
    print(f"  ✓ 快照目录: {PHOTO_DIR}/channel_XX/  (每路最多 {PHOTO_MAX_PER_CHANNEL} 张)")

# ── 推理流水线 ────────────────────────────────────────────────────────────────
def _reconnect_async(ch_id: int):
    """后台异步重连：绝不在 cap_locks[ch_id] 内同步阻塞，避免重连卡死时
    后续每轮新起的 worker 线程在锁上无限排队、无限堆积。"""
    try:
        new_cap = _open_rtsp(ch_id)
        old_cap = None
        with cap_locks[ch_id]:
            old_cap = caps.get(ch_id)
            caps[ch_id] = new_cap
        if old_cap is not None:
            try: old_cap.release()
            except Exception: pass
    finally:
        with _reconnect_state_lock:
            _ch_reconnecting[ch_id] = False
            _ch_cooldown_until[ch_id] = time.time() + _RECONNECT_COOLDOWN


def read_frame(ch_id: int):
    cap = caps.get(ch_id)
    if cap is None:
        return None

    # 非阻塞获取锁：若上一帧的读取/重连仍占用，本轮直接跳过，绝不无限等待
    if not cap_locks[ch_id].acquire(timeout=2):
        return None
    try:
        ok, f = cap.read()
    finally:
        cap_locks[ch_id].release()

    if ok:
        return f

    # 读取失败：触发一次后台重连，带冷却时间防止同一通道堆积重连线程
    now = time.time()
    with _reconnect_state_lock:
        already_running = _ch_reconnecting.get(ch_id, False)
        cooling_down     = now < _ch_cooldown_until.get(ch_id, 0)
        if not already_running and not cooling_down:
            _ch_reconnecting[ch_id] = True
            threading.Thread(target=_reconnect_async, args=(ch_id,), daemon=True).start()
    return None

def _is_dark_frame(frame_bgr: np.ndarray) -> bool:
    """判断是否为暗场景：灰度均值低于 DARK_THR 视为暗。"""
    return float(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).mean()) < DARK_THR


# Gamma 查找表 & CLAHE 缓存（避免每帧重复创建 C++ 对象）
_GAMMA_TABLE: dict = {}
_CLAHE = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

def _gamma_correct(frame_bgr: np.ndarray, gamma: float = 0.5) -> np.ndarray:
    """
    Gamma 校正（gamma<1 使暗部像素大幅提亮）。
    例：原始亮度43 → gamma=0.5后约105；原始110 → 约168。
    配合 CLAHE 形成"局部对比度+全局亮度"双重增强。
    """
    if gamma not in _GAMMA_TABLE:
        table = np.array(
            [int((i / 255.0) ** gamma * 255) for i in range(256)], dtype=np.uint8
        )
        _GAMMA_TABLE[gamma] = table
    return cv2.LUT(frame_bgr, _GAMMA_TABLE[gamma])


def _enhance_dark_frame(frame_bgr: np.ndarray) -> np.ndarray:
    """
    双重暗场增强流水线：
    ① CLAHE（LAB-L通道局部对比度均衡）→ 增强深色衣物轮廓边缘
    ② Gamma 0.55 校正 → 整体提亮暗区，使 YOLO 特征更显著
    """
    lab           = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l, a, b       = cv2.split(lab)
    l_eq          = _CLAHE.apply(l)
    enhanced_lab  = cv2.merge([l_eq, a, b])
    enhanced_bgr  = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
    return _gamma_correct(enhanced_bgr, gamma=0.55)


def infer_with_tiles(frame_bgr: np.ndarray, conf: float | None = None,
                     n_rows: int = 2, n_cols: int = 2,
                     overlap: float = 0.25) -> tuple:
    """
    2×2 分块推理：把高分辨率帧切成 4 块（带 15% 重叠），各自放大到 640×640 后推理，
    检测框反变换回原图坐标后做全局 NMS 合并。
    适用场景：1920×1080 及以上，多人/小目标场景，精度比单帧推理提升显著。
    返回 (count, boxes_in_orig_frame_coords)。
    """
    _conf = conf if conf is not None else CONF
    h, w  = frame_bgr.shape[:2]

    all_boxes:  list = []
    all_scores: list = []

    for r in range(n_rows):
        for c in range(n_cols):
            ov_y = int(overlap * h / n_rows)
            ov_x = int(overlap * w / n_cols)
            ty1  = max(0, r       * (h // n_rows) - ov_y)
            ty2  = min(h, (r + 1) * (h // n_rows) + ov_y)
            tx1  = max(0, c       * (w // n_cols) - ov_x)
            tx2  = min(w, (c + 1) * (w // n_cols) + ov_x)

            tile    = frame_bgr[ty1:ty2, tx1:tx2]
            tile_h, tile_w = tile.shape[:2]

            # Letterbox tile → 640×640
            scale_t = min(IN_SZ / tile_h, IN_SZ / tile_w)
            nh, nw  = int(round(tile_h * scale_t)), int(round(tile_w * scale_t))
            pxt = (IN_SZ - nw) // 2
            pyt = (IN_SZ - nh) // 2
            resized = cv2.resize(tile, (nw, nh), interpolation=cv2.INTER_LINEAR)
            canvas  = np.full((IN_SZ, IN_SZ, 3), 114, dtype=np.uint8)
            canvas[pyt:pyt+nh, pxt:pxt+nw] = resized
            img = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)[np.newaxis]

            with rknn_lock:
                outs = rknn.inference(inputs=[img])
            del img

            # 解析各尺度输出，将检测框变换到原图坐标
            for i, stride in enumerate([8, 16, 32]):
                dfl     = outs[i*3]
                cls_out = outs[i*3+1]
                obj_out = outs[i*3+2]
                b640    = _dfl_decode(dfl, stride)
                num_cls = cls_out.shape[1]
                cls_s   = cls_out[0].reshape(num_cls, -1).T
                obj_s   = obj_out[0].reshape(-1)
                person  = cls_s[:, 0] * obj_s
                mask    = person > _conf
                if mask.any():
                    b  = b640[mask]
                    s  = person[mask]
                    # 640-空间 → tile-空间 → 原图空间
                    ox1 = (b[:, 0] - pxt) / scale_t + tx1
                    oy1 = (b[:, 1] - pyt) / scale_t + ty1
                    ox2 = (b[:, 2] - pxt) / scale_t + tx1
                    oy2 = (b[:, 3] - pyt) / scale_t + ty1
                    all_boxes.append(np.stack([ox1, oy1, ox2, oy2], axis=1))
                    all_scores.append(s)
            del outs

    if not all_boxes:
        return 0, np.empty((0, 4), dtype=np.float32)

    boxes  = np.concatenate(all_boxes)
    scores = np.concatenate(all_scores)
    # 截断到原图边界
    boxes[:, 0::2] = np.clip(boxes[:, 0::2], 0, w)
    boxes[:, 1::2] = np.clip(boxes[:, 1::2], 0, h)
    # 分块推理合并 NMS：使用更宽松的 IoU=0.35（原始 0.45 太严格，
    # 导致两个分块对同一人产生的稍有偏移的框无法被合并）
    keep   = _nms(boxes, scores, iou_thr=0.35)
    return len(keep), boxes[keep]


def preprocess(frame):
    h, w   = frame.shape[:2]
    scale  = min(IN_SZ / h, IN_SZ / w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    px = (IN_SZ - nw) // 2
    py = (IN_SZ - nh) // 2
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas  = np.full((IN_SZ, IN_SZ, 3), 114, dtype=np.uint8)
    canvas[py:py+nh, px:px+nw] = resized
    img = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    return img[np.newaxis], scale, px, py

def _nms(boxes, scores, iou_thr: float | None = None):
    if len(boxes) == 0:
        return []
    _iou_thr = iou_thr if iou_thr is not None else IOU
    x1, y1, x2, y2 = boxes[:,0], boxes[:,1], boxes[:,2], boxes[:,3]
    areas = (x2-x1) * (y2-y1)
    idx   = scores.argsort()[::-1]
    keep  = []
    while idx.size:
        i = idx[0]; keep.append(i)
        if idx.size == 1: break
        xx1 = np.maximum(x1[i], x1[idx[1:]])
        yy1 = np.maximum(y1[i], y1[idx[1:]])
        xx2 = np.minimum(x2[i], x2[idx[1:]])
        yy2 = np.minimum(y2[i], y2[idx[1:]])
        inter = np.maximum(0, xx2-xx1) * np.maximum(0, yy2-yy1)
        iou   = inter / (areas[i] + areas[idx[1:]] - inter + 1e-6)
        idx   = idx[np.where(iou <= _iou_thr)[0] + 1]
    return keep

def _softmax(x, axis):
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)

def _dfl_decode(dfl_raw, stride, reg_max=16):
    _, _, H, W = dfl_raw.shape
    dfl  = dfl_raw[0].reshape(4, reg_max, H, W)
    dfl  = _softmax(dfl, axis=1)
    bins = np.arange(reg_max, dtype=np.float32).reshape(1, reg_max, 1, 1)
    reg  = (dfl * bins).sum(axis=1)
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32),
                          np.arange(H, dtype=np.float32))
    cx = (gx + 0.5) * stride
    cy = (gy + 0.5) * stride
    x1 = cx - reg[0]*stride; y1 = cy - reg[1]*stride
    x2 = cx + reg[2]*stride; y2 = cy + reg[3]*stride
    return np.stack([x1, y1, x2, y2], axis=-1).reshape(-1, 4)

def postprocess(outputs, conf: float | None = None):
    """
    conf: 动态置信度阈值。传入 CONF_DARK 时启用暗场景低阈值模式，
          提升深色衣物/低对比度场景的人员召回率。
    """
    _conf = conf if conf is not None else CONF
    strides = [8, 16, 32]
    all_boxes, all_scores = [], []
    for i, stride in enumerate(strides):
        dfl = outputs[i*3]; cls = outputs[i*3+1]; obj = outputs[i*3+2]
        boxes   = _dfl_decode(dfl, stride)
        num_cls = cls.shape[1]
        cls_s   = cls[0].reshape(num_cls, -1).T
        obj_s   = obj[0].reshape(-1)
        person  = cls_s[:, 0] * obj_s
        mask = person > _conf
        if mask.any():
            all_boxes.append(boxes[mask])
            all_scores.append(person[mask])
    if not all_boxes:
        return 0, np.empty((0, 4), dtype=np.float32)
    boxes  = np.concatenate(all_boxes)
    scores = np.concatenate(all_scores)
    keep   = _nms(boxes, scores)
    return len(keep), boxes[keep]

def save_annotated(frame_bgr, boxes_640, ch_id: int, scale, px, py):
    orig_h, orig_w = frame_bgr.shape[:2]
    img = frame_bgr.copy()
    for x1, y1, x2, y2 in boxes_640:
        ox1 = max(0, int((x1-px)/scale))
        oy1 = max(0, int((y1-py)/scale))
        ox2 = min(orig_w-1, int((x2-px)/scale))
        oy2 = min(orig_h-1, int((y2-py)/scale))
        cv2.rectangle(img, (ox1, oy1), (ox2, oy2), (0, 255, 0), 2)
        cv2.putText(img, "person", (ox1, max(oy1-8, 0)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    ch_dir = os.path.join(PHOTO_DIR, f"channel_{ch_id:02d}")
    path   = os.path.join(ch_dir, f"{ts}.jpg")
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    # 每50次触发一次旧照片清理，只保留最新 PHOTO_MAX_PER_CHANNEL 张
    cnt = _photo_save_count.get(ch_id, 0) + 1
    _photo_save_count[ch_id] = cnt
    if cnt % 50 == 0:
        try:
            photos = sorted(f for f in os.listdir(ch_dir) if f.endswith('.jpg'))
            for old in photos[:-PHOTO_MAX_PER_CHANNEL]:
                os.remove(os.path.join(ch_dir, old))
        except OSError:
            pass

def recamera_worker(ch_id: int, results: dict, boxes_out: dict):
    """
    reCamera HTTP 快照 → YOLO 推理。
    支持 recamera_yolo 和 recamera_yolo_vlm 两种模式。
    始终开启暗场景 CLAHE 增强（reCamera 画面通常亮度不稳定）。
    """
    ch_cfg = next((c for c in yolo_channels() if c["id"] == ch_id), None)
    if not ch_cfg:
        results[ch_id] = -1
        return
    url = ch_cfg.get("recamera_url", "http://192.168.42.1:1880/api/snapshot")
    try:
        import urllib.request as ur
        # 序列化同一 reCamera 主机的快照请求（避免并发导致超时）
        with _recamera_lock(url):
            with ur.urlopen(url, timeout=5) as resp:
                raw = resp.read()
        arr   = np.frombuffer(raw, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            results[ch_id] = -1
            return
    except Exception:
        results[ch_id] = -1
        return
    # reCamera 始终 CLAHE 增强 + 低置信度；1920×1080 自动开启分块推理
    frame = _enhance_dark_frame(frame)
    conf  = CONF_DARK
    orig_h, orig_w = frame.shape[:2]

    ch_cfg    = next((c for c in yolo_channels() if c["id"] == ch_id), {})
    use_tiles = ch_cfg.get("tiled_inference", False) and orig_w >= 1280

    if use_tiles:
        count, boxes = infer_with_tiles(frame, conf=conf)
        results[ch_id]   = count
        boxes_out[ch_id] = _norm_boxes(boxes, 1.0, 0, 0, orig_w, orig_h)
        save_annotated(frame, boxes, ch_id, 1.0, 0, 0)
    else:
        img, scale, px, py = preprocess(frame)
        with rknn_lock:
            outs = rknn.inference(inputs=[img])
        del img
        count, boxes = postprocess(outs, conf=conf)
        del outs
        results[ch_id]   = count
        boxes_out[ch_id] = _norm_boxes(boxes, scale, px, py, orig_w, orig_h)
        save_annotated(frame, boxes, ch_id, scale, px, py)
    del frame, boxes


def recamera_fast_loop():
    """
    reCamera 专属高频推理循环，每 1 秒推一次 YOLO。
    使用 /api/ids 追踪人员 ID，防止同一人反复计入进入人次。
    """
    global _recam_area_counts, _seen_recam_ids, _seen_ids_date, _seen_ids_max
    FAST_INTERVAL = 1.0

    while True:
        t0 = time.perf_counter()
        try:
            results:   dict = {}
            boxes_out: dict = {}

            recam_chs = [ch for ch in yolo_channels()
                         if ch.get("mode") in ("recamera_yolo", "recamera_yolo_vlm")]
            if recam_chs:
                threads = [
                    threading.Thread(target=recamera_worker,
                                     args=(ch["id"], results, boxes_out), daemon=True)
                    for ch in recam_chs
                ]
                for t in threads: t.start()
                for t in threads: t.join(timeout=5)

                area_counts: dict = {}
                for ch in recam_chs:
                    area  = ch["area"]
                    count = results.get(ch["id"], -1)
                    if area not in area_counts:
                        area_counts[area] = 0
                    if count >= 0:
                        area_counts[area] += count

                # ── ID 追踪：仅统计当天首次出现的追踪 ID 为新进入 ────────────────────
                entry_counts: dict | None = None
                ids_info = _fetch_recamera_ids()
                if ids_info is not None:
                    today = datetime.now().strftime('%Y-%m-%d')
                    if today != _seen_ids_date:
                        _seen_recam_ids.clear()
                        _seen_ids_date = today
                        _seen_ids_max  = 0

                    current_ids = set(ids_info.get("ids", []))
                    if current_ids:
                        cur_max = max(current_ids)
                        # reCamera 重启后追踪 ID 从 0 重新计数，检测到回退时清空历史集合
                        if _seen_ids_max > 20 and cur_max < _seen_ids_max - 10:
                            _seen_recam_ids.clear()
                            _seen_ids_max = 0
                        _seen_ids_max = max(_seen_ids_max, cur_max)

                    new_ids = current_ids - _seen_recam_ids
                    _seen_recam_ids.update(current_ids)
                    _save_seen_ids()  # 原子写盘，防止重启后重复计数

                    # 用 ID 数量覆盖实际人数（reCamera 自带计数更精准）
                    recam_count = ids_info.get("count", area_counts.get(recam_chs[0]["area"], 0))
                    for ch in recam_chs:
                        area_counts[ch["area"]] = recam_count

                    entry_counts = {ch["area"]: len(new_ids) for ch in recam_chs}

                if area_counts:
                    with _recam_lock:
                        _recam_area_counts = dict(area_counts)
                    if _in_operating_hours():
                        report_room_counts(area_counts, entry_counts, write_total=True)
                    else:
                        # 非营业时段（22:00–次日08:00）：仅更新热力图显示，不写入进入记录
                        report_room_counts(area_counts, write_total=False,
                                           no_entry_areas=set(area_counts.keys()))
        except Exception as e:
            # 任何单轮异常都不能让本线程退出——否则心跳永久停止写入，
            # 只能靠看门狗整体重启进程才能恢复（已实测发生过一次：NPU推理异常
            # 导致 postprocess 拿到坏数据，进而本循环抛出未捕获异常而退出）
            print(f"  [reCamera循环] 本轮异常，已跳过: {e}", flush=True)
        finally:
            _write_heartbeat("recam")
            wait = max(0.0, FAST_INTERVAL - (time.perf_counter() - t0))
            time.sleep(wait)


_RESULTS_PATH = "/tmp/yolo_results.json"
_RESULTS_TMP  = "/tmp/yolo_results.json.tmp"

def save_debug_results(ch_results: dict, area_counts: dict, boxes_out: dict | None = None):
    """
    原子写入推理结果供 debug_controller 读取。
    先写到 .tmp 临时文件，再用 os.replace() 原子替换目标文件。
    确保读取方永远看到完整的 JSON，不会出现截断导致的解析失败。
    """
    try:
        data = {
            "ts":       datetime.now().isoformat(),
            "channels": {str(k): v for k, v in ch_results.items()},
            "areas":    area_counts,
            "boxes":    {str(k): v for k, v in (boxes_out or {}).items()},
        }
        with open(_RESULTS_TMP, "w") as f:
            json.dump(data, f)
        os.replace(_RESULTS_TMP, _RESULTS_PATH)   # Linux 原子 rename
    except Exception:
        pass


def _norm_boxes(boxes_640, scale, px, py, orig_w, orig_h) -> list:
    """将 YOLO 640-空间检测框转换为原始帧的归一化坐标 [x1n,y1n,x2n,y2n]。
    注意：boxes 元素为 numpy.float32，必须用 float() 转换才能 JSON 序列化。
    """
    result = []
    for x1, y1, x2, y2 in boxes_640:
        ox1 = float(max(0.0, (x1 - px) / scale / orig_w))
        oy1 = float(max(0.0, (y1 - py) / scale / orig_h))
        ox2 = float(min(1.0, (x2 - px) / scale / orig_w))
        oy2 = float(min(1.0, (y2 - py) / scale / orig_h))
        result.append([round(ox1, 4), round(oy1, 4), round(ox2, 4), round(oy2, 4)])
    return result


# ── 实时单通道推理（供 debug_controller 调用） ────────────────────────────────
INFER_API_PORT = 8082

def _single_infer(ch_id: int) -> dict:
    """
    对指定通道抓一帧并立即推理，返回 {count, boxes, ts, dark}。
    复用主进程的 rknn 实例，无 NPU 冲突，每次调用约 30-150ms。
    """
    if rknn is None:
        return {"count": -1, "boxes": [], "error": "rknn not ready"}
    try:
        ch_cfg = next((c for c in yolo_channels() if c["id"] == ch_id), None)
        if not ch_cfg:
            return {"count": -1, "boxes": [], "error": "channel not found"}

        mode = ch_cfg.get("mode", "yolo")
        if mode in ("recamera_yolo", "recamera_yolo_vlm"):
            url = ch_cfg.get("recamera_url", "http://192.168.42.1:1880/api/snapshot")
            with _recamera_lock(url):
                with urllib.request.urlopen(url, timeout=5) as r:
                    raw = r.read()
            arr   = np.frombuffer(raw, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        else:
            frame = read_frame(ch_id)

        if frame is None:
            return {"count": -1, "boxes": [], "error": "no frame"}

        dark = _is_dark_frame(frame)
        conf = CONF_DARK if (dark or mode in ("recamera_yolo", "recamera_yolo_vlm")) else CONF
        if dark or mode in ("recamera_yolo", "recamera_yolo_vlm"):
            frame = _enhance_dark_frame(frame)

        orig_h, orig_w = frame.shape[:2]
        use_tiles = ch_cfg.get("tiled_inference", False) and orig_w >= 1280

        if use_tiles:
            count, boxes = infer_with_tiles(frame, conf=conf)
            norm = _norm_boxes(boxes, 1.0, 0, 0, orig_w, orig_h)
        else:
            img, scale, px, py = preprocess(frame)
            with rknn_lock:
                outs = rknn.inference(inputs=[img])
            del img
            count, boxes = postprocess(outs, conf=conf)
            del outs
            norm = _norm_boxes(boxes, scale, px, py, orig_w, orig_h)

        del frame, boxes
        return {"count": count, "boxes": norm,
                "ts": datetime.now().isoformat(), "dark": dark, "tiled": use_tiles}
    except Exception as exc:
        return {"count": -1, "boxes": [], "error": str(exc)}


class _InferHandler(http.server.BaseHTTPRequestHandler):
    """GET /infer/{ch_id} → 实时推理并返回 JSON。"""
    def log_message(self, *args): pass   # 不打印每次请求日志

    def do_GET(self):
        path = self.path.strip("/").split("/")
        if len(path) == 2 and path[0] == "infer":
            try:
                ch_id = int(path[1])
            except ValueError:
                self.send_response(400); self.end_headers(); return
            result = _single_infer(ch_id)
            body   = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type",   "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()


def start_infer_server():
    """在后台线程启动实时推理 API，端口 INFER_API_PORT。"""
    server = socketserver.TCPServer(("127.0.0.1", INFER_API_PORT), _InferHandler)
    server.allow_reuse_address = True
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"  ✓ 实时推理接口: http://127.0.0.1:{INFER_API_PORT}/infer/{{channel}}")
    return server


def worker(ch_id: int, results: dict, boxes_out: dict):
    frame = read_frame(ch_id)
    if frame is None:
        results[ch_id] = -1
        return
    dark  = _is_dark_frame(frame)
    conf  = CONF_DARK if dark else CONF
    if dark:
        frame = _enhance_dark_frame(frame)
    orig_h, orig_w = frame.shape[:2]

    ch_cfg     = next((c for c in yolo_channels() if c["id"] == ch_id), {})
    use_tiles  = ch_cfg.get("tiled_inference", False) and orig_w >= 1280

    if use_tiles:
        count, boxes = infer_with_tiles(frame, conf=conf)
        # boxes 已是原图坐标，用 scale=1, px=py=0 传给 _norm_boxes / save_annotated
        results[ch_id]   = count
        boxes_out[ch_id] = _norm_boxes(boxes, 1.0, 0, 0, orig_w, orig_h)
        save_annotated(frame, boxes, ch_id, 1.0, 0, 0)
    else:
        img, scale, px, py = preprocess(frame)
        with rknn_lock:
            outs = rknn.inference(inputs=[img])
        del img
        count, boxes = postprocess(outs, conf=conf)
        del outs
        results[ch_id]   = count
        boxes_out[ch_id] = _norm_boxes(boxes, scale, px, py, orig_w, orig_h)
        save_annotated(frame, boxes, ch_id, scale, px, py)
    del frame, boxes

# ── 区域聚合（支持多路摄像头归入同一区域） ────────────────────────────────────
def aggregate_rooms(ch_results: dict) -> dict:
    """
    将各通道推理结果按区域名聚合。
    - 同区域多路：累加
    - 断线通道（count=-1）：对该区域贡献 0，不跳过（防止脏数据残留）
    - 每个区域始终出现在结果字典中，保证大屏每轮都被刷新为真实值
    """
    # 先将所有区域初始化为 0，确保断线时仍下发 0 而非保留历史值
    area_counts: dict = {}
    for ch in yolo_channels():
        area = ch["area"]
        if area not in area_counts:
            area_counts[area] = 0
    # 叠加各通道有效计数
    for ch in yolo_channels():
        ch_id = ch["id"]
        area  = ch["area"]
        count = ch_results.get(ch_id, -1)
        if count >= 0:
            area_counts[area] += count
    return area_counts

# ── 报告打印 ───────────────────────────────────────────────────────────────────
def print_report(area_counts: dict, ch_results: dict,
                 elapsed_ms: float, vlm_text: str = ""):
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = sum(area_counts.values())
    SEP   = "═" * 62
    SEP2  = "─" * 62

    lines = ["", f"  {SEP}",
             f"  ◆  YOLOv11n 14路行人检测  [生产·RTSP·区域对齐]",
             f"  ◆  时间: {ts}", f"  {SEP}"]

    for ch in yolo_channels():
        ch_id = ch["id"]
        area  = ch["area"]
        ip    = ch.get("camera_ip", "?")
        cnt   = ch_results.get(ch_id, -1)
        tag   = f"[{ch_id:02d}·{area}·{ip}]"
        if cnt >= 0:
            bar  = "█" * min(cnt, 20)
            line = f"  {tag}  {cnt:2d}人  {bar}"
        else:
            line = f"  {tag}  ── RTSP读取失败（重连中）──"
        lines.append(line)

    lines += [f"  {SEP2}",
              f"  区域汇总: {area_counts}",
              f"  合计: {total}人   耗时: {elapsed_ms:.0f}ms"]

    if vlm_text:
        vch  = vlm_channel()
        varea = vch.get("area", "VLM Area") if vch else "VLM Area"
        channel = vch.get("id", "?") if vch else "?"
        lines.append(f"  ◆  VLM[{channel}·{varea}]: {vlm_text}")

    lines += [f"  {SEP}", ""]
    with print_lock:
        print("\n".join(lines), flush=True)

# ── 配置热加载守护线程 ─────────────────────────────────────────────────────────
def config_watcher():
    global _rebuild_needed
    while True:
        reload_interval = cfg().get("config_reload_interval", 30)
        time.sleep(reload_interval)
        try:
            mtime = os.path.getmtime(CONFIG_FILE)
            with _cfg_lock:
                old_mtime = _cfg_mtime
            if mtime > old_mtime:
                new_cfg = _load_config()
                _apply_config(new_cfg)
                with _rebuild_flag_lock:
                    _rebuild_needed = True
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"  ♻ config.json 已变更，下轮循环热重载 ({ts})", flush=True)
        except Exception as exc:
            print(f"  ⚠ 配置热重载检查异常: {exc}", flush=True)

# ── 主循环 ────────────────────────────────────────────────────────────────────
def main():
    global _rebuild_needed, _last_vlm_emit_at   # 必须在函数顶部声明，Python 编译期作用域分析要求
    raw_cfg = _load_config()
    _apply_config(raw_cfg)

    nvr   = cfg().get("nvr", {})
    n_yolo = len(yolo_channels())
    vlm_ch = vlm_channel()

    print(f"\n{'─'*60}")
    print(f"  RK3576 NPU · 14路行人检测+VLM  [生产·RTSP·区域对齐]")
    print(f"{'─'*60}")
    print(f"  NVR  : {nvr.get('ip')}:{nvr.get('port', 554)}")
    print(f"  YOLO : {n_yolo}路  "
          f"通道 {', '.join(str(ch['id']) for ch in yolo_channels())}")
    vlm_label = f"通道{vlm_ch['id']} → {vlm_ch.get('area', 'VLM Area')}" if vlm_ch else "N/A"
    print(f"  VLM  : {vlm_label}")
    print(f"  配置 : {CONFIG_FILE}  (热加载间隔 "
          f"{cfg().get('config_reload_interval', 30)}s)")
    print(f"  正在初始化…\n")

    init_rknn()
    init_caps()
    init_photo_dirs()
    _load_seen_ids()   # 恢复今日 ID 追踪状态，防止重启后重复计数
    validate_channel_mapping()

    threading.Thread(target=config_watcher, daemon=True).start()
    threading.Thread(target=recamera_fast_loop, daemon=True).start()
    threading.Thread(target=_recamera_id_reset_loop, daemon=True).start()
    threading.Thread(target=_db_cleanup_loop, daemon=True).start()
    start_infer_server()

    if vlm.is_ready():
        print("  ✓ VLM API 就绪 (localhost:8002)")
    else:
        print("  ⚠ VLM API 未就绪（确认 Docker 容器运行中）")

    interval = cfg().get("yolo_interval", 20)
    print(f"\n  系统就绪，RTSP 每 {interval} 秒一轮，reCamera 每 1 秒一轮。Ctrl+C 退出。\n")

    while True:
        t0 = time.perf_counter()
        try:
            # ── 检查是否需要热重载 RTSP 连接 ──────────────────────────────────
            with _rebuild_flag_lock:
                need_rebuild = _rebuild_needed
                if need_rebuild:
                    _rebuild_needed = False
            if need_rebuild:
                print("  ♻ 正在重建 RTSP 连接…", flush=True)
                rebuild_caps()
                print("  ✓ RTSP 连接已重建", flush=True)

            ch_results: dict = {}
            boxes_out:  dict = {}
            yolo_chs   = yolo_channels()

            threads = []
            for ch in yolo_chs:
                # reCamera 通道由 recamera_fast_loop 独立处理，主循环跳过
                if ch.get("mode") in ("recamera_yolo", "recamera_yolo_vlm"):
                    continue
                t = threading.Thread(target=worker,
                                     args=(ch["id"], ch_results, boxes_out), daemon=True)
                threads.append(t)
            for t in threads: t.start()
            for t in threads: t.join(timeout=30)

            elapsed_ms  = (time.perf_counter() - t0) * 1000
            area_counts = aggregate_rooms(ch_results)

            # 合并 reCamera 快速循环的最新区域计数（仅用于显示，不在此计进入人次）
            with _recam_lock:
                recam_areas = set(_recam_area_counts.keys())
                for area, count in _recam_area_counts.items():
                    area_counts[area] = count

            total = sum(area_counts.values())

            # ── VLM 分析（独立于 YOLO） ─────────────────────────────────────────
            vlm_text = ""
            vch      = vlm_channel()
            vlm_area = vch.get("area", "VLM Area") if vch else "VLM Area"
            now = time.monotonic()
            if vlm.is_ready() and (total > 0 or now - _last_vlm_emit_at >= 60):
                vlm_text = vlm.analyze(total)
                if vlm_text:
                    _last_vlm_emit_at = now

            # ── 输出 + 上报 ────────────────────────────────────────────────────
            print_report(area_counts, ch_results, elapsed_ms, vlm_text)
            # no_entry_areas：reCamera 区域已由快速循环用 ID 追踪精确计数，主循环不重复计
            if _in_operating_hours():
                report_room_counts(area_counts, write_total=True, no_entry_areas=recam_areas)
            else:
                # 非营业时段：仅更新热力图显示，不写入进入记录
                report_room_counts(area_counts, write_total=False,
                                   no_entry_areas=set(area_counts.keys()))
            save_debug_results(ch_results, area_counts, boxes_out)  # 含检测框供调试控制器
            if vlm_text:
                report_vlm(vlm_text, vlm_area)
        except Exception as e:
            # 任何单轮异常都不能让主循环退出——否则只能靠PM2整进程重启才能恢复，
            # 代价比跳过一轮更大（已实测reCamera循环发生过同类问题，详见 recamera_fast_loop）
            print(f"  [主循环] 本轮异常，已跳过: {e}", flush=True)
        finally:
            _write_heartbeat("main")
            wait = max(0.0, cfg().get("yolo_interval", 20) - (time.perf_counter() - t0))
            time.sleep(wait)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  已停止监控。")
    finally:
        for cap in caps.values():
            try: cap.release()
            except: pass
        if rknn:
            try: rknn.release()
            except: pass
