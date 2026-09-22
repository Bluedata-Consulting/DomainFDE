#!/usr/bin/env bash
# Runs every component test. Each part must pass before the agents are worth scoring.
set -u
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$KIT"
failed=0
for part in "The grounding parts:tests/test_grounding.py" \
            "The ontology:tests/test_ontology.py"; do
  name="${part%%:*}"; file="${part##*:}"
  echo ""
  echo "=============================================================="
  echo "  $name  ($file)"
  echo "=============================================================="
  python3 "$file" 2>&1 | grep -v "Processing request" || failed=1
done
echo ""
if [ "$failed" -eq 0 ]; then
  echo "ALL PARTS PASS. The agents are worth scoring."
else
  echo "A PART FAILED. Fix the part before scoring the agents."
fi
exit $failed
