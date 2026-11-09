"""Shared bits for the voice comparison: the three Saher lines, timing and memory logging."""
import json, os, subprocess, sys, time, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "samples")
RESULTS = os.path.join(HERE, "results")
os.makedirs(SAMPLES, exist_ok=True)
os.makedirs(RESULTS, exist_ok=True)
sys.stdout.reconfigure(encoding="utf-8")

LINES = [
    "هلا والله! وش أقدر أسوي لك اليوم؟",
    "أبشر، الحين أدور لك على أقرب مطعم مفتوح.",
    "والله ما جربتها، بس أنصحك تروح بدري قبل الزحمة.",
]


def ollama_ps():
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10).stdout
        return [l for l in out.strip().splitlines()[1:]]
    except Exception as e:
        return [f"error: {e}"]


def gpu_used_mb():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


def available_ram_mb():
    import psutil
    return round(psutil.virtual_memory().available / 2**20)


def rss_mb():
    import psutil
    p = psutil.Process()
    return round(p.memory_info().rss / 2**20)


def save_wav(path, audio, sr):
    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    a = np.clip(a, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((a * 32767).astype(np.int16).tobytes())
    return len(a) / sr


def write_result(name, data):
    path = os.path.join(RESULTS, f"{name}_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("wrote", path)
