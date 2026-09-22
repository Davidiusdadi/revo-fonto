# wikt-enrich

Fills missing translations in this ReVo fork from Wiktionary. No word is ever written by a
language model: every inserted translation is one that Wiktionary editors put in a translation
table next to the Esperanto word. Scripts collect the candidates and their evidence; a model
reads each one against the entry's definition and may only accept it into a sense or reject it.

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

### Other languages

The same measurement for the strong-evidence rule (own edition, ≥ 4 editions, unambiguous sense,
at most three words per entry), for every language that has an edition in the dumps:

| | holdout match | holdout candidates | note |
|---|---|---|---|
| de · en | 90 % · 89 % | 4,068 · 5,303 | filled, through the judge, read by a speaker |
| pt · ru · es | 93 % · 93 % · 91 % | 1,419 · 2,659 · 1,159 | not filled: needs a reader (below) |
| nl · fr · pl · cs | 92 % · 92 % · 92 % · 89 % | 1,103 · 4,673 · 3,528 · 584 | not filled: needs a reader |
| it · tr | 92 % · 91 % | 185 · 137 | not filled: needs a reader; small holdout |
| el | 86 % | 198 | not filled: weaker, small holdout (88 % at ≥ 5 editions) |
| ja · zh | 83 % · 80 % | 835 · 771 | not filled: misses are mostly script variants and synonyms, and ReVo writes a `<pr>` transcription that `apply.py` does not produce |
| ku · ko | 71 % · 63 % | 98 · 177 | not filled: ReVo's own translations differ in kind (inflected forms, other vocabulary), so the holdout cannot vouch |

Latin has no edition in the dumps, so only the "others only" column applies to it: 84 % at 6+
editions on a holdout of 104, with vowel-length marks (*Mārs*) counted as misses. Not filled.

What did **not** predict correctness: how many of ReVo's existing translations appear in the same
Wiktionary row ("anchors"). A broad row lists several Esperanto and several German words, and an
anchor confirms the row's sense, not the pairing. Anchors are used only to choose the `<snc>`.

Two normalisations matter: en.wiktionary writes Cyrillic with stress accents (U+0301 is stripped
before comparing and never written), and it files dialects (Bavarian, Alemannic) under the parent language code.
Those rows are not filtered out; a dialect word only gets through if several editions list it.

## Why counting is not enough: homonyms

A first version wrote the strong-evidence words without any model. Wiktionary lists an Esperanto
word by its spelling only, while ReVo keeps homonyms as separate entries, and candidates are found
by spelling. So *flea*, correct for *pulo*, was also written into the other *pulo*, a coin of
Afghanistan; *Kiel* into *kilo* = kilogram; *almond* into *migdalo*, the part of the brain. Of the
words written that way, 134 sat in entries that share their spelling with another entry, and of the
German and English ones among them about three in four were wrong. A guard on same-spelled entries
catches what ReVo knows, but not a meaning Wiktionary has and ReVo lacks. Requiring an anchor does
not help either: *almond* has seven, because many languages use one word for both. Only reading
the definition does, so every candidate now goes to the judge, which is shown the other
same-spelled entries (`same_spelling`), and only languages someone here can read are filled.

## Who decides

| | | decided by |
|---|---|---|
| judged | every gap entry that has a candidate | a model with no tools and no network, given a packet: accept into a sense, or reject |
| — | Wiktionary has no candidate | nothing; out of scope |

The packet (`judge/queue.py`) holds, per sense, the Esperanto definition, up to four examples with
ReVo's style codes, cross-references and existing translations in up to eight languages; the
article's root word with its definition; other entries of the same spelling; and per candidate the
number of editions, whether the own edition is among them, the source entries and its register
mark. One call judges a batch of 25 entries. `judge/prompt.md` carries a version number that is
stored with every result.

Measured on 300 German holdout entries (228 candidates, 36 % of which ReVo has): the share of
accepted words that ReVo has was 64–67 % for claude-haiku-4-5, 61–74 % for claude-opus-5 depending
on the prompt, 47–59 % for gpt-5.6-luna and -sol. The rest are largely valid synonyms, so the
difference that mattered was in the errors read by hand: Haiku accepted *Vulkanolog*, *Jungfrau*
for *virgulo* and the inflected *link*; Opus rejected them. Extended thinking did not repair any
of them and flipped one verdict in six between runs. Asking Haiku whether a verdict was "obvious"
did not either: it called every one of those errors obvious. Hence Opus for everything.
`run.py --model gpt-…` runs the same batch through the Codex CLI for comparison.

A language's judge is switched on only after it has been run on that language's holdout, where
its accept/reject can be compared with what ReVo has, and only when someone can read a sample of
what it accepts.

