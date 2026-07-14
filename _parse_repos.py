import json
from collections import Counter

with open(r"C:\Users\pc\.cursor\projects\c-Users-pc-Desktop-gthb\agent-tools\57057ed1-6f8b-43c9-b82b-a05a022b8d8d.txt", encoding="utf-8") as f:
    repos = json.load(f)

langs = Counter()
for r in repos:
    desc = (r.get("description") or "")[:70]
    print(f"{r['name']:40} lang={str(r.get('language')):12} stars={r['stargazers_count']:3} fork={r['fork']} {desc}")
    if r.get("language") and not r["fork"]:
        langs[r["language"]] += 1

print("---LANGS---")
print(dict(langs))
print("count", len(repos))
print("own", sum(1 for r in repos if not r["fork"]))
