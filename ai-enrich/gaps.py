#!/usr/bin/env python3
"""Write one work file per article that lacks words in the target language, for the AI workflow.

  gaps.py --lng de                  work files       -> out/<lng>/work/<article>.json
  gaps.py --lng de --holdout 100    calibration: entries that HAVE the language, with it hidden
                                    -> out/<lng>/holdout/work/<article>.json, truth.json beside it

Reads the article XML directly (no voko.db needed). A work file carries everything an agent needs
for most decisions, so it does not have to look further (README, "What an agent sees"):

- the article's XML as written (in a holdout, without the hidden language);
- per entry and sense: the Esperanto definition, examples, usage tags and references, and every
  language's words. ReVo's own words and those a Wiktionary run supplied (fnt "Vikt: ...") are
  kept apart; only ReVo's own count as evidence;
- the gap each entry or sense is: A the entry has no word in the language at all, B a sense has
  none and neither has the entry, C a sense has none but the entry has a whole-word one (which
  may or may not cover it);
- the target and the other target language's words of the entries a sense refers to (sin, vid,
  super ...), and the entries elsewhere spelled the same.

Gaps are counted only where other languages give evidence; an entry nobody translates stays out.
No model is involved here.
"""
import argparse, hashlib, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path
from lxml import etree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "wikt-enrich"))
from packets import REVO, parser, flat, context  # noqa: E402

TARGETS = ("de", "en", "zh")
OTHER = {"de": "en", "en": "de", "zh": "en"}   # the strongest single source for each target
SKIP_TRD = ("klr", "pr", "baz", "ofc")


def in_dif(node):
    """<trd>/<trdgrp> written inside the node's own definitions (a Latin name: <trd lng="la">Adiantum</trd>),
    not inside their examples."""
    for d in node.findall("dif"):
        stack = list(d)
        while stack:
            c = stack.pop(0)
            if c.tag in ("trd", "trdgrp"):
                yield c
            elif c.tag not in ("ekz", "klr") and isinstance(c.tag, str):
                stack.extend(c)


def words(node, rad):
    """[(lng, word, fnt)] for a node's own <trd>/<trdgrp>, not those of its examples or senses."""
    out = []
    for c in [*node, *in_dif(node)]:
        if c.tag == "trd" and c.get("lng"):
            out.append((c.get("lng"), " ".join(flat(c, rad, skip=SKIP_TRD).split()), c.get("fnt") or ""))
        elif c.tag == "trdgrp":
            for t in c.findall("trd"):
                out.append((c.get("lng"), " ".join(flat(t, rad, skip=SKIP_TRD).split()), t.get("fnt") or ""))
    return out


def by_lng(ws, supplied):
    """{lng: [word]} of ReVo's own words (supplied=False) or of the supplied ones (True)."""
    res = defaultdict(list)
    for l, w, f in ws:
        if bool(f.startswith(("Vikt:", "AI:"))) == supplied and w and w not in res[l]:
            res[l].append(w)
    return dict(res)


def esperanto_dif(n, rad):
    difs = [d for d in n.findall("dif") if d.get("lng", "eo") == "eo"]
    return " ".join(" ".join(flat(d, rad, skip=("ekz", "trd", "trdgrp", "fnt")).split()) for d in difs)[:500]


def refs_of(n):
    """Targets of a node's own references (not those in its examples, translations or subsenses)."""
    inner = {x for sub in n.iter("snc", "subsnc", "drv") if sub is not n for x in sub.iter()}
    return [(r.get("tip") or r.getparent().get("tip") or "vid", r.get("cel"))
            for r in n.iter("ref") if r not in inner and r.get("cel") and r.getparent().tag not in ("ekz", "trd")]


