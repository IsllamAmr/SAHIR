"""Automatic surface checks for chat-diagnostic results. Stdlib only. Marker lists are rough
signals, not a dialect judgment; read the replies too.
Usage: python score.py RESULTS_JSON [RESULTS_JSON ...]"""
import json, re, sys, unicodedata

NAJDI = ["وش", "أبي", "ابي", "تبي", "تبين", "ليش", "الحين", "زين", "أبشر", "مرة", "عشان", "هلا", "لين", "شي", "يعطيك العافية", "وايد", "علمني", "خلك", "خلني", "ترى"]
MSA = ["يمكنني", "يمكنك", "أستطيع", "تستطيع", "لذلك", "بالتالي", "حيث", "ينبغي", "ماذا", "هل ترغب", "سوف", "بالإضافة", "أيضاً", "أيضا", "إذا كنت", "الخاص بك"]
EGY_LEV = ["كده", "دي", "ده", "عايز", "عايزة", "بتاع", "إزاي", "ازاي", "كتير", "أوي", "هيك", "بدي", "تانية", "تاني", "بعرف", "منيح", "شو"]

def words(text): return re.findall(r"[؀-ۿ]+", text)
def count(text, markers):
    ws, hits = words(text), []
    for m in markers:
        n = text.count(m) if " " in m else ws.count(m)
        hits += [m] * n
    return hits
def foreign(text): return "".join(c for c in text if c.isalpha() and not unicodedata.name(c, "").startswith("ARABIC"))

for path in sys.argv[1:]:
    data = json.load(open(path, encoding="utf-8"))
    timeouts = sum(t.get("reply") is None for r in data["results"] for t in r["turns"])
    replies = [t["reply"] for r in data["results"] for t in r["turns"] if t.get("reply") is not None]
    n = len(replies)
    off = [r for r in replies if foreign(r)]
    najdi = sum(bool(count(r, NAJDI)) for r in replies)
    msa = sum(bool(count(r, MSA)) for r in replies)
    egy = sum(bool(count(r, EGY_LEV)) for r in replies)
    avg_len = sum(len(words(r)) for r in replies) / n
    print(f"{data['meta']['prompt']} fewshot={data['meta']['fewshot']}: replies={n} "
          f"non-arabic={len(off)} with-najdi-marker={najdi} with-msa-marker={msa} "
          f"with-egy/lev-marker={egy} avg-words={avg_len:.0f} timeouts={timeouts}")
