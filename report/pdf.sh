#!/usr/bin/env bash
# PDFs of the Sectors research pages (the same HTML, with the site's print stylesheet), via headless Chrome.
#
#   bash report/pdf.sh ../pramana-research-landing      # -> research/filing-evidence-sectors/pdf/*.pdf
#
# The pages link their stylesheet as /research/assets/research.css (site-absolute), so they are printed from a
# temporary copy whose stylesheet link points at the file on disk.
set -euo pipefail
SITE="$(cd "$1" && pwd)"
SRC="$SITE/research"
STUDY="filing-evidence-sectors"
OUT="$SRC/$STUDY/pdf"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
CHROME="$(command -v google-chrome || command -v chromium || command -v chromium-browser)"

mkdir -p "$TMP/research"
cp -r "$SRC/assets" "$SRC/$STUDY" "$TMP/research/"
find "$TMP/research" -name "*.html" -exec sed -i "s#href=\"/research/assets/research.css\"#href=\"file://$TMP/research/assets/research.css\"#" {} \;
mkdir -p "$OUT"

print() {  # page.html -> name.pdf
  "$CHROME" --headless=new --disable-gpu --no-pdf-header-footer --virtual-time-budget=8000 \
    --print-to-pdf="$OUT/$2" "file://$TMP/research/$STUDY/$1" 2>/dev/null
  echo "  $2 ($(du -h "$OUT/$2" | cut -f1))"
}
print index.html "$STUDY.pdf"
for d in "$TMP/research/$STUDY"/*/; do
  b="$(basename "$d")"
  [ "$b" = pdf ] && continue
  [ -f "$d/index.html" ] && print "$b/index.html" "$b.pdf"
done