def read_article(path, p):
    """The article's entries: {mrk, eo, whole, senses}; each sense and whole carries its words."""
    art = etree.parse(str(path), p).getroot().find("art")
    if art is None:
        return []
    rad_el = art.find("kap/rad")
    rad = (rad_el.text or "").strip() if rad_el is not None else ""
    out = []
    for drv in art.iter("drv"):
        kap = drv.find("kap")
        if kap is None:
            continue
        head = " ".join(flat(kap, rad, skip=("fnt", "var", "ofc")).replace(",", " ").split())
        senses = []
        for i, n in enumerate(drv.iter("snc", "subsnc")):
            below = [w for sub in n.iter("snc", "subsnc") for w in words(sub, rad)]
            senses.append({
                "mrk": n.get("mrk") or f'{drv.get("mrk")}#{i + 1}',
                "kind": n.tag,
                "uzo": [u.text for u in n.findall("uzo") if u.text],
                "dif": esperanto_dif(n, rad),
                **context(n, rad),
                "refs": refs_of(n),
                "own": words(n, rad),
                "below": below,                   # the sense with its subsenses: what "has a word" means
            })
        out.append({"mrk": drv.get("mrk"), "eo": head, "dif": esperanto_dif(drv, rad),
                    "uzo": [u.text for u in drv.findall("uzo") if u.text], **context(drv, rad),
                    "refs": refs_of(drv), "whole": words(drv, rad),
                    "all": [w for n in drv.iter("drv", "subdrv", "snc", "subsnc") for w in words(n, rad)],
                    "senses": senses})
    return out


def langs(ws, supplied_too=True):
    return {l for l, _, f in ws if supplied_too or not f.startswith(("Vikt:", "AI:"))}


def classify(e, lng):
    """Set e["gap"] (A or None) and each sense's gap (B, C or None); evidence = ReVo's own words."""
    evidence = langs(e["all"], supplied_too=False) - {"eo", lng}
    e["gap"] = "A" if lng not in langs(e["all"]) and evidence else None
    whole = lng in langs(e["whole"])
    for s in e["senses"]:
        s["gap"] = None
        if lng in langs(s["below"]) or not (langs(s["below"], supplied_too=False) - {"eo", lng}):
            continue
        s["gap"] = "C" if whole else "B"


def index(arts):
    """mrk -> (entry, sense or None) for every entry and sense; eo headword -> entries."""
    by_mrk, same = {}, defaultdict(list)
    for es in arts.values():
        for e in es:
            by_mrk[e["mrk"]] = (e, None)
            same[e["eo"]].append(e)
            for s in e["senses"]:
                by_mrk[s["mrk"]] = (e, s)
    return by_mrk, same


def target_of(by_mrk, cel):
    """The entry or sense a reference points to: its mrk, else the nearest one above it."""
    while cel:
        if cel in by_mrk:
            return by_mrk[cel]
        cel = cel.rpartition(".")[0]
    return None


def ref_words(refs, by_mrk, lng, other):
    """The two target languages' words of what the references point to; one row per target, with
    every reference type that points there."""
    out = {}
    for tip, cel in refs:
        if cel in out:
            if tip not in out[cel]["tip"]:
                out[cel]["tip"] += f" {tip}"
            continue
        hit = target_of(by_mrk, cel)
        if not hit:
            continue
        e, s = hit
        mine = by_lng(s["below"] if s else e["all"], False)
        out[cel] = {"tip": tip, "cel": cel, "eo": e["eo"], lng: mine.get(lng, []), other: mine.get(other, [])}
    return list(out.values())


def sense_view(s, by_mrk, lng, other):
    v = {"mrk": s["mrk"], "kind": s["kind"], "gap": s["gap"], "dif": s["dif"]}
    for k in ("uzo", "ekz", "ref"):
        if s[k]:
            v[k] = s[k]
    v["words"] = by_lng(s["own"], False)
    if sup := by_lng(s["own"], True):
        v["supplied"] = sup
    if rw := ref_words(s["refs"], by_mrk, lng, other):
        v["ref_words"] = rw
    return v


def entry_view(e, by_mrk, same, lng, other):
    v = {"mrk": e["mrk"], "eo": e["eo"], "gap": e["gap"]}
    if e["dif"]:
        v["dif"] = e["dif"]
    for k in ("uzo", "ekz", "ref"):
        if e[k]:
            v[k] = e[k]
    v["whole_words"] = by_lng(e["whole"], False)
    if sup := by_lng(e["whole"], True):
        v["whole_supplied"] = sup
    if rw := ref_words(e["refs"], by_mrk, lng, other):
        v["ref_words"] = rw
    v["senses"] = [sense_view(s, by_mrk, lng, other) for s in e["senses"]]
    homs = [{"mrk": o["mrk"], "dif": (o["dif"] or next((s["dif"] for s in o["senses"] if s["dif"]), ""))[:120],
             lng: by_lng(o["all"], False).get(lng, [])} for o in same[e["eo"]] if o is not e]
    if homs:
        v["same_spelling"] = homs
    return v


