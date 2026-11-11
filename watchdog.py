"""
看门狗：独立进程，定期检查 yolo-detector 的心跳文件是否新鲜。
心跳由 main.py 的主循环（_write_heartbeat("main")）和 reCamera 快速循环
（_write_heartbeat("recam")）在每轮跑完后写入 /tmp/yolo_heartbeat_*。
如果某个心跳长时间没更新（说明对应循环卡死/进程僵死），自动 pm2 restart。

设计原则：看门狗本身必须极简、无网络依赖、不会自己卡死。
"""
import os
import shutil
import subprocess
import time

PM2_PROCESS_NAME = "yolo-detector"

# 心跳文件 -> (期望更新间隔, 判定卡死的容忍倍数阈值秒数)
# main 循环默认 20 秒一轮，recam 循环 1 秒一轮；阈值留足够余量避免误判
HEARTBEATS = {
    "main":  ("/tmp/yolo_heartbeat_main", 90),
    "recam": ("/tmp/yolo_heartbeat_recam", 30),
}

CHECK_INTERVAL   = 15    # 秒，多久检查一次
STARTUP_GRACE    = 90    # 秒，看门狗自身启动后的宽限期（等被监控进程先完成一次初始化）
RESTART_COOLDOWN = 180   # 秒，两次重启之间的最小间隔，防止反复重启抖动

_pm2_bin = shutil.which("pm2") or "pm2"


def _restart_target():
    print(f"  ⚠ 看门狗：检测到心跳超时，正在重启 {PM2_PROCESS_NAME} ...", flush=True)
    try:
        subprocess.run([_pm2_bin, "restart", PM2_PROCESS_NAME], timeout=30, check=False)
        print(f"  ✓ 看门狗：已触发 pm2 restart {PM2_PROCESS_NAME}", flush=True)
    except Exception as e:
        print(f"  ✗ 看门狗：触发重启失败: {e}", flush=True)


def main():
    print(f"  看门狗启动，{STARTUP_GRACE}秒后开始监控心跳文件: "
          f"{', '.join(p for p, _ in HEARTBEATS.values())}", flush=True)
    start = time.time()
    last_restart_at = 0.0

    while True:
        time.sleep(CHECK_INTERVAL)
        now = time.time()
        if now - start < STARTUP_GRACE:
            continue
        if now - last_restart_at < RESTART_COOLDOWN:
            continue

        stale_reasons = []
        for name, (path, max_age) in HEARTBEATS.items():
            try:
                age = now - os.path.getmtime(path)
            except OSError:
                age = None  # 文件还不存在，视为卡死（已过宽限期仍未写出说明进程从未跑通）

            if age is None or age > max_age:
                stale_reasons.append(f"{name}心跳{'缺失' if age is None else f'已过期{age:.0f}秒'}")

        if stale_reasons:
            print(f"  ⚠ 看门狗：{'; '.join(stale_reasons)}", flush=True)
            _restart_target()
            last_restart_at = now
            start = now  # 重启后重新计宽限期，给新进程时间初始化


if __name__ == "__main__":
    main()
