#!/usr/bin/env python3
"""
客流数据清洗脚本
清除今日测试产生的虚假数据，保留历史累计准确性
"""
import os
import sys
from datetime import date, datetime
from urllib.parse import unquote, urlparse
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "app", ".env"))


def database_config() -> dict:
    parsed = urlparse(os.getenv("DATABASE_URL", ""))
    if parsed.scheme not in ("mysql", "mariadb") or not parsed.hostname:
        raise RuntimeError("请先在app/.env中配置有效的DATABASE_URL")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/"),
    }

def run():
    try:
        import mysql.connector
    except ImportError:
        print("[错误] 请先运行: pip3 install mysql-connector-python --break-system-packages")
        sys.exit(1)

    # autocommit=True：每条语句独立提交，避免与并发写入产生事务冲突
    conn = mysql.connector.connect(**database_config(), autocommit=True)
    cur  = conn.cursor(dictionary=True)
    today = date.today().strftime("%Y-%m-%d")

    # ── 1. 统计今日数据 ──────────────────────────────────────────────────────
    cur.execute("""
        SELECT COUNT(*) AS records,
               COALESCE(MAX(count), 0) AS peak,
               COALESCE(SUM(count), 0) AS total_sum
        FROM person_flow_records
        WHERE DATE(timestamp) = %s
    """, (today,))
    stats = cur.fetchone()
    print(f"\n{'═'*50}")
    print(f"  今日 ({today}) 测试数据统计")
    print(f"  记录条数 : {stats['records']:,}")
    print(f"  峰值人数 : {stats['peak']}")
    print(f"  累计总量 : {stats['total_sum']:,}")
    print(f"{'═'*50}")

    if stats['records'] == 0:
        print("  今日无数据，无需清理。")
        cur.close(); conn.close(); return

    confirm = input("\n  确认删除今日全部测试数据？(yes/no): ").strip().lower()
    if confirm != "yes":
        print("  已取消。")
        cur.close(); conn.close(); return

    # ── 2. 删除今日 person_flow_records（分批删除，防止大表锁定超时）────────
    total_deleted = 0
    while True:
        cur.execute("""DELETE FROM person_flow_records
                       WHERE DATE(timestamp) = %s LIMIT 500""", (today,))
        n = cur.rowcount
        total_deleted += n
        if n == 0:
            break
    deleted_flow = total_deleted

    # ── 3. 删除今日 event_logs ───────────────────────────────────────────────
    cur.execute("DELETE FROM event_logs WHERE DATE(timestamp) = %s", (today,))
    deleted_events = cur.rowcount

    # ── 4. 删除今日 vlm_logs ─────────────────────────────────────────────────
    cur.execute("DELETE FROM vlm_logs WHERE DATE(timestamp) = %s", (today,))
    deleted_vlm = cur.rowcount

    # ── 5. 删除今日 daily_stats ──────────────────────────────────────────────
    cur.execute("DELETE FROM daily_stats WHERE date = %s", (today,))
    deleted_stats = cur.rowcount

    # ── 6. 重置所有房间当前人数为 0 ──────────────────────────────────────────
    cur.execute("UPDATE rooms SET current_count = 0")

    print(f"\n  ✓ person_flow_records 删除 {deleted_flow:,} 条")
    print(f"  ✓ event_logs          删除 {deleted_events:,} 条")
    print(f"  ✓ vlm_logs            删除 {deleted_vlm:,} 条")
    print(f"  ✓ daily_stats         删除 {deleted_stats:,} 条")
    print(f"  ✓ 所有房间人数已归零")

    # ── 7. 输出剩余历史数据摘要 ──────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) AS r, COALESCE(SUM(count),0) AS s FROM person_flow_records")
    remain = cur.fetchone()
    print(f"\n  历史数据剩余: {remain['r']:,} 条 | 历史总客流: {remain['s']:,} 人次")
    print(f"\n{'═'*50}")
    print("  数据清洗完成！大屏刷新后将显示真实历史数据。")
    print(f"{'═'*50}\n")

    cur.close()
    conn.close()

if __name__ == "__main__":
    run()