def hide(xml, lng):
    """The article's XML without the language's translations (a holdout's view)."""
    xml = re.sub(rf'[ \t]*<trdgrp lng="{lng}">.*?</trdgrp>[ \t]*\n?', "", xml, flags=re.S)
    return re.sub(rf'[ \t]*<trd lng="{lng}"[^>]*>.*?</trd>[ \t]*\n?', "", xml, flags=re.S)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lng", required=True, choices=TARGETS)
    ap.add_argument("--holdout", type=int, metavar="N", help="N entries that have the language, hidden")
    ap.add_argument("--out", type=Path, default=HERE / "out")
    a = ap.parse_args()
    lng, other = a.lng, OTHER[a.lng]
    p = parser()
    arts = {}
    for path in sorted(REVO.glob("*.xml")):
        try:
            arts[path.stem] = read_article(path, p)
        except etree.XMLSyntaxError as e:
            print("skip", path.name, e, file=sys.stderr)
    by_mrk, same = index(arts)

    stats = Counter()
    if a.holdout:
        # entries whose words in the language are all ReVo's own and whose other languages give
        # evidence; picked by a hash of the mark, so the same set comes back every run
        pool = [(f, e) for f, es in arts.items() for e in es
                if lng in langs(e["all"], supplied_too=False) and lng not in (langs(e["all"]) - langs(e["all"], False))
                and langs(e["all"], False) - {"eo", lng}]
        chosen = sorted(pool, key=lambda fe: sha(fe[1]["mrk"]))[:a.holdout]
        picked = defaultdict(list)
        for f, e in chosen:
            picked[f].append(e)
        out = a.out / lng / "holdout" / "work"
        truth = {}
        for f, es in picked.items():
            for e in es:
                truth[e["mrk"]] = {"whole": by_lng(e["whole"], False).get(lng, []),
                                   "senses": {s["mrk"]: w for s in e["senses"] if (w := by_lng(s["own"], False).get(lng))}}
                for ws in (e["whole"], e["all"], *(s[k] for s in e["senses"] for k in ("own", "below"))):
                    ws[:] = [w for w in ws if w[0] != lng]
                classify(e, lng)
            write(out, f, [x for x in arts[f] if x in es], hide((REVO / f"{f}.xml").read_text(encoding="utf-8"), lng),
                  by_mrk, same, lng, other, "holdout")
        (out.parent / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{lng} holdout: {len(chosen)} entries in {len(picked)} articles -> {out}")
        return

    out = a.out / lng / "work"
    for f, es in arts.items():
        for e in es:
            classify(e, lng)
            stats["entries"] += 1
            stats["A"] += e["gap"] == "A"
            for s in e["senses"]:
                if s["gap"]:
                    stats[f'{s["gap"]} {s["kind"]}'] += 1
        gapped = [e for e in es if e["gap"] or any(s["gap"] for s in e["senses"])]
        if gapped:
            stats["articles"] += 1
            stats["articles with A"] += any(e["gap"] for e in gapped)
            write(out, f, gapped, (REVO / f"{f}.xml").read_text(encoding="utf-8"), by_mrk, same, lng, other, "gap")
    print(f"{lng}: " + ", ".join(f"{k} {v}" for k, v in sorted(stats.items())) + f" -> {out}")


def write(out, f, entries, xml, by_mrk, same, lng, other, kind):
    out.mkdir(parents=True, exist_ok=True)
    work = {"article": f, "lng": lng, "other": other, "kind": kind,
            "entries": [entry_view(e, by_mrk, same, lng, other) for e in entries], "xml": xml}
    body = json.dumps(work, ensure_ascii=False, indent=1)
    work["sha"] = sha(body)
    (out / f"{f}.json").write_text(json.dumps(work, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
