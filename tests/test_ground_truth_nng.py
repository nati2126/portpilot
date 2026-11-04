"""Integration: predicted configure vs the real CMakeCache of nng built for QNX 8.0.

Needs the real SDP index (`portpilot sdp-index`) and nng sources, so it is skipped in CI:
    PORTPILOT_NNG_UPSTREAM=<nng at caf6f9f>  PORTPILOT_NNG_PORT=<same tree + ports/nng patch>
The expected values in tests/data/ were read from CMakeCache.txt after configuring nng with
the QNX toolchain (upstream: no extra flags; port: -DCMAKE_REQUIRED_LIBRARIES=socket).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from portpilot import kb as kb_mod
from portpilot.scan import scan_project
from portpilot.sdp_index import load_default

DATA = Path(__file__).parent / "data"


def truth(name: str) -> dict[str, bool]:
    out = {}
    for line in (DATA / name).read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v not in ("", "0", "OFF", "FALSE")
    return out


def compare(src: str, truth_file: str, defines: dict[str, str]) -> tuple[int, int, list[str]]:
    sdp = load_default()
    if sdp is None or not os.environ.get("QNX_TARGET"):
        pytest.skip("needs the QNX SDP environment and `portpilot sdp-index`")
    root = os.environ.get(src)
    if not root:
        pytest.skip(f"set {src}")
    r = scan_project(Path(root), kb_mod.load(), sdp, defines=defines)
    pred: dict[str, bool | None] = {}
    for c in r.configure:
        var = str(c["var"])
        if var not in pred or c["runs"] is not False:
            pred[var] = False if c["runs"] is False else c["value"]  # type: ignore[assignment]
    right = unknown = 0
    wrong: list[str] = []
    for var, value in truth(truth_file).items():
        p = pred.get(var)
        if p is None:
            unknown += 1
        elif p == value:
            right += 1
        else:
            wrong.append(f"{var}: predicted {p}, real {value}")
    return right, unknown, wrong


def test_upstream_nng() -> None:
    right, unknown, wrong = compare("PORTPILOT_NNG_UPSTREAM", "nng-cmakecache-upstream.txt", {})
    assert wrong == []
    assert right >= 42 and unknown <= 2


def test_ported_nng() -> None:
    right, unknown, wrong = compare("PORTPILOT_NNG_PORT", "nng-cmakecache-port.txt",
                                    {"CMAKE_REQUIRED_LIBRARIES": "socket"})
    assert wrong == []
    assert right >= 42 and unknown <= 2
