#!/usr/bin/env python3
"""
reCamera 图像拉取服务
持续从 reCamera (192.168.42.1:1880) 抓取快照，保存到大屏可读目录
大屏通过静态文件路径 /snapshot/latest.jpg 读取最新帧
"""
import time
import urllib.request
import urllib.error
import os
import shutil
import signal
import sys

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
RECAMERA_URL   = os.getenv("RECAMERA_URL", "http://192.168.42.1:1880/api/snapshot")
OUTPUT_DIR     = os.getenv(
    "RECAMERA_OUTPUT_DIR",
    os.path.join(BASE_DIR, "app", "dist", "public", "snapshot"),
)
LATEST_PATH    = os.path.join(OUTPUT_DIR, "latest.jpg")
INTERVAL       = 1.0 / 10   # 10fps（reCamera HTTP API 不宜拉太快）
CONNECT_TIMEOUT = 3
READ_TIMEOUT    = 5
_running = True


def _sig_handler(sig, frame):
    global _running
    _running = False
    print("\n[recamera_puller] 收到停止信号，正在退出…", flush=True)
    sys.exit(0)


signal.signal(signal.SIGTERM, _sig_handler)
signal.signal(signal.SIGINT,  _sig_handler)


def ensure_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def fetch_snapshot() -> bytes | None:
    try:
        req = urllib.request.Request(RECAMERA_URL, headers={"Accept": "image/jpeg"})
        with urllib.request.urlopen(req, timeout=READ_TIMEOUT) as resp:
            if resp.status == 200:
                return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    return None


def save_snapshot(data: bytes):
    # 目录可能在进程运行期间被部署/构建流程重建（如 npm run build 重新生成 dist/public），
    # 每次写入前兜底确保目录存在，避免因此长期写入失败直到进程重启才能自愈
    ensure_dir()
    tmp = LATEST_PATH + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    shutil.move(tmp, LATEST_PATH)   # 原子替换，避免大屏读到半截文件


def main():
    ensure_dir()
    ok_count   = 0
    fail_count = 0
    last_log   = time.time()

    print(f"[recamera_puller] 启动，拉取地址: {RECAMERA_URL}", flush=True)
    print(f"[recamera_puller] 输出目录: {OUTPUT_DIR}", flush=True)

    while _running:
        t0   = time.perf_counter()
        data = fetch_snapshot()

        if data:
            save_snapshot(data)
            ok_count   += 1
            fail_count  = 0
        else:
            fail_count += 1
            if fail_count == 1:
                print(f"[recamera_puller] ⚠ reCamera 不可达，重试中…", flush=True)

        # 每 30 秒打印一次状态
        now = time.time()
        if now - last_log >= 30:
            status = "✓ 正常" if data else "✗ 离线"
            print(f"[recamera_puller] 状态: {status}  累计成功帧: {ok_count}", flush=True)
            last_log = now

        elapsed = time.perf_counter() - t0
        sleep   = max(0.0, INTERVAL - elapsed)
        time.sleep(sleep)


if __name__ == "__main__":
    main()
