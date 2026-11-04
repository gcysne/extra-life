#!/usr/bin/env python3
"""Security scan for pull requests (standard library only).

Reads what a pull request adds (git diff base..head) as data and never runs any of it. Findings:
  BLOCK  the pull request is rejected: binaries, archives, prompt injection, hidden Unicode, obfuscated or encoded
         code, long numeric/encoded arrays, downloads or installs from sources not in allowed-sources.txt, piping
         downloads into a shell, reverse shells, miners, exfiltration endpoints, sudoers/setuid changes,
         destructive commands on / or ~, install hooks in package.json, changes to .github/ or CODEOWNERS.
  WARN   reported in the review for a human to check: rm -rf and other deletions, sudo, system changes, process
         kills, force pushes, credential paths, persistence (cron, shell profiles, services), new dependencies.
  NOTE   informational: new external links.

usage: pr_scan.py --base SHA --head SHA [--repo DIR] [--out DIR] [--author-is-owner]
Writes report.md and result.json to --out; exit code 1 when there is a BLOCK finding.
The rules and allowed-sources.txt are read from this script's own folder: in CI that is the base branch, so a pull
request can't change the rules it is checked against.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARKER = "<!-- pr-security-scan -->"
MAX_FILE_BYTES = 2 * 1024 * 1024
IMAGE_MAGIC = {
    ".png": [b"\x89PNG\r\n\x1a\n"], ".jpg": [b"\xff\xd8\xff"], ".jpeg": [b"\xff\xd8\xff"],
    ".gif": [b"GIF87a", b"GIF89a"], ".webp": [b"RIFF"], ".ico": [b"\x00\x00\x01\x00"],
}
DANGEROUS_MAGIC = [
    (b"\x7fELF", "ELF executable"), (b"MZ", "Windows executable"), (b"\xcf\xfa\xed\xfe", "Mach-O executable"),
    (b"\xca\xfe\xba\xbe", "Mach-O/Java binary"), (b"PK\x03\x04", "zip/jar/wheel archive"), (b"\x1f\x8b", "gzip archive"),
    (b"\xfd7zXZ", "xz archive"), (b"7z\xbc\xaf", "7z archive"), (b"Rar!", "rar archive"), (b"BZh", "bzip2 archive"),
    (b"\x00asm", "WebAssembly binary"), (b"!<arch>", "ar/deb archive"),
]
CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".lua",
            ".pl", ".rb", ".php"}
SKIP_CONTENT = (".github/security/",)        # the scanner's own rules and test samples
LOCKFILES = ("pnpm-lock.yaml", "package-lock.json", "yarn.lock")


def rx(p):
    return re.compile(p, re.I)


# --- line rules: (level, category, regex, message) ------------------------------------------------------------
LINE_RULES = [
    # prompt injection aimed at AI agents (skills, agent instructions and docs are read by agents)
    ("BLOCK", "prompt injection", rx(r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|any|your|system)\b.{0,20}\b(instructions?|prompts?|rules|guidelines|directives)"), "tells an AI agent to ignore its instructions"),
    ("BLOCK", "prompt injection", rx(r"\byou are now\b|\bnew (system )?instructions\s*:|\bdeveloper mode\b|\bjailbreak|\bDAN mode\b"), "role or instruction override aimed at an AI agent"),
    ("BLOCK", "prompt injection", rx(r"<\|im_start\|>|<\|im_end\|>|<\|(system|user|assistant)\|>|\[/?INST\]|<<SYS>>|\bBEGIN SYSTEM PROMPT\b|</?(system_prompt|system-reminder)>"), "chat-template or system-prompt markers"),
    ("BLOCK", "prompt injection", rx(r"\b(do not|don't|never)\s+(tell|inform|show|mention|reveal|report)\b.{0,30}\b(the )?(user|owner|human)\b"), "asks an agent to hide something from the user"),
    ("BLOCK", "prompt injection", rx(r"\b(silently|secretly|covertly|quietly|stealthily)\s+(run|execute|install|download|upload|send|post|delete|remove|disable|exfiltrate)"), "asks for a hidden action"),
    ("BLOCK", "prompt injection", rx(r"\b(send|upload|post|exfiltrat\w*|leak|forward)\b.{0,40}\b(token|api[_ -]?key|password|credential|secret|ssh key|cookie)s?\b.{0,40}\b(to|into)\b.{0,30}(https?://|server|endpoint|webhook|url|e-?mail|address|discord|telegram)"), "asks to send credentials somewhere"),
    # remote code: piping downloads into an interpreter
    ("BLOCK", "remote script", rx(r"\b(curl|wget|fetch)\b[^\n|]*\|\s*(sudo\s+)?(-?\w+=\S+\s+)*(ba|z|da|k|c|fi)?sh\b|\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(python3?|perl|ruby|node)\b|(ba)?sh\s+<\(\s*(curl|wget)|\b(ba)?sh\s+-c\s+[\"']?\$\((curl|wget)|\beval\s+[\"']?\$\((curl|wget)|\b(iex|Invoke-Expression)\b.{0,40}(iwr|Invoke-WebRequest|DownloadString)"), "pipes a download straight into an interpreter"),
    ("BLOCK", "obfuscated code", rx(r"base64\s+(-d|--decode)\b[^\n]*\|\s*(ba|z)?sh\b|base64\s+(-d|--decode)\b[^\n]*\|\s*(python3?|perl|node)\b|\becho\s+[A-Za-z0-9+/=]{40,}\s*\|\s*base64"), "decodes data and runs it"),
    # dangerous shells and payloads
    ("BLOCK", "dangerous shell", rx(r"/dev/(tcp|udp)/|\bn(c|cat)\b[^\n]*\s-(e|c)\s|\bsocat\b[^\n]*\b(exec|system):|\bmkfifo\b[^\n]*\b(nc|ncat|telnet)\b|\bbash\s+-i\s*[<>]&|\bpty\.spawn\(|\bos\.dup2\(|\btelnet\b[^\n]*\|\s*/bin/(ba)?sh"), "reverse or bind shell"),
    ("BLOCK", "dangerous shell", rx(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:|--no-preserve-root|\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(\"|')?(/|/\*|~|~/|\$HOME|\$\{HOME\}|/home|/usr|/etc|/boot|/var)(\"|')?\s*($|[;&|])|\bmkfs(\.\w+)?\s|\bdd\b[^\n]*\bof=/dev/(sd|nvme|mmcblk|hd|vd)|>\s*/dev/(sd|nvme|mmcblk)[a-z0-9]*\b|\bwipefs\s+-a"), "destroys the system or a disk"),
    ("BLOCK", "privilege escalation", rx(r"/etc/sudoers|\bNOPASSWD\b|\bvisudo\b|\bchmod\s+([ugoa]*\+s|[0-7]?[4-7][0-7]{3})\s|\bsetcap\b|\bpasswd\s+-d\b"), "sudoers, setuid or capability change"),
    ("BLOCK", "malware", rx(r"\bxmrig\b|stratum\+(tcp|ssl)://|\bminerd\b|\bcryptonight\b|\bcoinhive\b|\bnicehash\b"), "crypto miner"),
    ("BLOCK", "exfiltration", rx(r"(discord(app)?\.com/api/webhooks|api\.telegram\.org/bot|pastebin\.com|hastebin|paste\.ee|transfer\.sh|ngrok(-free)?\.(io|app)|webhook\.site|requestbin|pipedream\.net|interact\.sh|oast\.(fun|me|pro|live|site)|burpcollaborator|canarytokens|ipinfo\.io|ifconfig\.me)"), "known data-exfiltration or callback endpoint"),
    # obfuscated / dynamic code
    ("BLOCK", "obfuscated code", rx(r"\b(exec|eval)\s*\(\s*(compile|base64|b64decode|codecs|zlib|bytes\.fromhex|bytearray|marshal|__import__|\"|'|[a-z_]+\.decode)"), "runs decoded or string code"),
    ("BLOCK", "obfuscated code", rx(r"\b__import__\s*\(|\bmarshal\.loads\b|\bcodecs\.decode\([^)]*rot|\bnew\s+Function\s*\(|\bFunction\s*\(\s*[\"'`]|\bsetTimeout\s*\(\s*[\"'`]|\bsetInterval\s*\(\s*[\"'`]"), "dynamic code construction"),
    ("BLOCK", "obfuscated code", rx(r"String\.fromCharCode\s*\((\s*\d+\s*,){8,}|(\\x[0-9a-f]{2}){16,}|(\\u[0-9a-f]{4}){12,}|(\\[0-7]{3}){16,}|(%[0-9a-f]{2}){24,}"), "long escaped or char-code sequence"),
    ("BLOCK", "encoded data", rx(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{200,}={0,2}(?![A-Za-z0-9+/])"), "long base64-like blob"),
    ("BLOCK", "encoded data", rx(r"(?<![0-9a-f])[0-9a-f]{160,}(?![0-9a-f])"), "long hex blob"),
    ("BLOCK", "install hook", rx(r"\bpip3?\s+install\b[^\n]*(--(extra-)?index-url|git\+|https?://|\.whl\b|\.tar\.gz\b)|\b(npm|pnpm|yarn)\s+(i|install|add)\b[^\n]*(git\+|github:|https?://|\.tgz\b)|\bnpm\s+config\s+set\s+registry|\bflatpak\s+remote-add\b(?![^\n]*flathub)"), "installs from a source that isn't the official package index"),
    # warnings: potentially harmful, needs a human look
    ("WARN", "deletion", rx(r"\brm\s+(-[a-z]*\s+)*-[a-z]*[rf]|\brm\s+-[a-z]*[rf]|\bshred\b|\bfind\b[^\n]*\s-delete\b|\btruncate\s+-s\s*0|\bshutil\.rmtree\b|\bos\.(remove|unlink|rmdir)\s*\(|\.unlink\s*\(|\bfs\.(rm|rmSync|unlink|unlinkSync|rmdir)\b|\brmtree\b"), "deletes files"),
    ("WARN", "root", rx(r"\bsudo\b|\bpkexec\b|\bdoas\b|\bsu\s+-?\s*(root)?\s*-c\b|\bsteamos-readonly\b|\brpm-ostree\b|\bpacman\s+-[A-Za-z]*[SUR]"), "runs as root or changes the system"),
    ("WARN", "system change", rx(r"\bsystemctl\b(?![^\n]*--user)[^\n]*\b(enable|disable|mask|start|stop|restart)\b|\bmodprobe\b|\bsysctl\s+-w|\bchmod\s+-R\b|\bchown\s+-R\b|\bchmod\s+777\b|\b(iptables|nft|ufw)\b|\bdd\s+if="), "changes system settings or permissions"),
    ("WARN", "processes", rx(r"\bkill\s+-(9|KILL)\b|\bpkill\b|\bkillall\b"), "kills processes"),
    ("WARN", "git", rx(r"\bgit\s+push\b[^\n]*(--force|-f\b)|\bgit\s+reset\s+--hard\b|\bgit\s+clean\s+-[a-z]*f"), "destructive git command"),
    ("WARN", "credentials", rx(r"\.ssh/|id_(rsa|ed25519|ecdsa)\b|/etc/shadow|\.aws/credentials|\.git-credentials|gh/hosts\.yml|loginusers\.vdf|\bssfn\w*|\.netrc\b|\bkeyring\b|\bkwallet\b|cookies\.sqlite|Login Data"), "touches credentials or keys"),
    ("WARN", "persistence", rx(r"\bcrontab\b|/etc/cron|\.bashrc\b|\.bash_profile\b|\.zshrc\b|\.profile\b|\bLD_PRELOAD\b|/etc/profile|autostart/|\.config/systemd/user/[^\s]*\.(service|timer|path)"), "runs code at login, boot or on a schedule"),
    ("WARN", "network", rx(r"\bnc\s+-l|\bpython3?\s+-m\s+http\.server\b|\bsocket\.socket\(|\bsshd\b|\bufw\s+allow"), "opens a network service"),
    ("WARN", "dynamic code", rx(r"\beval\b|\bexec\s*\(|\bsubprocess\b[^\n]*shell\s*=\s*True|\bos\.system\s*\(|\bchild_process\b|\batob\s*\("), "runs dynamic code or a shell"),
]

DOWNLOAD_CONTEXT = rx(r"\b(curl|wget|aria2c|urlopen|urlretrieve|requests\.(get|post)|httpx\.|fetch\s*\(|Invoke-WebRequest|iwr|git\s+clone|git\s+submodule\s+add|pip3?\s+install|(npm|pnpm|yarn)\s+(i|install|add)|flatpak\s+(install|remote-add)|gh\s+release\s+download|download)\b")
URL = re.compile(r"\bhttps?://[^\s\"'<>()`\]\[{}]+", re.I)
HIDDEN_UNICODE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿­᠎\U000e0000-\U000e007f]")


class Scan:
    def __init__(self, repo, base, head, author_is_owner=False):
        self.repo, self.base, self.head, self.owner = Path(repo), base, head, author_is_owner
        self.findings = []
        self.allowed = [l.strip().lower() for l in (HERE / "allowed-sources.txt").read_text().splitlines()
                        if l.strip() and not l.lstrip().startswith("#")]

    # -- git helpers (read-only) --
    def git(self, *args, binary=False):
        r = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, check=True)
        return r.stdout if binary else r.stdout.decode("utf-8", "replace")

    def add(self, level, category, path, line, message, snippet=""):
        self.findings.append({"level": level, "category": category, "path": path, "line": line,
                              "message": message, "snippet": snippet[:200]})

    def allowed_url(self, url):
        u = re.sub(r"^https?://", "", url.lower()).rstrip(".,;:")
        return any(u.startswith(a) for a in self.allowed)

    # -- main --
    def run(self):
        raw = self.git("diff", "--raw", "-z", "--no-renames", "--no-ext-diff", self.base, self.head)
        parts = raw.split("\0")
        changed = []
        i = 0
        while i < len(parts) - 1:
            meta = parts[i]
            if not meta.startswith(":"):
                i += 1
                continue
            _, new_mode, _, new_sha, status = meta[1:].split(" ")[:5]
            changed.append((status[0], parts[i + 1], new_mode, new_sha))
            i += 2
        added_lines = self.added_lines()
        for status, path, mode, sha in changed:
            self.check_path(status, path)
            if status == "D":
                continue
            self.check_blob(path, mode, sha)
        for path, lines in added_lines.items():
            if path.startswith(SKIP_CONTENT):
                continue
            self.check_lines(path, lines)
        if any(p == "package.json" or p.endswith("/package.json") for _, p, _, _ in changed):
            for _, p, _, _ in changed:
                if p.endswith("package.json"):
                    self.check_package_json(p)
        return self.findings

    def added_lines(self):
        out = {}
        path = None
        lineno = 0
        diff = self.git("diff", "-U0", "--no-color", "--no-renames", "--no-ext-diff", self.base, self.head)
        for raw in diff.splitlines():
            if raw.startswith("+++ "):
                path = raw[6:] if raw.startswith("+++ b/") else None
                continue
            if raw.startswith("@@"):
                m = re.search(r"\+(\d+)", raw)
                lineno = int(m.group(1)) if m else 0
                continue
            if path and raw.startswith("+"):
                out.setdefault(path, []).append((lineno, raw[1:]))
                lineno += 1
        return out

    def check_path(self, status, path):
        if path.startswith(".github/") or path.split("/")[-1] == "CODEOWNERS":
            level = "WARN" if self.owner else "BLOCK"
            self.add(level, "protected path", path, 0,
                     "changes CI, security rules or code owners: only the maintainer may change these")

    def check_blob(self, path, mode, sha):
        if mode == "120000":
            target = self.git("cat-file", "blob", sha)
            if target.startswith("/") or ".." in target.split("/"):
                self.add("BLOCK", "symlink", path, 0, f"symlink pointing outside the repository ({target[:80]})")
            else:
                self.add("WARN", "symlink", path, 0, f"new symlink to {target[:80]}")
            return
        if mode == "160000":
            self.add("BLOCK", "submodule", path, 0, "adds a git submodule (code from another repository)")
            return
        size = int(self.git("cat-file", "-s", sha).strip())
        if size > MAX_FILE_BYTES:
            self.add("BLOCK", "large file", path, 0, f"file is {size // 1024} KB (limit {MAX_FILE_BYTES // 1024} KB)")
        data = self.git("cat-file", "blob", sha, binary=True)
        head = data[:16]
        ext = Path(path).suffix.lower()
        for magic, what in DANGEROUS_MAGIC:
            if head.startswith(magic) and not (what == "Windows executable" and ext in (".md", ".txt")):
                if not (magic == b"\x00\x00\x01\x00" and ext == ".ico"):
                    self.add("BLOCK", "binary", path, 0, f"{what}")
                    return
        is_binary = b"\0" in data[:8192]
        if not is_binary:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                is_binary = True
        if is_binary:
            magics = IMAGE_MAGIC.get(ext)
            if not magics:
                self.add("BLOCK", "binary", path, 0, "binary file (only PNG, JPEG, GIF, WebP and ICO images are accepted)")
            elif not any(head.startswith(m) for m in magics):
                self.add("BLOCK", "binary", path, 0, f"file content doesn't match its {ext} extension")
            return
        if mode == "100755" and not data.startswith(b"#!"):
            self.add("BLOCK", "binary", path, 0, "executable file without a #! interpreter line")

    def check_lines(self, path, lines):
        ext = Path(path).suffix.lower()
        is_code = ext in CODE_EXT or (lines and lines[0][1].startswith("#!"))
        lock = path.split("/")[-1] in LOCKFILES
        numeric_run = 0
        for n, text in lines:
            if HIDDEN_UNICODE.search(text):
                self.add("BLOCK", "hidden unicode", path, n,
                         "invisible or bidirectional Unicode characters (can hide text from reviewers)",
                         HIDDEN_UNICODE.sub("␣", text))
            if is_code and len(text) > 1000:
                self.add("BLOCK", "obfuscated code", path, n, f"{len(text)}-character line (minified or packed code)", text)
            # mysterious arrays: many numbers on one line, or many such lines in a row
            nums = len(re.findall(r"(?<![\w.])(0x[0-9a-f]+|\d+)(?![\w.])\s*,", text, re.I))
            if nums >= 40:
                self.add("BLOCK", "numeric array", path, n, f"array of {nums}+ numbers (possible hidden payload)", text)
            numeric_run = numeric_run + 1 if nums >= 8 else 0
            if numeric_run == 10:
                self.add("BLOCK", "numeric array", path, n, "10+ lines of numeric data (possible hidden payload)", text)
            if path.endswith(".md") and "<!--" in text:
                self.add("WARN", "hidden text", path, n, "HTML comment in Markdown (invisible on GitHub, read by agents)", text)
            for level, cat, pat, msg in LINE_RULES:
                if lock and cat in ("encoded data",):
                    continue
                if pat.search(text):
                    if cat == "remote script" and URL.findall(text) and all(self.allowed_url(u) for u in URL.findall(text)):
                        # e.g. the project's own documented one-line installer: a human should still look at it
                        self.add("WARN", cat, path, n, msg + " (from an allowed source)", text)
                    else:
                        self.add(level, cat, path, n, msg, text)
            urls = URL.findall(text)
            if urls:
                bad = [u for u in urls if not self.allowed_url(u)]
                if DOWNLOAD_CONTEXT.search(text) and bad:
                    self.add("WARN" if self.plain_doc(path) else "BLOCK", "unofficial source", path, n,
                             "downloads or installs from a source not in .github/security/allowed-sources.txt: "
                             + ", ".join(bad[:3]), text)
                elif lock and bad:
                    self.add("BLOCK", "unofficial source", path, n, "lockfile resolves a package outside the registry", text)
                elif bad:
                    self.add("NOTE", "link", path, n, "new external link: " + ", ".join(bad[:3]), text)

    @staticmethod
    def plain_doc(path):
        """Docs for humans only. Code, skills, agent instructions and knowledge/ are acted on by agents."""
        return path.endswith(".md") and ("/" not in path or path.startswith("docs/")) and \
            path.split("/")[-1] not in ("AGENT.md", "CLAUDE.md", "SKILL.md")

    def check_package_json(self, path):
        def load(rev):
            try:
                return json.loads(self.git("show", f"{rev}:{path}"))
            except (subprocess.CalledProcessError, ValueError):
                return {}
        old, new = load(self.base), load(self.head)
        for hook in ("preinstall", "install", "postinstall", "prepare", "prepublish", "prepack", "postpack"):
            if hook in (new.get("scripts") or {}) and (old.get("scripts") or {}).get(hook) != new["scripts"][hook]:
                self.add("BLOCK", "install hook", path, 0, f"package.json script '{hook}' runs code on install")
        for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
            for name, spec in (new.get(key) or {}).items():
                if (old.get(key) or {}).get(name) == spec:
                    continue
                if re.search(r"^(git|https?|file|link|github):|/|\.tgz$", str(spec)):
                    self.add("BLOCK", "unofficial source", path, 0, f"{key}.{name} = {spec} (not from the npm registry)")
                elif name not in (old.get(key) or {}):
                    self.add("WARN", "dependency", path, 0, f"new {key} entry: {name} {spec}")


def sanitize(text, limit=160):
    """Untrusted text, made safe for a Markdown table cell and for the Actions log (no workflow commands)."""
    text = HIDDEN_UNICODE.sub("␣", text).replace("\r", " ").replace("\n", " ")
    text = text.replace("::", ": :").replace("|", "\\|").replace("`", "'").replace("@", "&#64;").replace("<", "&lt;")
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def report(findings, owner, override):
    blocks = [f for f in findings if f["level"] == "BLOCK"]
    warns = [f for f in findings if f["level"] == "WARN"]
    notes = [f for f in findings if f["level"] == "NOTE"]
    lines = [MARKER, "## 🛡️ PR security scan", ""]
    if blocks and not override:
        lines += [f"**❌ Rejected: {len(blocks)} blocking finding(s).** This repository only accepts changes without "
                  "binaries, hidden or obfuscated code, prompt injection, or downloads from unofficial sources. If this "
                  "is a false positive, explain it in a comment: the maintainer can review it and add the "
                  "`security-reviewed` label.", ""]
    elif blocks:
        lines += [f"**⚠️ {len(blocks)} blocking finding(s), overridden by the maintainer (`security-reviewed`).**", ""]
    else:
        lines += ["**✅ No blocking findings.**", ""]
    for title, group in (("Blocking", blocks), ("Warnings: please review", warns), ("Notes", notes)):
        if not group:
            continue
        lines += [f"### {title} ({len(group)})", "", "| Category | Where | What | Line |", "|---|---|---|---|"]
        for f in group[:60]:
            where = f"`{sanitize(f['path'])}`" + (f":{f['line']}" if f["line"] else "")
            lines.append(f"| {f['category']} | {where} | {sanitize(f['message'])} | "
                         f"{('`' + sanitize(f['snippet']) + '`') if f['snippet'] else ''} |")
        if len(group) > 60:
            lines.append(f"| … | {len(group) - 60} more | | |")
        lines.append("")
    lines.append("<sub>Automatic scan of the lines this pull request adds (`.github/security/pr_scan.py`). It never "
                 "runs the pull request's code.</sub>")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default=".")
    ap.add_argument("--author-is-owner", action="store_true")
    ap.add_argument("--override", action="store_true", help="maintainer reviewed it (security-reviewed label)")
    a = ap.parse_args()
    findings = Scan(a.repo, a.base, a.head, a.author_is_owner).run()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    blocked = any(f["level"] == "BLOCK" for f in findings) and not a.override
    (out / "report.md").write_text(report(findings, a.author_is_owner, a.override))
    (out / "result.json").write_text(json.dumps({"blocked": blocked, "findings": findings}, indent=1))
    counts = {lvl: sum(f["level"] == lvl for f in findings) for lvl in ("BLOCK", "WARN", "NOTE")}
    print(f"blocking={counts['BLOCK']} warnings={counts['WARN']} notes={counts['NOTE']} rejected={blocked}")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
