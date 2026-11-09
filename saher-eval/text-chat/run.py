"""Replays scripts.json against ALLaM with the same settings as saher-app (127.0.0.1, temperature 0.2, top_p 0.9,
num_ctx 4096, 400 tokens for typed replies, last 16 messages). Each script is one fresh chat per seed; the model's own
replies are fed back. Usage: python run.py OUT_DIR PERSONA_FILE SEED [SEED ...]   (refuses to overwrite OUT_DIR)"""
import json, os, sys, hashlib, time, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
URL, MODEL = "http://127.0.0.1:11434/api/chat", "allam-7b-saher"
out, persona_file, seeds = sys.argv[1], sys.argv[2], [int(s) for s in sys.argv[3:]]
if os.path.exists(out) and os.listdir(out):
    sys.exit(f"refusing to overwrite non-empty {out}")
os.makedirs(out, exist_ok=True)
system = open(persona_file, encoding="utf-8").read()
scripts = json.load(open(os.path.join(HERE, "scripts.json"), encoding="utf-8"))
if os.environ.get("ONLY"):  # comma-separated script ids, for quick checks
    scripts = [s for s in scripts if s["id"] in os.environ["ONLY"].split(",")]

def chat(messages, seed):
    opts = {"temperature": 0.2, "top_p": 0.9, "num_ctx": 4096, "num_predict": 400, "seed": seed}
    body = json.dumps({"model": MODEL, "stream": False, "keep_alive": "30m", "options": opts,
                       "messages": [{"role": "system", "content": system}] + messages[-16:]}).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())

results = {"persona": os.path.basename(persona_file), "persona_sha256": hashlib.sha256(open(persona_file, "rb").read()).hexdigest(),
           "model": MODEL, "seeds": seeds, "chats": []}
for s in scripts:
    for seed in seeds:
        msgs, raw = [], []
        for t in s["turns"]:
            msgs.append({"role": "user", "content": t})
            r = chat(msgs, seed)
            raw.append(r)
            msgs.append({"role": "assistant", "content": r["message"]["content"].strip()})
        json.dump(raw, open(os.path.join(out, f"{s['id']}_seed{seed}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        results["chats"].append({"id": s["id"], "seed": seed, "messages": msgs})
        print(s["id"], seed, "|", msgs[-1]["content"][:90], flush=True)
json.dump(results, open(os.path.join(out, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
