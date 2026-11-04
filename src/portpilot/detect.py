"""Detect a project's build system from the files at (and near) its root."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Most specific first: a CMake project often also ships a Makefile wrapper.
_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("cmake", ("CMakeLists.txt",)),
    ("meson", ("meson.build",)),
    ("autotools", ("configure.ac", "configure.in", "configure")),
    ("bazel", ("BUILD.bazel", "WORKSPACE", "MODULE.bazel")),
    ("make", ("Makefile", "GNUmakefile", "makefile")),
]
SUPPORTED = ("cmake",)


@dataclass
class BuildSystem:
    primary: str  # cmake | meson | autotools | bazel | make | unknown
    found: dict[str, list[str]] = field(default_factory=dict)  # kind -> marker files

    @property
    def supported(self) -> bool:
        return self.primary in SUPPORTED


def detect(root: Path) -> BuildSystem:
    found: dict[str, list[str]] = {}
    for kind, names in _MARKERS:
        hits = [n for n in names if (root / n).is_file()]
        if hits:
            found[kind] = hits
    primary = next((kind for kind, _ in _MARKERS if kind in found), "unknown")
    return BuildSystem(primary=primary, found=found)
