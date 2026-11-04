"""configure.py: CMake condition evaluation, check prediction, the solver, #if evaluation."""

from __future__ import annotations

from pathlib import Path

import pytest

from portpilot.configure import (
    UNDEF,
    CExpr,
    ConfigureModel,
    Env,
    HeaderGrep,
    Prediction,
    predict_check,
    target_seed,
)
from portpilot.sdp_index import SdpIndex


def env(**values: str | None) -> Env:
    v = target_seed()
    v.update(values)
    return Env(v)


@pytest.mark.parametrize("cond,expected", [
    ("QNX", True),
    ("UNIX", True),
    ("WIN32", False),
    ("NOT APPLE", True),
    ("CMAKE_SYSTEM_NAME MATCHES \"Linux\"", False),
    ("CMAKE_SYSTEM_NAME STREQUAL \"QNX\"", True),
    # unquoted QNX is the *variable* QNX (value 1), as in real CMake
    ("CMAKE_SYSTEM_NAME STREQUAL QNX", False),
    ("\"QNX\"", False),  # a quoted non-constant string is false
    ("CMAKE_SYSTEM_NAME MATCHES \"^(QNX|Linux)$\"", True),
    ("${CMAKE_SYSTEM_NAME} STREQUAL \"QNX\"", True),
    ("CMAKE_SYSTEM_PROCESSOR STREQUAL x86_64 AND NOT WIN32", True),
    ("(WIN32 OR APPLE) AND UNIX", False),
    ("CMAKE_SYSTEM_VERSION VERSION_LESS 7.1", False),
    ("CMAKE_SYSTEM_VERSION VERSION_GREATER_EQUAL 8.0", True),
    ("DEFINED QNX", True),
    ("NEVER_ASSIGNED_ANYWHERE", False),  # undefined variable: false, as in CMake
    ("OpenSSL_FOUND", None),  # set by find_package(): unknown
    ("BUILD_SHARED_LIBS", None),  # set from the command line: unknown
    ("ON", True),
    ("0", False),
    ("Foo-NOTFOUND", False),
])
def test_cmake_conditions(cond: str, expected: bool | None) -> None:
    assert env().eval(cond) is expected


def test_cmake_variables_and_unknowns() -> None:
    e = env(POLLER="auto", HAVE_X="1", HAVE_Y="", MAYBE=None)
    assert e.eval("POLLER STREQUAL \"auto\"") is True
    assert e.eval("POLLER STREQUAL \"epoll\"") is False
    assert e.eval("HAVE_X AND NOT HAVE_Y") is True
    assert e.eval("MAYBE") is None
    assert e.eval("MAYBE AND HAVE_Y") is False  # Kleene: False wins over unknown
    assert e.eval("MAYBE OR HAVE_X") is True


def test_solver_if_chain_and_options() -> None:
    m = ConfigureModel()
    m.add_option(["USE_TLS", "doc", "OFF"], ())
    m.add_set(["POLLER", "auto", "CACHE", "STRING", "doc"], ())
    m.add_check(Prediction("HAVE_EPOLL", False, "c", "r", "f", 1), ())
    m.add_check(Prediction("HAVE_POLL", True, "c", "r", "f", 2), ())
    # if (POLLER STREQUAL "epoll") set(Q_EPOLL ON) else() if (HAVE_EPOLL) ... elseif (HAVE_POLL)
    m.add_set(["Q_EPOLL", "ON"], (("POLLER STREQUAL epoll", True),))
    m.add_set(["Q_EPOLL", "ON"], (("POLLER STREQUAL epoll", False), ("HAVE_EPOLL", True)))
    m.add_set(["Q_POLL", "ON"], (("POLLER STREQUAL epoll", False), ("HAVE_EPOLL", False),
                                 ("HAVE_POLL", True)))
    cfg = m.solve([])
    assert cfg.env.eval("Q_EPOLL") is False
    assert cfg.env.eval("Q_POLL") is True
    assert cfg.env.eval("USE_TLS") is False


def test_solver_command_line_overrides_cache_but_not_normal_set() -> None:
    m = ConfigureModel(overrides={"USE_TLS": "ON", "FORCED": "ON"})
    m.add_option(["USE_TLS", "doc", "OFF"], ())
    m.add_set(["FORCED", "OFF"], ())
    cfg = m.solve([])
    assert cfg.env.eval("USE_TLS") is True
    assert cfg.env.eval("FORCED") is False


def test_solver_macro_follows_check_and_conditions() -> None:
    m = ConfigureModel()
    m.add_check(Prediction("HAVE_EPOLL", False, "c", "r", "f", 1), ())
    m.add_macro("PLATFORM_LINUX", (('CMAKE_SYSTEM_NAME MATCHES "Linux"', True),))
    m.add_macro("PLATFORM_QNX", (('CMAKE_SYSTEM_NAME MATCHES "Linux"', False),
                                 ('CMAKE_SYSTEM_NAME MATCHES "QNX"', True)))
    cfg = m.solve([])
    assert cfg.macros["HAVE_EPOLL"] is UNDEF
    assert cfg.macros["PLATFORM_LINUX"] is UNDEF
    assert cfg.macros["PLATFORM_QNX"] == "1"


