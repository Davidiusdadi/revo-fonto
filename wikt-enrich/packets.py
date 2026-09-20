#!/usr/bin/env python3
"""Build one packet per ReVo entry that lacks a translation in the target language.

Reads the article XML directly (no voko.db needed) and the Esperanto-linked Wiktionary rows
from eo_links_all.db (see extract.py). A packet carries the entry's senses, what ReVo already
translates, and every Wiktionary candidate with its evidence. No model is involved here.

  packets.py --lng de                 gap packets      -> out/packets.de.jsonl
  packets.py --lng de --holdout       calibration: entries that HAVE German, with it hidden;
                                      each packet then also carries the hidden truth

Which candidates are strong enough to insert without a judge is decided later (apply.py,
languages.toml); a packet only states the evidence.
"""
import argparse, json, os, sqlite3, sys, unicodedata
from collections import defaultdict
from pathlib import Path
from lxml import etree

HERE = Path(__file__).resolve().parent
REVO = HERE.parent / "revo"
DTD = Path(os.environ.get("VOKO_DTD", HERE.parent.parent / "voko-grundo" / "dtd"))
LINKS = Path(os.environ.get("WIKT_DATA", HERE / "data")) / "eo_links_all.db"
LNG_ALIAS = {"cmn": "zh", "nb": "no"}          # Wiktionary code -> ReVo code


def norm(s):
    """Fold for comparison: NFC, lowercase, no stress accent (en.wiktionary marks Cyrillic stress)."""
    s = unicodedata.normalize("NFD", s or "").replace("́", "")
    return " ".join(unicodedata.normalize("NFC", s).lower().split())


def eo_pos(head):
    """Part of speech from the Esperanto ending; None when it says nothing (particles, phrases)."""
    if " " in head or "-" in head.strip("-") or not head:
        return None
    w = head.lower()
    for suf in ("jn", "j", "n"):
        if w.endswith(suf) and len(w) > len(suf) + 1:
            w = w[: -len(suf)]; break
    return {"o": "noun", "a": "adj", "i": "verb", "e": "adv"}.get(w[-1]) if len(w) > 2 else None


def pos_fits(eo, src):
    """False only on a clear contradiction between the headword's ending and the source entry's POS."""
    src = {"name": "noun", "adv": "adj"}.get(src, src)
    eo = {"adv": "adj"}.get(eo, eo)
    return eo is None or src not in ("noun", "adj", "verb") or eo == src


def script_ok(c, lng, cfg):
    """The tier that needs no judge (README, "What counts as evidence"): the target language's
    own Wiktionary lists the pair, enough other editions agree, and the sense is unambiguous."""
    return (lng in c["editions"] and len(c["editions"]) >= cfg["script_min_editions"]
            and c["sense_clear"])


def fnt(c, lng, judge=None):
    """The fnt attribute: own edition first, then the others; '; juĝis <model>' when judged."""
    eds = sorted(c["editions"], key=lambda e: (e != lng, e))
    return "Vikt: " + " ".join(eds) + (f"; juĝis {judge}" if judge else "")


class DtdResolver(etree.Resolver):
    def resolve(self, url, pubid, context):
        if url.endswith(".dtd"):                  # the articles say ../dtd/, which the fork does not have
            return self.resolve_filename(str(DTD / os.path.basename(url)), context)


def parser():
    p = etree.XMLParser(load_dtd=True, resolve_entities=True, no_network=True)
    p.resolvers.add(DtdResolver())
    return p


def flat(el, rad, skip=()):
    """Element text with <tld/> expanded; subtrees named in skip are left out."""
    out = [el.text or ""]
    for c in el:
        if c.tag == "tld":
            lit = c.get("lit")
            out.append(lit + rad[1:] if lit else rad)
        elif c.tag not in skip and isinstance(c.tag, str):
            out.append(flat(c, rad, skip))
        out.append(c.tail or "")
    return "".join(out)


def own_trd(node, rad):
    """{lng: [word,...]} for <trd>/<trdgrp> that are direct children (so not example translations)."""
    res = defaultdict(list)
    for c in node:
        if c.tag == "trd" and c.get("lng"):
            res[c.get("lng")].append(" ".join(flat(c, rad, skip=("klr", "pr", "baz", "ofc")).split()))
        elif c.tag == "trdgrp":
            for t in c.findall("trd"):
                res[c.get("lng")].append(" ".join(flat(t, rad, skip=("klr", "pr", "baz", "ofc")).split()))
    return res


