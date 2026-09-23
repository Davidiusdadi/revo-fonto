#!/usr/bin/env python3
"""Score a holdout run: what the checker accepted against the words ReVo has and the run hid.

  score.py --lng de             counts, then a sample of accepted words ReVo does not have
  score.py --lng de --sample 0

Per accepted word: `exact` ReVo has this word for the entry; `near` ReVo has one containing it or
contained in it, ignoring case, "to ", "sich " and articles (Staat ~ Teilstaat); `other` ReVo has
neither. `other` is not the same as wrong - ReVo lists few words per entry - which is why the
sample is there to be read. `placed` counts exact words under the very place ReVo has them.
Also: entries where some accepted word is exact, and proposals the checker rejected that ReVo has
(the checker being too strict).
"""
import argparse, json, random, re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def fold(w):
    w = re.sub(r"\([^)]*\)|\[[^]]*\]", "", w.lower())
    w = re.sub(r"^(to|sich|der|die|das|a|an|the)\s+", "", w.strip())
    return " ".join(w.split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lng", required=True)
    ap.add_argument("--sample", type=int, default=30)
    a = ap.parse_args()
    base = HERE / "out" / a.lng / "holdout"
    truth = json.loads((base / "truth.json").read_text(encoding="utf-8"))
    c, entries_hit, others, rejected_right = Counter(), set(), [], []
    for check_path in sorted((base / "results").glob("*.check.json")):
        article = check_path.name[: -len(".check.json")]
        prop = json.loads((base / "results" / f"{article}.propose.json").read_text(encoding="utf-8"))
        check = json.loads(check_path.read_text(encoding="utf-8"))
        work = json.loads((base / "work" / f"{article}.json").read_text(encoding="utf-8"))
        drv_of = {e["mrk"]: e["mrk"] for e in work["entries"]}
        drv_of |= {s["mrk"]: e["mrk"] for e in work["entries"] for s in e["senses"]}
        eo = {e["mrk"]: e["eo"] for e in work["entries"]}
        verdict = {(v["mrk"], v["word"]): v for v in check["verdicts"]}
        c["articles"] += 1
        c["definitions accepted"] += sum(d["accept"] for d in check["definitions"])
        c["definitions"] += len(check["definitions"])
        c["covered"] += len(prop["covered"])
        c["flags"] += len(prop["flags"]) + len(check["flags"])
        for p in prop["proposals"]:
            drv = drv_of[p["mrk"]]
            t = truth.get(drv)
            if t is None:
                continue
            here = t["whole"] if p["mrk"] == drv else t["senses"].get(p["mrk"], [])
            every = {fold(w) for w in t["whole"] + [w for ws in t["senses"].values() for w in ws]}
            w = fold(p["word"])
            kind = "exact" if w in every else "near" if any(w in x or x in w for x in every) else "other"
            v = verdict.get((p["mrk"], p["word"]))
            c["proposed"] += 1
            if not v or not v["accept"]:
                c["rejected"] += 1
                if kind == "exact":
                    rejected_right.append((eo[drv], p["mrk"], p["word"], v and v["why"]))
                continue
            c["accepted"] += 1
            c[kind] += 1
            c["searched"] += v["searched"]
            if kind == "exact":
                entries_hit.add(drv)
                c["placed"] += w in {fold(x) for x in here}
            elif kind == "other":
                others.append((eo[drv], p["mrk"], p["word"] + (" " + v["mark"] if v["mark"] else ""), sorted(every)))
    acc = c["accepted"] or 1
    print(f'{a.lng} holdout: {c["articles"]} articles of {len({*truth})} entries; {c["proposed"]} words proposed, '
          f'{c["accepted"]} accepted, {c["rejected"]} rejected ({c["searched"]} accepted after a search)')
    print(f'  accepted: exact {c["exact"]} ({c["exact"] / acc:.0%}), near {c["near"]} ({c["near"] / acc:.0%}), '
          f'other {c["other"]} ({c["other"] / acc:.0%}); exact under ReVo\'s own place {c["placed"]}')
    print(f'  entries with an exact word: {len(entries_hit)} of {len(truth)}; rejected words ReVo has: {len(rejected_right)}')
    print(f'  C senses judged covered: {c["covered"]}; definitions {c["definitions accepted"]} of {c["definitions"]} '
          f'accepted; flags {c["flags"]}')
    random.seed(7)
    if a.sample:
        print("\naccepted, ReVo has neither (read these):")
        for e, m, w, t in random.sample(others, min(a.sample, len(others))):
            print(f"  {e:<20} {m:<26} {w:<28} ReVo: {', '.join(t)}")
        print("\nrejected, but ReVo has it:")
        for e, m, w, why in rejected_right[: a.sample // 2]:
            print(f"  {e:<20} {m:<26} {w:<20} {why or ''}")


if __name__ == "__main__":
    main()
