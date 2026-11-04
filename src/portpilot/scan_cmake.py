"""Scan CMake files for configure checks and link settings that misbehave on QNX.

The key insight (ground truth F-004/F-011): CMake feature checks *link* a test program.
On QNX many POSIX functions live outside libc (libsocket, libregex) and libpthread/librt/
libdl do not exist, so checks fail and features are silently compiled out.

The scanner also feeds the configure model (configure.py), which predicts each check's
result on QNX and therefore which sources and #if-blocks QNX really compiles.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

from .configure import (
    CHECK_RESULT_ARG,
    LIBC_ONLY_LIBS,
    Configure,
    ConfigureModel,
    HeaderGrep,
    Prediction,
    predict_check,
)
from .cpp_text import ident_kind, tokens
from .kb import KnowledgeBase
from .models import Finding
from .scan_source import _BUILD_DIR, SKIP_DIRS, area_of
from .sdp_index import SdpIndex

# check -> (symbol arg index, header arg index or None, library arg index or None)
_CHECK_POS = {
    "check_function_exists": (0, None, None),
    "check_symbol_exists": (0, 1, None),
    "check_cxx_symbol_exists": (0, 1, None),
    "check_library_exists": (1, None, 0),
    "check_include_file": (0, None, None),
    "check_include_file_cxx": (0, None, None),
    "check_include_files": (0, None, None),
}
_INCLUDE_CHECKS = {"check_include_file", "check_include_file_cxx", "check_include_files"}
_DEFINE_CMDS = {"add_definitions", "add_compile_definitions", "target_compile_definitions"}
_SCOPES = {"PRIVATE", "PUBLIC", "INTERFACE", "BEFORE", "AFTER", "SYSTEM"}
_LINUX_COND = re.compile(
    r'(\bLINUX\b|CMAKE_SYSTEM_NAME\}?\s+(?:STREQUAL|MATCHES)\s+"?\^?Linux|'
    r'CMAKE_HOST_SYSTEM_NAME\}?\s+(?:STREQUAL|MATCHES)\s+"?\^?Linux)'
)
_SRC_FILE = re.compile(r"[\w./+-]+\.(c|cc|cpp|cxx|c\+\+)$", re.I)
_MACRO_NAME = re.compile(r"[A-Za-z_]\w*")
# commands that assign variables PortPilot does not model: mark the outputs unknown
_OUT_ARGS = {
    "find_library": (0,), "find_path": (0,), "find_program": (0,), "find_file": (0,),
    "get_filename_component": (0,), "get_property": (0,), "get_target_property": (0,),
    "get_directory_property": (0,), "math": (1,), "try_compile": (0,), "try_run": (0, 1),
    "file": (1, 2), "list": (1, -1), "string": (1, 2, 3, 4, -1), "foreach": (0,),
}
DEAD_BUILD_GUARDS = {"config-off", "build-linux", "build-other-os", "build-feature",
                     "build-optional"}

Conds = tuple[tuple[str, bool], ...]


@dataclass
class Command:
    name: str  # lower-cased
    args: list[str]
    line: int
    # enclosing if()/elseif()/else() conditions, outermost first: (condition, taken-when-true).
    # In an else-branch the condition appears with False.
    conds: Conds
    chain: int = 0  # id of the if/elseif/else chain this command belongs to (if-commands)
    in_body: bool = False  # inside a function()/macro() definition


@dataclass
class CMakeInfo:
    findings: list[Finding] = field(default_factory=list)
    build_guards: dict[str, str] = field(default_factory=dict)  # basename | 'dir:<p>/'
    qnx_aware: list[str] = field(default_factory=list)
    linked: set[str] = field(default_factory=set)  # libraries the project links or probes
    configure: Configure | None = None


def _strip_comments(text: str) -> str:
    text = re.sub(r"#\[(=*)\[.*?\]\1\]", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    out = []
    for line in text.split("\n"):
        in_q = False
        for i, ch in enumerate(line):
            if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                in_q = not in_q
            elif ch == "#" and not in_q:
                line = line[:i]
                break
        out.append(line)
    return "\n".join(out)


def _split_args(s: str) -> list[str]:
    """Split command arguments; quotes are removed, an empty "" argument is kept."""
    args, cur, in_q, quoted = [], "", False, False
    for ch in s:
        if ch == '"':
            in_q = not in_q
            quoted = True
            continue
        if ch.isspace() and not in_q:
            if cur or quoted:
                args.append(cur)
                cur, quoted = "", False
        else:
            cur += ch
    if cur or quoted:
        args.append(cur)
    return args


_CMD = re.compile(r"\b([A-Za-z_]\w*)\s*\(")


def parse_commands(text: str) -> list[Command]:
    """Tokenize CMake into top-level commands (balanced parentheses), tracking if/else."""
    text = _strip_comments(text)
    cmds: list[Command] = []
    chains: list[tuple[list[str], bool, int]] = []  # (conditions so far, in else, chain id)
    next_chain = 0
    body_depth = 0
    pos, line = 0, 1
    while (m := _CMD.search(text, pos)) is not None:
        depth, j, in_q = 1, m.end(), False
        while j < len(text) and depth:
            ch = text[j]
            if ch == '"' and text[j - 1] != "\\":
                in_q = not in_q
            elif not in_q:
                depth += ch == "("
                depth -= ch == ")"
            j += 1
        line += text.count("\n", pos, m.start())
        name = m.group(1).lower()
        inner = text[m.end() : j - 1]
        args = _split_args(inner)
        # conditions keep their quotes: a quoted "QNX" is a string, an unquoted QNX is the
        # variable QNX (CMake policy CMP0054)
        cond_text = " ".join(inner.split())
        chain_id = 0
        if name == "if":
            next_chain += 1
            chains.append(([cond_text], False, next_chain))
            chain_id = next_chain
        elif name == "elseif" and chains:
            conds, _, cid = chains[-1]
            chains[-1] = ([*conds, cond_text], False, cid)
            chain_id = cid
        elif name == "else" and chains:
            conds, _, cid = chains[-1]
            chains[-1] = (conds, True, cid)
            chain_id = cid
        elif name == "endif" and chains:
            chain_id = chains.pop()[2]
        active: list[tuple[str, bool]] = []
        for conds, in_else, _ in chains:
            *prev, cur = conds
            active += [(c, False) for c in prev]
            active.append((cur, not in_else))
        if name in ("if", "elseif", "else"):
            active = active[:-1]  # the command's own frame
        if name in ("endfunction", "endmacro"):
            body_depth = max(0, body_depth - 1)
        cmds.append(Command(name, args, line, tuple(active), chain_id, body_depth > 0))
        if name in ("function", "macro"):
            body_depth += 1
        line += text.count("\n", m.start(), j)
        pos = j
    return cmds


def iter_cmake_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not _BUILD_DIR.match(d))
        for fn in sorted(filenames):
            if fn == "CMakeLists.txt" or fn.endswith(".cmake"):
                yield Path(dirpath, fn)


# ---- project-defined wrappers -------------------------------------------------------------
@dataclass
class _Wrapper:
    kind: str  # "check" | "define" | "plain"
    params: list[str]
    check: str = ""  # the check_* command it forwards to
    templates: list[str] = field(default_factory=list)  # the check's arguments in the body

    def resolve(self, call_args: list[str]) -> list[str]:
        mapping = {p: (call_args[i] if i < len(call_args) else "")
                   for i, p in enumerate(self.params)}
        mapping["ARGN"] = ";".join(call_args[len(self.params):])

        def sub(t: str) -> str:
            return re.sub(r"\$\{(\w+)\}", lambda m: mapping.get(m.group(1), m.group(0)), t)

        return [sub(t) for t in self.templates]


def _find_wrappers(all_cmds: list[list[Command]]) -> dict[str, _Wrapper]:
    """function(nng_check_func SYM DEF) check_function_exists(${SYM} ${DEF}) -> wrapper."""
    wrappers: dict[str, _Wrapper] = {}
    for cmds in all_cmds:
        i = 0
        while i < len(cmds):
            c = cmds[i]
            if c.name in ("function", "macro") and c.args:
                wname, params = c.args[0].lower(), c.args[1:]
                end = "end" + c.name
                body: list[Command] = []
                j = i + 1
                while j < len(cmds) and cmds[j].name != end:
                    body.append(cmds[j])
                    j += 1
                w = _Wrapper("plain", params)
                check = next((b for b in body if b.name in CHECK_RESULT_ARG), None)
                if check is not None and any("${" in a for a in check.args):
                    w = _Wrapper("check", params, check.name, check.args)
                elif any(b.name in _DEFINE_CMDS for b in body):
                    w = _Wrapper("define", params)
                wrappers.setdefault(wname, w)
                i = j
            i += 1
    return wrappers


def _guard_from_conds(conds: Conds) -> str:
    """Name-based guard of code under these if()-conditions, seen from QNX:
    qnx | build-linux | build-other-os | build-feature (HAVE_X detected) |
    build-optional (user option / engine choice) | none."""
    rank = {"none": 0, "build-optional": 1, "build-feature": 2, "build-other-os": 3,
            "build-linux": 4}
    kind = "none"
    for cond, taken in conds:
        words = cond.replace("(", " ( ").replace(")", " ) ").split()
        for i, w in enumerate(words):
            for ident in re.findall(r"[A-Za-z_]\w*", w):
                k = ident_kind(ident)
                if k == "qnx":
                    return "qnx"
                negated = i > 0 and words[i - 1].upper() == "NOT"
                if taken == negated:  # this branch runs when `ident` is false
                    continue
                toks = set(tokens(ident))
                new = "none"
                if k == "linux":
                    new = "build-linux"
                elif k == "other-os":
                    new = "build-other-os"
                elif toks & {"have", "has"}:
                    new = "build-feature"
                elif toks & {"enable", "use", "with", "build", "tests", "testing",
                             "examples", "engine"}:
                    new = "build-optional"
                if rank[new] > rank[kind]:
                    kind = new
        if kind == "none" and taken and re.search(r"\b(STREQUAL|MATCHES)\b", cond):
            kind = "build-optional"
    return kind


class CMakeScanner:
    def __init__(self, kb: KnowledgeBase, sdp: SdpIndex | None = None,
                 qnx_target: Path | None = None, arch: str = "x86_64",
                 qnx_host: Path | None = None, defines: dict[str, str] | None = None) -> None:
        self.kb = kb
        self.sdp = sdp
        self.grep = HeaderGrep(qnx_target, qnx_host, arch)
        self.arch = arch
        self.defines = dict(defines or {})  # cmake -D values the port passes

    def scan(self, root: Path) -> CMakeInfo:
        parsed: list[tuple[str, list[Command]]] = []
        for path in iter_cmake_files(root):
            try:
                parsed.append((path.relative_to(root).as_posix(), parse_commands(
                    path.read_text(encoding="utf-8", errors="replace"))))
            except OSError:
                continue
        wrappers = _find_wrappers([c for _, c in parsed])
        required_libs = self._required_libs(parsed)
        required_libs |= {x for x in self.defines.get("CMAKE_REQUIRED_LIBRARIES", "").split(";")
                          if x}
        model = ConfigureModel(self.arch, self.defines)
        info = CMakeInfo()
        predictions: list[Prediction] = []
        pending: list[tuple[Finding, Conds, str]] = []  # (finding, conds, guard style)
        sources: list[tuple[str, Conds]] = []  # (build-guard key, conds)
        qnx_chains = {(rel, c.chain) for rel, cmds in parsed for c in cmds
                      if c.name in ("if", "elseif") and re.search(r"\bQNX", " ".join(c.args))}

        for rel, cmds in parsed:
            area = area_of(rel)
            base = rel.rsplit("/", 1)[0] + "/" if "/" in rel else ""
            for c in cmds:
                if any(re.search(r"\bQNX\b", a) for a in c.args):
                    info.qnx_aware.append(f"{rel}:{c.line}")
                if c.in_body:
                    if c.name in ("set", "option", "list", "unset") and c.args:
                        model.maybe.add(c.args[1] if c.name == "list" and len(c.args) > 1
                                        else c.args[0])
                    continue
                conds, args = c.conds, c.args
                w = wrappers.get(c.name)
                if w is not None and c.name.endswith("_if") and args:
                    conds, args = (*conds, (args[0], True)), args[1:]
                self._model(c.name, args, conds, model)

                # compile definitions -> C macros
                if c.name in _DEFINE_CMDS or (w is not None and w.kind == "define"):
                    defs = args[1:] if c.name == "target_compile_definitions" else args
                    for d in defs:
                        name, _, val = d.removeprefix("-D").partition("=")
                        if (d.startswith("-D") or c.name != "add_definitions") and \
                                _MACRO_NAME.fullmatch(name) and name not in _SCOPES:
                            model.add_macro(name, conds, val or "1")

                # sources and subdirectories (guards are decided after the solve)
                if c.name == "add_subdirectory" and args:
                    sources.append((f"dir:{base}{args[0].strip('/')}/", conds))
                else:
                    for a in args:
                        if _SRC_FILE.search(a) and "${" not in a.split("/")[-1]:
                            sources.append((os.path.basename(a), conds))
                        elif re.fullmatch(r"[A-Za-z_][\w-]*", a) and a not in _SCOPES:
                            # nng_test(foo) / add_executable(foo ...) -> <dir>/foo.c
                            sources.append((f"stem:{base}{a}", conds))

                info.linked |= self._linked_libs(c.name, args)
                for f in self._link_findings(c.name, args, rel, c.line, area):
                    pending.append((f, conds, "check"))
                cond = " ".join(args)
                if c.name in ("if", "elseif") and _LINUX_COND.search(cond) and not re.match(
                    r"\s*NOT\b", cond
                ) and (rel, c.chain) not in qnx_chains:
                    pending.append((Finding("cmake-linux-branch", cond[:80], "cmake-branch",
                                            rel, c.line, area, "none"), (), "check"))

                # configure checks (direct or through a project wrapper)
                check, cargs = (c.name, args) if c.name in CHECK_RESULT_ARG else ("", args)
                if not check and w is not None and w.kind == "check":
                    check, cargs = w.check, w.resolve(c.args)
                    if w.check == "check_library_exists" and cargs:
                        info.linked.add(cargs[0])
                if not check:
                    continue
                ri = CHECK_RESULT_ARG[check]
                var = cargs[ri] if ri < len(cargs) else ""
                value, reason = predict_check(check, cargs, self.sdp, self.grep, required_libs)
                shown = " ".join(a for i, a in enumerate(cargs) if i != ri and a)
                if var and "${" not in var:
                    pred = Prediction(var, value, f"{check}({shown})", reason, rel, c.line)
                    predictions.append(pred)
                    model.add_check(pred, conds)
                if check in _CHECK_POS:
                    cf = self._check_finding(check, cargs, rel, c.line, area, required_libs)
                    if cf:
                        pending.append((cf, conds, "check"))

        configure = model.solve(predictions)
        info.configure = configure
        for f, conds, _ in pending:
            info.findings.append(replace(f, guard=self._final_guard(conds, configure, True)))
        per_key: dict[str, list[str]] = {}
        for key, conds in sources:
            per_key.setdefault(key, []).append(self._final_guard(conds, configure, False))
        for key, guards in per_key.items():
            if "none" in guards:
                continue  # built unconditionally somewhere
            info.build_guards[key] = guards[0]
        return info

    # ---- configure model --------------------------------------------------------------
    @staticmethod
    def _model(name: str, args: list[str], conds: Conds, model: ConfigureModel) -> None:
        if name == "set":
            model.add_set(args, conds)
        elif name == "option":
            model.add_option(args, conds)
        elif name == "cmake_dependent_option":
            model.add_dependent_option(args, conds)
        elif name == "unset":
            model.add_unset(args, conds)
        elif name == "execute_process":
            for i, a in enumerate(args[:-1]):
                if a.endswith("_VARIABLE"):
                    model.add_unknown(args[i + 1], conds)
        elif name in _OUT_ARGS and args:
            for i in _OUT_ARGS[name]:
                if -len(args) <= i < len(args) and _MACRO_NAME.fullmatch(args[i]):
                    model.add_unknown(args[i], conds)

    @staticmethod
    def _final_guard(conds: Conds, configure: Configure, is_finding: bool) -> str:
        """Guard for code under `conds`, using the predicted configure first."""
        h = _guard_from_conds(conds)
        v = configure.conds_true(conds) if conds else True
        if v is True:
            return "none"
        if v is False:
            if h in ("build-linux", "build-other-os", "qnx"):
                return {"build-linux": "linux", "build-other-os": "other-os"}.get(h, h) \
                    if is_finding else h
            return "config-off"
        if is_finding:  # a check inside an optional block still runs when enabled
            return {"build-linux": "linux", "build-other-os": "other-os", "qnx": "qnx"}.get(
                h, "none")
        return h

    # ---- helpers -----------------------------------------------------------------------
    @staticmethod
    def _required_libs(parsed: list[tuple[str, list[Command]]]) -> set[str]:
        libs: set[str] = set()
        for _, cmds in parsed:
            for c in cmds:
                if c.args and "CMAKE_REQUIRED_LIBRARIES" in c.args[:2]:
                    libs.update(a for a in c.args if a != "CMAKE_REQUIRED_LIBRARIES")
        return libs

    @staticmethod
    def _linked_libs(name: str, args: list[str]) -> set[str]:
        """Libraries a command makes the project link (or probe for linking)."""
        if name == "target_link_libraries":
            items = args[1:]
        elif name == "link_libraries":
            items = args
        elif name == "check_library_exists" and args:
            items = args[:1]
        elif name == "find_library" and "NAMES" in args:
            items = args[args.index("NAMES") + 1 :]
        else:
            return set()
        return {a[2:] if a.startswith("-l") else a for a in items
                if re.fullmatch(r"(-l)?[A-Za-z][\w+.-]*", a) and a not in _SCOPES}

    @staticmethod
    def _link_findings(name: str, args: list[str], rel: str, line: int,
                       area: str) -> list[Finding]:
        if name not in ("target_link_libraries", "link_libraries", "set", "list"):
            return []
        out = []
        for a in args[1:]:
            lib = a[2:] if a.startswith("-l") else a
            if lib in LIBC_ONLY_LIBS:
                out.append(Finding("link-libc-only", lib, "link", rel, line, area, "none",
                                   f"lib{lib} does not exist on QNX (in libc)"))
        return out

    def _check_finding(self, check: str, args: list[str], rel: str, line: int, area: str,
                       required_libs: set[str]) -> Finding | None:
        sym_i, hdr_i, lib_i = _CHECK_POS[check]
        if len(args) <= sym_i:
            return None
        sym = args[sym_i]
        if "${" in sym:
            return None

        def mk(rule: str, name: str, detail: str) -> Finding:
            return Finding(rule, name, "cmake-check", rel, line, area, "none", detail)

        if check == "check_library_exists":
            lib = args[lib_i] if lib_i is not None and lib_i < len(args) else ""
            if lib not in LIBC_ONLY_LIBS:
                return None
            if self.sdp is not None and not self.sdp.in_libc(sym):
                return mk("cmake-check-absent", f"{lib}:{sym}",
                          f"lib{lib} does not exist on QNX and {sym} is not in the QNX SDP")
            return mk("cmake-check-lib-in-libc", f"{lib}:{sym}",
                      f"lib{lib} does not exist on QNX; {sym} is in libc")
        if check in _INCLUDE_CHECKS:
            if self.sdp is not None:
                missing = [h for h in sym.split(";") if h and not self.sdp.has_header(h)]
                if missing:
                    return mk("cmake-check-absent", sym,
                              f"header {', '.join(missing)} absent on QNX")
            return None
        hdrs = args[hdr_i].split(";") if hdr_i is not None and hdr_i < len(args) else []
        # Known header-layout case (works without an SDP index): AF_INET6
        if sym == "AF_INET6" and hdrs and "sys/socket.h" not in hdrs:
            return mk("cmake-check-header-layout", f"AF_INET6 in {';'.join(hdrs)}",
                      "QNX defines AF_INET6 in <sys/socket.h> only")
        if self.sdp is None:
            return None
        libs = self.sdp.libs_for(sym)
        if libs:
            flag = self.sdp.link_flag_for(sym)
            if flag and flag[2:] not in required_libs:
                return mk("cmake-check-needs-libsocket", sym,
                          f"{sym} is in {libs[0]}: the check fails unless "
                          f"CMAKE_REQUIRED_LIBRARIES contains {flag[2:]}")
            return None
        if sym.isupper() or sym.startswith("_"):
            if not self.grep.available or not hdrs or self.grep.defines(sym, hdrs):
                return None
            return mk("cmake-check-absent", sym, f"{sym} is not defined via {';'.join(hdrs)} "
                      "on QNX")
        return mk("cmake-check-absent", sym,
                  f"{sym} is absent on QNX: the project's fallback will be used")