def entries(path, p):
    art = etree.parse(str(path), p).getroot().find("art")
    if art is None:
        return
    rad_el = art.find("kap/rad")
    rad = (rad_el.text or "").strip() if rad_el is not None else ""
    for drv in art.iter("drv"):
        kap = drv.find("kap")
        if kap is None:
            continue
        head = " ".join(flat(kap, rad, skip=("fnt", "var", "ofc")).replace(",", " ").split())
        nodes = [drv] + [n for n in drv.iter("snc", "subsnc")]
        senses = []
        for i, n in enumerate(nodes):
            dif = n.find("dif")
            senses.append({
                "mrk": n.get("mrk") or f'{drv.get("mrk")}#{i}',   # unmarked senses: position in the entry
                "kind": n.tag,
                "uzo": [u.text for u in n.findall("uzo") if u.text],
                "dif": " ".join(flat(dif, rad, skip=("ekz", "trd", "trdgrp", "fnt")).split())[:400] if dif is not None else "",
                "trd": own_trd(n, rad),
            })
        yield {"file": path.name, "mrk": drv.get("mrk"), "eo": head, "senses": senses}


def candidates(db, entry, lng, hide):
    """Wiktionary words in lng for this headword, each with evidence rows and anchors."""
    revo = defaultdict(set)                       # (lng, norm word) -> sense mrks holding it
    for s in entry["senses"]:
        for l, ws in s["trd"].items():
            if l != hide:
                for w in ws:
                    revo[(l, norm(w))].add(s["mrk"])
    rows = defaultdict(list)
    epos = eo_pos(entry["eo"])
    for ed, sw, pos, si, l, trd in db.execute(
            "SELECT edition, src_word, pos, sense_index, lng, trd FROM pivot WHERE eo=?", (entry["eo"],)):
        if pos_fits(epos, pos):                   # a noun row says nothing about a verb headword
            rows[(ed, sw, si)].append((LNG_ALIAS.get(l, l), trd))
    cands = {}
    for (ed, sw, si), items in rows.items():
        words = [t for l, t in items if l == lng]
        if not words:
            continue
        anchors = {(l, t): sorted(revo[(l, norm(t))]) for l, t in items if l != lng and (l, norm(t)) in revo}
        for w in words:
            c = cands.setdefault(norm(w), {"word": w, "rows": [], "anchors": {}, "editions": set()})
            c["rows"].append(f"{ed}:{sw}#{si}")
            c["editions"].add(ed)
            for (l, t), mrks in anchors.items():
                c["anchors"].setdefault(l, {"word": t, "senses": mrks})
    out = []
    for i, c in enumerate(sorted(cands.values(), key=lambda c: (-len(c["editions"]), -len(c["anchors"]), c["word"])), 1):
        hinted = {m for a in c["anchors"].values() for m in a["senses"]}
        n_snc = sum(1 for s in entry["senses"] if s["kind"] != "drv")
        clear = n_snc <= 1 or len(hinted) == 1
        out.append({"id": f"c{i}", "word": c["word"], "rows": sorted(set(c["rows"]))[:8],
                    "editions": sorted(c["editions"]), "anchors": c["anchors"],
                    "n_anchor_lngs": len(c["anchors"]), "sense_hint": sorted(hinted),
                    "sense_clear": clear})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lng", required=True)
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    db = sqlite3.connect(f"file:{LINKS}?mode=ro", uri=True)
    p = parser()
    out_dir = HERE / "out"; out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{'holdout' if a.holdout else 'packets'}.{a.lng}.jsonl"
    stats = defaultdict(int)
    with open(out, "w", encoding="utf-8") as f:
        for path in sorted(REVO.glob("*.xml")):
            try:
                es = list(entries(path, p))
            except etree.XMLSyntaxError as e:
                print("skip", path.name, e, file=sys.stderr); continue
            for e in es:
                stats["entries"] += 1
                truth = sorted({w for s in e["senses"] for w in s["trd"].get(a.lng, [])})
                if bool(truth) != a.holdout:
                    continue
                stats["in_scope"] += 1
                cs = candidates(db, e, a.lng, a.lng)
                if not cs:
                    continue
                if a.holdout:
                    e["truth"] = truth
                    for s in e["senses"]:
                        s["trd"].pop(a.lng, None)
                e["want"], e["candidates"] = a.lng, cs
                stats["with_candidate"] += 1
                stats[f'best_editions_{min(max(len(c["editions"]) for c in cs), 5)}'] += 1
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
                if a.limit and stats["with_candidate"] >= a.limit:
                    break
            else:
                continue
            break
    print(out, dict(stats))


if __name__ == "__main__":
    main()
