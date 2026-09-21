#!/usr/bin/env bash
# Runs every component test. Each part must pass before the whole agent is worth scoring.
set -u
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$KIT"
failed=0
for part in "The rules and the router:tests/test_rules.py" \
            "The metrics:tests/test_metrics.py" \
            "The ontology:tests/test_ontology.py"; do
  name="${part%%:*}"; file="${part##*:}"
  echo ""
  echo "=============================================================="
  echo "  $name  ($file)"
  echo "=============================================================="
  python3 "$file" || failed=1
done
echo ""
if [ "$failed" -eq 0 ]; then
  echo "ALL PARTS PASS. The agent is worth scoring."
else
  echo "A PART FAILED. Fix the part before scoring the agent."
fi
exit $failed
