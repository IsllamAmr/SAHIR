"""Flag letters outside the Arabic script in each reply of a results.json. Stdlib only.
Usage: python script_check.py RESULTS_JSON"""
import json, sys, unicodedata

def foreign(text):
    bad = []
    for ch in text:
        if ch.isalpha() and not unicodedata.name(ch, "").startswith("ARABIC"):
            bad.append(ch)
    return "".join(bad)

data = json.load(open(sys.argv[1], encoding="utf-8"))
clean = 0
for r in data["results"]:
    f = foreign(r["reply"])
    clean += not f
    print(f'{r["variant"]}_{r["id"]}: {"OK" if not f else "NON-ARABIC " + repr(f[:60])}')
print(f"arabic-only: {clean}/{len(data['results'])}")
