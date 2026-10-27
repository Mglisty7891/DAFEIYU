"""路径解析：所有位置都可由环境变量覆盖，默认值取自仓库自身。

开放源码时最忌讳把作者机器上的绝对路径写死，这里统一收口。
"""
from __future__ import annotations

import os

# 仓库根目录：core/ 的上一级
HOME = os.environ.get("DAFEIYU_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("DAFEIYU_DATA") or os.path.join(HOME, "data")

# 记忆库 / 状态文件
MEMORY_DB = os.environ.get("DAFEIYU_DB") or os.path.join(DATA_DIR, "memory.db")
MOOD_STATE = os.environ.get("DAFEIYU_MOOD_STATE") or os.path.join(DATA_DIR, "mood.json")
NEEDS_STATE = os.environ.get("DAFEIYU_NEEDS_STATE") or os.path.join(DATA_DIR, "needs.json")
MOOD_CURSOR = os.environ.get("DAFEIYU_MOOD_CURSOR") or os.path.join(DATA_DIR, "mood-cursor.json")

# 与「聊天侧」的交接点（可选）：情绪层把一行状态写进这个目录，由聊天侧读取后注入提示词。
# 不接聊天侧时，这些文件不产生，情绪层照常自用。
CHAT_STATE_DIR = os.environ.get("DAFEIYU_CHAT_STATE") or os.path.join(DATA_DIR, "chat-state")
MOOD_OUT = os.environ.get("DAFEIYU_MOOD_OUT") or os.path.join(CHAT_STATE_DIR, "mood.txt")
ACTIVITY_LOG = os.environ.get("DAFEIYU_ACTIVITY_LOG") or os.path.join(CHAT_STATE_DIR, "activity.log")


def render_hint_for_chat() -> str:
    """给聊天侧的一行状态：格式稳定，便于对方用正则取「精力 N/100」。"""
    return "（由 moodd 写入 mood.txt）"


def ensure_dirs() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
