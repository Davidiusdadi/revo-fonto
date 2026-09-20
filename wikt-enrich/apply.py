#!/usr/bin/env python3
"""Write accepted translations into the article XML. The only script that edits revo/.

  apply.py --lng de            dry run: what would be inserted, plus a random sample to read
  apply.py --lng de --write    insert, then validate every touched file against the DTD

Accepted = the script tier (packets.script_ok) plus, once judged, the accepted verdicts under
out/queue.<lng>/results/.

Idempotent: an entry that already has a translation in the language - anyone's - is skipped, and
existing <trd> are never changed. Insertion is textual so the files keep their entities and
layout; a file whose layout is not the usual one-<trd>-per-line is reported and left alone.
"""
import argparse, json, random, re, sys, tomllib
from collections import defaultdict
from pathlib import Path
from lxml import etree
from packets import HERE, REVO, DTD, DtdResolver, fnt, parser, script_ok

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


def script_tier(lng, cfg):
    """Decisions that need no judge: strong pair agreement and an unambiguous sense."""
    for line in open(HERE / "out" / f"packets.{lng}.jsonl", encoding="utf-8"):
        e = json.loads(line)
        good = [c for c in e["candidates"] if script_ok(c, lng, cfg)]
        if not good:
            continue
        hint = good[0]["sense_hint"]
        yield {"file": e["file"], "drv": e["mrk"], "eo": e["eo"], "lng": lng,
               "node": hint[0] if len(hint) == 1 else None,
               "words": [{"word": c["word"], "fnt": fnt(c, lng)} for c in good[: cfg.get("max_words", 3)]]}


def plan_file(path, decisions, ents, p):
    """-> ([(line index, new lines, decision)], [(decision, why skipped)]) for one article."""
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
        if any(c.get("lng") == d["lng"] for n in nodes for c in direct(n)):
            skipped.append((d, "already translated")); continue
        keys = [n.get("mrk") or f'{d["drv"]}#{i}' for i, n in enumerate(nodes)]
        if d["node"] in keys:
            node = nodes[keys.index(d["node"])]
        else:                                   # single-sense entry: go where its translations already are
            node = max(nodes, key=lambda n: len(direct(n)))
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
        if len(ws) == 1:
            new = [f'{indent}<trd lng="{d["lng"]}" fnt="{ws[0]["fnt"]}">{encode(ws[0]["word"], ents)}</trd>\n']
        else:
            new = [f'{indent}<trdgrp lng="{d["lng"]}">\n']
            new += [f'{indent}  <trd fnt="{w["fnt"]}">{encode(w["word"], ents)}</trd>{"," if i < len(ws) - 1 else ""}\n'
                    for i, w in enumerate(ws)]
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
    for d in script_tier(a.lng, cfg):
        by_file[d["file"]].append(d)
    ents, p = entity_map(), parser()
    done, skips, touched = [], [], []
    for name in sorted(by_file):
        path = REVO / name
        lines, edits, skipped = plan_file(path, by_file[name], ents, p)
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
        print(f'  {d["eo"]:<24} → {", ".join(w["word"] for w in d["words"]):<40} [{d["words"][0]["fnt"]}]')
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
