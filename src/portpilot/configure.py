"""Predict what CMake's configure step decides when the target is QNX.

PortPilot does not run CMake. It reads the project's CMake files, predicts the result of
every configure check (check_symbol_exists, check_library_exists, ...) from facts in the
user's QNX SDP, then evaluates if()/set()/option() with three-valued logic
(True / False / unknown). The result tells the scanners which sources, directories and
#if-blocks are really compiled on QNX, so dead code (an epoll backend that QNX never
builds) is not reported as porting work.

Unknown stays unknown: anything PortPilot cannot decide falls back to name heuristics.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .sdp_index import SdpIndex

LIBC_ONLY_LIBS = {"pthread", "rt", "dl"}  # absent on QNX 8.0 (ground truth F-011)


class _Undef:
    """A variable known to be undefined (CMake treats it as false)."""

    def __repr__(self) -> str:
        return "UNDEF"


UNDEF = _Undef()
Value = str | _Undef | None  # None = unknown

TRUE_CONSTS = {"1", "ON", "YES", "TRUE", "Y"}
FALSE_CONSTS = {"0", "OFF", "NO", "FALSE", "N", "IGNORE", "NOTFOUND", ""}

# What CMake itself sets for a QNX target (QNX toolchain file + CMake platform module).
PLATFORM_UNDEF = (
    "WIN32", "WIN64", "MSVC", "MINGW", "CYGWIN", "MSYS", "APPLE", "IOS", "ANDROID", "LINUX",
    "BSD", "WINCE", "WINDOWS_PHONE", "WINDOWS_STORE", "EMSCRIPTEN", "XCODE", "BORLAND",
    "WATCOM", "SOLARIS", "HAIKU", "CMAKE_HOST_WIN32", "MSVC_VERSION",
)


def target_seed(arch: str = "x86_64") -> dict[str, Value]:
    proc = {"x86_64": "x86_64", "aarch64": "aarch64le", "aarch64le": "aarch64le"}.get(arch, arch)
    seed: dict[str, Value] = {
        "CMAKE_SYSTEM_NAME": "QNX",
        "CMAKE_SYSTEM_VERSION": "8.0.0",
        "CMAKE_SYSTEM_PROCESSOR": proc,
        "CMAKE_CROSSCOMPILING": "TRUE",
        "CMAKE_C_COMPILER_ID": "QCC",
        "CMAKE_CXX_COMPILER_ID": "QCC",
        "CMAKE_SIZEOF_VOID_P": "8",
        "QNX": "1",
        "QNXNTO": "1",
        "UNIX": "1",
    }
    for v in PLATFORM_UNDEF:
        seed[v] = UNDEF
    return seed


# ---- QNX predefined C macros (qcc -Vgcc_nto<arch>) ------------------------------------------
def target_macros(arch: str = "x86_64") -> dict[str, Value]:
    m: dict[str, Value] = {k: "1" for k in (
        "__QNX__", "__QNXNTO__", "__unix__", "__unix", "unix", "__ELF__", "__GNUC__")}
    m.update({k: UNDEF for k in (
        # gcc 12 has no __has_feature; sanitizers are off unless -fsanitize is given
        "__has_feature", "__SANITIZE_ADDRESS__", "__SANITIZE_THREAD__", "__clang__",
        "__linux__", "__linux", "linux", "__gnu_linux__", "__GLIBC__", "_WIN32", "_WIN64",
        "WIN32", "_MSC_VER", "__MINGW32__", "__MINGW64__", "__CYGWIN__", "__APPLE__",
        "__MACH__", "__FreeBSD__", "__NetBSD__", "__OpenBSD__", "__DragonFly__", "__sun",
        "__ANDROID__", "__EMSCRIPTEN__", "__HAIKU__", "_AIX", "__hpux", "__Fuchsia__")})
    if arch == "x86_64":
        m.update({"__x86_64__": "1", "__x86_64": "1", "__aarch64__": UNDEF})
    else:
        m.update({"__aarch64__": "1", "__x86_64__": UNDEF, "__x86_64": UNDEF})
    # gcc 12 operators usable in `#if defined(...)`
    m.update({k: "1" for k in ("__has_include", "__has_include_next", "__has_attribute",
                               "__has_cpp_attribute", "__has_builtin")})
    return m


def sdp_macros(predefined_c: dict[str, str], predefined_cxx: dict[str, str]
               ) -> dict[str, Value]:
    """Exact predefined macros from the SDP's qcc. Macros that only C++ defines
    (__cplusplus, __cpp_*) depend on the file's language: unknown."""
    m: dict[str, Value] = dict(predefined_c)
    for k in predefined_cxx:
        if k not in predefined_c:
            m[k] = None
    return m


