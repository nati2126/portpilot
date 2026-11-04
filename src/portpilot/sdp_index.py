"""Index of what the installed QNX SDP provides: exported symbols per library, and headers.

Built locally from $QNX_TARGET (never shipped: it is derived from the user's SDP).
Used to answer "is X available on QNX, and in which library?" with facts instead of guesses.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

INDEX_VERSION = 2
DEFAULT_CACHE = Path.home() / ".cache" / "portpilot"

# nm -D output: "<addr> <type> <name>[@version]"; defined code/data/weak symbols only.
_NM_DEFINED = re.compile(r"^[0-9a-fA-F]*\s+([TDBRWVi])\s+([A-Za-z_][\w.$]*?)(?:@@?\S+)?$")

# Libraries that export copies of libc/POSIX names without being a real provider for
# applications: sanitizer/debug interceptors and private compat copies inside other libs.
# (e.g. strchrnul is "exported" only by libasan; arc4random only by libunbound.)
NON_PROVIDERS = ("libasan.", "liblsan.", "libtsan.", "libubsan.", "librcheck.", "libunbound.")


@dataclass
class SdpIndex:
    """symbol -> list of library sonames/basenames; set of header paths relative to usr/include."""

    arch: str
    symbols: dict[str, list[str]] = field(default_factory=dict)
    headers: set[str] = field(default_factory=set)
    libraries: set[str] = field(default_factory=set)
    # compiler-predefined macros (qcc -dM -E) for C and for C++
    predefined_c: dict[str, str] = field(default_factory=dict)
    predefined_cxx: dict[str, str] = field(default_factory=dict)
    # reserved-name macros (_X / __x) that some SDP header #defines
    header_macros: set[str] = field(default_factory=set)

    # ---- queries -------------------------------------------------------------------------
    def libs_for(self, symbol: str) -> list[str]:
        """Real providers of `symbol` (sanitizers and private compat copies excluded)."""
        return [lib for lib in self.symbols.get(symbol, []) if not lib.startswith(NON_PROVIDERS)]

    def has_symbol(self, symbol: str) -> bool:
        return bool(self.libs_for(symbol))

    def link_flag_for(self, symbol: str) -> str | None:
        """'' if in libc (no flag needed), '-l<name>' for another library, None if absent."""
        libs = self.libs_for(symbol)
        if not libs:
            return None
        if any(lib.startswith("libc.") for lib in libs):
            return ""
        name = _lib_name(libs[0])
        return f"-l{name}" if name else None

    def in_libc(self, symbol: str) -> bool:
        return any(lib.startswith("libc.") for lib in self.libs_for(symbol))

    def has_header(self, header: str) -> bool:
        return header in self.headers

    def has_library(self, name: str) -> bool:
        """name without 'lib' prefix and suffix, e.g. 'pthread'."""
        return name in self.libraries

    # ---- persistence ---------------------------------------------------------------------
    def to_json(self) -> str:
        return json.dumps(
            {
                "version": INDEX_VERSION,
                "arch": self.arch,
                "symbols": self.symbols,
                "headers": sorted(self.headers),
                "libraries": sorted(self.libraries),
                "predefined_c": self.predefined_c,
                "predefined_cxx": self.predefined_cxx,
                "header_macros": sorted(self.header_macros),
            }
        )

    @classmethod
    def from_json(cls, text: str) -> SdpIndex:
        d = json.loads(text)
        if d.get("version") != INDEX_VERSION:
            raise ValueError(f"unsupported SDP index version {d.get('version')}")
        return cls(
            arch=d["arch"],
            symbols={k: list(v) for k, v in d["symbols"].items()},
            headers=set(d["headers"]),
            libraries=set(d["libraries"]),
            predefined_c=dict(d.get("predefined_c", {})),
            predefined_cxx=dict(d.get("predefined_cxx", {})),
            header_macros=set(d.get("header_macros", [])),
        )

    @classmethod
    def load(cls, path: Path) -> SdpIndex:
        return cls.from_json(path.read_text())


def _lib_name(filename: str) -> str | None:
    """'libsocket.so.4' -> 'socket'; 'libregex.a' -> 'regex'."""
    m = re.match(r"^lib(.+?)\.(?:so(?:\.\d+)*|a)$", filename)
    return m.group(1) if m else None


def _nm_tool() -> str:
    for tool in ("nm", "ntox86_64-nm"):
        if shutil.which(tool):
            return tool
    raise FileNotFoundError("no 'nm' found (install binutils or source qnxsdp-env.sh)")


def build_index(qnx_target: Path, arch: str = "x86_64") -> SdpIndex:
    """Scan $QNX_TARGET/<arch>/{lib,usr/lib} shared libs and $QNX_TARGET/usr/include headers."""
    idx = SdpIndex(arch=arch)
    nm = _nm_tool()
    lib_dirs = [qnx_target / arch / "lib", qnx_target / arch / "usr" / "lib"]
    # The compiler runtime (libatomic.a, libgcc.a) lives in lib/gcc/<version>/, static only.
    gcc_dirs = sorted((qnx_target / arch / "lib" / "gcc").glob("*"))
    for d in lib_dirs + gcc_dirs:
        if not d.is_dir():
            continue
        static_ok = d in gcc_dirs
        for f in sorted(d.iterdir()):
            name = _lib_name(f.name)
            if name is None:
                continue
            idx.libraries.add(name)
            # Shared objects carry the export table we want (skip symlinks); static
            # archives are read only for the compiler runtime.
            if f.is_symlink():
                continue
            if ".so" in f.name:
                cmd = [nm, "-D", "--defined-only", str(f)]
            elif static_ok and f.name.endswith(".a"):
                cmd = [nm, "-g", "--defined-only", str(f)]
            else:
                continue
            out = subprocess.run(cmd, capture_output=True, text=True).stdout
            for line in out.splitlines():
                m = _NM_DEFINED.match(line.strip())
                if m:
                    libs = idx.symbols.setdefault(m.group(2), [])
                    if f.name not in libs:
                        libs.append(f.name)
    # System headers, the libc++ headers (c++/v1) and the compiler's own headers
    # (stddef.h, immintrin.h, ...), all keyed by the name used in #include <...>.
    inc_dirs = [qnx_target / "usr" / "include", qnx_target / "usr" / "include" / "c++" / "v1"]
    qnx_host = os.environ.get("QNX_HOST")
    if qnx_host:
        inc_dirs += sorted(Path(qnx_host, "usr", "lib", "gcc").glob("*/*/include"))
    for inc in inc_dirs:
        if not inc.is_dir():
            continue
        for root, _, files in os.walk(inc):
            for fn in files:
                if fn.endswith((".h", ".hpp", ".hh")) or "." not in fn:
                    rel = str(Path(root, fn).relative_to(inc)).replace(os.sep, "/")
                    idx.headers.add(rel)
                    try:
                        text = Path(root, fn).read_text(errors="replace")
                    except OSError:
                        continue
                    idx.header_macros.update(_RESERVED_DEFINE.findall(text))
    idx.predefined_c = predefined_macros(arch, "c")
    idx.predefined_cxx = predefined_macros(arch, "c++")
    return idx


_QCC_VARIANT = {"x86_64": "gcc_ntox86_64", "aarch64le": "gcc_ntoaarch64le",
                "aarch64": "gcc_ntoaarch64le"}
_RESERVED_DEFINE = re.compile(r"^\s*#\s*define\s+(_[_A-Z]\w*)", re.M)
_DEFINE_LINE = re.compile(r"^#define\s+([A-Za-z_]\w*)(?:\s+(.*))?$")


def predefined_macros(arch: str = "x86_64", lang: str = "c") -> dict[str, str]:
    """Macros qcc predefines for `arch` (qcc -V<variant> -dM -E). Empty if qcc is missing."""
    tool = "qcc" if lang == "c" else "q++"
    if not shutil.which(tool):
        return {}
    variant = _QCC_VARIANT.get(arch, f"gcc_nto{arch}") + ("" if lang == "c" else "_cxx")
    cmd = [tool, f"-V{variant}", "-dM", "-E", "-x", "c" if lang == "c" else "c++", "-"]
    out = subprocess.run(cmd, input="", capture_output=True, text=True).stdout
    macros: dict[str, str] = {}
    for line in out.splitlines():
        m = _DEFINE_LINE.match(line.strip())
        if m:
            macros[m.group(1)] = (m.group(2) or "").strip()
    return macros


def default_index_path(arch: str = "x86_64") -> Path:
    return DEFAULT_CACHE / f"sdp-index-{arch}.json"


def load_default(arch: str = "x86_64") -> SdpIndex | None:
    p = default_index_path(arch)
    return SdpIndex.load(p) if p.exists() else None
