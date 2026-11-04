"""Turn a QNX build log (cmake + make + qcc/q++ + ld) into structured diagnostics.

The formats were taken from real qcc 12.2 (SDP 8.0) output; tests/data/diag/ holds the samples.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

# kind values, most specific first in the docs:
#   missing-header       fatal error: <h>: No such file or directory
#   implicit-decl        implicit declaration of function 'f'
#   undeclared           'X' undeclared / was not declared in this scope / has not been
#                        declared / is not a member of
#   unknown-type         unknown type name 'T' / 'T' does not name a type
#   no-member            'struct s' has no member named 'm'
#   compile-error        any other compiler error
#   undefined-reference  ld: undefined reference to 'sym'
#   missing-library      ld: cannot find -lfoo
#   duplicate-symbol     ld: multiple definition of 'sym'
#   link-error           any other linker error
#   missing-package      CMake: find_package() failed
#   cmake-error          any other CMake error
KINDS = ("missing-header", "implicit-decl", "undeclared", "unknown-type", "no-member",
         "compile-error", "undefined-reference", "missing-library", "duplicate-symbol",
         "link-error", "missing-package", "cmake-error")


@dataclass(frozen=True)
class Diagnostic:
    kind: str
    severity: str  # error | warning
    message: str
    tool: str  # cc | ld | cmake
    file: str = ""
    line: int = 0
    col: int = 0
    symbol: str = ""  # header, identifier, symbol, library or package
    member: str = ""  # for no-member: the member name
    function: str = ""  # for undefined-reference: the function that references it
    included_from: tuple[str, ...] = ()
    source_line: str = ""  # the source line gcc quoted, if any
    log_line: int = 0  # 1-based line in the log

    @property
    def is_error(self) -> bool:
        return self.severity == "error"

    def location(self) -> str:
        if not self.file:
            return ""
        if not self.line:
            return self.file
        return f"{self.file}:{self.line}" + (f":{self.col}" if self.col else "")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["included_from"] = list(self.included_from)
        return d


@dataclass
class ParsedLog:
    diagnostics: list[Diagnostic] = field(default_factory=list)
    failed_targets: list[str] = field(default_factory=list)  # make targets that failed

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.is_error]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if not d.is_error]

    @property
    def phase(self) -> str:
        """Where the build stopped: configure | compile | link | ok."""
        tools = {d.tool for d in self.errors}
        if "cmake" in tools:
            return "configure"
        if "cc" in tools:
            return "compile"
        if "ld" in tools:
            return "link"
        return "ok" if not self.failed_targets else "unknown"


_Q = "['‘`]"  # opening quote: ' ‘ `
_E = "['’]"  # closing quote: ' ’
_GCC = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[^:\s][^:]*?):(?P<line>\d+):(?:(?P<col>\d+):)? "
                  r"(?P<sev>fatal error|error|warning|note): (?P<msg>.*)$")
_INCLUDED = re.compile(r"^(?:In file included|\s+) from (?P<loc>[^:]+:\d+)(?::\d+)?[:,]$")
_CONTEXT = re.compile(r"^\s*\d+ \| (?P<src>.*)$")
_LD_PREFIX = re.compile(r"^(?:\S*/)?(?:\S+-)?ld(?:\.\w+)?: (?P<rest>.*)$")
_LD_IN_FUNC = re.compile(rf"^(?P<obj>.+): in function {_Q}(?P<fn>.+){_E}:$")
_LD_UNDEF = re.compile(rf"^(?P<loc>.+?): (?:\(\.\w[^)]*\): )?"
                       rf"undefined reference to {_Q}(?P<sym>.+){_E}$")
_LD_UNDEF_LOC = re.compile(r"^(?P<file>[^:]+?)(?::(?P<line>\d+))?(?::\(\.[^)]*\))?$")
_LD_MULTI = re.compile(rf"^(?P<loc>.+?): multiple definition of {_Q}(?P<sym>.+){_E}")
_LD_NOLIB = re.compile(r"^cannot find -l(?P<lib>[^\s:]+)")
_CMAKE_AT = re.compile(r"^CMake Error at (?P<file>.+?):(?P<line>\d+) \((?P<cmd>\w+)\):\s*$")
_CMAKE_PLAIN = re.compile(r"^CMake Error(?: \(dev\))?: (?P<msg>.*)$")
_MAKE_FAIL = re.compile(r"^g?make(?:\[\d+\])?: \*\*\* \[(?P<target>[^\]]+)\] Error \d+")
_NOT_FOUND_PKG = re.compile(r"Could NOT find (?P<pkg>[\w:+.-]+)|"
                            r"By not providing \"Find(?P<pkg2>[\w+.-]+)\.cmake\"|"
                            r"Could not find a package configuration file provided by "
                            r"\"(?P<pkg3>[\w+.-]+)\"")
_NOISE = re.compile(r"^(?:collect2: error: ld returned|cc: .*\b(?:ld|cc1\w*) error \d+|"
                    r"cc1\w*: some warnings being treated as errors|compilation terminated\.)")


def _norm_quotes(s: str) -> str:
    return s.replace("‘", "'").replace("’", "'")


def classify_compiler(msg: str) -> tuple[str, str, str]:
    """(kind, symbol, member) for a gcc error/warning message."""
    m = _norm_quotes(msg)
    if r := re.match(r"(?P<h>[^:]+): No such file or directory", m):
        return "missing-header", r.group("h").strip(), ""
    if r := re.search(r"implicit declaration of function '(?P<f>[^']+)'", m):
        return "implicit-decl", r.group("f"), ""
    if r := re.search(r"'(?P<x>[^']+)' (?:undeclared|was not declared in this scope|"
                      r"has not been declared)", m):
        return "undeclared", r.group("x"), ""
    if r := re.search(r"'(?P<x>[^']+)' is not a member of '(?P<ns>[^']+)'", m):
        return "undeclared", f"{r.group('ns')}::{r.group('x')}", ""
    if r := re.search(r"unknown type name '(?P<t>[^']+)'|'(?P<t2>[^']+)' does not name a type",
                      m):
        return "unknown-type", r.group("t") or r.group("t2"), ""
    if r := re.search(r"'(?P<s>[^']+)' has no member named '(?P<mem>[^']+)'", m):
        return "no-member", r.group("s"), r.group("mem")
    return "compile-error", "", ""


def parse(text: str | Iterable[str]) -> ParsedLog:
    lines = text.splitlines() if isinstance(text, str) else [ln.rstrip("\n") for ln in text]
    out = ParsedLog()
    seen: set[tuple[str, str, int, int, str, str]] = set()
    included: list[str] = []
    ld_function = ""

    def add(d: Diagnostic) -> None:
        key = (d.kind, d.file, d.line, d.col, d.symbol, d.member or d.message)
        if key not in seen:
            seen.add(key)
            out.diagnostics.append(d)

    i = 0
    while i < len(lines):
        raw = lines[i]
        ln = raw.rstrip()
        i += 1
        if not ln or _NOISE.match(ln):
            continue
        if m := _INCLUDED.match(ln):
            included.append(m.group("loc"))
            continue
        if m := _GCC.match(ln):
            sev = m.group("sev")
            if sev == "note":
                included = []
                continue
            src = ""
            if i < len(lines) and (c := _CONTEXT.match(lines[i])):
                src = c.group("src").rstrip()
            kind, sym, member = classify_compiler(m.group("msg"))
            add(Diagnostic(
                kind=kind, severity="warning" if sev == "warning" else "error",
                message=_norm_quotes(m.group("msg")), tool="cc", file=m.group("file"),
                line=int(m.group("line")), col=int(m.group("col") or 0), symbol=sym,
                member=member, included_from=tuple(included), source_line=src, log_line=i))
            included = []
            continue
        included = []
        rest = ln
        is_ld = False
        if m := _LD_PREFIX.match(ln):
            rest, is_ld = m.group("rest"), True
        if m := _LD_IN_FUNC.match(rest):
            ld_function = _norm_quotes(m.group("fn"))
            continue
        if m := _LD_UNDEF.match(rest):
            loc = _LD_UNDEF_LOC.match(m.group("loc"))
            file = loc.group("file") if loc else m.group("loc")
            line = int(loc.group("line")) if loc and loc.group("line") else 0
            sym = _norm_quotes(m.group("sym"))
            add(Diagnostic(kind="undefined-reference", severity="error",
                           message=f"undefined reference to '{sym}'", tool="ld", file=file,
                           line=line, symbol=sym, function=ld_function, log_line=i))
            continue
        if m := _LD_MULTI.match(rest):
            sym = _norm_quotes(m.group("sym"))
            add(Diagnostic(kind="duplicate-symbol", severity="error",
                           message=f"multiple definition of '{sym}'", tool="ld",
                           file=m.group("loc"), symbol=sym, log_line=i))
            continue
        if is_ld:
            if m := _LD_NOLIB.match(rest):
                add(Diagnostic(kind="missing-library", severity="error",
                               message=f"cannot find -l{m.group('lib')}", tool="ld",
                               symbol=m.group("lib"), log_line=i))
            elif "warning:" in rest:
                add(Diagnostic(kind="link-error", severity="warning", message=rest, tool="ld",
                               log_line=i))
            else:
                add(Diagnostic(kind="link-error", severity="error", message=rest, tool="ld",
                               log_line=i))
            continue
        if (m := _CMAKE_AT.match(ln)) or (m := _CMAKE_PLAIN.match(ln)):
            start = i
            body: list[str] = []
            if m.groupdict().get("msg"):
                body.append(m.group("msg"))
            blank = 0
            while i < len(lines):
                nxt = lines[i].rstrip()
                if not nxt:
                    blank += 1
                    if blank >= 2:
                        break
                    i += 1
                    continue
                if not nxt.startswith(" ") and body:
                    break
                blank = 0
                body.append(nxt.strip())
                i += 1
            msg = " ".join(body)
            kind, sym = "cmake-error", ""
            if p := _NOT_FOUND_PKG.search(msg):
                kind, sym = "missing-package", p.group("pkg") or p.group("pkg2") or p.group("pkg3")
            gd = m.groupdict()
            add(Diagnostic(kind=kind, severity="error", message=msg, tool="cmake",
                           file=gd.get("file") or "", line=int(gd.get("line") or 0),
                           symbol=sym or (gd.get("cmd") or ""), log_line=start))
            continue
        if m := _MAKE_FAIL.match(ln):
            out.failed_targets.append(m.group("target"))
            continue
    return out
