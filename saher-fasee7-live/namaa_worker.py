"""NAMAA Saudi TTS worker. Runs inside saher-tts-compare\venv-chatterbox (read only: nothing is installed or changed there).
Same line protocol as tts_worker.py. Chatterbox doesn't stream, so each reply is one chunk followed by "done".
Load code is the same as saher-tts-compare\run_namaa.py (NAMAA's own files only, nothing downloaded)."""
import base64, json, os, sys, time, faulthandler
os.environ.setdefault("HF_HUB_OFFLINE", "1")

proto = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr
faulthandler.enable()

import numpy as np
import torch
from safetensors.torch import load_file
from chatterbox.mtl_tts import ChatterboxMultilingualTTS, Conditionals
from chatterbox.models.t3 import T3
from chatterbox.models.t3.modules.t3_config import T3Config
from chatterbox.models.s3gen import S3Gen
from chatterbox.models.tokenizers import MTLTokenizer
from chatterbox.models.voice_encoder import VoiceEncoder

CKPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "saher-tts-compare", "models", "namaa-saudi-tts")
DEVICE = os.environ.get("NAMAA_DEVICE", "cuda")


def send(obj):
    proto.write(json.dumps(obj, ensure_ascii=False) + "\n")
    proto.flush()


t = time.perf_counter()
ve = VoiceEncoder(); ve.load_state_dict(load_file(os.path.join(CKPT, "ve.safetensors"))); ve.to(DEVICE).eval()
t3 = T3(T3Config.multilingual()); t3.load_state_dict(load_file(os.path.join(CKPT, "t3_mtl23ls_v2.safetensors"))); t3.to(DEVICE).eval()
s3 = S3Gen(); s3.load_state_dict(load_file(os.path.join(CKPT, "s3gen.safetensors")), strict=False); s3.to(DEVICE).eval()
tok = MTLTokenizer(os.path.join(CKPT, "mtl_tokenizer.json"))
conds = Conditionals.load(os.path.join(CKPT, "conds.pt"), map_location="cpu").to(DEVICE)
model = ChatterboxMultilingualTTS(t3, s3, ve, tok, DEVICE, conds=conds)
model.generate("هلا", language_id="ar")  # warm-up
send({"type": "ready", "sample_rate": model.sr, "load_s": round(time.perf_counter() - t, 1)})

for line in sys.stdin:
    if not line.strip():
        continue
    t0 = time.perf_counter()
    ms = lambda: round((time.perf_counter() - t0) * 1000)
    try:
        wav = model.generate(json.loads(line)["text"], language_id="ar")
        a = np.clip(wav.squeeze(0).float().cpu().numpy(), -1, 1)
        send({"type": "chunk", "pcm16": base64.b64encode((a * 32767).astype(np.int16).tobytes()).decode(), "ms": ms()})
        send({"type": "done", "ms": ms(), "audio_s": round(len(a) / model.sr, 2)})
    except Exception as e:
        send({"type": "error", "error": f"{type(e).__name__}: {e}", "ms": ms()})
