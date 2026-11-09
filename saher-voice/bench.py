"""Measures the four voice timings over several tries, without a microphone.
Test questions are spoken by the Piper voice itself (synthetic speech), then run through the full pipeline.
Usage: python bench.py [rounds]   -> prints a table and writes results\\bench_<time>.json"""
import json, os, statistics, subprocess, sys, time
import numpy as np
from scipy.signal import resample_poly
from pipeline import Pipeline, HERE, MODEL, ASR_SIZE, ASR_DEVICE

sys.stdout.reconfigure(encoding="utf-8")
QUESTIONS = ["هلا ساهر، كيف حالك اليوم؟",
             "وش أسوي إذا ما جاني نوم بالليل؟",
             "أبي أطلع مع أهلي الويكند، وين تنصحني أروح في الرياض؟",
             "عطني فكرة عشا سريعة.",
             "كم ساعة أذاكر باليوم عشان الاختبار؟"]
rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 2

p = Pipeline()
p.warm_up()
clips = []
for q in QUESTIONS:
    pcm = np.frombuffer(p.tts(q), np.int16).astype(np.float32) / 32768
    clips.append(resample_poly(pcm, 16000, p.sample_rate).astype(np.float32))

runs = []
for r in range(rounds):
    for q, clip in zip(QUESTIONS, clips):
        gpu = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout.strip().splitlines()[1:]
        audio_ms = [0]
        def emit(e):
            if e["type"] == "audio":
                audio_ms[0] += len(e["pcm16"]) / 2 / e["sample_rate"] * 1000
        times, heard, reply = p.turn(clip, [], emit)
        runs.append({"question": q, "heard": heard, "reply": reply, "speech_ms": round(audio_ms[0]),
                     "ollama_ps_before": gpu, "llm": p.llm_stats, **times})
        print(f"[{r+1}] asr={times['transcribed']}ms text={times['first_text']}ms audio={times['first_audio']}ms "
              f"full={times['full_reply']}ms speech={audio_ms[0]/1000:.1f}s prefill={p.llm_stats['prompt_eval_count']}tok/{(p.llm_stats['prompt_eval_duration'] or 0)/1e6:.0f}ms | heard: {heard} | reply: {reply}")

def stat(k):
    v = [x[k] for x in runs if x[k] is not None]
    return {"median": round(statistics.median(v)), "min": min(v), "max": max(v)}
summary = {k: stat(k) for k in ("transcribed", "first_text", "first_audio", "full_reply", "speech_ms")}
print("\nmedian / min / max (ms, from end of speech):")
for k, s in summary.items():
    print(f"  {k:12} {s['median']:>6} {s['min']:>6} {s['max']:>6}")
os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
out = os.path.join(HERE, "results", time.strftime("bench_%Y%m%d_%H%M%S.json"))
json.dump({"model": MODEL, "asr": f"{ASR_SIZE}/{ASR_DEVICE}", "summary": summary, "runs": runs},
          open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved", out)
