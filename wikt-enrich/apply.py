#!/usr/bin/env python3
"""Write accepted translations into the article XML. The only script that edits revo/.

  apply.py --lng de            dry run: what would be inserted, plus a random sample to read
  apply.py --lng de --write    insert, then validate every touched file against the DTD

Accepted = the verdicts of the language's judge under out/queue.<lng>/results/. Nothing is
written on evidence counts alone: Wiktionary lists Esperanto words by spelling, ReVo keeps
homonyms apart, and only someone who reads the definition can tell which entry a word belongs to.

A word with a register mark (marks.toml) is written as
<trd lng="de" kod="ARK" fnt="...">Haupt <klr>(veraltet)</klr></trd>: kod for programs, where ReVo
has a code, <klr> for readers.

Idempotent: an entry that already has a translation in the language - anyone's - is skipped, and
existing <trd> are never changed. Insertion is textual so the files keep their entities and
layout; a file whose layout is not the usual one-<trd>-per-line is reported and left alone.
"""
import argparse, json, random, re, sys, tomllib
from collections import defaultdict
from pathlib import Path
from lxml import etree
from packets import HERE, REVO, DTD, DtdResolver, fnt, mark_labels, parser
sys.path.insert(0, str(HERE / "judge"))
from run import done_for

BIB = REVO.parent / "cfg" / "bibliogr.xml"
BIB_ENTRY = '''  <vrk mll="Vikt" tip="leksikono">
     <url>https://kaikki.org/</url>
     <tit>Vikivortaro (Wiktionary), tradukoj eltiritaj per wiktextract</tit>
  </vrk>

'''


def entity_map():
    """codepoint -> ReVo entity name, from voko-grundo (first definition wins)."""
    m = {}
    for name, cp in re.findall(r'<!ENTITY\s+(\w+)\s+"&#x([0-9a-fA-F]+);">', (DTD / "vokosgn.dtd").read_text(encoding="utf-8")):
        m.setdefault(int(cp, 16), name)
    return m


def encode(text, ents):
    out = []
    for ch in text:
        if ch in "&<>":
            out.append({"&": "&amp;", "<": "&lt;", ">": "&gt;"}[ch])
        elif ord(ch) < 128:
            out.append(ch)
        else:
            out.append(f"&{ents[ord(ch)]};" if ord(ch) in ents else f"&#x{ord(ch):04X};")
    return "".join(out)


def judged_tier(lng, cfg):
    """Accepted verdicts of the language's judge. A verdict only counts if the candidate it names is
    still the same word in the current packets; one decision per sense the judge placed words in."""
    model = cfg.get("judge")
    q = HERE / "out" / f"queue.{lng}"
    if not model or not (q / "results" / model).exists():
        return
    packets = {e["mrk"]: e for e in map(json.loads, open(HERE / "out" / f"packets.{lng}.jsonl", encoding="utf-8"))}
    for res in sorted((q / "results" / model).glob("[0-9]*.json")):
        if not done_for(q / "results" / model, q / res.name):
            print(f"{res.name}: judged a different batch than the queue now holds, skipped (run judge/run.py)", file=sys.stderr)
            continue
        sent = {(e["mrk"], c["id"]): c["word"] for e in json.loads((q / res.name).read_text(encoding="utf-8")) for c in e["candidates"]}
        by_node = defaultdict(list)
        for v in json.loads(res.read_text(encoding="utf-8"))["verdicts"]:
            e = packets.get(v["entry"])           # by word: candidate numbers shift when other languages fill in
            word = sent.get((v["entry"], v["id"]))
            c = e and next((c for c in e["candidates"] if c["word"] == word), None)
            if v["sense"] == "reject" or c is None:
                continue
            mark = c.get("mark") or (v.get("mark") if v.get("mark") in c.get("marks", []) else "")
            by_node[(v["entry"], None if v["sense"] == v["entry"] else v["sense"])].append({**c, "mark": mark, "judged_as": v["id"]})
        for (mrk, node), cs in by_node.items():
            e = packets[mrk]
            cs.sort(key=lambda c: int(c["judged_as"][1:]))   # the order the judge saw: strongest first
            yield {"file": e["file"], "drv": mrk, "eo": e["eo"], "lng": lng, "node": node,
                   "words": [{"word": c["word"], "mark": c["mark"], "fnt": fnt(c, lng, model)} for c in cs[: cfg.get("max_words", 3)]]}


