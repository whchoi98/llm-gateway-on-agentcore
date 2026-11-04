#!/usr/bin/env bash
# Rebuild docs/architecture.html (ko) and docs/architecture.en.html (en), export every diagram to
# docs/<name>.<lang>.{svg,png}, and verify each SVG with the aws-diagram-design checkers.
#
# Needs python3, node, a playwright-core package and a Chromium binary:
#   PLAYWRIGHT_CORE=/path/to/node_modules/playwright-core \
#   CHROMIUM=/path/to/chrome-headless-shell \
#   bash scripts/diagrams/export.sh
# AWS_DIAGRAM_SKILL overrides the aws-diagram-design skill folder (icons, fonts, checkers).
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

here="$(cd "$(dirname "$0")" && pwd)"
docs="$(cd "$here/../../docs" && pwd)"
skill="$(python3 "$here/build.py" --print-skill)"  # AWS_DIAGRAM_SKILL, else the newest installed version

python3 "$here/build.py"
python3 "$here/export_svg.py" "$docs/architecture.en.html" en
python3 "$here/export_svg.py" "$docs/architecture.html" ko
node "$here/export_png.mjs" "$docs/architecture.en.html" "$docs" en
node "$here/export_png.mjs" "$docs/architecture.html" "$docs" ko

# One SVG per run: verify-geometry merges every SVG it is given into one coordinate space.
status=0
for svg in "$docs"/{architecture,request-flow,fallback-sequence,deploy-order}.{en,ko}.svg; do
  python3 "$skill/scripts/self_check.py" "$svg" || status=1
  python3 "$skill/scripts/verify-geometry.py" "$svg" | tail -1
  python3 "$skill/scripts/verify-geometry.py" "$svg" >/dev/null || status=1
done
if grep -l '·' "$docs"/*.svg; then
  echo "middle dot (U+00B7) in the SVGs above: use '/' for a pair, commas for a list" >&2
  status=1
fi
exit "$status"
