"""记忆子系统：编码 → 存储 → 巩固 → 检索 → 遗忘。

所有公式都落在代码里，参数见 core/config.py。
"""
from __future__ import annotations

import json
import math
import random
import time
import uuid
from collections import Counter

from . import config as C
from . import text as T
from .store import Store


class Memory:
    def __init__(self, db_path: str):
        self.store = Store(db_path)
        if not self.store.idf_table():
            self.store.rebuild_idf()

    # ── 编码 ──────────────────────────────────────────────
    def encode(
        self,
        text: str,
        region: str = "general",
        source: str = "other",
        tags: list[str] | None = None,
        level: str = "normal",
        valence: float = 0.0,
        arousal: float = 0.0,
    ) -> dict:
        """写入一条记忆。

        - surprise：与既有记忆的最大字符集相似度的补集，近似预测误差
        - 初始权重 w0 = w_base · (1 + surprise)
        - 情绪唤醒高 → flash（不合并、不淘汰、检索优先）
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("text 不能为空")
        tags = tags or []
        now = self.store.now_ms()

        # 高唤醒触发「闪光灯记忆」：不合并、不淘汰、检索优先
        if arousal >= 0.8:
            region = C.FLASH_REGION

        existing = self.store.nodes()
        sims = [(T.jaccard(text, n["text"]), n) for n in existing]
        max_sim = max((s for s, _ in sims), default=0.0)
        surprise = 1.0 - max_sim

        # 去重：Jaccard ≥ .60 且包含度 ≥ .78 且同 region 或共享 tag，闪光灯节点不参与
        if region != C.FLASH_REGION:
            for sim, node in sorted(sims, key=lambda x: -x[0]):
                if sim < C.DEDUPE_JACCARD:
                    break
                if node["region"] == C.FLASH_REGION:
                    continue
                cont = T.containment(text, node["text"])
                shared = set(json.loads(node["tags"])) & set(tags)
                if cont >= C.DEDUPE_CONTAINMENT and (node["region"] == region or shared):
                    merged_tags = sorted(set(json.loads(node["tags"])) | set(tags))
                    self.store.update_node(
                        node["id"],
                        w0=node["w0"] + 0.5 * self._w0(source, surprise),
                        tags=json.dumps(merged_tags, ensure_ascii=False),
                        last_access=now,
                        access_count=node["access_count"] + 1,
                    )
                    return {"id": node["id"], "merged": True, "surprise": surprise}

        w0 = self._w0(source, surprise)
        node = {
            "id": uuid.uuid4().hex[:12],
            "text": text,
            "region": region,
            "level": level,
            "source": source,
            "tags": json.dumps(tags, ensure_ascii=False),
            "w0": w0,
            "valence": float(valence),
            # 6 位结构编码：由特征位组合而成（不是文本哈希）
            "code": T.code_from_features(T.feature_bits(
                text, source=source, level=level, tags=tags,
                region=region, valence=valence, arousal=arousal,
            )),
            "state": "hot",
            "created_at": now,
            "last_access": 0,
            "access_count": 0,
            "meta": "{}",
        }
        self.store.insert_node(node)
        self.store.set_tokens(node["id"], self._tf(text))

        # 共现边：按 **token 集合重叠** 连到最相似的 3 条（图通道）。
        # 不用字符 Jaccard —— 英文词/数字不参与二元组，会导致这类记忆完全孤立。
        new_content = T.content_tokens(text)
        linked = 0
        for cand_id in self.store.candidates(set(T.tokenize(text)), limit_per_token=50):
            if cand_id == node["id"] or linked >= 5:
                continue
            other = self.store.get_node(cand_id)
            if not other:
                continue
            other_content = T.content_tokens(other["text"])
            overlap = T.overlap_coefficient(new_content, other_content)
            if len(new_content & other_content) >= 2 and overlap >= 0.25:
                self.store.upsert_edge(node["id"], cand_id, "cooccur", round(overlap, 4))
                self.store.upsert_edge(cand_id, node["id"], "cooccur", round(overlap, 4))
                linked += 1

        if self.store.count() % 20 == 0:
            self.store.rebuild_idf()

        return {"id": node["id"], "merged": False, "surprise": surprise, "w0": w0}

    @staticmethod
    def token_sim(a: str, b: str) -> float:
        """token 集合 Jaccard：比字符二元组更能抓住"说的是同一件事"。"""
        sa, sb = set(T.tokenize(a)), set(T.tokenize(b))
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def _w0(self, source: str, surprise: float) -> float:
        base = C.W_BASE_OWNER if source == "owner" else C.W_BASE_OTHER
        return base * (1.0 + max(0.0, surprise))

    def _tf_from_tokens(self, toks: list[str]) -> dict[str, float]:
        c = Counter(toks)
        total = sum(c.values()) or 1
        return {t: v / total for t, v in c.items()}

    def _weighted_tf(self, toks: list[str]) -> dict[str, float]:
        """单字降权到 0.3：短查询（"喝什么"）靠单字召回，长文本里的单字基本是噪声。"""
        c = Counter(toks)
        weighted = {t: v * (0.3 if len(t) < 2 else 1.0) for t, v in c.items()}
        total = sum(weighted.values()) or 1
        return {t: v / total for t, v in weighted.items()}

    def _tf(self, text: str) -> dict[str, float]:
        toks = T.tokenize(text)
        c = Counter(toks)
        total = sum(c.values()) or 1
        return {t: v / total for t, v in c.items()}

    # ── 检索 ──────────────────────────────────────────────
    def retrieve(
        self,
        query: str,
        top_k: int = C.DEFAULT_TOP_K,
        temperature: str = C.DEFAULT_TEMPERATURE,
        drive_bias: float = 1.0,
        region_hint: str | None = None,
    ) -> list[dict]:
        """三路融合检索：0.65·cos + 0.35·lex，再乘权重/分区/抖动。"""
        qtoks = T.tokenize(query)
        if not qtoks:
            return []
        cand = self.store.candidates(set(qtoks))
        # 图通道：候选节点的 1 跳邻居也进来（扩散激活）
        expanded = set(cand)
        for nid in list(cand)[:30]:
            for dst, _w in self.store.neighbors(nid, limit=6):
                expanded.add(dst)

        idf = self.store.idf_table()
        # 余弦只用内容词（二元组/英文词）：单字在短文本里噪声太大，
        # 实测会把"记忆系统怎么分工"匹配到毫不相干的句子上。
        q_content = T.content_tokens(query)
        qvec = T.tfidf_from_tf(self._weighted_tf(qtoks), idf)
        now = self.store.now_ms()
        t_scale = C.TEMPERATURE.get(temperature, 1.0)

        scored = []
        for nid in expanded:
            node = self.store.get_node(nid)
            if not node or node["state"] == "evicted":
                continue
            doc_tf = {t: (v * (0.3 if len(t) < 2 else 1.0)) for t, v in self.store.node_tokens(nid).items()}
            dvec = T.tfidf_from_tf(doc_tf, idf)
            cos = T.cosine(qvec, dvec)
            lex = T.jaccard(query, node["text"])
            base = C.W_COS * cos + C.W_LEX * lex
            if base <= 0:
                continue
            # 关键词命中（内容词重叠）与标签命中：这两路比纯余弦更能抓住"同一话题"
            doc_content = T.content_tokens(node["text"])
            kw = len(q_content & doc_content)
            keyword_boost = 1.0 + 0.3 * kw
            tags = json.loads(node["tags"])
            tag_hit = any(t and t in query for t in tags)
            tag_boost = 1.6 if tag_hit else 1.0
            w = self._decayed(node, now)
            boost = C.NEUTRAL_REGION_BOOST
            if node["region"] == C.FLASH_REGION:
                boost = C.FLASH_REGION_BOOST
            elif region_hint and node["region"] == region_hint:
                boost = C.MATCH_REGION_BOOST
            jitter = 1.0 + random.uniform(-C.JITTER, C.JITTER) * t_scale
            scored.append(
                {
                    "id": nid,
                    "text": node["text"],
                    "region": node["region"],
                    "level": node["level"],
                    "tags": json.loads(node["tags"]),
                    "code": node["code"],
                    "score": base * w * boost * keyword_boost * tag_boost * drive_bias * jitter,
                    "detail": {
                        "cos": round(cos, 4),
                        "lex": round(lex, 4),
                        "kw": kw,
                        "tag": tag_hit,
                        "w": round(w, 3),
                    },
                }
            )

        scored.sort(key=lambda x: -x["score"])
        return self._diversify(scored, top_k)

    def _diversify(self, scored: list[dict], top_k: int) -> list[dict]:
        """同卦节点按 0.86 / 0.72 递减，避免检索同质化。"""
        seen: Counter[int] = Counter()
        out: list[dict] = []
        while scored and len(out) < top_k:
            best_i, best_score = 0, -1.0
            for i, item in enumerate(scored):
                k = seen[item["code"]]
                decay = 1.0
                if k >= 1:
                    idx = min(k - 1, len(C.DIVERSITY_DECAY) - 1)
                    decay = C.DIVERSITY_DECAY[idx]
                s = item["score"] * decay
                if s > best_score:
                    best_i, best_score = i, s
            item = scored.pop(best_i)
            seen[item["code"]] += 1
            out.append(item)
        return out

    def mark_access(self, node_ids: list[str]) -> None:
        """召回后记账：刷新 last_access，短窗口内反复召回收反刍抑制。"""
        now = self.store.now_ms()
        for nid in node_ids:
            node = self.store.get_node(nid)
            if not node:
                continue
            w0 = node["w0"]
            if now - (node["last_access"] or 0) < C.RUMINATION_WINDOW_SEC * 1000:
                w0 *= C.RUMINATION_PENALTY
            self.store.update_node(
                nid, last_access=now, access_count=node["access_count"] + 1, w0=w0
            )

    # ── 遗忘 ──────────────────────────────────────────────
    def _decayed(self, node: dict, now: int) -> float:
        tau_days = C.TAU_DAYS.get(node["level"], C.TAU_DAYS["normal"])
        ref = node["last_access"] or node["created_at"]
        dt_sec = max(0, (now - ref) / 1000.0)
        return node["w0"] * math.exp(-dt_sec / (tau_days * 86400.0))

    def forget_tick(self, now: int | None = None) -> dict:
        """时间衰减 + 容量淘汰。返回本次状态变化统计。"""
        now = now or self.store.now_ms()
        moved_cold = 0
        evicted = 0
        for node in self.store.nodes(("hot", "cold")):
            w = self._decayed(node, now)
            if node["region"] == C.FLASH_REGION:
                continue  # 闪光灯记忆不淘汰
            if node["state"] == "hot" and w < 0.5:
                self.store.update_node(node["id"], state="cold")
                moved_cold += 1
            elif node["state"] == "cold" and w < 0.05:
                self.store.update_node(node["id"], state="evicted")
                evicted += 1

        # 容量：热库超限时按权重下沉
        hot = [n for n in self.store.nodes(("hot",)) if n["region"] != C.FLASH_REGION]
        overflow = len(hot) - C.HOT_CAPACITY
        if overflow > 0:
            hot.sort(key=lambda n: self._decayed(n, now))
            for node in hot[:overflow]:
                self.store.update_node(node["id"], state="cold")
                moved_cold += 1

        return {"moved_cold": moved_cold, "evicted": evicted}

    # ── 巩固 ──────────────────────────────────────────────
    def consolidate(self, now: int | None = None) -> list[dict]:
        """把相似且同 region 的记忆合并成一条抽象记忆。"""
        now = now or self.store.now_ms()
        nodes = [n for n in self.store.nodes(("hot", "cold")) if n["region"] != C.FLASH_REGION]
        used: set[str] = set()
        created: list[dict] = []
        for i, a in enumerate(nodes):
            if a["id"] in used:
                continue
            group = [a]
            for b in nodes[i + 1 :]:
                if b["id"] in used or b["region"] != a["region"]:
                    continue
                ca, cb = T.content_tokens(a["text"]), T.content_tokens(b["text"])
                sim = T.overlap_coefficient(ca, cb)
                if len(ca & cb) >= 2 and sim >= C.CONSOLIDATE_SIM:
                    group.append(b)
            if len(group) < 2:
                continue
            merged_text = "｜".join(g["text"] for g in group)
            tags = sorted({t for g in group for t in json.loads(g["tags"])})
            level = "important" if sum(1 for g in group if g["level"] != "normal") >= 1 else "normal"
            res = self.encode(
                merged_text,
                region=a["region"],
                source=a["source"],
                tags=tags,
                level=level,
            )
            if res["merged"]:
                continue
            for g in group:
                used.add(g["id"])
                self.store.update_node(g["id"], state="consolidated")
                self.store.upsert_edge(res["id"], g["id"], "theme", 1.0)
            created.append({"abstract": res["id"], "members": [g["id"] for g in group]})
        return created

    # ── 维护 ──────────────────────────────────────────────
    def maintain(self) -> dict:
        """修复自环、悬空边、缺失 region/tags，重建 idf。"""
        fixed = {"self_loop": 0, "dangling": 0, "region": 0, "tags": 0}
        ids = {n["id"] for n in self.store.nodes(("hot", "cold", "consolidated"))}
        for e in self.store.all_edges():
            if e["src"] == e["dst"]:
                self.store.delete_edge(e["src"], e["dst"], e["kind"])
                fixed["self_loop"] += 1
            elif e["dst"] not in ids or e["src"] not in ids:
                self.store.delete_edge(e["src"], e["dst"], e["kind"])
                fixed["dangling"] += 1
        for node in self.store.nodes(("hot", "cold", "consolidated")):
            if not node["region"]:
                self.store.update_node(node["id"], region="general")
                fixed["region"] += 1
            try:
                json.loads(node["tags"])
            except Exception:
                self.store.set_tags(node["id"], [])
                fixed["tags"] += 1
        self.store.rebuild_idf()
        return fixed

    # ── 统计 ──────────────────────────────────────────────
    def stats(self) -> dict:
        nodes = self.store.nodes(("hot", "cold", "consolidated"))
        by_region = Counter(n["region"] for n in nodes)
        by_state = Counter(n["state"] for n in nodes)
        return {
            "total": self.store.count("hot") + self.store.count("cold") + self.store.count("consolidated"),
            "hot": by_state.get("hot", 0),
            "cold": by_state.get("cold", 0),
            "consolidated": by_state.get("consolidated", 0),
            "evicted": self.store.count("evicted"),
            "by_region": dict(by_region),
            "edges": len(self.store.all_edges()),
            "flash": by_region.get(C.FLASH_REGION, 0),
        }
