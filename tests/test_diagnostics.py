"""The parser against real qcc 12.2 / ld / cmake output (tests/data/diag, captured on SDP 8.0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from portpilot.diagnostics import Diagnostic, parse

DIAG = Path(__file__).parent / "data" / "diag"


def errors(name: str) -> list[Diagnostic]:
    return parse((DIAG / f"{name}.log").read_text(encoding="utf-8")).errors


def one(name: str) -> Diagnostic:
    errs = errors(name)
    assert len(errs) == 1, errs
    return errs[0]


@pytest.mark.parametrize("name,header,file,line", [
    ("missing_sys_errno", "sys/errno.h", "missing_sys_errno.c", 1),
    ("missing_epoll", "sys/epoll.h", "missing_epoll.c", 2),
    ("missing_header_cxx", "sys/eventfd.h", "missing_header_cxx.cpp", 1),
])
def test_missing_header(name: str, header: str, file: str, line: int) -> None:
    d = one(name)
    assert (d.kind, d.symbol, d.file, d.line) == ("missing-header", header, file, line)
    assert d.tool == "cc"
    assert d.source_line.startswith("#include <")


def test_missing_header_via_include_chain() -> None:
    d = one("nested_include")
    assert (d.kind, d.symbol, d.file) == ("missing-header", "sys/timerfd.h", "inc/a.h")
    assert d.included_from == ("nested_include.c:1",)


def test_undefined_reference_c() -> None:
    errs = errors("undef_regcomp")
    assert [(d.kind, d.symbol, d.file, d.function) for d in errs] == [
        ("undefined-reference", "regcomp", "undef_regcomp.c", "main"),
        ("undefined-reference", "regfree", "undef_regcomp.c", "main"),
    ]


def test_undefined_reference_cxx_keeps_function_context() -> None:
    d = one("undef_socket_cxx")
    assert (d.kind, d.symbol, d.tool) == ("undefined-reference", "socket", "ld")
    assert d.function.startswith("n::open_sock(")


def test_missing_libraries() -> None:
    assert one("no_lpthread").symbol == "pthread"
    assert [d.symbol for d in errors("no_lrt_ldl")] == ["rt", "dl"]


def test_implicit_declaration_is_warning_unless_werror() -> None:
    log = parse((DIAG / "implicit_decl.log").read_text())
    assert log.errors == []
    assert [(d.kind, d.symbol) for d in log.warnings] == [("implicit-decl", "epoll_create1")]
    d = one("implicit_decl_werror")
    assert (d.kind, d.symbol, d.severity) == ("implicit-decl", "epoll_create1", "error")


def test_undeclared_c_and_cxx() -> None:
    assert [d.symbol for d in errors("undeclared_ident")] == ["SO_PEERCRED", "MSG_MORE"]
    assert [d.symbol for d in errors("undeclared_cxx")] == ["SO_PEERCRED", "std::foo"]
    assert {d.kind for d in errors("undeclared_cxx")} == {"undeclared"}


def test_no_member_and_unknown_type() -> None:
    errs = errors("no_member")
    assert (errs[0].kind, errs[0].symbol, errs[0].member) == ("no-member", "struct dirent",
                                                               "d_type")
    assert (errs[1].kind, errs[1].symbol) == ("undeclared", "DT_DIR")
    d = one("unknown_type")
    assert (d.kind, d.symbol) == ("unknown-type", "cpu_set_t")


def test_warnings_only_build_has_no_errors() -> None:
    for name in ("warning_only", "incompatible_ptr"):
        log = parse((DIAG / f"{name}.log").read_text())
        assert log.errors == [] and len(log.warnings) == 1


def test_cmake_and_make() -> None:
    log = parse((DIAG / "cmake_make_link.log").read_text())
    assert [(d.kind, d.symbol) for d in log.errors] == [("missing-library", "pthread")]
    assert log.phase == "link"
    assert log.failed_targets[0] == "CMakeFiles/demo.dir/build.make:97: libdemo.so"
    log = parse((DIAG / "cmake_missing_source.log").read_text())
    assert log.phase == "configure"
    first = log.errors[0]
    assert (first.kind, first.file, first.line, first.symbol) == (
        "cmake-error", "CMakeLists.txt", 3, "add_library")
    assert "Cannot find source file: missing_file.c" in first.message


def test_missing_package_message() -> None:
    text = (
        'CMake Error at /usr/share/cmake-3.28/Modules/FindPackageHandleStandardArgs.cmake:230'
        ' (message):\n'
        '  Could NOT find OpenSSL, try to set the path to OpenSSL root folder in the\n'
        '  system variable OPENSSL_ROOT_DIR (missing: OPENSSL_CRYPTO_LIBRARY)\n'
    )
    d = parse(text).errors[0]
    assert (d.kind, d.symbol) == ("missing-package", "OpenSSL")


def test_unicode_quotes_and_duplicates() -> None:
    text = ("a.c:3:5: error: ‘FOO’ undeclared (first use in this function)\n"
            "a.c:3:5: error: ‘FOO’ undeclared (first use in this function)\n")
    errs = parse(text).errors
    assert len(errs) == 1 and errs[0].symbol == "FOO"
