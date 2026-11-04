"""Rule-based fixes from scan findings and from real build diagnostics."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from portpilot import fixes as fx
from portpilot.diagnostics import parse
from portpilot.kb import KnowledgeBase
from portpilot.scaffold import PortSpec
from portpilot.scan import scan_project
from portpilot.sdp_index import SdpIndex

DIAG = Path(__file__).parent / "data" / "diag"


@pytest.fixture
def src(minilib: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "minilib"
    shutil.copytree(minilib, dest)
    return dest


def test_fixes_from_scan(src: Path, kb: KnowledgeBase, fake_sdp: SdpIndex, qnx_target: Path,
                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QNX_TARGET", str(qnx_target))
    monkeypatch.delenv("QNX_HOST", raising=False)
    r = scan_project(src, kb, fake_sdp)
    found = {f.rule_id: f for f in fx.from_findings(r.findings, kb, src)}
    assert set(found) == {"cmake-check-needs-libsocket", "nonstandard-sys-headers",
                          "cmake-check-header-layout"}
    sock = found["cmake-check-needs-libsocket"]
    assert sock.kind == "port" and sock.setting is not None
    assert sock.setting.value == "-DCMAKE_REQUIRED_LIBRARIES=socket"
    assert sock.setting.source == "docs/ground-truth.md#f-004"
    inc = found["nonstandard-sys-headers"]
    assert (inc.path, inc.old, inc.new) == ("src/core.c", "#include <sys/errno.h>",
                                            "#include <errno.h>")
    lay = found["cmake-check-header-layout"]
    assert (lay.old, lay.new) == ("netinet/in.h", '"sys/socket.h;netinet/in.h"')

    spec = PortSpec("minilib")
    for f in found.values():
        assert fx.apply(f, spec, src)
    assert "#include <errno.h>" in (src / "src" / "core.c").read_text()
    assert 'mini_check_sym(AF_INET6 "sys/socket.h;netinet/in.h" MINI_HAVE_INET6)' in \
        (src / "CMakeLists.txt").read_text()
    assert [s.value for s in spec.cmake_args] == ["-DCMAKE_REQUIRED_LIBRARIES=socket"]
    # applying twice is a no-op
    assert not fx.apply(found["nonstandard-sys-headers"], spec, src)
    assert not fx.apply(sock, spec, src)


def test_undefined_reference_becomes_a_link_flag(kb: KnowledgeBase, fake_sdp: SdpIndex,
                                                 tmp_path: Path) -> None:
    diags = parse((DIAG / "undef_regcomp.log").read_text()).errors
    fixes, unfixed = fx.from_diagnostics(diags, kb, fake_sdp, tmp_path)
    assert unfixed == []
    assert len(fixes) == 1  # regcomp and regfree: one flag
    f = fixes[0]
    assert (f.rule_id, f.kind, f.field) == ("link-regex", "port", "ldflags")
    assert f.setting is not None and f.setting.value == "-lregex"


def test_project_symbol_is_not_guessed(kb: KnowledgeBase, fake_sdp: SdpIndex,
                                       tmp_path: Path) -> None:
    diags = parse((DIAG / "undef_project_sym.log").read_text()).errors
    fixes, unfixed = fx.from_diagnostics(diags, kb, fake_sdp, tmp_path)
    assert fixes == [] and len(unfixed) == 1
    assert "not in the QNX SDP" in unfixed[0].hint


def test_missing_sys_errno_from_the_compiler(kb: KnowledgeBase, tmp_path: Path) -> None:
    (tmp_path / "missing_sys_errno.c").write_text(
        "#include <sys/errno.h>\nint f(void) { return errno; }\n")
    diags = parse((DIAG / "missing_sys_errno.log").read_text()).errors
    fixes, unfixed = fx.from_diagnostics(diags, kb, None, tmp_path)
    assert unfixed == [] and fixes[0].new == "#include <errno.h>"
    assert fx.apply(fixes[0], PortSpec("x"), tmp_path)
    assert (tmp_path / "missing_sys_errno.c").read_text().startswith("#include <errno.h>\n")


def test_epoll_is_not_auto_fixed(kb: KnowledgeBase, tmp_path: Path) -> None:
    diags = parse((DIAG / "missing_epoll.log").read_text()).errors
    fixes, unfixed = fx.from_diagnostics(diags, kb, None, tmp_path)
    assert fixes == []
    assert unfixed[0].rule_id == "epoll" and "poll()" in unfixed[0].hint


def test_lpthread_is_wrapped_for_qnx_only(kb: KnowledgeBase, tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        "add_library(demo SHARED demo.c)\n"
        "target_link_libraries(demo\n  PRIVATE pthread m)\n"
        "target_link_libraries(other ${CMAKE_THREAD_LIBS_INIT})\n")
    diags = parse((DIAG / "cmake_make_link.log").read_text()).errors
    fixes, unfixed = fx.from_diagnostics(diags, kb, None, tmp_path)
    assert unfixed == [] and len(fixes) == 1
    assert fx.apply(fixes[0], PortSpec("x"), tmp_path)
    text = (tmp_path / "CMakeLists.txt").read_text()
    assert "PRIVATE $<$<NOT:$<PLATFORM_ID:QNX>>:pthread> m)" in text
    assert "${CMAKE_THREAD_LIBS_INIT}" in text


def test_identifier_rule_hint(kb: KnowledgeBase, tmp_path: Path) -> None:
    diags = parse((DIAG / "undeclared_ident.log").read_text()).errors
    _, unfixed = fx.from_diagnostics(diags, kb, None, tmp_path)
    assert unfixed[0].rule_id == "so-peercred"
