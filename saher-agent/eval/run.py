r"""Eval for Saher agent: runs eval\tasks.json against the live model and saves every raw step.
Each run uses a fresh copy of SAHIR\workspace\ (without outputs), so reports written by the eval never touch the real
workspace and every task sees the same file list. Mail is forced to mock so no real email lands in the logs.
Usage: python run.py LABEL [SEED]      env: ONLY=id,id   SAHER_AGENT_GUARD=0 (raw model, injection test)"""
import hashlib, json, os, re, shutil, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.dirname(HERE)
LABEL = sys.argv[1] if len(sys.argv) > 1 else "run"
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 1
OUT = os.path.join(HERE, "runs", f"{LABEL}_seed{SEED}")
WS = os.path.join(OUT, "workspace")
if os.path.exists(OUT):
    shutil.rmtree(OUT)
shutil.copytree(os.path.join(os.path.dirname(AGENT), "workspace"), WS, ignore=shutil.ignore_patterns("outputs"))
os.makedirs(os.path.join(WS, "outputs"))
os.environ["SAHER_WORKSPACE"] = WS
os.environ["SAHER_AGENT_MAIL"] = "mock"
sys.path.insert(0, AGENT)
sys.stdout.reconfigure(encoding="utf-8")
import agent, tools  # noqa: E402

agent.OPTIONS["seed"] = SEED
agent.PLAN_OPTIONS["seed"] = SEED
tasks = json.load(open(os.path.join(HERE, "tasks.json"), encoding="utf-8"))
only = [x for x in os.environ.get("ONLY", "").split(",") if x]
tasks = [t for t in tasks if not only or t["id"] in only]


def score(t, trace):
    used = [s["tool"] for s in trace["steps"] if s.get("tool")]
    want, allow = set(t["tools"]), set(t.get("allow", [])) | set(t.get("first", []))
    if not want:
        tool_ok = all(u in allow for u in used)
    else:
        tool_ok = bool(set(used) & want) and all(u in want | allow | {"list_files"} for u in used)
        if "create_report" in want:
            tool_ok = tool_ok and any(s.get("tool") == "create_report" and s["result"]["ok"] for s in trace["steps"])
    final = trace["final"]
    miss = [p for p in t.get("must", []) if not re.search(p, final)]
    bad = [p for p in t.get("must_not", []) if re.search(p, final)]
    return {"tools_used": used, "tool_ok": tool_ok, "answer_ok": not miss and not bad, "missing": miss, "forbidden": bad}


def model_info():
    req = urllib.request.Request(agent.OLLAMA + "/api/show", json.dumps({"model": agent.MODEL}).encode(),
                                 {"Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=20))
    return {"model": agent.MODEL, "details": d.get("details"), "modified_at": d.get("modified_at")}


settings = {"label": LABEL, "seed": SEED, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "ollama": agent.OLLAMA,
            "options": agent.OPTIONS, "planner_options": agent.PLAN_OPTIONS,
            "planner_model": agent.PLANNER_MODEL, "max_steps": agent.MAX_STEPS, "guard": tools.GUARD_ON, "limits": agent.LIMITS, "mail": "mock",
            "persona_file": os.path.basename(agent.PERSONA_FILE),
            "persona_sha1": hashlib.sha1(open(agent.PERSONA_FILE, "rb").read()).hexdigest()[:12],
            "model_info": model_info()}
os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, "writer_system_prompt.txt"), "w", encoding="utf-8").write(agent.persona_text())
json.dump(agent.planner_messages(tools.workspace_files(), [], "<طلب المستخدم>"),
          open(os.path.join(OUT, "planner_messages.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(agent.schema(tools.workspace_files()), open(os.path.join(OUT, "schema.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
json.dump(settings, open(os.path.join(OUT, "settings.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

rows = []
agent.stream(agent.MODEL, [{"role": "user", "content": "هلا"}], dict(agent.OPTIONS, num_predict=5))  # warm-up
for t in tasks:
    trace = agent.run_turn([], t["text"])
    s = score(t, trace)
    rec = dict(id=t["id"], task=t, score=s, trace=trace)
    json.dump(rec, open(os.path.join(OUT, f"{t['id']}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    rows.append({"id": t["id"], **s, "ms": trace["ms"], "steps": len(trace["steps"]), "notes": trace["notes"],
                 "final": trace["final"]})
    print(f"{t['id']:18} tool={'OK ' if s['tool_ok'] else 'BAD'} ans={'OK ' if s['answer_ok'] else 'BAD'} "
          f"{trace['ms'] / 1000:5.1f}s {s['tools_used']} {trace['notes']}\n   → {trace['final'][:220]}", flush=True)

summary = {"settings": settings, "n": len(rows), "tool_ok": sum(r["tool_ok"] for r in rows),
           "answer_ok": sum(r["answer_ok"] for r in rows), "rows": rows,
           "outputs": sorted(os.listdir(os.path.join(WS, "outputs")))}
json.dump(summary, open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n{LABEL} seed {SEED}: tool choice {summary['tool_ok']}/{len(rows)}, answer checks {summary['answer_ok']}/{len(rows)}")
print("outputs:", summary["outputs"])
