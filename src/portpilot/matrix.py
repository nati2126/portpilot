"""Aggregate findings into the dependency matrix (the QNX porting guide's format + extras)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .kb import KnowledgeBase, Rule
from .models import Finding, ScanResult

SEV_ORDER = {"blocker": 0, "fix": 1, "warn": 2, "info": 3}
GUARD_TEXT = {
    "config-off": "not compiled on QNX (predicted configure)",
    "other-arch": "code for another CPU architecture",
    "feature": "behind a feature check for this API (QNX uses the fallback)",
    "build-feature": "file built only when the feature is detected",
    "build-optional": "file built only with an optional setting",
    "linux": "Linux-only code path",
    "build-linux": "file built only on Linux",
    "other-os": "other-OS code path",
    "build-other-os": "file built only on another OS",
    "qnx": "already handles QNX",
    "handled": "the build already links the library",
}


@dataclass
class Row:
    rule: Rule
    findings: list[Finding] = field(default_factory=list)

    @property
    def active(self) -> list[Finding]:
        """Occurrences that QNX will actually compile, in library code."""
        return [f for f in self.findings if not f.guarded and f.area == "lib"]

    @property
    def status(self) -> str:
        if self.active:
            return "note" if self.rule.severity == "info" else "needs work"
        unguarded = [f for f in self.findings if not f.guarded]
        if unguarded:
            areas = sorted({f.area for f in unguarded})
            return f"{'/'.join(areas)} only"
        return "guarded"

    @property
    def effective_severity(self) -> str:
        return self.rule.severity if self.status == "needs work" else "info"

    def names(self) -> list[tuple[str, int]]:
        return Counter(f.name for f in self.findings).most_common()

    def guards(self) -> list[tuple[str, int]]:
        return Counter(f.guard for f in self.findings if f.guarded).most_common()


def build_rows(result: ScanResult, kb: KnowledgeBase) -> list[Row]:
    rows: dict[str, Row] = {}
    for f in result.findings:
        rows.setdefault(f.rule_id, Row(kb.rule(f.rule_id))).findings.append(f)
    order = {"needs work": 0, "note": 1}
    return sorted(
        rows.values(),
        key=lambda r: (order.get(r.status, 2), SEV_ORDER[r.effective_severity],
                       r.rule.category, r.rule.id),
    )


def summary(rows: list[Row]) -> dict[str, int]:
    c: Counter[str] = Counter()
    for r in rows:
        if r.status == "needs work":
            c[r.rule.severity] += 1
            if r.rule.fix == "rule":
                c["auto_fixable"] += 1
        elif r.status == "note":
            c["info"] += 1
        else:
            c["guarded_or_nonlib"] += 1
    return dict(c)


def _loc(f: Finding) -> str:
    return f"{f.path}:{f.line}"


def to_markdown(result: ScanResult, kb: KnowledgeBase, top: int = 3) -> str:
    rows = build_rows(result, kb)
    s = summary(rows)
    out = [
        f"# PortPilot scan: `{result.root}`",
        "",
        f"- Build system: **{result.build_system}**"
        + ("" if result.build_system == "cmake" else " (PortPilot MVP supports CMake)"),
        f"- Files scanned: {result.files_scanned}; SDP index: "
        + ("yes (facts checked against your QNX SDP)" if result.sdp_index_used else
           "no (run `portpilot sdp-index` for exact availability)"),
        f"- Needs work: **{s.get('blocker', 0)} blocker**, {s.get('fix', 0)} fix, "
        f"{s.get('warn', 0)} warn, {s.get('info', 0)} info "
        f"({s.get('auto_fixable', 0)} auto-fixable by rule); "
        f"{s.get('guarded_or_nonlib', 0)} more are guarded or outside library code",
    ]
    if result.qnx_aware:
        out.append(f"- Already mentions QNX in {len(result.qnx_aware)} place(s), e.g. "
                   f"`{result.qnx_aware[0]}`")
    out += [
        "",
        "## Dependency matrix",
        "",
        "| Dependency | Linux standard | QNX equivalent | Porting strategy | Auto-fix | Status "
        "| Where |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        where = ", ".join(f"`{_loc(f)}`" for f in (r.active or r.findings)[:top])
        more = len(r.active or r.findings) - top
        if more > 0:
            where += f" +{more}"
        names = ", ".join(n for n, _ in r.names()[:4])
        sev = r.effective_severity
        out.append(
            f"| **{r.rule.title}** ({sev})<br>{names} | {r.rule.linux} | {r.rule.qnx} | "
            f"{r.rule.strategy} | {r.rule.auto_fixable} | {r.status} | {where} |"
        )
    detailed = [r for r in rows if r.status == "needs work" and not r.rule.quiet]
    if detailed:
        out += ["", "## Details (needs work)", ""]
        for r in detailed:
            out.append(f"### {r.rule.title} — {r.rule.severity}")
            out.append("")
            for f in r.active[:12]:
                d = f" — {f.detail}" if f.detail else ""
                out.append(f"- `{_loc(f)}` `{f.name}`{d}")
            if len(r.active) > 12:
                out.append(f"- … {len(r.active) - 12} more")
            out.append("- Sources: " + "; ".join(
                f"[{kb.sources[s].title}]({kb.sources[s].url})" for s in r.rule.sources))
            out.append("")
    guarded = [r for r in rows if r.status not in ("needs work", "note")]
    if guarded:
        out += ["## Guarded or outside library code", ""]
        for r in guarded:
            g = ", ".join(f"{GUARD_TEXT.get(k, k)} ×{n}" for k, n in r.guards()) or r.status
            out.append(f"- **{r.rule.title}** ({len(r.findings)}): {g}")
        out.append("")
    checks = [c for c in result.configure if c["runs"] is not False]
    if checks:
        off = [c for c in checks if c["value"] is False]
        on = [c for c in checks if c["value"] is True]
        out += ["## Predicted configure on QNX", "",
                f"{len(checks)} configure checks: {len(on)} pass, {len(off)} fail, "
                f"{len(checks) - len(on) - len(off)} not predicted. "
                "Failing checks switch features off.", "",
                "| Variable | Check | QNX | Why |", "|---|---|---|---|"]
        for c in sorted(checks, key=lambda c: (c["value"] is not False, c["var"])):
            v = {True: "ON", False: "**OFF**", None: "?"}[c["value"]]
            out.append(f"| `{c['var']}` | `{c['check']}` | {v} | {c['reason']} |")
        out.append("")
    out.append(f"_Scanned in {result.elapsed_s:.2f}s by PortPilot._")
    return "\n".join(out) + "\n"


def to_json(result: ScanResult, kb: KnowledgeBase) -> str:
    rows = build_rows(result, kb)
    data: dict[str, Any] = {
        "root": result.root,
        "build_system": result.build_system,
        "build_markers": result.build_markers,
        "files_scanned": result.files_scanned,
        "sdp_index_used": result.sdp_index_used,
        "qnx_aware": result.qnx_aware,
        "elapsed_s": round(result.elapsed_s, 3),
        "summary": summary(rows),
        "matrix": [
            {
                "rule": r.rule.id,
                "dependency": r.rule.title,
                "category": r.rule.category,
                "linux_standard": r.rule.linux,
                "qnx_equivalent": r.rule.qnx,
                "porting_strategy": r.rule.strategy,
                "auto_fixable": r.rule.auto_fixable,
                "severity": r.rule.severity,
                "effective_severity": r.effective_severity,
                "status": r.status,
                "sources": [{"title": kb.sources[s].title, "url": kb.sources[s].url}
                            for s in r.rule.sources],
                "occurrences": [f.to_dict() for f in r.findings],
            }
            for r in rows
        ],
        "configure": result.configure,
    }
    return json.dumps(data, indent=2)
