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
import argparse, csv, datetime, json, os, subprocess, sys, tempfile, tomllib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from packets import HERE, mark_labels

USAGE = HERE / "usage.tsv"
COLS = ["time", "queue", "batch", "model", "entries", "candidates", "in", "cache_read", "cache_write", "out", "cost_usd", "accepted", "rejected"]
PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")
SCHEMA = (Path(__file__).parent / "schema.json").read_text(encoding="utf-8")


def rows():
    return list(csv.DictReader(open(USAGE, encoding="utf-8"), delimiter="\t")) if USAGE.exists() else []


def status():
    for q in sorted((HERE / "out").glob("queue.*")):
        total = len(list(q.glob("[0-9]*.json"))); done = len({p.name for p in (q / "results").rglob("*.json")})
        r = [x for x in rows() if x["queue"] == q.name]
        cost = sum(float(x["cost_usd"]) for x in r); tok = sum(int(x["in"]) + int(x["cache_read"]) + int(x["cache_write"]) + int(x["out"]) for x in r)
        acc = sum(int(x["accepted"]) for x in r); rej = sum(int(x["rejected"]) for x in r)
        rest = f", remaining ≈ ${cost / len(r) * (total - done):.2f} / {tok // len(r) * (total - done):,} tokens" if r else ""
        print(f"{q.name}: {done}/{total} batches, {tok:,} tokens, ${cost:.2f}, accepted {acc}, rejected {rej}{rest}")


def for_language(marks):
    """The schema with the language's closed list of register marks (marks.toml) filled in."""
    sc = json.loads(SCHEMA)
    sc["properties"]["verdicts"]["items"]["properties"]["mark"]["enum"] = [""] + marks
    return PROMPT, json.dumps(sc)


def judge_codex(batch, model, think, prompt, schema):
    """Same prompt and batch through the Codex CLI (models named gpt-*). Codex has no tool-free mode, so
    it runs in an empty folder with a read-only sandbox and none of the user's config; its usage report
    has tokens but no cost."""
    strict = json.loads(schema)                   # OpenAI's strict schemas want every property required
    strict["properties"]["verdicts"]["items"]["required"] = ["entry", "id", "sense", "mark", "why"]
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "schema.json").write_text(json.dumps(strict))
        out = subprocess.run(["codex", "exec", "-m", model, "-c", f'model_reasoning_effort="{"medium" if think else "low"}"',
                              "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
                              "--ignore-rules", "-C", tmp, "--output-schema", f"{tmp}/schema.json",
                              "-o", f"{tmp}/last.json", "--json", "-"],
                             input=prompt + "\n\nUse no tools. `why` is \"\" when accepting.\n\nThe entries:\n" + batch,
                             capture_output=True, text=True, timeout=1800)
        if out.returncode != 0 or not (Path(tmp) / "last.json").exists():
            raise RuntimeError(out.stderr[-800:] or out.stdout[-800:])
        u = {}
        for line in out.stdout.splitlines():
            try: ev = json.loads(line)
            except ValueError: continue
            if ev.get("type") == "turn.completed": u = ev.get("usage", {})
        cached = u.get("cached_input_tokens", 0)
        return {"result": (Path(tmp) / "last.json").read_text(encoding="utf-8"), "total_cost_usd": 0,
                "usage": {"input_tokens": u.get("input_tokens", 0) - cached, "cache_read_input_tokens": cached,
                          "output_tokens": u.get("output_tokens", 0)}}


def judge(batch, model, think, prompt, schema):
    if model.startswith("gpt-"):
        return judge_codex(batch, model, think, prompt, schema)
    env = dict(os.environ) if think else dict(os.environ, MAX_THINKING_TOKENS="0")
    out = subprocess.run(["claude", "-p", "--model", model, "--system-prompt", prompt, "--tools", "",
                          "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence",
                          "--output-format", "json", "--json-schema", schema],
                         input=batch, capture_output=True, text=True, timeout=900, env=env)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-500:] or out.stdout[-500:])
    return json.loads(out.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lng"); ap.add_argument("--holdout", action="store_true"); ap.add_argument("--model")
    ap.add_argument("--from", dest="lo", type=int); ap.add_argument("--to", dest="hi", type=int)
    ap.add_argument("--max-batches", type=int); ap.add_argument("--max-cost", type=float); ap.add_argument("--max-tokens", type=int)
    ap.add_argument("--status", action="store_true"); ap.add_argument("--tag")
    ap.add_argument("--prompt-file"); ap.add_argument("--schema-file")      # try a variant without touching the real ones
    ap.add_argument("--think", action="store_true", help="allow extended thinking (about 10x the output tokens)")
    a = ap.parse_args()
    if a.status:
        return status()
    if not a.lng or not (a.lo or a.max_batches or a.max_cost or a.max_tokens):
        sys.exit("give --lng and a limit: --from/--to, --max-batches, --max-cost or --max-tokens")
    cfg = tomllib.load(open(HERE / "languages.toml", "rb"))[a.lng]
    model = a.model or cfg["judge"]
    global PROMPT, SCHEMA
    if a.prompt_file: PROMPT = Path(a.prompt_file).read_text(encoding="utf-8")
    if a.schema_file: SCHEMA = Path(a.schema_file).read_text(encoding="utf-8")
    prompt, schema = for_language(list(mark_labels(a.lng)))
    q = HERE / "out" / (f"queue.{a.lng}" + (".holdout" if a.holdout else "") + (f".{a.tag}" if a.tag else ""))
    label = model + ("+think" if a.think else "")
    res = q / "results" / label; res.mkdir(parents=True, exist_ok=True)
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
        r = judge(p.read_text(encoding="utf-8"), model, a.think, prompt, schema)
        raw = r.get("structured_output") or json.loads(r["result"])
        heads = {}                                     # a model sometimes names the entry by its headword
        for e in items: heads[e["eo"]] = None if e["eo"] in heads else e["mrk"]
        for v in raw["verdicts"]:
            if v["entry"] not in senses and heads.get(v["entry"]): v["entry"] = heads[v["entry"]]
        ok = [v for v in raw["verdicts"] if (v["entry"], v["id"]) in known
              and (v["sense"] == "reject" or v["sense"] in senses[v["entry"]])]   # unknown ids or senses are dropped
        if raw["verdicts"] and not ok:                # the model answered about something else: keep it to look at, do not count it
            (res / (p.stem + ".raw")).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            print(f"{p.stem}: no verdict matched the batch, raw answer kept"); continue
        offered = {(e["mrk"], c["id"]): c.get("marks", []) for e in items for c in e["candidates"]}
        for v in ok:                                   # the judge only chooses among marks the word's Wiktionary page offers
            if v.get("mark") not in offered[(v["entry"], v["id"])]: v.pop("mark", None)
        u = r.get("usage", {})
        row = dict(time=datetime.datetime.now().isoformat(timespec="seconds"), queue=q.name, batch=p.stem, model=label,
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
