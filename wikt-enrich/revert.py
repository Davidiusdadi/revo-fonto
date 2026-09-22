#!/usr/bin/env python3
"""Take translations added from Wiktionary out of the XML again, selected by what their fnt says.

  revert.py --lng de                      dry run: what would be removed
  revert.py --lng de --judge claude-opus-5 --write
  revert.py --lng en --max-editions 1     only words that a single edition listed
  revert.py --lng de --include-reviewed   also words a person has checked (fnt ends "; kontrolita")

A person who checks a word appends "; kontrolita" to its fnt; such words are kept unless asked.
Only <trd> whose fnt starts with "Vikt:" are touched, and only as whole lines, the way apply.py
wrote them: a lone <trd lng> line, or members of a <trdgrp> that holds nothing else. A group
that loses members keeps its comma layout; one that loses all of them goes with its tags.
Anything else that carries a Vikt fnt (edited by hand into another shape) is reported, not touched.

Refreshing a language after a better model or new dumps is: revert.py (unreviewed words), then
packets.py, judge/queue.py, judge/run.py and apply.py as for a first run. An entry that keeps a
checked word is no longer a gap and is not judged again.
"""
import argparse, re, sys
from collections import Counter
from lxml import etree
from packets import REVO, DtdResolver

LONE = re.compile(r'^(\s*)<trd lng="(\w+)"( kod="\w+")? fnt="(Vikt:[^"]*)">.*</trd>\s*$')
OPEN = re.compile(r'^\s*<trdgrp lng="(\w+)">\s*$')
MEMBER = re.compile(r'^(\s*)<trd( kod="\w+")? fnt="(Vikt:[^"]*)">(.*</trd>)(,?)\s*$')
CLOSE = re.compile(r"^\s*</trdgrp>\s*$")


def chosen(fnt, a):
    eds, _, rest = fnt[len("Vikt:"):].partition(";")
    judge = re.search(r"juĝis (\S+)", fnt)
    return ((a.include_reviewed or "kontrolita" not in fnt)
            and (not a.judge or (judge and judge.group(1) == a.judge))
            and (a.max_editions is None or len(eds.split()) <= a.max_editions))


def revert_lines(lines, a, stats):
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        m = LONE.match(line)
        if m and m.group(2) == a.lng:
            if chosen(m.group(4), a): stats["words"] += 1; i += 1; continue
        g = OPEN.match(line)
        if g and g.group(1) == a.lng:
            j = i + 1
            while j < len(lines) and MEMBER.match(lines[j]): j += 1
            if j > i + 1 and j < len(lines) and CLOSE.match(lines[j]):
                members = [MEMBER.match(l) for l in lines[i + 1:j]]
                keep = [l for l, m in zip(lines[i + 1:j], members) if not chosen(m.group(3), a)]
                stats["words"] += len(members) - len(keep)
                if keep:
                    eol = "\r\n" if line.endswith("\r\n") else "\n"
                    keep = [re.sub(r",?\s*$", "", l) + ("," if k < len(keep) - 1 else "") + eol for k, l in enumerate(keep)]
                    out += [line, *keep, lines[j]]
                i = j + 1; continue
        if 'fnt="Vikt:' in line and f'lng="{a.lng}"' in line and not LONE.match(line):
            stats["not touched (hand-edited layout)"] += 1
        out.append(line); i += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lng", required=True)
    ap.add_argument("--judge", help="only words this model judged")
    ap.add_argument("--max-editions", type=int, help="only words listed by at most this many editions")
    ap.add_argument("--include-reviewed", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    stats, touched = Counter(), []
    for path in sorted(REVO.glob("*.xml")):
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
        if 'fnt="Vikt:' not in text:
            continue
        lines = text.splitlines(keepends=True)
        new = revert_lines(lines, a, stats)
        if new != lines:
            touched.append(path)
            if a.write:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write("".join(new))
    print(f'{a.lng}: {stats.pop("words", 0)} words in {len(touched)} files {"removed" if a.write else "would be removed"}'
          + (f"; {dict(stats)}" if stats else ""))
    if a.write:
        v = etree.XMLParser(load_dtd=True, dtd_validation=True, no_network=True)
        v.resolvers.add(DtdResolver())
        bad = []
        for p in touched:
            try: etree.parse(str(p), v)
            except etree.XMLSyntaxError as e: bad.append((p.name, str(e)))
        print(f"validated {len(touched)} files against the DTD: {len(bad)} invalid")
        for b in bad: print("  INVALID", *b)
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
