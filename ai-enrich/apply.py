#!/usr/bin/env python3
"""Write what the checker accepted into the article XML: words as <trd>, definitions as <dif lng>.

  apply.py --lng de                 dry run: counts, what is skipped and why, a sample to read
  apply.py --lng de --write         insert, then validate every touched file against the DTD
  apply.py --lng de --only words    just the words (or --only definitions), e.g. to commit them apart
  apply.py --lng de --holdout       dry run on the holdout results (words there are skipped, as the
                                    language is only hidden; definitions show how they would land)

Accepted = a check result (out/<lng>/results/<article>.check.json) whose proposals and verdicts
were made on the current work file (same work_sha, so an article whose XML changed since is
skipped until it is run again). A word is written only with the checker's accept; a definition
only with its accept, in the checker's wording.

  <trd lng="de" fnt="AI: pl fr ru; proponis M; kontrolis C">Teilstaat</trd>
  <trd lng="de" kod="ARK" fnt="AI: ...; serĉo">Haupt <klr>(veraltet)</klr></trd>
  <dif lng="de" fnt="AI: eo; tradukis M; kontrolis C">Ein Staat innerhalb eines Bundesstaats.</dif>

Words go where the proposal put them: under the sense, or under the entry for a whole-word
translation, at most 3 per place, the checker's order of acceptance being the proposer's order.
A Chinese word is written in both scripts, each with its pinyin: <trd>漢語 <pr>hànyǔ</pr></trd>.
A place that already has the language is skipped (someone filled it since); a word the entry
already has elsewhere is not repeated. A definition follows the node's Esperanto <dif>; a node
that already has one in the language is skipped. Insertion is textual (wikt-enrich/apply.py
plan_file), so files keep their entities and layout; an unusual layout is reported, not touched.
"""
import argparse, json, random, sys
from collections import defaultdict
from pathlib import Path
from lxml import etree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "wikt-enrich"))
from packets import REVO, DtdResolver, mark_labels, parser  # noqa: E402
from apply import BIB, encode, entity_map, plan_file  # noqa: E402

MAX_WORDS = 3
BIB_ENTRY = '''  <vrk mll="AI" tip="leksikono">
     <tit>Proponoj de lingvomodelo (Claude) laŭ la tradukoj de ReVo mem, kontrolitaj de dua modelo</tit>
  </vrk>

'''


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def accepted(lng, holdout=False):
    """-> (word decisions, definition decisions, skipped counts), per article."""
    base = HERE / "out" / lng / ("holdout" if holdout else "")
    words, difs, skipped = defaultdict(list), defaultdict(list), defaultdict(int)
    for check_path in sorted((base / "results").glob("*.check.json")):
        article = check_path.name[: -len(".check.json")]
        work_path, prop_path = base / "work" / f"{article}.json", base / "results" / f"{article}.propose.json"
        if not work_path.exists() or not prop_path.exists():
            skipped["no work file or proposal"] += 1; continue
        work, prop, check = load(work_path), load(prop_path), load(check_path)
        if not prop["work_sha"] == check["work_sha"] == work["sha"]:
            skipped["made on an older work file"] += 1; continue
        drv_of = {e["mrk"]: e["mrk"] for e in work["entries"]}
        drv_of |= {s["mrk"]: e["mrk"] for e in work["entries"] for s in e["senses"]}
        eo_of = {e["mrk"]: e["eo"] for e in work["entries"]}
        verdict = {(v["mrk"], v["word"]): v for v in check["verdicts"]}
        by_node = defaultdict(list)
        for pr in prop["proposals"]:
            v = verdict.get((pr["mrk"], pr["word"]))
            if not v or not v["accept"]:
                continue
            sources = " ".join(dict.fromkeys(pr["sources"]))
            fnt = f"AI: {sources}; proponis {prop['model']}; kontrolis {check['model']}" + ("; serĉo" if v["searched"] else "")
            if lng == "zh":                          # both scripts, traditional first, each with its pinyin
                py, trad = v.get("pinyin") or pr.get("pinyin"), v.get("traditional") or pr.get("traditional")
                by_node[pr["mrk"]].append([{"word": f, "mark": "", "pr": py, "fnt": fnt}
                                           for f in dict.fromkeys(x for x in (trad, pr["word"]) if x)])
            else:
                by_node[pr["mrk"]].append([{"word": pr["word"], "mark": v["mark"], "fnt": fnt}])
        for mrk, ws in by_node.items():
            drv = drv_of[mrk]
            words[article].append({"file": f"{article}.xml", "drv": drv, "eo": eo_of[drv], "lng": lng,
                                   "node": None if mrk == drv else mrk, "words": [w for g in ws[:MAX_WORDS] for w in g]})
        for d in check["definitions"]:
            if d["accept"] and d["text"].strip():
                text = " ".join(d["text"].split())
                if text.endswith((":", "：")):       # copied from an Esperanto dif that examples follow
                    text = text[:-1].rstrip() + ("。" if lng == "zh" else ".")
                difs[article].append({"drv": drv_of[d["mrk"]], "node": d["mrk"], "text": text,
                                      "fnt": f"AI: eo; tradukis {prop['model']}; kontrolis {check['model']}"})
    return words, difs, skipped