# ---- check prediction (ground truth F-004, F-011) ------------------------------------------
@pytest.fixture
def grep(qnx_target: Path) -> HeaderGrep:
    return HeaderGrep(qnx_target)


def test_function_in_libsocket_fails_without_required_libraries(fake_sdp: SdpIndex,
                                                               grep: HeaderGrep) -> None:
    ok, why = predict_check("check_function_exists", ["recvmsg", "V"], fake_sdp, grep, set())
    assert ok is False and "libsocket" in why
    ok, _ = predict_check("check_function_exists", ["recvmsg", "V"], fake_sdp, grep, {"socket"})
    assert ok is True


def test_libc_only_libraries(fake_sdp: SdpIndex, grep: HeaderGrep) -> None:
    for lib in ("pthread", "rt", "dl"):
        ok, why = predict_check("check_library_exists", [lib, "sem_wait", "", "V"], fake_sdp,
                                grep, set())
        assert ok is False and "does not exist on QNX" in why
    ok, _ = predict_check("check_library_exists", ["atomic", "__atomic_load_1", "", "V"],
                          fake_sdp, grep, set())
    assert ok is True


def test_af_inet6_header_layout(fake_sdp: SdpIndex, grep: HeaderGrep) -> None:
    ok, _ = predict_check("check_symbol_exists", ["AF_INET6", "netinet/in.h", "V"], fake_sdp,
                          grep, set())
    assert ok is False
    ok, _ = predict_check("check_symbol_exists", ["AF_INET6", "sys/socket.h;netinet/in.h", "V"],
                          fake_sdp, grep, set())
    assert ok is True


def test_symbol_checks(fake_sdp: SdpIndex, grep: HeaderGrep) -> None:
    assert predict_check("check_symbol_exists", ["epoll_create", "sys/epoll.h", "V"], fake_sdp,
                         grep, set())[0] is False
    assert predict_check("check_symbol_exists", ["poll", "poll.h", "V"], fake_sdp, grep,
                         set())[0] is True
    # a macro in the header counts, whatever its case
    assert predict_check("check_symbol_exists", ["atomic_flag_test_and_set", "stdatomic.h",
                                                 "V"], fake_sdp, grep, set())[0] is True
    # declared only under a C11 feature macro: depends on -std, so unknown
    assert predict_check("check_symbol_exists", ["timespec_get", "time.h", "V"], fake_sdp,
                         grep, set())[0] is None
    # sanitizer / private copies are not providers
    assert predict_check("check_function_exists", ["getentropy", "V"], fake_sdp, grep,
                         set())[0] is False


def test_struct_member_and_include_checks(fake_sdp: SdpIndex, grep: HeaderGrep) -> None:
    assert predict_check("check_struct_has_member", ["struct sockaddr_un", "sun_path",
                                                     "sys/un.h", "V"], fake_sdp, grep,
                         set())[0] is True
    assert predict_check("check_struct_has_member", ["struct sockpeercred", "uid",
                                                     "sys/socket.h", "V"], fake_sdp, grep,
                         set())[0] is False
    assert predict_check("check_include_file", ["sys/epoll.h", "V"], fake_sdp, grep,
                         set())[0] is False
    assert predict_check("check_c_source_compiles", ["int main(){}", "V"], fake_sdp, grep,
                         set())[0] is None


def test_no_sdp_means_unknown() -> None:
    assert predict_check("check_function_exists", ["recvmsg", "V"], None, HeaderGrep(None),
                         set())[0] is None


# ---- C preprocessor ------------------------------------------------------------------------
def test_cexpr_basics() -> None:
    c = CExpr({"A": "1", "B": UNDEF, "V": "3", "ALIAS": "V", "EXPR": "(V + 1)"})
    assert c.eval("defined(A) && !defined(B)") is True
    assert c.eval("defined A") is True
    assert c.eval("V == 3") is True
    assert c.eval("ALIAS == 3") is True
    assert c.eval("EXPR > 3") is True
    assert c.eval("B") is False  # undefined macro is 0 in #if
    assert c.eval("UNKNOWN_MACRO") is None
    assert c.eval("UNKNOWN_MACRO && B") is False
    assert c.eval("UNKNOWN_MACRO || A") is True
    assert c.eval("FOO(1, 2)") is None


def test_cexpr_has_include_and_closed_reserved_names() -> None:
    c = CExpr({}, has_include=lambda h: h == "poll.h", closed=True,
              header_macros={"_POSIX_VERSION"})
    assert c.eval("__has_include(<poll.h>)") is True
    assert c.eval("__has_include(<sys/epoll.h>)") is False
    assert c.eval('FMT_HAS_INCLUDE("poll.h")') is True
    assert c.eval("defined(__MVS__)") is False  # reserved, not predefined: undefined
    assert c.eval("defined(_WIN32)") is False
    assert c.eval("defined(_POSIX_VERSION)") is None  # an SDP header may define it
    assert c.eval("defined(MY_MACRO)") is None  # project names stay unknown
