r"""Saher agent: a local chat page on 127.0.0.1 where Saher can use local tools (read files in SAHIR\workspace\,
calculate, tell the time, write NEW Word/Excel reports into workspace\outputs\, read unread emails).
Nothing can be sent, deleted, moved or overwritten. The chat is not logged or saved.
Usage: python server.py   (or double-click start_saher_agent.bat)"""
import json, os, sys, threading, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import agent, sender, tools

HERE = os.path.dirname(os.path.abspath(__file__))
HOST, PORT = "127.0.0.1", int(os.environ.get("SAHER_PORT", "8769"))
MAX_MESSAGES = 16
sys.stdout.reconfigure(encoding="utf-8")
# Send mode (SAHER_SEND=mock|gmail) has its own page: Modern Standard Arabic, approval cards, stop button.
PAGE_FILE = "index_send.html" if agent.SEND_ON else "index.html"
PAGE = (open(os.path.join(HERE, PAGE_FILE), encoding="utf-8").read().replace("{{MODEL}}", agent.MODEL)
        .replace("{{SEND_MODE}}", sender.MODE).encode())
LOGO = open(os.path.join(HERE, "logo.svg"), encoding="utf-8").read().encode()
lock = threading.Lock()  # one turn at a time: the laptop GPU has room for one model call


def ollama_running():
    try:
        with urllib.request.urlopen(agent.OLLAMA + "/api/tags", timeout=2) as r:
            return any(m["name"].split(":")[0] == agent.MODEL.split(":")[0] for m in json.load(r).get("models", []))
    except Exception:
        return False


def mail_mode():
    if tools.MAIL_MODE == "auto":
        return "gmail" if tools._n8n_up() else "mock"
    return tools.MAIL_MODE


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the console free of chat content
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self):
        if self.path == "/":
            return self._send(200, "text/html; charset=utf-8", PAGE)
        if self.path == "/logo.svg":
            return self._send(200, "image/svg+xml", LOGO)
        if self.path == "/status":
            files = tools.workspace_files()
            return self._json({"model": ollama_running(), "model_name": agent.MODEL, "mail": mail_mode(), "send": sender.MODE,
                               "workspace": tools.WORKSPACE, "files": len([f for f in files if not f.startswith("outputs/")]),
                               "reports": len([f for f in files if f.startswith("outputs/")])})
        self.send_error(404)

    def _same_origin(self):
        # Only this page may call the API: blocks other websites open in the browser from using it.
        origin = self.headers.get("Origin")
        return origin in (None, f"http://{HOST}:{PORT}") and self.headers.get("Host") == f"{HOST}:{PORT}"

    def do_POST(self):
        if not self._same_origin():
            return self.send_error(403)
        if self.path == "/quit":
            self.send_response(204)
            self.end_headers()
            threading.Thread(target=self.server.shutdown).start()
            return
        if self.path == "/cancel":  # the page's stop button: ends the running turn at the next model chunk or step
            agent.CANCEL.set()
            return self._json({"ok": True})
        if self.path.startswith("/draft/"):
            return self._draft(self.path[len("/draft/"):])
        if self.path == "/open_outputs":  # opens workspace\outputs in Explorer (only that folder, nothing else)
            os.makedirs(tools.OUTPUTS, exist_ok=True)
            os.startfile(tools.OUTPUTS)
            self.send_response(204)
            self.end_headers()
            return
        if self.path != "/turn":
            return self.send_error(404)
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def emit(e):
            self.wfile.write((json.dumps(e, ensure_ascii=False) + "\n").encode())
            self.wfile.flush()
        try:
            history = [m for m in req.get("messages", []) if m.get("role") in ("user", "assistant")][-MAX_MESSAGES:]
            text = str(req.get("text", "")).strip()[:2000]
            if not text:
                return emit({"type": "done", "reply": "", "ms": 0})
            with lock:
                agent.run_turn(history, text, emit)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # the page stopped, reset or closed mid-reply
        except agent.Cancelled:
            try:
                emit({"type": "cancelled"})
            except OSError:
                pass
        except agent.ModelError as e:
            print("model error:", str(e)[:200])
            try:
                emit({"type": "error", "error": "model", "detail": str(e)[:300]})
            except OSError:
                pass
        except Exception as e:
            print("error:", type(e).__name__, str(e)[:200])
            try:
                emit({"type": "error", "error": "internal", "detail": f"{type(e).__name__}: {e}"[:300]})
            except OSError:
                pass


def _draft_action(self, action):
    """Approval-card actions. Only these requests can send, and only the exact approved fingerprint."""
    if not agent.SEND_ON:
        return {"ok": False, "error": "الإرسال غير مفعّل في هذا التشغيل."}
    req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
    did = str(req.get("id", ""))
    if action == "send":
        return sender.send_approved(did, str(req.get("hash", "")))
    if action == "update":
        atts = [str(a) for a in req.get("attachments", []) if isinstance(a, str)]
        return sender.update_draft(did, str(req.get("to", "")), str(req.get("subject", "")), str(req.get("body", "")), atts)
    if action == "cancel":
        return sender.cancel_draft(did)
    if action == "check":
        return sender.recheck(did)
    return {"ok": False, "error": "unknown action"}


def _draft(self, action):
    try:
        with send_lock:  # one send at a time, never two clicks racing
            res = _draft_action(self, action)
    except Exception as e:
        print("draft error:", type(e).__name__, str(e)[:200])
        res = {"ok": False, "error": f"حدث خطأ في البرنامج ({type(e).__name__}). لم يُرسل شيء إلا إذا ظهر رقم الرسالة من Gmail."}
    return self._json(res)


Handler._draft = _draft
send_lock = threading.Lock()


if __name__ == "__main__":
    # Without SO_REUSEADDR a second copy fails loudly instead of silently sharing the port on Windows.
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print(f"Port {PORT} is already in use: Saher agent (or another app) is already running. Open http://{HOST}:{PORT}/")
        sys.exit(1)
    os.makedirs(tools.OUTPUTS, exist_ok=True)
    url = f"http://{HOST}:{PORT}/"
    print(f"Saher agent is running at {url}")
    print(f"Model: {agent.MODEL} via {agent.OLLAMA}. Workspace: {tools.WORKSPACE}. Mail: {mail_mode()}. "
          f"Sending: {sender.MODE}" + (f" via {sender.BASE}" if agent.SEND_ON else " (this launcher cannot send)"))
    print("Close it with the 'إنهاء' button on the page, or press Ctrl+C here.")
    if not os.environ.get("SAHER_NO_BROWSER"):
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    print("Saher agent stopped.")
