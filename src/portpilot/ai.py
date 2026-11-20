"""Assistive AI fixes for build errors no rule covers. Local-first, verified, never trusted.

- Provider: any OpenAI-compatible chat endpoint. Default: Ollama on this machine
  (http://localhost:11434/v1, model qwen2.5-coder:7b). No key, nothing leaves the machine.
- The model sees one error, the code around it and QNX facts from the SDP index, and must
  answer with exact SEARCH/REPLACE edits. Edits are limited to the files involved and to a few
  lines.
- The caller rebuilds after applying an edit and keeps it only if that error is gone and no new
  error appeared (see port.py). Rejected edits are reverted and logged.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .diagnostics import Diagnostic

DEFAULT_URL = os.environ.get("PORTPILOT_AI_URL", "http://localhost:11434/v1")
DEFAULT_MODEL = os.environ.get("PORTPILOT_AI_MODEL", "qwen2.5-coder:7b")
MAX_CHANGED_LINES = 20

SYSTEM = """You fix C/C++ build errors when porting Linux code to QNX 8.0 (qcc, gcc 12).
Rules:
- Make the smallest change that fixes THIS error. Do not refactor or reformat.
- Prefer portable POSIX code. If the change only makes sense on QNX, guard it with
  #if defined(__QNX__) ... #endif.
- Never delete functionality or change what the code computes to make an error go away.
- Use only the QNX facts you are given; do not invent QNX APIs.
- Usual QNX porting strategies (QNX porting guide):
  * A Linux syscall wrapper or GNU function is missing: call the POSIX/QNX function the facts
    name, including its header.
  * An optional flag that is only an optimization hint is missing: keep the code and define
    the flag to 0 under #ifndef, so behavior stays correct.
  * A struct member is missing: get the same information another POSIX way (for example
    lstat() and S_ISDIR() for a file type), keeping the result identical.
- Answer ONLY with one or more edit blocks in exactly this format, nothing else:

FILE: <path exactly as given>
<<<<<<< SEARCH
<exact lines copied from the file, including indentation>
=======
<replacement lines>
>>>>>>> REPLACE

If you cannot fix it safely, answer exactly: NO_FIX <one-line reason>"""


@dataclass
class Edit:
    path: str
    search: str
    replace: str


@dataclass
class Proposal:
    edits: list[Edit] = field(default_factory=list)
    no_fix: str = ""  # the model's reason when it declines
    raw: str = ""
    error: str = ""  # transport / format error


class Provider:
    def __init__(self, url: str = DEFAULT_URL, model: str = DEFAULT_MODEL,
                 api_key: str | None = None, timeout: float = 180) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.api_key = api_key or os.environ.get("PORTPILOT_AI_KEY", "")
        self.timeout = timeout

    def _request(self, path: str, body: bytes | None, timeout: float) -> bytes:
        url = f"{self.url}{path}"
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (local URL)
                return bytes(r.read())
        except urllib.error.URLError:
            win = _windows_curl()
            if not win or "localhost" not in url and "127.0.0.1" not in url:
                raise
            # WSL with NAT networking cannot reach a model server on Windows' localhost;
            # Windows' own curl.exe (run through WSL interop) can. Nothing leaves the machine.
            cmd = [win, "-s", "-f", "-m", str(int(timeout)), "-H",
                   "Content-Type: application/json"]
            if self.api_key:
                cmd += ["-H", f"Authorization: Bearer {self.api_key}"]
            if body is not None:
                cmd += ["--data-binary", "@-"]
            r2 = subprocess.run([*cmd, url], input=body or b"", capture_output=True,
                                timeout=timeout + 10)
            if r2.returncode != 0:
                raise urllib.error.URLError(f"curl.exe rc={r2.returncode}") from None
            return r2.stdout

    def chat(self, system: str, user: str) -> str:
        body = json.dumps({"model": self.model, "temperature": 0, "seed": 7,
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": user}]}).encode()
        data = json.loads(self._request("/chat/completions", body, self.timeout))
        return str(data["choices"][0]["message"]["content"])

    def available(self) -> str:
        """"" if the endpoint answers and has the model, else the reason."""
        try:
            ids = {m.get("id") for m in
                   json.loads(self._request("/models", None, 10)).get("data", [])}
        except (urllib.error.URLError, OSError, ValueError, subprocess.SubprocessError) as e:
            return f"no AI endpoint at {self.url} ({e})"
        if self.model not in ids:
            return f"model {self.model} not available at {self.url} (have: {sorted(ids)})"
        return ""


def _windows_curl() -> str:
    """Windows' curl.exe when running inside WSL, else ""."""
    if not os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop"):
        return ""
    return shutil.which("curl.exe") or (
        "/mnt/c/Windows/System32/curl.exe"
        if os.path.exists("/mnt/c/Windows/System32/curl.exe") else "")


