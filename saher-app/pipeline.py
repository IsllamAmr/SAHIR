r"""Saher pipeline for the combined app: one conversation you can type in or talk to.
Push-to-talk: speech -> faster-whisper -> a transcript you review and correct before sending.
Every turn: text -> ALLaM (streamed) -> Piper speech sentence by sentence, when replies are set to be spoken.
Everything runs locally. Nothing is written to disk or logged.
Adapted from ..\saher-voice\pipeline.py, which stays untouched."""
import json, os, queue, re, threading, time, urllib.request
import numpy as np
from faster_whisper import WhisperModel
from piper import PiperVoice

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first and adds about 2 s to every request.
OLLAMA = os.environ.get("SAHER_OLLAMA", "http://127.0.0.1:11434") + "/api/chat"
MODEL = os.environ.get("SAHER_MODEL", "allam-7b-saher")
# The persona is read (never edited) from saher-chat on every turn, so persona fixes show up here without a restart.
PERSONA_FILE = os.environ.get("SAHER_PERSONA", os.path.join(ROOT, "saher-chat", "persona_allam_v4.txt"))
VOICE_NOTE = ("\n\nأنت الحين تتكلم بالصوت، فخل ردك قصير جداً: جملة أو جملتين بس. "
              "لا تستخدم قوائم ولا رموز ولا أرقام بين أقواس.")
OPTIONS = {"temperature": 0.2, "top_p": 0.9, "num_ctx": 4096}
SPOKEN_TOKENS, TYPED_TOKENS = 90, 400
MAX_MESSAGES = 16
ASR_SIZE = os.environ.get("SAHER_ASR", "small")
ASR_DEVICE = os.environ.get("SAHER_ASR_DEVICE", "cpu")  # keep on CPU: 6 GB VRAM is all ALLaM's
VOICE_FILE = os.environ.get("SAHER_VOICE", os.path.join(ROOT, "saher-voice", "voices", "ar_JO-kareem-medium.onnx"))

# A chunk is sent to TTS at the end of a sentence; the very first chunk may also break at a comma so speech starts sooner.
END = re.compile(r"[.!؟?\n]")
SOFT = re.compile(r"[،,؛:]")
FIRST_WORDS = 6
CLEAN = re.compile(r"[*#_`>\[\](){}\"«»]|[\U0001F000-\U0001FAFF☀-➿]")


class Pipeline:
    def __init__(self):
        compute = "int8" if ASR_DEVICE == "cpu" else "int8_float16"
        self.asr = WhisperModel(ASR_SIZE, device=ASR_DEVICE, compute_type=compute, cpu_threads=4)
        self.voice = PiperVoice.load(VOICE_FILE)
        self.sample_rate = self.voice.config.sample_rate
        self.lock = threading.Lock()  # one turn at a time

    def warm_up(self):
        self.asr.transcribe(np.zeros(16000, np.float32), language="ar", beam_size=1)
        list(self.voice.synthesize("هلا"))
        list(self._chat([{"role": "user", "content": "هلا"}], spoken=False, num_predict=1))

    def transcribe(self, audio16k):
        segs, _ = self.asr.transcribe(audio16k, language="ar", beam_size=1, vad_filter=False,
                                      condition_on_previous_text=False, without_timestamps=True)
        return " ".join(s.text.strip() for s in segs).strip()

    def tts(self, text):
        return b"".join(c.audio_int16_bytes for c in self.voice.synthesize(text))

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
        """One turn. text is what you typed, or the transcript you reviewed after push-to-talk (spoken=True asks for a
        short reply, as it would be in a voice chat). speak voices the reply sentence by sentence.
        emit(event: dict) gets text deltas, audio chunks and timings."""
        with self.lock:
            t0 = time.perf_counter()
            ms = lambda: round((time.perf_counter() - t0) * 1000)
            times = {}

            # TTS runs in its own thread so ALLaM keeps generating while a sentence is being voiced.
            chunks, self.queued = queue.Queue(), 0
            def voice():
                while (chunk := chunks.get()) is not None:
                    pcm = self.tts(chunk)
                    times.setdefault("first_audio", ms())
                    emit({"type": "audio", "pcm16": pcm, "sample_rate": self.sample_rate, "text": chunk, "ms": ms()})
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
                # first chunk: also break at a comma, or after FIRST_WORDS words, so speech starts sooner
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