def existing_words(root, drv_mrk, lng):
    drv = next((x for x in root.iter("drv") if x.get("mrk") == drv_mrk), None)
    if drv is None:
        return set()
    return {" ".join("".join(t.itertext()).split()).lower() for t in drv.iter("trd")
            if (t.get("lng") or t.getparent().get("lng")) == lng}


def plan_difs(lines, root, decisions, lng, ents):
    """-> ([(line index, new lines, decision)], [(decision, why skipped)]): each after its node's Esperanto <dif>."""
    edits, skipped = [], []
    for d in decisions:
        drv = next((x for x in root.iter("drv") if x.get("mrk") == d["drv"]), None)
        nodes = [drv] + list(drv.iter("snc", "subsnc")) if drv is not None else []
        keys = [n.get("mrk") or f'{d["drv"]}#{i}' for i, n in enumerate(nodes)]
        if d["node"] not in keys:
            skipped.append((d, "node not found")); continue
        node = nodes[keys.index(d["node"])]
        if any(x.get("lng") == lng for x in node.findall("dif")):
            skipped.append((d, "already has one")); continue
        eo = [x for x in node.findall("dif") if x.get("lng", "eo") == "eo"]
        if not eo:
            skipped.append((d, "no Esperanto definition")); continue
        last = max((x.sourceline for x in eo[-1].iter() if x.sourceline), default=eo[-1].sourceline)
        at = next((i for i in range(last - 1, len(lines)) if "</dif>" in lines[i]), None)
        if at is None or not lines[at].rstrip().endswith("</dif>"):
            skipped.append((d, "unusual layout")); continue
        first = lines[eo[-1].sourceline - 1]
        indent = first[: len(first) - len(first.lstrip())]
        d["node_used"] = d["node"]
        edits.append((at + 1, [f'{indent}<dif lng="{lng}" fnt="{d["fnt"]}">{encode(d["text"], ents)}</dif>\n'], d))
    return edits, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lng", required=True, choices=("de", "en", "zh"))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--only", choices=("words", "definitions"))
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--sample", type=int, default=30)
    a = ap.parse_args()
    if a.holdout and a.write:
        sys.exit("--holdout is a dry run only")
    words, difs, not_read = accepted(a.lng, a.holdout)
    ents, p, kods = entity_map(), parser(), mark_labels(a.lng)
    done_w, done_d, why, touched = [], [], defaultdict(int), []
    if a.only == "words":
        difs = {}
    elif a.only == "definitions":
        words = {}
    for article in sorted(set(words) | set(difs)):
        path = REVO / f"{article}.xml"
        root = etree.parse(str(path), p).getroot()
        ws = []
        for d in words.get(article, []):
            have = existing_words(root, d["drv"], a.lng)
            d["words"] = [w for w in d["words"] if w["word"].lower() not in have]
            if d["words"]:
                ws.append(d)
            else:
                why["words: already in the entry"] += 1
        lines, edits, skipped = plan_file(path, ws, ents, p, kods, node_only=True)
        for d, w in skipped:
            why[f"words: {w}"] += 1
        if difs:
            d_edits, d_skipped = plan_difs(lines, root, difs.get(article, []), a.lng, ents)
            for d, w in d_skipped:
                why[f"definitions: {w}"] += 1
            edits += d_edits
        if not edits:
            continue
        # from the bottom up, so earlier line numbers hold; at one line, words before definitions
        for at, new, d in sorted(edits, key=lambda e: (-e[0], "text" in e[2])):
            lines[at:at] = new
            (done_d if "text" in d else done_w).append(d)
        if a.write:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("".join(lines))
            touched.append(path)
    n_words = sum(len(d["words"]) for d in done_w)
    verb = "written" if a.write else "would be written"
    print(f"{a.lng}: {n_words} words in {len(done_w)} places, {len(done_d)} definitions {verb}")
    print(f"  results not read: {dict(not_read) or 'none'}; skipped: {dict(why) or 'none'}")
    random.seed(7)
    for d in random.sample(done_w, min(a.sample, len(done_w))):
        print(f'  {d["eo"]:<22} {d.get("node_used") or d["drv"]:<24} → '
              f'{", ".join(w["word"] + (" " + w["mark"] if w["mark"] else "") for w in d["words"]):<36} [{d["words"][0]["fnt"]}]')
    for d in random.sample(done_d, min(a.sample // 3, len(done_d))):
        print(f'  dif {d["node_used"]:<28} {d["text"][:110]}')
    if not a.write:
        return
    v = etree.XMLParser(load_dtd=True, dtd_validation=True, no_network=True)
    v.resolvers.add(DtdResolver())
    bad = []
    for path in touched:
        try:
            etree.parse(str(path), v)
        except etree.XMLSyntaxError as e:
            bad.append((path.name, str(e)))
    print(f"validated {len(touched)} files against the DTD: {len(bad)} invalid")
    for b in bad:
        print("  INVALID", *b)
    bib = BIB.read_text(encoding="utf-8")
    if 'mll="AI"' not in bib:
        BIB.write_text(bib.replace('  <vrk mll="Vikt"', BIB_ENTRY + '  <vrk mll="Vikt"', 1), encoding="utf-8")
        print("added AI to cfg/bibliogr.xml")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
