#!/usr/bin/env python3
"""需求缺口模型自测：python3 tests/test_needs.py"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.needs import NEEDS, Needs  # noqa: E402

PASS = FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {extra}")


def fresh() -> Needs:
    return Needs(tempfile.mktemp(suffix=".json"))


def main() -> int:
    print("[初始]")
    n = fresh()
    check("三个需求都有初始值", set(n.levels) == set(NEEDS), str(n.levels))
    check("初始无缺口（50 < target 但不超过阈）", all(0 <= v <= 100 for v in n.deficits().values()))

    print("[时间推动缺口]")
    n2 = fresh()
    before = n2.deficits()["social"]
    n2.pass_time(4)
    after = n2.deficits()["social"]
    check("空闲 4 小时后社交缺口变大", after > before, f"{before:.1f} -> {after:.1f}")

    print("[满足事件]")
    n3 = fresh()
    n3.pass_time(6)
    low = n3.levels["social"]
    n3.satisfy("chat", 1.0)
    check("聊天提升社交满意度", n3.levels["social"] > low, f"{low:.1f} -> {n3.levels['social']:.1f}")
    n4 = fresh()
    l2 = n4.levels["curiosity"]
    n4.satisfy("learn", 1.0)
    check("学习提升好奇满意度", n4.levels["curiosity"] > l2)

    print("[缺口 → 情绪漂移]")
    n5 = fresh()
    n5.pass_time(12)          # 长时间无人理
    dm, de = n5.pressure(1.0)
    check("缺口让心情往下走", dm < 0, f"dm={dm:.4f}")
    check("休息缺口额外消耗精力", de <= 0, f"de={de:.4f}")

    print("[没有事件也有变化（内生性）]")
    n6 = fresh()
    base = n6.levels["social"]
    n6.pass_time(8)
    check("无事件时满意度下降", n6.levels["social"] < base, f"{base:.1f} -> {n6.levels['social']:.1f}")
    check("缺口可被感知", n6.dominant() is not None or n6.deficits()["social"] > 0)

    print("[边界]")
    n7 = fresh()
    for _ in range(50):
        n7.satisfy("chat", 3.0)
    check("满意度上限 100", n7.levels["social"] <= 100.0, str(n7.levels["social"]))
    n8 = fresh()
    n8.pass_time(1000)
    check("满意度下限 0", all(v >= 0 for v in n8.levels.values()), str(n8.levels))
    check("缺口不超过期望值", all(d <= NEEDS[k]["target"] + 1e-6 for k, d in n8.deficits().items()))

    print("[渲染]")
    n9 = fresh()
    n9.pass_time(15)
    hint = n9.render_hint()
    check("有缺口时给出倾向描述", bool(hint), hint)
    check("倾向描述不含命令式要求", "必须" not in hint and "你要" not in hint, hint)

    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
