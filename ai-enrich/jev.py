#!/usr/bin/env python3
"""Jev as the checker: score a run's proposals (codex.py --propose-only) and write the check results.

  JEV_ENV=<.env with API_KEY> jev.py <lng> <run> [--threshold 0.8] [--holdout]

Jev (TypeSafe System One, wikt-enrich/zh.py) answers one yes/no question per proposed word, and one
per definition, with p(yes). A word or definition at or above the threshold is accepted. The result is
an ordinary <article>.check.json with model "jev-latest" and each verdict's score in "jev", so apply.py
writes it unchanged except for the fnt, which keeps the score for a later review:

  <trd fnt="AI: en de fr; proponis gpt-5.6-luna; taksis Jev 84%">
  <dif lng="zh" fnt="AI: eo; tradukis gpt-5.6-luna; taksis Jev 91%">

What falls below the threshold stays in the check file with accept false and its score, so it can be
looked at again. Scores are cached in out/<lng>/jev.jsonl by work sha, node and text.
"""
import argparse, concurrent.futures as cf, json, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "wikt-enrich"))
from concurrent.futures import thread  # noqa: E402,F401  (before zh: its imports put judge/queue.py on the path)
import zh  # noqa: E402

MODEL = "jev-latest"
NAMES = {"de": "German", "en": "English", "zh": "Chinese"}
CONTEXT = ("en", "de", "fr", "es", "ru", "ja", "pl", "nl", "pt", "it")
WORD_Q = ("The {name} word is a correct translation of the Esperanto word in the meaning the definition gives "
          "(same meaning and same part of speech, not a related or broader word, not a word from another "
          "meaning of the same spelling).")
DEF_Q = ("The {name} definition is a faithful translation of the Esperanto definition: it says the same thing, "
         "with nothing missing, added or wrong.")


def node(work, mrk):
    """-> (Esperanto word, Esperanto definition, other languages' words) for an entry or sense mrk."""
    for e in work["entries"]:
        senses = e["senses"] if e["mrk"] == mrk else [s for s in e["senses"] if s["mrk"] == mrk]
        if e["mrk"] != mrk and not senses:
            continue
        dif = " | ".join(s["dif"] for s in senses if s["dif"]) or " | ".join(s["dif"] for s in e["senses"] if s["dif"])
        ws = {l: list(v) for l, v in e["whole_words"].items()}
        for s in senses:
            for l, v in s["words"].items():
                ws.setdefault(l, []).extend(x for x in v if x not in ws[l])
        return e["eo"], dif[:600], {l: ws[l][:4] for l in CONTEXT if ws.get(l)}
    return None, "", {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lng", choices=tuple(NAMES)); ap.add_argument("run")
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--holdout", action="store_true")
    a = ap.parse_args()
    name = NAMES[a.lng]
    base = HERE / "out" / a.lng / ("holdout" if a.holdout else "")
    cache_f = HERE / "out" / a.lng / "jev.jsonl"
    cache = {d["id"]: d["p"] for d in map(json.loads, open(cache_f, encoding="utf-8"))} if cache_f.exists() else {}
    todo, articles = {}, []
    for pf in sorted((base / "results").glob("*.propose.json")):
        prop = json.loads(pf.read_text(encoding="utf-8"))
        if prop["run"] != a.run:
            continue
        work = json.loads((base / "work" / f'{prop["article"]}.json').read_text(encoding="utf-8"))
        if work["sha"] != prop["work_sha"]:
            print(f'{prop["article"]}: proposed on an older work file, skipped', file=sys.stderr); continue
        articles.append((prop, work))
        for p in prop["proposals"]:
            eo, dif, ws = node(work, p["mrk"])
            forms = " / ".join(dict.fromkeys(x for x in (p.get("traditional"), p["word"]) if x))
            i = f'{work["sha"]}|{p["mrk"]}|w|{forms}'
            if i not in cache:
                todo[i] = {"state": {"esperanto_word": eo, "definition": dif, "translations_in_other_languages": ws,
                                     f"{name.lower()}_word": forms},
                           "questions": {"ok": {"type": "noul", "instructions": WORD_Q.format(name=name)}}}
        for d in prop["definitions"]:
            eo, dif, ws = node(work, d["mrk"])          # the words show what an Esperanto-only definition means
            i = f'{work["sha"]}|{d["mrk"]}|d2|{d["text"]}'
            if i not in cache:
                todo[i] = {"state": {"esperanto_word": eo, "esperanto_definition": dif,
                                     "translations_in_other_languages": ws, f"{name.lower()}_definition": d["text"]},
                           "questions": {"ok": {"type": "noul", "instructions": DEF_Q.format(name=name)}}}
    key, failed = zh.jev_key() if todo else None, 0
    with open(cache_f, "a", encoding="utf-8") as f, cf.ThreadPoolExecutor(12) as ex:
        for i, r in zip(todo, ex.map(lambda b: zh.send(key, b), todo.values())):
            if "answers" in r:
                cache[i] = round(r["answers"]["ok"]["noul"], 4)
                f.write(json.dumps({"id": i, "p": cache[i]}, ensure_ascii=False) + "\n")
            else:
                failed += 1
    n = {"words": 0, "words kept": 0, "definitions": 0, "definitions kept": 0, "articles": 0}
    for prop, work in articles:
        verdicts, defs, complete = [], [], True
        for p in prop["proposals"]:
            forms = " / ".join(dict.fromkeys(x for x in (p.get("traditional"), p["word"]) if x))
            s = cache.get(f'{work["sha"]}|{p["mrk"]}|w|{forms}')
            complete &= s is not None
            verdicts.append({"mrk": p["mrk"], "word": p["word"], "accept": s is not None and s >= a.threshold,
                             "jev": s, "mark": "", "searched": False})
        for d in prop["definitions"]:
            s = cache.get(f'{work["sha"]}|{d["mrk"]}|d2|{d["text"]}')
            complete &= s is not None
            defs.append({"mrk": d["mrk"], "accept": s is not None and s >= a.threshold, "jev": s, "text": d["text"]})
        if not complete:
            continue                                # a Jev call failed: no check file, so a rerun picks it up
        check = {"article": prop["article"], "lng": a.lng, "stage": "check", "run": a.run, "model": MODEL,
                 "work_sha": work["sha"], "saved": time.strftime("%Y-%m-%dT%H:%M:%S"), "threshold": a.threshold,
                 "verdicts": verdicts, "definitions": defs, "flags": []}
        (base / "results" / f'{prop["article"]}.check.json').write_text(
            json.dumps(check, ensure_ascii=False, indent=1), encoding="utf-8")
        n["articles"] += 1
        n["words"] += len(verdicts); n["words kept"] += sum(v["accept"] for v in verdicts)
        n["definitions"] += len(defs); n["definitions kept"] += sum(d["accept"] for d in defs)
    print(f"{a.run}: Jev at {a.threshold:.0%}, {len(todo)} asked, {failed} failed; "
          + ", ".join(f"{k} {v}" for k, v in n.items()))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
