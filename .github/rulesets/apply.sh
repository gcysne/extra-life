#!/usr/bin/env bash
# Create or update the repository rulesets from the JSON files in this folder (needs `gh`, logged in as an admin).
#   .github/rulesets/apply.sh [owner/repo]
# Rulesets on private repositories need a paid GitHub plan; on public repositories they're free.
set -euo pipefail
REPO="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
cd "$(dirname "$0")"
for f in *.json; do
    name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "$f")"
    id="$(gh api "repos/$REPO/rulesets" -q ".[] | select(.name == \"$name\") | .id" | head -1)"
    if [[ -n "$id" ]]; then
        gh api -X PUT "repos/$REPO/rulesets/$id" --input "$f" >/dev/null && echo "updated ruleset '$name' ($REPO)"
    else
        gh api -X POST "repos/$REPO/rulesets" --input "$f" >/dev/null && echo "created ruleset '$name' ($REPO)"
    fi
done
