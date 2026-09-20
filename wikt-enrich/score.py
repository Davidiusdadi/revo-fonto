#!/usr/bin/env python3
"""Score a holdout file: would each flow's candidates have matched what ReVo really has?

Exact match is a LOWER bound on precision: a candidate that differs from ReVo's word may still
be a correct synonym. score.py --misses N prints mismatches for a human to read.
"""
import argparse, json, random, re, sys
from collections import defaultdict
from packets import norm

def key(w):                       # compare loosely: drop bracketed clarifications and articles
    w = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", norm(w))
    return re.sub(r"^(der|die|das|to|the|a|an|sich) ", "", " ".join(w.split()))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("file"); ap.add_argument("--misses", type=int, default=0)
    a = ap.parse_args()
    tot, hit, miss = defaultdict(int), defaultdict(int), defaultdict(list)
    for line in open(a.file, encoding="utf-8"):
        e = json.loads(line)
        truth = {key(t) for w in e["truth"] for t in re.split(r"[,;]", w)}
        for c in e["candidates"]:
            n = len(c["editions"])
            tier = f'editions={min(n, 6)}{"+" if n >= 6 else " "} {"own edition" if e["want"] in c["editions"] else "others only"}'
            tot[tier] += 1
            if key(c["word"]) in truth: hit[tier] += 1
            else: miss[tier].append((e["eo"], c["word"], sorted(e["truth"])[:4]))
    print(f'{"tier":<16}{"cands":>8}{"match":>8}{"rate":>8}')
    for t in sorted(tot):
        print(f"{t:<16}{tot[t]:>8}{hit[t]:>8}{100*hit[t]/tot[t]:>7.1f}%")
    random.seed(1)
    for t in sorted(miss):
        for m in random.sample(miss[t], min(a.misses, len(miss[t]))):
            print(t, "|", m[0], "→", m[1], "| ReVo:", ", ".join(m[2]))

if __name__ == "__main__":
    main()
