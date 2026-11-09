"""Fasee7 speech worker. Runs inside saher-tts-compare\\venv-voxcpm (read only: nothing is installed or changed there).
The trial server starts it as a child process and talks to it with one JSON object per line:
  stdin : {"text": "..."}
  stdout: {"type": "ready", "sample_rate": 48000, "load_s": ...}
          {"type": "chunk", "pcm16": "<base64>", "ms": ...}      (ms since the request arrived)
          {"type": "done", "ms": ..., "audio_s": ...}
          {"type": "error", "error": "..."}
Load code is the same as saher-tts-compare\\run_fasee7.py: LoRA at r=32/alpha=32 and the model built directly in bf16."""
import base64, json, os, sys, time, faulthandler
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# stdout carries the protocol; anything the libraries print goes to stderr instead.
proto = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr
faulthandler.enable()

import numpy as np
import torch
from voxcpm import VoxCPM
from voxcpm.model.voxcpm2 import LoRAConfig

COMPARE = os.environ.get("FASEE7_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "saher-tts-compare"))
BASE = os.path.join(COMPARE, "models", "voxcpm2")
LORA = os.path.join(COMPARE, "models", "fasee7-najdi-small")
SEED = 1234  # the default voice the user approved (seed-1234 samples, no reference clip)
DEVICE = os.environ.get("FASEE7_DEVICE", "cuda")


def send(obj):
    proto.write(json.dumps(obj, ensure_ascii=False) + "\n")
    proto.flush()


with open(os.path.join(LORA, "lora_config.json"), encoding="utf-8") as f:
    LORA_CFG = LoRAConfig(**json.load(f)["lora_config"])  # voxcpm 2.0.3 would otherwise fall back to r=8

import voxcpm.model.voxcpm2 as vx
BASE_WEIGHTS = os.path.normcase(os.path.abspath(os.path.join(BASE, "model.safetensors")))
_load_file = vx.load_file


def skip_base_weights(path, *a, **k):
    # voxcpm reads the whole 4.6 GB model.safetensors into RAM while its own 4.6 GB copy of the model is also
    # still in RAM. Next to ALLaM that ~9 GB peak ran out of Windows commit memory (access violation), so the
    # base weights are skipped here and streamed onto the GPU one tensor at a time after the model is built.
    if os.path.normcase(os.path.abspath(path)) == BASE_WEIGHTS:
        return {}
    return _load_file(path, *a, **k)


vx.load_file = skip_base_weights

t = time.perf_counter()
torch.set_default_dtype(torch.bfloat16)  # the float32 build needs ~9 GB of commit and crashed next to ALLaM
model = VoxCPM(BASE, zipenhancer_model_path=None, enable_denoiser=False, optimize=False,
               device=DEVICE, lora_config=LORA_CFG, lora_weights_path=LORA)
torch.set_default_dtype(torch.float32)
params = model.tts_model.state_dict()  # shares storage with the live (GPU) parameters
matched, unknown = 0, []
# Plain file reads, not safetensors' own loader: that maps the whole file copy-on-write, which also reserves
# 4.6 GB of commit and crashed the same way.
DTYPES = {"BF16": torch.bfloat16, "F16": torch.float16, "F32": torch.float32, "I64": torch.int64, "I32": torch.int32, "BOOL": torch.bool}
with torch.no_grad(), open(BASE_WEIGHTS, "rb") as f:
    n = int.from_bytes(f.read(8), "little")
    header = json.loads(f.read(n))
    header.pop("__metadata__", None)
    for key, info in sorted(header.items(), key=lambda kv: kv[1]["data_offsets"][0]):
        if key not in params:
            unknown.append(key)
            continue
        b, e = info["data_offsets"]
        f.seek(8 + n + b)
        buf = bytearray(f.read(e - b))
        tensor = torch.frombuffer(buf, dtype=DTYPES[info["dtype"]]).reshape(info["shape"]) if buf else torch.empty(info["shape"], dtype=DTYPES[info["dtype"]])
        params[key].copy_(tensor)
        matched += 1
print(f"base weights: {matched} loaded, {len(unknown)} not in model {unknown[:5]}", file=sys.stderr, flush=True)
if unknown or matched == 0:
    raise RuntimeError(f"base weights did not match the model: {len(unknown)} unknown keys")
del params
SR = model.tts_model.sample_rate
KW = dict(cfg_value=2.0, inference_timesteps=10)
torch.manual_seed(SEED)
model.generate("هلا", **KW)  # warm-up
send({"type": "ready", "sample_rate": SR, "load_s": round(time.perf_counter() - t, 1)})

for line in sys.stdin:
    if not line.strip():
        continue
    t0 = time.perf_counter()
    ms = lambda: round((time.perf_counter() - t0) * 1000)
    try:
        text = json.loads(line)["text"]
        torch.manual_seed(SEED)
        total = 0
        for c in model.generate_streaming(text, **KW):
            a = np.clip(np.asarray(c, dtype=np.float32).reshape(-1), -1, 1)
            total += len(a)
            send({"type": "chunk", "pcm16": base64.b64encode((a * 32767).astype(np.int16).tobytes()).decode(), "ms": ms()})
        send({"type": "done", "ms": ms(), "audio_s": round(total / SR, 2)})
    except Exception as e:
        send({"type": "error", "error": f"{type(e).__name__}: {e}", "ms": ms()})
