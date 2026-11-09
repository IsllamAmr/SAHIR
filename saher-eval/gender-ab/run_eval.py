"""Run Saher gender A/B cases against a local Ollama model. Stdlib only.
Usage: python3 run_eval.py   (expects prompt_A.txt, prompt_B.txt, cases.json beside it)"""
import json, os, urllib.request, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "qwen2.5:7b"
OPTIONS = {"temperature": 0.7, "top_p": 0.9, "seed": 42, "num_ctx": 4096}
URL = "http://localhost:11434/api/chat"

def chat(system, user):
    body = json.dumps({"model": MODEL, "stream": False, "options": OPTIONS,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)

cases = json.load(open(os.path.join(HERE, "cases.json"), encoding="utf-8"))
out = os.path.join(HERE, "outputs"); os.makedirs(out, exist_ok=True)
results = []
for variant in ("A", "B"):
    system = open(os.path.join(HERE, f"prompt_{variant}.txt"), encoding="utf-8").read()
    for c in cases:
        raw = chat(system, c["user"])
        json.dump(raw, open(os.path.join(out, f"{variant}_{c['id']}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        results.append({"variant": variant, **c, "reply": raw["message"]["content"]})
        print(variant, c["id"], "done")
tags = json.load(urllib.request.urlopen("http://localhost:11434/api/tags"))
digest = next((m.get("digest") for m in tags.get("models", []) if m.get("name") == MODEL), None)
version = json.load(urllib.request.urlopen("http://localhost:11434/api/version")).get("version")
meta = {"model": MODEL, "digest": digest, "ollama_version": version, "options": OPTIONS, "run_at": datetime.datetime.now().isoformat(),
        "note": "one fresh chat per case, single sample, outputs unedited"}
json.dump({"meta": meta, "results": results}, open(os.path.join(out, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", os.path.join(out, "results.json"))
