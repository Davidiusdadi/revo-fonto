#!/usr/bin/env python3
"""The workflow on the Codex CLI instead of Claude: per bundle a fresh proposer, then a fresh checker.

  codex.py <lng> <run> <slice.json> [--out DIR] [--parallel 8]
           [--propose-model gpt-5.6-sol --propose-effort medium --check-model gpt-5.6-sol --check-effort high]

<slice.json> is what slice.py prints. The task text is workflow.js's; each stage is its own `codex exec`
process, so the checker sees the saved proposals and nothing of the proposer's session. The proposer
has no web search, the checker has it. Completion is judged from the saved result files, not from what
an agent says. --out sets AI_OUT (default out/); logs go to out/<lng>/codex-logs/<run>/.
"""
import argparse, concurrent.futures as cf, json, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HOLDOUT = False                                     # set by --holdout

PREAMBLE = """You are one agent in a pipeline, running non-interactively: nobody can answer a question, so decide.
Use the shell only to read the files named below and to run `python3 ai-enrich/ask.py`. Change no file:
your only write is `ask.py save`, exactly as shown (keep the AI_OUT=... prefix). Do not start sub-agents.
Where the instructions name WebSearch/WebFetch, that means your own web search tool{search}.
"""


def task(stage, lng, run, model, out, articles):
    base = f"{out}/{lng}" + ("/holdout" if HOLDOUT else "")
    lines = [PREAMBLE.format(search="" if stage == "check" else " (you have none: the proposer does not search)"),
             f"Read {ROOT}/ai-enrich/prompt-{stage}.md and follow it exactly.",
             f"Target language: {lng}. Run tag: {run}. Model: {model}.",
             f"Work in {ROOT}: start every command with `cd {ROOT} && `.",
             "Handle these articles one after another, each on its own, and save each before starting the next:"]
    for a in articles:
        lines.append(f"- {a}: work file {base}/work/{a}.json"
                     + (f", proposals {base}/results/{a}.propose.json" if stage == "check" else "")
                     + f"; save with `cd {ROOT} && AI_OUT={out} python3 ai-enrich/ask.py save {stage} {lng} {a}"
                       f" --run {run} --model {model}{' --holdout' if HOLDOUT else ''} <<'JSON'`")
    lines.append("End with one line per article: saved, or not saved and why.")
    return "\n".join(lines)


def codex(prompt, model, effort, search, log):
    cmd = ["codex", "exec", "--ephemeral", "--disable", "memories", "-m", model,
           "-c", f'model_reasoning_effort="{effort}"', "-c", 'approval_policy="never"', "-c", "mcp_servers={}",
           "-c", f'web_search="{"live" if search else "disabled"}"',
           "-s", "workspace-write", "-C", str(ROOT), "--output-last-message", str(log.with_suffix(".md")), "-"]
    t = time.time()
    with open(log, "w") as f:
        p = subprocess.run(cmd, input=prompt, text=True, stdout=f, stderr=subprocess.STDOUT, timeout=3600)
    return p.returncode, time.time() - t


def saved(out, lng, stage, run, articles):
    ok = []
    for a in articles:
        f = Path(out) / lng / ("holdout" if HOLDOUT else "") / "results" / f"{a}.{stage}.json"
        if f.exists() and json.loads(f.read_text())["run"] == run:
            ok.append(a)
    return ok


def bundle(i, articles, a):
    logs = HERE / "out" / a.lng / "codex-logs" / a.run
    logs.mkdir(parents=True, exist_ok=True)
    # Resuming a run (after a usage limit, say) skips what this run already saved.
    todo = [x for x in articles if x not in saved(a.out, a.lng, "propose", a.run, articles)]
    if todo:
        rc, dt = codex(task("propose", a.lng, a.run, a.propose_model, a.out, todo), a.propose_model, a.propose_effort,
                       False, logs / f"{i:03d}-propose.log")
        print(f"bundle {i}: propose rc={rc} {dt:.0f}s", flush=True)
    prop = saved(a.out, a.lng, "propose", a.run, articles)
    print(f"bundle {i}: proposals saved {len(prop)}/{len(articles)}", flush=True)
    if a.propose_only:
        return articles, prop
    if not prop:
        return articles, []
    todo = [x for x in prop if x not in saved(a.out, a.lng, "check", a.run, prop)]
    if todo:
        rc, dt = codex(task("check", a.lng, a.run, a.check_model, a.out, todo), a.check_model, a.check_effort,
                       True, logs / f"{i:03d}-check.log")
        print(f"bundle {i}: check rc={rc} {dt:.0f}s", flush=True)
    chk = saved(a.out, a.lng, "check", a.run, prop)
    print(f"bundle {i}: checks saved {len(chk)}/{len(prop)}", flush=True)
    return articles, chk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lng"); ap.add_argument("run"); ap.add_argument("slice")
    ap.add_argument("--out", default=str(HERE / "out")); ap.add_argument("--parallel", type=int, default=8)
    ap.add_argument("--propose-model", default="gpt-5.6-sol"); ap.add_argument("--propose-effort", default="medium")
    ap.add_argument("--check-model", default="gpt-5.6-sol"); ap.add_argument("--check-effort", default="high")
    ap.add_argument("--propose-only", action="store_true", help="no checker; the proposals are scored elsewhere (Jev)")
    ap.add_argument("--holdout", action="store_true", help="the holdout work files (gaps.py --holdout)")
    a = ap.parse_args()
    global HOLDOUT
    HOLDOUT = a.holdout
    bundles = json.loads(Path(a.slice).read_text())["bundles"]
    with cf.ThreadPoolExecutor(a.parallel) as ex:
        res = list(ex.map(lambda ib: bundle(ib[0], ib[1], a), enumerate(bundles, 1)))
    done = [x for _, c in res for x in c]
    missing = [x for arts, c in res for x in arts if x not in c]
    what = "proposed" if a.propose_only else "checked"
    print(f"DONE {a.run}: {what} {len(done)}/{sum(map(len, bundles))}; not {what}: {missing or 'none'}")


if __name__ == "__main__":
    main()
