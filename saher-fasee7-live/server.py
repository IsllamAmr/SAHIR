"""Saher hands-free trial (experimental, separate from saher-app and saher-voice).
Speech -> text (faster-whisper small, CPU) -> ALLaM via local Ollama -> one short sentence -> a voice picked with SAHER_TTS:
  fasee7 - Fasee7 Najdi Small (child process in venv-voxcpm, GPU). Saudi, but ~20x slower than real time here.
  piper  - Piper ar_JO-kareem (in this process, CPU). Fastest: well under a second.
  namaa  - NAMAA Saudi TTS (child process in venv-chatterbox, GPU). Saudi, a few seconds per sentence.
The page listens hands-free: it detects when you start and stop talking, and ignores the mic while Saher is thinking or speaking.
The conversation lives only in the open browser tab. Nothing is written to disk or logged.

Timings for each turn are measured from the moment the recorded speech reaches the server:
  transcribed   - speech recognition finished
  first_text    - first token from ALLaM
  sentence      - the one-sentence reply is final (cut in code if ALLaM runs on)
  first_chunk   - first piece of audio
  audio_ready   - the whole reply is synthesized, so it can play without stalling
Usage: python server.py   (or double-click start_fasee7_live.bat)"""
import base64, json, os, re, subprocess, sys, threading, time, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np
from faster_whisper import WhisperModel

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOST, PORT = "127.0.0.1", int(os.environ.get("SAHER_PORT", "8770"))
# 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first and adds about 2 s to every request.
OLLAMA = os.environ.get("SAHER_OLLAMA", "http://127.0.0.1:11434") + "/api/chat"
MODEL = os.environ.get("SAHER_MODEL", "allam-7b-saher")
# SAHER_STYLE=fusha (the default here): Modern Standard Arabic only, persona_fusha.txt in this folder.
# SAHER_STYLE=saudi: the white Saudi dialect persona from saher-chat (read only).
STYLE = os.environ.get("SAHER_STYLE", "fusha")
PERSONA_FILE = os.environ.get("SAHER_PERSONA", os.path.join(HERE, "persona_fusha.txt") if STYLE == "fusha"
                              else os.path.join(ROOT, "saher-chat", "persona_allam_v4.txt"))
VOICE_NOTE = ("\n\nمهم جداً: أنت الآن تتحدث بالصوت. أجب بجملة واحدة قصيرة فقط، أقل من عشر كلمات، "
              "وباللغة العربية الفصحى وحدها. لا تستخدم قوائم ولا رموزاً ولا أرقاماً." if STYLE == "fusha" else
              "\n\nمهم جداً: أنت الحين تتكلم بالصوت. فرد بجملة وحدة قصيرة بس، أقل من عشر كلمات، "
              "حتى لو الأمثلة فوق أطول. لا تستخدم قوائم ولا رموز ولا أرقام.")
OPTIONS = {"temperature": 0.2, "top_p": 0.9, "num_ctx": 4096, "num_predict": 48}
MAX_MESSAGES = 12
MAX_WORDS = int(os.environ.get("SAHER_MAX_WORDS", "14"))
ASR_SIZE = os.environ.get("SAHER_ASR", "small")
TTS = os.environ.get("SAHER_TTS", "fasee7")
VENVS = {"fasee7": "venv-voxcpm", "namaa": "venv-chatterbox"}
WORKERS = {"fasee7": "tts_worker.py", "namaa": "namaa_worker.py"}
LABELS = {"fasee7": "Fasee7 Najdi Small, default voice (GPU, bf16)", "namaa": "NAMAA Saudi TTS, default voice (GPU)",
          "piper": "Piper ar_JO-kareem (CPU)"}
NOTES = {"fasee7": " صوت فصيح بطيء على هالجهاز، فالرد ياخذ تقريباً دقيقة قبل ما يطلع.",
         "namaa": " صوت نماء ياخذ كم ثانية يجهز الجملة قبل ما يتكلم.", "piper": ""}

END = re.compile(r"[.!؟?\n]")
SOFT = re.compile(r"[،,؛:]")
CLEAN = re.compile(r"[*#_`>\[\](){}\"«»]|[\U0001F000-\U0001FAFF☀-➿]")
sys.stdout.reconfigure(encoding="utf-8")


