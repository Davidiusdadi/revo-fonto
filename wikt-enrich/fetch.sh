#!/usr/bin/env bash
# Download the Kaikki (wiktextract) dumps listed in manifest.tsv into $WIKT_DATA.
#   fetch.sh            fetch what is missing, then verify sha256 against the manifest
#   fetch.sh --update   re-download everything and rewrite manifest.tsv (a new evidence base)
# The English edition lives under /dictionary/, every other one under /<code>wiktionary/.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
data="${WIKT_DATA:-$here/data}"
editions="de es en fr pl ru pt zh ja el nl cs it tr ko ku"
url() { [ "$1" = en ] && echo "https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz" \
                      || echo "https://kaikki.org/${1}wiktionary/raw-wiktextract-data.jsonl.gz"; }
mkdir -p "$data"
if [ "${1:-}" = "--update" ]; then
  printf 'edition\turl\tlast_modified\tbytes\tsha256\n' > "$here/manifest.tsv"
  for e in $editions; do
    [ "${2:-}" = "--keep" ] || curl -fsSL -o "$data/$e-extract.jsonl.gz" "$(url $e)"
    lm=$(curl -fsSIL "$(url $e)" | tr -d '\r' | awk -F': ' 'tolower($1)=="last-modified"{v=$2} END{print v}')
    printf '%s\t%s\t%s\t%s\t%s\n' "$e" "$(url $e)" "$lm" "$(stat -c %s "$data/$e-extract.jsonl.gz")" \
      "$(sha256sum "$data/$e-extract.jsonl.gz" | cut -d' ' -f1)" >> "$here/manifest.tsv"
  done
else
  tail -n +2 "$here/manifest.tsv" | while IFS=$'\t' read -r e u lm bytes sha; do
    f="$data/$e-extract.jsonl.gz"
    [ -s "$f" ] || curl -fsSL -o "$f" "$u"
    [ "$(sha256sum "$f" | cut -d' ' -f1)" = "$sha" ] && echo "ok       $e" \
      || echo "CHANGED  $e  (Kaikki republishes weekly; results will differ from the recorded run)"
  done
fi
