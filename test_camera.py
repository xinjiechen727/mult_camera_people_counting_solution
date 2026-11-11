#!/usr/bin/env python3
"""
海康 NVR · 14路 RTSP 子码流连通性压测工具
用法：python3 test_camera.py
"""
import json
import os, time, sys
import cv2

# 防死锁超时：3 秒（单位微秒）
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;3000000"

# ── NVR 连接配置（只从本地config.json读取，不在源码保存密码）─────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.getenv("CONFIG_PATH", os.path.join(BASE_DIR, "config.json"))
try:
    with open(CONFIG_PATH, encoding="utf-8") as config_file:
        CONFIG = json.load(config_file)
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"无法读取{CONFIG_PATH}: {exc}")

NVR = CONFIG.get("nvr", {})
NVR_IP = NVR.get("ip", "")
NVR_PORT = int(NVR.get("port", 554))
USERNAME = NVR.get("username", "")
PASSWORDS = NVR.get("passwords", [])
N_CH = len(CONFIG.get("channels", []))

if not NVR_IP or not USERNAME or not PASSWORDS or N_CH == 0:
    raise SystemExit("config.json中的NVR账号、密码或通道配置不完整")

# ─────────────────────────────────────────────────────────────────────────────

def rtsp_url(ch: int, password: str) -> str:
    """海康子码流 URL：/Streaming/Channels/{ch:02d}2"""
    return (f"rtsp://{USERNAME}:{password}@{NVR_IP}:{NVR_PORT}"
            f"/Streaming/Channels/{ch:02d}2")


def test_channel(ch: int) -> dict:
    """
    尝试连接通道 ch，返回结果字典。
    主密码失败时自动切换备用密码。
    """
    for pwd in PASSWORDS:
        url = rtsp_url(ch, pwd)
        t0  = time.perf_counter()
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)

        if not cap.isOpened():
            cap.release()
            continue

        ok, frame = cap.read()
        latency_ms = (time.perf_counter() - t0) * 1000
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()

        if ok and frame is not None:
            return {
                "ch": ch, "ok": True,
                "url": url, "pwd_used": pwd,
                "res": f"{w}×{h}",
                "fps": fps,
                "latency_ms": latency_ms,
            }

    return {"ch": ch, "ok": False, "url": rtsp_url(ch, PASSWORDS[0])}


def main():
    SEP  = "═" * 66
    SEP2 = "─" * 66

    print(f"\n  {SEP}")
    print(f"  ◆  海康 NVR  RTSP 子码流连通性压测")
    print(f"  ◆  目标：{NVR_IP}:{NVR_PORT}   通道数：{N_CH}")
    print(f"  {SEP}\n")

    results   = []
    fail_list = []

    for ch in range(1, N_CH + 1):
        tag = f"[通道 {ch:02d}]"
        print(f"  {tag}  测试中... ", end="", flush=True)

        r = test_channel(ch)
        results.append(r)

        if r["ok"]:
            fps_str = f"{r['fps']:.0f}fps" if r["fps"] > 0 else "fps未知"
            print(f"✓  {r['res']} @ {fps_str}   延迟 {r['latency_ms']:.0f} ms"
                  + (f"  [备用密码]" if r["pwd_used"] != PASSWORDS[0] else ""))
        else:
            fail_list.append(ch)
            print("✗  连接失败（两组密码均无效）")

    ok_count = sum(1 for r in results if r["ok"])

    print(f"\n  {SEP2}")
    print(f"  汇总：成功 {ok_count}/{N_CH} 路", end="")
    if fail_list:
        print(f"   |   失败通道：{fail_list}")
    else:
        print("   ✓ 全部通道正常")
    print(f"  {SEP}\n")

    if fail_list:
        print("  [建议] 失败通道请核查：")
        print("    · NVR 通道是否启用并有摄像头接入")
        print("    · 防火墙是否放通 RTSP 554 端口")
        print("    · 用 VLC 手动验证 URL：")
        for ch in fail_list:
            print(f"      {rtsp_url(ch, PASSWORDS[0])}")
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
