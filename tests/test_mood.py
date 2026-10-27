#!/usr/bin/env python3
"""状态层自测：python3 tests/test_mood.py"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.mood import Mood, jitter_pace  # noqa: E402

PASS = FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {extra}")


def fresh() -> Mood:
    return Mood(tempfile.mktemp(suffix=".json"))


def main() -> int:
    print("[初始化]")
    m = fresh()
    check("默认精力 70", abs(m.state["energy"] - 70) < 1e-6)
    check("时间戳已补", m.state["updated_at"] > 0)

    print("[边界]")
    m.nudge("praise", 100)
    check("心情上限 1", m.state["mood"] <= 1.0 + 1e-9, str(m.state["mood"]))
    m.nudge("insult", 200)
    check("心情下限 -1", m.state["mood"] >= -1.0 - 1e-9, str(m.state["mood"]))

    print("[衰减与恢复]")
    m2 = fresh()
    e0 = m2.state["energy"]
    m2.decay(now=time.time() + 3 * 3600, idle_hours=3)
    check("空闲后精力恢复", m2.state["energy"] > e0, f"{e0} -> {m2.state['energy']}")
    m3 = fresh()
    m3.nudge("praise", 5)          # mood 拉高
    hi = m3.state["mood"]
    m3.decay(now=time.time() + 4 * 3600, idle_hours=0)
    check("心情向 0 回归", abs(m3.state["mood"]) < abs(hi), f"{hi} -> {m3.state['mood']}")

    print("[事件]")
    m4 = fresh()
    m4.nudge("insult", 3)
    check("被怼心情下降", m4.state["mood"] < 0.1)
    m5 = fresh()
    m5.nudge("burnt", 1) if False else None
    m5.nudge("late", 6)
    check("熬夜掉精力", m5.state["energy"] < 70, str(m5.state["energy"]))

    print("[渲染]")
    m6 = fresh()
    m6.state["energy"] = 20          # 直接设定低精力，避免被 nudge 的恢复量抵掉
    m6.nudge("insult", 6)
    line = m6.render()
    check("含状态标记", "【你的状态】" in line)
    check("含不影响判断的约束", "不影响你判断事实" in line)
    check("低精力时提示放慢", "慢一点" in line, line)
    m7 = fresh()
    m7.nudge("praise", 6)
    hi_line = m7.render()
    check("高心情时语气变活", ("活泼" in hi_line) or ("话多" in hi_line), hi_line)

    print("[节奏倍率]")
    m8 = fresh()
    m8.state["energy"] = 100
    fast = jitter_pace(m8)
    m8.state["energy"] = 10
    slow = jitter_pace(m8)
    check("有劲更快", fast < slow, f"{fast:.2f} vs {slow:.2f}")
    check("倍率在合理区间", 0.6 <= fast <= 1.8 and 0.6 <= slow <= 1.8)

    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
