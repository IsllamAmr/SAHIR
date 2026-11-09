"""Fasee7 Najdi Small (VoxCPM2 base + Wittify's LoRA), same three lines as Piper and NAMAA.
VoxCPM2 streams, so time to first audio = time until the first chunk arrives.
Usage: python run_fasee7.py [cuda|cpu] [reference.wav "exact transcript"]
Without a reference it uses no cloned voice and a fixed seed, so the speaker is whatever the model picks."""
import os, sys, time, json, faulthandler
faulthandler.enable()
os.environ.setdefault("HF_HUB_OFFLINE", "1")
import numpy as np
import torch
from voxcpm import VoxCPM
from voxcpm.model.voxcpm2 import LoRAConfig
from common import LINES, SAMPLES, HERE, save_wav, write_result, ollama_ps, gpu_used_mb, available_ram_mb, rss_mb

device = sys.argv[1] if len(sys.argv) > 1 else "cuda"
ref = sys.argv[2] if len(sys.argv) > 2 else None
ref_text = sys.argv[3] if len(sys.argv) > 3 else None
tag = f"fasee7_{device}" + ("_ref" if ref else "")
BASE = os.path.join(HERE, "models", "voxcpm2")
LORA = os.path.join(HERE, "models", "fasee7-najdi-small")
SEED = 1234
# voxcpm 2.0.3 ignores lora_config.json and falls back to r=8/alpha=16, but Fasee7 was trained with r=32/alpha=32
with open(os.path.join(LORA, "lora_config.json"), encoding="utf-8") as f:
    LORA_CFG = LoRAConfig(**json.load(f)["lora_config"])
SAMPLE_ONLY = os.environ.get("FASEE7_SAMPLE_ONLY") == "1"

ollama_before, gpu0, ram0 = ollama_ps(), gpu_used_mb(), available_ram_mb()
t = time.perf_counter()
# optimize=False: torch.compile needs Triton, which isn't available on Windows.
# No denoiser: it would download an extra ModelScope model.
# VoxCPM builds the 2B model in float32 on the CPU first (~9 GB of committed memory) before casting to bf16.
# With ALLaM loaded the laptop only has ~6 GB of commit headroom, and loading crashed with an access violation,
# so build it directly in bf16 (~4.6 GB). The audio decoder is cast back to float32 by VoxCPM itself.
torch.set_default_dtype(torch.bfloat16)
model = VoxCPM(BASE, zipenhancer_model_path=None, enable_denoiser=False, optimize=False,
               device=device, lora_config=LORA_CFG, lora_weights_path=LORA)
torch.set_default_dtype(torch.float32)
load_s = time.perf_counter() - t
sr = model.tts_model.sample_rate
kw = dict(cfg_value=2.0, inference_timesteps=10)  # voxcpm 2.0.3 has no seed argument; seeded via torch below
if ref:
    kw.update(prompt_wav_path=ref, prompt_text=ref_text) if ref_text else kw.update(reference_wav_path=ref)
torch.manual_seed(SEED)
t0 = time.perf_counter()
wav = model.generate(LINES[0], **kw)  # warm-up, and the quick check sample
print(f"sample ok: {len(wav) / sr:.2f}s audio in {time.perf_counter() - t0:.1f}s, load {load_s:.1f}s", flush=True)
if SAMPLE_ONLY:
    save_wav(os.path.join(SAMPLES, f"{tag}_check.wav"), wav, sr)
    sys.exit(0)
if device == "cuda":
    torch.cuda.reset_peak_memory_stats()

runs = []
for rnd in range(3):
    for i, line in enumerate(LINES, 1):
        chunks, first = [], None
        torch.manual_seed(SEED)
        t0 = time.perf_counter()
        for c in model.generate_streaming(line, **kw):
            if first is None:
                if device == "cuda":
                    torch.cuda.synchronize()
                first = time.perf_counter() - t0
            chunks.append(c)
        gen = time.perf_counter() - t0
        dur = save_wav(os.path.join(SAMPLES, f"{tag}_line{i}.wav"), np.concatenate(chunks), sr)
        runs.append(dict(round=rnd, line=i, first_audio_s=round(first, 2), total_s=round(gen, 2),
                         audio_s=round(dur, 2), rtf=round(gen / dur, 2), ollama=ollama_ps()))
        print({k: v for k, v in runs[-1].items() if k != "ollama"}, flush=True)

write_result(tag, dict(model="Wittify/Fasee7-Najdi-Small on openbmb/VoxCPM2", device=device, reference=ref,
                       seed=SEED, load_s=round(load_s, 1), rss_mb=rss_mb(),
                       avail_ram_before_mb=ram0, avail_ram_after_mb=available_ram_mb(),
                       gpu_used_before_mb=gpu0, gpu_used_after_mb=gpu_used_mb(),
                       torch_peak_vram_mb=round(torch.cuda.max_memory_allocated() / 2**20) if device == "cuda" else None,
                       ollama_before=ollama_before, runs=runs))
