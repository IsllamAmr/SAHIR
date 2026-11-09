r"""Saher for managers: a local, text-only chat page on 127.0.0.1 that can read your latest five unread Outlook emails
(through the local n8n workflow, read only), summarise them and suggest replies you can copy.
Nothing is sent, moved, deleted, drafted or marked as read. Nothing is written to disk or logged.
Usage: python server.py   (or double-click ..\start_saher_manager.bat)"""
import json, os, re, sys, threading, time, urllib.error, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mail

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOST, PORT = "127.0.0.1", int(os.environ.get("SAHER_PORT", "8768"))
# 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first and adds about 2 s to every request.
OLLAMA = os.environ.get("SAHER_OLLAMA", "http://127.0.0.1:11434")
MODEL = os.environ.get("SAHER_MODEL", "allam-7b-saher")
# Persona v5 is read (never edited) from saher-chat on every turn.
PERSONA_FILE = os.environ.get("SAHER_PERSONA", os.path.join(ROOT, "saher-chat", "persona_allam_v5.txt"))
TEST_MODE = os.environ.get("SAHER_TEST") == "1"  # shows the mock inbox picker
MAIL = "gmail" if os.environ.get("SAHER_MAIL", "").lower() == "gmail" else "outlook"  # which inbox n8n reads
MAIL_NAME = "Gmail" if MAIL == "gmail" else "Outlook"
OPTIONS = {"temperature": 0.2, "top_p": 0.9, "num_ctx": 4096}
CHAT_TOKENS, EMAIL_TOKENS, MAX_MESSAGES = 400, 260, 16

# Appended to persona v5 for this app only, so Saher describes the email feature truthfully.
MAIL_NOTE = """

في هالنسخة من ساهر (نسخة المدراء) فيه زر «آخر ٥ إيميلات غير مقروءة». لما يضغطه المستخدم، برنامج n8n على نفس الجهاز يقرأ آخر خمس إيميلات غير مقروءة من Outlook، وأنت تلخصها وتقترح ردود ينسخها بنفسه. هذا الشي الوحيد اللي تقدر توصله، وما تقدر ترسل ولا تحذف ولا تنقل ولا تعلّم أي إيميل كمقروء ولا تسوي مسودة. إذا طلب منك ترسل أو ترد بنفسك، قل له إنك تقترح الرد بس وهو يرسله من Outlook. إذا سأل عن إيميل، جاوب من الملخصات اللي في المحادثة بس، ولا تخترع شي مو فيها. أي رد تكتبه له يكون على لسانه هو، فلا توقّع باسم ساهر، وخاطب المرسل بصيغة الجمع (لكم، منكم)، ولا تضيف مواعيد أو أرقام ما قالها."""

# Requests to act on mail are answered by code, not by the model: ALLaM sometimes says "أبشر، بنرسل" even though
# nothing here can send. Drafting help ("ساعدني أرد") still goes to the model.
ACT_REQUEST = re.compile(
    r"(^|\s)(أرسل|ارسل|إرسل|ابعث|أبعث|احذف|إحذف|امسح|انقل|حوّل الإيميل|حول الإيميل|علّم|علّمه|علّمها|علمه|علمها|خل[يّ]?ه مقروء|"
    r"ردّ? عليه|ردّ? عليها|ردّ? عليهم|send|forward|delete|move|archive|mark as read|reply to)(\s|$)", re.I)
DRAFT_HELP = re.compile(r"(أبي|ابي|أبغى|ابغى|ودي|بغيت|لازم|أقدر|اقدر) |ساعدني|اكتب|أكتب|صيغ|صياغة|مسودة|كيف|وش أرد|ايش أرد|help me|draft|write", re.I)
ACT_REPLY = ("ما أقدر أسوي هذا. أنا أقرأ آخر الإيميلات غير المقروءة بس، وما أقدر أرسل ولا أحذف ولا أنقل ولا أعلّم شي كمقروء. "
             "إذا تبي، أكتب لك نص الرد هنا وتنسخه وترسله أنت من Outlook.")
CLAIMED_ACTION = re.compile(r"(رديت|ردّيت|بعثت|أرسلنا|تم الرد|بنرسل|بأرسل|راح أرسل|أرسلت|ارسلت|أرسلته|تم الإرسال|تم إرسال|بحذف|حذفت|تم الحذف|نقلته|"
                            r"علّمته|I sent|I've sent|has been sent|I deleted)")
CLAIM_NOTE = "\n\n(تصحيح: ساهر ما يقدر يرسل أو يحذف أو ينقل أي إيميل. ما صار أي شي في بريدك.)"


MAIL_NOTE, ACT_REPLY = MAIL_NOTE.replace("Outlook", MAIL_NAME), ACT_REPLY.replace("Outlook", MAIL_NAME)


def persona_text():
    # The email note goes after the first paragraph, so the end of persona v5 (its recall example) stays last:
    # moving that example changed ALLaM's recall in the v5 tests.
    text = open(PERSONA_FILE, encoding="utf-8").read()
    head, sep, rest = text.partition("\n\n")
    return head + MAIL_NOTE + "\n\n" + rest if sep else text + MAIL_NOTE


sys.stdout.reconfigure(encoding="utf-8")
PAGE = open(os.path.join(HERE, "index.html"), encoding="utf-8").read() \
    .replace("{{MODEL}}", MODEL).replace("{{TEST_MODE}}", "true" if TEST_MODE else "false").replace("{{MAIL}}", MAIL)
