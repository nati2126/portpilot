"""Scan C/C++ sources for Linux-specific headers, calls, identifiers and strings."""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .configure import UNDEF, CExpr, Value, sdp_macros, target_macros
from .cpp_text import Frame, classify_guard, guard_frames, ident_kind, path_guard, strip_code
from .kb import KnowledgeBase, Rule
from .models import Finding
from .sdp_index import SdpIndex

SOURCE_EXTS = {".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp"}
SKIP_DIRS = {".git", ".github", ".svn", "node_modules", "__pycache__", ".cache"}
_BUILD_DIR = re.compile(r"^(build|_build|cmake-build-.*|out|nto-.*)$")
_VENDORED = {"third_party", "thirdparty", "3rdparty", "third-party", "external", "extern",
             "vendor", "vendored", "deps", "googletest", "gtest", "gmock", "catch2", "doctest",
             "subprojects", "contrib"}
_TESTS = {"test", "tests", "testing", "unittest", "unittests", "unit_tests", "t"}
_EXTRA = {"example", "examples", "sample", "samples", "demo", "demos", "doc", "docs",
          "bench", "benchmark", "benchmarks", "perf", "tools", "fuzz", "fuzzing"}
_SYSTEM_DIRS = {"sys", "linux", "asm", "asm-generic", "bits", "netinet", "netinet6", "arpa",
                "net", "netpacket", "machine", "scsi", "mtd", "sound", "rdma", "xen", "gnu"}

_INCLUDE = re.compile(r'^\s*#\s*include\s*([<"])([^>"]+)[>"]')
_IDENT = re.compile(r"[A-Za-z_]\w*")
_HEADER_EXTS = {".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp"}
# guards meaning "QNX does not compile this"
DEAD_GUARDS = {"config-off", "linux", "other-os", "other-arch", "feature", "build-linux",
               "build-other-os", "build-feature", "build-optional"}