_BLOCK = re.compile(r"FILE:\s*(?P<path>\S+)\s*\n<<<<<<< SEARCH\n(?P<search>.*?)\n=======\n"
                    r"(?P<replace>.*?)\n?>>>>>>> REPLACE", re.S)


_NUMBERED = re.compile(r"^\s*\d+: ?", re.M)


def _unnumber(block: str) -> str:
    """Drop 'NN: ' prefixes when the model copied the line numbers of the excerpt."""
    lines = block.splitlines()
    if lines and all(_NUMBERED.match(ln) for ln in lines if ln.strip()):
        return "\n".join(_NUMBERED.sub("", ln, count=1) for ln in lines)
    return block


def parse_reply(text: str) -> Proposal:
    t = re.sub(r"```\w*\n?", "", text)
    if (m := re.search(r"NO_FIX\b(.*)", t)) and not _BLOCK.search(t):
        return Proposal(no_fix=m.group(1).strip() or "declined", raw=text)
    edits = [Edit(m.group("path"), _unnumber(m.group("search")), _unnumber(m.group("replace")))
             for m in _BLOCK.finditer(t)]
    if not edits:
        return Proposal(raw=text, error="no edit blocks in the reply")
    return Proposal(edits=edits, raw=text)


def _changed_lines(e: Edit) -> int:
    a, b = e.search.splitlines(), e.replace.splitlines()
    return sum(1 for x in a if x not in b) + sum(1 for y in b if y not in a)


def check_edits(p: Proposal, root: Path, allowed: set[str]) -> str:
    """"" if every edit can be applied exactly once to an allowed file, else the reason."""
    for e in p.edits:
        if e.path not in allowed:
            return f"edit to {e.path} is outside the files involved ({sorted(allowed)})"
        f = root / e.path
        if not f.is_file():
            return f"{e.path} does not exist"
        n = f.read_text(encoding="utf-8", errors="surrogateescape").count(e.search)
        if n != 1:
            return f"SEARCH text found {n} times in {e.path} (must be exactly once)"
        if _changed_lines(e) > MAX_CHANGED_LINES:
            return f"edit changes more than {MAX_CHANGED_LINES} lines"
        if not e.search.strip():
            return "empty SEARCH"
    return ""


def apply_edits(p: Proposal, root: Path) -> dict[str, str]:
    """Apply; return the original text of every touched file (for reverting)."""
    orig: dict[str, str] = {}
    for e in p.edits:
        f = root / e.path
        text = f.read_text(encoding="utf-8", errors="surrogateescape")
        orig.setdefault(e.path, text)
        with open(f, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.write(text.replace(e.search, e.replace, 1))
    return orig


def revert(root: Path, orig: dict[str, str]) -> None:
    for rel, text in orig.items():
        with open(root / rel, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.write(text)


# ---- prompt ----------------------------------------------------------------------------------
def excerpt(path: Path, line: int, radius: int = 15) -> tuple[str, str]:
    """(code around the line, the line itself), without line numbers."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lo, hi = max(1, line - radius), min(len(lines), line + radius)
    return "\n".join(lines[lo - 1:hi]), lines[line - 1] if 0 < line <= len(lines) else ""


def include_block(path: Path, max_lines: int = 40) -> str:
    """The file's first #include line through its last one before any code (at most
    max_lines lines), or ""."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    first = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("#include")), None)
    if first is None:
        return ""
    last = first
    for i in range(first, min(len(lines), first + max_lines)):
        s = lines[i].strip()
        if s.startswith("#include"):
            last = i
        elif s and not s.startswith(("#", "//", "/*", "*")):
            break
    return "\n".join(lines[first:last + 1])


def build_prompt(d: Diagnostic, rel: str, root: Path, facts: list[str],
                 related: list[Diagnostic] | None = None) -> str:
    parts = [f"Build error (qcc for QNX 8.0 x86_64):\n{rel}:{d.line}:{d.col}: {d.message}"]
    if d.included_from:
        parts.append("Included from: " + ", ".join(d.included_from))
    for r in (related or [])[:4]:
        parts.append(f"Also in this file: {r.location()}: {r.message}")
    code, err_line = excerpt(root / rel, d.line)
    if (top := include_block(root / rel)) and top not in code:
        # a fix that must come before the first #include (a feature macro) needs to see it
        parts.append(f"The #include lines at the top of {rel} (copy SEARCH lines from here "
                     f"exactly):\n{top}")
    parts.append(f"The error is on this line of {rel}:\n{err_line}")
    parts.append(f"Code around it in {rel} (copy SEARCH lines from here exactly):\n{code}")
    if facts:
        parts.append("QNX facts (from the QNX SDP 8.0 on this machine):\n"
                     + "\n".join(f"- {f}" for f in facts))
    parts.append(f"Edit only {rel}.")
    return "\n\n".join(parts)
