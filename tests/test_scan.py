"""End-to-end scan of the fixture library: what QNX really compiles, and what needs work."""

from __future__ import annotations

from pathlib import Path

import pytest

from portpilot import kb as kb_mod
from portpilot.matrix import build_rows, summary, to_json, to_markdown
from portpilot.models import Finding, ScanResult
from portpilot.scan import scan_project


def by_rule(result: ScanResult, rule: str) -> list[Finding]:
    return [f for f in result.findings if f.rule_id == rule]


def active(result: ScanResult, rule: str) -> list[Finding]:
    return [f for f in by_rule(result, rule) if f.guard == "none" and f.area == "lib"]


def predicted(result: ScanResult) -> dict[str, bool | None]:
    out: dict[str, bool | None] = {}
    for c in result.configure:
        if c["runs"] is not False:
            out[str(c["var"])] = c["value"]  # type: ignore[assignment]
    return out


def test_predicted_configure(scan_minilib: ScanResult) -> None:
    p = predicted(scan_minilib)
    assert p["MINI_HAVE_EPOLL"] is False  # no <sys/epoll.h> on QNX
    assert p["MINI_HAVE_POLL"] is True
    assert p["MINI_HAVE_INET6"] is False  # AF_INET6 only in <sys/socket.h> (F-004)
    assert p["MINI_HAVE_RECVMSG"] is False  # in libsocket, not linked by the check (F-004)
    assert p["MINI_HAVE_STRLCPY"] is True
    assert p["MINI_HAVE_SEM_PTHREAD"] is False  # no libpthread on QNX (F-011)


def test_dead_backend_is_not_porting_work(scan_minilib: ScanResult) -> None:
    epoll = by_rule(scan_minilib, "epoll")
    assert epoll, "epoll uses should still be listed"
    assert all(f.guard == "config-off" for f in epoll), epoll
    assert all(f.guard == "config-off" for f in by_rule(scan_minilib, "eventfd"))


def test_header_reachability(scan_minilib: ScanResult) -> None:
    hup = {f.path: f.guard for f in by_rule(scan_minilib, "pollhup-pipe")}
    assert hup["src/pollq_epoll.h"] == "config-off"  # only included for the epoll backend
    assert hup["src/pollq_poll.h"] == "none"
    assert hup["src/poll_poll.c"] == "none"


def test_real_problems_are_reported(scan_minilib: ScanResult) -> None:
    assert active(scan_minilib, "nonstandard-sys-headers")[0].name == "sys/errno.h"
    assert active(scan_minilib, "cmake-check-needs-libsocket")[0].name == "recvmsg"
    assert active(scan_minilib, "cmake-check-header-layout")
    assert active(scan_minilib, "cmake-check-lib-in-libc")[0].name == "pthread:sem_wait"
    assert active(scan_minilib, "eai-addrfamily")  # F-006
    assert active(scan_minilib, "unix-stale-socket")  # F-008


def test_comments_strings_and_methods_are_ignored(scan_minilib: ScanResult) -> None:
    core_calls = [f for f in scan_minilib.findings if f.path == "src/core.c" and f.kind == "call"
                  and f.rule_id in ("epoll", "eventfd")]
    assert core_calls == []
    assert by_rule(scan_minilib, "linux-namespaces") == []  # Obj::clone() is not clone(2)


def test_project_macros_and_has_include(scan_minilib: ScanResult) -> None:
    win = {f.name: f.guard for f in scan_minilib.findings if f.path == "src/win.c"}
    assert win["windows.h"] != "none"  # MINI_OS == MINI_OS_WIN is false on QNX
    assert win["fancy/fancy.h"] != "none"  # MINI_USE_FANCY defaults to 0
    assert "xlocale.h" not in win or win["xlocale.h"] != "none"  # __has_include is false


def test_optional_and_test_code(scan_minilib: ScanResult) -> None:
    tls = [f for f in scan_minilib.findings if f.path.startswith("src/tls/")]
    assert tls and all(f.guard != "none" for f in tls)
    forks = by_rule(scan_minilib, "fork")
    assert forks and all(f.area == "test" for f in forks)


