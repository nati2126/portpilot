"""QNX facts for one build error, read from the user's SDP (headers + symbol index).

These go into the AI prompt so the model works from what QNX 8.0 really provides instead of
from memory, e.g. "MSG_MORE is not defined in any QNX header" or "cpu_set_t is not declared;
QNX uses ThreadCtl(_NTO_TCTL_RUNMASK, ...)" (the latter from the knowledge base).
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from .cpp_text import guard_frames
from .diagnostics import Diagnostic
from .kb import KnowledgeBase
from .sdp_index import SdpIndex

MAX_HITS = 3
_INCLUDE_GUARD = re.compile(r"!?\s*defined\s*\(?\w+_H(?:_\w*)?\)?")


@lru_cache(maxsize=2)
def _headers(include_dir: str) -> tuple[tuple[str, str], ...]:
    out = []
    for dp, _, files in os.walk(include_dir):
        for f in files:
            if f.endswith((".h", ".hpp")) or "." not in f:
                p = Path(dp, f)
                try:
                    out.append((p.relative_to(include_dir).as_posix(),
                                p.read_text(errors="replace")))
                except OSError:
                    continue
    return tuple(sorted(out))


def _decl_patterns(sym: str) -> re.Pattern[str]:
    s = re.escape(sym)
    return re.compile(rf"#\s*define\s+{s}\b|\btypedef\b[^;{{]*\b{s}\s*;|"
                      rf"\b(?:struct|union|enum)\s+{s}\s*\{{|\b{s}\s*\([^;{{]*\)\s*;|"
                      rf"^\s*{s}\s*(?:=[^;]*)?,?\s*(?:/[*/].*)?$", re.M)  # enum constant


_REDIRECT = re.compile(r'#\s*error\s+"?do not include \S+ directly,?\s+include\s+'
                       r'<?(?P<h>[\w/+-]+\.h(?:pp)?)\b')


def _negate(c: str) -> str:
    c = c.strip()
    if re.fullmatch(r"!\s*defined\s*\(?\s*\w+\s*\)?", c):
        return c.lstrip("!").strip()
    if re.fullmatch(r"defined\s*\(?\s*\w+\s*\)?|\w+", c):
        return f"!{c}"
    return f"!({c})"


def _conds_at(text: str, ln: int) -> list[str]:
    frames = guard_frames(text)
    return [_negate(f.cond) if f.negated else f.cond
            for f in (frames[ln] if ln < len(frames) else ())
            if not _INCLUDE_GUARD.fullmatch(f.cond.strip())]


def _public(rel: str, text: str, include_dir: str) -> tuple[str, list[str]]:
    """A header that says '#error do not include X directly, include Y' is reached via Y:
    (Y, the conditions under which Y includes it). Else (rel, [])."""
    m = _REDIRECT.search(text)
    if not m:
        return rel, []
    pub = m.group("h")
    texts = dict(_headers(include_dir))
    ptext = texts.get(pub)
    if ptext is None:
        return rel, []
    incs = list(re.finditer(rf"^\s*#\s*include\s*<{re.escape(rel)}>", ptext, re.M))
    if not incs:
        return pub, []
    # the last #include of it: QNX headers keep the non-QNX branch first
    return pub, _conds_at(ptext, ptext.count("\n", 0, incs[-1].start()))


def declaring_headers(sym: str, include_dir: Path,
                      limit: int = MAX_HITS) -> list[tuple[str, list[str], str]]:
    """(header, gating #if conditions, declaration line) for each SDP header declaring sym.

    An internal header is reported as the public one that includes it, with that include's
    conditions added. A copy under a subdirectory (devs/sys/queue.h) of a header that is
    also found (sys/queue.h) is dropped."""
    hits: list[tuple[str, list[str], str]] = []
    pat = _decl_patterns(sym)
    for rel, text in _headers(str(include_dir)):
        if sym not in text:
            continue
        m = pat.search(text)
        if not m:
            continue
        ln = text.count("\n", 0, m.start())
        line = text.splitlines()[ln].strip()[:120]
        pub, pconds = _public(rel, text, str(include_dir))
        hits.append((pub, pconds + _conds_at(text, ln), line))
        if len(hits) >= limit + 2:
            break
    names = {h[0] for h in hits}
    hits = [h for h in hits if not any(h[0] != o and h[0].endswith("/" + o) for o in names)]
    return hits[:limit]


def where_declared(sym: str, include_dir: Path) -> list[str]:
    out = []
    for rel, conds, line in declaring_headers(sym, include_dir):
        gate = f" (only when: {' && '.join(conds)})" if conds else ""
        out.append(f"`{sym}` is declared in <{rel}>{gate}: `{line}`")
    return out


def struct_members(tag: str, include_dir: Path, limit: int = 25) -> str:
    """The body of `struct tag { ... }` from the SDP headers, trimmed."""
    name = tag.split()[-1]
    pat = re.compile(rf"\bstruct\s+{re.escape(name)}\s*\{{(?P<body>.*?)\}}", re.S)
    for rel, text in _headers(str(include_dir)):
        if name in text and (m := pat.search(text)):
            body = re.sub(r"/\*.*?\*/|//[^\n]*", "", m.group("body"), flags=re.S)
            members: list[str] = []
            for ln in body.splitlines():
                ln = " ".join(ln.split())
                if ln and not ln.startswith("#") and ln not in members:
                    members.append(ln)
            return f"<{rel}> struct {name} {{ " + " ".join(members[:limit]) + " }"
    return ""


def qnx_facts(d: Diagnostic, kb: KnowledgeBase, sdp: SdpIndex | None,
              qnx_target: Path | None, code: str = "") -> list[str]:
    facts = _facts(d, kb, sdp, qnx_target)
    inc = qnx_target / "usr" / "include" if qnx_target else None
    if inc is not None:
        # raw Linux syscalls in the file: where QNX declares the function of the same name
        for name in sorted(set(re.findall(r"\bSYS_(\w+)", code)))[:3]:
            hits = where_declared(name, inc)
            facts += hits[:1] or [f"`{name}` is not declared in any QNX SDP header"]
    return facts


def _facts(d: Diagnostic, kb: KnowledgeBase, sdp: SdpIndex | None,
           qnx_target: Path | None) -> list[str]:
    facts: list[str] = []
    inc = qnx_target / "usr" / "include" if qnx_target else None
    sym = d.symbol.split("::")[-1] if d.symbol else ""
    rules = kb.name_to_rule()
    if (r := rules.get(sym) or rules.get(d.symbol) or rules.get(d.member)) is not None:
        facts.append(f"{r.title}: on QNX use {r.qnx}. {r.strategy}")
    if d.kind == "missing-header":
        if sdp is not None and inc is not None:
            base = Path(d.symbol).name
            similar = [rel for rel, _ in _headers(str(inc)) if Path(rel).name == base]
            facts.append(f"<{d.symbol}> does not exist in QNX 8.0."
                         + (f" Headers with that name: {', '.join(similar[:5])}" if similar
                            else ""))
        return facts
    if d.kind == "no-member" and inc is not None:
        if body := struct_members(d.symbol, inc):
            facts.append(f"QNX has no member `{d.member}`. Its definition: {body}")
        return facts
    if not sym or not re.fullmatch(r"\w+", sym):
        return facts
    if sdp is not None and sdp.has_symbol(sym):
        libs = sdp.libs_for(sym)
        facts.append(f"`{sym}` is exported by {', '.join(libs[:2])} on QNX")
    if inc is not None:
        hits = where_declared(sym, inc)
        facts += hits or [f"`{sym}` is not declared in any QNX SDP header"]
        if m := re.search(r"did you mean '([^']+)'", d.message):
            alt = m.group(1)
            facts += where_declared(alt, inc)[:1]
    return facts
