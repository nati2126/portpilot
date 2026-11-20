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
import re
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
from .deps import find_build_files
from .kb import KnowledgeBase
from .matrix import to_json as matrix_json
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


_PRERELEASE = re.compile(r"(?i)rc|alpha|beta|pre|dev|preview|snapshot|nightly|test")
_VERSION_TAG = re.compile(r"^[A-Za-z_.-]*\d+(?:[._]\d+)+$")


def latest_release_tag(url: str) -> str:
    """The highest version-like tag that is not a pre-release, or "" (then the default
    branch is used). The official QNX ports also build a release tag, not master.
    A network failure is an error, not "no tags": that would silently port master."""
    from .build import BuildError
    for attempt in range(3):
        try:
            r = subprocess.run(["git", "ls-remote", "--tags", "--refs", url],
                               capture_output=True, text=True, timeout=180, check=False)
            if r.returncode == 0:
                break
            why = r.stderr.strip()[:200]
        except subprocess.TimeoutExpired:
            why = "timed out"
        if attempt == 2:
            raise BuildError(f"cannot list the tags of {url} ({why}); retry, or pass "
                             "--ref TAG (or --ref HEAD)")
    best: tuple[tuple[int, ...], str] = ((), "")
    for ln in r.stdout.splitlines():
        tag = ln.rpartition("refs/tags/")[2]
        if _VERSION_TAG.match(tag) and not _PRERELEASE.search(tag):
            # compare the numbers only: zlib-ng has both 2.2.2 and zlib's old v1.2.11
            best = max(best, (tuple(int(n) for n in re.findall(r"\d+", tag)), tag))
    return best[1]