def test_linux_branch_with_qnx_branch_is_not_reported(scan_minilib: ScanResult) -> None:
    assert by_rule(scan_minilib, "cmake-linux-branch") == []
    # target_link_libraries(mini pthread) sits in the Linux branch: not a QNX problem
    assert all(f.guard != "none" for f in by_rule(scan_minilib, "link-libc-only"))


def test_matrix_outputs(scan_minilib: ScanResult) -> None:
    kb = kb_mod.load()
    rows = build_rows(scan_minilib, kb)
    s = summary(rows)
    assert s.get("fix", 0) >= 3
    md = to_markdown(scan_minilib, kb)
    assert "## Dependency matrix" in md and "## Predicted configure on QNX" in md
    assert "MINI_HAVE_EPOLL" in md
    import json
    d = json.loads(to_json(scan_minilib, kb))
    assert {r["rule"] for r in d["matrix"]} >= {"epoll", "cmake-check-needs-libsocket"}
    assert any(c["var"] == "MINI_HAVE_RECVMSG" for c in d["configure"])


def test_define_overrides(minilib: Path, fake_sdp: object, qnx_target: Path,
                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QNX_TARGET", str(qnx_target))
    r = scan_project(minilib, kb_mod.load(), fake_sdp,  # type: ignore[arg-type]
                     defines={"CMAKE_REQUIRED_LIBRARIES": "socket", "MINI_ENABLE_TLS": "ON"})
    assert predicted(r)["MINI_HAVE_RECVMSG"] is True
    assert active(r, "cmake-check-needs-libsocket") == []
    tls = [f for f in r.findings if f.path.startswith("src/tls/")]
    assert tls and all(f.guard == "none" for f in tls)


def test_scan_without_sdp_still_works(minilib: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QNX_TARGET", raising=False)
    r = scan_project(minilib, kb_mod.load(), None)
    assert r.build_system == "cmake"
    assert not r.sdp_index_used
    # the headers-only facts still hold: epoll is still recognised as dead
    assert by_rule(r, "epoll")
    assert predicted(r)["MINI_HAVE_SEM_PTHREAD"] is False


def test_optional_headers_do_not_block(tmp_path: Path) -> None:
    """spdlog: include/spdlog/sinks/kafka_sink.h needs librdkafka, but no compiled source
    includes it; only users who want that sink do."""
    from portpilot.models import Finding
    from portpilot.scan import mark_optional_headers
    inc = tmp_path / "include" / "lib"
    (inc / "sinks").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.cpp").write_text('#include "lib/core.h"\n')
    (inc / "core.h").write_text('#include "details.h"\n')
    (inc / "details.h").write_text("#include <sys/socket.h>\n")
    (inc / "sinks" / "kafka_sink.h").write_text("#include <librdkafka/rdkafkacpp.h>\n")
    fs = [Finding("third-party-dep", "librdkafka", "include", "include/lib/sinks/kafka_sink.h",
                  1, "lib", "none"),
          Finding("link-socket", "socket", "call", "include/lib/details.h", 1, "lib", "none")]
    out = mark_optional_headers(tmp_path, fs)
    assert [f.guard for f in out] == ["optional-header", "none"]
    # header-only library: every header may be an entry point
    (tmp_path / "src" / "lib.cpp").unlink()
    assert [f.guard for f in mark_optional_headers(tmp_path, fs)] == ["none", "none"]


def test_scan_reports_bsd_only_sockaddr_length(tmp_path: Path) -> None:
    from portpilot.scan import scan_project

    (tmp_path / "CMakeLists.txt").write_text("project(x C)\nadd_library(x src/a.c)\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.c").write_text(
        "#include <netinet/in.h>\nvoid f(struct sockaddr_in *s) {\n"
        "#if defined(__APPLE__) || defined(BSD)\n  s->sin_len = sizeof *s;\n#endif\n}\n")
    res = scan_project(tmp_path, sdp=None)
    hits = [f for f in res.findings if f.rule_id == "bsd-sockaddr-len"]
    assert [(f.path, f.line, f.guard, f.area) for f in hits] == [("src/a.c", 3, "none", "lib")]
