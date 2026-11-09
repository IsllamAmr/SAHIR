"""NAMAA-Saudi-TTS (Chatterbox Multilingual with NAMAA's T3 weights), same three lines as Piper.
Chatterbox is not streaming, so time to first audio = time to synthesize the whole line.
Usage: python run_namaa.py [cuda|cpu] [reference.wav]
Without a reference it uses the default voice that ships in the model folder (conds.pt)."""
import os, sys, time
os.environ.setdefault("HF_HUB_OFFLINE", "1")  # skip the Chinese-only Cangjie download
import torch
from safetensors.torch import load_file
from chatterbox.mtl_tts import ChatterboxMultilingualTTS, Conditionals
from chatterbox.models.t3 import T3
from chatterbox.models.t3.modules.t3_config import T3Config
from chatterbox.models.s3gen import S3Gen
from chatterbox.models.tokenizers import MTLTokenizer
from chatterbox.models.voice_encoder import VoiceEncoder
from common import LINES, SAMPLES, HERE, save_wav, write_result, ollama_ps, gpu_used_mb, available_ram_mb, rss_mb

device = sys.argv[1] if len(sys.argv) > 1 else "cuda"
ref = sys.argv[2] if len(sys.argv) > 2 else None
tag = f"namaa_{device}" + ("_ref" if ref else "")
CKPT = os.path.join(HERE, "models", "namaa-saudi-tts")

def load(ckpt, device):
    """Like ChatterboxMultilingualTTS.from_local, but reads the files NAMAA actually ships
    (s3gen/ve as .safetensors, NAMAA's own mtl_tokenizer.json), so nothing extra is downloaded."""
    ve = VoiceEncoder(); ve.load_state_dict(load_file(os.path.join(ckpt, "ve.safetensors"))); ve.to(device).eval()
    t3 = T3(T3Config.multilingual()); t3.load_state_dict(load_file(os.path.join(ckpt, "t3_mtl23ls_v2.safetensors"))); t3.to(device).eval()
    s3 = S3Gen(); r = s3.load_state_dict(load_file(os.path.join(ckpt, "s3gen.safetensors")), strict=False); s3.to(device).eval()
    print("s3gen missing:", r.missing_keys[:5], len(r.missing_keys), "unexpected:", r.unexpected_keys[:5], len(r.unexpected_keys))
    tok = MTLTokenizer(os.path.join(ckpt, "mtl_tokenizer.json"))
    conds = Conditionals.load(os.path.join(ckpt, "conds.pt"), map_location="cpu").to(device)
    return ChatterboxMultilingualTTS(t3, s3, ve, tok, device, conds=conds)


ollama_before, gpu0, ram0 = ollama_ps(), gpu_used_mb(), available_ram_mb()
t = time.perf_counter()
model = load(CKPT, device)
load_s = time.perf_counter() - t
kw = dict(language_id="ar")
if ref:
    kw["audio_prompt_path"] = ref
model.generate("هلا", **kw)  # warm-up
if device == "cuda":
    torch.cuda.reset_peak_memory_stats()

runs = []
for rnd in range(3):
    for i, line in enumerate(LINES, 1):
        t0 = time.perf_counter()
        wav = model.generate(line, **kw)
        if device == "cuda":
            torch.cuda.synchronize()
        gen = time.perf_counter() - t0
        dur = save_wav(os.path.join(SAMPLES, f"{tag}_line{i}.wav"), wav.squeeze(0).cpu().numpy(), model.sr)
        runs.append(dict(round=rnd, line=i, first_audio_s=round(gen, 2), audio_s=round(dur, 2), rtf=round(gen / dur, 2),
                         ollama=ollama_ps()))
        print({k: v for k, v in runs[-1].items() if k != "ollama"}, flush=True)

write_result(tag, dict(model="NAMAA-Space/NAMAA-Saudi-TTS", device=device, reference=ref, load_s=round(load_s, 1),
                       rss_mb=rss_mb(), avail_ram_before_mb=ram0, avail_ram_after_mb=available_ram_mb(),
                       gpu_used_before_mb=gpu0, gpu_used_after_mb=gpu_used_mb(),
                       torch_peak_vram_mb=round(torch.cuda.max_memory_allocated() / 2**20) if device == "cuda" else None,
                       ollama_before=ollama_before, runs=runs))
