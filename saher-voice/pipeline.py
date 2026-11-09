"""Saher voice pipeline: speech -> text (faster-whisper) -> ALLaM via local Ollama (streamed) -> speech (Piper), sentence by sentence.
Everything runs locally. Nothing is written to disk or logged.

Timings for each turn are measured from the moment the recorded audio reaches the pipeline (right after push-to-talk is released):
  transcribed  - speech recognition finished
  first_text   - first token from ALLaM
  first_audio  - first sentence of speech synthesized and ready to play
  full_reply   - whole reply generated and all of its speech synthesized
"""
import json, os, queue, re, threading, time, urllib.request
import numpy as np
from faster_whisper import WhisperModel
from piper import PiperVoice

HERE = os.path.dirname(os.path.abspath(__file__))
# 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first and adds about 2 s to every request.
OLLAMA = os.environ.get("SAHER_OLLAMA", "http://127.0.0.1:11434") + "/api/chat"
MODEL = os.environ.get("SAHER_MODEL", "allam-7b-saher")
# Saher's current persona is read (never edited) from saher-chat on every turn, so persona fixes show up here automatically.
PERSONA_FILE = os.environ.get("SAHER_PERSONA", os.path.join(HERE, "..", "saher-chat", "persona_core.txt"))
VOICE_NOTE = ("\n\nأنت الحين تتكلم بالصوت، فخل ردك قصير جداً: جملة أو جملتين بس. "
              "لا تستخدم قوائم ولا رموز ولا أرقام بين أقواس.")
OPTIONS = {"temperature": 0.2, "top_p": 0.9, "num_ctx": 4096, "num_predict": 90}
MAX_MESSAGES = 12
ASR_SIZE = os.environ.get("SAHER_ASR", "small")
ASR_DEVICE = os.environ.get("SAHER_ASR_DEVICE", "cpu")
VOICE_FILE = os.environ.get("SAHER_VOICE", os.path.join(HERE, "voices", "ar_JO-kareem-medium.onnx"))

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
        self._chat([{"role": "user", "content": "هلا"}], num_predict=1)

    def transcribe(self, audio16k):
        segs, _ = self.asr.transcribe(audio16k, language="ar", beam_size=1, vad_filter=False,
                                      condition_on_previous_text=False, without_timestamps=True)
        return " ".join(s.text.strip() for s in segs).strip()

    def tts(self, text):
        return b"".join(c.audio_int16_bytes for c in self.voice.synthesize(text))

    def _chat(self, messages, num_predict=None):
        persona = open(PERSONA_FILE, encoding="utf-8").read() + VOICE_NOTE
        opts = dict(OPTIONS, **({"num_predict": num_predict} if num_predict else {}))
        body = json.dumps({"model": MODEL, "stream": True, "options": opts, "keep_alive": "30m",
                           "messages": [{"role": "system", "content": persona}] + messages[-MAX_MESSAGES:]}).encode()
        req = urllib.request.Request(OLLAMA, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            for line in r:
                d = json.loads(line)
                if d.get("error"):
                    raise RuntimeError(d["error"])
                if d.get("done"):
                    self.llm_stats = {k: d.get(k) for k in ("prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration", "load_duration")}
                if d.get("message", {}).get("content"):
                    yield d["message"]["content"]

    def turn(self, audio16k, history, emit):
        """Runs one push-to-talk turn. emit(event: dict) is called with transcript, text deltas, audio chunks and timings."""
        with self.lock:
            t0 = time.perf_counter()
            ms = lambda: round((time.perf_counter() - t0) * 1000)
            times = {}
            text = self.transcribe(audio16k)
            times["transcribed"] = ms()
            emit({"type": "transcript", "text": text, "ms": times["transcribed"]})
            if not text:
                times["first_text"] = times["first_audio"] = times["full_reply"] = None
                emit({"type": "done", "reply": "", "times": times})
                return times, text, ""

            # TTS runs in its own thread so ALLaM keeps generating while a sentence is being voiced.
            chunks = queue.Queue()
            self.queued = 0
            def speak():
                while (chunk := chunks.get()) is not None:
                    pcm = self.tts(chunk)
                    times.setdefault("first_audio", ms())
                    emit({"type": "audio", "pcm16": pcm, "sample_rate": self.sample_rate, "text": chunk, "ms": ms()})
            speaker = threading.Thread(target=speak)
            speaker.start()

            reply, pending = "", ""
            try:
                for delta in self._chat(history + [{"role": "user", "content": text}]):
                    times.setdefault("first_text", ms())
                    reply += delta
                    pending += delta
                    emit({"type": "text", "delta": delta, "ms": ms()})
                    pending = self._flush(pending, chunks)
            finally:
                if pending.strip():
                    self._queue(pending, chunks)
                chunks.put(None)
                speaker.join()
            times["full_reply"] = ms()
            emit({"type": "done", "reply": reply.strip(), "times": times})
            return times, text, reply.strip()

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
