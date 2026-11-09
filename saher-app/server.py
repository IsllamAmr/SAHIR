"""Saher: one page on 127.0.0.1 where you can type or talk (push-to-talk, then review the transcript), in the same conversation.
The conversation lives only in the open browser tab. Nothing is written to disk or logged.
Usage: python server.py   (or double-click start_saher.bat)"""
import base64, json, os, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np
from pipeline import Pipeline, HERE, MODEL, ASR_SIZE, ASR_DEVICE

HOST, PORT = "127.0.0.1", int(os.environ.get("SAHER_PORT", "8767"))
sys.stdout.reconfigure(encoding="utf-8")
print("Loading speech recognition, voice and ALLaM...")
pipe = Pipeline()
pipe.warm_up()
PAGE = open(os.path.join(HERE, "index.html"), encoding="utf-8").read().replace(
    "{{SETUP}}", f"{MODEL} · Whisper {ASR_SIZE} ({ASR_DEVICE}) · Piper ar_JO-kareem (CPU)").encode()


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
        if self.path not in ("/turn", "/transcribe"):
            return self.send_error(404)
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/transcribe":
            audio = np.frombuffer(base64.b64decode(req["pcm16"]), np.int16).astype(np.float32) / 32768
            t0 = time.perf_counter()
            with pipe.lock:
                text = pipe.transcribe(audio)
            body = json.dumps({"text": text, "ms": round((time.perf_counter() - t0) * 1000)}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        history = [{"role": m["role"], "content": m["content"]} for m in req.get("messages", [])
                   if m.get("role") in ("user", "assistant")]
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.end_headers()

        def emit(e):
            if "pcm16" in e:
                e = dict(e, pcm16=base64.b64encode(e["pcm16"]).decode())
            self.wfile.write((json.dumps(e, ensure_ascii=False) + "\n").encode())
            self.wfile.flush()
        try:
            pipe.turn(history, emit, text=req["text"].strip(), speak=bool(req.get("speak")), spoken=bool(req.get("spoken")))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # the page stopped, reset or closed mid-reply
        except Exception as e:
            try:
                emit({"type": "error", "error": str(e)})
            except OSError:
                pass

server = ThreadingHTTPServer((HOST, PORT), Handler)
url = f"http://{HOST}:{PORT}/"
print(f"Saher is running at {url}")
print("Close it with the 'إنهاء' button on the page, or press Ctrl+C here.")
if not os.environ.get("SAHER_NO_BROWSER"):
    webbrowser.open(url)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
print("Saher stopped.")
