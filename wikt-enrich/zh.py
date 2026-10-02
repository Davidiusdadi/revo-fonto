#!/usr/bin/env python3
"""Chinese from Wiktionary, without a model judge: every candidate is written, scored by Jev.

ReVo writes Chinese in both scripts, each with its pinyin: <trd>漢語 <pr>hànyǔ</pr></trd>, <trd>汉语
<pr>hànyǔ</pr></trd>. Wiktionary candidates come in either script or as "漢語 /汉语"; the zh
edition supplies the other script and the pinyin.

  zh.py lex                 data/zh_lex.json: pinyin and traditional -> simplified, from the zh and en dumps (~10 min)
  zh.py score               ask Jev for every word group (cached in out/jev.zh.jsonl, resumable)
  zh.py                     dry run: what would be written, score distribution, a sample
  zh.py --write             insert, then validate every touched file against the DTD

Nobody here reads Chinese, so nothing is filtered on meaning: the fnt says the word is unreviewed
("Vikt: en zh; taksis Jev 87%") and the score orders the later review, lowest first. Only junk
the scripts can see is dropped: affix fragments, Latin letters, characters outside the Basic
Multilingual Plane (most fonts cannot show them).
"""
import argparse, concurrent.futures as cf, gzip, json, os, random, re, sys, time, urllib.error, urllib.request
from collections import Counter, defaultdict
from concurrent.futures import thread                    # before apply: it puts judge/queue.py on the path
from lxml import etree
from packets import HERE, REVO, LINKS, DtdResolver, parser
from apply import entity_map, plan_file

LEX = LINKS.parent / "zh_lex.json"
PACKETS = HERE / "out" / "packets.zh.jsonl"
CACHE = HERE / "out" / "jev.zh.jsonl"
MAX_GROUPS = 3
CONTEXT_LNGS = ("en", "de", "fr", "es", "ru", "ja", "pl", "nl", "pt", "it")
QUESTION = ("The Chinese word is a correct translation of the Esperanto word in the meaning the definition gives "
            "(same meaning and same part of speech, not a related or broader word, not a word from another "
            "meaning of the same spelling).")


def lex():
    """Standard-Mandarin pinyin per word (shared between the two scripts of a pair) and
    traditional -> simplified, per word and per character."""
    pinyin, t2s, pages = defaultdict(Counter), {}, 0
    for dump in ("zh", "en"):                             # en.wiktionary covers Chinese far more fully
        with gzip.open(LINKS.parent / f"{dump}-extract.jsonl.gz", "rt", encoding="utf-8") as f:
            for line in f:
                if '"lang_code": "zh"' not in line:
                    continue
                d = json.loads(line)
                if d.get("lang_code") != "zh" or "word" not in d:
                    continue
                pages += 1
                w = d["word"]
                for s in d.get("sounds", []):
                    t = set(s.get("tags", []))
                    pr = re.split(r"[，,(]", s.get("zh_pron") or "")[0].strip()
                    standard = t & {"Standard-Chinese", "Standard"} or t == {"Mandarin", "Pinyin"}
                    if {"Pinyin", "Mandarin"} <= t and standard and "Erhua" not in t and pr and not re.search(r"\d", pr):
                        pinyin[w][pr] += 1
                for fm in d.get("forms", []):
                    t = fm.get("tags", [])
                    if "Simplified-Chinese" in t and fm["form"] != w:
                        t2s[w] = fm["form"]
                    if "Traditional-Chinese" in t and fm["form"] != w:
                        t2s[fm["form"]] = w
    for trad, simp in t2s.items():                        # a pair shares its reading
        for a, b in ((trad, simp), (simp, trad)):
            if a in pinyin and b not in pinyin:
                pinyin[b] = pinyin[a]
    t2s = {a: b for a, b in t2s.items() if len(a) > 1}   # single characters also list dialect forms (格 -> 个)
    seen = defaultdict(Counter)                           # per character, learned from aligned word pairs
    for a, b in t2s.items():
        if len(a) == len(b):
            for x, y in zip(a, b):
                seen[x][y] += 1
    c2s = {}
    for x, c in seen.items():                             # the main non-identity conversion, when it clearly dominates
        other = Counter({y: n for y, n in c.items() if y != x})
        if other and (top := other.most_common(1)[0])[1] >= max(3, 0.9 * sum(other.values()), c[x]):
            c2s[x] = top[0]
    # a word pair whose characters do not all convert that way is a dialect or variant spelling, not the script pair
    t2s = {a: b for a, b in t2s.items() if len(a) == len(b) and all(x == y or c2s.get(x) == y for x, y in zip(a, b))}
    LEX.write_text(json.dumps({"pinyin": {w: [p for p, _ in c.most_common()] for w, c in pinyin.items()}, "t2s": t2s, "c2s": c2s},
                              ensure_ascii=False), encoding="utf-8")
    print(f"{LEX.name}: {pages} pages, pinyin for {len(pinyin)}, {len(t2s)} word pairs, {len(c2s)} character pairs")


