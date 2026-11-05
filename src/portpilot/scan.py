"""Run every scanner over a project and return one ScanResult."""

from __future__ import annotations

import dataclasses
import os
import time
from pathlib import Path

from . import kb as kb_mod
from .detect import detect
from .kb import KnowledgeBase
from .models import Finding, ScanResult
from .scan_cmake import CMakeScanner
from .scan_source import SourceScanner
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