def fetch(src: str, work: Path, ref: str | None = None) -> tuple[Path, str, str]:
    """Clone a URL (or use a local tree). Returns (tree, upstream url, ref): the tag that was
    cloned, else the short commit. `ref`: None = latest release tag, "HEAD" = default branch.
    """
    if "://" in src or src.startswith("git@"):
        dest = work / "upstream"
        tag = latest_release_tag(src) if ref is None else ("" if ref == "HEAD" else ref)
        for _ in range(3 if not dest.exists() else 0):  # a busy network resets connections
            r = subprocess.run(["git", "clone", "-q", "--depth", "1", "--recurse-submodules",
                                "--shallow-submodules", *(["-b", tag] if tag else []), src,
                                str(dest)], capture_output=True, text=True, check=False)
            if r.returncode == 0:
                break
            shutil.rmtree(dest, ignore_errors=True)  # a partial clone would be reused
        if not dest.exists():
            from .build import BuildError
            raise BuildError(f"cannot clone {src}{f' at {tag}' if tag else ''} (3 tries): "
                             f"{r.stderr.strip()[-300:]}")
        return dest, src, tag or _git(["rev-parse", "--short", "HEAD"], dest)
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
    ai: list[dict[str, Any]] = field(default_factory=list)  # every AI attempt, kept or not
    # behavior differences the scan found in library code (they show up as test failures)
    scan_warnings: list[dict[str, Any]] = field(default_factory=list)
    tests_skipped: str = ""  # why the library's tests were not built, if they were not

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
        "localhost": getattr(tr, "localhost", ""), "services": getattr(tr, "services", []),
        "cases": list(c) if (c := tr.cases()) else None,
        "results": [asdict(r) for r in tr.results]}
    (out / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    spec = load_spec(out / "spec.json")
    readme = render_readme(spec, results={"Result": result_line(run["target_tests"])},
                           changes=changes_from_run(run))
    (Path(run["port_dir"]) / "README.md").write_text(readme, encoding="utf-8")
    _report(out)
    return run


def result_line(tt: dict[str, Any]) -> str:
    """The port README's Result row, from a recorded target test run."""
    result = f"{tt['passed']}/{tt['total']} test programs pass on QNX"
    if c := tt.get("cases"):
        result = f"{c[0]}/{c[1]} test cases pass on QNX ({result})"
    if tt.get("failed"):
        bad = ", ".join(r["name"] for r in tt.get("results", [])
                        if r["status"] != "PASS")[:200]
        result += f" (failing: {bad})"
    if lh := tt.get("localhost"):
        result += f"; the tests' localhost services ran on the host ({lh})"
    if svcs := tt.get("services"):
        result += "; services run on the QNX target meanwhile: " + ", ".join(
            f"`{s}`" for s in svcs)
    return result


def refresh_port(out: Path) -> Path:
    """Re-render the port folder with the current templates (keeping its patch, runner and
    recorded result), so a contribution never ships files from an older PortPilot."""
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    port_dir = rerender(out, load_spec(out / "spec.json"))
    if tt := run.get("target_tests"):
        readme = render_readme(load_spec(out / "spec.json"),
                               results={"Result": result_line(tt)},
                               changes=changes_from_run(run))
        (port_dir / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    return port_dir


def _src_url(kb: KnowledgeBase, rule_id: str) -> str:
    srcs = kb.rule(rule_id).sources
    return next((kb.sources[s].url for s in srcs if not kb.sources[s].url.startswith("http")),
                kb.sources[srcs[0]].url)


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
             jobs: int = 8, max_attempts: int = 10, sdp: SdpIndex | None = None,
             kb: KnowledgeBase | None = None, do_build: bool = True, testing: bool = True,
             env: dict[str, str] | None = None, ai: Any = None,
             build_files: Path | None = None, ref: str | None = None,
             say: Callable[[str], None] = say_flush) -> PortRun:
    t0 = time.perf_counter()
    kb = kb or kb_mod.load()
    out = out.resolve()
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    tree, upstream, commit = fetch(src, work, ref)
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
    out.mkdir(parents=True, exist_ok=True)
    (out / "matrix.json").write_text(matrix_json(scan, kb), encoding="utf-8")
    for fd in scan.findings:
        r = kb.rule(fd.rule_id)
        if r.severity == "warn" and fd.guard == "none" and fd.area == "lib":
            run.scan_warnings.append({"rule": r.id, "title": r.title,
                                      "where": f"{fd.path}:{fd.line}",
                                      "source": _src_url(kb, r.id)})

    # 2. scaffold
    say(f"[2/4] scaffold {port_dir}")
    write(port_dir, render(spec))
    if not do_build:
        run.stopped = "build skipped (--no-build)"
        return _finish(run, spec, srcw, port_dir, applied, None, out, t0)

    # 3. build loop: rules first, then (optionally) the verified AI step
    env = env if env is not None else sdp_env()
    stage = work / "stage"
    last: BuildResult | None = None
    need_clean = True
    implicit: dict[str, Any] = {}  # implicit-decl warnings seen in any attempt (by symbol)
    cmake_state = [s.value for s in spec.cmake_args]
    tried_deps: set[str] = set()
    force_clean = False
    bf = build_files if build_files is not None else find_build_files()
    include_dir = (Path(env["QNX_TARGET"]) / "usr" / "include") if env.get("QNX_TARGET") \
        else None
    for n in range(1, max_attempts + 1):
        say(f"[3/4] build attempt {n}")
        if need_clean:
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
        implicit.update({w.symbol: w for w in last.parsed.warnings if w.kind == "implicit-decl"})
        say(f"      failed at {last.phase}: {len(errs)} errors"
            + (f", first: {errs[0].location()} {errs[0].message}" if errs else ""))
        found, unfixed = fx.from_diagnostics(errs, kb, sdp, srcw, implicit, include_dir)
        new = [f for f in found if fx.apply(f, spec, srcw)]
        built_deps = _build_deps(errs, tried_deps, stage, env, out, bf, arch, jobs, say)
        if built_deps:
            spec.deps = sorted({*spec.deps, *(p for p, _ in built_deps)})
            new += [f for _, f in built_deps]
            force_clean = True
        built_pkgs = {f.path for _, f in built_deps}  # the CMake package names
        test_only = [d for d in errs if d.kind == "missing-package"
                     and d.symbol.lower() in TEST_FRAMEWORKS and d.symbol not in built_pkgs]
        bundled = [d for d in errs if _bundled_test_framework(d)]
        if (test_only or bundled) and testing:
            # a test framework QNX cannot provide: build the library without its tests
            testing = False
            if test_only:
                pkg = test_only[0].symbol
                from .deps import official_port
                why = (f"its official QNX port did not build (logs/dep-{pkg}.log)"
                       if official_port(pkg, bf) else "which has no official QNX port")
                run.tests_skipped = f"tests not built: they need {pkg}, {why}"
            else:
                d0 = bundled[0]
                pkg = _bundled_test_framework(d0)
                run.tests_skipped = (
                    f"tests not built: they include <{d0.symbol}>, which QNX does not have"
                    if d0.kind == "missing-header" else
                    f"tests not built: the {pkg} the project downloads for its tests does "
                    "not build for QNX")
            say(f"      {run.tests_skipped}; building the library only")
            new.append(fx.Fix("tests-need-framework", "dep", f"build without tests ({pkg})",
                              run.tests_skipped))
            force_clean = True
        unfixed = [u for u in unfixed
                   if not _dep_handled(u.diagnostic, built_pkgs, tests_off=not testing)]
        for f in new:
            say(f"      fix ({f.rule_id}): {f.title}" + (f"  [{f.path}:{f.line}]" if f.path
                                                         else ""))
        if not new and ai is not None and unfixed:
            new, last = _ai_round(ai, unfixed, last, kb, sdp, srcw, port_dir, stage, out, run,
                                  implicit=implicit,
                                  env=env, arch=arch, jobs=jobs, testing=testing, say=say)
            fixed_files = {f.path for f in new}
            unfixed = [u for u in unfixed if _rel(srcw, u.diagnostic.file) not in fixed_files]
            if last.ok:
                att.applied = [_fix_dict(f) for f in new]
                applied += new
                say(f"      built after AI fixes in {last.seconds:.0f}s")
                break
        att.applied = [_fix_dict(f) for f in new]
        att.unfixed = [_unfixed_dict(u) for u in unfixed]
        applied += new
        if not new:
            run.stopped = "no rule fixes the remaining errors" if errs else \
                f"build failed (rc={last.rc}) without a parsable error; see {last.log}"
            for u in unfixed[:10]:
                say(f"      unfixed: {u.diagnostic.location()} {u.diagnostic.message}"
                    f"  -> {u.hint}")
            break
        write(port_dir, render(spec))
        state = [s.value for s in spec.cmake_args]
        need_clean = state != cmake_state or force_clean  # CMake caches results: start over
        cmake_state = state
        force_clean = False
    else:
        run.stopped = f"still failing after {max_attempts} attempts"
    return _finish(run, spec, srcw, port_dir, applied, last, out, t0, testing=testing,
                   env=env, jobs=jobs, arch=arch)


def verify_archs(out: Path, *, tested: str = "x86_64", jobs: int = 8, max_attempts: int = 4,
                 env: dict[str, str] | None = None, build_files: Path | None = None,
                 say: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """Build the final port for every architecture besides the tested one, with tests, as
    build-files CI does (it builds every nto-* folder). Rule fixes are applied (F-016: char
    is unsigned on aarch64); if they change the port, the tested arch is rebuilt to show it
    still builds. An arch that still fails is marked Makefile.dnm, as official ports do.
    Results go to run.json "arch_builds"."""
    from .deps import ensure_muslflt, ensure_port
    from .scaffold import ARCH_DIRS

    env = env if env is not None else sdp_env()
    bf = build_files if build_files is not None else find_build_files()
    kb = kb_mod.load()
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    spec = load_spec(out / "spec.json")
    port_dir, srcw, stage = Path(run["port_dir"]), out / "work" / "src", out / "work" / "stage"
    include_dir = Path(env["QNX_TARGET"]) / "usr" / "include" if env.get("QNX_TARGET") else None
    results: list[dict[str, Any]] = []
    changed = False
    for arch in [a for a in ARCH_DIRS if a != tested]:
        res: dict[str, Any] = {"arch": arch, "ok": False, "attempts": 0, "fixes": []}
        results.append(res)
        say(f"      {arch}: building the port as build-files CI will")
        why = ""
        if spec.muslflt:
            why = ensure_muslflt(stage, env, out / "work",
                                 out / "logs" / f"muslflt-{arch}.log", bf, arch, jobs)
        for dep in spec.deps:
            if not why:
                why = ensure_port(dep, stage, env, out / "logs" / f"dep-{dep}-{arch}.log",
                                  bf, arch=arch, jobs=jobs)[1]
        if why:
            res["reason"] = f"a dependency does not build for {arch}: {why}"
        dnm = port_dir / ARCH_DIRS[arch] / "Makefile.dnm"
        dnm.unlink(missing_ok=True)
        for n in range(1, max_attempts + 1):
            if why:
                break
            res["attempts"] = n
            clean(port_dir, arch)
            b = run_make(port_dir, srcw, stage, out / "logs" / f"build-{arch}-{n}.log",
                         arch=arch, jobs=jobs, testing=True, env=env)
            if b.ok:
                res["ok"] = True
                say(f"      {arch}: built in {b.seconds:.0f}s")
                break
            found, _unfixed = fx.from_diagnostics(b.parsed.errors, kb, None, srcw, {},
                                                  include_dir)
            new = [f for f in found if fx.apply(f, spec, srcw)]
            if not new:
                e = b.parsed.errors
                res["reason"] = (f"{e[0].location()} {e[0].message}" if e else
                                 f"build failed (rc={b.rc}); see {b.log}")
                break
            for f in new:
                say(f"      {arch}: fix ({f.rule_id}): {f.title}")
            res["fixes"] += [_fix_dict(f) for f in new]
            changed = True
            rerender(out, spec)
        if not res["ok"]:
            say(f"      {arch}: does not build ({res.get('reason', '')[:100]}); "
                "marked Makefile.dnm")
            dnm.write_text("", encoding="utf-8")
    if changed:  # the tested arch must still build with the new settings
        clean(port_dir, tested)
        b = run_make(port_dir, srcw, stage, out / "logs" / f"build-{tested}-recheck.log",
                     arch=tested, jobs=jobs, testing=True, env=env)
        results.append({"arch": tested, "ok": b.ok, "recheck": True})
        say(f"      {tested}: rebuilt with the new settings: {'ok' if b.ok else 'FAILED'}")
    run["arch_builds"] = results
    (out / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    return results


TEST_FRAMEWORKS = {"catch2", "gtest", "googletest", "gmock", "cmocka", "check", "doctest",
                   "unity", "cppunit", "cunit", "criterion", "cpputest",
                   "boost_unit_test_framework"}


_STAMP = re.compile(r"/(?P<name>[\w.+-]+)-stamp/")


_TEST_HEADER = re.compile(r"^(?:CUnit|gtest|gmock|catch2|criterion|CppUTest|doctest|"
                          r"boost/test)/|^(?:catch\.hpp|check\.h|cmocka\.h|unity\.h|"
                          r"doctest\.h)$")


def _bundled_test_framework(d: Any) -> str:
    """The name of a test framework the project builds itself (CMake ExternalProject) whose
    build failed, e.g. civetweb's check-unit-test-framework, or whose header the tests
    include without CMake looking for it (libcoap: <CUnit/CUnit.h>). Else ""."""
    if d.kind == "missing-header" and _TEST_HEADER.search(d.symbol):
        return str(d.symbol).split("/")[0].removesuffix(".h").removesuffix(".hpp")
    m = _STAMP.search(d.file) if d.kind == "cmake-error" else None
    if not m:
        return ""
    name = m.group("name")
    words = set(re.split(r"[-_.]", name.lower()))
    return name if words & TEST_FRAMEWORKS or "test" in words else ""


def _dep_handled(d: Any, built_pkgs: set[str], *, tests_off: bool) -> bool:
    """A missing package that is now built, or a test framework while tests are off."""
    if tests_off and _bundled_test_framework(d):
        return True
    return d.kind == "missing-package" and (
        d.symbol in built_pkgs or (tests_off and d.symbol.lower() in TEST_FRAMEWORKS))


def _build_deps(errs: list[Any], tried: set[str], stage: Path, env: dict[str, str],
                out: Path, bf: Path | None, arch: str, jobs: int,
                say: Callable[[str], None]) -> list[tuple[str, fx.Fix]]:
    """Build the official QNX port of each package CMake could not find (once each).
    Returns (port name, fix) for each port built."""
    from .deps import ensure_port
    built: list[tuple[str, fx.Fix]] = []
    for d in errs:
        pkg = d.symbol
        if d.kind != "missing-package" or not pkg or pkg in tried:
            continue
        tried.add(pkg)
        say(f"      dependency {pkg}: building the official QNX port")
        port, why = ensure_port(pkg, stage, env, out / "logs" / f"dep-{pkg}.log", bf,
                                arch=arch, jobs=jobs)
        if why:
            say(f"      dependency {pkg}: {why}")
            continue
        say(f"      fix (dep-official-port): built {port} from qnx-ports into the stage")
        built.append((port, fx.Fix("dep-official-port", "dep",
                                   f"build dependency {port} from qnx-ports into the stage",
                                   f"CMake needs {pkg}; QNX has an official port of it",
                                   path=pkg)))
    return built


def _rel(root: Path, file: str) -> str:
    return fx.rel_in_root(root, file) or ""


def _err_key(d: Any) -> tuple[str, str, str, str]:
    return (d.kind, Path(d.file).name, d.symbol, d.message)


def _ai_round(ai: Any, unfixed: list[fx.Unfixed], last: BuildResult, kb: KnowledgeBase,
              sdp: SdpIndex | None, srcw: Path, port_dir: Path, stage: Path, out: Path,
              run: PortRun, *, env: dict[str, str], arch: str, jobs: int, testing: bool,
              say: Callable[[str], None], implicit: dict[str, Any] | None = None,
              max_errors: int = 4,
              tries: int = 2) -> tuple[list[fx.Fix], BuildResult]:
    """Ask the model about each unfixed compile error (first per file); keep verified edits.

    An edit is kept only if, after an incremental rebuild, that error is gone and the edited
    file has no compile error it did not have before. (Link errors that appear once a file
    compiles are newly visible, not caused by the edit.) Otherwise the file is restored.
    """
    from . import ai as ai_mod
    from .diagnostics import Diagnostic
    from .facts import qnx_facts

    qt = Path(env["QNX_TARGET"]) if env.get("QNX_TARGET") else None
    accepted: list[fx.Fix] = []
    seen_files: set[str] = set()
    cands = []
    implicit = {**(implicit or {}),
                **{w.symbol: w for w in last.parsed.warnings if w.kind == "implicit-decl"}}
    for u in unfixed:
        d = u.diagnostic
        if d.kind == "undefined-reference" and d.symbol in implicit:
            # a function QNX lacks: the compiler only warned, the linker failed. Ask about
            # the call site the warning points at.
            w = implicit[d.symbol]
            d = Diagnostic(kind="undefined-reference", severity="error", tool="cc",
                           message=f"undefined reference to '{d.symbol}' (the function does "
                           f"not exist on QNX; it was implicitly declared here)",
                           file=w.file, line=w.line, col=w.col, symbol=d.symbol)
            u = fx.Unfixed(d, u.rule_id, u.hint)
        rel = _rel(srcw, d.file)
        if d.tool != "cc" or not rel or rel in seen_files or not d.line:
            continue
        if u.rule_id in kb.rules and kb.rule(u.rule_id).fix == "manual":
            continue  # semantic redesign (e.g. epoll, CPU affinity): reported, not guessed
        seen_files.add(rel)
        cands.append((u, rel))
    for u, rel in cands[:max_errors]:
        d = u.diagnostic
        facts = qnx_facts(d, kb, sdp, qt,
                          (srcw / rel).read_text(encoding="utf-8", errors="replace"))
        related = [x.diagnostic for x in unfixed
                   if x.diagnostic is not d and _rel(srcw, x.diagnostic.file) == rel]
        prompt = ai_mod.build_prompt(d, rel, srcw, facts, related)
        feedback = ""
        for k in range(1, tries + 1):
            n_ai = len(run.ai) + 1
            entry: dict[str, Any] = {"n": n_ai, "error": f"{rel}:{d.line}: {d.message}",
                                     "model": ai.model, "try": k, "facts": facts}
            run.ai.append(entry)
            try:
                reply = ai.chat(ai_mod.SYSTEM, prompt + feedback)
            except Exception as e:  # transport errors: stop asking
                entry.update(result="error", reason=str(e))
                say(f"      AI unavailable: {e}")
                return accepted, last
            (out / "logs").mkdir(parents=True, exist_ok=True)
            (out / "logs" / f"ai-{n_ai}.txt").write_text(
                f"=== PROMPT\n{prompt}{feedback}\n\n=== REPLY\n{reply}\n", encoding="utf-8")
            prop = ai_mod.parse_reply(reply)
            if prop.no_fix or prop.error:
                entry.update(result="no_fix" if prop.no_fix else "invalid",
                             reason=prop.no_fix or prop.error)
                say(f"      AI: {entry['result']} ({entry['reason'][:70]})")
                break
            why = ai_mod.check_edits(prop, srcw, {rel})
            if why:
                entry.update(result="invalid", reason=why)
                say(f"      AI edit invalid: {why[:80]}")
                feedback = f"\n\nYour previous answer was rejected: {why}. Try again."
                continue
            orig = ai_mod.apply_edits(prop, srcw)
            entry["edits"] = [{"path": e.path, "search": e.search, "replace": e.replace}
                              for e in prop.edits]
            b = run_make(port_dir, srcw, stage, out / "logs" / f"ai-{n_ai}-build.log",
                         arch=arch, jobs=jobs, testing=testing, env=env)
            before = {_err_key(x) for x in last.parsed.errors}
            after = {_err_key(x) for x in b.parsed.errors}
            gone = _err_key(d) not in after and not (
                d.kind == "undefined-reference"
                and any(x.symbol == d.symbol for x in b.parsed.errors))
            edited = {Path(e.path).name for e in prop.edits}
            added = {k_ for k_ in after - before if k_[1] in edited
                     and k_[0] not in ("undefined-reference", "missing-library",
                                       "duplicate-symbol", "link-error")}
            if b.ok or (gone and not added):
                entry.update(result="accepted", reason="the build succeeds" if b.ok else
                             "rebuild: the error is gone and the edited file has no new "
                             "compile errors")
                say(f"      AI fix accepted ({ai.model}): {rel}: {d.message[:60]}")
                accepted.append(fx.Fix("ai", "source", f"AI edit for: {d.message[:70]}",
                                       f"verified by rebuild ({ai.model})", path=rel,
                                       line=d.line))
                last = b
                break
            ai_mod.revert(srcw, orig)
            reason = "error still there" if not gone else \
                "new errors: " + "; ".join(k_[3] for k_ in list(added)[:2])
            entry.update(result="rejected", reason=reason)
            say(f"      AI fix rejected ({reason[:70]})")
            feedback = ("\n\nYour previous edit was applied and rebuilt but rejected: "
                        f"{reason}. Try a different fix.")
    return accepted, last


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
    _report(out)
    return run


def _report(out: Path) -> None:
    """Refresh report.html; a report problem must never fail a port."""
    from .report import write_report
    try:
        write_report(out)
    except Exception as e:  # noqa: BLE001
        say_flush(f"      (report.html not written: {type(e).__name__}: {e})")


# ---- test on the target, fix what a rule explains, rebuild, test again ----------------------
def rerender(out: Path, spec: PortSpec) -> Path:
    """Re-write the port folder from spec, keeping the generated qnxtests.sh and patch."""
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    port_dir = Path(run.get("port_dir") or out / spec.name)
    tests_sh = port_dir / "qnxtests.sh"
    patch = port_dir / "patches" / "qnx.patch"
    files = render(spec, qnxtests=tests_sh.read_text() if tests_sh.exists() else None,
                   patch=patch.read_text() if patch.exists() else None,
                   readme=render_readme(spec, changes=changes_from_run(run)))
    write(port_dir, files)
    save_spec(spec, out / "spec.json")
    return port_dir


def _ai_log(out: Path, entry: dict[str, Any]) -> None:
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    run.setdefault("ai", []).append(entry)
    (out / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")


_SRC_REF = re.compile(r"([\w./-]+\.(?:c|cc|cpp|cxx|h|hpp)):(\d+)")


def _ai_test_repair(ai: Any, out: Path, failing: Any, logs_dir: Path, ai_files: list[str],
                    srcw: Path, port_dir: Path, *, env: dict[str, str], arch: str, jobs: int,
                    say: Callable[[str], None]) -> dict[str, str] | None:
    """A test fails on QNX after AI edits: show the model its diff, the test output and the
    test code, and apply its repair if it builds. Returns the originals (to revert) or None."""
    from . import ai as ai_mod

    log = logs_dir / f"{failing.name}.out"
    text = log.read_text(errors="replace") if log.exists() else ""
    tail = "\n".join(text.splitlines()[-30:])
    diff_txt = subprocess.run(["git", "diff", "--no-color", "--", *ai_files], cwd=srcw,
                              capture_output=True, text=True).stdout
    refs = []
    for f, ln in _SRC_REF.findall(text)[:2]:
        rel = fx.rel_in_root(srcw, f)
        if rel and rel not in ai_files:
            code, _ = ai_mod.excerpt(srcw / rel, int(ln), 10)
            refs.append(f"Test code around {rel}:{ln}:\n{code}")
    current = "\n\n".join(f"Current {p}:\n{(srcw / p).read_text(errors='replace')[:3000]}"
                          for p in ai_files)
    prompt = (f"These edits were made to port the library to QNX 8.0. They compile, but the "
              f"library's own test '{failing.name}' now fails on QNX.\n\nEdits (git diff):\n"
              f"{diff_txt}\n\nTest output on QNX (last lines):\n{tail}\n\n"
              + "\n\n".join(refs) + f"\n\n{current}\n\nFix the ported code so it behaves "
              f"exactly like the original Linux code. Edit only: {', '.join(ai_files)}.")
    n = len(list((out / "logs").glob("ai-test-*.txt"))) + 1
    try:
        reply = ai.chat(ai_mod.SYSTEM, prompt)
    except Exception as e:
        say(f"      AI unavailable: {e}")
        return None
    (out / "logs" / f"ai-test-{n}.txt").write_text(f"=== PROMPT\n{prompt}\n\n=== REPLY\n{reply}\n",
                                                   encoding="utf-8")
    prop = ai_mod.parse_reply(reply)
    why = prop.no_fix or prop.error or ai_mod.check_edits(prop, srcw, set(ai_files))
    if why:
        _ai_log(out, {"stage": "test-repair", "test": failing.name, "result": "invalid",
                      "reason": why, "model": ai.model})
        say(f"      AI repair not usable: {why[:80]}")
        return None
    orig = ai_mod.apply_edits(prop, srcw)
    b = run_make(port_dir, srcw, out / "work" / "stage", out / "logs" / f"ai-test-{n}-build.log",
                 arch=arch, jobs=jobs, testing=True, env=env)
    if not b.ok:
        ai_mod.revert(srcw, orig)
        run_make(port_dir, srcw, out / "work" / "stage", out / "logs" / f"ai-test-{n}-revert.log",
                 arch=arch, jobs=jobs, testing=True, env=env)
        _ai_log(out, {"stage": "test-repair", "test": failing.name, "result": "rejected",
                      "reason": "repair does not build", "model": ai.model})
        say("      AI repair rejected: it does not build")
        return None
    _ai_log(out, {"stage": "test-repair", "test": failing.name, "result": "trying",
                  "model": ai.model, "edits": [{"path": e.path, "search": e.search,
                                                "replace": e.replace} for e in prop.edits]})
    say(f"      AI repair for {failing.name} builds; re-testing on QNX")
    return orig


def test_and_fix(out: Path, target: Any, *, env: dict[str, str], jobs: int = 8,
                 arch: str = "x86_64", timeout_scale: float = 3,
                 build_files: Path | None = None, max_rounds: int = 3, ai: Any = None,
                 say: Callable[[str], None] = say_flush, localhost: str = "",
                 services: list[Any] | None = None) -> Any:
    from .deps import ensure_muslflt
    from .target import run_tests
    from .testfail import classify

    out = out.resolve()
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    name = run["name"]
    srcw = out / "work" / "src"
    history: list[dict[str, Any]] = []
    tr = None
    pending: tuple[dict[str, str], str] | None = None  # AI repair awaiting its test result
    tried: set[str] = set()  # one AI repair per failing test (temperature 0: same answer)
    for rnd in range(max_rounds + 1):
        tr = run_tests(target, test_dir(out, name, arch), name, out / "logs" / f"tests-{rnd + 1}",
                       timeout_scale=timeout_scale, localhost=localhost, services=services)
        say(f"      tests round {rnd + 1}: {tr.passed}/{tr.total} pass"
            + (f", failing: {', '.join(r.name for r in tr.results if r.status != 'PASS')}"
               if tr.failed else ""))
        run = record_tests(out, tr, arch)
        entry: dict[str, Any] = {"round": rnd + 1, "passed": tr.passed, "total": tr.total,
                                 "fixes": []}
        history.append(entry)
        if pending is not None:
            # the previous round tried an AI repair: keep it only if its test now passes
            orig, test_name = pending
            pending = None
            still = any(r.name == test_name and r.status != "PASS" for r in tr.results)
            _ai_log(out, {"stage": "test-repair", "result": "rejected" if still else
                          "accepted", "test": test_name})
            if still:
                say(f"      AI repair rejected: {test_name} still fails; reverting it")
                from .ai import revert
                revert(srcw, orig)
                run_make(Path(run["port_dir"]), srcw, out / "work" / "stage",
                         out / "logs" / f"revert-{rnd + 1}.log", arch=arch, jobs=jobs,
                         testing=True, env=env)
            else:
                say(f"      AI repair accepted: {test_name} passes on QNX")
        if tr.aborted:
            say("      every program hangs on QNX: the runner stopped early")
            for w in run.get("scan_warnings", [])[:5]:
                say(f"      likely cause ({w['rule']}): {w['title']} at {w['where']} "
                    f"[{w['source']}]")
            entry["aborted"] = True
            break
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
        if not applied and ai is not None and rnd < max_rounds:
            ai_files = sorted({e["path"] for a in run.get("ai", [])
                               if a.get("result") == "accepted" for e in a.get("edits", [])})
            bad = [r for r in tr.results if r.status != "PASS" and r.name not in tried]
            if ai_files and bad:
                tried.add(bad[0].name)
                rep = _ai_test_repair(ai, out, bad[0], Path(tr.logs_dir), ai_files, srcw,
                                      Path(run["port_dir"]), env=env, arch=arch, jobs=jobs,
                                      say=say)
                if rep is not None:
                    pending = (rep, bad[0].name)
                    entry["fixes"] = [{"rule": "ai-test-repair", "test": bad[0].name,
                                       "title": f"AI repair of its own edit ({ai.model})"}]
                    continue
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
    patch = diff(srcw)  # test-time repairs change the source: ship the final patch
    pfile = Path(run["port_dir"]) / "patches" / "qnx.patch"
    if patch:
        pfile.parent.mkdir(parents=True, exist_ok=True)
        pfile.write_text(patch, encoding="utf-8")
    (out / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    if tr is not None:
        record_tests(out, tr, arch)
    return tr
