# ai-enrich

Fills German and English gaps that Wiktionary could not (see `../wikt-enrich`), from ReVo's own
evidence: the other languages' translations of the same entry and sense, the Esperanto definition
and examples, and the words of the entries a sense refers to. One agent proposes, a second one,
independent and allowed to search the web, tries to refute each proposal. Only what the checker
accepts is written, and everything written says so in `fnt`. The same pass translates the
Esperanto definitions into `<dif lng fnt>`.

## Gaps

For one target language, per article:

- **A**: the entry has no word in the language anywhere (a Vikt word counts as one), other
  languages have some of ReVo's own.
- **B**: a sense (with its subsenses) has none, and neither has the entry as a whole word.
- **C**: a sense has none, but the entry has a whole-word translation. "Covered" is a valid
  answer and writes nothing.

Unmarked senses are keyed `<drv mrk>#<i>`, the drv being 0 and its senses counted from 1 in
document order, as `wikt-enrich/apply.py` counts them. A `<trd>` inside a `<dif>` (Latin taxon
names) counts as evidence.

## Pieces

| | |
|---|---|
| `gaps.py --lng de` | one work file per article with a gap: `out/<lng>/work/<article>.json` (entries, senses, evidence, the raw XML, its sha) |
| `gaps.py --lng de --holdout 100` | 100 entries that have the language, hidden in the XML and evidence, under `out/<lng>/holdout/`, with `truth.json` |
| `headwords.py` | `../wikt-enrich/data/headwords.db` from the de and en Kaikki extracts, for `ask.py exists` |
| `prompt-propose.md`, `prompt-check.md` | what the agents do, versioned here |
| `schemas/` | the result shapes `ask.py save` accepts |
| `ask.py` | the agents' only tool: `used`, `exists`, `entry` (read-only), `save` (the only write) |
| `slice.py` | the next slice of articles not done yet, as the workflow's args |
| `workflow.js` | the Claude workflow: propose, then check, per bundle of about 5 articles |
| `score.py --lng de` | a holdout run against the hidden words |
| `apply.py --lng de [--write]` | what the checker accepted into the XML |
| `flags.py` | things found wrong in passing, outside the repo |

`ask.py` reads a local voko.db (`AI_DB`, default revo-mcp's `data/voko.db`) with `mode=ro`, not
the deployed revo-mcp: the local build has the Vikt words and every local change.

## Agents

`ai-propose` (Bash, Read) and `ai-check` (also WebSearch, WebFetch) are agent types in the user's
agents folder, outside the repo; a session only knows them if they existed when it started.
Without them, pass `"typed": false` and the default workflow agent runs, held to `ask.py` by the
prompt alone. The proposer does not search, so the two do not share search results.

Each agent saves its own result per article through `ask.py save`, which validates it against
the schema and the work file (every mrk must exist; the checker must give exactly one verdict per
proposal and per definition). A result records run tag, model and the work file's sha, so a
result made on an older work file is neither applied nor counted as done.

## Running it

```sh
python3 ai-enrich/gaps.py --lng de --holdout 100
python3 ai-enrich/slice.py --lng de --holdout --run h1        # -> args for the workflow
# Workflow ai-enrich/workflow.js with those args (in a Claude Code session)
python3 ai-enrich/score.py --lng de
python3 ai-enrich/flags.py collect

python3 ai-enrich/gaps.py --lng de
python3 ai-enrich/slice.py --lng de --gap A --bundles 40 --run a1
# Workflow ...; again with the same slice command until it prints no bundles
python3 ai-enrich/apply.py --lng de            # read the dry run
python3 ai-enrich/apply.py --lng de --write    # DTD-validated; adds mll="AI" to cfg/bibliogr.xml
```

Words and definitions are committed apart, so either can be reverted on its own:
`apply.py --only words --write`, commit, `apply.py --write` (adds the definitions), commit.
`../wikt-enrich/revert.py --source AI --only words|definitions` takes out one kind later.

A slice of 40 bundles is 80 agents. Workflows count against the session's plan usage; the
workflow logs output tokens as bundles finish.

## How it is marked

```xml
<trd lng="de" fnt="AI: pl fr ru; proponis claude-opus-5-5; kontrolis claude-opus-5-5">Teilstaat</trd>
<trd lng="de" kod="ARK" fnt="AI: ...; serĉo">Haupt <klr>(veraltet)</klr></trd>
<dif lng="de" fnt="AI: eo; tradukis claude-opus-5-5; kontrolis claude-opus-5-5">Ein Staat innerhalb eines Bundesstaats.</dif>
```

Source languages first (`ref`: from the words of referenced entries, `dif`: from the definition
alone), then who proposed and who checked; `serĉo` when the checker needed the web. A person who
has looked appends `; kontrolita`. `<dif fnt>` is an attribute of this fork's DTD (voko-grundo
`dif-fnt`); revo-mcp and Kunirado show both kinds with an AI mark. `../wikt-enrich/revert.py
--source AI` takes everything out again.

## Flags

The file `REVO_FLAGS` names, one finding per line, outside every
repo. Agents put what they notice in passing (a wrong word, a typo in a definition, a bad ref) in
their result; `flags.py collect` merges it without duplicates; `flags.py add` is for people.
Fixing ReVo's own errors is a separate step.
