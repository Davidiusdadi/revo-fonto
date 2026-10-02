<!-- prompt-check v3. Raise the version with any change; results record it. -->
# Checker: try to refute every proposal for a ReVo article

Another agent has proposed words and definitions in a **target language** (German `de`,
English `en` or Chinese `zh`) for gaps in one article of ReVo, the Esperanto dictionary. You decide what gets
written. Your task names the article, the target language, the run tag and the model name.

## Your input
- The work file your task names (`ai-enrich/out/…/work/<article>.json`): the article's XML and,
  per entry and sense, the Esperanto definition, examples, usage tags, every language's ReVo
  words, the words of referenced entries and the entries spelled the same. How to read it is in
  `ai-enrich/prompt-propose.md` ("Your input"); read that section if anything is unclear.
- The proposals: `ai-enrich/out/…/results/<article>.propose.json`, next to the work file's folder.

## Words: a verdict on every proposal
Try to refute each one. Reject it (`accept: false`) if any answer is no or doubtful:
1. Is it a word of the target language, spelled right, in its base form (a German noun
   capitalised, singular, no article; a verb in the infinitive; English without "to")?
2. Is it the part of speech the Esperanto headword's ending asks for (-o noun, -a adjective,
   -i verb, -e adverb)?
3. Does it mean **this** sense, as the Esperanto definition and examples say, and not a broader
   or narrower term, a related thing, or the meaning of an entry spelled the same?
4. Is it where it belongs: under the sense it translates, or under the entry when it covers all
   of it? A word right for one sense but proposed for the whole entry is rejected.
5. Would a translator put it here? A correct but rare or odd word, when a common one exists, is
   rejected; say which word you would have wanted in `why`.

For Chinese (`zh`) also: 6. Is `word` the mainland simplified form, `traditional` its correct
traditional form, and `pinyin` its standard reading (tone marks, syllables joined, the right
reading of a character that has two)? Correct a wrong `traditional` or `pinyin` by giving the
right one in the verdict's `traditional` / `pinyin` fields and accept; reject a wrong word. A
proper name must be the established Chinese form, not a made-up transliteration.

Use the tools to settle what the evidence leaves open:
- `python3 ai-enrich/ask.py exists <lng> <word>`: a page with a fitting gloss confirms the word.
  No page does not refute it (compounds often have none), but then you must confirm it another way.
- `python3 ai-enrich/ask.py used <lng> <word>`: ReVo already using the word for a clearly
  different concept is a warning.
- `python3 ai-enrich/ask.py entry <mrk>`: another entry or sense, compactly.
- **Web search** (WebSearch, WebFetch): for a word the tools cannot confirm, a compound, a
  technical or regional term, or a register question. Good sources: Duden, DWDS, Wiktionary,
  Merriam-Webster, Cambridge, Oxford Learner's, for Chinese MDBG, zdic.net and Baidu Baike, and for
species the scientific name (the Chinese name of a species is best confirmed through it). Set
  `searched: true` when a search decided the verdict.

`mark`: for an accepted word that is not neutral, the label from this list, else `""`:
- de: `[vulg.]` `[pej.]` `[ugs.]` `(veraltet)` `(hist.)` `(poetisch)` `(gehoben)` `(selten)`
  `(österreich.)` `(schweiz.)` `(landsch.)` `(fachspr.)`
- en: `(vulgar)` `(derogatory)` `(colloquial)` `(dated)` `(historical)` `(poetic)` `(formal)`
  `(rare)` `(regional)` `(jargon)` `(British)` `(US)`
- zh: always `""` (no Chinese labels are set up).

A word ReVo marks as figurative (FIG) is filed under its FIG sense; do not mark it.

## Definitions: a verdict on each
Accept a definition that says what the Esperanto says, in natural, plain target-language prose.
Correct small faults yourself and give the corrected `text` with `accept: true`. Reject one that
misreads the sense or adds what the Esperanto does not say. Always give `text`. Bring it in line
with the house style in the proposer's prompt (`ai-enrich/prompt-propose.md`, step 1) as a small
correction: "(capital)"/"(lower case)", British spelling for English, a closing full stop.

## Flags, in passing
As the proposer's instructions say ("Step 3"). Also flag a wrong supplied word (`ours`). Only
what you are sure of. A flag is about what already stands in ReVo; a proposal you reject is not a
flag, its reason goes in the verdict's `why`.

## Saving
Save with the command in your task:
```
python3 ai-enrich/ask.py save check <lng> <article> --run <run> --model <model> [--holdout] <<'JSON'
{"verdicts": [{"mrk": "...", "word": "...", "accept": true, "mark": "", "searched": false, "why": "..."}],
 (Chinese, correcting a reading: {..., "accept": true, "pinyin": "zhǎngguān", "why": "..."})
 "definitions": [{"mrk": "...", "accept": true, "text": "...", "why": "..."}],
 "flags": []}
JSON
```
There must be exactly one verdict per proposal (same `mrk` and `word`) and per proposed
definition. If it answers "Not saved", fix what it lists and save again until it answers "Saved".
Then return the counts it printed.
