"""Rules added from the first 12-library batch (Nov 4): link lists, QNX headers, strict
modes, qcc -dumpmachine, and dependencies from official QNX ports."""

from __future__ import annotations

from pathlib import Path

from portpilot import fixes as fx
from portpilot.deps import official_port, port_source
from portpilot.diagnostics import parse
from portpilot.kb import KnowledgeBase
from portpilot.scaffold import PortSpec


def test_pthread_and_dl_in_a_link_list_variable(kb: KnowledgeBase, tmp_path: Path) -> None:
    """libhv: set(LIBS ${LIBS} pthread m dl); CMake's own CMAKE_REQUIRED_* is left alone."""
    (tmp_path / "CMakeLists.txt").write_text(
        'set(CMAKE_REQUIRED_LIBRARIES "-pthread")\n'
        "set(LIBS ${LIBS} pthread m dl)\n"
        "set(HANDLE_dl_OPEN 1)\n"
        "target_link_libraries(hv ${LIBS})\n")
    log = ("/usr/bin/ld: cannot find -lpthread: No such file or directory\n"
           "/usr/bin/ld: cannot find -ldl: No such file or directory\n")
    fixes, unfixed = fx.from_diagnostics(parse(log).errors, kb, None, tmp_path)
    assert unfixed == [] and len(fixes) == 2
    for f in fixes:
        assert fx.apply(f, PortSpec("x"), tmp_path)
    text = (tmp_path / "CMakeLists.txt").read_text()
    assert ("set(LIBS ${LIBS} $<$<NOT:$<PLATFORM_ID:QNX>>:pthread> m "
            "$<$<NOT:$<PLATFORM_ID:QNX>>:dl>)") in text
    assert 'set(CMAKE_REQUIRED_LIBRARIES "-pthread")' in text
    assert "set(HANDLE_dl_OPEN 1)" in text  # 'dl' inside a word is never touched
    for f in fixes:  # idempotent: wrapped tokens are not wrapped again
        assert not fx.apply(f, PortSpec("x"), tmp_path)


def _inc(tmp_path: Path, files: dict[str, str]) -> Path:
    inc = tmp_path / "inc"
    for rel, text in files.items():
        (inc / rel).parent.mkdir(parents=True, exist_ok=True)
        (inc / rel).write_text(text)
    return inc


def test_function_declared_in_a_qnx_header_the_code_never_includes(
        kb: KnowledgeBase, tmp_path: Path) -> None:
    """paho.mqtt.c: be32toh is in <net/netbyte.h>; the code includes <endian.h> only on
    Linux/macOS/BSD."""
    inc = _inc(tmp_path, {"net/netbyte.h": "#define be32toh(__x) __NET_BE32((__x))\n"})
    src = tmp_path / "src"
    src.mkdir()
    (src / "SHA1.c").write_text("#if defined(__linux__)\n#  include <endian.h>\n#endif\n"
                                "#include <string.h>\nunsigned f(unsigned x) "
                                "{ return be32toh(x); }\n")
    log = (f"{src}/SHA1.c:5:35: warning: implicit declaration of function 'be32toh' "
           "[-Wimplicit-function-declaration]\n"
           "/usr/bin/ld: libpaho.so: undefined reference to `be32toh'\n")
    parsed = parse(log)
    implicit = {w.symbol: w for w in parsed.warnings if w.kind == "implicit-decl"}
    fixes, unfixed = fx.from_diagnostics(parsed.errors, kb, None, tmp_path, implicit, inc)
    assert unfixed == [] and [f.rule_id for f in fixes] == ["qnx-header"]
    assert fx.apply(fixes[0], PortSpec("x"), tmp_path)
    assert ("#include <string.h>\n#if defined(__QNX__)\n#include <net/netbyte.h>\n#endif\n"
            in (src / "SHA1.c").read_text())
    # no second copy on the next attempt
    again, _ = fx.from_diagnostics(parsed.errors, kb, None, tmp_path, implicit, inc)
    assert again == []


def test_strict_mode_gets_qnx_source(kb: KnowledgeBase, tmp_path: Path) -> None:
    """spdlog with -std=c++17: '::fstat' has not been declared (F-013)."""
    inc = _inc(tmp_path, {"sys/stat.h": "#if defined(__EXT_POSIX1_198808)\n"
                          "extern int fstat(int __fildes, struct stat *__buf);\n#endif\n"})
    log = ("/w/include/spdlog/details/os-inl.h:236:11: error: '::fstat' has not been "
           "declared; did you mean 'stat'?\n")
    d = parse(log).errors
    assert d[0].kind == "undeclared" and d[0].symbol.removeprefix("::") == "fstat"
    fixes, unfixed = fx.from_diagnostics(d, kb, None, tmp_path, None, inc)
    assert unfixed == [] and fixes[0].rule_id == "strict-mode-hides-posix"
    spec = PortSpec("x")
    assert fx.apply(fixes[0], spec, tmp_path)
    assert [s.value for s in spec.cflags] == ["-D_QNX_SOURCE"]
    assert not fx.apply(fixes[0], spec, tmp_path)


def test_qcc_dumpmachine_probe(kb: KnowledgeBase, tmp_path: Path) -> None:
    """civetweb: execute_process(COMMAND ${CMAKE_C_COMPILER} -dumpmachine) fails with qcc."""
    (tmp_path / "cmake").mkdir()
    (tmp_path / "cmake" / "Arch.cmake").write_text(
        "execute_process(\n  COMMAND ${CMAKE_C_COMPILER} -dumpmachine\n"
        "  RESULT_VARIABLE RESULT)\n")
    log = ("CMake Error at cmake/Arch.cmake:37 (message):\n"
           "  Failed to determine target architecture triplet: 1\n\n")
    fixes, _ = fx.from_diagnostics(parse(log).errors, kb, None, tmp_path)
    assert [f.rule_id for f in fixes] == ["qcc-dumpmachine"]
    assert fx.apply(fixes[0], PortSpec("x"), tmp_path)
    assert ("COMMAND $ENV{QNX_HOST}/usr/bin/nto${CMAKE_SYSTEM_PROCESSOR}-gcc -dumpmachine"
            in (tmp_path / "cmake" / "Arch.cmake").read_text())


def test_official_port_lookup_and_source(tmp_path: Path) -> None:
    bf = tmp_path / "build-files"
    for name in ("Catch2", "check", "googletest"):
        (bf / "ports" / name).mkdir(parents=True)
    (bf / "ports" / "Catch2" / "README.md").write_text(
        "```bash\ngit clone https://github.com/qnx-ports/build-files.git\n"
        "git clone https://github.com/qnx-ports/Catch2.git\n```\n")
    (bf / "ports" / "check" / "README.md").write_text(
        "git clone -b v0.15.2 https://github.com/libcheck/check.git\n")
    assert official_port("Catch2", bf) == "Catch2"
    assert official_port("CHECK", bf) == "check"  # 'Could NOT find CHECK'
    assert official_port("CMocka", bf) is None
    assert port_source(bf / "ports" / "Catch2") == ("https://github.com/qnx-ports/Catch2", "")
    assert port_source(bf / "ports" / "check") == ("https://github.com/libcheck/check",
                                                    "v0.15.2")
    assert port_source(bf / "ports" / "googletest") is None  # no README
