"""`portpilot port`: scan -> scaffold -> build -> fix -> rebuild, until it builds or we're stuck.

Layout of the output directory:
    <out>/<name>/          the port folder (build-files/ports/<name>), ready to submit
    <out>/work/src/        working copy of the source that the fixes are applied to
    <out>/work/stage/      install root (INSTALL_ROOT_nto)
    <out>/logs/            build-<n>.log for every attempt
    <out>/run.json         what happened, for the report
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import fixes as fx
from . import kb as kb_mod
from .build import BuildResult, build_dir, clean, run_make, sdp_env
from .kb import KnowledgeBase
from .qnxtests import generate as gen_tests
from .scaffold import PortSpec, Setting, initial_spec, render, render_readme, write
from .scan import scan_project
from .sdp_index import SdpIndex

_SKIP = shutil.ignore_patterns(".git", "build", "build-*", "cmake-build-*", "_build", "out")


def say_flush(msg: str) -> None:
    print(msg, flush=True)


def _git(args: list[str], cwd: Path, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)
    return r.stdout.strip()


def fetch(src: str, work: Path) -> tuple[Path, str, str]:
    """Clone a URL (or use a local tree). Returns (tree, upstream url, short commit)."""
    if "://" in src or src.startswith("git@"):
        dest = work / "upstream"
        if not dest.exists():
            subprocess.run(["git", "clone", "-q", "--depth", "1", "--recurse-submodules",
                            "--shallow-submodules", src, str(dest)], check=True)
        return dest, src, _git(["rev-parse", "--short", "HEAD"], dest)
    p = Path(src).resolve()
    url = commit = ""
    if (p / ".git").exists():
        url = _git(["remote", "get-url", "origin"], p, check=False)
        commit = _git(["rev-parse", "--short", "HEAD"], p, check=False)
    return p, url, commit


def working_copy(tree: Path, dest: Path) -> Path:
    """Copy the source (without .git and build dirs) and commit it, so fixes become a diff."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(tree, dest, ignore=_SKIP, symlinks=True)
    _git(["init", "-q"], dest)
    _git(["add", "-A"], dest)
    _git(["-c", "user.name=portpilot", "-c", "user.email=portpilot@localhost", "commit", "-q",
          "--no-gpg-sign", "-m", "upstream"], dest)
    return dest


def diff(dest: Path) -> str:
    return subprocess.run(["git", "diff", "--no-color"], cwd=dest, capture_output=True,
                          text=True, check=True).stdout


