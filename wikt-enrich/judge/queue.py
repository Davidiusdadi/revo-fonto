#!/usr/bin/env python3
"""Cut the judged tier into a fixed, numbered queue of batches: out/queue.<lng>/0001.json ...

  queue.py --lng de              every gap entry with a candidate
  queue.py --lng de --holdout N  N random holdout entries (truth kept aside in truth.json) to
                                 measure a judge before it is trusted with a language

Deterministic: same packets -> same batches in the same order, most used words first
($WIKT_FREQ = a `word<TAB>count` file; without it, strongest evidence first). What a batch
contains is the least a judge needs - that is the token budget.
"""
import argparse, json, os, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from packets import HERE

CONTEXT_LNGS = ["en", "de", "fr", "es", "ru", "pl", "it", "pt", "nl", "cs", "sv", "hu"]   # shown first
MAX_LNGS = 8                                             # existing translations shown to the judge


def freq():
    f = os.environ.get("WIKT_FREQ")
    if not f or not Path(f).exists():
        return {}
    return {w: int(c) for w, c in (l.rstrip("\n").split("\t") for l in list(open(f, encoding="utf-8"))[1:])}


def usage(head, fq):
    w = head.lower()
    stem = w[:-1]
    forms = [w, w + "j", w + "n", w + "jn"] if w[-1:] in "oa" else \
            [stem + e for e in ("i", "as", "is", "os", "us", "u")] if w.endswith("i") else [w]
    return sum(fq.get(x, 0) for x in forms)


def slim(e, want):
    cands = e["candidates"]
    return {"mrk": e["mrk"], "eo": e["eo"], "want": want,
            "senses": [{"mrk": s["mrk"], **({"uzo": s["uzo"]} if s["uzo"] else {}),
                        **({"dif": s["dif"][:220]} if s["dif"] else {}),
                        **({"ekz": s["ekz"]} if s.get("ekz") else {}),
                        **({"ref": s["ref"]} if s.get("ref") else {}),
                        **({"trd": t} if (t := {l: s["trd"][l][:3] for l in [l for l in sorted(s["trd"], key=lambda l: (l not in CONTEXT_LNGS, l))
                                                                     if l != want and s["trd"][l]][:MAX_LNGS]}) else {})}
                       for s in e["senses"] if s["dif"] or s["trd"] or s.get("ref") or s["kind"] == "drv"],
            **({"root": e["root"]} if e.get("root") else {}),
            **({"same_spelling": e["homonyms"]} if e.get("homonyms") else {}),
            "candidates": [{"id": c["id"], "word": c["word"], "n": len(c["editions"]),
                            **({"own": True} if want in c["editions"] else {}),
                            **{k: c[k] for k in ("mark", "marks") if k in c},
                            "via": [r.split("#")[0] for r in c["rows"][:3]]} for c in cands[:6]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lng", required=True)
    ap.add_argument("--holdout", type=int)
    ap.add_argument("--size", type=int, default=25)
    ap.add_argument("--tag", help="suffix for the queue folder, to keep queues of different packet or prompt versions apart")
    a = ap.parse_args()
    src = HERE / "out" / f"{'holdout' if a.holdout else 'packets'}.{a.lng}.jsonl"
    es = [json.loads(l) for l in open(src, encoding="utf-8")]
    fq = freq()
    if a.holdout:
        random.Random(11).shuffle(es); es = es[: a.holdout]
    else:
        es.sort(key=lambda e: (-usage(e["eo"], fq), -max(len(c["editions"]) for c in e["candidates"]), e["mrk"]))
    name = f"queue.{a.lng}" + (".holdout" if a.holdout else "") + (f".{a.tag}" if a.tag else "")
    out = HERE / "out" / name; out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("[0-9]*.json"): old.unlink()
    items = [s for e in es if (s := slim(e, a.lng))["candidates"]]
    for i in range(0, len(items), a.size):
        (out / f"{i // a.size + 1:04d}.json").write_text(json.dumps(items[i:i + a.size], ensure_ascii=False), encoding="utf-8")
    if a.holdout:
        (out / "truth.json").write_text(json.dumps({e["mrk"]: e["truth"] for e in es}, ensure_ascii=False), encoding="utf-8")
    n = -(-len(items) // a.size)
    chars = sum(len(p.read_text(encoding="utf-8")) for p in out.glob("[0-9]*.json"))
    print(f"{name}: {len(items)} entries, {sum(len(x['candidates']) for x in items)} candidates, {n} batches, ~{chars // 3 // max(n, 1)} input tokens per batch")


if __name__ == "__main__":
    main()
