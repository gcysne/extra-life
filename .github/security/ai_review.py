#!/usr/bin/env python3
"""AI security review of a pull request: an extra, advisory layer on top of pr_scan.py.

Claude Code reads the diff as text with **no tools at all** (--tools ""), no MCP servers, no settings and no session
files, so whatever the pull request says, it can't read files (or the token in its environment), run commands or
reach the network. Its answer is parsed as JSON, any secret value is scrubbed from it, and it's rendered as a
Markdown comment. It can add findings and fail its own check on "block"; it can never pass a pull request that
pr_scan.py rejected (that check is separate and required).

usage: ai_review.py --diff FILE --out DIR [--claude PATH] [--count N] [--skip REASON]
Auth: CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`, Pro/Max plan) or ANTHROPIC_API_KEY in the environment.
Exit 1 only on an AI "block" verdict; any failure of the AI itself is reported and exits 0.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pr_scan import sanitize  # noqa: E402

MARKER = "<!-- ai-security-review -->"
MAX_DIFF_BYTES = 400_000
START, END = "<<<UNTRUSTED_PULL_REQUEST_DIFF", "UNTRUSTED_PULL_REQUEST_DIFF>>>"


def scrub(text):
    """Remove any secret that might have ended up in the model's answer."""
    for var in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(var)
        if value and len(value) > 8:
            text = text.replace(value, "[redacted]")
    return re.sub(r"sk-ant-[A-Za-z0-9_\-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}", "[redacted]", text)


def run_claude(claude, diff_text, timeout=900):
    prompt = (HERE / "ai-review-prompt.md").read_text()
    # The diff can't close the untrusted block early: neutralise the end marker inside it.
    body = diff_text.replace(END, END.replace(">>>", "> > >"))
    stdin = f"{prompt}\n\n{START}\n{body}\n{END}\n\nReturn only the JSON object."
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "HOME", "LANG", "TMPDIR", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")}
    cmd = [claude, "-p", "--tools", "", "--restricted", "--strict-mcp-config", "--no-session-persistence",
           "--output-format", "json"]
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout, env=env,
                       cwd=os.environ.get("RUNNER_TEMP", "/tmp"))
    if r.returncode != 0:
        raise RuntimeError(scrub((r.stderr or r.stdout).strip()[-400:]) or f"claude exited with {r.returncode}")
    outer = json.loads(r.stdout)
    if outer.get("is_error"):
        raise RuntimeError(scrub(str(outer.get("result", "error"))[:400]))
    text = outer.get("result", "")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("the reviewer didn't return JSON")
    review = json.loads(m.group(0))
    if review.get("verdict") not in ("block", "warn", "pass"):
        raise RuntimeError("the reviewer returned an unknown verdict")
    return review


def render(review=None, error=None, skipped=None, count=0):
    lines = [MARKER, f"<!-- ai-review-count: {count} -->", "## 🤖 AI security review", ""]
    if skipped:
        lines += [f"Skipped: {skipped}"]
    elif error:
        lines += [f"The AI review couldn't run ({sanitize(scrub(error))}). This review is advisory; the "
                  "required **PR security scan** still applies."]
    else:
        icon = {"block": "❌ **Blocking issues found.**", "warn": "⚠️ **Needs a maintainer's look.**",
                "pass": "✅ **Nothing suspicious found.**"}[review["verdict"]]
        lines += [icon + " " + sanitize(scrub(str(review.get("summary", ""))), 600), ""]
        findings = review.get("findings") or []
        if findings:
            lines += ["| Severity | Where | Issue | Why |", "|---|---|---|---|"]
            order = {"block": 0, "warn": 1, "info": 2}
            for f in sorted(findings, key=lambda f: order.get(f.get("severity"), 3))[:40]:
                where = f"`{sanitize(scrub(str(f.get('file', ''))))}`" + (f":{int(f['line'])}" if str(f.get("line", "0")).isdigit() and int(f["line"]) else "")
                lines.append(f"| {sanitize(str(f.get('severity', '?')))} | {where} | "
                             f"{sanitize(scrub(str(f.get('issue', ''))), 300)} | {sanitize(scrub(str(f.get('why', ''))), 400)} |")
    lines += ["", "<sub>Advisory review by Claude, which read the diff as text with no tools. It can add findings "
              "but never overrides the required PR security scan.</sub>"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--diff", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--claude", default="claude")
    ap.add_argument("--count", type=int, default=0, help="AI reviews this pull request already had")
    ap.add_argument("--skip", default="", help="don't call the AI; post this reason (budget, scan rejected...)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    diff = Path(a.diff).read_bytes()
    review, error, skipped = None, None, None
    if a.skip:
        skipped = a.skip
    elif not (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        skipped = "no CLAUDE_CODE_OAUTH_TOKEN secret is set in this repository."
    elif len(diff) > MAX_DIFF_BYTES:
        skipped = f"the diff is {len(diff) // 1024} KB (limit {MAX_DIFF_BYTES // 1024} KB); review it by hand."
    elif not diff.strip():
        skipped = "the pull request changes nothing."
    else:
        try:
            review = run_claude(a.claude, diff.decode("utf-8", "replace"))
        except Exception as e:  # advisory layer: report, never crash the workflow
            error = str(e)
    ran = review is not None or error is not None          # an attempt used the budget
    (out / "ai-report.md").write_text(render(review, error, skipped, a.count + (1 if ran else 0)))
    blocked = bool(review and review["verdict"] == "block")
    (out / "ai-result.json").write_text(json.dumps({"blocked": blocked, "error": error, "skipped": skipped,
                                                    "review": review}, indent=1))
    print(f"verdict={review['verdict'] if review else 'none'} error={bool(error)} skipped={bool(skipped)}")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
