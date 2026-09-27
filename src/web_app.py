"""Local web chat for the insurance analyst. Standard library only.

Usage (from the project root, .venv active, database built, .env filled in):
    python src/web_app.py
Then open http://127.0.0.1:8000 in your browser. Ctrl+C stops the server.

Routes:
    GET  /            -> web/index.html (the chat page)
    GET  /api/health  -> {"ok": true, "model": "..."}
    POST /api/ask     -> {"question": "..."}  ->  the same record ask.py produces

The server listens on 127.0.0.1 only, so nothing outside your computer can reach it.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ask import DB_PATH, answer, log, log_record
from llm_client import load_env

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "web" / "index.html"

HOST, PORT = "127.0.0.1", 8000
MAX_BODY_BYTES = 10_000
MAX_QUESTION_CHARS = 500


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            body = INDEX_HTML.read_bytes()   # re-read each time, so HTML edits show on refresh
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        elif self.path == "/api/health":
            self.send_json(200, {"ok": True, "model": os.environ.get("LLM_MODEL", "")})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/api/ask":
            self.send_json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY_BYTES:
            self.send_json(413, {"error": "Request too large."})
            return
        try:
            question = str(json.loads(self.rfile.read(length) or b"{}").get("question", "")).strip()
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Body must be JSON."})
            return
        if not question:
            self.send_json(400, {"error": "Please type a question."})
            return
        if len(question) > MAX_QUESTION_CHARS:
            self.send_json(400, {"error": f"Questions are limited to {MAX_QUESTION_CHARS} characters."})
            return

        try:
            record = answer(question)
        except Exception as e:  # LLM/network problems: show them in the chat instead of crashing
            log({"question": question, "status": "error", "error": str(e), "source": "web"})
            self.send_json(502, {"error": str(e)})
            return

        log_record({**record, "source": "web"})
        self.send_json(200, record)

    def log_message(self, fmt, *args) -> None:  # quieter console: one line per request
        sys.stderr.write(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}\n")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_env()
    if not DB_PATH.exists():
        print("Database not found. Run: python src/build_database.py")
        return 1
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Insurance analyst chat running at http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