_DEFINE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)(\()?(.*)$", re.M)
_NOT_DECL_WORDS = {"return", "case", "else", "do", "throw", "new", "delete", "sizeof",
                   "co_return", "co_await", "not", "and", "or"}
_ARCH_FAMILY = {
    "x86": "x86", "x86_64": "x86", "x64": "x86", "amd64": "x86", "i386": "x86", "i686": "x86",
    "sse": "x86", "sse2": "x86", "sse4": "x86", "avx": "x86", "avx2": "x86", "avx512": "x86",
    "arm": "arm", "arm64": "arm", "aarch64": "arm", "armv7": "arm", "armv8": "arm",
    "neon": "arm", "power": "power", "ppc": "power", "ppc64": "power", "powerpc": "power",
    "altivec": "power", "vsx": "power", "s390": "s390", "s390x": "s390", "riscv": "riscv",
    "riscv64": "riscv", "rvv": "riscv", "loongarch": "loongarch", "loongarch64": "loongarch",
    "lsx": "loongarch", "lasx": "loongarch", "mips": "mips", "sparc": "sparc",
}


def arch_guard(rel: str, arch: str) -> str:
    """CPU-specific directories (arch/power/...) are not compiled for another CPU."""
    target = _ARCH_FAMILY.get(arch.removesuffix("le"), "")
    for part in rel.lower().split("/")[:-1]:
        fam = _ARCH_FAMILY.get(part)
        if fam and target and fam != target:
            return "other-arch"
    return "none"


def _is_declaration(code: str, start: int) -> bool:
    """`ptr clone(` / `int *fork(` (a declaration) rather than `x = fork(` (a call)."""
    prev = code[max(0, start - 80):start].rstrip()
    if prev.endswith(("&&", "||", "->", ">>", "<<")):
        return False
    m = re.search(r"([A-Za-z_]\w*|[*&>])$", prev)
    if not m:
        return False
    tok = m.group(1)
    return tok in "*&>" or tok not in _NOT_DECL_WORDS


@dataclass
class _Src:
    rel: str
    src: str
    code: str
    strings: list[tuple[int, str]]
    frames: list[tuple[Frame, ...]]


def area_of(rel: str) -> str:
    parts = [p.lower() for p in rel.split("/")[:-1]]
    if any(p in _VENDORED for p in parts):
        return "vendored"
    if any(p in _TESTS for p in parts):
        return "test"
    if any(p in _EXTRA for p in parts):
        return "extra"
    return "lib"


def build_guard_for(rel: str, build_guards: dict[str, str]) -> str | None:
    """Guard from the build system: keys are source basenames, 'stem:<dir>/<name>' (a
    target named like the file) or 'dir:<path>/' prefixes."""
    name = rel.rsplit("/", 1)[-1]
    if name in build_guards:
        return build_guards[name]
    stem = "stem:" + rel.rsplit(".", 1)[0]
    if stem in build_guards:
        return build_guards[stem]
    best = ""
    for key in build_guards:
        if key.startswith("dir:") and rel.startswith(key[4:]) and len(key) > len(best):
            best = key
    return build_guards[best] if best else None


def iter_sources(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not _BUILD_DIR.match(d))
        for fn in sorted(filenames):
            if Path(fn).suffix.lower() in SOURCE_EXTS:
                yield Path(dirpath, fn)


def _alternation(names: list[str]) -> str:
    return "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))


class SourceScanner:
    def __init__(self, kb: KnowledgeBase, sdp: SdpIndex | None = None,
                 arch: str = "x86_64") -> None:
        self.kb = kb
        self.sdp = sdp
        self.arch = arch
        self.cexpr = CExpr(target_macros(arch))
        self._frame_cache: dict[str, bool | None] = {}
        self.by_header = kb.header_to_rule()
        self.prefix_rules = [(p, r) for r in kb.scan_rules() for p in r.header_prefixes]
        self.by_func = kb.function_to_rule()
        self.by_ident = kb.identifier_to_rule()
        self.string_rules = [(s, r) for r in kb.scan_rules() for s in r.strings]
        self._re_cache: dict[tuple[str, tuple[str, ...]], re.Pattern[str]] = {}
        self._suffixes: set[str] = set()

    # -------------------------------------------------------------------------------------
    def scan(
        self,
        root: Path,
        build_guards: dict[str, str] | None = None,
        macros: dict[str, Value] | None = None,
    ) -> tuple[list[Finding], int, list[str]]:
        """Return (findings, files scanned, QNX-aware locations).

        `build_guards` come from the CMake scanner; `macros` are the C macros that the
        predicted QNX configure defines (or leaves undefined)."""
        files = list(iter_sources(root))
        rels = [f.relative_to(root).as_posix() for f in files]
        project_headers = set(rels)
        parsed: list[_Src] = []
        for f, rel in zip(files, rels, strict=True):
            try:
                src = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            code, strings = strip_code(src)
            parsed.append(_Src(rel, src, code, strings, guard_frames(code, src)))
        defined = self._project_definitions(parsed)

        def has_include(h: str) -> bool | None:
            if self._in_project(h, project_headers):
                return True
            return None if self.sdp is None else self.sdp.has_header(h)

        base = target_macros(self.arch)
        closed = self.sdp is not None and bool(self.sdp.predefined_c)
        if self.sdp is not None and closed:
            base.update(sdp_macros(self.sdp.predefined_c, self.sdp.predefined_cxx))
        base.update(macros or {})
        hdr_macros = self.sdp.header_macros if self.sdp is not None else set()
        self.cexpr = CExpr(base, has_include, closed=closed, header_macros=hdr_macros)
        self._frame_cache = {}
        self._shared: tuple[CExpr, dict[str, bool | None]] = (
            self.cexpr.derive({**self._project_macros(parsed, base), **base}), {})
        self._ctx: dict[str, tuple[CExpr, dict[str, bool | None]]] = {}
        file_guards = self._file_guards(parsed, build_guards or {})
        findings: list[Finding] = []
        qnx_aware: list[str] = []
        for ps in parsed:
            self._enter(ps)
            findings += self._scan_file(ps, project_headers, defined, file_guards.get(ps.rel),
                                        qnx_aware)
        return findings, len(files), qnx_aware

    # ---- guards ---------------------------------------------------------------------------
    def _enter(self, ps: _Src) -> None:
        """Use this file's view of the macros: names it #defines itself (outside an
        include guard) are unknown here, since the file may define them before use."""
        if ps.rel not in self._ctx:
            shared, cache = self._shared
            local = {m.group(1) for m in _DEFINE.finditer(ps.code)} - shared.macros.keys()
            if local:
                self._ctx[ps.rel] = (shared.derive({**shared.macros,
                                                    **dict.fromkeys(local, None)}), {})
            else:
                self._ctx[ps.rel] = (shared, cache)
        self.cexpr, self._frame_cache = self._ctx[ps.rel]

    def _frame_state(self, f: Frame) -> bool | None:
        """True: this #if branch is compiled on QNX; False: it is not; None: unknown."""
        if f.cond not in self._frame_cache:
            self._frame_cache[f.cond] = self.cexpr.eval(f.cond)
        v = self._frame_cache[f.cond]
        return None if v is None else v != f.negated

    def line_guard(self, frames: tuple[Frame, ...], names: tuple[str, ...] = ()) -> str:
        """Guard from the preprocessor: evaluated #if first, name heuristics for the rest."""
        states = [self._frame_state(f) for f in frames]
        dead = tuple(f for f, st in zip(frames, states, strict=True) if st is False)
        if dead:
            g = classify_guard(dead, names)
            return g if g in ("linux", "other-os", "qnx") else "config-off"
        for f, st in zip(frames, states, strict=True):
            if st and any(ident_kind(m.group(0)) == "qnx" for m in _IDENT.finditer(f.cond)):
                return "qnx"
        unknown = tuple(f for f, st in zip(frames, states, strict=True) if st is None)
        return classify_guard(unknown, names)

    def _file_guards(self, parsed: list[_Src], build_guards: dict[str, str]) -> dict[str, str]:
        """Guard of each file: from an OS-specific path, from the build system, or - for a
        header - inherited when no place that QNX compiles includes it."""
        own: dict[str, str] = {}
        for ps in parsed:
            g = path_guard(ps.rel)
            if g == "none":
                g = arch_guard(ps.rel, self.arch)
            if g == "none":
                g = build_guard_for(ps.rel, build_guards) or "none"
            own[ps.rel] = g
        by_name: dict[str, list[str]] = {}
        for r in own:
            by_name.setdefault(r.rsplit("/", 1)[-1], []).append(r)

        def resolve(inc_rel: str, header: str) -> list[str]:
            cand = posixpath.normpath(posixpath.join(posixpath.dirname(inc_rel), header))
            if cand in own:
                return [cand]
            return [r for r in by_name.get(header.rsplit("/", 1)[-1], [])
                    if r == header or r.endswith("/" + header)]

        sites: dict[str, list[tuple[str, str]]] = {}  # header -> [(includer, line guard)]
        for ps in parsed:
            self._enter(ps)
            for idx, raw in enumerate(ps.src.split("\n")):
                m = _INCLUDE.match(raw) if "include" in raw else None
                if not m:
                    continue
                fr = ps.frames[idx] if idx < len(ps.frames) else ()
                for t in resolve(ps.rel, m.group(2).strip()):
                    if t != ps.rel:
                        sites.setdefault(t, []).append((ps.rel, self.line_guard(fr)))

        def is_header(r: str) -> bool:
            return Path(r).suffix.lower() in _HEADER_EXTS

        live = {r for r, g in own.items()
                if g not in DEAD_GUARDS and (r not in sites or not is_header(r))}
        changed = True
        while changed:  # least fixed point: a header is live if a live file includes it
            changed = False
            for h, ss in sites.items():
                if h in live or own.get(h) in DEAD_GUARDS or not is_header(h):
                    continue
                if any(inc in live and lg not in DEAD_GUARDS for inc, lg in ss):
                    live.add(h)
                    changed = True
        out = {r: g for r, g in own.items() if g != "none"}
        for h, ss in sites.items():
            if h not in live and h not in out:
                inc, lg = ss[0]
                out[h] = lg if lg in DEAD_GUARDS else out.get(inc, "config-off")
        return out

    # -------------------------------------------------------------------------------------
    def _names_re(self, kind: str, names: dict[str, Rule], code: str) -> re.Pattern[str] | None:
        """Regex for the KB names that occur in `code` (substring prefilter, then a small
        cached alternation): much faster than one alternation of every name."""
        present = tuple(sorted(n for n in names if n in code))
        if not present:
            return None
        key = (kind, present)
        if key not in self._re_cache:
            alt = _alternation(list(present))
            if kind == "call":
                pat = rf"(?<![\w.>:])({alt})\s*\("
            elif kind == "defn":
                pat = rf"^[A-Za-z_][\w\s\*]*?\b({alt})\s*\([^;{{]*\)\s*\{{"
            else:
                pat = rf"\b({alt})\b"
            self._re_cache[key] = re.compile(pat, re.M)
        return self._re_cache[key]

    def _project_definitions(self, parsed: list[_Src]) -> set[str]:
        """Names of KB functions the project defines or declares itself (shims, wrappers,
        C++ methods such as clone()): calls to these are not Linux API calls."""
        if not self.by_func:
            return set()
        found: set[str] = set()
        for ps in parsed:
            decl = self._names_re("call", self.by_func, ps.code)
            defn = self._names_re("defn", self.by_func, ps.code)
            if decl is None or defn is None:
                continue
            found.update(m.group(1) for m in defn.finditer(ps.code))
            for m in decl.finditer(ps.code):
                if m.group(1) not in found and _is_declaration(ps.code, m.start()):
                    found.add(m.group(1))
        return found

    def _project_macros(self, parsed: list[_Src], base: dict[str, Value]) -> dict[str, Value]:
        """Object-like macros the project's own headers #define (platform detection such as
        `#elif defined(__linux__)  #define EFSW_OS EFSW_OS_LINUX`), evaluated for QNX.
        Defines in .c files are local to that file and are not used."""
        sites: dict[str, list[tuple[tuple[Frame, ...], str]]] = {}
        include_guards: dict[str, Value] = {}
        for ps in parsed:
            if Path(ps.rel).suffix.lower() not in _HEADER_EXTS or area_of(ps.rel) != "lib":
                continue
            for idx, line in enumerate(ps.code.split("\n")):
                m = _DEFINE.match(line)
                if not m or m.group(2) or m.group(1) in base:
                    continue  # function-like, or a predefined / build-system macro
                name, value = m.group(1), m.group(3).strip()
                fr = ps.frames[idx] if idx < len(ps.frames) else ()
                if value.endswith("\\"):
                    value = "\x00"  # multi-line value: unknown
                guard = re.compile(rf"defined\s*\(?\s*{re.escape(name)}\b")
                if not value and any(guard.search(f.cond) for f in fr):
                    # include guard (#ifndef X_H / #define X_H): seen from the first
                    # inclusion it is not defined yet, so the header body is compiled
                    include_guards[name] = UNDEF
                    continue
                sites.setdefault(name, []).append((fr, value))
        macros: dict[str, Value] = {}
        root_cexpr = self.cexpr
        for _ in range(4):  # definitions depend on other definitions
            env = {**include_guards, **macros, **base}
            self.cexpr = root_cexpr.derive(env)
            self._frame_cache = {}
            new: dict[str, Value] = {}
            for name, ss in sites.items():
                values: set[str] = set()
                unknown = False
                # `#ifndef X / #define X default`: evaluate with X not yet defined
                selfref = re.compile(rf"\b{re.escape(name)}\b")
                own = root_cexpr.derive({**env, name: UNDEF})
                for fr, value in ss:
                    st: bool | None = True
                    for f in fr:
                        if selfref.search(f.cond):
                            v = own.eval(f.cond)
                            s = None if v is None else v != f.negated
                        else:
                            s = self._frame_state(f)
                        st = False if s is False else (None if s is None or st is None
                                                       else st)
                        if st is False:
                            break
                    if st is None:
                        unknown = True
                    elif st:
                        values.add(value)
                if unknown or len(values) > 1 or "\x00" in values:
                    new[name] = None
                elif values:
                    new[name] = values.pop()
                else:
                    new[name] = UNDEF
            if new == macros:
                break
            macros = new
        out: dict[str, Value] = dict(include_guards)
        out.update({k: v for k, v in macros.items() if v is not None})
        return out

    def _header_rule(self, header: str) -> Rule | None:
        if header in self.by_header:
            return self.by_header[header]
        for prefix, rule in self.prefix_rules:
            if header.startswith(prefix):
                return rule
        return None

    def _in_project(self, header: str, project_headers: set[str]) -> bool:
        if not self._suffixes:  # every path suffix of every project file, built once
            for p in project_headers:
                parts = p.split("/")
                self._suffixes.update("/".join(parts[i:]) for i in range(len(parts)))
        return header in self._suffixes

    def _scan_file(
        self,
        ps: _Src,
        project_headers: set[str],
        defined: set[str],
        file_guard: str | None,
        qnx_aware: list[str],
    ) -> list[Finding]:
        rel, src, code, strings, frames = ps.rel, ps.src, ps.code, ps.strings, ps.frames
        raw_lines = src.split("\n")
        code_lines = code.split("\n")
        area = area_of(rel)
        out: list[Finding] = []

        def guard_at(line_no: int, names: tuple[str, ...] = ()) -> str:
            fr = frames[line_no - 1] if 0 < line_no <= len(frames) else ()
            g = self.line_guard(fr, names)
            return file_guard if g == "none" and file_guard else g

        def add(rule: Rule, name: str, kind: str, line_no: int, detail: str = "") -> None:
            names = (*rule.identifiers, *rule.functions, *rule.headers, rule.id, name)
            g = guard_at(line_no, names)
            out.append(Finding(rule.id, name, kind, rel, line_no, area, g, detail))

        if re.search(r"\b(__QNX__|__QNXNTO__)\b", code):
            qnx_aware.append(rel)

        # includes (path taken from the raw line: string contents are blanked in `code`)
        for idx, cl in enumerate(code_lines):
            if "include" not in cl or not cl.lstrip().startswith("#"):
                continue
            m = _INCLUDE.match(raw_lines[idx]) if idx < len(raw_lines) else None
            if not m:
                continue
            quote, header = m.group(1), m.group(2).strip()
            rule = self._header_rule(header)
            if (rule is not None and self.sdp is not None and self.sdp.has_header(header)
                    and rule.severity in ("fix", "blocker") and not rule.link):
                continue  # your SDP has this header: nothing to port
            if rule is not None:
                detail = rule.header_map.get(header, "")
                add(rule, header, "include", idx + 1, f"use <{detail}>" if detail else "")
            elif quote == "<" and self.sdp is not None:
                if self._in_project(header, project_headers) or self.sdp.has_header(header):
                    continue
                top = header.split("/")[0] if "/" in header else ""
                rid = "header-absent" if (not top or top in _SYSTEM_DIRS) else "third-party-dep"
                if rid in self.kb.rules:
                    add(self.kb.rule(rid), header, "include", idx + 1,
                        "not found in the QNX SDP or the project")

        # function calls
        func_re = self._names_re("call", self.by_func, code)
        if func_re is not None:
            for m in func_re.finditer(code):
                name = m.group(1)
                if name in defined:
                    continue
                rule = self.by_func[name]
                line_no = code.count("\n", 0, m.start()) + 1
                if code_lines[line_no - 1].lstrip().startswith("#"):
                    continue  # inside a macro definition / directive line
                detail = rule.hints.get(name, "")
                if self.sdp is not None:
                    detail = self._availability(rule, name, detail)
                    if detail == "AVAILABLE":
                        continue  # your SDP has it where the rule expects nothing extra
                add(rule, name, "call", line_no, detail)

        # identifiers (macros, types, errno names), with per-file conditions
        ident_re = self._names_re("ident", self.by_ident, code)
        if ident_re is not None:
            for m in ident_re.finditer(code):
                name = m.group(1)
                rule = self.by_ident[name]
                if rule.requires_in_file and not any(
                    re.search(rf"\b{re.escape(t)}\b", code) for t in rule.requires_in_file
                ):
                    continue
                if rule.absent_in_file and any(
                    re.search(rf"\b{re.escape(t)}\b", code) for t in rule.absent_in_file
                ):
                    continue
                line_no = code.count("\n", 0, m.start()) + 1
                add(rule, name, "identifier", line_no, rule.hints.get(name, ""))

        # string literals
        for line_no, text in strings:
            for needle, rule in self.string_rules:
                if needle in text:
                    add(rule, needle, "string", line_no, text[:60])
        return out

    def _availability(self, rule: Rule, name: str, hint: str) -> str:
        """Refine a call finding with the SDP facts. Returns 'AVAILABLE' when the SDP
        provides the symbol in libc and the rule is only about absence."""
        assert self.sdp is not None
        flag = self.sdp.link_flag_for(name)
        if rule.link:  # link rules: report which library provides it
            return f"in {self.sdp.libs_for(name)[0]} ({rule.link})" if flag else hint
        if flag is None:
            return hint or "absent from the QNX SDP"
        if flag == "":
            return "AVAILABLE" if rule.severity in ("fix", "blocker") else hint
        return f"available in {self.sdp.libs_for(name)[0]} (link {flag})"
