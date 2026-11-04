"""Rule-based fixes: from scan findings and build diagnostics to concrete, safe changes.

Two kinds of fix:
  port    a setting in the port's common.mk (link flag, CMake -D value); no source change
  source  a one-line edit in the project's source tree; collected into patches/qnx.patch

Every fix names the knowledge-base rule (and so the cited source) that justifies it.
Anything without a safe rule is returned as "unfixed" for the AI loop or a human.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cpp_text import guard_frames
from .diagnostics import Diagnostic
from .facts import declaring_headers
from .kb import KnowledgeBase
from .models import Finding
from .scaffold import PortSpec, Setting
from .scan_cmake import iter_cmake_files, parse_commands
from .sdp_index import SdpIndex

LIBC_ONLY = {"pthread", "rt", "dl"}
_LINK_CMDS = {"target_link_libraries", "link_libraries"}


@dataclass(frozen=True)
class Fix:
    rule_id: str
    kind: str  # port | source
    title: str  # what changes, one line
    reason: str  # why, one line (QNX behavior)
    setting: Setting | None = None  # port fixes
    field: str = ""  # port fixes: "ldflags" | "cmake_args"
    path: str = ""  # source fixes: relative to the source root
    line: int = 0  # 1-based
    old: str = ""
    new: str = ""

    def key(self) -> tuple[str, ...]:
        if self.kind == "port" and self.setting:
            return ("port", self.field, self.setting.value)
        return ("source", self.path, str(self.line), self.old)


@dataclass(frozen=True)
class Unfixed:
    diagnostic: Diagnostic
    rule_id: str  # knowledge-base rule that explains it, or ""
    hint: str


def _src(kb: KnowledgeBase, rule_id: str) -> str:
    srcs = kb.rule(rule_id).sources if rule_id in kb.rules else ()
    for s in srcs:
        url = kb.sources[s].url
        if not url.startswith("http"):
            return url
    return kb.sources[srcs[0]].url if srcs else ""


# ---- from scan findings (before the first build) -----------------------------------------
def from_findings(findings: Iterable[Finding], kb: KnowledgeBase, root: Path) -> list[Fix]:
    out: dict[tuple[str, ...], Fix] = {}

    def add(f: Fix | None) -> None:
        if f is not None:
            out.setdefault(f.key(), f)

    for f in findings:
        if f.guard != "none":
            continue
        if f.rule_id == "cmake-check-needs-libsocket" and f.area == "lib":
            add(Fix("cmake-check-needs-libsocket", "port",
                    "pass -DCMAKE_REQUIRED_LIBRARIES=socket",
                    f"{f.name} is in libsocket: without it CMake's check fails and the "
                    "feature is silently disabled",
                    Setting("-DCMAKE_REQUIRED_LIBRARIES=socket",
                            "sendmsg, recvmsg, socketpair, getpeereid... are in libsocket; "
                            "without it CMake's checks fail and features are silently "
                            "disabled", "cmake-check-needs-libsocket",
                            _src(kb, "cmake-check-needs-libsocket")),
                    field="cmake_args"))
        elif f.rule_id == "nonstandard-sys-headers" and f.kind == "include":
            new = kb.rule(f.rule_id).header_map.get(f.name)
            if new:
                add(_include_fix(root, f.path, f.line, f.name, new, f.rule_id))
        elif f.rule_id == "cmake-check-header-layout":
            add(_header_layout_fix(root, f))
    return list(out.values())


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="surrogateescape").splitlines(keepends=True)


def _include_fix(root: Path, rel: str, line: int, old_h: str, new_h: str,
                 rule_id: str) -> Fix | None:
    p = root / rel
    if not p.is_file():
        return None
    lines = _read_lines(p)
    if not 0 < line <= len(lines):
        return None
    text = lines[line - 1]
    m = re.search(r"#\s*include\s*[<\"]" + re.escape(old_h) + r"[>\"]", text)
    if not m:
        return None
    old = m.group(0)
    new = old.replace(old_h, new_h)
    return Fix(rule_id, "source", f"include <{new_h}> instead of <{old_h}>",
               f"QNX has no <{old_h}>; <{new_h}> is the standard header", path=rel, line=line,
               old=old, new=new)


def _header_layout_fix(root: Path, f: Finding) -> Fix | None:
    hdrs = f.name.split(" in ", 1)[1] if " in " in f.name else ""
    if not hdrs:
        return None
    p = root / f.path
    if not p.is_file():
        return None
    lines = _read_lines(p)
    if not 0 < f.line <= len(lines):
        return None
    text = lines[f.line - 1]
    m = re.search(r'(?<![\w/;."])"?' + re.escape(hdrs) + r'"?(?![\w/;."])', text)
    if not m or "AF_INET6" not in text:
        return None
    return Fix("cmake-check-header-layout", "source",
               "look for AF_INET6 in <sys/socket.h> too",
               "QNX defines AF_INET6 in <sys/socket.h> only, so the check failed and IPv6 "
               "was silently disabled", path=f.path, line=f.line, old=m.group(0),
               new=f'"sys/socket.h;{hdrs}"')


# ---- from build diagnostics ------------------------------------------------------------
def rel_in_root(root: Path, file: str) -> str | None:
    if not file:
        return None
    p = Path(file)
    try:
        if p.is_absolute():
            return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    if (root / p).is_file():
        return p.as_posix()
    hits = [q for q in root.rglob(p.name) if q.as_posix().endswith("/" + p.as_posix())]
    return hits[0].relative_to(root).as_posix() if len(hits) == 1 else None


def _link_rule_for(kb: KnowledgeBase, flag: str) -> str:
    for r in kb.rules.values():
        if r.link == flag:
            return r.id
    return "link-sdp-library"


def _lib_token(lib: str) -> re.Pattern[str]:
    """A bare `lib` / `-llib` link item (not part of a word, variable or generator expr)."""
    return re.compile(rf"(?<![\w${{:<>-])(-l)?{re.escape(lib)}(?![\w}}:>])")


def _is_link_list(c: Any) -> bool:
    """target_link_libraries(...), or set()/list(APPEND) of a project link-list variable
    such as LIBS or LIBS_SYSTEM (not CMake's own CMAKE_REQUIRED_LIBRARIES etc.)."""
    if c.name in _LINK_CMDS:
        return True
    if c.name == "set" and c.args:
        var = c.args[0]
    elif c.name == "list" and len(c.args) > 1 and c.args[0].upper() == "APPEND":
        var = c.args[1]
    else:
        return False
    return "LIB" in var.upper() and not var.upper().startswith("CMAKE_")


def _libc_only_fixes(root: Path, lib: str) -> list[Fix]:
    """Wrap a bare pthread/rt/dl in link lists so it is not used on QNX."""
    out = []
    tok_re = _lib_token(lib)
    for f in iter_cmake_files(root):
        text = f.read_text(encoding="utf-8", errors="replace")
        if lib not in text:
            continue
        lines = text.splitlines()
        rel = f.relative_to(root).as_posix()
        for c in parse_commands(text):
            if not _is_link_list(c) or not any(a in (lib, f"-l{lib}") for a in c.args):
                continue
            # the token may sit on a continuation line: search the command's lines
            for ln in range(c.line, min(len(lines), c.line + 30) + 1):
                m = tok_re.search(lines[ln - 1])
                if m:
                    tok = m.group(0)
                    out.append(Fix("link-libc-only", "source",
                                   f"do not link {tok} on QNX",
                                   f"QNX has no lib{lib}: its functions are in libc "
                                   f"('cannot find -l{lib}')", path=rel, line=ln, old=tok,
                                   new=f"$<$<NOT:$<PLATFORM_ID:QNX>>:{tok}>"))
                    break
                if ")" in lines[ln - 1]:
                    break
    return out


def _after_includes(root: Path, rel: str, block: str, rule_id: str, title: str,
                    reason: str, sym: str = "") -> Fix | None:
    """Insert `block` right after an #include (one-line edit of that line): the last one
    before the first use of `sym` that is active wherever that use is (not the one inside
    `#if defined(SHA1_TEST)` at the end of the file)."""
    lines = _read_lines(root / rel)
    if block in "".join(lines):
        return None  # already there
    inc = [i for i, ln in enumerate(lines) if re.match(r"\s*#\s*include\b", ln)]
    if sym:
        use = next((i for i, ln in enumerate(lines)
                    if re.search(rf"\b{re.escape(sym)}\b", ln)
                    and not re.match(r"\s*(?:#|//|/?\*)", ln)), None)
        if use is not None:
            frames = guard_frames("".join(lines).replace("\r", ""))
            at_use = frames[use] if use < len(frames) else ()
            inc = [i for i in inc if i < use and i < len(frames)
                   and at_use[:len(frames[i])] == frames[i]]
    if not inc:
        return None
    i = inc[-1]
    old = lines[i].rstrip("\r\n")
    return Fix(rule_id, "source", title, reason, path=rel, line=i + 1, old=old,
               new=f"{old}\n{block}")


def _optional_flag_fix(root: Path, rel: str, flag: str) -> Fix | None:
    """`#define FLAG 0` under #ifndef."""
    return _after_includes(
        root, rel, f"#ifndef {flag}\n#define {flag} 0 /* not on QNX; only an optimization "
        "hint */\n#endif", "optional-flag", f"define {flag} as 0 when missing",
        f"QNX has no {flag}; it is only a hint, so 0 keeps the behavior correct", flag)


# Same approach as glibc's own macros: a gcc statement expression, so the copy is on the
# caller's stack (released on return, exactly like strdupa). qcc is gcc 12.
ALLOCA_DUP_SHIM = """\
#if defined(__QNX__) && !defined(strdupa)
#include <string.h>
#define strdupa(s) (__extension__({ const char *pp_s_ = (s); \\
    size_t pp_n_ = strlen(pp_s_) + 1; \\
    (char *)memcpy(__builtin_alloca(pp_n_), pp_s_, pp_n_); }))
#define strndupa(s, n) (__extension__({ const char *pp_s_ = (s); \\
    size_t pp_n_ = strnlen(pp_s_, (n)); char *pp_d_ = (char *)__builtin_alloca(pp_n_ + 1); \\
    pp_d_[pp_n_] = '\\0'; (char *)memcpy(pp_d_, pp_s_, pp_n_); }))
#endif"""


def _qnx_header_fix(root: Path, rel: str, sym: str, include_dir: Path | None) -> Fix | None:
    """`sym` is used without a declaration, but the QNX SDP declares it in one header:
    include that header on QNX. Only for a single unambiguous public header."""
    if include_dir is None or not re.fullmatch(r"\w+", sym):
        return None
    c_file = rel.endswith(".c")
    hits = [h for h in declaring_headers(sym, include_dir, limit=4)
            if not h[0].startswith(("_", "c++/", "bits/"))
            and (h[0].endswith(".h") or not c_file)]  # no C++ header for a C file
    if len({h[0] for h in hits}) != 1:
        return None
    hdr, conds, _ = hits[0]
    text = "".join(_read_lines(root / rel))
    if re.search(rf"^\s*#\s*include\s*[<\"]{re.escape(hdr)}[>\"]", text, re.M):
        return None  # included already: something else hides it (see _qnx_source_fix)
    gate = f" (declared when {' && '.join(conds)})" if conds else ""
    return _after_includes(root, rel, f"#if defined(__QNX__)\n#include <{hdr}>\n#endif",
                           "qnx-header", f"include <{hdr}> for {sym} on QNX",
                           f"QNX declares {sym} in <{hdr}>{gate}", sym)


_SRC_EXT = (".c", ".cc", ".cpp", ".cxx")


def _callers(root: Path, sym: str, limit: int = 20) -> list[str]:
    """Source files (relative) that call `sym`."""
    pat = re.compile(rf"\b{re.escape(sym)}\s*\(")
    out = []
    for p in sorted(root.rglob("*")):
        if (p.suffix in _SRC_EXT and p.is_file() and ".git" not in p.parts
                and pat.search(p.read_text(encoding="utf-8", errors="replace"))):
            out.append(p.relative_to(root).as_posix())
            if len(out) >= limit:
                break
    return out


def _qnx_source_fix(sym: str, include_dir: Path | None, kb: KnowledgeBase) -> Fix | None:
    """`sym` is undeclared, but QNX declares it behind an __EXT_* gate: the build uses a
    strict mode (-std=c++17, -std=c99, ...) in which QNX headers hide POSIX. Define
    _QNX_SOURCE, as most official QNX ports do (F-013)."""
    if include_dir is None or not re.fullmatch(r"\w+", sym):
        return None
    for hdr, conds, _ in declaring_headers(sym, include_dir, limit=3):
        if any("__EXT_" in c for c in conds):
            rid = "strict-mode-hides-posix"
            return Fix(rid, "port", "define _QNX_SOURCE",
                       f"{sym} is declared in <{hdr}> only when {' && '.join(conds)}",
                       Setting("-D_QNX_SOURCE",
                               "a strict -std= mode hides POSIX declarations in QNX headers",
                               rid, _src(kb, rid)), field="cflags")
    return None


def _header_or_source(root: Path, sym: str, include_dir: Path | None,
                      kb: KnowledgeBase) -> list[Fix]:
    """A function that failed to link after an implicit declaration: include its QNX header
    in every file that calls it; once all do, the remaining cause is a strict mode."""
    hfxs = [h for rel in _callers(root, sym)
            if (h := _qnx_header_fix(root, rel, sym, include_dir))]
    if hfxs:
        return hfxs
    qfx = _qnx_source_fix(sym, include_dir, kb)
    return [qfx] if qfx else []


_DUMPMACHINE = re.compile(r"\$\{CMAKE_(?:C|CXX)_COMPILER\}(\s+-dumpmachine)")
QNX_GCC = "$ENV{QNX_HOST}/usr/bin/nto${CMAKE_SYSTEM_PROCESSOR}-gcc"


def _dumpmachine_fixes(root: Path) -> list[Fix]:
    """qcc does not answer -dumpmachine (rc=1, no output); the gcc driver it wraps does
    (x86_64-pc-nto-qnx8.0.0). Point such probes at that driver."""
    out = []
    for f in iter_cmake_files(root):
        rel = f.relative_to(root).as_posix()
        for i, ln in enumerate(_read_lines(f), 1):
            if m := _DUMPMACHINE.search(ln):
                out.append(Fix("qcc-dumpmachine", "source", "ask the gcc driver for the target "
                               "triplet", "qcc does not support -dumpmachine",
                               path=rel, line=i, old=m.group(0),
                               new=QNX_GCC + m.group(1)))
    return out


def _alloca_dup_fix(root: Path, rel: str, sym: str) -> Fix | None:
    return _after_includes(root, rel, ALLOCA_DUP_SHIM, "gnu-alloca-dup",
                           f"define {sym} for QNX (stack copy, as in glibc)",
                           f"QNX libc has no {sym}; strdup() instead would leak", sym)


def from_diagnostics(diags: Iterable[Diagnostic], kb: KnowledgeBase, sdp: SdpIndex | None,
                     root: Path, implicit: dict[str, Diagnostic] | None = None,
                     include_dir: Path | None = None,
                     ) -> tuple[list[Fix], list[Unfixed]]:
    """`implicit`: implicit-declaration warnings by function name (the call sites of
    functions that then fail to link), accumulated over build attempts.
    `include_dir`: the SDP's usr/include, to find where QNX declares a missing name."""
    fixes: dict[tuple[str, ...], Fix] = {}
    unfixed: list[Unfixed] = []
    h2r = kb.header_to_rule()
    i2r = kb.name_to_rule()
    implicit = implicit or {}
    shims = set(kb.rule("gnu-alloca-dup").functions) if "gnu-alloca-dup" in kb.rules else set()

    def add(f: Fix) -> None:
        fixes.setdefault(f.key(), f)

    for d in diags:
        if not d.is_error:
            continue
        if d.kind == "missing-header":
            rule = h2r.get(d.symbol)
            new = rule.header_map.get(d.symbol) if rule else None
            rel = rel_in_root(root, d.file)
            if rule and new and rel:
                fx = _include_fix(root, rel, d.line, d.symbol, new, rule.id)
                if fx:
                    add(fx)
                    continue
            hint = (f"{rule.title}: {rule.strategy}" if rule
                    else f"<{d.symbol}> is not in the QNX SDP")
            unfixed.append(Unfixed(d, rule.id if rule else "header-absent", hint))
        elif (d.kind == "undefined-reference" and d.symbol in shims and d.symbol in implicit
              and (rel := rel_in_root(root, implicit[d.symbol].file))
              and (afx := _alloca_dup_fix(root, rel, d.symbol))):
            add(afx)
        elif (d.kind == "undefined-reference" and d.symbol in implicit
              and not (sdp and sdp.has_symbol(d.symbol))
              and (hfxs := _header_or_source(root, d.symbol, include_dir, kb))):
            for f in hfxs:  # e.g. be32toh: a macro in <net/netbyte.h>, never included
                add(f)
        elif d.kind == "undefined-reference":
            sym = d.symbol
            flag =sdp.link_flag_for(sym) if sdp and re.fullmatch(r"\w+", sym) else None
            if flag:
                rid = _link_rule_for(kb, flag)
                lib = sdp.libs_for(sym)[0] if sdp else flag
                add(Fix(rid, "port", f"link {flag}", f"{sym} is in {lib} on QNX",
                        Setting(flag, f"{sym} and friends are in {lib} on QNX, not in libc",
                                rid, _src(kb, rid)), field="ldflags"))
            else:
                where = "not in the QNX SDP" if sdp else "unknown (no SDP index)"
                unfixed.append(Unfixed(d, i2r[sym].id if sym in i2r else "",
                                       f"{sym} is {where}: a project symbol or a missing "
                                       "feature"))
        elif (d.kind == "undeclared" and "optional-flag" in kb.rules
              and d.symbol in kb.rule("optional-flag").identifiers
              and (rel := rel_in_root(root, d.file))
              and (ofx := _optional_flag_fix(root, rel, d.symbol))):
            add(ofx)
        elif (d.kind in ("undeclared", "unknown-type")
              and (rel := rel_in_root(root, d.file))
              and (hfx := _qnx_header_fix(root, rel, d.symbol.removeprefix("::"),
                                          include_dir))):
            add(hfx)
        elif (d.kind in ("undeclared", "unknown-type")
              and (qfx := _qnx_source_fix(d.symbol.removeprefix("::"), include_dir, kb))):
            add(qfx)  # the header is included, but a strict -std= mode hides it
        elif d.kind == "link-error" and "recompile with -fPIC" in d.message:
            rid = "qcc-not-gnucc"
            add(Fix(rid, "port", "build position-independent code",
                    "ld: 'recompile with -fPIC'; the project adds -fPIC only for GCC, and CMake "
                    "identifies qcc as QCC",
                    Setting("-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
                            "objects linked into a shared library must be PIC", rid,
                            _src(kb, rid)), field="cmake_args"))
        elif d.kind == "cmake-error" and (dms := _dumpmachine_fixes(root)):
            for f in dms:
                add(f)
        elif d.kind == "missing-library" and d.symbol in LIBC_ONLY:
            found = _libc_only_fixes(root, d.symbol)
            for fx in found:
                add(fx)
            if not found:
                unfixed.append(Unfixed(d, "link-libc-only", kb.rule("link-libc-only").strategy))
        else:
            rule = i2r.get(d.symbol.split("::")[-1]) if d.symbol else None
            unfixed.append(Unfixed(d, rule.id if rule else "",
                                   f"{rule.title}: {rule.strategy}" if rule else d.message))
    return list(fixes.values()), unfixed


# ---- applying ------------------------------------------------------------------------------
def apply_source(root: Path, fix: Fix) -> bool:
    """Apply a one-line source edit. False if the line no longer matches."""
    p = root / fix.path
    lines = _read_lines(p)
    if not 0 < fix.line <= len(lines) or fix.old not in lines[fix.line - 1]:
        return False
    if fix.rule_id == "link-libc-only":  # replace the bare token only, never inside a word
        lib = fix.old.removeprefix("-l")
        new_line, n = _lib_token(lib).subn(fix.new, lines[fix.line - 1], count=1)
        if n == 0:
            return False  # only wrapped occurrences left: already applied
        lines[fix.line - 1] = new_line
    else:
        lines[fix.line - 1] = lines[fix.line - 1].replace(fix.old, fix.new, 1)
    with open(p, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        fh.write("".join(lines))
    return True


def apply_port(spec: PortSpec, fix: Fix) -> bool:
    if fix.setting is None:
        return False
    if fix.field == "ldflags":
        return spec.add_ldflag(fix.setting)
    if fix.field == "cmake_args":
        return spec.add_cmake_arg(fix.setting)
    if fix.field == "cflags":
        return spec.add_cflag(fix.setting)
    return False


def apply(fix: Fix, spec: PortSpec, root: Path) -> bool:
    return apply_port(spec, fix) if fix.kind == "port" else apply_source(root, fix)
