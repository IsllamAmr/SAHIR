"""End-to-end check without a microphone: posts a WAV of a spoken question to a running trial server
and prints what came back. Usage: python e2e_test.py question.wav"""
import base64, json, os, sys, time, urllib.request, wave
import numpy as np
sys.stdout.reconfigure(encoding="utf-8")
with wave.open(sys.argv[1]) as w:
    sr, a = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
if sr != 16000:
    a = np.interp(np.arange(0, len(a), sr / 16000), np.arange(len(a)), a)
pcm = a.astype(np.int16).tobytes()
body = json.dumps({"pcm16": base64.b64encode(pcm).decode(), "messages": []}).encode()
t0 = time.perf_counter()
audio = b""
with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{os.environ.get('SAHER_PORT', '8770')}/turn", body), timeout=900) as r:
    for line in r:
        e = json.loads(line)
        if e["type"] == "audio":
            audio += base64.b64decode(e["pcm16"]); rate = e["sample_rate"]
            continue
        if e["type"] != "text":
            print(round(time.perf_counter() - t0, 2), e, flush=True)
if audio:
    out = sys.argv[2] if len(sys.argv) > 2 else "reply.wav"
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(audio)
    print("saved", out, len(audio) / 2 / rate, "s")
