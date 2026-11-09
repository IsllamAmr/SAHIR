r"""EXPERIMENT: Saher with an ElevenLabs voice instead of Piper. Not open source and not self-hosted:
the text of every spoken reply is sent to ElevenLabs and uses your credits. Speech recognition (Whisper) and
the reply (ALLaM via Ollama) still run on this computer.
Copied from ..\saher-app\pipeline.py, which stays untouched. Nothing is written to disk or logged."""
import json, os, queue, re, threading, time, urllib.request
import numpy as np
import requests
from faster_whisper import WhisperModel

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load_env(path):
    """Reads KEY=value lines from .env next to this file. Values already set in the environment win."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8-sig"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env(os.path.join(HERE, ".env"))

# 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first and adds about 2 s to every request.
OLLAMA = os.environ.get("SAHER_OLLAMA", "http://127.0.0.1:11434") + "/api/chat"
MODEL = os.environ.get("SAHER_MODEL", "allam-7b-saher")
PERSONA_FILE = os.environ.get("SAHER_PERSONA", os.path.join(ROOT, "saher-chat", "persona_allam_v4.txt"))
VOICE_NOTE = ("\n\nأنت الحين تتكلم بالصوت، فخل ردك قصير جداً: جملة أو جملتين بس. "
              "لا تستخدم قوائم ولا رموز ولا أرقام بين أقواس.")
OPTIONS = {"temperature": 0.2, "top_p": 0.9, "num_ctx": 4096}
SPOKEN_TOKENS, TYPED_TOKENS = 90, 400
MAX_MESSAGES = 16
ASR_SIZE = os.environ.get("SAHER_ASR", "small")
ASR_DEVICE = os.environ.get("SAHER_ASR_DEVICE", "cpu")  # keep on CPU: 6 GB VRAM is all ALLaM's

# ElevenLabs. The key is read from ELEVENLABS_API_KEY (environment or .env) and is never printed or sent anywhere else.
XI_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
XI_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "rpGHcNQJvO8dFNNFNj1v")
XI_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")  # lowest-latency multilingual model, has Arabic
XI_RATE = 22050
XI_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{XI_VOICE}/stream?output_format=pcm_{XI_RATE}"

END = re.compile(r"[.!؟?\n]")
SOFT = re.compile(r"[،,؛:]")
FIRST_WORDS = 6
CLEAN = re.compile(r"[*#_`>\[\](){}\"«»]|[\U0001F000-\U0001FAFF☀-➿]")


class TTSError(Exception):
    pass


class Pipeline:
    def __init__(self):
        if not XI_KEY:
            raise SystemExit("No ElevenLabs key found. Put ELEVENLABS_API_KEY=... in the .env file in this folder "
                             "(see README.md), then start again.")
        compute = "int8" if ASR_DEVICE == "cpu" else "int8_float16"
        self.asr = WhisperModel(ASR_SIZE, device=ASR_DEVICE, compute_type=compute, cpu_threads=4)
        self.sample_rate = XI_RATE
        self.http = requests.Session()  # keeps the TLS connection to ElevenLabs open between sentences
        self.http.headers.update({"xi-api-key": XI_KEY, "Accept": "audio/pcm"})
        self.lock = threading.Lock()  # one turn at a time

    def warm_up(self):
        self.asr.transcribe(np.zeros(16000, np.float32), language="ar", beam_size=1)
        list(self._chat([{"role": "user", "content": "هلا"}], spoken=False, num_predict=1))
        try:  # open the connection only; no speech is generated, so no credits are used
            self.http.head("https://api.elevenlabs.io/", timeout=10)
        except requests.RequestException:
            pass

    def transcribe(self, audio16k):
        segs, _ = self.asr.transcribe(audio16k, language="ar", beam_size=1, vad_filter=False,
                                      condition_on_previous_text=False, without_timestamps=True)
        return " ".join(s.text.strip() for s in segs).strip()

    def tts_stream(self, text, previous_text=""):
        """Yields PCM16 audio for text as ElevenLabs streams it back."""
        body = {"text": text, "model_id": XI_MODEL, "language_code": "ar"}
        if previous_text:
            body["previous_text"] = previous_text[-300:]  # keeps the intonation continuous across sentences
        try:
            r = self.http.post(XI_URL, json=body, stream=True, timeout=(10, 60))
        except requests.RequestException as e:
            raise TTSError(f"ما قدرت أوصل لـ ElevenLabs ({type(e).__name__})")
        with r:
            if r.status_code != 200:
                try:
                    detail = r.json().get("detail")
                    detail = detail.get("message") or detail.get("status") if isinstance(detail, dict) else detail
                except ValueError:
                    detail = ""
                raise TTSError(f"ElevenLabs رد بخطأ {r.status_code}: {detail or r.reason}")
            carry = b""
            for part in r.iter_content(chunk_size=8820):  # about 0.2 s of audio per piece
                part = carry + part
                cut = len(part) - len(part) % 2
                carry = part[cut:]
                if cut:
                    yield part[:cut]

    def _chat(self, messages, spoken, num_predict=None):
        persona = open(PERSONA_FILE, encoding="utf-8").read() + (VOICE_NOTE if spoken else "")
        opts = dict(OPTIONS, num_predict=num_predict or (SPOKEN_TOKENS if spoken else TYPED_TOKENS))
        body = json.dumps({"model": MODEL, "stream": True, "options": opts, "keep_alive": "30m",
                           "messages": [{"role": "system", "content": persona}] + messages[-MAX_MESSAGES:]}).encode()
        req = urllib.request.Request(OLLAMA, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            for line in r:
                d = json.loads(line)
                if d.get("error"):
                    raise RuntimeError(d["error"])
                if d.get("message", {}).get("content"):
                    yield d["message"]["content"]

    def turn(self, history, emit, text, speak=True, spoken=False):
        """One turn: ALLaM streams the reply; each sentence goes to ElevenLabs as soon as it is complete,
        and its audio is passed to the page piece by piece as it arrives."""
        with self.lock:
            t0 = time.perf_counter()
            ms = lambda: round((time.perf_counter() - t0) * 1000)
            times = {}

            chunks, self.queued = queue.Queue(), 0
            def voice():
                said, failed = "", False
                while (chunk := chunks.get()) is not None:
                    if failed:
                        continue
                    try:
                        for pcm in self.tts_stream(chunk, said):
                            times.setdefault("first_audio", ms())
                            emit({"type": "audio", "pcm16": pcm, "sample_rate": self.sample_rate, "ms": ms()})
                        said += " " + chunk
                    except TTSError as e:
                        failed = True  # the text keeps coming; only the voice stops
                        try:
                            emit({"type": "tts_error", "error": str(e)})
                        except OSError:
                            pass
                    except OSError:
                        failed = True  # the page stopped or closed: send nothing more to ElevenLabs
                times["tts_done"] = ms()
            speaker = threading.Thread(target=voice, daemon=True)
            if speak:
                speaker.start()

            reply, pending = "", ""
            try:
                for delta in self._chat(history + [{"role": "user", "content": text}], spoken):
                    times.setdefault("first_text", ms())
                    reply += delta
                    emit({"type": "text", "delta": delta, "ms": ms()})
                    if speak:
                        pending = self._flush(pending + delta, chunks)
                times["full_text"] = ms()
            finally:
                if speak:
                    if pending.strip():
                        self._queue(pending, chunks)
                    chunks.put(None)
                    speaker.join()
            times["full_reply"] = ms()
            emit({"type": "done", "reply": reply.strip(), "times": times})

    def _flush(self, pending, chunks):
        while True:
            m = END.search(pending)
            if not m and self.queued == 0:
                m = SOFT.search(pending)
                if not m and len(pending.split()) > FIRST_WORDS:
                    m = re.match(r"\s*(?:\S+\s+){%d}" % FIRST_WORDS, pending)
            if not m:
                return pending
            self._queue(pending[:m.end()], chunks)
            pending = pending[m.end():]

    def _queue(self, text, chunks):
        text = CLEAN.sub("", text).strip()
        if re.search(r"[؀-ۿA-Za-z0-9]", text):
            chunks.put(text)
            self.queued += 1
