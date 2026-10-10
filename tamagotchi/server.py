"""HTTP 服务：静态页面 + 游戏 API。零第三方依赖，python3 server.py 即可运行。"""

import errno
import json
import os
import posixpath
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
import game
import llm

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))
PORT_TRIES = 12

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "Tamagotchi/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, status, body, content_type):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload, ensure_ascii=False), CONTENT_TYPES[".json"])

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        clean = posixpath.normpath(urllib.parse.unquote(path)).lstrip("/")
        target = os.path.join(STATIC_DIR, clean)
        if not os.path.abspath(target).startswith(os.path.abspath(STATIC_DIR)) or not os.path.isfile(target):
            self._send(404, "404 Not Found", "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(target)[1].lower()
        with open(target, "rb") as fh:
            self._send(200, fh.read(), CONTENT_TYPES.get(ext, "application/octet-stream"))

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/state":
            self._json(200, {"ok": True, "state": game.build_state()})
            return
        if path.startswith("/api/"):
            self._json(404, {"ok": False, "error": "未知接口"})
            return
        self._static(path)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        payload = self._body()
        try:
            if path == "/api/chat":
                result = game.do_chat(payload.get("text", ""))
            elif path == "/api/gift":
                result = game.do_gift(payload.get("item_id", ""))
            elif path == "/api/work":
                result = game.do_work(payload.get("job_id", ""))
            elif path == "/api/activity":
                result = game.do_activity(payload.get("activity_id", ""))
            elif path == "/api/rest":
                result = game.do_rest()
            elif path == "/api/reset":
                game.new_game(payload.get("persona"))
                result = {"reply": "（新的故事开始了）"}
            else:
                self._json(404, {"ok": False, "error": "未知接口"})
                return
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        except llm.LLMError as exc:
            self.log_message("模型调用失败: %s", exc)
            self._json(502, {"ok": False, "error": "她好像走神了，等一下再说一次吧"})
            return
        except Exception as exc:  # noqa: BLE001
            self.log_message("内部错误: %r", exc)
            self._json(500, {"ok": False, "error": "服务器内部错误：{}".format(exc)})
            return

        self._json(200, {"ok": True, "result": result, "state": game.build_state()})


def _utf8_stdio():
    """Termux 默认不设 LANG，stdout 可能是 ascii 编码，一 print 中文就崩。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _bind(host, port, handler):
    """端口被占时顺延重试：手机上和 Termux 共用同一个网络命名空间，
    容器里已经跑着的实例会把 8765 占住，直接 bind 只会甩出一段 traceback。"""
    for candidate in range(port, port + PORT_TRIES):
        try:
            return ThreadingHTTPServer((host, candidate), handler)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            print("端口 {} 被占用，试 {}。".format(candidate, candidate + 1))
    raise SystemExit("{}~{} 都被占用了，换一个：PORT=9000 sh run.sh web".format(port, port + PORT_TRIES - 1))


def main():
    _utf8_stdio()
    db.init_db()
    if not db.get_save():
        game.new_game()
        print("已创建新存档。")
    if not os.environ.get("DEEPSEEK_API_KEY") and not os.path.exists(os.path.join(BASE_DIR, ".env")):
        print("警告：未找到 API Key，请在 .env 里配置 DEEPSEEK_API_KEY。")
    server = _bind(HOST, PORT, Handler)
    port = server.server_address[1]
    if port != PORT:
        print("{} 被占用（可能是上一次的实例还没退），已改用 {}。".format(PORT, port))
    print("养成游戏已启动： http://{}:{}/".format("127.0.0.1" if HOST == "0.0.0.0" else HOST, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