def one_sentence(text, final=False):
    """Returns (sentence, finished, cut). Stops at the first sentence end once there are at least 3 words,
    and never lets the reply run past MAX_WORDS words. ALLaM sometimes opens by echoing the user's question
    ("أفضل وقت أمشي فيه؟") and answers after it, so a leading question is dropped when an answer follows it."""
    start = 0
    for m in END.finditer(text):
        part = text[start:m.end()]
        if len(part.split()) < 3:
            continue
        if part.strip().endswith(("؟", "?")) and start == 0:
            if not text[m.end():].strip():
                return part.strip(), final, False  # wait: maybe the answer comes next
            start = m.end()
            continue
        return part.strip(), True, False
    body = text[start:]
    words = body.split()
    if len(words) > MAX_WORDS:
        head = " ".join(words[:MAX_WORDS])
        soft = [m.end() for m in SOFT.finditer(head)]
        if soft and len(head[:soft[-1]].split()) >= 4:
            head = head[:soft[-1]]
        return head.rstrip("،,؛: ").strip(), True, True
    return body.strip(), final, False


class Worker:
    """A voice that runs as a child process in its own venv (see tts_worker.py for the protocol). One reply at a time."""
    def __init__(self):
        VENV_PY = os.path.join(ROOT, "saher-tts-compare", VENVS[TTS], "Scripts", "python.exe")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        self.p = subprocess.Popen([VENV_PY, os.path.join(HERE, WORKERS[TTS])], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=None, env=env, cwd=HERE,
                                  text=True, encoding="utf-8", bufsize=1)
        ready = self._read()
        if ready.get("type") != "ready":
            raise RuntimeError(f"{TTS} failed to load: {ready}")
        self.sample_rate, self.load_s = ready["sample_rate"], ready["load_s"]

    def _read(self):
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError(f"{TTS} process exited (code {self.p.poll()}); see the console above for the reason")
        return json.loads(line)

    def speak(self, text):
        self.p.stdin.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        while True:
            e = self._read()
            yield e
            if e["type"] in ("done", "error"):
                return


print(f"Style: {STYLE}, persona: {PERSONA_FILE}", flush=True)
print("Loading Whisper...", flush=True)
asr = WhisperModel(ASR_SIZE, device="cpu", compute_type="int8", cpu_threads=4)
asr.transcribe(np.zeros(16000, np.float32), language="ar", beam_size=1)
class Piper:
    """Piper in this process: the same speak() events as Worker, so turn() doesn't care which voice it has."""
    p = None

    def __init__(self):
        from piper import PiperVoice
        t = time.perf_counter()
        self.voice = PiperVoice.load(os.environ.get("SAHER_VOICE", os.path.join(ROOT, "saher-voice", "voices", "ar_JO-kareem-medium.onnx")))
        self.sample_rate = self.voice.config.sample_rate
        list(self.voice.synthesize("هلا"))
        self.load_s = round(time.perf_counter() - t, 1)

    def speak(self, text):
        t0 = time.perf_counter()
        pcm = b"".join(c.audio_int16_bytes for c in self.voice.synthesize(text))
        ms = round((time.perf_counter() - t0) * 1000)
        yield {"type": "chunk", "pcm16": base64.b64encode(pcm).decode(), "ms": ms}
        yield {"type": "done", "ms": ms, "audio_s": round(len(pcm) / 2 / self.sample_rate, 2)}


print(f"Loading the {TTS} voice...", flush=True)
tts = Piper() if TTS == "piper" else Worker()
print(f"{TTS} ready in {tts.load_s}s, {tts.sample_rate} Hz", flush=True)
lock = threading.Lock()


