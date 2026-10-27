"""大肥鱼系统 · 配置常数。

所有可调参数集中在这里，对应《技术术语与概念文档 v2.0》里的公式。
"""

# ── 记忆子系统 ────────────────────────────────────────────────
# 写入权重 w0 = w_base · (1 + surprise)
W_BASE_OWNER = 4.0      # 主人来源
W_BASE_OTHER = 1.5      # 其他来源

# 闪关灯记忆（flash）：不合并、不淘汰、检索优先
FLASH_REGION = "flash"
FLASH_REGION_BOOST = 1.45
MATCH_REGION_BOOST = 1.35
NEUTRAL_REGION_BOOST = 1.0

# 时间衰减 w(t) = w0 · exp(-Δt / τ)，τ 按等级
TAU_DAYS = {"core": 3650, "important": 30, "normal": 7}

# 检索融合 score = 0.65 · cos + 0.35 · lex
W_COS = 0.65
W_LEX = 0.35

# 回忆温度 T（由驱力/专注度决定）jitter = 1 + U(-0.175, 0.175) · T
JITTER = 0.175
TEMPERATURE = {"focused": 0.55, "normal": 1.0, "diffuse": 1.45}
DEFAULT_TEMPERATURE = "normal"

# 卦象多样性：同卦节点按 0.86 / 0.72 递减
DIVERSITY_DECAY = (0.86, 0.72)

# 去重：Jaccard ≥ 0.60 且包含度 ≥ 0.78 且（同 region 或共享 tag）
DEDUPE_JACCARD = 0.60
DEDUPE_CONTAINMENT = 0.78

# 容量：热库上限
HOT_CAPACITY = 5000

# 巩固：相似度阈值（低于此值不合并）
CONSOLIDATE_SIM = 0.25   # 内容词 overlap 系数阈值

# 反刍抑制：短窗口内反复召回收降权
RUMINATION_WINDOW_SEC = 600
RUMINATION_PENALTY = 0.75

# 检索默认返回条数
DEFAULT_TOP_K = 8

# ── 身份 ──────────────────────────────────────────────────────
OWNER_REGIONS = ("owner",)   # 主人来源的 region 标记（文档里按 QQ 号判定，这里先留接口）