def plan_file(path, decisions, ents, p, kods, node_only=False):
    """-> ([(line index, new lines, decision)], [(decision, why skipped)]) for one article.

    node_only (ai-enrich): a decision names the very node it fills, and only that node having the
    language already stops it; an entry translated whole can still get words for one sense."""
    with open(path, encoding="utf-8", newline="") as f:      # newline="": keep every byte as it is
        lines = f.read().splitlines(keepends=True)
    root = etree.parse(str(path), p).getroot()
    edits, skipped = [], []
    for d in decisions:
        drv = next((x for x in root.iter("drv") if x.get("mrk") == d["drv"]), None)
        if drv is None:
            skipped.append((d, "drv not found")); continue
        nodes = [drv] + list(drv.iter("snc", "subsnc"))
        def direct(n): return [c for c in n if c.tag in ("trd", "trdgrp")]
        if not node_only and any(c.get("lng") == d["lng"] for n in nodes for c in direct(n)):
            skipped.append((d, "already translated")); continue
        keys = [n.get("mrk") or f'{d["drv"]}#{i}' for i, n in enumerate(nodes)]
        if d["node"] in keys:
            node = nodes[keys.index(d["node"])]
        elif node_only and d["node"] is not None:
            skipped.append((d, "sense not found")); continue
        elif node_only:
            node = drv
        else:                                   # single-sense entry: go where its translations already are
            node = max(nodes, key=lambda n: len(direct(n)))
        if node_only and any(c.get("lng") == d["lng"] for c in direct(node)):
            skipped.append((d, "already translated")); continue
        kids = direct(node)
        after = next((c for c in kids if (c.get("lng") or "") > d["lng"]), None)
        if after is not None:
            at = after.sourceline - 1
            ok = lines[at].lstrip().startswith("<trd")
            indent = lines[at][: len(lines[at]) - len(lines[at].lstrip())]
        elif kids:
            close = "</trdgrp>" if kids[-1].tag == "trdgrp" else "</trd>"
            at = next((i for i in range(kids[-1].sourceline - 1, len(lines)) if close in lines[i]), None)
            ok = at is not None and lines[at].rstrip().endswith(close)
            first = lines[kids[-1].sourceline - 1]
            indent = first[: len(first) - len(first.lstrip())]
            at = (at or 0) + 1
        else:
            close = f"</{node.tag}>"
            last = max((x.sourceline for x in node.iter() if x.sourceline), default=node.sourceline)
            at = next((i for i in range(last - 1, len(lines)) if close in lines[i]), None)
            ok = at is not None and lines[at].strip() == close
            base = lines[at] if ok else ""
            indent = base[: len(base) - len(base.lstrip())] + "  "
        if not ok:
            skipped.append((d, "unusual layout")); continue
        ws = d["words"]
        def trd(w, lng=None):
            attrs = (f' lng="{lng}"' if lng else "") + (f' kod="{kods[w["mark"]]}"' if kods.get(w["mark"]) else "")
            klr = f' <klr>{encode(w["mark"], ents)}</klr>' if w["mark"] else ""
            return f'<trd{attrs} fnt="{w["fnt"]}">{encode(w["word"], ents)}{klr}</trd>'
        if len(ws) == 1:
            new = [f'{indent}{trd(ws[0], d["lng"])}\n']
        else:
            new = [f'{indent}<trdgrp lng="{d["lng"]}">\n']
            new += [f'{indent}  {trd(w)}{"," if i < len(ws) - 1 else ""}\n' for i, w in enumerate(ws)]
            new.append(f"{indent}</trdgrp>\n")
        d["node_used"] = node.get("mrk") or d["drv"]
        edits.append((at, new, d))
    return lines, edits, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lng", required=True)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--sample", type=int, default=30)
    a = ap.parse_args()
    cfg = tomllib.load(open(HERE / "languages.toml", "rb")).get(a.lng) or sys.exit(f"{a.lng}: not in languages.toml")
    if not cfg.get("fill") or cfg.get("needs"):
        sys.exit(f"{a.lng}: not switched on (fill={cfg.get('fill')}, needs={cfg.get('needs')})")
    by_file = defaultdict(list)
    for d in judged_tier(a.lng, cfg):
        by_file[d["file"]].append(d)
    ents, p, kods = entity_map(), parser(), mark_labels(a.lng)
    done, skips, touched = [], [], []
    for name in sorted(by_file):
        path = REVO / name
        lines, edits, skipped = plan_file(path, by_file[name], ents, p, kods)
        skips += skipped
        if not edits:
            continue
        for at, new, d in sorted(edits, key=lambda e: -e[0]):
            lines[at:at] = new
            done.append(d)
        if a.write:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("".join(lines))
            touched.append(path)
    why = defaultdict(int)
    for _, w in skips: why[w] += 1
    n_words = sum(len(d["words"]) for d in done)
    print(f'{a.lng}: {len(done)} entries, {n_words} words {"written" if a.write else "would be written"};'
          f' skipped: {dict(why) or "none"}')
    random.seed(7)
    for d in random.sample(done, min(a.sample, len(done))):
        print(f'  {d["eo"]:<24} → {", ".join(w["word"] + (" " + w["mark"] if w["mark"] else "") for w in d["words"]):<40} [{d["words"][0]["fnt"]}]')
    if not a.write:
        return
    v = etree.XMLParser(load_dtd=True, dtd_validation=True, no_network=True)
    v.resolvers.add(DtdResolver())
    bad = []
    for path in touched:
        try: etree.parse(str(path), v)
        except etree.XMLSyntaxError as e: bad.append((path.name, str(e)))
    print(f"validated {len(touched)} files against the DTD: {len(bad)} invalid")
    for b in bad: print("  INVALID", *b)
    bib = BIB.read_text(encoding="utf-8")
    if 'mll="Vikt"' not in bib:
        BIB.write_text(bib.replace('  <vrk mll="VivZam">', BIB_ENTRY + '  <vrk mll="VivZam">', 1), encoding="utf-8")
        print("added Vikt to cfg/bibliogr.xml")


if __name__ == "__main__":
    main()