if MAIL == "gmail":  # visible wording only; ids such as dotOutlook stay as they are
    PAGE = PAGE.replace("import_into_n8n.bat", "import_gmail_into_n8n.bat").replace("Connect my account", "Sign in with Google")
    PAGE = re.sub(r"(?<![A-Za-z])Outlook(?![A-Za-z])", "Gmail", PAGE)
PAGE = PAGE.encode()
LOGO = open(os.path.join(HERE, "logo.svg"), encoding="utf-8").read().encode()
lock = threading.Lock()  # one model call at a time: the laptop GPU has room for one


class ModelError(Exception):
    pass


def chat_stream(messages, num_predict):
    body = json.dumps({"model": MODEL, "stream": True, "keep_alive": "30m", "messages": messages,
                       "options": dict(OPTIONS, num_predict=num_predict)}).encode()
    req = urllib.request.Request(OLLAMA + "/api/chat", body, {"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=600)
    except urllib.error.HTTPError as e:
        raise ModelError(f"ollama HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}")
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise ModelError(f"ollama unreachable: {e}")
    with r:
        for line in r:
            d = json.loads(line)
            if d.get("error"):
                raise ModelError(d["error"])
            if d.get("message", {}).get("content"):
                yield d["message"]["content"]


def chat_once(messages, num_predict):
    return "".join(chat_stream(messages, num_predict))


def n8n_running():
    try:
        with urllib.request.urlopen("http://127.0.0.1:5678/healthz", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def ollama_running():
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=2) as r:
            return any(m["name"].split(":")[0] == MODEL.split(":")[0] for m in json.load(r).get("models", []))
    except Exception:
        return False


def summarise(e):
    raw = chat_once(mail.email_messages(e), EMAIL_TOKENS)
    out = mail.finish(e, raw)
    if out["reply"] and (mail.singular(out["reply"]) or mail.gendered(out["reply"])):
        retry = mail.finish(e, chat_once(mail.email_messages(e, retry=True), EMAIL_TOKENS))
        score = lambda o: len(mail.gendered(o["reply"])) * 10 + len(mail.singular(o["reply"]))
        if score(retry) <= score(out):
            out = retry
        out["retried"] = True
    if mail.needs_english(e, out["reply"]) and not out["risky"]:
        # ALLaM often drafts in Arabic even for English emails; a short English-only prompt fixes that.
        en = chat_once(mail.english_reply_messages(e), EMAIL_TOKENS).strip()
        if en and mail.is_english(en):
            out["reply"] = en
    out["check_wording"] = mail.gendered(out["reply"])
    out["check_facts"] = mail.unsupported(out["reply"], e)
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the console free of chat and email content
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
            return self._json({"n8n": n8n_running(), "model": ollama_running(), "model_name": MODEL})
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
        if self.path not in ("/turn", "/inbox"):
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
            (self.turn if self.path == "/turn" else self.inbox)(req, emit)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # the page stopped, reset or closed mid-reply
        except ModelError as e:
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

    def turn(self, req, emit):
        history = [{"role": m["role"], "content": str(m["content"])[:6000]} for m in req.get("messages", [])
                   if m.get("role") in ("user", "assistant")]
        text = req["text"].strip()
        if ACT_REQUEST.search(text) and not DRAFT_HELP.search(text):
            emit({"type": "text", "delta": ACT_REPLY})
            return emit({"type": "done", "reply": ACT_REPLY, "ms": 0})
        persona = persona_text()
        msgs = [{"role": "system", "content": persona}] + (history + [{"role": "user", "content": text}])[-MAX_MESSAGES:]
        t0 = time.perf_counter()
        reply = ""
        with lock:
            for delta in chat_stream(msgs, CHAT_TOKENS):
                reply += delta
                emit({"type": "text", "delta": delta})
        if CLAIMED_ACTION.search(reply):
            reply += CLAIM_NOTE
            emit({"type": "text", "delta": CLAIM_NOTE})
        emit({"type": "done", "reply": reply.strip(), "ms": round((time.perf_counter() - t0) * 1000)})

    def inbox(self, req, emit):
        source = str(req.get("source") or MAIL)
        if not TEST_MODE and source != MAIL:
            source = MAIL
        t0 = time.perf_counter()
        res = mail.fetch_unread(source)
        if not res["ok"]:
            return emit({"type": "error", "error": res["error"], "detail": res.get("detail", ""), "source": res["source"]})
        public = [{k: e[k] for k in ("id", "from_name", "from_address", "subject", "received", "has_attachments",
                                     "importance")} for e in res["emails"]]
        emit({"type": "list", "source": res["source"], "emails": public})
        for e in res["emails"]:
            with lock:
                out = summarise(e)
            emit(dict(out, type="email"))
        emit({"type": "done", "ms": round((time.perf_counter() - t0) * 1000), "count": len(res["emails"])})


if __name__ == "__main__":
    # On Windows SO_REUSEADDR lets a second server bind a port that is already taken, and the two then split the
    # requests. Without it, starting Saher twice fails loudly instead.
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print(f"Port {PORT} is already in use: Saher (or another app) is already running. Open http://{HOST}:{PORT}/ "
              "or close the other window first.")
        sys.exit(1)
    url = f"http://{HOST}:{PORT}/"
    print(f"Saher for managers is running at {url}" + ("  [TEST MODE: mock inboxes available]" if TEST_MODE else ""))
    print(f"Model: {MODEL} via {OLLAMA}. Persona: {PERSONA_FILE}")
    print("Close it with the 'إنهاء' button on the page, or press Ctrl+C here.")
    if not os.environ.get("SAHER_NO_BROWSER"):
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    print("Saher stopped.")
