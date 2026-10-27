"""需求缺口模型：让情绪有"内生来源"，而不是只对外部事件做加减。

核心思路（与动机系统同源，但只保留最小必要）：
- 每个需求有一个**满意度** level（0..100）和一个**期望** target。
- 满意度随时间自然下降 → 需求缺口 deficit = max(0, target - level) 变大。
- 缺口不靠事件也会"推"情绪：没社交会闷、没新鲜事会烦、没休息会累。
  这就是「自己的情绪」的雏形——不是别人给了什么，而是**自己想要什么而没得到**。

边界：只产出 mood/energy 的漂移量，不参与事实判断、不参与检索、不影响"要不要回答"。
"""
from __future__ import annotations

import json
import os

# target = 期望值；decay = 满意度每小时自然下降；satisfy = 一次满足事件的回升量
NEEDS = {
    "social":    {"target": 60.0, "decay": 6.0, "satisfy": 8.0, "label": "社交"},
    "curiosity": {"target": 55.0, "decay": 4.5, "satisfy": 7.0, "label": "新鲜感"},
    "rest":      {"target": 65.0, "decay": 3.0, "satisfy": 9.0, "label": "休息"},
}

# 缺口如何推动状态（每小时）
MOOD_PER_DEFICIT = 0.00025    # 每点缺口每小时拉动心情（调小：一夜不该掉到底）
ENERGY_PER_REST_DEFICIT = 0.02  # 休息缺口对精力的额外消耗


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


class Needs:
    def __init__(self, path: str):
        self.path = path
        self.levels = {k: 50.0 for k in NEEDS}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path) as f:
                data = json.load(f)
            for k in NEEDS:
                if k in data:
                    self.levels[k] = _clamp(float(data[k]))
        except Exception:
            pass

    def save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({k: round(v, 2) for k, v in self.levels.items()}, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    # ── 时间与事件 ────────────────────────────────────────
    def pass_time(self, hours: float, sleeping: bool = False) -> None:
        """满意度自然下降 → 需求缺口变大。

        sleeping=True（长时间没人说话）时，休息满意度**回升**而不是下降：
        它确实在"歇着"，不该一边歇着一边累积"没休息够"的缺口。
        """
        if hours <= 0:
            return
        for k, spec in NEEDS.items():
            if k == "rest" and sleeping:
                self.levels[k] = _clamp(self.levels[k] + 12.0 * hours)
            else:
                self.levels[k] = _clamp(self.levels[k] - spec["decay"] * hours)

    def satisfy(self, event: str, strength: float = 1.0) -> None:
        """满足事件：聊天满足社交，探索满足好奇，空闲/休息满足休息。"""
        mapping = {
            "chat": "social",
            "learn": "curiosity",
            "search": "curiosity",
            "rest": "rest",
            "idle": "rest",
        }
        key = mapping.get(event)
        if not key:
            return
        self.levels[key] = _clamp(self.levels[key] + NEEDS[key]["satisfy"] * strength)

    # ── 缺口 → 状态漂移 ───────────────────────────────────
    def deficits(self) -> dict[str, float]:
        return {k: max(0.0, NEEDS[k]["target"] - self.levels[k]) for k in NEEDS}

    def pressure(self, hours: float) -> tuple[float, float]:
        """返回 (心情漂移, 精力漂移)。缺口越大，情绪越往下走。"""
        d = self.deficits()
        mood_delta = -MOOD_PER_DEFICIT * (d["social"] + d["curiosity"] + 0.5 * d["rest"]) * hours
        energy_delta = -ENERGY_PER_REST_DEFICIT * d["rest"] * hours
        return mood_delta, energy_delta

    def dominant(self) -> tuple[str, float] | None:
        """当前最缺的那个（用于语气提示，不用来说话内容）。"""
        d = self.deficits()
        key = max(d, key=d.get)
        return (key, d[key]) if d[key] >= 15 else None

    def render_hint(self) -> str:
        """一行"内在倾向"，只给语气，不要求说出来。"""
        top = self.dominant()
        if not top:
            return ""
        key, amount = top
        phrase = {
            "social": "有点闷（想有人说说话）",
            "curiosity": "有点无聊（想要点新鲜事）",
            "rest": "有点撑（想歇一会儿）",
        }[key]
        level = "轻" if amount < 30 else "明显"
        return f"{phrase}，程度{level}"
