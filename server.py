#!/usr/bin/env python3
"""记忆子系统 HTTP API（本机回环，供 DSH / QQ 桥接调用）。

启动：python3 server.py --port 8730
接口：
  POST /add        {text, region?, source?, tags?, level?, arousal?}
  POST /search     {query, top?, temperature?, region?}
  GET  /stats
  POST /forget     {}
  POST /consolidate{}
  POST /maintain   {}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.memory import Memory  # noqa: E402

LOCK = threading.Lock()
MEM: Memory | None = None
TOKEN = os.environ.get("DAFEIYU_TOKEN", "")


class Handler(BaseHTTPRequestHandler):
    server_version = "dafeiyu-memory/0.1"

    def log_message(self, fmt, *args):  # 静音默认访问日志
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _authorized(self) -> bool:
        if not TOKEN:
            return True
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self) -> None:
        if not self._authorized():
            return self._json(401, {"ok": False, "error": "unauthorized"})
        if self.path == "/stats":
            with LOCK:
                return self._json(200, {"ok": True, "stats": MEM.stats()})
        if self.path == "/health":
            return self._json(200, {"ok": True, "version": "0.1"})
        return self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            return self._json(401, {"ok": False, "error": "unauthorized"})
        try:
            body = self._read()
            with LOCK:
                if self.path == "/add":
                    res = MEM.encode(
                        body["text"],
                        region=body.get("region", "general"),
                        source=body.get("source", "other"),
                        tags=body.get("tags") or [],
                        level=body.get("level", "normal"),
                        arousal=float(body.get("arousal") or 0.0),
                    )
                    return self._json(200, {"ok": True, **res})
                if self.path == "/search":
                    hits = MEM.retrieve(
                        body["query"],
                        top_k=int(body.get("top") or 8),
                        temperature=body.get("temperature", "normal"),
                        region_hint=body.get("region"),
                    )
                    MEM.mark_access([h["id"] for h in hits])
                    return self._json(200, {"ok": True, "hits": hits})
                if self.path == "/forget":
                    return self._json(200, {"ok": True, "result": MEM.forget_tick()})
                if self.path == "/consolidate":
                    return self._json(200, {"ok": True, "result": MEM.consolidate()})
                if self.path == "/maintain":
                    return self._json(200, {"ok": True, "result": MEM.maintain()})
        except KeyError as e:
            return self._json(400, {"ok": False, "error": f"missing field {e}"})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"ok": False, "error": str(e)})
        return self._json(404, {"ok": False, "error": "not found"})


def main() -> int:
    global MEM
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8730)
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "memory.db"))
    args = ap.parse_args()

    MEM = Memory(args.db)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"记忆服务已启动: http://127.0.0.1:{args.port}  db={args.db}")
    if TOKEN:
        print("已启用 Bearer 令牌校验")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
