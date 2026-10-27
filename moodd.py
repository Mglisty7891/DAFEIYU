#!/usr/bin/env python3
"""心情/精力守护：定期衰减 + 从桥接活动日志推断事件 + 渲染成提示词用的一行。

产物：$DAFEIYU_CHAT_STATE/mood.txt（聊天侧每次唤醒读它；默认 data/chat-state）
区间：每 60 秒一次；无 QQ 活动时只做自然衰减。
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import paths  # noqa: E402
from core.mood import Mood  # noqa: E402
from core.needs import Needs  # noqa: E402

STATE = paths.MOOD_STATE
NEEDS_PATH = paths.NEEDS_STATE
PIDFILE = os.environ.get("DAFEIYU_MOODD_PID") or "/tmp/moodd.pid"
OUT = paths.MOOD_OUT
ACTIVITY = paths.ACTIVITY_LOG
LOG = "/tmp/moodd.log"
INTERVAL = 60

POS = ("谢谢", "厉害", "牛", "可爱", "喜欢", "好耶", "赞", "哈哈", "笑死")
NEG = ("滚", "闭嘴", "烦", "垃圾", "傻", "别烦", "闭嘴", "恶心")


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


CURSOR = paths.MOOD_CURSOR


def _load_cursor() -> int:
    try:
        with open(CURSOR) as f:
            return int(json.load(f).get("pos") or 0)
    except Exception:
        return -1  # -1 = 第一次运行，直接跳到文件末尾，不把历史当新事件


def _save_cursor(pos: int) -> None:
    try:
        with open(CURSOR, "w") as f:
            json.dump({"pos": pos}, f)
    except Exception:
        pass


def new_activity() -> list[str]:
    """只返回**上次读取之后新增**的日志行。

    早期版本按「时间戳 + 今天日期」过滤，会把昨天的日志误判成今天的
    （日志里只有 HH:MM:SS，没有日期），结果是旧消息被反复计成新事件。
    改成字节游标：位置只前进，历史一律不算。
    """
    try:
        size = os.path.getsize(ACTIVITY)
    except Exception:
        return []
    pos = _load_cursor()
    if pos < 0 or pos > size:
        _save_cursor(size)
        return []
    if pos == size:
        return []
    try:
        with open(ACTIVITY, "rb") as f:
            f.seek(pos)
            data = f.read().decode("utf-8", "replace")
    except Exception:
        return []
    _save_cursor(size)
    # 只保留完整行（末尾可能是半行）
    lines = [ln for ln in data.splitlines() if ln.startswith("[")]
    return lines


def infer_events(lines: list[str]) -> dict[str, int]:
    """粗粒度从日志文本推断事件数（够用即可，不做 NLP）。"""
    events = {"chat": 0, "praise": 0, "insult": 0, "burst": 0, "ignored": 0, "late": 0}
    for line in lines:
        body = line[11:] if len(line) > 11 else line
        if "接收 <-" in body or "消息已入未读" in body or "收到" in body:
            events["chat"] += 1
        if any(w in body for w in POS):
            events["praise"] += 1
        if any(w in body for w in NEG):
            events["insult"] += 1
        if "工具统一发送：成功" in body:
            events["chat"] += 0
    hour = time.localtime().tm_hour
    if events["chat"] and (hour >= 23 or hour < 6):
        events["late"] = events["chat"]
    if events["chat"] >= 20:
        events["burst"] = 1
    return events


def already_running() -> int | None:
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except Exception:
        return None


def main() -> int:
    other = already_running()
    if other and other != os.getpid():
        log(f"已有实例在跑（pid={other}），退出")
        return 0
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

    mood = Mood(STATE)
    needs = Needs(NEEDS_PATH)
    last_seen = 0
    log("心情守护启动")
    while True:
        try:
            now = time.time()
            lines = new_activity()
            # 距上次 tick 的时长（用于需求缺口推进）
            last_ts = float(mood.state.get("updated_at") or now)
            hours = max(0.0, (now - last_ts) / 3600.0)
            # 空闲时长：活动日志最后一条距今多久
            idle_hours = (now - last_seen) / 3600.0 if last_seen else hours
            mood.decay(now=now, idle_hours=idle_hours)
            events = infer_events(lines)
            for name, count in events.items():
                if count:
                    mood.nudge(name, count if name != "burst" else 1)
                    # 需求满足：聊天/被夸补社交，探索补好奇，闲着补休息
                    if name in ("chat", "praise"):
                        needs.satisfy("chat", min(3, count) / 3.0)
                    elif name == "burst":
                        needs.satisfy("chat", 1.0)
            needs.pass_time(hours, sleeping=(idle_hours >= 2.0))
            dm, de = needs.pressure(hours)
            mood.state["mood"] = max(-1.0, min(1.0, mood.state["mood"] + dm))
            mood.state["energy"] = max(0.0, min(100.0, mood.state["energy"] + de))
            needs.save()
            if lines:
                last_seen = now
            mood.save()
            hint = needs.render_hint()
            line = mood.render() + (f"　内在：{hint}。" if hint else "")
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT + ".tmp", "w") as f:
                f.write(line)
            os.replace(OUT + ".tmp", OUT)
        except Exception as e:  # noqa: BLE001
            log(f"循环异常：{e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
