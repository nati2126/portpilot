"""Lightweight C/C++ text processing: strip comments/strings, track preprocessor guards.

Not a parser. It answers, per line:
  * what code text is there (comments removed, string/char contents blanked, lines kept);
  * which string literals start on that line;
  * which #if/#ifdef conditions are active (with #else/#elif negation tracked).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_RAW_OPEN = re.compile(r'"([^()\\ ]{0,16})\(')
_SPECIAL = re.compile(r"[/\"']")


def strip_code(src: str) -> tuple[str, list[tuple[int, str]]]:
    """Return (code, strings). `code` has the same line structure as `src`, with comments
    removed and string/char literal contents blanked (quotes kept). `strings` holds
    (1-based line, contents) for every string literal."""
    out: list[str] = []
    strings: list[tuple[int, str]] = []
    i, n, line = 0, len(src), 1
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j  # keep the newline itself
        elif c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            nl = src.count("\n", i, j)
            out.append("\n" * nl if nl else " ")
            line += nl
            i = j
        elif c == '"' or c == "'":
            if c == '"' and i > 0 and src[i - 1] == "R" and (m := _RAW_OPEN.match(src, i)):
                close = ")" + m.group(1) + '"'
                end = src.find(close, i)
                end = n if end < 0 else end + len(close)
                body = src[m.end() : end - len(close)]
                strings.append((line, body))
                nl = src.count("\n", i, end)
                out.append('""' + "\n" * nl)
                line += nl
                i = end
                continue
            # C++14 digit separator (1'000'000): not a char literal
            if c == "'" and i > 0 and src[i - 1].isalnum() and nxt.isalnum() and _digit_sep(src, i):
                out.append(c)
                i += 1
                continue
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            if c == '"':
                strings.append((line, src[i + 1 : j]))
            out.append(c + c)
            i = j + 1 if j < n and src[j] == c else j
        else:
            # plain code: copy everything up to the next / " ' in one go
            m = _SPECIAL.search(src, i + 1)
            j = n if m is None else m.start()
            out.append(src[i:j])
            line += src.count("\n", i, j)
            i = j
    return "".join(out), strings


def _digit_sep(src: str, i: int) -> bool:
    k = i - 1
    while k >= 0 and (src[k].isalnum() or src[k] in "'."):
        k -= 1
    token = src[k + 1 : i]
    return bool(token) and token[0].isdigit()


_DIRECTIVE = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)$")


@dataclass(frozen=True)
class Frame:
    cond: str  # normalized condition, e.g. "defined(__linux__)"
    negated: bool  # True inside #else, or for earlier conditions of an #elif chain


def _norm(kind: str, rest: str) -> str:
    rest = rest.strip()
    if kind == "ifdef":
        return f"defined({rest.split()[0]})" if rest else ""
    if kind == "ifndef":
        return f"!defined({rest.split()[0]})" if rest else ""
    return rest


_COMMENT = re.compile(r"/\*.*?\*/|//.*$")


def guard_frames(code: str, raw: str | None = None) -> list[tuple[Frame, ...]]:
    """For each line (index 0 = line 1) the active preprocessor frames, outermost first.
    With `raw` (the unstripped source, same line count), #if/#elif conditions keep their
    string arguments, e.g. __has_include("x.h")."""
    lines = code.split("\n")
    raw_lines = raw.split("\n") if raw is not None else None
    result: list[tuple[Frame, ...]] = []
    stack: list[tuple[list[str], bool]] = []  # (conditions of the chain, in #else)

    def active() -> tuple[Frame, ...]:
        frames: list[Frame] = []
        for conds, in_else in stack:
            *prev, cur = conds
            frames += [Frame(c, True) for c in prev]
            frames.append(Frame(cur, in_else))
        return tuple(frames)

    cur: tuple[Frame, ...] = ()
    i = 0
    while i < len(lines):
        joined, k = lines[i], i
        if "#" not in joined:  # fast path: not a directive
            result.append(cur)
            i += 1
            continue
        while joined.endswith("\\") and k + 1 < len(lines):
            k += 1
            joined = joined[:-1] + " " + lines[k]
        m = _DIRECTIVE.match(joined)
        if m:
            kind, rest = m.group(1), m.group(2)
            if raw_lines is not None and kind in ("if", "elif") and i < len(raw_lines) \
                    and '"' in raw_lines[i]:
                rj = " ".join(raw_lines[j].rstrip("\\") for j in range(i, min(k + 1,
                                                                             len(raw_lines))))
                rm = _DIRECTIVE.match(_COMMENT.sub(" ", rj))
                if rm:
                    rest = rm.group(2)
            if kind in ("if", "ifdef", "ifndef"):
                stack.append(([_norm(kind, rest)], False))
            elif kind == "elif" and stack:
                stack[-1] = ([*stack[-1][0], _norm(kind, rest)], False)
            elif kind == "else" and stack:
                stack[-1] = (stack[-1][0], True)
            elif kind == "endif" and stack:
                stack.pop()
            cur = active()
        for _ in range(i, k + 1):
            result.append(cur)
        i = k + 1
    return result


# ---- guard classification --------------------------------------------------------------
# Classification works on the *tokens* of macro names, so project-specific macros such as
# NNG_PLATFORM_WINDOWS or FOO_ON_OPENBSD are understood, not just _WIN32/__APPLE__.
QNX_TOKENS = {"qnx", "qnxnto"}
LINUX_TOKENS = {"linux", "glibc", "android"}
OTHER_OS_TOKENS = {
    "windows", "win32", "win64", "wince", "msc", "msvc", "mingw", "mingw32", "mingw64",
    "cygwin", "darwin", "macos", "macosx", "osx", "apple", "mach", "ios", "bsd", "freebsd",
    "netbsd", "openbsd", "dragonfly", "solaris", "sunos", "sun", "illumos", "haiku",
    "emscripten", "wasm", "aix", "hpux", "vxworks", "zephyr", "fuchsia",
}
FEATURE_TOKENS = {"have", "has", "use", "enable", "enabled", "with"}
_GENERIC = FEATURE_TOKENS | {"nng", "sys", "posix", "support", "supported", "h", "lib", "the",
                             "func", "function", "platform", "config", "no", "disable"}
_IDENT = re.compile(r"[A-Za-z_]\w*")


def tokens(ident: str) -> list[str]:
    return [t for t in ident.lower().split("_") if t]


def ident_kind(ident: str) -> str | None:
    """'qnx' | 'linux' | 'other-os' | 'feature' | None for one macro name."""
    toks = set(tokens(ident))
    if toks & QNX_TOKENS:
        return "qnx"
    if toks & FEATURE_TOKENS:
        return "feature"
    if toks & LINUX_TOKENS:
        return "linux"
    if toks & OTHER_OS_TOKENS:
        return "other-os"
    return None


def related(macro: str, api_names: tuple[str, ...]) -> bool:
    """Is a feature macro (e.g. NNG_HAVE_EPOLL) about one of these APIs (epoll_wait, ...)?"""
    flat = macro.lower().replace("_", "")
    mtoks = set(tokens(macro)) - _GENERIC
    for name in api_names:
        base = re.sub(r"\.(h|hpp)$", "", name).replace("/", "_")
        if len(base) >= 4 and base.lower().replace("_", "") in flat:
            return True
        if mtoks & ({t for t in tokens(base) if len(t) >= 4} - _GENERIC):
            return True
    return False


def _negated(cond: str, start: int) -> bool:
    before = cond[:start].rstrip()
    before = re.sub(r"defined\s*\(?\s*$", "", before).rstrip()
    return before.endswith("!")


def classify_guard(frames: tuple[Frame, ...], api_names: tuple[str, ...] = ()) -> str:
    """How code at this point is guarded, seen from QNX:
    'qnx'      a condition mentions QNX (project already handles QNX here)
    'linux'    only compiled on Linux                     -> QNX skips it
    'other-os' only compiled on another OS (Windows, BSD) -> QNX skips it
    'feature'  only compiled if a feature *about this API* is detected (HAVE_EPOLL around
               epoll_wait) -> QNX lacks it, so the project's fallback is used
    'none'     compiled on QNX"""
    kind = "none"
    for f in frames:
        for m in _IDENT.finditer(f.cond):
            ident = m.group(0)
            if ident == "defined":
                continue
            k = ident_kind(ident)
            if k == "qnx":
                return "qnx"
            positive = _negated(f.cond, m.start()) == f.negated  # taken when ident is true
            if not positive:
                continue
            if k == "linux":
                kind = "linux"
            elif k == "other-os" and kind == "none":
                kind = "other-os"
            elif kind == "none" and (
                ident in api_names or (k == "feature" and related(ident, api_names))
            ):
                kind = "feature"
    return kind


def path_guard(rel: str) -> str:
    """OS-specific directories (src/platform/windows/...) are not compiled on QNX."""
    for part in rel.lower().split("/")[:-1]:
        k = ident_kind(part.replace("-", "_"))
        if k in ("linux", "other-os", "qnx"):
            return k
    return "none"
