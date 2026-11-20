"""Measure what the local AI adds: rules vs. AI without QNX facts vs. AI with them, on the
real compile errors of libraries PortPilot has ported.

For each `portpilot port` output, the library's pristine upstream source is built once more
with its final port settings (VERBOSE, keep going), which records the qcc command of every
file. Each source file with a compile error is one case: its first error. Every condition
is then judged the way the port loop judges an AI edit: the file is recompiled alone with its
recorded command, and the fix counts only if that error is gone and the edited file has no
compile error it did not have before. The sandbox is restored after every attempt.

Conditions:
  rules     the knowledge-base rules (source edits, and compiler flags they set)
  bare      the local model, given the error and the code only
  grounded  the same model and prompt, plus the QNX facts the port loop gives it
            (knowledge base and SDP index: which header declares what, what QNX lacks)

Accepted AI edits are kept in the results with a `suspect` flag for edits that only delete
or disable code, so a person can review every one.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import ai as ai_mod
from . import fixes as fx
from .build import run_make
from .diagnostics import Diagnostic, parse
from .facts import qnx_facts
from .kb import KnowledgeBase
from .sdp_index import SdpIndex

_CMD = re.compile(r"^cd (?P<cwd>\S+) && (?P<cmd>\S*/(?:qcc|q\+\+) .* -c (?P<src>\S+))\s*$")
_OBJ = re.compile(r"(?<=\s)-o\s+\S+")
CONDITIONS = ("rules", "bare", "grounded")


@dataclass
class Case:
    library: str
    rel: str  # the file with the error, relative to the source root
    tu: str  # the translation unit that is compiled to see it
    cwd: str
    command: str
    error: dict[str, Any]  # the Diagnostic
    results: dict[str, dict[str, Any]] = field(default_factory=dict)


def _key(d: Diagnostic) -> tuple[str, str, str, str]:
    return (d.kind, Path(d.file).name, d.symbol, d.message)


def commands(log: str) -> dict[str, tuple[str, str]]:
    """Absolute source path -> (directory, qcc command) from a CMake VERBOSE build log."""
    out: dict[str, tuple[str, str]] = {}
    for ln in log.splitlines():
        if m := _CMD.match(ln.rstrip()):
            out[m.group("src")] = (m.group("cwd"), m.group("cmd"))
    return out


def compile_tu(case: Case, tmp: Path, extra: list[str] | None = None,
               timeout: float = 300) -> list[Diagnostic]:
    """Recompile the case's translation unit alone; its compile errors."""
    cmd = _OBJ.sub(f"-o {tmp / 'eval.o'}", case.command, count=1)
    if extra:
        cmd += " " + " ".join(extra)
    r = subprocess.run(["bash", "-c", f"cd {case.cwd} && {cmd}"], capture_output=True,
                       text=True, errors="replace", timeout=timeout)
    return [d for d in parse(r.stdout + r.stderr).diagnostics if d.tool == "cc"]


def _errors(diags: list[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diags if d.is_error]


def judge(case: Case, before: list[Diagnostic], after: list[Diagnostic],
          edited: set[str]) -> tuple[bool, str]:
    """The port loop's test: the error is gone and the edited files have no new error."""
    target = Diagnostic(**{**case.error, "included_from": tuple(case.error["included_from"])})
    keys_after = {_key(x) for x in _errors(after)}
    if _key(target) in keys_after:
        return False, "error still there"
    added = {k for k in keys_after - {_key(x) for x in _errors(before)} if k[1] in edited}
    if added:
        return False, "new errors: " + "; ".join(k[3] for k in list(added)[:2])
    return True, "error gone, no new error in the edited file"


def suspect(edits: list[dict[str, str]]) -> str:
    """Why an accepted edit may only hide the error ("" if it looks like a real change)."""
    for e in edits:
        new = [x.strip() for x in e["replace"].splitlines() if x.strip()]
        old = [x.strip() for x in e["search"].splitlines() if x.strip()]
        if any(x.startswith("#if 0") for x in new):
            return "disables code with #if 0"
        if len(new) < len(old) and set(new) <= set(old):
            return "only deletes lines"
        if any(x.startswith("//") and x.lstrip("/ ").strip() in old for x in new):
            return "comments code out"
    return ""


# ---- preparing the cases ---------------------------------------------------------------------
_BUILD_FILE = re.compile(r"(?:^|/)(?:CMakeLists\.txt|[^/]*\.cmake(?:\.in)?)$")


def keep_build_edits(ported: Path, src: Path) -> list[str]:
    """Copy the port's edits to CMake files into the pristine source, so it configures as
    the port does; the C/C++ files stay as upstream wrote them. Returns the copied files."""
    copied = []
    for p in sorted(ported.rglob("*")):
        rel = p.relative_to(ported).as_posix()
        if not p.is_file() or not _BUILD_FILE.search(rel) or rel.split("/")[0] in (".git",
                                                                                   "build"):
            continue
        dest = src / rel
        if not dest.is_file() or dest.read_bytes() != p.read_bytes():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            copied.append(rel)
    return copied
def prepare(run_dir: Path, eval_dir: Path, env: dict[str, str], *, jobs: int = 16,
            max_cases: int = 12, say: Callable[[str], None] = print) -> list[Case]:
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    lib = run["name"]
    upstream = run_dir / "work" / "upstream"
    port = Path(run.get("port_dir") or run_dir / lib)
    d = eval_dir / lib
    src, port_copy, stage = d / "src", d / "port", d / "stage"
    log = d / "build.log"
    if not log.is_file():
        shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(upstream, src, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "build"))
        keep_build_edits(run_dir / "work" / "src", src)
        shutil.copytree(port, port_copy, symlinks=True,
                        ignore=shutil.ignore_patterns("build", "Makefile.dnm"))
        if (run_dir / "work" / "stage").is_dir():
            shutil.copytree(run_dir / "work" / "stage", stage, symlinks=True)
        say(f"  {lib}: building the pristine source with the final port settings")
        b = run_make(port_copy, src, stage, log, jobs=jobs, testing=True, env=env,
                     timeout=3600)
        say(f"  {lib}: {'built' if b.ok else 'failed'} in {b.seconds:.0f}s, "
            f"{len(b.parsed.errors)} errors")
    text = log.read_text(encoding="utf-8", errors="replace")
    cmds = commands(text)
    cases: list[Case] = []
    seen: set[str] = set()
    for e in parse(text).errors:
        rel = fx.rel_in_root(src, e.file)
        if e.tool != "cc" or not rel or not e.line or rel in seen or e.kind == "driver-option":
            continue
        tu = e.file if e.file in cmds else ""
        if not tu and e.included_from:  # an error in a header: compile the file including it
            top = e.included_from[-1].rsplit(":", 1)[0]
            tu = next((s for s in cmds if s == top or s.endswith("/" + top)), "")
        if not tu:
            continue
        seen.add(rel)
        cwd, cmd = cmds[tu]
        cases.append(Case(lib, rel, tu, cwd, cmd, e.to_dict()))
        if len(cases) >= max_cases:
            break
    return cases


