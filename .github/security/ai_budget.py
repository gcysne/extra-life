#!/usr/bin/env python3
"""Decide whether the AI security review may run for this event (it uses the maintainer's Claude plan).

Limits (edit here; only the maintainer can change .github/):
  PER_PR   AI reviews per pull request (automatic first review + reviews requested with the `ai-review` label)
  PER_DAY  AI reviews per repository in the last 24 hours, over all pull requests
The per-PR count lives in the AI review comment (<!-- ai-review-count: N -->); the daily count is the number of
"AI security review" jobs that actually ran (success or failure) in the last 24 hours.

usage: ai_budget.py --repo OWNER/NAME --pr N --out FILE      (needs gh with GH_TOKEN)
Writes "run=true|false" and "reason=..." to FILE (GITHUB_OUTPUT) and "count=N" (reviews so far for this PR).
"""

import argparse
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone

PER_PR = 3
PER_DAY = 10
REVIEW_JOB = "AI security review"
COUNT = re.compile(r"<!-- ai-review-count: (\d+) -->")


def gh(*args):
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=True)
    return json.loads(r.stdout or "null")


def pr_count(repo, pr):
    for page in range(1, 20):
        comments = gh(f"repos/{repo}/issues/{pr}/comments?per_page=100&page={page}")
        for c in comments:
            m = COUNT.search(c.get("body") or "")
            if m and "<!-- ai-security-review -->" in c["body"]:
                return int(m.group(1))
        if len(comments) < 100:
            break
    return 0


def day_count(repo):
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = gh(f"repos/{repo}/actions/workflows/pr-ai-review.yml/runs?created=>={since}&per_page=100")
    n = 0
    for run in (runs or {}).get("workflow_runs", []):
        jobs = gh(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=50")
        n += sum(1 for j in jobs.get("jobs", []) if j["name"] == REVIEW_JOB and j["conclusion"] in ("success", "failure"))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    count = pr_count(a.repo, a.pr)
    run, reason = True, ""
    if count >= PER_PR:
        run, reason = False, (f"this pull request already had {count} AI reviews (limit {PER_PR}). "
                              "The maintainer reviews further changes by hand.")
    else:
        today = day_count(a.repo)
        if today >= PER_DAY:
            run, reason = False, (f"{today} AI reviews ran in this repository in the last 24 hours (limit {PER_DAY}). "
                                  "The maintainer can request one later with the `ai-review` label.")
    with open(a.out, "a") as f:
        f.write(f"run={'true' if run else 'false'}\nreason={reason}\ncount={count}\n")
    print(f"run={run} count={count} {reason}")


if __name__ == "__main__":
    main()
