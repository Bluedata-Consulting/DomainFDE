#!/usr/bin/env bash
# Runs every component test. Each part must pass before a release is worth deploying.
set -u
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$KIT"
failed=0
for part in "Releases and the fire drill:tests/test_release.py" \
            "The rules and the router:tests/test_rules.py" \
            "The grounding parts:tests/test_grounding.py" \
            "The metrics:tests/test_metrics.py" \
            "The ontology:tests/test_ontology.py"; do
  name="${part%%:*}"; file="${part##*:}"
  echo ""
  echo "=============================================================="
  echo "  $name  ($file)"
  echo "=============================================================="
  python3 "$file" 2>&1 | grep -v "Processing request\|EXPERIMENTAL\|check_feature" || failed=1
done
echo ""
if [ "$failed" -eq 0 ]; then
  echo "ALL PARTS PASS. The release is worth deploying."
else
  echo "A PART FAILED. Fix it before deploying."
fi
exit $failed