# ---- running the conditions ------------------------------------------------------------------
def _snapshot(root: Path, rels: set[str]) -> dict[str, str]:
    return {r: (root / r).read_text(encoding="utf-8", errors="surrogateescape")
            for r in rels if (root / r).is_file()}


def run_rules(case: Case, src: Path, before: list[Diagnostic], kb: KnowledgeBase,
              sdp: SdpIndex | None, include_dir: Path | None, tmp: Path) -> dict[str, Any]:
    implicit = {w.symbol: w for w in before if not w.is_error and w.kind == "implicit-decl"}
    found, _ = fx.from_diagnostics(_errors(before), kb, sdp, src, implicit, include_dir)
    flags = [f.setting.value for f in found
             if f.kind == "port" and f.setting and f.field == "cflags"]
    edits = [f for f in found if f.kind == "source"]
    orig = _snapshot(src, {f.path for f in edits})
    applied = [f for f in edits if fx.apply_source(src, f)]
    try:
        if not applied and not flags:
            return {"ok": False, "reason": "no rule applies", "rules": []}
        after = compile_tu(case, tmp, flags)
        ok, why = judge(case, before, after, {Path(f.path).name for f in applied}
                        | {Path(case.rel).name})
        return {"ok": ok, "reason": why,
                "rules": sorted({f.rule_id for f in applied}
                                | {f.rule_id for f in found if f.kind == "port"})}
    finally:
        ai_mod.revert(src, orig)


def run_ai(case: Case, src: Path, before: list[Diagnostic], ai: ai_mod.Provider,
           facts: list[str], tmp: Path, tries: int = 2) -> dict[str, Any]:
    d = Diagnostic(**{**case.error, "included_from": tuple(case.error["included_from"])})
    related = [x for x in _errors(before) if fx.rel_in_root(src, x.file) == case.rel
               and _key(x) != _key(d)]
    prompt = ai_mod.build_prompt(d, case.rel, src, facts, related)
    feedback = ""
    res: dict[str, Any] = {"ok": False, "tries": 0, "facts": facts}
    for k in range(1, tries + 1):
        res["tries"] = k
        t0 = time.perf_counter()
        try:
            reply = ai.chat(ai_mod.SYSTEM, prompt + feedback)
        except Exception as e:  # noqa: BLE001 (transport errors end this case)
            res.update(reason=f"AI unavailable: {e}")
            return res
        res["seconds"] = round(res.get("seconds", 0) + time.perf_counter() - t0, 1)
        prop = ai_mod.parse_reply(reply)
        if prop.no_fix or prop.error:
            res.update(reason=("NO_FIX: " + prop.no_fix) if prop.no_fix else prop.error)
            return res
        why = ai_mod.check_edits(prop, src, {case.rel})
        if why:
            res["reason"] = why
            feedback = f"\n\nYour previous answer was rejected: {why}. Try again."
            continue
        orig = ai_mod.apply_edits(prop, src)
        try:
            after = compile_tu(case, tmp)
        finally:
            ai_mod.revert(src, orig)
        ok, why = judge(case, before, after, {Path(e.path).name for e in prop.edits})
        edits = [{"path": e.path, "search": e.search, "replace": e.replace} for e in prop.edits]
        res.update(ok=ok, reason=why, edits=edits)
        if ok:
            res["suspect"] = suspect(edits)
            return res
        feedback = ("\n\nYour previous edit was applied and rebuilt but rejected: "
                    f"{why}. Try a different fix.")
    return res


