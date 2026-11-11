#!/usr/bin/env python3
"""
现场全天测试监控记录器：独立进程，每分钟采样一次系统状态，写入JSONL日志，
供测试结束后离线分析（内存增长趋势、PM2重启次数、心跳异常、新增错误等）。

设计原则：本身必须极简、只读取已有状态（pm2 jlist / 心跳文件mtime / 错误日志增量），
不调用任何可能阻塞或失败的网络/外部依赖，避免成为新的故障点。
"""
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.getenv("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
PM2_HOME = os.getenv("PM2_HOME", os.path.expanduser("~/.pm2"))
LOG_PATH = os.getenv("FIELD_MONITOR_LOG", os.path.join(PROJECT_ROOT, "field_test_log.jsonl"))
SAMPLE_INTERVAL = 60  # 秒

HEARTBEAT_FILES = {
    "main":  "/tmp/yolo_heartbeat_main",
    "recam": "/tmp/yolo_heartbeat_recam",
}

ERROR_LOG_FILES = {
    "yolo-detector":   os.path.join(PM2_HOME, "logs", "yolo-detector-error.log"),
    "recamera-puller": os.path.join(PM2_HOME, "logs", "recamera-puller-error.log"),
    "people-counting-dashboard": os.path.join(PM2_HOME, "logs", "people-counting-dashboard-error.log"),
    "watchdog-out":    os.path.join(PM2_HOME, "logs", "watchdog-out.log"),
}

# 已知噪音行：RTSP断线重连是预期行为，不计入"新增异常"
NOISE_SUBSTRINGS = (
    "Connection timed out",
    "VIDEOIO(FFMPEG)",
    "rknn-toolkit-lite2",
    "Query dynamic range",
    "RTSP读取失败",
)

_pm2_bin = shutil.which("pm2") or "pm2"
CST = timezone(timedelta(hours=8))


def _now_cst_iso() -> str:
    return datetime.now(CST).isoformat()


def _pm2_status() -> list:
    try:
        out = subprocess.run([_pm2_bin, "jlist"], capture_output=True, timeout=10, text=True, check=True)
        data = json.loads(out.stdout)
        now_ms = time.time() * 1000
        return [
            {
                "name": p["name"],
                "status": p["pm2_env"]["status"],
                "restarts": p["pm2_env"]["restart_time"],
                "pid": p.get("pid"),
                "uptime_s": round((now_ms - p["pm2_env"]["pm_uptime"]) / 1000) if p["pm2_env"].get("pm_uptime") else None,
                "mem_mb": round(p["monit"]["memory"] / 1024 / 1024, 1) if p.get("monit") else None,
                "cpu_pct": p["monit"]["cpu"] if p.get("monit") else None,
            }
            for p in data
        ]
    except Exception as e:
        return [{"error": f"pm2_jlist_failed: {e}"}]


def _heartbeat_ages() -> dict:
    now = time.time()
    ages = {}
    for name, path in HEARTBEAT_FILES.items():
        try:
            ages[name] = round(now - os.path.getmtime(path), 1)
        except OSError:
            ages[name] = None  # 文件不存在
    return ages


def _disk_free_pct(path: str = "/data") -> float:
    total, used, free = shutil.disk_usage(path)
    return round(free / total * 100, 1)


def _read_new_lines(path: str, offset: int) -> tuple[list, int]:
    """从上次记录的字节偏移量起读取新增内容；文件被截断/轮转时从头读。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], offset
    if size < offset:
        offset = 0  # 日志被轮转/清空
    new_lines = []
    try:
        with open(path, "r", errors="replace") as f:
            f.seek(offset)
            new_lines = [l.rstrip("\n") for l in f.readlines()]
        new_offset = f.tell() if False else os.path.getsize(path)
    except OSError:
        return [], offset
    return new_lines, new_offset


def main():
    print(f"[field_monitor] 启动，每{SAMPLE_INTERVAL}秒采样一次，日志写入 {LOG_PATH}", flush=True)
    error_offsets = {name: 0 for name in ERROR_LOG_FILES}
    # 启动时跳过已有内容，只记录从现在开始的新增异常
    for name, path in ERROR_LOG_FILES.items():
        try:
            error_offsets[name] = os.path.getsize(path)
        except OSError:
            error_offsets[name] = 0

    while True:
        sample = {
            "ts": _now_cst_iso(),
            "pm2": _pm2_status(),
            "heartbeat_age_s": _heartbeat_ages(),
            "disk_free_pct": _disk_free_pct(),
        }

        new_errors = {}
        for name, path in ERROR_LOG_FILES.items():
            lines, error_offsets[name] = _read_new_lines(path, error_offsets[name])
            significant = [l for l in lines if l.strip() and not any(n in l for n in NOISE_SUBSTRINGS)]
            if name == "watchdog-out":
                # 看门狗的重启动作是关注点而不是"错误"，单独标出但仍记录
                significant = [l for l in lines if "看门狗" in l or "restart" in l.lower()]
            if significant:
                new_errors[name] = significant
        if new_errors:
            sample["new_log_lines"] = new_errors

        try:
            with open(LOG_PATH, "a") as f:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[field_monitor] 写日志失败: {e}", flush=True)

        time.sleep(SAMPLE_INTERVAL)


if __name__ == "__main__":
    main()
