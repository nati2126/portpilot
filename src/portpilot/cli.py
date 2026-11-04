"""Command-line interface: port, scan, diagnose, qnxtests, sdp-index, detect."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from . import kb as kb_mod
from .ai import DEFAULT_MODEL, DEFAULT_URL
from .detect import detect
from .matrix import to_json, to_markdown
from .scan import scan_project
from .sdp_index import SdpIndex, build_index, default_index_path, load_default
from .target import Target, TargetError, default_key, vm_start, vm_stop


def _cmd_atlas_scan(a: argparse.Namespace) -> int:
    import json

    from .atlas import run_scan
    from .atlas import to_markdown as atlas_md
    out = Path(a.output).expanduser()
    run_scan(Path(a.candidates), out, limit=a.limit, jobs=a.jobs, arch=a.arch, keep=a.keep,
             say=lambda s: print(s, flush=True))
    atlas = json.loads((out / "atlas.json").read_text(encoding="utf-8"))
    (out / "atlas.md").write_text(atlas_md(atlas), encoding="utf-8")
    print(f"wrote {out / 'atlas.json'} and {out / 'atlas.md'}")
    return 0


def _cmd_atlas_report(a: argparse.Namespace) -> int:
    import json

    from .atlas import to_markdown as atlas_md
    atlas = json.loads((Path(a.dir).expanduser() / "atlas.json").read_text(encoding="utf-8"))
    print(atlas_md(atlas))
    return 0


def _cmd_scan(a: argparse.Namespace) -> int:
    root = Path(a.path)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    sdp: SdpIndex | None = None
    if a.sdp_index:
        sdp = SdpIndex.load(Path(a.sdp_index))
    elif not a.no_sdp:
        sdp = load_default(a.arch)
    defines: dict[str, str] = {}
    for d in a.define:
        k, _, v = d.partition("=")
        defines[k.split(":")[0]] = v  # accept -DVAR:BOOL=ON like cmake
    kb = kb_mod.load()
    result = scan_project(root, kb, sdp, a.arch, defines)
    md = to_markdown(result, kb)
    if a.output:
        out = Path(a.output)
        out.mkdir(parents=True, exist_ok=True)
        (out / "matrix.md").write_text(md, encoding="utf-8")
        (out / "matrix.json").write_text(to_json(result, kb), encoding="utf-8")
        print(f"wrote {out / 'matrix.md'} and {out / 'matrix.json'}")
    if a.json:
        print(to_json(result, kb))
    elif not a.output or a.print:
        print(md)
    return 0


def _cmd_sdp_index(a: argparse.Namespace) -> int:
    qt = a.qnx_target or os.environ.get("QNX_TARGET")
    if not qt:
        print("error: set QNX_TARGET (source qnxsdp-env.sh) or pass --qnx-target",
              file=sys.stderr)
        return 2
    idx = build_index(Path(qt), a.arch)
    out = Path(a.output) if a.output else default_index_path(a.arch)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(idx.to_json(), encoding="utf-8")
    print(f"indexed {len(idx.symbols)} symbols, {len(idx.headers)} headers, "
          f"{len(idx.libraries)} libraries -> {out}")
    return 0


def _load_sdp(a: argparse.Namespace) -> SdpIndex | None:
    if getattr(a, "sdp_index", None):
        return SdpIndex.load(Path(a.sdp_index))
    if getattr(a, "no_sdp", False):
        return None
    return load_default(a.arch)


def _cmd_port(a: argparse.Namespace) -> int:
    from .build import BuildError
    from .port import run_port

    sdp = _load_sdp(a)
    if sdp is None and not a.no_sdp:
        print("warning: no SDP index; run `portpilot sdp-index` for exact results",
              file=sys.stderr)
    provider = None
    if a.ai:
        from .ai import Provider

        provider = Provider(a.ai_url, a.ai_model)
        why = provider.available()
        if why:
            print(f"error: --ai: {why}", file=sys.stderr)
            return 2
        print(f"AI: {a.ai_model} at {a.ai_url} (local; edits kept only if the build verifies)")
    try:
        run = run_port(a.source, Path(a.output), name=a.name, arch=a.arch, jobs=a.jobs,
                       max_attempts=a.max_attempts, sdp=sdp, do_build=not a.no_build,
                       testing=not a.no_tests, ai=provider)
    except BuildError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    status = "BUILT" if run.ok else f"NOT BUILT ({run.stopped})"
    print(f"[4/4] {run.name}: {status} in {run.elapsed_s:.0f}s, "
          f"{len(run.attempts)} build attempt(s), {len(run.tests)} tests for the target")
    print(f"      port folder: {run.port_dir}")
    if run.patch_stat:
        print(f"      source patch: {run.patch_stat}")
    if run.ok and run.tests and (a.ip or a.vm):
        a.output_dir = a.output
        return _cmd_test(a)
    return 0 if run.ok or a.no_build else 1


def _target_from_args(a: argparse.Namespace, env: dict[str, str]) -> Target:
    key = a.key or default_key()
    kh = a.known_hosts or ""
    if a.ip:
        return Target(a.ip, user=a.user, key=key, known_hosts=kh)
    return vm_start(Path(a.vm).expanduser(), env, key=key, known_hosts=kh)


def _provider(a: argparse.Namespace) -> Any:
    if not getattr(a, "ai", False):
        return None
    from .ai import Provider

    return Provider(a.ai_url, a.ai_model)


def _cmd_test(a: argparse.Namespace) -> int:
    import json

    from .build import BuildError, sdp_env
    from .deps import find_build_files
    from .port import test_and_fix

    out = Path(a.output_dir).resolve()
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    if not a.ip and not a.vm:
        print("error: give --ip of a QNX target or --vm <mkqnximage dir>", file=sys.stderr)
        return 2
    t: Target | None = None
    try:
        env = sdp_env()
        t = _target_from_args(a, env)
        print(f"[5/5] test {run['name']} on QNX target {t.host}")
        tr = test_and_fix(out, t, env=env, jobs=getattr(a, "jobs", 8), arch=a.arch,
                          timeout_scale=a.timeout_scale,
                          build_files=find_build_files(a.build_files),
                          max_rounds=0 if a.no_fix else 3, ai=_provider(a))
    except (BuildError, TargetError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        if a.vm and a.stop_vm:
            vm_stop(Path(a.vm).expanduser(), sdp_env(), t)
    for r in tr.results:
        if r.status != "PASS":
            print(f"  {r.status:7} {r.name} rc={r.rc} {r.seconds}s")
    print(f"{run['name']}: {tr.passed}/{tr.total} pass on QNX ({tr.host}), "
          f"{tr.timeouts} timeouts, {tr.seconds:.0f}s" + ("" if tr.finished else
                                                          " [runner did not finish]"))
    return 0 if tr.ok else 1


def _add_target_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ip", help="QNX target address (ssh)")
    p.add_argument("--vm", help="mkqnximage VM directory: boot it if needed and use it")
    p.add_argument("--user", default="root")
    p.add_argument("--key", help="ssh identity (default ~/.ssh/qnx_vm_ed25519 if present)")
    p.add_argument("--known-hosts", help="ssh known_hosts file")
    p.add_argument("--timeout-scale", type=float, default=3,
                   help="multiply CTest timeouts (QEMU is slower; default 3)")
    p.add_argument("--stop-vm", action="store_true", help="stop the VM afterwards")
    p.add_argument("--build-files", help="build-files checkout, for dependency ports "
                   "(default $PORTPILOT_BUILD_FILES or ~/qnx-work/build-files)")
    p.add_argument("--no-fix", action="store_true", help="only run the tests once")
    p.add_argument("--ai", action="store_true",
                   help="ask a local model about what no rule fixes (kept only if verified)")
    p.add_argument("--ai-model", default=DEFAULT_MODEL, help=f"default {DEFAULT_MODEL}")
    p.add_argument("--ai-url", default=DEFAULT_URL,
                   help=f"OpenAI-compatible endpoint (default {DEFAULT_URL}, Ollama)")


def _cmd_diagnose(a: argparse.Namespace) -> int:
    from . import fixes as fx
    from .diagnostics import parse

    text = Path(a.log).read_text(encoding="utf-8", errors="replace")
    log = parse(text)
    errs = log.errors if not a.warnings else log.diagnostics
    print(f"{len(log.errors)} errors, {len(log.warnings)} warnings; stopped at: {log.phase}")
    sdp = _load_sdp(a)
    found, unfixed = fx.from_diagnostics(errs, kb_mod.load(), sdp,
                                         Path(a.source) if a.source else Path.cwd())
    for d in errs:
        print(f"  {d.severity:7} {d.kind:20} {d.location() or '-':40} {d.message}")
    for f in found:
        print(f"  fix ({f.rule_id}): {f.title}" + (f" [{f.path}:{f.line}]" if f.path else ""))
    for u in unfixed:
        print(f"  no rule: {u.diagnostic.symbol or u.diagnostic.kind}: {u.hint}")
    return 0


def _cmd_qnxtests(a: argparse.Namespace) -> int:
    from .qnxtests import generate

    text, tests = generate(Path(a.build_dir).resolve(), a.name)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
        print(f"{len(tests)} tests -> {a.output}")
    else:
        sys.stdout.write(text)
    return 0


def _cmd_detect(a: argparse.Namespace) -> int:
    bs = detect(Path(a.path))
    print(f"{bs.primary}  (markers: {bs.found or 'none'})"
          + ("" if bs.supported else "  [not supported by the MVP]"))
    return 0 if bs.supported else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="portpilot", description="Port Linux C/C++ libraries to QNX.")
    p.add_argument("--version", action="version", version=f"portpilot {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pt = sub.add_parser("port", help="scan, generate the port, build it and fix what breaks")
    pt.add_argument("source", help="local source tree or git URL")
    pt.add_argument("-o", "--output", required=True, help="output directory")
    pt.add_argument("--name", help="port name (default: the source directory name)")
    pt.add_argument("--arch", default="x86_64", choices=["x86_64", "aarch64"])
    pt.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4)
    pt.add_argument("--max-attempts", type=int, default=6, help="build attempts (default 6)")
    pt.add_argument("--no-build", action="store_true", help="only scan and generate the port")
    pt.add_argument("--no-tests", action="store_true", help="build without the tests")
    pt.add_argument("--sdp-index")
    pt.add_argument("--no-sdp", action="store_true")
    _add_target_args(pt)
    pt.set_defaults(func=_cmd_port)

    ts = sub.add_parser("test", help="run a built port's tests on a QNX target")
    ts.add_argument("output_dir", help="the -o directory of `portpilot port`")
    ts.add_argument("--arch", default="x86_64")
    _add_target_args(ts)
    ts.set_defaults(func=_cmd_test)

    dg = sub.add_parser("diagnose", help="parse a QNX build log and suggest rule fixes")
    dg.add_argument("log")
    dg.add_argument("--source", help="source tree the log was built from (for source fixes)")
    dg.add_argument("--warnings", action="store_true", help="also list warnings")
    dg.add_argument("--arch", default="x86_64")
    dg.add_argument("--sdp-index")
    dg.add_argument("--no-sdp", action="store_true")
    dg.set_defaults(func=_cmd_diagnose)

    qt = sub.add_parser("qnxtests", help="generate qnxtests.sh from a CMake build tree")
    qt.add_argument("build_dir")
    qt.add_argument("--name", default="tests")
    qt.add_argument("-o", "--output")
    qt.set_defaults(func=_cmd_qnxtests)

    s = sub.add_parser("scan", help="analyze a source tree and print the dependency matrix")
    s.add_argument("path")
    s.add_argument("-o", "--output", help="write matrix.md and matrix.json into this directory")
    s.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    s.add_argument("--print", action="store_true", help="also print Markdown with --output")
    s.add_argument("--sdp-index", help="SDP index file (default: ~/.cache/portpilot/...)")
    s.add_argument("--no-sdp", action="store_true", help="ignore any SDP index")
    s.add_argument("--arch", default="x86_64")
    s.add_argument("-D", "--define", action="append", default=[], metavar="VAR=VALUE",
                   help="CMake cache value the port passes, as for cmake -D (repeatable)")
    s.set_defaults(func=_cmd_scan)

    i = sub.add_parser("sdp-index", help="index your QNX SDP (symbols, headers, libraries)")
    i.add_argument("--qnx-target", help="default: $QNX_TARGET")
    i.add_argument("--arch", default="x86_64")
    i.add_argument("-o", "--output")
    i.set_defaults(func=_cmd_sdp_index)

    at = sub.add_parser("atlas", help="scan many libraries and rank what blocks them on QNX")
    asub = at.add_subparsers(dest="atlas_cmd", required=True)
    s2 = asub.add_parser("scan", help="clone and scan the candidates (resumable)")
    s2.add_argument("candidates", help="candidates.json from atlas/candidates.py")
    s2.add_argument("-o", "--output", required=True)
    s2.add_argument("--limit", type=int, default=300)
    s2.add_argument("-j", "--jobs", type=int, default=6)
    s2.add_argument("--keep", action="store_true", help="keep the clones")
    s2.add_argument("--arch", default="x86_64")
    s2.set_defaults(func=_cmd_atlas_scan)
    r2 = asub.add_parser("report", help="print the atlas summary (Markdown)")
    r2.add_argument("dir")
    r2.set_defaults(func=_cmd_atlas_report)

    d = sub.add_parser("detect", help="print the detected build system")
    d.add_argument("path")
    d.set_defaults(func=_cmd_detect)

    a = p.parse_args(argv)
    rc: int = a.func(a)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
