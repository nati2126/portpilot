"""Command-line interface: `portpilot scan`, `portpilot sdp-index`, `portpilot detect`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from . import kb as kb_mod
from .detect import detect
from .matrix import to_json, to_markdown
from .scan import scan_project
from .sdp_index import SdpIndex, build_index, default_index_path, load_default


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


def _cmd_detect(a: argparse.Namespace) -> int:
    bs = detect(Path(a.path))
    print(f"{bs.primary}  (markers: {bs.found or 'none'})"
          + ("" if bs.supported else "  [not supported by the MVP]"))
    return 0 if bs.supported else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="portpilot", description="Port Linux C/C++ libraries to QNX.")
    p.add_argument("--version", action="version", version=f"portpilot {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

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

    d = sub.add_parser("detect", help="print the detected build system")
    d.add_argument("path")
    d.set_defaults(func=_cmd_detect)

    a = p.parse_args(argv)
    rc: int = a.func(a)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
