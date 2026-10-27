#!/usr/bin/env python3
"""大肥鱼记忆系统 · 命令行入口。

用法：
  python3 cli.py add "用户说他喜欢喝冰美式" --source owner --level important --tags 饮食,偏好
  python3 cli.py search "他喝什么咖啡" --top 5
  python3 cli.py list
  python3 cli.py stats
  python3 cli.py forget            # 时间衰减 + 容量淘汰
  python3 cli.py consolidate       # 相似记忆合并
  python3 cli.py maintain          # 修复图结构
  python3 cli.py demo              # 跑一遍完整闭环
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.memory import Memory  # noqa: E402

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "memory.db")


def fmt(item: dict) -> str:
    tags = ",".join(item.get("tags") or [])
    return (
        f"[{item['score']:.3f}] ({item['region']}/{item['level']}) "
        f"{item['text']}"
        + (f"  #{tags}" if tags else "")
        + f"  · 卦象{format(item.get('code', 0), '06b')}"
        + f"  · cos={item['detail']['cos']} lex={item['detail']['lex']} w={item['detail']['w']}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="大肥鱼记忆系统")
    ap.add_argument("--db", default=DB)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="写入一条记忆")
    a.add_argument("text")
    a.add_argument("--region", default="general")
    a.add_argument("--source", default="other", choices=["owner", "other"])
    a.add_argument("--level", default="normal", choices=["core", "important", "normal"])
    a.add_argument("--tags", default="")
    a.add_argument("--arousal", type=float, default=0.0)

    s = sub.add_parser("search", help="检索")
    s.add_argument("query")
    s.add_argument("--top", type=int, default=8)
    s.add_argument("--temp", default="normal", choices=["focused", "normal", "diffuse"])
    s.add_argument("--region", default=None)

    sub.add_parser("list", help="列出全部记忆")
    sub.add_parser("stats", help="统计")
    sub.add_parser("forget", help="触发一次遗忘")
    sub.add_parser("consolidate", help="触发一次巩固")
    sub.add_parser("maintain", help="修复图结构")
    sub.add_parser("demo", help="跑一遍完整闭环")

    args = ap.parse_args()
    mem = Memory(args.db)

    if args.cmd == "add":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        res = mem.encode(
            args.text,
            region=args.region,
            source=args.source,
            tags=tags,
            level=args.level,
            arousal=args.arousal,
        )
        print(json.dumps(res, ensure_ascii=False))
        return 0

    if args.cmd == "search":
        hits = mem.retrieve(
            args.query, top_k=args.top, temperature=args.temp, region_hint=args.region
        )
        if not hits:
            print("没有命中。")
            return 0
        for h in hits:
            print(fmt(h))
        mem.mark_access([h["id"] for h in hits])
        return 0

    if args.cmd == "list":
        for n in mem.store.nodes(("hot", "cold", "consolidated")):
            print(f"({n['state']:12s}) ({n['region']}/{n['level']}) {n['text']}")
        return 0

    if args.cmd == "stats":
        print(json.dumps(mem.stats(), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "forget":
        print(json.dumps(mem.forget_tick(), ensure_ascii=False))
        return 0

    if args.cmd == "consolidate":
        print(json.dumps(mem.consolidate(), ensure_ascii=False))
        return 0

    if args.cmd == "maintain":
        print(json.dumps(mem.maintain(), ensure_ascii=False))
        return 0

    if args.cmd == "demo":
        return run_demo(mem)

    return 1


def run_demo(mem: Memory) -> int:
    print("=== 1. 写入（不同来源，权重不同）===")
    seeds = [
        ("用户最近在学 Rust，主要想写命令行工具", "owner", "important", ["编程", "Rust"]),
        ("用户不喜欢太甜的咖啡，一般喝冰美式", "owner", "normal", ["饮食"]),
        ("用户有个朋友叫阿岚，做前端开发", "owner", "normal", ["社交"]),
        ("今天把项目迁移到了新的构建流程", "other", "normal", ["部署"]),
        ("同事说 Rust 的借用检查太劝退", "other", "normal", ["编程", "闲聊"]),
        ("用户说 Rust 的所有权机制一开始很难理解", "owner", "normal", ["编程", "Rust"]),
        ("用户又说 Rust 所有权要花时间才能习惯", "owner", "normal", ["编程", "Rust"]),
    ]
    for text, source, level, tags in seeds:
        r = mem.encode(text, source=source, level=level, tags=tags)
        print(f"  + {text[:24]}… -> w0={r.get('w0'):.2f} merged={r['merged']}")

    print("\n=== 2. 检索（三路融合 + 多样性）===")
    for q in ("他学什么语言", "咖啡口味", "Rust"):
        print(f"  Q: {q}")
        for h in mem.retrieve(q, top_k=3):
            print("    " + fmt(h))

    print("\n=== 3. 巩固（相似记忆合并成抽象）===")
    memo = mem.encode("Rust 学习进度：已经写完第一个 CLI，正在看所有权", source="owner", level="normal", tags=["编程", "Rust"])
    print("  新写入:", memo)
    print("  合并结果:", json.dumps(mem.consolidate(), ensure_ascii=False))

    print("\n=== 4. 遗忘（模拟 40 天后）===")
    future = mem.store.now_ms() + 40 * 86400 * 1000
    print("  衰减结果:", json.dumps(mem.forget_tick(now=future), ensure_ascii=False))
    print("  统计:", json.dumps(mem.stats(), ensure_ascii=False))

    print("\n=== 5. 维护 ===")
    print("  ", json.dumps(mem.maintain(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