# Reserved identifiers: only the compiler or system headers may define these.
_RESERVED = re.compile(r"_[_A-Z]\w*")


def truthy(value: str) -> bool:
    """Truth of a variable's value in if(<variable>)."""
    u = value.upper()
    return not (u in FALSE_CONSTS or u.endswith("-NOTFOUND"))


def k_and(a: bool | None, b: bool | None) -> bool | None:
    if a is False or b is False:
        return False
    return True if (a and b) else None


def k_or(a: bool | None, b: bool | None) -> bool | None:
    if a is True or b is True:
        return True
    return False if (a is False and b is False) else None


def k_not(a: bool | None) -> bool | None:
    return None if a is None else not a


# ---- CMake condition evaluation ------------------------------------------------------------
_BINOPS = {
    "STREQUAL", "STRLESS", "STRGREATER", "STRLESS_EQUAL", "STRGREATER_EQUAL", "EQUAL", "LESS",
    "GREATER", "LESS_EQUAL", "GREATER_EQUAL", "MATCHES", "VERSION_EQUAL", "VERSION_LESS",
    "VERSION_GREATER", "VERSION_LESS_EQUAL", "VERSION_GREATER_EQUAL", "IN_LIST", "PATH_EQUAL",
}
_UNARY = {"DEFINED", "EXISTS", "COMMAND", "TARGET", "POLICY", "IS_DIRECTORY", "IS_ABSOLUTE",
          "IS_SYMLINK", "IS_READABLE", "IS_WRITABLE", "IS_EXECUTABLE"}
