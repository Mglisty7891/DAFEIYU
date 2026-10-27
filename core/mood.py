"""轻量状态层：精力 + 心情两个标量。

设计边界（重要）：
- **只影响表达**：回得快不快、话多不多、语气冷不冷。
- **绝不参与事实判断**：不带它做检索、不用它改结论、不因心情而编造。
- 状态由事件驱动、随时间自然衰减，不需要模型主动查询。

坐标：
- energy: 0..100。高=有劲，低=蔫。随时间下降，休息回升。
- mood:   -1..+1。负=冷淡/烦，正=活跃/软。向 0 回归（稳态），被事件推动。
"""
from __future__ import annotations

import json
import math
import os
import random
import time

DEFAULTS = {
    "energy": 70.0,
    "mood": 0.1,
    "updated_at": 0,
}

# 每小时自然衰减/恢复速率
ENERGY_DECAY_PER_HOUR = 3.0      # 清醒状态下的自然消耗
ENERGY_RECOVER_PER_HOUR = 6.0    # 长时间无消息时的恢复
MOOD_HOMEOSTASIS_PER_HOUR = 0.12  # 心情向 0 回归

# 事件对状态的影响
NUDGES = {
    "praise":   {"mood": +0.18, "energy": +2},
    "insult":   {"mood": -0.22, "energy": -3},
    "chat":     {"mood": +0.02, "energy": -1},   # 每条正常聊天
    "burst":    {"mood": -0.05, "energy": -4},   # 短时间刷屏
    "ignored":  {"mood": -0.06, "energy": 0},    # 说了没人理
    "late":     {"mood": -0.03, "energy": -5},   # 深夜聊天
    "rest":     {"mood": +0.05, "energy": +8},   # 被允许休息
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class Mood:
    def __init__(self, path: str):
        self.path = path
        self.state = dict(DEFAULTS)
        self._load()
        # 首次创建时把时间戳补上，否则第一次 decay 会因为 last<=0 直接跳过，
        # 状态永远停在初始值（实测踩过）。
        if not self.state.get("updated_at"):
            self.state["updated_at"] = time.time()
            self.save()

    def _load(self) -> None:
        try:
            with open(self.path) as f:
                data = json.load(f)
            self.state.update({k: data[k] for k in DEFAULTS if k in data})
        except Exception:
            pass

    def save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def decay(self, now: float | None = None, idle_hours: float = 0.0) -> None:
        """按流逝时间更新。idle_hours 由调用方给出（多久没消息了）。"""
        now = now or time.time()
        last = float(self.state.get("updated_at") or 0)
        if last <= 0:
            self.state["updated_at"] = now
            return
        hours = max(0.0, (now - last) / 3600.0)
        if hours <= 0:
            return
        # 精力：有消息时消耗、长时间空闲时恢复
        if idle_hours >= 2.0:
            rate = ENERGY_RECOVER_PER_HOUR * min(1.0, idle_hours / 6.0)
        else:
            rate = -ENERGY_DECAY_PER_HOUR
        self.state["energy"] = _clamp(self.state["energy"] + rate * hours, 0, 100)
        # 心情：向 0 **比例**回归（指数衰减）。
        # 早期用的是"每小时减固定量"，那会把任何轻微负值直接压回 0，
        # 于是"没社交导致的闷"永远显示不出来（实测 -0.03）。改比例后，
        # 需求缺口能把心情稳定在某个负值上，而不是被削平。
        self.state["mood"] = _clamp(
            self.state["mood"] * math.exp(-MOOD_HOMEOSTASIS_PER_HOUR * hours), -1, 1
        )
        self.state["updated_at"] = now

    def nudge(self, event: str, times: int = 1) -> None:
        d = NUDGES.get(event)
        if not d:
            return
        self.state["energy"] = _clamp(self.state["energy"] + d["energy"] * times, 0, 100)
        self.state["mood"] = _clamp(self.state["mood"] + d["mood"] * times, -1, 1)

    # ── 渲染：给提示词用的一行 ──────────────────────────────
    def band(self) -> dict:
        e, m = self.state["energy"], self.state["mood"]
        if e >= 70:
            energy_band, pace = "有精神", "正常偏快"
        elif e >= 40:
            energy_band, pace = "一般", "正常"
        else:
            energy_band, pace = "蔫", "慢一点、句子更短"
        if m <= -0.35:
            mood_band, tone = "冷淡/烦", "话少、语气平、不主动玩梗"
        elif m <= 0.05:
            mood_band, tone = "平静", "正常"
        elif m <= 0.45:
            mood_band, tone = "不错", "可以活泼一点"
        else:
            mood_band, tone = "很好", "话多、愿意接梗、语气软"
        return {"energy": energy_band, "pace": pace, "mood": mood_band, "tone": tone}

    def render(self) -> str:
        b = self.band()
        return (
            f"【你的状态】精力 {self.state['energy']:.0f}/100（{b['energy']}），"
            f"心情 {self.state['mood']:+.2f}（{b['mood']}）。"
            f"→ 节奏：{b['pace']}；语气：{b['tone']}。"
            "（这只影响你怎么说，不影响你判断事实；别把状态念出来，也不要拿它当借口敷衍。）"
        )


# 节奏倍率的**唯一公式**：桥接（src/bridge.js 的 moodPaceFactor）与本文件必须一致。
# 能量 100 → ×0.8（更快）；能量 0 → ×1.5（更慢）。范围 [0.7, 1.6]。
PACE_BASE = 1.5
PACE_SLOPE = 0.7
PACE_MIN = 0.7
PACE_MAX = 1.6


def jitter_pace(mood: "Mood") -> float:
    """回复延迟倍率：有精神更快，蔫了更慢。公式与桥接保持一致。"""
    e = mood.state["energy"]
    return _clamp(PACE_BASE - (e / 100.0) * PACE_SLOPE, PACE_MIN, PACE_MAX)