## Register marks

Slang, dated or regional words are real translations (*Birne* for *kapo*), provided the reader is
told. The mark is not the model's opinion: it comes from the tags the target language's own
Wiktionary puts on the senses of the word (`sense_tags.py`), mapped in `marks.toml` to a ReVo
code and to the label ReVo's translators already use in that language.

- The sense that lists the Esperanto word is known, or all senses of the page agree: the mark is
  set by script.
- The senses differ (*Birne*: fruit, lamp, colloquially head): the packet offers the page's marks
  and the judge chooses one or none for the sense it accepts the word in.
- No page in the own edition: no mark; a word that is plainly not neutral is then rejected.

Figurative use has no mark: ReVo expresses it by filing the word under a sense marked FIG, and
the judge places each word under the sense it actually names.

## How an inserted translation is marked

ReVo cites through keys that resolve in `cfg/bibliogr.xml`. This adds the key `Vikt` and uses the
`fnt` attribute the DTD provides on `<trd>` ("kie oni trovis la tradukon"):

```xml
<trd lng="de" fnt="Vikt: de en fr ku pl ru; juĝis claude-opus-5">Bildhauer</trd>
<trd lng="de" kod="ARK" fnt="Vikt: en pl; juĝis claude-opus-5">Hürde <klr>(veraltet)</klr></trd>
<trd lng="de" fnt="Vikt: de; juĝis claude-opus-5">Birne <klr>[ugs.]</klr></trd>
```

A mark is written twice, for two readers: `kod` (the DTD's "komputile interpretebla kodo") holds
the code from `stiloj.xml` or `fakoj.xml` where ReVo has one, for programs; `<klr>` holds the label
for people, as ReVo's translators have always written it. Registers ReVo has no code for
(colloquial, pejorative, regional, formal) have the label only. In `voko.db` these arrive as
`trd.kod` and as a `klr` row whose `parent` is the translation.

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
./sense_tags.py de                       # -> sense_tags.de.json: the own edition's register tags, 30 s
./packets.py --lng de                    # -> out/packets.de.jsonl, 1 min
./packets.py --lng de --holdout && ./score.py out/holdout.de.jsonl   # the table above

judge/queue.py --lng de                  # fixed numbered batches of 25, most used words first
judge/run.py --lng de --from 1 --to 5    # or --max-batches / --max-cost / --max-tokens
judge/run.py --status                    # progress, spend (usage.tsv), projected remainder

./apply.py --lng de                      # dry run + random sample to read
./apply.py --lng de --write              # insert, then validate every touched file against the DTD
```

`apply.py` reads `out/packets.<lng>.jsonl` and only uses a verdict whose candidate is still the
same word there, so after any change to the XML run `packets.py` again before `apply.py`.

`run.py` refuses to start without a limit. A batch result is written only when complete, so a run
can be interrupted, and a finished batch is never paid for again.

## Reviewing, reverting, refreshing

Every added word stays recognisable by its `fnt`, and that is what makes later passes possible:
a better model, corrected dumps, another source.

- **Reviewed.** A person who checks a word appends `; kontrolita` to its `fnt`
  (`fnt="Vikt: de en; juĝis claude-opus-5; kontrolita"`). The origin stays visible; who checked
  it is in the commit log, as ReVo keeps people out of the XML. Reverting and refreshing leave
  such words alone.
- **Revert.** `revert.py --lng de [--judge MODEL] [--max-editions N] [--include-reviewed]`
  (dry run; `--write` edits and validates) removes added words by what their `fnt` says. It only
  removes lines in the shape `apply.py` wrote them, so a full revert restores the files
  byte for byte; anything reshaped by hand is reported, not touched.
- **Refresh.** `revert.py --write` for the unreviewed words, then `packets.py`, `judge/queue.py`,
  `judge/run.py`, `apply.py` as for a first run. Each judge result stores a hash of the batch it
  judged, so a rebuilt queue is judged again where its contents changed and never matched against
  old verdicts. Verdicts are matched by word, not candidate number, and written in the order the
  judge saw them: reverting and re-applying the same results reproduces the files exactly.
  An entry that keeps a reviewed word is no longer a gap and is not judged again.

The XML is the truth. The gap is recomputed from it each time, so an entry that has a translation
in the language, from anyone, is never touched again, and a second run changes nothing. Existing
`<trd>` are never edited. `apply.py` inserts text and leaves every other byte alone (entities,
line endings); a file whose layout is not one `<trd>` per line is reported and skipped.

## Licence note

Wiktionary text is CC BY-SA; ReVo is GPL-2.0. Individual word pairs are facts rather than
expression, and every inserted word names its source editions, but this is unsettled and should be
before any of it is offered upstream.
