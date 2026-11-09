"""Multi-turn chat diagnostics for Saher against a local Ollama model. Stdlib only.
Mirrors saher-chat settings (temperature 0.2, top_p 0.9, num_ctx 4096) with a fixed seed per sample.
Usage: python run_chat_diag.py OUT_DIR PROMPT_FILE [FEWSHOT_JSON|-] SEED [SEED ...]
Each script in scripts.json is played as one fresh conversation per seed; the model's own replies are fed back."""
import json, os, sys, hashlib, urllib.request, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("SAHER_MODEL", "qwen2.5:7b")
URL = "http://localhost:11434/api/chat"
TIMEOUT = 180  # a normal reply takes seconds; longer means a runaway generation, recorded as a failure

out, prompt_file, fewshot_file, seeds = sys.argv[1], sys.argv[2], sys.argv[3], [int(s) for s in sys.argv[4:]]
if os.path.exists(out) and os.listdir(out):
    sys.exit(f"refusing to overwrite non-empty {out}")
os.makedirs(out, exist_ok=True)
scripts_file = os.environ.get("SAHER_SCRIPTS", os.path.join(HERE, "scripts.json"))
scripts = json.load(open(scripts_file, encoding="utf-8"))
system = open(prompt_file, encoding="utf-8").read()
fewshot = [] if fewshot_file == "-" else json.load(open(fewshot_file, encoding="utf-8"))

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

def chat(messages, seed):
    options = {"temperature": 0.2, "top_p": 0.9, "num_ctx": 4096, "seed": seed}
    body = json.dumps({"model": MODEL, "stream": False, "options": options, "messages": messages}).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)

results = []
for seed in seeds:
    for s in scripts:
        messages = [{"role": "system", "content": system}] + fewshot
        raws, turns = [], []
        for user in s["turns"]:
            messages.append({"role": "user", "content": user})
            try:
                raw = chat(messages, seed)
            except TimeoutError:
                turns.append({"user": user, "reply": None, "timeout_s": TIMEOUT})
                raws.append({"timeout_s": TIMEOUT})
                break
            reply = raw["message"]["content"]
            messages.append({"role": "assistant", "content": reply})
            raws.append(raw)
            turns.append({"user": user, "reply": reply})
        json.dump(raws, open(os.path.join(out, f"{s['id']}_seed{seed}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        results.append({"id": s["id"], "seed": seed, "checks": s["checks"], "turns": turns})
        print(s["id"], "seed", seed, "done", flush=True)
version = json.load(urllib.request.urlopen("http://localhost:11434/api/version")).get("version")
tags = json.load(urllib.request.urlopen("http://localhost:11434/api/tags"))
digest = next((m.get("digest") for m in tags.get("models", []) if m.get("name") == MODEL), None)
inputs = [scripts_file, prompt_file] + ([] if fewshot_file == "-" else [fewshot_file])
meta = {"model": MODEL, "digest": digest, "ollama_version": version,
        "options": {"temperature": 0.2, "top_p": 0.9, "num_ctx": 4096}, "seeds": seeds,
        "prompt": os.path.basename(prompt_file), "fewshot": None if fewshot_file == "-" else os.path.basename(fewshot_file),
        "inputs_sha256": {os.path.basename(p): sha(p) for p in inputs},
        "run_at": datetime.datetime.now().isoformat(), "note": "fresh conversation per script and seed, outputs unedited"}
json.dump({"meta": meta, "results": results}, open(os.path.join(out, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", os.path.join(out, "results.json"))
