"""Saher baseline diagnostics against a local Ollama model. Stdlib only.
Same request as gender-ab/run_eval.py; prompt files, temperature and output dir are arguments.
Usage: python run_diag.py OUT_DIR TEMPERATURE PROMPT_FILE [PROMPT_FILE ...]
Each prompt file's stem is used as the variant label. Cases come from ../gender-ab/cases.json."""
import json, os, sys, hashlib, urllib.request, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, "..", "gender-ab", "cases.json")
MODEL = "qwen2.5:7b"
URL = "http://localhost:11434/api/chat"

out, temperature, prompt_files = sys.argv[1], float(sys.argv[2]), sys.argv[3:]
OPTIONS = {"temperature": temperature, "top_p": 0.9, "seed": 42, "num_ctx": 4096}
if os.path.exists(out) and os.listdir(out):
    sys.exit(f"refusing to overwrite non-empty {out}")
os.makedirs(out, exist_ok=True)

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

def chat(system, user):
    body = json.dumps({"model": MODEL, "stream": False, "options": OPTIONS,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)

cases = json.load(open(CASES, encoding="utf-8"))
results = []
for pf in prompt_files:
    variant = os.path.splitext(os.path.basename(pf))[0]
    system = open(pf, encoding="utf-8").read()
    for c in cases:
        raw = chat(system, c["user"])
        json.dump(raw, open(os.path.join(out, f"{variant}_{c['id']}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        results.append({"variant": variant, **c, "reply": raw["message"]["content"]})
        print(variant, c["id"], "done", flush=True)
tags = json.load(urllib.request.urlopen("http://localhost:11434/api/tags"))
digest = next((m.get("digest") for m in tags.get("models", []) if m.get("name") == MODEL), None)
version = json.load(urllib.request.urlopen("http://localhost:11434/api/version")).get("version")
meta = {"model": MODEL, "digest": digest, "ollama_version": version, "options": OPTIONS,
        "run_at": datetime.datetime.now().isoformat(),
        "inputs_sha256": {os.path.basename(p): sha(p) for p in [CASES, *prompt_files]},
        "note": "one fresh chat per case, single sample, outputs unedited"}
json.dump({"meta": meta, "results": results}, open(os.path.join(out, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", os.path.join(out, "results.json"))
