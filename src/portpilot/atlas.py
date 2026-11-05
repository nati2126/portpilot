"""QNX Port Atlas: scan many open-source libraries and rank what blocks them on QNX 8.0.

    portpilot atlas scan atlas/candidates.json -o ~/qnx-work/atlas --limit 300
    portpilot atlas report ~/qnx-work/atlas

Each candidate is shallow-cloned, scanned (the same scanner as `portpilot scan`, checked
against your SDP index) and deleted again; only a small JSON record per library is kept.
Each library gets a predicted tier from the rules it needs:

    auto       everything it needs is fixed by a PortPilot rule (or nothing is needed)
    assisted   needs AI-assisted or small manual edits with a known POSIX replacement
    deps       needs a library the SDP does not have (port it first), nothing worse
    redesign   uses a Linux-only design (epoll, timerfd, CPU affinity, ...): a person decides

The tier is a prediction. `portpilot port` then builds and tests the promising ones for real.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from . import kb as kb_mod
from .matrix import build_rows
from .scan import scan_project
from .sdp_index import SdpIndex, load_default

MAX_SIZE_KB = 300_000  # skip giant repositories (browsers, engines, monorepos)
TIERS = ("auto", "assisted", "deps", "redesign")
DEP_RULES = {"third-party-dep"}


def _slug(repo: str) -> str:
    return repo.replace("/", "__")


def tier(needs: list[dict[str, Any]]) -> str:
    """Only a blocking Linux-only design is a redesign. A missing library means porting the
    dependency first; a manual warning (/proc reads) is a local edit."""
    real = [n for n in needs if n["severity"] != "info"]
    if any(n["fix"] == "manual" and n["severity"] == "blocker" and n["rule"] not in DEP_RULES
           for n in real):
        return "redesign"
    if any(n["rule"] in DEP_RULES for n in real):
        return "deps"
    if {n["fix"] for n in real} - {"rule", "none"}:
        return "assisted"
    return "auto"


def scan_one(cand: dict[str, Any], work: Path, sdp_path: str | None,
             arch: str = "x86_64", keep: bool = False) -> dict[str, Any]:
    """Clone, scan and summarize one candidate. Never raises: errors go into the record."""
    rec: dict[str, Any] = {k: cand.get(k) for k in
                           ("repo", "url", "stars", "language", "markets", "description")}
    src = work / _slug(cand["repo"])
    t0 = time.monotonic()
    try:
        for _ in range(3 if not src.exists() else 0):  # busy networks reset connections
            r = subprocess.run(["git", "clone", "-q", "--depth", "1", "--single-branch",
                                "--no-tags", f"{cand['url']}.git", str(src)],
                               capture_output=True, text=True, timeout=600,
                               env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin"})
            if r.returncode == 0:
                break
            shutil.rmtree(src, ignore_errors=True)
            time.sleep(5)
        if not src.exists():
            return {**rec, "error": f"clone failed: {r.stderr.strip()[:200]}"}
        rec["commit"] = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"],
                                       capture_output=True, text=True).stdout.strip()
        kb = kb_mod.load()
        sdp = SdpIndex.load(Path(sdp_path)) if sdp_path else None
        res = scan_project(src, kb, sdp, arch)
        rows = build_rows(res, kb)
        needs = [{"rule": r.rule.id, "title": r.rule.title, "severity": r.rule.severity,
                  "fix": r.rule.fix, "count": len(r.active),
                  "where": [f"{f.path}:{f.line}" for f in r.active[:3]]}
                 for r in rows if r.status == "needs work"]
        rec.update(build_system=res.build_system, files=res.files_scanned,
                   qnx_aware=len(res.qnx_aware), needs=needs,
                   guarded=[r.rule.id for r in rows if r.status == "guarded"],
                   configure_off=[c["var"] for c in res.configure if c["value"] is False],
                   tier=tier(needs) if res.build_system == "cmake" else "not-cmake",
                   scan_s=round(time.monotonic() - t0, 1))
    except Exception as e:  # noqa: BLE001 (one bad repo must not stop a 500-repo run)
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
    finally:
        if not keep:
            shutil.rmtree(src, ignore_errors=True)
    return rec


def _done(rec: Path) -> bool:
    """Scanned before, and not a clone failure (those are retried)."""
    try:
        return "error" not in json.loads(rec.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def run_scan(candidates: Path, out: Path, *, limit: int = 300, jobs: int = 6,
             arch: str = "x86_64", sdp_path: str | None = None, keep: bool = False,
             say: Any = print) -> list[dict[str, Any]]:
    cands = [c for c in json.loads(candidates.read_text(encoding="utf-8"))
             if c.get("cmake") and not c.get("already_ported")
             and (c.get("size_kb") or 0) <= MAX_SIZE_KB][:limit]
    if sdp_path is None and load_default(arch) is not None:
        from .sdp_index import default_index_path
        sdp_path = str(default_index_path(arch))
    recs_dir, work = out / "records", out / "src"
    recs_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    todo = [c for c in cands if not _done(recs_dir / f"{_slug(c['repo'])}.json")]
    say(f"atlas: {len(cands)} candidates, {len(cands) - len(todo)} already scanned, "
        f"SDP index: {'yes' if sdp_path else 'no'}")
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(scan_one, c, work, sdp_path, arch, keep): c for c in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            (recs_dir / f"{_slug(rec['repo'])}.json").write_text(json.dumps(rec, indent=1),
                                                                 encoding="utf-8")
            say(f"  [{i}/{len(todo)}] {rec['repo']:40} "
                + (f"ERROR {rec['error'][:60]}" if "error" in rec else
                   f"{rec['tier']:9} {len(rec['needs'])} needs, {rec['scan_s']}s"))
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(recs_dir.glob("*.json"))]
    (out / "atlas.json").write_text(json.dumps(aggregate(recs), indent=1), encoding="utf-8")
    return recs


def aggregate(recs: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in recs if "error" not in r and r.get("tier") in TIERS]
    by_rule: dict[str, dict[str, Any]] = {}
    for r in ok:
        for n in r["needs"]:
            e = by_rule.setdefault(n["rule"], {"rule": n["rule"], "title": n["title"],
                                               "severity": n["severity"], "fix": n["fix"],
                                               "libraries": 0, "occurrences": 0,
                                               "examples": []})
            e["libraries"] += 1
            e["occurrences"] += n["count"]
            if len(e["examples"]) < 5:
                e["examples"].append(r["repo"])
    blockers = sorted(by_rule.values(), key=lambda e: (-e["libraries"], e["rule"]))
    for e in blockers:
        e["share"] = round(e["libraries"] / len(ok), 3) if ok else 0
        # libraries whose ONLY non-auto need is this rule: what a shim for it would unlock
        e["sole_blocker_of"] = sum(
            1 for r in ok
            if {n["rule"] for n in r["needs"] if n["fix"] not in ("rule", "none")
                and n["severity"] != "info"} == {e["rule"]})
    tiers = Counter(r["tier"] for r in ok)
    markets: dict[str, Counter[str]] = {}
    for r in ok:
        for m in r.get("markets") or ["other"]:
            markets.setdefault(m, Counter())[r["tier"]] += 1
    return {"scanned": len(recs), "analyzed": len(ok),
            "errors": sum(1 for r in recs if "error" in r),
            "not_cmake": sum(1 for r in recs if r.get("tier") == "not-cmake"),
            "tiers": {t: tiers.get(t, 0) for t in TIERS},
            "markets": {m: dict(c) for m, c in sorted(markets.items())},
            "blockers": blockers,
            "libraries": sorted(ok, key=lambda r: (TIERS.index(r["tier"]), -int(r["stars"])))}


def to_markdown(atlas: dict[str, Any], top: int = 15) -> str:
    n = atlas["analyzed"]
    t = atlas["tiers"]

    def pct(k: int) -> str:
        return f"{100 * k / n:.0f}%" if n else "-"

    out = ["# QNX Port Atlas", "",
           f"{n} open-source C/C++ CMake libraries scanned against the QNX 8.0 SDP "
           f"({atlas['errors']} failed to scan, {atlas['not_cmake']} not CMake).", "",
           "| Predicted tier | Libraries | Share |", "|---|---|---|",
           f"| auto (rules fix everything) | {t['auto']} | {pct(t['auto'])} |",
           f"| assisted (known POSIX replacement) | {t['assisted']} | {pct(t['assisted'])} |",
           f"| deps (needs a library QNX lacks) | {t['deps']} | {pct(t['deps'])} |",
           f"| redesign (Linux-only design) | {t['redesign']} | {pct(t['redesign'])} |", "",
           "## What blocks QNX ports most", "",
           "| Linux dependency | Libraries | Share | Only blocker of | Fix | Examples |",
           "|---|---|---|---|---|---|"]
    for e in atlas["blockers"][:top]:
        out.append(f"| {e['title']} (`{e['rule']}`) | {e['libraries']} | "
                   f"{100 * e['share']:.0f}% | {e['sole_blocker_of']} | {e['fix']} | "
                   + ", ".join(e["examples"][:3]) + " |")
    out += ["", "## By market", "", "| Market | auto | assisted | deps | redesign |",
            "|---|---|---|---|---|"]
    for m, c in atlas["markets"].items():
        out.append(f"| {m} | {c.get('auto', 0)} | {c.get('assisted', 0)} | "
                   f"{c.get('deps', 0)} | {c.get('redesign', 0)} |")
    out += ["", "_Tiers are predictions from the scan; `portpilot port` verifies them by "
            "building and testing on QNX._", ""]
    return "\n".join(out)
