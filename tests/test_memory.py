#!/usr/bin/env python3
"""记忆子系统自测（不依赖 pytest，直接 python3 tests/test_memory.py）。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import text as T
from core.memory import Memory  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {extra}")


def fresh() -> Memory:
    path = tempfile.mktemp(suffix=".db")
    return Memory(path)


def test_text() -> None:
    print("[text]")
    check("code6 落在 0..63", all(0 <= T.code6(f"文本{i}") <= 63 for i in range(200)))
    check("code6 稳定", T.code6("同一段话") == T.code6("同一段话"))
    check("jaccard 自比=1", abs(T.jaccard("abc", "abc") - 1.0) < 1e-9)
    check("containment 偏置正确", T.containment("abc", "abcdef") > T.containment("abcdef", "abc"))
    ct = T.content_tokens("主人说 Rust 所有权很难理解")
    check("内容词含英文与二元组", "rust" in ct and "所有" in ct and "的" not in ct)
    check("overlap 系数", abs(T.overlap_coefficient({"a", "b"}, {"a", "b", "c"}) - 1.0) < 1e-9)


def test_encode() -> None:
    print("[编码]")
    m = fresh()
    r1 = m.encode("主人喜欢喝冰美式", source="owner", tags=["饮食"])
    r2 = m.encode("今天天气不错", source="other")
    check("首条 surprise=1", abs(r1["surprise"] - 1.0) < 1e-9, str(r1))
    check("主人权重更高", r1["w0"] > r2["w0"], f"{r1['w0']} vs {r2['w0']}")
    check("完全相同的文本会被去重", m.encode("主人喜欢喝冰美式", source="owner")["merged"] is True)
    check("去重后不新增节点", m.store.count() == 2, str(m.store.count()))
    # 闪光灯：高唤醒
    r3 = m.encode("被骂了一顿，情绪很激动", source="owner", arousal=0.95)
    node = m.store.get_node(r3["id"])
    check("高唤醒进 flash", node["region"] == "flash", node["region"])


def test_retrieve() -> None:
    print("[检索]")
    m = fresh()
    m.encode("主人最近在学 Rust，想写命令行工具", source="owner", tags=["编程", "Rust"])
    m.encode("主人喜欢喝冰美式，不喜欢太甜", source="owner", tags=["饮食"])
    m.encode("群友在聊显卡价格", source="other", tags=["闲聊"])
    hits = m.retrieve("Rust 怎么学", top_k=3)
    check("检索非空", len(hits) > 0)
    check("Rust 相关排第一", "Rust" in hits[0]["text"], hits[0]["text"])
    check("分数降序", all(hits[i]["score"] >= hits[i + 1]["score"] for i in range(len(hits) - 1)))
    hits2 = m.retrieve("喝什么", top_k=1)
    check("饮食命中", "美式" in hits2[0]["text"], hits2[0]["text"]) if hits2 else check("饮食命中", False)
    # 温度只影响抖动幅度：focused(0.55) 的方差应明显小于 diffuse(1.45)
    def spread(temp: str, n: int = 40) -> float:
        vals = [m.retrieve("Rust", top_k=1, temperature=temp)[0]["score"] for _ in range(n)]
        mean = sum(vals) / len(vals)
        return max(vals) - min(vals)

    s_focused, s_diffuse = spread("focused"), spread("diffuse")
    check("focused 抖动小于 diffuse", s_focused < s_diffuse, f"{s_focused:.4f} vs {s_diffuse:.4f}")


def test_diversity() -> None:
    print("[多样性]")
    m = fresh()
    items = [
        {"id": "a", "score": 1.0, "code": 7},
        {"id": "b", "score": 0.99, "code": 7},
        {"id": "c", "score": 0.90, "code": 9},
    ]
    out = m._diversify([dict(x) for x in items], top_k=3)
    # b 与 a 同卦：0.99 被降到 0.99*0.86=0.851 < 0.90，所以应排到 c 之后
    check("同卦第二条被降权到后面", out[1]["id"] == "c", str([o["id"] for o in out]))


def test_forget() -> None:
    print("[遗忘]")
    m = fresh()
    n = m.encode("一条普通记忆", level="normal")
    f = m.encode("一条重要记忆", level="important")
    fl = m.encode("闪光灯记忆", arousal=1.0)
    future = m.store.now_ms() + 40 * 86400 * 1000
    stats = m.forget_tick(now=future)
    check("普通记忆下沉冷库", m.store.get_node(n["id"])["state"] in ("cold", "evicted"))
    check("闪光灯不淘汰", m.store.get_node(fl["id"])["state"] != "evicted", m.store.get_node(fl["id"])["state"])
    check("统计有变化", stats["moved_cold"] >= 1, str(stats))


def test_consolidate() -> None:
    print("[巩固]")
    m = fresh()
    m.encode("主人说 Rust 的所有权机制一开始很难理解", source="owner", tags=["编程"])
    m.encode("主人又说 Rust 所有权要花时间才能习惯", source="owner", tags=["编程"])
    res = m.consolidate()
    check("产生一条抽象记忆", len(res) == 1, str(res))
    check("成员被标记 consolidated", m.store.count("consolidated") == 2, str(m.store.count("consolidated")))
    abs_id = res[0]["abstract"] if res else None
    check("抽象节点存在", abs_id is not None and m.store.get_node(abs_id) is not None)


def test_maintain() -> None:
    print("[维护]")
    m = fresh()
    n1 = m.encode("甲乙丙丁", source="other")
    m.store.upsert_edge(n1["id"], n1["id"], "cooccur", 1.0)      # 自环
    m.store.upsert_edge(n1["id"], "不存在的节点", "cooccur", 1.0)  # 悬空
    fixed = m.maintain()
    check("自环被清", fixed["self_loop"] == 1, str(fixed))
    check("悬空边被清", fixed["dangling"] == 1, str(fixed))
    check("维护后边表干净", len(m.store.all_edges()) == 0, str(m.store.all_edges()))


def main() -> int:
    test_text()
    test_encode()
    test_retrieve()
    test_diversity()
    test_forget()
    test_consolidate()
    test_maintain()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
