"""Baseline: the current Piper voice (ar_JO-kareem-medium, CPU), same lines as the other models.
Time to first audio = time until Piper hands back its first audio chunk (it yields one per sentence)."""
import os, time
import numpy as np
from piper import PiperVoice
from common import LINES, SAMPLES, save_wav, write_result, ollama_ps, gpu_used_mb, available_ram_mb, rss_mb

VOICE = os.path.join(os.path.dirname(__file__), "..", "saher-voice", "voices", "ar_JO-kareem-medium.onnx")

ram0, rss0 = available_ram_mb(), rss_mb()
t = time.perf_counter(); v = PiperVoice.load(VOICE); load_s = time.perf_counter() - t
list(v.synthesize("هلا"))  # warm-up
runs = []
for rnd in range(3):
    for i, line in enumerate(LINES, 1):
        t0 = time.perf_counter(); first = None; chunks = []
        for c in v.synthesize(line):
            if first is None:
                first = time.perf_counter() - t0
            chunks.append(np.frombuffer(c.audio_int16_bytes, np.int16).astype(np.float32) / 32768)
        total = time.perf_counter() - t0
        sr = v.config.sample_rate
        dur = save_wav(os.path.join(SAMPLES, f"piper_line{i}.wav"), np.concatenate(chunks), sr)
        runs.append(dict(round=rnd, line=i, first_audio_s=round(first, 3), total_s=round(total, 3), audio_s=round(dur, 2)))
        print(runs[-1])
write_result("piper", dict(model="piper ar_JO-kareem-medium", device="cpu", load_s=round(load_s, 2),
                           rss_mb=rss_mb(), rss_before_mb=rss0, avail_ram_before_mb=ram0, gpu_used_mb=gpu_used_mb(),
                           ollama_ps=ollama_ps(), runs=runs))
