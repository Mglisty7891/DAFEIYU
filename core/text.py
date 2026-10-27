"""文本层：分词、相似度、6 位卦象编码。

离线方案（无 embedding 服务）：用
  - 字符二元组（bigram）Jaccard  → 近似"字面相似"
  - TF-IDF 余弦                  → 近似"语义相似"
  - 6 位特征编码                 → 结构化索引 + 检索多样性控制
接口刻意做成「一个相似度函数」，以后接真 embedding 只改这里。
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

_CJK = re.compile(r"[\u4e00-\u9fff]")
_WORD = re.compile(r"[a-zA-Z0-9_]+")


def tokenize(text: str) -> list[str]:
    """中文按字 + 二元组，英文/数字按词。够用且无需词典。"""
    text = (text or "").strip()
    if not text:
        return []
    out: list[str] = []
    # 英文/数字词
    out.extend(w.lower() for w in _WORD.findall(text))
    # 连续中文段：单字 + 相邻二元组
    for chunk in _CJK.findall(text):
        out.append(chunk)
    for m in re.finditer(r"[\u4e00-\u9fff]+", text):
        s = m.group(0)
        for i in range(len(s) - 1):
            out.append(s[i : i + 2])
    return out


def content_tokens(text: str) -> set[str]:
    """内容词：中文二元组 + 英文词（丢掉单字，避免"的/了/我"这类噪声）。"""
    out: set[str] = set()
    for w in _WORD.findall(text or ""):
        if len(w) >= 2:
            out.add(w.lower())
    for m in re.finditer(r"[\u4e00-\u9fff]+", text or ""):
        s = m.group(0)
        for i in range(len(s) - 1):
            out.add(s[i : i + 2])
    return out


def overlap_coefficient(a: set[str], b: set[str]) -> float:
    """共享词数 / 较短一侧词数 —— 比 Jaccard 更能识别"同一件事的不同说法"。"""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def bigrams(text: str) -> set[str]:
    """字符二元组集合（忽略空白与标点），用于 Jaccard。"""
    s = re.sub(r"[\s\W_]+", "", text or "")
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def jaccard(a: str, b: str) -> float:
    sa, sb = bigrams(a), bigrams(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def containment(part: str, whole: str) -> float:
    """包含度：part 的二元组有多少比例出现在 whole 里。"""
    sp, sw = bigrams(part), bigrams(whole)
    if not sp or not sw:
        return 0.0
    return len(sp & sw) / len(sp)


# ── 六位特征编码（十六进制风格的结构索引）────────────────────────────────────────────
# 八卦：按二进制值 0..7 排列（坤=000 → 乾=111）
TRIGRAMS = ["坤", "艮", "坎", "巽", "震", "离", "兑", "乾"]
TRIGRAM_BITS = {"坤": 0b000, "艮": 0b001, "坎": 0b010, "巽": 0b011,
                "震": 0b100, "离": 0b101, "兑": 0b110, "乾": 0b111}
# 八卦取象，用于解析卦名
TRIGRAM_IMAGE = {"乾": "天", "兑": "泽", "离": "火", "震": "雷",
                 "巽": "风", "坎": "水", "艮": "山", "坤": "地"}

# 六十四卦（文王序）卦名——上卦在前、下卦在后
_HEXAGRAM_NAMES = [
    "乾为天", "坤为地", "水雷屯", "山水蒙", "水天需", "天水讼", "地水师", "水地比",
    "风天小畜", "天泽履", "地天泰", "天地否", "天火同人", "火天大有", "地山谦", "雷地豫",
    "泽雷随", "山风蛊", "地泽临", "风地观", "火雷噬嗑", "山火贲", "山地剥", "地雷复",
    "天雷无妄", "山天大畜", "山雷颐", "泽风大过", "坎为水", "离为火", "泽山咸", "雷风恒",
    "天山遁", "雷天大壮", "火地晋", "地火明夷", "风火家人", "火泽睽", "水山蹇", "雷水解",
    "山泽损", "风雷益", "泽天夬", "天风姤", "泽地萃", "地风升", "泽水困", "水风井",
    "泽火革", "火风鼎", "震为雷", "艮为山", "风山渐", "雷泽归妹", "雷火丰", "火山旅",
    "巽为风", "兑为泽", "风水涣", "水泽节", "风泽中孚", "雷山小过", "水火既济", "火水未济",
]


def _parse_hexagram_name(name: str) -> tuple[str, str]:
    """把「水雷屯」解析成 (上卦, 下卦)。「乾为天」这种三字纯卦单独处理。"""
    if "为" in name:
        trigram = next(t for t, img in TRIGRAM_IMAGE.items() if img == name[-1])
        return trigram, trigram
    image_to_trigram = {img: t for t, img in TRIGRAM_IMAGE.items()}
    return image_to_trigram[name[0]], image_to_trigram[name[1]]


# HEXAGRAM[upper][lower] = 卦名
HEXAGRAM: dict[str, dict[str, str]] = {
    u: {l: "" for l in TRIGRAMS} for u in TRIGRAMS
}
for _name in _HEXAGRAM_NAMES:
    _u, _l = _parse_hexagram_name(_name)
    HEXAGRAM[_u][_l] = _name


def code_from_features(bits: list[int] | tuple[int, ...]) -> int:
    """6 位特征 → 0..63。b1 落在最低位（下卦首爻）。"""
    if len(bits) != 6:
        raise ValueError("需要 6 位")
    out = 0
    for i, b in enumerate(bits):
        out |= (1 if b else 0) << i
    return out


def feature_bits(text: str, *, source: str = "other", level: str = "normal",
                 tags: list[str] | None = None, region: str = "general",
                 valence: float = 0.0, arousal: float = 0.0) -> list[int]:
    """从记忆的结构特征取 6 位（文档未定义具体取哪些特征，这里是可复核的启发式）。

    b1 来源是否主人 · b2 等级是否 core/important · b3 是否带标签
    b4 是否带情绪（效价非零或唤醒 >0.3） · b5 文本长度 ≥30 · b6 分区是否专用（非 general）
    """
    return [
        1 if source == "owner" else 0,
        1 if level in ("core", "important") else 0,
        1 if tags else 0,
        1 if (abs(valence) > 0 or arousal > 0.3) else 0,
        1 if len(text) >= 30 else 0,
        1 if region not in ("general", "") else 0,
    ]


def code6(text: str) -> int:
    """兼容旧接口：无上下文时退化为文本哈希取 6 位（新代码请用 feature_bits）。"""
    h = hashlib.sha256((text or "").encode("utf-8")).digest()
    bits = [h[i] & 1 for i in range(6)]
    return code_from_features(bits)


def code_name(code: int) -> str:
    """0..63 → 文王卦名（上卦=b4b5b6，下卦=b1b2b3）。"""
    lower = TRIGRAMS[code & 0b111]
    upper = TRIGRAMS[(code >> 3) & 0b111]
    return HEXAGRAM[upper][lower]


# ── TF-IDF ────────────────────────────────────────────────────


def build_idf(docs: list[list[str]]) -> dict[str, float]:
    """docs: 每篇的 token 列表。返回 idf 表。"""
    n = len(docs)
    df: Counter[str] = Counter()
    for toks in docs:
        df.update(set(toks))
    return {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}


def tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf = Counter(tokens)
    total = sum(tf.values()) or 1
    vec = {t: (c / total) * idf.get(t, 1.0) for t, c in tf.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {t: v / norm for t, v in vec.items()}


def tfidf_from_tf(tf: dict[str, float], idf: dict[str, float]) -> dict[str, float]:
    """从已有的 tf 表直接算 tf-idf 向量（存储层只存 tf）。"""
    vec = {t: v * idf.get(t, 1.0) for t, v in tf.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {t: v / norm for t, v in vec.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())
