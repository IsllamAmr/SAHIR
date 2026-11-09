r"""Approved email sending for Saher (send mode only: SAHER_SEND=mock or gmail; off by default).

Rules enforced here, in code:
- A message is sent only by send_approved(draft_id, hash): the page sends back the fingerprint (sha256) of the exact
  message it showed. Any change (recipient, subject, body, an attachment's bytes) gives a new fingerprint, so the old
  approval no longer matches and the user must approve again.
- One send per approved message: every attempt is written to state\sends.jsonl BEFORE the network call. A message
  whose fingerprint is already "sending", "sent" or "unknown" is refused, also after a restart.
- No automatic resend. If the outcome is unknown (timeout, connection lost, Gmail 5xx), Saher searches Gmail for the
  message's own Message-ID (read-only) up to 3 times. Only if the user then checks again and it is still not found
  can the same message be approved again.
- "Sent" is reported only with Gmail's message id and thread id (from the send reply or from the Sent search).
- Attachments only from SAHIR\workspace\ (tools.safe_path), at most 4 MB in total, re-hashed right before sending.
Gmail is reached through local n8n (credential "Gmail - Saher (send only)", scope gmail.send). mock_gmail.py
answers on the same paths for tests and records every request."""
import base64, datetime, hashlib, json, mimetypes, os, re, threading, time, uuid
import urllib.error, urllib.parse, urllib.request
from email.message import EmailMessage
from email.utils import formataddr
import tools

HERE = os.path.dirname(os.path.abspath(__file__))
MODE = os.environ.get("SAHER_SEND", "off").lower()  # off | mock | gmail
MOCK_URL = os.environ.get("SAHER_MOCK_GMAIL", "http://127.0.0.1:5699")
N8N = os.environ.get("SAHER_N8N_BASE", "http://127.0.0.1:5678")
BASE = MOCK_URL if MODE == "mock" else N8N
SEND_URL = BASE + "/webhook/saher-send-gmail"
CHECK_URL = BASE + "/webhook/saher-sent-check"
TIMEOUT = float(os.environ.get("SAHER_SEND_TIMEOUT", "45"))  # n8n's own Gmail call times out at 30 s
CHECK_WAITS = [float(x) for x in os.environ.get("SAHER_CHECK_WAITS", "2,4,8").split(",")]
MAX_ATTACH = 4 * 1024 * 1024
STATE = os.environ.get("SAHER_SEND_STATE", os.path.join(HERE, "state", "sends.jsonl"))
KEY_FILE = os.path.join(os.path.dirname(HERE), "saher-manager", "n8n_key.txt")
ADDRESS = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
BLOCKING = {"sending", "sent", "unknown"}  # a fingerprint in one of these states can't be sent again

_lock = threading.Lock()
DRAFTS = {}  # draft id -> draft (in memory only; drafts are not saved)


