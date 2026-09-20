# wikt-enrich

Fills missing translations in this ReVo fork from Wiktionary. No word is ever written by a
language model: every inserted translation is one that Wiktionary editors put in a translation
table next to the Esperanto word. Scripts decide where the evidence is strong; a model is only
asked to accept or reject a given candidate where it is not.

## Source

[Kaikki](https://kaikki.org/) publishes [wiktextract](https://github.com/tatuylonen/wiktextract)
dumps of 16 useful Wiktionary editions as JSONL. `manifest.tsv` records URL, date, size and sha256
of the dumps a run used; Kaikki overwrites them weekly, so keep the files. There is no extract of
the Esperanto Wiktionary. What links the languages is the translation table of any entry: one
sense of German *Hund* lists eo *hundo*, es *perro*, en *dog*. `extract.py` keeps every such row
that mentions Esperanto.

Sources are always all editions. Which languages get **filled** is a separate, explicit list in
`languages.toml`.

## What counts as evidence

Measured on a holdout: take entries where ReVo already has the language, hide it, and see whether
the candidates reproduce it (`packets.py --holdout`, `score.py`). Exact match with ReVo per
candidate (dumps of 2026-09-16…20, ReVo f6da172; ~19,000 de and ~17,600 en holdout entries):

| editions listing the pair | de: own edition among them | de: others only | en: own edition among them | en: others only |
|---|---|---|---|---|
| 1 | 30 % | 14 % | 34 % | 10 % |
| 2 | 61 % | 31 % | 59 % | 29 % |
| 3 | 74 % | 44 % | 71 % | 42 % |
| 4 | 83 % | 60 % | 80 % | 50 % |
| 5 | 87 % | 65 % | 85 % | 59 % |
| 6+ | 94 % | 77 % | 93 % | 57 % |

Two things carry the signal. **How many editions** independently list the same eo–word pair, and
above all **whether the target language's own Wiktionary is one of them**: when the German page
*Südafrika* says "Esperanto: Sud-Afriko", German editors made the pairing themselves. A Polish or
Dutch page that lists both words under one sense only implies it. The own edition roughly doubles
the rate at every count.

Exact match is a lower bound: in the strong tiers nearly all misses are synonyms or spelling
variants (*Photograph* for ReVo's *Fotograph*, *Schraubendreher* for *Schraubenzieher*); the rest
are near misses such as a broader term or a feminine form.

What did **not** predict correctness: how many of ReVo's existing translations appear in the same
Wiktionary row ("anchors"). A broad row lists several Esperanto and several German words, and an
anchor confirms the row's sense, not the pairing. Anchors are used only to choose the `<snc>`.

Two normalisations matter: en.wiktionary writes Cyrillic with stress accents (U+0301 is stripped
before comparing), and it files dialects (Bavarian, Alemannic) under the parent language code.
Those rows are not filtered out; a dialect word only gets through if several editions list it.

## Tiers

| | rule | decided by |
|---|---|---|
| script | the language's own Wiktionary lists the pair, ≥ `script_min_editions` editions do in total (4 = own + 3 others: 80–94 % above), the source entry's part of speech does not contradict the Esperanto ending, and the sense is unambiguous (one sense, or all anchors point to one) | `apply.py`, no model |
| judged | everything else that has a candidate: fewer editions, indirect sources only, or an ambiguous sense | a model with no tools, given a packet: accept into a sense, or reject |
| — | Wiktionary has no candidate | nothing; out of scope |

A language's judge is switched on only after it has been run on that language's holdout, where
its accept/reject can be compared with what ReVo has. That is also how languages nobody here
reads can be added later.

## How an inserted translation is marked

ReVo cites through keys that resolve in `cfg/bibliogr.xml`. This adds the key `Vikt` and uses the
`fnt` attribute the DTD provides on `<trd>` ("kie oni trovis la tradukon"):

```xml
<trd lng="de" fnt="Vikt: de en fr ku pl ru">Bildhauer</trd>
<trd lng="de" fnt="Vikt: en fr; juĝis claude-haiku-4-5">…</trd>
```

`Vikt: <editions listing the pair>[; juĝis <model>[ +reto]]`, the language's own edition first
when it is among them. In that edition the page is the word itself
(`https://de.wiktionary.org/wiki/Bildhauer`). The build carries the attribute into `voko.db`
(`trd.fnt`), so a front end can show origin and strength, and because the editions are spelled
out, a later change of rule ("drop everything without the own edition") is a grep, not a rerun.
The exact source entries of any candidate are in `out/packets.<lng>.jsonl` (`rows`), which can be
regenerated from the dumps in `manifest.tsv`.

## Running it

```sh
export WIKT_DATA=/path/to/dumps          # default ./data (a symlink is fine); ~5.4 GB
export VOKO_DTD=/path/to/voko-grundo/dtd # default ../../voko-grundo/dtd
export WIKT_FREQ=/path/to/word-count.tsv # optional: orders the judge queue by usage

./fetch.sh                               # download what is missing, verify against manifest.tsv
./extract.py de es en fr pl ru pt zh ja el nl cs it tr ko ku     # -> eo_links_all.db, ~25 min
./packets.py --lng de                    # -> out/packets.de.jsonl, 15 s
./packets.py --lng de --holdout && ./score.py out/holdout.de.jsonl   # the table above
./apply.py --lng de                      # dry run + random sample to read
./apply.py --lng de --write              # insert, then validate every touched file against the DTD

judge/queue.py --lng de                  # fixed numbered batches of 25, most used words first
judge/run.py --lng de --from 1 --to 5    # or --max-batches / --max-cost / --max-tokens
judge/run.py --status                    # progress, spend (usage.tsv), projected remainder
```

`run.py` refuses to start without a limit. A batch result is written only when complete, so a run
can be interrupted, and a finished batch is never paid for again.

## Reruns

The XML is the truth. The gap is recomputed from it each time, so an entry that has a translation
in the language, from anyone, is never touched again, and a second run changes nothing. Existing
`<trd>` are never edited or removed. `apply.py` inserts text and leaves every other byte alone
(entities, line endings); a file whose layout is not one `<trd>` per line is reported and skipped.
New dumps or upstream merges simply produce new packets.

## Licence note

Wiktionary text is CC BY-SA; ReVo is GPL-2.0. Individual word pairs are facts rather than
expression, and every inserted word names its source editions, but this is unsettled and should be
before any of it is offered upstream.