def evaluate(run_dirs: list[Path], eval_dir: Path, env: dict[str, str], kb: KnowledgeBase,
             sdp: SdpIndex | None, ai: ai_mod.Provider | None, *,
             conditions: tuple[str, ...] = CONDITIONS, max_cases: int = 12, jobs: int = 16,
             say: Callable[[str], None] = print) -> list[Case]:
    eval_dir.mkdir(parents=True, exist_ok=True)
    qt = Path(env["QNX_TARGET"]) if env.get("QNX_TARGET") else None
    include_dir = qt / "usr" / "include" if qt else None
    tmp = eval_dir / "tmp"
    tmp.mkdir(exist_ok=True)
    out_json = eval_dir / "results.json"
    done: dict[tuple[str, str], Case] = {}
    if out_json.is_file():  # resume: keep finished cases
        for c in json.loads(out_json.read_text(encoding="utf-8")):
            done[(c["library"], c["rel"])] = Case(**c)
    cases: list[Case] = []
    libs: set[str] = set()
    for rd in run_dirs:
        if not (rd / "run.json").is_file():
            continue
        name = json.loads((rd / "run.json").read_text(encoding="utf-8"))["name"]
        if name in libs or not (rd / "work" / "upstream").is_dir():
            continue  # the same library from another run, or no pristine source
        libs.add(name)
        for c in prepare(rd, eval_dir, env, jobs=jobs, max_cases=max_cases, say=say):
            prev = done.get((c.library, c.rel))
            if prev and all(k in prev.results for k in conditions):
                cases.append(prev)
                continue
            src = eval_dir / c.library / "src"
            before = compile_tu(c, tmp)
            target = Diagnostic(**{**c.error, "included_from": tuple(c.error["included_from"])})
            if _key(target) not in {_key(x) for x in _errors(before)}:
                continue  # not reproduced by compiling the file alone
            if prev:
                c.results = prev.results
            for cond in conditions:
                if cond in c.results:
                    continue
                if cond == "rules":
                    c.results[cond] = run_rules(c, src, before, kb, sdp, include_dir, tmp)
                elif ai is not None:
                    facts = (qnx_facts(target, kb, sdp, qt,
                                       (src / c.rel).read_text(encoding="utf-8",
                                                               errors="replace"))
                             if cond == "grounded" else [])
                    c.results[cond] = run_ai(c, src, before, ai, facts, tmp)
            say(f"  {c.library}: {c.rel}:{c.error['line']} {c.error['message'][:60]} -> "
                + " ".join(f"{k}={'ok' if v['ok'] else 'no'}" for k, v in c.results.items()))
            cases.append(c)
            out_json.write_text(json.dumps([asdict(x) for x in cases], indent=1),
                                encoding="utf-8")
    out_json.write_text(json.dumps([asdict(x) for x in cases], indent=1), encoding="utf-8")
    return cases


def summary(cases: list[Case], model: str = "") -> str:
    n = len(cases)
    if not n:
        return "No cases.\n"

    def ok(c: Case, k: str) -> bool:
        return bool(c.results.get(k, {}).get("ok"))

    def pct(x: int, m: int) -> str:
        return f"{x}/{m} ({100 * x / m:.0f}%)" if m else "0/0"

    rows = [("Rules only", sum(ok(c, "rules") for c in cases)),
            (f"AI alone, no QNX facts{f' ({model})' if model else ''}",
             sum(ok(c, "bare") for c in cases)),
            ("AI alone, with QNX facts", sum(ok(c, "grounded") for c in cases)),
            ("Rules, then AI with QNX facts",
             sum(ok(c, "rules") or ok(c, "grounded") for c in cases))]
    left = [c for c in cases if not ok(c, "rules")]
    sus = [c for c in cases for k in ("bare", "grounded")
           if ok(c, k) and c.results[k].get("suspect")]
    libs = sorted({c.library for c in cases})
    lines = [f"{n} compile errors (one per file) from {len(libs)} libraries: "
             + ", ".join(libs) + ".", "",
             "| Condition | Errors fixed (verified by recompiling) |", "|---|---|"]
    lines += [f"| {name} | {pct(x, n)} |" for name, x in rows]
    lines += ["", f"Of the {len(left)} errors no rule fixes: AI without facts fixes "
              f"{pct(sum(ok(c, 'bare') for c in left), len(left))}, with facts "
              f"{pct(sum(ok(c, 'grounded') for c in left), len(left))}.",
              f"Accepted AI edits flagged for review (only delete or disable code): {len(sus)}."]
    return "\n".join(lines) + "\n"