@dataclass
class Attempt:
    n: int
    ok: bool
    seconds: float
    phase: str
    log: str
    errors: list[dict[str, Any]] = field(default_factory=list)
    applied: list[dict[str, Any]] = field(default_factory=list)
    unfixed: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PortRun:
    name: str
    source: str
    upstream: str
    commit: str
    port_dir: str
    ok: bool = False
    stopped: str = ""  # why the loop stopped, if not ok
    pre_fixes: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    patch_stat: str = ""
    elapsed_s: float = 0.0
    scan_summary: dict[str, Any] = field(default_factory=dict)
    settings: list[dict[str, str]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def save_spec(spec: PortSpec, path: Path) -> None:
    path.write_text(json.dumps(asdict(spec), indent=2), encoding="utf-8")


def load_spec(path: Path) -> PortSpec:
    d = json.loads(path.read_text(encoding="utf-8"))
    for k in ("options", "cmake_args", "ldflags", "cflags"):
        d[k] = [Setting(**s) for s in d.get(k, [])]
    return PortSpec(**d)


def changes_from_run(run: dict[str, Any]) -> list[tuple[str, str, str]]:
    rows: dict[tuple[str, str], str] = {}
    fixes = [*run.get("pre_fixes", []), *(f for a in run.get("attempts", [])
                                          for f in a.get("applied", []))]
    for f in fixes:
        if f.get("kind") == "source":
            rows.setdefault((f["path"], f["title"]), f["reason"])
    return [(p, t, w) for (p, t), w in rows.items()]


def test_dir(out: Path, name: str, arch: str = "x86_64") -> Path:
    return out / "work" / "stage" / arch / "usr" / "local" / "bin" / f"{name}_tests"


def record_tests(out: Path, tr: Any, arch: str = "x86_64") -> dict[str, Any]:
    """Store a target test run in run.json and put the result into the port README."""
    run: dict[str, Any] = json.loads((out / "run.json").read_text(encoding="utf-8"))
    run["target_tests"] = {
        "host": tr.host, "ok": tr.ok, "passed": tr.passed, "failed": tr.failed,
        "timeouts": tr.timeouts, "total": tr.total, "seconds": tr.seconds,
        "finished": tr.finished, "output": tr.output, "logs_dir": tr.logs_dir,
        "results": [asdict(r) for r in tr.results]}
    (out / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    spec = load_spec(out / "spec.json")
    result = f"{tr.passed}/{tr.total} test programs pass on QNX"
    if tr.failed:
        bad = ", ".join(r.name for r in tr.results if r.status != "PASS")[:200]
        result += f" (failing: {bad})"
    readme = render_readme(spec, results={"Result": result},
                           changes=changes_from_run(run))
    (Path(run["port_dir"]) / "README.md").write_text(readme, encoding="utf-8")
    return run


def _fix_dict(f: fx.Fix) -> dict[str, Any]:
    d: dict[str, Any] = {"rule": f.rule_id, "kind": f.kind, "title": f.title,
                         "reason": f.reason}
    if f.kind == "source":
        d.update(path=f.path, line=f.line, old=f.old, new=f.new)
    elif f.setting:
        d.update(setting=f.setting.value)
    return d


def _unfixed_dict(u: fx.Unfixed) -> dict[str, Any]:
    d = u.diagnostic
    return {"kind": d.kind, "symbol": d.symbol, "location": d.location(),
            "message": d.message, "rule": u.rule_id, "hint": u.hint}


def _changes_table(applied: list[fx.Fix]) -> list[tuple[str, str, str]]:
    rows: dict[tuple[str, str], str] = {}
    for f in applied:
        if f.kind == "source":
            rows.setdefault((f.path, f.title), f.reason)
    return [(p, t, w) for (p, t), w in rows.items()]


def run_port(src: str, out: Path, *, name: str | None = None, arch: str = "x86_64",
             jobs: int = 8, max_attempts: int = 6, sdp: SdpIndex | None = None,
             kb: KnowledgeBase | None = None, do_build: bool = True, testing: bool = True,
             env: dict[str, str] | None = None,
             say: Callable[[str], None] = say_flush) -> PortRun:
    t0 = time.perf_counter()
    kb = kb or kb_mod.load()
    out = out.resolve()
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    tree, upstream, commit = fetch(src, work)
    name = name or (tree.name if tree.name != "upstream" else src.rstrip("/").split("/")[-1])
    name = name.removesuffix(".git")
    srcw = working_copy(tree, work / "src")
    port_dir = out / name
    run = PortRun(name=name, source=src, upstream=upstream, commit=commit,
                  port_dir=str(port_dir))

    # 1. scan + fixes known before building
    say(f"[1/4] scan {name}")
    spec: PortSpec = initial_spec(srcw, name, upstream, commit)
    scan = scan_project(srcw, kb, sdp, arch)
    pre = fx.from_findings(scan.findings, kb, srcw)
    applied: list[fx.Fix] = []
    for f in pre:
        if fx.apply(f, spec, srcw):
            applied.append(f)
            run.pre_fixes.append(_fix_dict(f))
            say(f"      fix ({f.rule_id}): {f.title}" + (f"  [{f.path}:{f.line}]" if f.path
                                                         else ""))
    run.scan_summary = {"files": scan.files_scanned, "findings": len(scan.findings),
                        "sdp_index": scan.sdp_index_used}

    # 2. scaffold
    say(f"[2/4] scaffold {port_dir}")
    write(port_dir, render(spec))
    if not do_build:
        run.stopped = "build skipped (--no-build)"
        return _finish(run, spec, srcw, port_dir, applied, None, out, t0)

    # 3. build loop
    env = env if env is not None else sdp_env()
    stage = work / "stage"
    last: BuildResult | None = None
    for n in range(1, max_attempts + 1):
        say(f"[3/4] build attempt {n}")
        clean(port_dir, arch)
        last = run_make(port_dir, srcw, stage, out / "logs" / f"build-{n}.log", arch=arch,
                        jobs=jobs, testing=testing, env=env)
        att = Attempt(n=n, ok=last.ok, seconds=round(last.seconds, 1), phase=last.phase,
                      log=str(last.log),
                      errors=[d.to_dict() for d in last.parsed.errors[:50]])
        run.attempts.append(att)
        if last.ok:
            say(f"      built in {last.seconds:.0f}s")
            break
        errs = last.parsed.errors
        say(f"      failed at {last.phase}: {len(errs)} errors"
            + (f", first: {errs[0].location()} {errs[0].message}" if errs else ""))
        found, unfixed = fx.from_diagnostics(errs, kb, sdp, srcw)
        new = [f for f in found if fx.apply(f, spec, srcw)]
        att.applied = [_fix_dict(f) for f in new]
        att.unfixed = [_unfixed_dict(u) for u in unfixed]
        for f in new:
            say(f"      fix ({f.rule_id}): {f.title}" + (f"  [{f.path}:{f.line}]" if f.path
                                                         else ""))
        applied += new
        if not new:
            run.stopped = "no rule fixes the remaining errors" if errs else \
                f"build failed (rc={last.rc}) without a parsable error; see {last.log}"
            for u in unfixed[:10]:
                say(f"      unfixed: {u.diagnostic.location()} {u.diagnostic.message}"
                    f"  -> {u.hint}")
            break
        write(port_dir, render(spec))
    else:
        run.stopped = f"still failing after {max_attempts} attempts"
    return _finish(run, spec, srcw, port_dir, applied, last, out, t0, testing=testing,
                   env=env, jobs=jobs, arch=arch)


def _finish(run: PortRun, spec: PortSpec, srcw: Path, port_dir: Path, applied: list[fx.Fix],
            last: BuildResult | None, out: Path, t0: float, *, testing: bool = True,
            env: dict[str, str] | None = None, jobs: int = 8, arch: str = "x86_64") -> PortRun:
    run.ok = bool(last and last.ok)
    patch = diff(srcw)
    spec.has_patch = bool(patch)
    if patch:
        run.patch_stat = subprocess.run(["git", "diff", "--shortstat"], cwd=srcw,
                                        capture_output=True, text=True).stdout.strip()
    qnxtests = None
    if run.ok and testing:
        qnxtests, tests = gen_tests(build_dir(port_dir, arch), spec.name)
        run.tests = [t.name for t in tests]
    files = render(spec, qnxtests=qnxtests, patch=patch or None,
                   readme=render_readme(spec, changes=_changes_table(applied)))
    write(port_dir, files)
    if qnxtests and env is not None:
        # re-install so that qnxtests.sh lands next to the test binaries (incremental)
        run_make(port_dir, srcw, out / "work" / "stage", out / "logs" / "install-tests.log",
                 arch=arch, jobs=jobs, testing=True, env=env, keep_going=False)
    run.settings = [{"value": s.value, "reason": s.reason, "rule": s.rule}
                    for s in (*spec.cmake_args, *spec.ldflags, *spec.cflags, *spec.options)]
    run.elapsed_s = round(time.perf_counter() - t0, 1)
    (out / "run.json").write_text(run.to_json(), encoding="utf-8")
    save_spec(spec, out / "spec.json")
    return run


# ---- test on the target, fix what a rule explains, rebuild, test again ----------------------
def rerender(out: Path, spec: PortSpec) -> Path:
    """Re-write the port folder from spec, keeping the generated qnxtests.sh and patch."""
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    port_dir = Path(run["port_dir"])
    tests_sh = port_dir / "qnxtests.sh"
    patch = port_dir / "patches" / "qnx.patch"
    files = render(spec, qnxtests=tests_sh.read_text() if tests_sh.exists() else None,
                   patch=patch.read_text() if patch.exists() else None,
                   readme=render_readme(spec, changes=changes_from_run(run)))
    write(port_dir, files)
    save_spec(spec, out / "spec.json")
    return port_dir


def test_and_fix(out: Path, target: Any, *, env: dict[str, str], jobs: int = 8,
                 arch: str = "x86_64", timeout_scale: float = 3,
                 build_files: Path | None = None, max_rounds: int = 2,
                 say: Callable[[str], None] = say_flush) -> Any:
    from .deps import ensure_muslflt
    from .target import run_tests
    from .testfail import classify

    out = out.resolve()
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    name = run["name"]
    srcw = out / "work" / "src"
    history: list[dict[str, Any]] = []
    tr = None
    for rnd in range(max_rounds + 1):
        tr = run_tests(target, test_dir(out, name, arch), name, out / "logs" / f"tests-{rnd + 1}",
                       timeout_scale=timeout_scale)
        say(f"      tests round {rnd + 1}: {tr.passed}/{tr.total} pass"
            + (f", failing: {', '.join(r.name for r in tr.results if r.status != 'PASS')}"
               if tr.failed else ""))
        run = record_tests(out, tr, arch)
        entry: dict[str, Any] = {"round": rnd + 1, "passed": tr.passed, "total": tr.total,
                                 "fixes": []}
        history.append(entry)
        if tr.ok or rnd == max_rounds:
            break
        found: dict[str, tuple[str, str]] = {}
        for r in tr.results:
            if r.status == "PASS":
                continue
            log = Path(tr.logs_dir) / f"{r.name}.out"
            text = log.read_text(errors="replace") if log.exists() else ""
            for c in classify(text):
                found.setdefault(c.rule_id, (r.name, c.evidence))
        spec = load_spec(out / "spec.json")
        applied = []
        if "float-format" in found and not spec.muslflt:
            test, ev = found["float-format"]
            say(f"      {test}: float output differs from glibc ({ev}) -> rule float-format")
            err = ensure_muslflt(out / "work" / "stage", env, out / "work",
                                 out / "logs" / "muslflt-build.log", build_files, arch, jobs)
            if err:
                say(f"      cannot apply float-format: {err}")
            else:
                spec.muslflt = True
                applied.append({"rule": "float-format", "test": test, "evidence": ev,
                                "title": "link muslflt (project_hooks.cmake)"})
        if not applied:
            say("      no rule explains the remaining failures; see the logs in "
                f"{tr.logs_dir}")
            break
        entry["fixes"] = applied
        for a in applied:
            say(f"      fix ({a['rule']}): {a['title']}")
        port_dir = rerender(out, spec)
        clean(port_dir, arch)
        b = run_make(port_dir, srcw, out / "work" / "stage",
                     out / "logs" / f"rebuild-tests-{rnd + 1}.log", arch=arch, jobs=jobs,
                     testing=True, env=env)
        say(f"      rebuilt: {'ok' if b.ok else 'FAILED'} in {b.seconds:.0f}s")
        if not b.ok:
            break
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    run["test_rounds"] = history
    (out / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    return tr
