"""大肥鱼系统 —— 记忆子系统（Phase 1）。

记忆闭环：编码 → 存储 → 巩固 → 检索 → 遗忘。
离线实现：字符二元组 + TF-IDF 近似语义，接口留好可替换为真 embedding。
"""

from .memory import Memory

__all__ = ["Memory"]
__version__ = "0.1.0"
