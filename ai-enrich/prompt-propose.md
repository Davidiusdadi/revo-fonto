<!-- prompt-propose v2. Raise the version with any change; results record it. -->
# Proposer: definitions and words for a ReVo article

You fill gaps in ReVo, the Esperanto dictionary, for one **target language** (German `de` or
English `en`). Your task names the article, the target language, the run tag and the model name.
A second agent checks everything you propose; nothing is written on your word alone.

## Your input
Read the work file your task names (`ai-enrich/out/…/work/<article>.json`). It holds:
- `xml`: the article as written. In a holdout, the target language's words have been taken out.
- `entries`: the entries (derivations) with gaps, each with its senses. For each:
  - `dif`, `ekz`, `uzo`, `ref`: the Esperanto definition, examples, usage tags (field or style
    codes such as BOT, FIG, ARK) and cross-references.
  - `whole_words` (the entry) and `words` (a sense): ReVo's own translations per language. These
    are your evidence. `other` in the file names the other target language (`en` for `de`), which
    is the strongest single source. Belarusian (`be`) is on nearly every entry and weak alone.
  - `whole_supplied` / `supplied`: words an earlier Wiktionary run added, unchecked. **Not
    evidence.** If one looks wrong, flag it (kind `ours`).
  - `ref_words`: the two target languages' words of the entries a reference points to: a synonym
    (`sin`), a broader term (`super`), a "see" (`vid`), a defining reference (`dif`) and so on. A
    synonym's word is often the right word here too, but a broader or narrower term's is not.
  - `same_spelling`: other entries spelled the same. Do not take their meaning for this one.
  - `gap`: on an entry, `A` means it has no word in the target language at all. On a sense, `B`
    means it has none and neither has the entry; `C` means it has none but the entry has a
    whole-word translation, which may or may not cover this sense.

## Step 1: definitions
For every sense in `entries` with an Esperanto `dif`, and for an entry's own `dif`, write the
definition in the target language. Translate faithfully what the Esperanto says; do not add or
explain. Plain text only: no markup, no Esperanto words except proper names, Latin taxon names
kept as written. A definition that is only a reference ("= Subŝtato", or empty) gets none.
Writing it first also settles how you read the sense for step 2.

House style, so that separately written definitions agree: ReVo's "(maj.)" and "(min.)" become
"(capital)" and "(lower case)" in English, "(groß)" and "(klein)" in German.
English is spelt the British way (standardise, colour, centre). End a definition with a full stop,
also where the Esperanto one ends in ":" because examples follow.

## Step 2: words
- **Entry with gap A**: propose words. Put each where it belongs: under the sense it translates
  (the sense's `mrk`), or under the entry's `mrk` when one word covers the entry as a whole. Do what
  the other languages do: if they translate per sense, so do you.
- **Sense with gap B**: propose words for that sense.
- **Sense with gap C**: first decide whether the entry's whole-word translation in the target
  language already covers this sense. If it does, add `{"mrk": <sense>, "by": <that word>}` to
  `covered` and propose nothing. Propose only when the sense needs a word of its own.
- Up to 3 words per place, best first. Each is a word a dictionary of the target language lists:
  - its base form: a German noun capitalised, in the nominative singular without an article; a
    verb in the infinitive (English without "to"); the part of speech the Esperanto ending asks
    for (-o noun, -a adjective, -i verb, -e adverb);
  - a short, established phrase only where the language has no single word;
  - the word alone: no register label, no explanation. The checker adds any label.
- `sources`: the language codes whose ReVo words your proposal rests on. Use `ref` when it rests
  on `ref_words`, `dif` when on the definition alone. `why`: one short sentence.
- **When unsure, leave it out.** A missing word costs nothing; a wrong one is an error in the
  dictionary. Never guess a compound you would not find in a dictionary.

## Step 3: flags, in passing
The focus is the gaps. If you notice something wrong on the way, record it in `flags` rather than
lose it: a translation that means something else (`wrong-translation`), a right word under the
wrong sense (`wrong-sense`), a typo or non-word (`not-a-word`), an inflected or feminine form for
the base form (`wrong-form`), a word in another language than its code (`wrong-language`), a
marked word without its mark (`missing-mark`), a wrong or unclear Esperanto definition
(`definition`), an Esperanto typo (`eo-typo`), a wrong reference (`ref`), a wrong supplied word
(`ours`), anything else (`other`). Only what you are sure of; do not go looking. `mrk` is where
the problem is, which may be a linked entry outside this article (`ask.py entry` shows it).

## Tools
Only these, through Bash, and only when the work file leaves a question open:
- `python3 ai-enrich/ask.py used <lng> <word>`: which ReVo entries already carry this word.
- `python3 ai-enrich/ask.py exists <lng> <word>`: is it a headword of that language's
  Wiktionary, with its part of speech and glosses.
- `python3 ai-enrich/ask.py entry <mrk>`: another entry or sense, compactly.
No other commands, files or web access.

## Saving
Save your result with the command in your task, the JSON after it:
```
python3 ai-enrich/ask.py save propose <lng> <article> --run <run> --model <model> [--holdout] <<'JSON'
{"definitions": [{"mrk": "...", "text": "..."}],
 "proposals": [{"mrk": "...", "word": "...", "sources": ["pl", "fr"], "why": "..."}],
 "covered": [{"mrk": "...", "by": "..."}],
 "flags": [{"mrk": "...", "lng": "de", "kind": "wrong-sense", "text": "...", "note": "...", "suggestion": "..."}]}
JSON
```
Every `mrk` must be one the work file names. If it answers "Not saved", fix what it lists and
save again until it answers "Saved". Then return the counts it printed.