def simplified(w, L):
    """Word-level pair first; else character by character (only characters that convert the same way in at least 90 % of word pairs)."""
    return L["t2s"].get(w) or "".join(L["c2s"].get(ch, ch) for ch in w)


HAN = re.compile(r"^[㐀-鿿豈-﫿〇·]+$")


def compose(w, L):
    """Pinyin for a phrase without a page: longest known words first, single characters only when they
    have one reading (的 has several, so 无私的 needs the word 无私 and a reading for 的: none). None when unsure."""
    out, i = [], 0
    while i < len(w):
        for j in range(len(w), i, -1):
            piece, rs = w[i:j], L["pinyin"].get(w[i:j])
            if rs and (j - i > 1 or len(set(rs)) == 1):
                out.append(rs[0]); i = j; break
        else:
            return None
    return "".join(out)


def groups(entry, L):
    """The entry's candidates as word groups {forms: [traditional, simplified], pinyin, editions, node},
    strongest first, at most MAX_GROUPS."""
    s2t = L["s2t"]
    out = {}
    for c in entry["candidates"]:
        for w in (x.strip() for x in c["word"].split("/")):
            if not HAN.match(w):                          # fragments (以-, 第……), Latin, outside the BMP
                continue
            simp = simplified(w, L)
            g = out.setdefault(simp, {"simp": simp, "seen": set(), "editions": set(), "hint": set(), "clear": True})
            g["seen"].add(w)
            g["editions"] |= set(c["editions"])
            g["hint"] |= set(c["sense_hint"])
            g["clear"] &= c["sense_clear"]
    res = []
    for g in sorted(out.values(), key=lambda g: -len(g["editions"])):
        trad = next((w for w in g["seen"] if w != g["simp"]), None) or next(iter(s2t.get(g["simp"], [])), g["simp"])
        forms = [trad, g["simp"]] if trad != g["simp"] else [g["simp"]]
        py = next((rs[0] for f in (*forms, *g["seen"]) if (rs := L["pinyin"].get(f)) and (len(f) > 1 or len(set(rs)) == 1)), None) \
            or next((c for f in forms if (c := compose(f, L))), None)
        res.append({"forms": forms, "pinyin": py, "editions": sorted(g["editions"], key=lambda e: (e != "zh", e)),
                    "hint": sorted(g["hint"]), "clear": g["clear"]})
    return res[:MAX_GROUPS]


def node_for(entry, g):
    n_snc = sum(1 for s in entry["senses"] if s["kind"] != "drv")
    if n_snc <= 1:
        return None                                       # apply.plan_file puts it where the translations are
    if g["clear"] and len(g["hint"]) == 1:
        return g["hint"][0]
    return entry["mrk"]                                   # meaning not settled: the whole entry


def state(entry, g):
    node = node_for(entry, g)
    senses = [s for s in entry["senses"] if node in (None, entry["mrk"]) or s["mrk"] == node]
    trd = defaultdict(list)
    for s in senses:
        for l in CONTEXT_LNGS:
            trd[l] += [w for w in s["trd"].get(l, []) if w and w not in trd[l]]
    return {"esperanto_word": entry["eo"],
            "definition": " | ".join(s["dif"] for s in senses if s["dif"])[:600],
            "translations_in_other_languages": {l: ws[:4] for l, ws in trd.items() if ws},
            "chinese_word": " / ".join(g["forms"])}