_VARLIKE = re.compile(r"[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+")
_REF = re.compile(r"\$\{(\w+)\}")
_COND_TOK = re.compile(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()"]+(?:"[^"]*"[^\s()"]*)*')


def _version(s: str) -> tuple[int, ...] | None:
    parts = re.findall(r"\d+", s)
    return tuple(int(p) for p in parts) if parts else None


# Variables that come from outside the project's own CMake code: CMake itself, the user's
# command line, or find_package(). Never assume these are undefined.
_EXTERNAL = re.compile(r"^(CMAKE_|PROJECT_|BUILD_|ENV\{)|_(FOUND|LIBRARIES|LIBRARY|LIBS|"
                       r"INCLUDE_DIRS?|DIR|VERSION\w*|EXECUTABLE|TARGETS?|SOURCE_DIR|"
                       r"BINARY_DIR|IS_TOP_LEVEL)$")


class Env:
    """Variable values as CMake would see them on QNX (three-valued)."""

    def __init__(self, values: dict[str, Value], maybe: set[str] | None = None) -> None:
        self.values = values
        self.maybe = maybe or set()  # assigned inside functions/macros: not modelled

    def external(self, name: str) -> bool:
        return name in self.maybe or _EXTERNAL.search(name) is not None

    def lookup(self, name: str) -> Value:
        if name in self.values:
            return self.values[name]
        # never assigned by the project: undefined, as CMake would see it - unless it is
        # the kind of variable set from outside (cache, -D, find_package)
        return None if self.external(name) else UNDEF

    def expand(self, text: str) -> str | None:
        unknown = False

        def rep(m: re.Match[str]) -> str:
            nonlocal unknown
            v = self.lookup(m.group(1))
            if v is None:
                unknown = True
                return ""
            return "" if isinstance(v, _Undef) else v

        out = _REF.sub(rep, text)
        return None if unknown else out

    # if(<word>) -------------------------------------------------------------------------
    def bool_of(self, tok: str) -> bool | None:
        if len(tok) >= 2 and tok[0] == tok[-1] == '"':
            # quoted: never a variable name (CMP0054); true only for a true constant
            s = self.expand(tok[1:-1])
            if s is None:
                return None
            u = s.upper()
            if u in TRUE_CONSTS:
                return True
            try:
                return float(s) != 0
            except ValueError:
                return False
        if "${" in tok:
            s = self.expand(tok)
            if s is None:
                return None
            tok = s
        u = tok.upper()
        if u in TRUE_CONSTS:
            return True
        if u in FALSE_CONSTS or u.endswith("-NOTFOUND"):
            return False
        try:
            return float(tok) != 0
        except ValueError:
            pass
        v = self.lookup(tok)
        if v is None:
            return None
        return False if isinstance(v, _Undef) else truthy(v)

    def operand(self, tok: str) -> str | None:
        """Left/right side of a binary operator: unquoted variable names are dereferenced,
        quoted strings are literal (with ${} expanded)."""
        if len(tok) >= 2 and tok[0] == tok[-1] == '"':
            return self.expand(tok[1:-1])
        if "${" in tok:
            return self.expand(tok)
        if tok in self.values:
            v = self.values[tok]
            if v is None:
                return None
            # an undefined variable name is compared as the literal word (CMake rule)
            return tok if isinstance(v, _Undef) else v
        if _VARLIKE.fullmatch(tok) and self.external(tok):
            return None
        return tok

    def eval(self, cond: str) -> bool | None:
        toks = _COND_TOK.findall(cond)
        if not toks:
            return False
        p = _CondParser(toks, self)
        try:
            v = p.parse_or()
        except (IndexError, re.error, ValueError):
            return None
        return v if p.i == len(toks) else None


class _CondParser:
    def __init__(self, toks: list[str], env: Env) -> None:
        self.t = toks
        self.i = 0
        self.env = env

    def peek(self) -> str | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> str:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def parse_or(self) -> bool | None:
        v = self.parse_and()
        while self.peek() == "OR":
            self.take()
            v = k_or(v, self.parse_and())
        return v

    def parse_and(self) -> bool | None:
        v = self.parse_not()
        while self.peek() == "AND":
            self.take()
            v = k_and(v, self.parse_not())
        return v

    def parse_not(self) -> bool | None:
        if self.peek() == "NOT":
            self.take()
            return k_not(self.parse_not())
        return self.parse_cmp()

    def parse_cmp(self) -> bool | None:
        tok = self.take()
        if tok == "(":
            v = self.parse_or()
            if self.take() != ")":
                raise ValueError("unbalanced")
            return v
        if tok in _UNARY:
            arg = self.take()
            if tok == "DEFINED":
                if arg.startswith(("ENV{", "CACHE{")):
                    return None
                val = self.env.lookup(arg)
                return None if val is None else not isinstance(val, _Undef)
            return None
        if self.peek() in _BINOPS:
            op = self.take()
            right = self.take()
            return self._binop(tok, op, right)
        return self.env.bool_of(tok)

    def _binop(self, left_tok: str, op: str, right_tok: str) -> bool | None:
        if op == "IN_LIST":
            item = self.env.operand(left_tok)
            lst = self.env.lookup(right_tok)
            if item is None or lst is None:
                return None
            return False if isinstance(lst, _Undef) else item in lst.split(";")
        a, b = self.env.operand(left_tok), self.env.operand(right_tok)
        if a is None or b is None:
            return None
        if op == "STREQUAL":
            return a == b
        if op == "MATCHES":
            return re.search(b, a) is not None
        if op.startswith("STR"):
            return {"STRLESS": a < b, "STRGREATER": a > b, "STRLESS_EQUAL": a <= b,
                    "STRGREATER_EQUAL": a >= b}[op]
        if op.startswith("VERSION_"):
            va, vb = _version(a), _version(b)
            if va is None or vb is None:
                return None
            n = max(len(va), len(vb))
            va, vb = va + (0,) * (n - len(va)), vb + (0,) * (n - len(vb))
            return {"VERSION_EQUAL": va == vb, "VERSION_LESS": va < vb,
                    "VERSION_GREATER": va > vb, "VERSION_LESS_EQUAL": va <= vb,
                    "VERSION_GREATER_EQUAL": va >= vb}[op]
        if op in ("EQUAL", "LESS", "GREATER", "LESS_EQUAL", "GREATER_EQUAL"):
            try:
                x, y = float(a), float(b)
            except ValueError:
                return False
            return {"EQUAL": x == y, "LESS": x < y, "GREATER": x > y, "LESS_EQUAL": x <= y,
                    "GREATER_EQUAL": x >= y}[op]
        return None


def eval_conds(conds: Iterable[tuple[str, bool]], env: Env) -> bool | None:
    """Is code under these (condition, taken-when-true) frames executed?"""
    v: bool | None = True
    for cond, taken in conds:
        c = env.eval(cond)
        v = k_and(v, c if taken else k_not(c))
        if v is False:
            return False
    return v


# ---- check prediction ------------------------------------------------------------------------
# command -> index of the result variable
CHECK_RESULT_ARG = {
    "check_function_exists": 1, "check_symbol_exists": 2, "check_cxx_symbol_exists": 2,
    "check_library_exists": 3, "check_include_file": 1, "check_include_file_cxx": 1,
    "check_include_files": 1, "check_struct_has_member": 3, "check_c_source_compiles": 1,
    "check_cxx_source_compiles": 1, "check_c_source_runs": 1, "check_cxx_source_runs": 1,
    "check_source_compiles": 2, "check_type_size": 1, "check_c_compiler_flag": 1,
    "check_cxx_compiler_flag": 1, "check_compiler_flag": 2, "check_linker_flag": 2,
    "check_prototype_definition": 4,
}


@dataclass
class Prediction:
    var: str
    value: bool | None  # predicted check result on QNX (None = cannot tell)
    check: str  # e.g. "check_symbol_exists(AF_INET6 netinet/in.h)"
    reason: str
    path: str
    line: int
    runs: bool | None = True  # is the check itself reached on QNX?

    def to_dict(self) -> dict[str, object]:
        return {"var": self.var, "value": self.value, "check": self.check,
                "reason": self.reason, "path": self.path, "line": self.line, "runs": self.runs}


_TRIPLES = {"x86_64": "x86_64-pc-nto-qnx*", "aarch64": "aarch64-unknown-nto-qnx*",
            "aarch64le": "aarch64-unknown-nto-qnx*"}
# Declarations inside these blocks depend on the -std= mode in use (QNX enables its
# __EXT_QNX / __EXT_POSIX* / __EXT_BSD extensions by default, but C11 additions such as
# timespec_get only appear with -std=c11 or later).
_FEATURE_GATED = re.compile(r"__EXT_ANSIC_|__STDC_VERSION__|_XOPEN_SOURCE|_GNU_SOURCE")


class HeaderGrep:
    """Look for declarations in the SDP headers (and the compiler's own include directory),
    following their #includes."""

    def __init__(self, qnx_target: Path | None, qnx_host: Path | None = None,
                 arch: str = "x86_64") -> None:
        self.dirs: list[Path] = []
        if qnx_target is not None:
            self.dirs.append(qnx_target / "usr" / "include")
        if qnx_host is not None:
            gcc = qnx_host / "usr" / "lib" / "gcc"
            self.dirs += sorted(gcc.glob(f"{_TRIPLES.get(arch, '*')}/*/include"))
        self._cache: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return bool(self.dirs)

    def _text(self, h: str) -> str:
        if h not in self._cache:
            self._cache[h] = ""
            for d in self.dirs:
                p = d / h
                if p.is_file():
                    self._cache[h] = p.read_text(errors="replace")
                    break
        return self._cache[h]

    def closure(self, hdrs: Iterable[str], limit: int = 80) -> Iterable[str]:
        seen: set[str] = set()
        todo = [h for h in hdrs if h]
        while todo and len(seen) < limit:
            h = todo.pop(0)
            if h in seen:
                continue
            seen.add(h)
            text = self._text(h)
            yield text
            todo += re.findall(r"#\s*include\s*<([^>]+)>", text)

    def defines(self, sym: str, hdrs: Iterable[str]) -> bool:
        pat = re.compile(rf"#\s*define\s+{re.escape(sym)}\b|\benum\b[^;]*\b{re.escape(sym)}\b",
                         re.S)
        return any(pat.search(t) for t in self.closure(hdrs))

    def declares(self, sym: str, hdrs: Iterable[str]) -> bool | None:
        """True if declared, False if not, None if only declared behind feature macros
        (e.g. `#if defined(__EXT_ANSIC_201112)`): depends on the compiler flags in use."""
        from .cpp_text import guard_frames  # local import: cpp_text is a leaf module

        pat = re.compile(rf"\b{re.escape(sym)}\s*[(;\[]")
        gated = False
        for t in self.closure(hdrs):
            m = pat.search(t)
            if not m:
                continue
            frames = guard_frames(t)
            while m:
                ln = t.count("\n", 0, m.start())
                fr = frames[ln] if ln < len(frames) else ()
                if not any(_FEATURE_GATED.search(f.cond) for f in fr):
                    return True
                gated = True
                m = pat.search(t, m.end())
        return None if gated else False

    def struct_member(self, struct: str, member: str, hdrs: Iterable[str]) -> bool:
        name = struct.split()[-1]
        pat = re.compile(rf"\bstruct\s+{re.escape(name)}\s*\{{")
        for t in self.closure(hdrs):
            m = pat.search(t)
            if m:
                body = t[m.end(): t.find("};", m.end())]
                return re.search(rf"\b{re.escape(member)}\b", body) is not None
        return False


def predict_check(check: str, args: list[str], sdp: SdpIndex | None, grep: HeaderGrep,
                  required_libs: set[str]) -> tuple[bool | None, str]:
    """Predicted result of one configure check on QNX, with the reason."""

    def arg(i: int) -> str:
        return args[i] if i < len(args) else ""

    def linkable(sym: str) -> tuple[bool | None, str]:
        if sdp is None:
            return None, "no SDP index"
        flag = sdp.link_flag_for(sym)
        if flag is None:
            return False, f"{sym} is not in any QNX SDP library"
        if flag == "":
            return True, f"{sym} is in libc"
        if flag[2:] in required_libs:
            return True, f"{sym} is in lib{flag[2:]} (in CMAKE_REQUIRED_LIBRARIES)"
        return False, f"{sym} is in lib{flag[2:]}, which the check does not link"

    if any("${" in a for a in args[:4]):
        return None, "arguments not resolved"
    if check == "check_function_exists":
        return linkable(arg(0))
    if check in ("check_symbol_exists", "check_cxx_symbol_exists"):
        sym, hdrs = arg(0), [h for h in arg(1).split(";") if h]
        if sdp is not None:
            missing = [h for h in hdrs if not sdp.has_header(h)]
            if missing:
                return False, f"<{missing[0]}> is not in the QNX SDP"
        if grep.available and grep.defines(sym, hdrs):
            return True, f"{sym} is a macro in <{';'.join(hdrs)}>"
        if sym.isupper() or sym.startswith("_"):
            if not grep.available:
                return None, "macro: needs $QNX_TARGET headers"
            if sdp is None or not sdp.has_symbol(sym):
                return False, f"{sym} is not defined via <{';'.join(hdrs)}> on QNX"
        ok, why = linkable(sym)
        if ok and grep.available:
            declared = grep.declares(sym, hdrs)
            if declared is None:
                return None, f"{why}, but <{';'.join(hdrs)}> declares it only under " \
                             "feature macros (depends on -std/-D flags)"
            if not declared:
                return False, f"{sym} is not declared via <{';'.join(hdrs)}> on QNX"
        return ok, why
    if check == "check_library_exists":
        lib, sym = arg(0), arg(1)
        if lib in LIBC_ONLY_LIBS:
            return False, f"lib{lib} does not exist on QNX ({sym} is in libc)"
        if sdp is None:
            return None, "no SDP index"
        if not sdp.has_library(lib):
            return False, f"lib{lib} is not in the QNX SDP"
        provided = any(p.startswith(f"lib{lib}.") for p in sdp.symbols.get(sym, []))
        return (True, f"{sym} is in lib{lib}") if provided else (
            False, f"lib{lib} does not export {sym}")
    if check in ("check_include_file", "check_include_file_cxx", "check_include_files"):
        if sdp is None:
            return None, "no SDP index"
        missing = [h for h in arg(0).split(";") if h and not sdp.has_header(h)]
        if missing:
            return False, f"<{missing[0]}> is not in the QNX SDP"
        return True, "headers present"
    if check == "check_struct_has_member":
        hdrs = [h for h in arg(2).split(";") if h]
        if sdp is not None and any(not sdp.has_header(h) for h in hdrs):
            return False, "header not in the QNX SDP"
        if not grep.available:
            return None, "needs $QNX_TARGET headers"
        if grep.struct_member(arg(0), arg(1), hdrs):
            return True, f"{arg(0)} has {arg(1)}"
        return False, f"{arg(0)}.{arg(1)} not found via <{';'.join(hdrs)}> on QNX"
    return None, "compile/run check: not predicted"


# ---- the configure model --------------------------------------------------------------------
@dataclass
class _Def:
    var: str
    value: Value  # str, UNDEF, or None (unknown, e.g. unpredictable check)
    conds: tuple[tuple[str, bool], ...]
    weak: bool  # option()/set(CACHE): does not override a normal variable
    order: int
    pred: Prediction | None = None
    # cmake_dependent_option: value depends on conditions evaluated later
    dependent: tuple[str, str, str] | None = None  # (default, depends, force)


@dataclass
class MacroSource:
    """A C macro the build defines: by a definitions command, or tied to a check variable."""

    conds: tuple[tuple[str, bool], ...] = ()
    var: str | None = None  # defined iff this CMake variable is true
    value: str = "1"


@dataclass
class Configure:
    """Result of the configure prediction."""

    env: Env
    predictions: list[Prediction] = field(default_factory=list)
    macros: dict[str, Value] = field(default_factory=dict)  # C macros the build defines

    def conds_true(self, conds: Iterable[tuple[str, bool]]) -> bool | None:
        return eval_conds(conds, self.env)


class ConfigureModel:
    """Collects definitions while the CMake scanner walks commands, then solves them."""

    def __init__(self, arch: str = "x86_64", overrides: dict[str, str] | None = None) -> None:
        self.defs: dict[str, list[_Def]] = {}
        self.macro_sources: dict[str, list[MacroSource]] = {}
        self.seed = target_seed(arch)
        self.overrides = dict(overrides or {})  # cmake -DVAR=VALUE: wins over the project
        self.arch = arch
        self.maybe: set[str] = set()  # variables assigned inside function()/macro() bodies
        self._n = 0

    def _add(self, d: _Def) -> None:
        self.defs.setdefault(d.var, []).append(d)

    def _next(self) -> int:
        self._n += 1
        return self._n

    def add_set(self, args: list[str], conds: tuple[tuple[str, bool], ...]) -> None:
        if not args or "${" in args[0]:
            return
        var, rest = args[0], args[1:]
        weak = "CACHE" in rest and "FORCE" not in rest
        if "CACHE" in rest:
            rest = rest[: rest.index("CACHE")]
        if "PARENT_SCOPE" in rest:
            rest = rest[: rest.index("PARENT_SCOPE")]
        text = ";".join(rest)
        d = _Def(var, text if rest else UNDEF, conds, weak, self._next())
        if f"${{{var}}}" in text:  # self-append (lists): not modelled
            d.value = None
        elif "${" in text:  # expanded when solving
            d.value, d.dependent = None, ("expand", text, "")
        self._add(d)

    def add_option(self, args: list[str], conds: tuple[tuple[str, bool], ...]) -> None:
        if not args:
            return
        default = args[2] if len(args) > 2 else "OFF"
        self._add(_Def(args[0], default, conds, True, self._next()))

    def add_dependent_option(self, args: list[str],
                             conds: tuple[tuple[str, bool], ...]) -> None:
        if len(args) < 5:
            return
        d = _Def(args[0], None, conds, True, self._next())
        d.dependent = (args[2], args[3], args[4])
        self._add(d)

    def add_unset(self, args: list[str], conds: tuple[tuple[str, bool], ...]) -> None:
        if args:
            self._add(_Def(args[0], UNDEF, conds, False, self._next()))

    def add_unknown(self, var: str, conds: tuple[tuple[str, bool], ...]) -> None:
        if var and "${" not in var:
            self._add(_Def(var, None, conds, False, self._next()))

    def add_check(self, pred: Prediction, conds: tuple[tuple[str, bool], ...]) -> None:
        value: Value = None if pred.value is None else ("1" if pred.value else "")
        self._add(_Def(pred.var, value, conds, False, self._next(), pred))
        # nng_check_* / #cmakedefine style: the C macro of the same name follows the check
        self.macro_sources.setdefault(pred.var, []).append(MacroSource(conds, pred.var))

    def add_macro(self, name: str, conds: tuple[tuple[str, bool], ...], value: str = "1",
                  var: str | None = None) -> None:
        self.macro_sources.setdefault(name, []).append(MacroSource(conds, var, value))

    # ---- solve ----------------------------------------------------------------------------
    def _value(self, defs: list[_Def], env: Env, name: str) -> Value:
        if name in self.overrides:  # -D sets the cache entry; a normal set() still wins
            defs = [d for d in defs if not d.weak]
        strong = [d for d in defs if not d.weak]
        weak = [d for d in defs if d.weak]
        result: Value = UNDEF
        decided = False
        for d in reversed(strong):  # the last executed normal assignment wins
            c = eval_conds(d.conds, env)
            if c is False:
                continue
            if c is None:
                return None
            result, decided = self._def_value(d, env), True
            break
        if decided:
            return result
        for d in weak:  # first cache/option definition wins
            c = eval_conds(d.conds, env)
            if c is False:
                continue
            if c is None:
                return None
            return self._def_value(d, env)
        if name in self.overrides:
            return self.overrides[name]
        return self.seed.get(name, UNDEF)

    @staticmethod
    def _def_value(d: _Def, env: Env) -> Value:
        if d.dependent is None:
            return d.value
        a, b, c = d.dependent
        if a == "expand":
            return env.expand(b)
        ok: bool | None = True
        for dep in b.split(";"):
            ok = k_and(ok, env.eval(dep))
        if ok is None:
            return None
        return a if ok else c

    def solve(self, predictions: list[Prediction]) -> Configure:
        values: dict[str, Value] = {**self.seed, **self.overrides}
        for name in self.defs:
            values[name] = None
        env = Env(values, self.maybe)
        for _ in range(12):  # fixed point: conditions depend on other variables
            changed = False
            for name, defs in self.defs.items():
                v = self._value(defs, env, name)
                if v != env.values.get(name) or type(v) is not type(env.values.get(name)):
                    env.values[name] = v
                    changed = True
            if not changed:
                break
        for p in predictions:
            p.runs = None
        for defs in self.defs.values():
            for d in defs:
                if d.pred is not None:
                    d.pred.runs = eval_conds(d.conds, env)
        macros: dict[str, Value] = {}
        for name, sources in self.macro_sources.items():
            macros[name] = self._macro_value(sources, env)
        return Configure(env, predictions, macros)

    @staticmethod
    def _macro_value(sources: list[MacroSource], env: Env) -> Value:
        result: Value = UNDEF
        for s in sources:
            c = eval_conds(s.conds, env)
            if s.var is not None and c is not False:
                b = env.bool_of(s.var)
                c = k_and(c, b)
            if c is True:
                return s.value
            if c is None:
                result = None
        return result


# ---- C preprocessor evaluation ---------------------------------------------------------------
_CTOK = re.compile(r"\s*(defined|0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*|[A-Za-z_]\w*|\"[^\"\n]*\"|"
                   r"&&|\|\||==|!=|<=|>=|<<|>>|[()!<>+\-*/%~&|^?:,.])")
_HAS_INCLUDE = re.compile(r"__has_include(_next)?|\w*HAS_INCLUDE\w*")
HasInclude = Callable[[str], bool | None]


class CExpr:
    """Three-valued #if evaluation with known macro values; unknown macros -> None.
    `has_include(header)` answers __has_include(<header>) (and FOO_HAS_INCLUDE wrappers)."""

    def __init__(self, macros: dict[str, Value], has_include: HasInclude | None = None,
                 depth: int = 0, closed: bool = False,
                 header_macros: frozenset[str] | set[str] = frozenset()) -> None:
        self.macros = macros
        self.has_include = has_include
        self.depth = depth
        # closed: `macros` holds the compiler's complete predefined list and
        # `header_macros` every reserved name the SDP headers #define, so any other
        # reserved name (__MVS__, __SVR4, _WIN32, __cpp_impl_reflection) is undefined
        self.closed = closed
        self.header_macros = header_macros

    def _get(self, name: str) -> Value:
        if name in self.macros:
            return self.macros[name]
        if self.closed and _RESERVED.fullmatch(name) and name not in self.header_macros:
            return UNDEF
        return None

    def derive(self, macros: dict[str, Value]) -> CExpr:
        """Same settings, other macro values."""
        return CExpr(macros, self.has_include, self.depth, self.closed, self.header_macros)

    def eval(self, expr: str) -> bool | None:
        v = self.eval_int(expr)
        return None if v is None else v != 0

    def eval_int(self, expr: str) -> int | None:
        toks: list[str] = []
        pos = 0
        expr = expr.strip()
        while pos < len(expr):
            m = _CTOK.match(expr, pos)
            if not m:
                return None
            toks.append(m.group(1))
            pos = m.end()
            while pos < len(expr) and expr[pos].isspace():
                pos += 1
        if not toks:
            return None
        self.t, self.i = toks, 0
        try:
            v = self._or()
        except (IndexError, ValueError, ZeroDivisionError):
            return None
        return v if self.i == len(toks) else None

    def _peek(self) -> str | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def _take(self) -> str:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def _bin(self, sub: Callable[[], int | None], ops: dict[str, Callable[[int, int], int]]
             ) -> int | None:
        v = sub()
        while self._peek() in ops:
            op = self._take()
            w = sub()
            if op == "&&":
                v = 0 if (v == 0 or w == 0) else (None if v is None or w is None else 1)
            elif op == "||":
                v = 1 if (v not in (0, None) or w not in (0, None)) else (
                    None if v is None or w is None else 0)
            else:
                v = None if v is None or w is None else ops[op](v, w)
        return v

    def _or(self) -> int | None:
        return self._bin(self._and, {"||": lambda a, b: int(bool(a or b))})

    def _and(self) -> int | None:
        return self._bin(self._eq, {"&&": lambda a, b: int(bool(a and b))})

    def _eq(self) -> int | None:
        return self._bin(self._rel, {"==": lambda a, b: int(a == b),
                                     "!=": lambda a, b: int(a != b)})

    def _rel(self) -> int | None:
        return self._bin(self._add, {"<": lambda a, b: int(a < b), ">": lambda a, b: int(a > b),
                                     "<=": lambda a, b: int(a <= b),
                                     ">=": lambda a, b: int(a >= b)})

    def _add(self) -> int | None:
        return self._bin(self._unary, {"+": lambda a, b: a + b, "-": lambda a, b: a - b})

    def _unary(self) -> int | None:
        tok = self._peek()
        if tok == "!":
            self._take()
            v = self._unary()
            return None if v is None else int(v == 0)
        if tok == "-":
            self._take()
            v = self._unary()
            return None if v is None else -v
        return self._primary()

    def _primary(self) -> int | None:
        tok = self._take()
        if tok == "(":
            v = self._or()
            if self._take() != ")":
                raise ValueError
            return v
        if tok == "defined":
            paren = self._peek() == "("
            if paren:
                self._take()
            name = self._take()
            if paren and self._take() != ")":
                raise ValueError
            mv = self._get(name)
            return None if mv is None else int(not isinstance(mv, _Undef))
        if tok[0].isdigit():
            return int(tok.rstrip("uUlL"), 0)
        if self._peek() == "(":  # function-like macro call: collect its argument tokens
            depth, arg = 0, []
            while True:
                t = self._take()
                depth += t == "("
                depth -= t == ")"
                if depth == 0:
                    break
                if depth >= 1 and not (depth == 1 and t == "("):
                    arg.append(t)
            if _HAS_INCLUDE.fullmatch(tok) and self.has_include is not None:
                h = "".join(arg).strip()
                if len(h) > 2 and h[0] in "<\"" and h[-1] in ">\"":
                    r = self.has_include(h[1:-1])
                    return None if r is None else int(r)
            return None
        return self._macro_int(tok)

    def _macro_int(self, name: str) -> int | None:
        mv = self._get(name)
        if mv is None:
            return None
        if isinstance(mv, _Undef):
            return 0
        text = mv.strip()
        while text.startswith("(") and text.endswith(")"):
            text = text[1:-1].strip()
        try:
            return int(text.rstrip("uUlL"), 0)
        except ValueError:
            pass
        if self.depth >= 8 or not text:
            return None
        # the macro expands to another macro or an expression: evaluate it
        sub = CExpr(self.macros, self.has_include, self.depth + 1, self.closed,
                    self.header_macros)
        if re.fullmatch(r"[A-Za-z_]\w*", text):
            return sub._macro_int(text)
        return sub.eval_int(text)