def _key():
    return open(KEY_FILE, encoding="utf-8").read().strip()


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---------------- drafts and fingerprints ----------------
def file_info(rel):
    full = tools.safe_path(rel)
    if not full or not os.path.isfile(full):
        return None
    data = open(full, "rb").read()
    return {"path": os.path.relpath(full, tools.WORKSPACE).replace("\\", "/"), "name": os.path.basename(full),
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def fingerprint(d):
    canon = {"to": d["to"].lower(), "to_name": d.get("to_name", ""), "subject": d["subject"], "body": d["body"],
             "attachments": [[a["path"], a["sha256"]] for a in d["attachments"]]}
    return hashlib.sha256(json.dumps(canon, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def check_fields(to, subject, body, attachments):
    """Returns a list of problems (Arabic, for the page). Empty list = the draft is valid."""
    problems = []
    if not ADDRESS.match(to or ""):
        problems.append("عنوان المستلم غير صالح.")
    if not (subject or "").strip():
        problems.append("الموضوع فارغ.")
    if not (body or "").strip():
        problems.append("نص الرسالة فارغ.")
    if re.search(r"[\r\n]", (subject or "") + (to or "")):
        problems.append("الموضوع أو العنوان يحتوي على سطر جديد.")
    if sum(a["size"] for a in attachments) > MAX_ATTACH:
        problems.append("حجم المرفقات أكبر من 4 ميغابايت.")
    return problems


def make_draft(to, to_name, subject, body, attach_paths, source):
    atts = []
    for p in attach_paths:
        info = file_info(p)
        if info and info["path"] not in [a["path"] for a in atts]:
            atts.append(info)
    d = {"id": uuid.uuid4().hex[:12], "to": (to or "").strip(), "to_name": (to_name or "").strip(),
         "subject": re.sub(r"\s+", " ", subject or "").strip()[:200], "body": (body or "").strip()[:8000],
         "attachments": atts, "version": 1, "created": now_iso(), "source": source, "status": "pending", "result": None}
    d["hash"] = fingerprint(d)
    d["problems"] = check_fields(d["to"], d["subject"], d["body"], atts)
    with _lock:
        DRAFTS[d["id"]] = d
    return public(d)


def update_draft(draft_id, to, subject, body, attach_paths):
    """An edit from the approval card. It always makes a new version with a new fingerprint (new approval needed)."""
    with _lock:
        d = DRAFTS.get(draft_id)
        if not d:
            return {"ok": False, "error": "المسودة غير موجودة. ربما أُعيد تشغيل ساهر."}
        if d["status"] in ("sending", "sent"):
            return {"ok": False, "error": "هذه الرسالة أُرسلت أو قيد الإرسال، ولا يمكن تعديلها."}
        atts = [i for i in (file_info(p) for p in attach_paths) if i]
        if (to or "").strip().lower() != d["to"].lower():
            d["to_name"] = ""  # the name belonged to the old address
        d.update(to=(to or "").strip(), subject=re.sub(r"\s+", " ", subject or "").strip()[:200],
                 body=(body or "").strip()[:8000], attachments=atts, version=d["version"] + 1, status="pending",
                 result=None)
        d["hash"] = fingerprint(d)
        d["problems"] = check_fields(d["to"], d["subject"], d["body"], atts)
        return {"ok": True, "draft": public(d)}


def cancel_draft(draft_id):
    with _lock:
        d = DRAFTS.get(draft_id)
        if d and d["status"] in ("pending", "failed", "not_found"):
            d["status"] = "cancelled"
            return {"ok": True, "draft": public(d)}
        return {"ok": False, "error": "لا يمكن إلغاء هذه المسودة الآن."}


def public(d):
    return {k: d[k] for k in ("id", "to", "to_name", "subject", "body", "attachments", "version", "hash", "status",
                              "result", "problems")} | {"mode": MODE}


# ---------------- send log (survives restarts) ----------------
def _log(rec):
    """Raises if the log can't be written: the "sending" record must exist before anything is sent (fail closed)."""
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    line = json.dumps(dict(rec, time=now_iso(), mode=MODE), ensure_ascii=False) + "\n"
    for attempt in range(6):  # Windows sometimes holds the file briefly (indexer, antivirus)
        try:
            with open(STATE, "a", encoding="utf-8") as f:
                f.write(line)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.3)


def last_status(h):
    status = None
    if os.path.exists(STATE):
        for line in open(STATE, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("hash") == h and r.get("mode") == MODE:
                status = r
    return status


# ---------------- MIME and HTTP ----------------
def message_id(h):
    return f"saher-{h[:40]}@saher.local"


def build_raw(d):
    m = EmailMessage()
    m["To"] = formataddr((d["to_name"], d["to"])) if d.get("to_name") else d["to"]
    m["Subject"] = d["subject"]
    m["Message-ID"] = f"<{message_id(d['hash'])}>"
    m["X-Saher-Approval"] = d["hash"]
    m.set_content(d["body"], charset="utf-8")
    for a in d["attachments"]:
        data = open(tools.safe_path(a["path"]), "rb").read()
        ctype = mimetypes.guess_type(a["name"])[0] or "application/octet-stream"
        main, sub = ctype.split("/", 1)
        m.add_attachment(data, maintype=main, subtype=sub, filename=a["name"])
    return base64.urlsafe_b64encode(m.as_bytes()).decode()


def _call(url, body=None, timeout=TIMEOUT):
    """Returns (json or None, kind): kind = 'ok' | 'timeout' | 'unreachable' | 'http_<code>'."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data, {"Content-Type": "application/json", "X-Saher-Key": _key()},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r), "ok"
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}"), f"http_{e.code}"
        except ValueError:
            return None, f"http_{e.code}"
    except (TimeoutError, OSError) as e:  # socket.timeout and connection errors are OSErrors
        reason = getattr(e, "reason", e)
        if isinstance(reason, ConnectionRefusedError):
            return None, "refused"  # nothing listening: the request never left this computer
        if isinstance(reason, TimeoutError) or "timed out" in str(e).lower():
            return None, "timeout"
        return None, "connection_lost"  # reset/aborted: the message may or may not have been sent


def check_sent(h):
    """Searches Gmail (read-only) for the message's own Message-ID. Returns {'found': bool, ...} or {'error': ...}."""
    j, kind = _call(CHECK_URL + "?mid=" + urllib.parse.quote(message_id(h)), timeout=30)
    if kind != "ok" or not j or not j.get("ok"):
        return {"error": (j or {}).get("error") or kind}
    return {"found": bool(j.get("found")), "id": j.get("id", ""), "threadId": j.get("threadId", "")}



def send_approved(draft_id, approved_hash, progress=lambda e: None):
    """Sends one approved draft. Returns the draft (public) with status sent | failed | unknown | refused."""
    with _lock:
        d = DRAFTS.get(draft_id)
        if not d:
            return {"ok": False, "error": "المسودة غير موجودة. ربما أُعيد تشغيل ساهر، فاطلب الرسالة من جديد."}
        if approved_hash != d["hash"]:
            return {"ok": False, "error": "الرسالة تغيّرت بعد عرضها. راجع النسخة الجديدة ووافق عليها مرة أخرى."}
        if d["status"] == "cancelled":
            return {"ok": False, "error": "أُلغيت هذه المسودة."}
        last = last_status(d["hash"])
        if last and last["status"] in BLOCKING:
            return {"ok": False, "error": "لن أرسل هذه الرسالة مرة ثانية: " + {
                "sent": "أُرسلت من قبل.", "sending": "إرسالها قيد التنفيذ.",
                "unknown": "نتيجة الإرسال السابق غير معروفة. اضغط «تحقق من المرسل» أولًا."}[last["status"]]}
        # Attachments are re-read now: if a file changed since approval, the fingerprint no longer matches.
        fresh = [file_info(a["path"]) for a in d["attachments"]]
        if any(f is None or f["sha256"] != a["sha256"] for f, a in zip(fresh, d["attachments"])):
            return {"ok": False, "error": "أحد المرفقات تغيّر أو حُذف بعد الموافقة. لم أرسل شيئًا."}
        problems = check_fields(d["to"], d["subject"], d["body"], d["attachments"])
        if problems:
            return {"ok": False, "error": " ".join(problems)}
        approval = uuid.uuid4().hex
        d["status"] = "sending"
        _log({"hash": d["hash"], "approval": approval, "status": "sending", "to": d["to"], "subject": d["subject"],
              "attachments": [a["name"] for a in d["attachments"]]})
    progress({"stage": "sending"})
    raw = build_raw(d)
    j, kind = _call(SEND_URL, {"raw": raw})
    rec = {"hash": d["hash"], "approval": approval, "to": d["to"], "subject": d["subject"]}
    if kind == "ok" and j and j.get("ok") and j.get("id"):
        res = {"status": "sent", "id": j["id"], "threadId": j.get("threadId", ""), "labelIds": j.get("labelIds", []),
               "verified_by": "send_reply"}
    elif j and j.get("ok") is False and j.get("definitive"):
        res = {"status": "failed", "error": j.get("error", "gmail_error"), "detail": str(j.get("detail", ""))[:300]}
    elif kind in ("http_403", "http_401") and j and j.get("error") == "forbidden":
        res = {"status": "failed", "error": "forbidden", "detail": "n8n refused Saher's key"}
    elif kind == "refused":
        # Connection refused before anything was sent (n8n not running): nothing reached Gmail.
        res = {"status": "failed", "error": "n8n_down", "detail": "connection refused"}
    else:
        res = {"status": "unknown", "error": (j or {}).get("error") or kind}
    if res["status"] == "unknown":
        _log(dict(rec, status="unknown", error=res["error"]))
        progress({"stage": "checking"})
        for wait in CHECK_WAITS:
            time.sleep(wait)
            c = check_sent(d["hash"])
            if c.get("found"):
                res = {"status": "sent", "id": c["id"], "threadId": c["threadId"], "verified_by": "sent_search"}
                break
            res["check"] = c.get("error") or "not_found"
    _log(dict(rec, status=res["status"], **{k: res[k] for k in ("id", "threadId", "error", "verified_by") if k in res}))
    with _lock:
        d["status"] = res["status"]
        d["result"] = res
    return {"ok": res["status"] == "sent", "draft": public(d)}


def recheck(draft_id):
    """The user's «تحقق من المرسل» button for an unknown outcome. If still not found, the same message may be
    approved again (state not_found); nothing is resent automatically."""
    with _lock:
        d = DRAFTS.get(draft_id)
    if not d:
        return {"ok": False, "error": "المسودة غير موجودة."}
    last = last_status(d["hash"])
    if not last or last["status"] != "unknown":
        return {"ok": False, "error": "لا يوجد إرسال بنتيجة غير معروفة لهذه الرسالة."}
    c = check_sent(d["hash"])
    if c.get("error"):
        return {"ok": False, "error": f"تعذّر البحث في Gmail ({c['error']}). لم أغيّر شيئًا."}
    rec = {"hash": d["hash"], "to": d["to"], "subject": d["subject"]}
    if c["found"]:
        res = {"status": "sent", "id": c["id"], "threadId": c["threadId"], "verified_by": "sent_search"}
    else:
        res = {"status": "not_found", "error": "not_found_after_check"}
    _log(dict(rec, **res))
    with _lock:
        d["status"] = res["status"]
        d["result"] = res
    return {"ok": True, "draft": public(d)}
