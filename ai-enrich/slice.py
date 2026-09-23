#!/usr/bin/env python3
"""The next slice of articles for the workflow, as its args (JSON on stdout).

  slice.py --lng de --holdout                     every holdout article not done yet
  slice.py --lng de --gap A --bundles 40          the next 40 bundles of articles with an A gap
  slice.py --lng de --gap C --bundles 40 --size 5

An article is done when its check result exists for the current work file (same work_sha): a
work file regenerated after the XML changed is done again, as wikt-enrich's done_for does.
Articles are bundled about `size` to an agent, a large one alone, in file order, so the same
command gives the same slice until results come in.
"""
import argparse, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LARGE = 30_000                                      # bytes of XML: such an article has an agent to itself


def done(results, name, sha):
    f = results / f"{name}.check.json"
    return f.exists() and json.loads(f.read_text(encoding="utf-8")).get("work_sha") == sha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lng", required=True)
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--gap", choices=("A", "B", "C"), help="only articles with this gap kind")
    ap.add_argument("--bundles", type=int, default=40)
    ap.add_argument("--size", type=int, default=5)
    ap.add_argument("--run", required=True, help="run tag, recorded in every result")
    ap.add_argument("--model", default="claude-opus-5-5")
    a = ap.parse_args()
    base = HERE / "out" / a.lng / ("holdout" if a.holdout else "")
    bundles, current = [], []
    for f in sorted((base / "work").glob("*.json")):
        work = json.loads(f.read_text(encoding="utf-8"))
        if done(base / "results", f.stem, work["sha"]):
            continue
        gaps = {e["gap"] for e in work["entries"]} | {s["gap"] for e in work["entries"] for s in e["senses"]}
        if a.gap and a.gap not in gaps:
            continue
        if len(work["xml"]) > LARGE:
            bundles.append([f.stem])
        else:
            current.append(f.stem)
            if len(current) == a.size:
                bundles.append(current)
                current = []
        if len(bundles) >= a.bundles:
            break
    if current and len(bundles) < a.bundles:
        bundles.append(current)
    print(json.dumps({"root": str(HERE.parent), "lng": a.lng, "holdout": a.holdout, "run": a.run,
                      "model": a.model, "bundles": bundles}, ensure_ascii=False))


if __name__ == "__main__":
    main()
