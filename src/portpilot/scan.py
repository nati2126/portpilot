"""Run every scanner over a project and return one ScanResult."""

from __future__ import annotations

import dataclasses
import os
import re
import time
from pathlib import Path

from . import kb as kb_mod
from .detect import detect
from .kb import KnowledgeBase
from .models import Finding, ScanResult
from .scan_cmake import CMakeScanner
from .scan_source import SourceScanner, area_of
from .sdp_index import SdpIndex


def _mark_handled_links(findings: list[Finding], kb: KnowledgeBase,
                        linked: set[str]) -> list[Finding]:
    """A '-lsocket needed' finding is already handled if the build links/probes socket."""
    out = []
    for f in findings:
        rule = kb.rule(f.rule_id)
        lib = rule.link[2:] if rule.link.startswith("-l") else ""
        if lib and lib in linked and f.guard == "none":
            f = dataclasses.replace(f, guard="handled")
        out.append(f)
    return out


_COMPILED = {".c", ".cc", ".cpp", ".cxx", ".c++"}
_HEADERS = {".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp"}
_INC = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)


def reachable_headers(root: Path, sources: list[Path]) -> set[Path]:
    """Project headers that the given sources include, directly or through other headers.
    Includes resolve against the including file's folder, the project root, and every
    folder named include/ or src/."""
    roots = [root] + [p for p in root.rglob("*") if p.is_dir() and p.name in ("include", "src")
                      and ".git" not in p.parts][:50]
    seen: set[Path] = set()
    todo = list(sources)
    while todo:
        f = todo.pop()
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name in _INC.findall(text):
            for base in (f.parent, *roots):
                h = (base / name).resolve()
                if h.suffix in _HEADERS and h not in seen and h.is_file():
                    seen.add(h)
                    todo.append(h)
                    break
    return seen


def mark_optional_headers(root: Path, findings: list[Finding]) -> list[Finding]:
    """A library header that no compiled library source includes is an optional component
    (spdlog's kafka/mongo/qt sinks): its findings only matter to users who include it, so
    they get the guard 'optional-header'. Header-only libraries are left alone: there every
    header can be the entry point."""
    cand = [f for f in findings if f.guard == "none" and f.area == "lib"
            and Path(f.path).suffix in _HEADERS]
    if not cand:
        return findings
    sources = [p for p in root.rglob("*") if p.suffix in _COMPILED and p.is_file()
               and ".git" not in p.parts and area_of(p.relative_to(root).as_posix()) == "lib"]
    if not sources:
        return findings
    reach = reachable_headers(root, sources)
    cand_ids = {id(f) for f in cand}
    out = []
    for f in findings:
        if id(f) in cand_ids and (root / f.path).resolve() not in reach:
            f = dataclasses.replace(f, guard="optional-header")
        out.append(f)
    return out


def scan_project(root: Path, kb: KnowledgeBase | None = None,
                 sdp: SdpIndex | None = None, arch: str = "x86_64",
                 defines: dict[str, str] | None = None) -> ScanResult:
    """Scan `root`. `defines` are cmake -D values (e.g. the port's flags)."""
    t0 = time.perf_counter()
    kb = kb or kb_mod.load()
    root = root.resolve()
    bs = detect(root)
    qt, qh = os.environ.get("QNX_TARGET"), os.environ.get("QNX_HOST")
    qnx_target = Path(qt) if qt and sdp is not None else None
    qnx_host = Path(qh) if qh and sdp is not None else None
    cm = CMakeScanner(kb, sdp, qnx_target, arch, qnx_host, defines).scan(root)
    macros = cm.configure.macros if cm.configure else {}
    src_findings, nfiles, src_qnx = SourceScanner(kb, sdp, arch).scan(
        root, cm.build_guards, macros)
    findings = _mark_handled_links(cm.findings + src_findings, kb, cm.linked)
    findings = mark_optional_headers(root, findings)
    return ScanResult(
        root=str(root),
        build_system=bs.primary,
        build_markers=bs.found,
        files_scanned=nfiles,
        sdp_index_used=sdp is not None,
        findings=findings,
        qnx_aware=src_qnx + cm.qnx_aware,
        elapsed_s=time.perf_counter() - t0,
        configure=[p.to_dict() for p in cm.configure.predictions] if cm.configure else [],
    )