def chat(messages, num_predict=None):
    persona = open(PERSONA_FILE, encoding="utf-8").read() + VOICE_NOTE
    opts = dict(OPTIONS, **({"num_predict": num_predict} if num_predict else {}))
    body = json.dumps({"model": MODEL, "stream": True, "options": opts, "keep_alive": "30m",
                       "messages": [{"role": "system", "content": persona}] + messages[-MAX_MESSAGES:]}).encode()
    req = urllib.request.Request(OLLAMA, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:  # leaving the loop early closes it, which stops ALLaM
        for line in r:
            d = json.loads(line)
            if d.get("error"):
                raise RuntimeError(d["error"])
            if d.get("message", {}).get("content"):
                yield d["message"]["content"]


print("Warming up ALLaM...", flush=True)
list(chat([{"role": "user", "content": "هلا"}], num_predict=1))


def turn(audio16k, history, emit):
    with lock:
        t0 = time.perf_counter()
        ms = lambda: round((time.perf_counter() - t0) * 1000)
        times = {}
        segs, _ = asr.transcribe(audio16k, language="ar", beam_size=1, vad_filter=False,
                                 condition_on_previous_text=False, without_timestamps=True)
        text = " ".join(s.text.strip() for s in segs).strip()
        times["transcribed"] = ms()
        emit({"type": "transcript", "text": text, "ms": times["transcribed"]})
        if not text:
            emit({"type": "done", "reply": "", "times": times})
            return

        raw, sentence, cut = "", "", False
        for delta in chat(history + [{"role": "user", "content": text}]):
            times.setdefault("first_text", ms())
            raw += delta
            sentence, finished, cut = one_sentence(CLEAN.sub("", raw))
            emit({"type": "text", "text": sentence, "ms": ms()})
            if finished:
                break
        else:
            sentence, _, cut = one_sentence(CLEAN.sub("", raw), final=True)
        times["sentence"] = ms()
        emit({"type": "reply", "text": sentence, "cut": cut, "raw_words": len(raw.split()), "ms": times["sentence"]})
        if not re.search(r"[؀-ۿA-Za-z0-9]", sentence):
            emit({"type": "done", "reply": "", "times": times})
            return

        for e in tts.speak(sentence):
            if e["type"] == "chunk":
                times.setdefault("first_chunk", times["sentence"] + e["ms"])
                emit({"type": "audio", "pcm16": e["pcm16"], "sample_rate": tts.sample_rate, "ms": ms()})
            elif e["type"] == "done":
                times["audio_ready"] = times["sentence"] + e["ms"]
                times["audio_s"] = e["audio_s"]
            else:
                raise RuntimeError(f"{TTS}: " + e["error"])
        emit({"type": "done", "reply": sentence, "times": times})


PAGE = open(os.path.join(HERE, "index.html"), encoding="utf-8").read().replace(
    "{{SETUP}}", f"{MODEL} · Whisper {ASR_SIZE} (CPU) · {LABELS[TTS]}").replace("{{NOTE}}", NOTES[TTS]).encode()


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
        if self.path != "/turn":
            return self.send_error(404)
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        audio = np.frombuffer(base64.b64decode(req["pcm16"]), np.int16).astype(np.float32) / 32768
        history = [{"role": m["role"], "content": m["content"]} for m in req.get("messages", [])
                   if m.get("role") in ("user", "assistant")]
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.end_headers()

        gone = []

        def emit(e):
            # If the page closed mid-reply, keep going quietly so the voice's output is fully drained for the next turn.
            if gone:
                return
            try:
                self.wfile.write((json.dumps(e, ensure_ascii=False) + "\n").encode())
                self.wfile.flush()
            except OSError:
                gone.append(True)
        try:
            turn(audio, history, emit)
        except Exception as e:
            print("turn failed:", type(e).__name__, e, flush=True)
            try:
                emit({"type": "error", "error": f"{type(e).__name__}: {e}"})
            except OSError:
                pass


class Server(ThreadingHTTPServer):
    # On Windows, address reuse lets a second copy bind the same port silently and steal requests from the first.
    allow_reuse_address = False


try:
    server = Server((HOST, PORT), Handler)
except OSError:
    print(f"Port {PORT} is already in use: this launcher is probably already open in another window.", flush=True)
    if tts.p is not None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(tts.p.pid)], capture_output=True)
    os._exit(1)
url = f"http://{HOST}:{PORT}/"
print(f"Saher hands-free ({TTS}) is running at {url}", flush=True)
print("Close it with the 'إنهاء' button on the page, or press Ctrl+C here.", flush=True)
if not os.environ.get("SAHER_NO_BROWSER"):
    webbrowser.open(url)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    print("Stopping...", flush=True)
    # Closing stdin ends the worker's loop. The venv's python.exe is a launcher with the real interpreter as its
    # child, so a plain kill would leave Fasee7 holding RAM; taskkill /T takes the whole tree if it doesn't exit.
    try:
        if tts.p is None:
            raise SystemExit
        tts.p.stdin.close()
        tts.p.wait(15)
    except SystemExit:
        pass
    except Exception:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(tts.p.pid)], capture_output=True)
    print("Stopped.", flush=True)
    os._exit(0)
