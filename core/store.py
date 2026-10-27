"""存储层：SQLite（节点 / 边 / 倒排索引）。

只用标准库 sqlite3，单文件、可备份、可 grep。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    region      TEXT NOT NULL DEFAULT 'general',
    level       TEXT NOT NULL DEFAULT 'normal',   -- core / important / normal
    source      TEXT NOT NULL DEFAULT 'other',    -- owner / other
    tags        TEXT NOT NULL DEFAULT '[]',
    w0          REAL NOT NULL DEFAULT 1.0,
    valence     REAL NOT NULL DEFAULT 0.0,
    code        INTEGER NOT NULL DEFAULT 0,
    state       TEXT NOT NULL DEFAULT 'hot',      -- hot / cold / consolidated
    created_at  INTEGER NOT NULL,
    last_access INTEGER NOT NULL DEFAULT 0,
    access_count INTEGER NOT NULL DEFAULT 0,
    meta        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_nodes_state ON nodes(state);
CREATE INDEX IF NOT EXISTS idx_nodes_code  ON nodes(code);

CREATE TABLE IF NOT EXISTS edges (
    src    TEXT NOT NULL,
    dst    TEXT NOT NULL,
    kind   TEXT NOT NULL DEFAULT 'cooccur',   -- cooccur / theme / time
    weight REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (src, dst, kind)
);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);

CREATE TABLE IF NOT EXISTS tokens (
    node_id TEXT NOT NULL,
    token   TEXT NOT NULL,
    tf      REAL NOT NULL,
    PRIMARY KEY (node_id, token)
);
CREATE INDEX IF NOT EXISTS idx_tokens_token ON tokens(token);

CREATE TABLE IF NOT EXISTS idf (
    token TEXT PRIMARY KEY,
    value REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        # check_same_thread=False：HTTP 服务是多线程的，写入由上层锁保护
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        """老库补新列（valence 是 Phase 1.5 加的）。"""
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(nodes)")}
        if "valence" not in cols:
            self.db.execute("ALTER TABLE nodes ADD COLUMN valence REAL NOT NULL DEFAULT 0.0")
        self.db.commit()

    # ── 节点 ──────────────────────────────────────────────
    def insert_node(self, node: dict) -> None:
        self.db.execute(
            """INSERT INTO nodes
               (id,text,region,level,source,tags,w0,valence,code,state,created_at,last_access,access_count,meta)
               VALUES (:id,:text,:region,:level,:source,:tags,:w0,:valence,:code,:state,:created_at,:last_access,:access_count,:meta)""",
            node,
        )
        self.db.commit()

    def update_node(self, node_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=:{k}" for k in fields)
        fields = {**fields, "id": node_id}
        self.db.execute(f"UPDATE nodes SET {cols} WHERE id=:id", fields)
        self.db.commit()

    def get_node(self, node_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return dict(row) if row else None

    def nodes(self, states: Iterable[str] = ("hot", "cold")) -> list[dict]:
        marks = ",".join("?" for _ in states)
        rows = self.db.execute(
            f"SELECT * FROM nodes WHERE state IN ({marks})", tuple(states)
        ).fetchall()
        return [dict(r) for r in rows]

    def count(self, state: str | None = None) -> int:
        if state:
            return self.db.execute("SELECT COUNT(*) c FROM nodes WHERE state=?", (state,)).fetchone()["c"]
        return self.db.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"]

    def set_tags(self, node_id: str, tags: list[str]) -> None:
        self.update_node(node_id, tags=json.dumps(tags, ensure_ascii=False))

    # ── 边 ────────────────────────────────────────────────
    def upsert_edge(self, src: str, dst: str, kind: str, weight: float) -> None:
        self.db.execute(
            """INSERT INTO edges(src,dst,kind,weight) VALUES(?,?,?,?)
               ON CONFLICT(src,dst,kind) DO UPDATE SET weight=weight+excluded.weight""",
            (src, dst, kind, weight),
        )
        self.db.commit()

    def neighbors(self, node_id: str, limit: int = 20) -> list[tuple[str, float]]:
        rows = self.db.execute(
            "SELECT dst, weight FROM edges WHERE src=? ORDER BY weight DESC LIMIT ?",
            (node_id, limit),
        ).fetchall()
        return [(r["dst"], r["weight"]) for r in rows]

    def adjacency(self) -> dict[str, list[tuple[str, float]]]:
        """出边邻接表，供个性化 PageRank 用。"""
        adj: dict[str, list[tuple[str, float]]] = {}
        for r in self.db.execute("SELECT src,dst,weight FROM edges"):
            adj.setdefault(r["src"], []).append((r["dst"], float(r["weight"])))
        return adj

    def all_edges(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM edges").fetchall()]

    def delete_edge(self, src: str, dst: str, kind: str) -> None:
        self.db.execute("DELETE FROM edges WHERE src=? AND dst=? AND kind=?", (src, dst, kind))
        self.db.commit()

    # ── 倒排索引 ──────────────────────────────────────────
    def set_tokens(self, node_id: str, tf: dict[str, float]) -> None:
        self.db.execute("DELETE FROM tokens WHERE node_id=?", (node_id,))
        self.db.executemany(
            "INSERT OR REPLACE INTO tokens(node_id,token,tf) VALUES(?,?,?)",
            [(node_id, t, v) for t, v in tf.items()],
        )
        self.db.commit()

    def node_tokens(self, node_id: str) -> dict[str, float]:
        rows = self.db.execute("SELECT token,tf FROM tokens WHERE node_id=?", (node_id,)).fetchall()
        return {r["token"]: r["tf"] for r in rows}

    def candidates(self, tokens: Iterable[str], limit_per_token: int = 200) -> set[str]:
        out: set[str] = set()
        for tok in tokens:
            rows = self.db.execute(
                "SELECT node_id FROM tokens WHERE token=? LIMIT ?", (tok, limit_per_token)
            ).fetchall()
            out.update(r["node_id"] for r in rows)
        return out

    def rebuild_idf(self) -> dict[str, float]:
        """按当前活跃节点重算 idf 并落库。"""
        import math

        rows = self.db.execute(
            """SELECT t.token, COUNT(DISTINCT t.node_id) df
               FROM tokens t JOIN nodes n ON n.id=t.node_id
               WHERE n.state IN ('hot','cold') GROUP BY t.token"""
        ).fetchall()
        n = max(self.count(), 1)
        table = {r["token"]: math.log((n + 1) / (r["df"] + 1)) + 1.0 for r in rows}
        self.db.execute("DELETE FROM idf")
        self.db.executemany(
            "INSERT INTO idf(token,value) VALUES(?,?)", list(table.items())
        )
        self.db.commit()
        return table

    def idf_table(self) -> dict[str, float]:
        rows = self.db.execute("SELECT token,value FROM idf").fetchall()
        return {r["token"]: r["value"] for r in rows}

    # ── meta ─────────────────────────────────────────────
    def set_meta(self, key: str, value) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self.db.commit()

    def get_meta(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def close(self) -> None:
        self.db.close()
