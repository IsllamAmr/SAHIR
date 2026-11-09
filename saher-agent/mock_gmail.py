r"""Simulated Gmail for testing Saher's sending. It answers on the same paths as the n8n workflows
(POST /webhook/saher-send-gmail, GET /webhook/saher-sent-check?mid=...), checks the same X-Saher-Key, sends nothing
anywhere, and records every request in state\mock_gmail_log.jsonl (recipient, subject, Message-ID, attachments).

The recipient's address picks the scenario (anything else = normal success, like Gmail's real reply):
  fail-scope@...    Gmail refuses: missing gmail.send permission (definitive, nothing sent)
  bad-request@...   Gmail refuses: invalid request (definitive)
  timeout-sent@...  the message IS recorded as sent, but the reply never comes in time (Saher must find it in Sent)
  timeout-lost@...  no reply and nothing recorded (Saher must report "unknown", never resend on its own)
  server-error@...  n8n answers with an unknown error after recording nothing
Usage: python mock_gmail.py   (port 5699, or SAHER_MOCK_PORT)"""
import base64, email, email.policy, json, os, secrets, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("SAHER_MOCK_PORT", "5699"))
LOG = os.environ.get("SAHER_MOCK_LOG", os.path.join(HERE, "state", "mock_gmail_log.jsonl"))
DELAY = float(os.environ.get("SAHER_MOCK_DELAY", "0.8"))
HANG = float(os.environ.get("SAHER_MOCK_HANG", "60"))  # longer than Saher's send timeout
KEY = open(os.path.join(os.path.dirname(HERE), "saher-manager", "n8n_key.txt"), encoding="utf-8").read().strip()
lock = threading.Lock()


def record(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with lock, open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def sent_records():
    if not os.path.exists(LOG):
        return []
    return [r for r in (json.loads(l) for l in open(LOG, encoding="utf-8") if l.strip()) if r.get("event") == "sent"]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass  # the client gave up (timeout scenarios)

    def do_POST(self):
        if urlparse(self.path).path != "/webhook/saher-send-gmail":
            return self.reply({"message": "not found"}, 404)
        if self.headers.get("X-Saher-Key") != KEY:
            return self.reply({"ok": False, "error": "forbidden", "definitive": True}, 403)
        raw = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}").get("raw", "")
        msg = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), policy=email.policy.default)
        to = str(msg["To"] or "")
        body = msg.get_body(("plain",))
        rec = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "to": to, "subject": str(msg["Subject"] or ""),
               "message_id": str(msg["Message-ID"] or "").strip("<>"), "approval": str(msg["X-Saher-Approval"] or ""),
               "body": body.get_content()[:2000] if body else "",
               "attachments": [{"name": p.get_filename(), "bytes": len(p.get_payload(decode=True) or b"")}
                               for p in msg.iter_attachments()]}
        time.sleep(DELAY)
        local = to.split("@")[0].split("<")[-1].lower()
        if local == "fail-scope":
            record(dict(rec, event="refused", scenario=local))
            return self.reply({"ok": False, "error": "no_permission", "definitive": True,
                               "detail": "403 - Request had insufficient authentication scopes."})
        if local == "bad-request":
            record(dict(rec, event="refused", scenario=local))
            return self.reply({"ok": False, "error": "bad_request", "definitive": True, "detail": "400 - Invalid To header"})
        if local == "server-error":
            record(dict(rec, event="error", scenario=local))
            return self.reply({"ok": False, "error": "unknown", "definitive": False, "detail": "500 - backendError"})
        ids = {"id": secrets.token_hex(8), "threadId": secrets.token_hex(8)}
        if local == "timeout-lost":
            record(dict(rec, event="lost", scenario=local))
            time.sleep(HANG)
            return self.reply({"ok": False, "error": "unknown", "definitive": False})
        record(dict(rec, **ids, event="sent", scenario=local if local == "timeout-sent" else "normal"))
        if local == "timeout-sent":
            time.sleep(HANG)
        self.reply({"ok": True, **ids, "labelIds": ["SENT"]})

    def do_GET(self):
        u = urlparse(self.path)
        if u.path != "/webhook/saher-sent-check":
            return self.reply({"message": "not found"}, 404)
        if self.headers.get("X-Saher-Key") != KEY:
            return self.reply({"ok": False, "error": "forbidden"}, 403)
        mid = parse_qs(u.query).get("mid", [""])[0]
        hit = next((r for r in sent_records() if r["message_id"] == mid), None)
        record({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "sent_check", "message_id": mid, "found": bool(hit)})
        self.reply({"ok": True, "found": bool(hit), "id": hit["id"] if hit else "", "threadId": hit["threadId"] if hit else ""})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError:
        print(f"Port {PORT} is busy: the mock Gmail is probably already running.")
        sys.exit(1)
    print(f"Mock Gmail on http://127.0.0.1:{PORT} (sends nothing; log: {LOG})")
    srv.serve_forever()
