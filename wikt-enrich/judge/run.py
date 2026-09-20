#!/usr/bin/env python3
"""Run the judge over a slice of the queue - never more than it is told to.

  run.py --lng de --from 1 --to 5          exactly these batches
  run.py --lng de --max-batches 5          the next 5 pending
  run.py --lng de --max-cost 0.50          pending batches until the next would pass $0.50
  run.py --lng de --max-tokens 200000      same, on input+output tokens
  run.py --status                          progress and spend per queue
  add --holdout to work on out/queue.<lng>.holdout, --model to override languages.toml

A limit is mandatory. Each batch is one `claude -p` call with no tools and a JSON schema; its
result lands in out/<queue>/results/NNNN.json only when complete, so interrupting is safe and a
finished batch is never paid for again. Every call appends a row to usage.tsv.
"""
import argparse, csv, datetime, json, subprocess, sys, tomllib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from packets import HERE

USAGE = HERE / "usage.tsv"
COLS = ["time", "queue", "batch", "model", "entries", "candidates", "in", "cache_read", "cache_write", "out", "cost_usd", "accepted", "rejected"]
PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
SCHEMA = (Path(__file__).parent / "schema.json").read_text(encoding="utf-8")


def rows():
    return list(csv.DictReader(open(USAGE, encoding="utf-8"), delimiter="\t")) if USAGE.exists() else []


def status():
    for q in sorted((HERE / "out").glob("queue.*")):
        total = len(list(q.glob("[0-9]*.json"))); done = len(list((q / "results").glob("*.json")))
        r = [x for x in rows() if x["queue"] == q.name]
        cost = sum(float(x["cost_usd"]) for x in r); tok = sum(int(x["in"]) + int(x["cache_read"]) + int(x["cache_write"]) + int(x["out"]) for x in r)
        acc = sum(int(x["accepted"]) for x in r); rej = sum(int(x["rejected"]) for x in r)
        rest = f", remaining ≈ ${cost / len(r) * (total - done):.2f} / {tok // len(r) * (total - done):,} tokens" if r else ""
        print(f"{q.name}: {done}/{total} batches, {tok:,} tokens, ${cost:.2f}, accepted {acc}, rejected {rej}{rest}")


def judge(batch, model):
    out = subprocess.run(["claude", "-p", "--model", model, "--system-prompt", PROMPT, "--tools", "",
                          "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence",
                          "--output-format", "json", "--json-schema", SCHEMA],
                         input=batch, capture_output=True, text=True, timeout=900)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-500:] or out.stdout[-500:])
    return json.loads(out.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lng"); ap.add_argument("--holdout", action="store_true"); ap.add_argument("--model")
    ap.add_argument("--from", dest="lo", type=int); ap.add_argument("--to", dest="hi", type=int)
    ap.add_argument("--max-batches", type=int); ap.add_argument("--max-cost", type=float); ap.add_argument("--max-tokens", type=int)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        return status()
    if not a.lng or not (a.lo or a.max_batches or a.max_cost or a.max_tokens):
        sys.exit("give --lng and a limit: --from/--to, --max-batches, --max-cost or --max-tokens")
    model = a.model or tomllib.load(open(HERE / "languages.toml", "rb"))[a.lng]["judge"]
    q = HERE / "out" / (f"queue.{a.lng}" + (".holdout" if a.holdout else ""))
    res = q / "results" / model; res.mkdir(parents=True, exist_ok=True)
    todo = [p for p in sorted(q.glob("[0-9]*.json")) if not (res / p.name).exists()
            and (not a.lo or a.lo <= int(p.stem) <= (a.hi or a.lo))]
    if a.max_batches: todo = todo[: a.max_batches]
    spent = tokens = 0.0; n = 0
    for p in todo:
        avg_c, avg_t = (spent / n, tokens / n) if n else (0, 0)
        if (a.max_cost and spent + avg_c > a.max_cost) or (a.max_tokens and tokens + avg_t > a.max_tokens):
            print("limit reached before", p.name); break
        items = json.loads(p.read_text(encoding="utf-8"))
        known = {(e["mrk"], c["id"]) for e in items for c in e["candidates"]}
        senses = {e["mrk"]: {s["mrk"] for s in e["senses"]} | {e["mrk"]} for e in items}
        r = judge(p.read_text(encoding="utf-8"), model)
        raw = r.get("structured_output") or json.loads(r["result"])
        ok = [v for v in raw["verdicts"] if (v["entry"], v["id"]) in known
              and (v["sense"] == "reject" or v["sense"] in senses[v["entry"]])]   # unknown ids or senses are dropped
        u = r.get("usage", {})
        row = dict(time=datetime.datetime.now().isoformat(timespec="seconds"), queue=q.name, batch=p.stem, model=model,
                   entries=len(items), candidates=len(known), cache_read=u.get("cache_read_input_tokens", 0),
                   cache_write=u.get("cache_creation_input_tokens", 0), out=u.get("output_tokens", 0),
                   cost_usd=f'{r.get("total_cost_usd", 0):.4f}', accepted=sum(v["sense"] != "reject" for v in ok),
                   rejected=sum(v["sense"] == "reject" for v in ok))
        row["in"] = u.get("input_tokens", 0)
        (res / p.name).write_text(json.dumps({"model": model, "prompt_version": PROMPT.split("Version: ")[1].split()[0],
                                              "verdicts": ok, "dropped": len(raw["verdicts"]) - len(ok)}, ensure_ascii=False), encoding="utf-8")
        new = not USAGE.exists()
        with open(USAGE, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, COLS, delimiter="\t", lineterminator="\n")
            if new: w.writeheader()
            w.writerow(row)
        n += 1; spent += float(row["cost_usd"]); tokens += sum(int(row[k]) for k in ("in", "cache_read", "cache_write", "out"))
        print(f'{p.stem}: {row["accepted"]} accepted, {row["rejected"]} rejected, {int(tokens):,} tokens, ${spent:.3f} so far')
    status()


if __name__ == "__main__":
    main()
