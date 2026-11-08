#!/usr/bin/env bash
# Apply the repository's protection settings (needs `gh`, logged in as an admin). Run it once the repository is public:
#   .github/rulesets/apply.sh [owner/repo]
# 1. Creates or updates the rulesets from the JSON files in this folder.
# 2. Requires the maintainer's approval before workflows run for pull requests from any outside contributor (fork PRs
#    run their own copy of pull_request workflows; GitHub's default only asks for first-time contributors).
# Both need a public repository on the free plan (rulesets on private repositories need a paid plan).
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
gh api -X PUT "repos/$REPO/actions/permissions/fork-pr-contributor-approval" \
    -f approval_policy=all_external_contributors >/dev/null
echo "fork pull request workflows: approval required for all outside contributors ($REPO)"
