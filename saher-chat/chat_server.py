"""Saher local chat: a tiny page on 127.0.0.1 that talks to the local Ollama model. Stdlib only.
The conversation lives only in the open browser tab. Nothing is written to disk or logged.
Usage: python chat_server.py   (or double-click start_chat.bat)"""
import json, os, threading, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
HOST, PORT = "127.0.0.1", 8765
OLLAMA = "http://localhost:11434/api/chat"
MODEL = os.environ.get("SAHER_MODEL", "qwen2.5:7b")
OPTIONS = {"temperature": 0.2, "top_p": 0.9, "num_ctx": 4096}
MAX_MESSAGES = 20  # only the latest turns are sent, so long chats stay inside the context window
PERSONA = open(os.path.join(HERE, os.environ.get("SAHER_PERSONA", "persona.txt")), encoding="utf-8").read()
PAGE = open(os.path.join(HERE, "index.html"), encoding="utf-8").read().replace("{{MODEL}}", MODEL).encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the console free of chat content
        pass

    def do_GET(self):
        if self.path != "/":
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE)

    def do_POST(self):
        if self.path == "/quit":
            self.send_response(204)
            self.end_headers()
            threading.Thread(target=self.server.shutdown).start()
            return
        if self.path != "/chat":
            return self.send_error(404)
        history = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["messages"]
        messages = [{"role": "system", "content": PERSONA}] + [
            {"role": m["role"], "content": m["content"]} for m in history[-MAX_MESSAGES:]
            if m.get("role") in ("user", "assistant")]
        body = json.dumps({"model": MODEL, "stream": True, "options": OPTIONS, "messages": messages}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.end_headers()
        try:
            req = urllib.request.Request(OLLAMA, body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                for line in r:
                    self.wfile.write(line)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the page reset or closed mid-reply
        except Exception as e:
            self.wfile.write((json.dumps({"error": str(e)}) + "\n").encode())


server = ThreadingHTTPServer((HOST, PORT), Handler)
url = f"http://{HOST}:{PORT}/"
print(f"Saher chat is running at {url}")
print("Close it with the 'إنهاء' button on the page, or press Ctrl+C here.")
if not os.environ.get("SAHER_NO_BROWSER"):
    webbrowser.open(url)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
print("Saher chat stopped.")