def jev_key():
    path = os.environ.get("JEV_ENV") or sys.exit("JEV_ENV: path of the .env holding Jev's API_KEY")
    for line in open(path):
        line = line.strip().removeprefix("export ")
        if line.startswith("API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    sys.exit("API_KEY not in JEV_ENV")


def send(key, body):
    data = json.dumps({"model": "jev-latest", **body}, ensure_ascii=False).encode()
    for attempt in range(8):
        req = urllib.request.Request("https://api.typesafe.ai/v1/systemone", data=data,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504, 529) and attempt < 7:
                time.sleep(min(float(e.headers.get("retry-after") or 2 ** attempt), 60)); continue
            return {"error": f"HTTP {e.code}"}
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 7:
                time.sleep(2 ** attempt); continue
            return {"error": str(e)}


def load_scores():
    if not CACHE.exists():
        return {}
    return {d["id"]: d for d in map(json.loads, open(CACHE, encoding="utf-8"))}


def score(entries, L):
    done, key = load_scores(), jev_key()
    todo = []
    for e in entries:
        for g in groups(e, L):
            body = {"state": state(e, g), "questions": {"ok": {"type": "noul", "instructions": QUESTION}}}
            i = f'{e["mrk"]}|{g["forms"][-1]}'
            if done.get(i, {}).get("request") != body:
                todo.append((i, body))
    tok = errs = 0
    with open(CACHE, "a", encoding="utf-8") as f, cf.ThreadPoolExecutor(12) as ex:
        futs = {ex.submit(send, key, b): (i, b) for i, b in todo}
        for k, fut in enumerate(cf.as_completed(futs), 1):
            (i, b), r = futs[fut], fut.result()
            if "answers" not in r:
                errs += 1; continue
            tok += r["usage"]["input_tokens"]
            f.write(json.dumps({"id": i, "p": r["answers"]["ok"]["noul"], "request": b}, ensure_ascii=False) + "\n")
            if k % 500 == 0:
                f.flush(); print(f"  {k}/{len(todo)}", flush=True)
    print(f"jev: asked {len(todo)}, {errs} errors, {tok / 1e6:.2f} Mtok (${tok * 0.042 / 1e6:.3f})")


def decisions(entries, L, scores):
    for e in entries:
        by_node = defaultdict(list)
        for g in groups(e, L):
            s = scores.get(f'{e["mrk"]}|{g["forms"][-1]}')
            if s is None:
                continue                                  # not scored yet: not written
            pct = round(s["p"] * 100)
            fnt = f'Vikt: {" ".join(g["editions"])}; taksis Jev {pct}%'
            by_node[node_for(e, g)] += [{"word": f, "mark": "", "pr": g["pinyin"], "fnt": fnt, "pct": pct} for f in g["forms"]]
        for node, ws in by_node.items():
            yield {"file": e["file"], "drv": e["mrk"], "eo": e["eo"], "lng": "zh", "node": node, "words": ws}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["lex", "score"])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--limit", type=int, help="score only the first N entries (trial)")
    a = ap.parse_args()
    if a.cmd == "lex":
        return lex()
    L = json.loads(LEX.read_text(encoding="utf-8"))
    L["s2t"] = defaultdict(list)
    for t, s in L["t2s"].items():
        L["s2t"][s].append(t)
    entries = [json.loads(l) for l in open(PACKETS, encoding="utf-8")]
    if a.cmd == "score":
        return score(entries[: a.limit] if a.limit else entries, L)
    by_file = defaultdict(list)
    for d in decisions(entries, L, load_scores()):
        by_file[d["file"]].append(d)
    ents, p = entity_map(), parser()
    done, skips, touched = [], Counter(), []
    for name in sorted(by_file):
        path = REVO / name
        lines, edits, skipped = plan_file(path, by_file[name], ents, p, {})
        skips.update(w for _, w in skipped)
        for at, new, d in sorted(edits, key=lambda x: -x[0]):
            lines[at:at] = new
            done.append(d)
        if a.write and edits:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("".join(lines))
            touched.append(path)
    words = [w for d in done for w in d["words"]]
    groups_ = {(d["drv"], w["fnt"], w["pr"]) for d in done for w in d["words"]}
    pcts = [int(f.split("Jev ")[1][:-1]) for _, f, _ in groups_]
    print(f'zh: {len({d["drv"] for d in done})} entries, {len(groups_)} word groups, {len(words)} <trd> '
          f'{"written" if a.write else "would be written"}; no pinyin: {sum(1 for w in words if not w["pr"])}; '
          f'skipped: {dict(skips) or "none"}')
    print("  Jev:", " ".join(f"{lo}-{lo + 19}%: {sum(lo <= x <= lo + 19 + (lo == 80) for x in pcts)}" for lo in range(0, 100, 20)))
    random.seed(7)
    for d in random.sample(done, min(a.sample, len(done))):
        print(f'  {d["eo"]:<22} {d["node"] or "":<22} ' + ", ".join(f'{w["word"]} {w["pr"] or "?"} ({w["pct"]}%)' for w in d["words"]))
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


if __name__ == "__main__":
    main()
