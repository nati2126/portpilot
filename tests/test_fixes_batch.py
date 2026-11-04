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


# ---- from the rerun of the 8 failures (Nov 4) ----------------------------------------------
def test_ld_undefined_reference_to_versioned_symbol() -> None:
    """libcoap examples: ld names the symbol with its version and the library it is in."""
    log = ("/q/x86_64-pc-nto-qnx8.0.0-ld: CMakeFiles/tiny.dir/examples/tiny.c.o: undefined "
           "reference to symbol 'freeaddrinfo@@libsocket.so.4'\n"
           "/q/x86_64-pc-nto-qnx8.0.0-ld: /q/target/qnx/x86_64/lib/libsocket.so.4: error "
           "adding symbols: DSO missing from command line\n")
    errs = parse(log).errors
    assert [(d.kind, d.symbol) for d in errs] == [("undefined-reference", "freeaddrinfo")]


def test_expected_before_an_undefined_type_macro() -> None:
    """open62541: LIST_ENTRY(x) pointers; with no <sys/queue.h>."""
    log = ("/w/eventloop_posix.h:233:5: error: expected specifier-qualifier-list before "
           "'LIST_ENTRY'\n/w/a.c:9:1: error: expected ';' before '(' token\n")
    d = parse(log).errors
    assert (d[0].kind, d[0].symbol) == ("unknown-type", "LIST_ENTRY")
    assert d[1].kind == "compile-error"


def test_internal_header_is_reported_as_its_public_header(tmp_path: Path) -> None:
    """sockaddr_in6 is in <netinet6/in6.h>, which QNX's <netinet/in.h> includes only when
    __EXT_POSIX1_200112; devs/ copies of public headers are not candidates."""
    from portpilot.facts import declaring_headers
    inc = _inc(tmp_path, {
        "netinet6/in6.h": '#ifndef __KAME_NETINET_IN_H_INCLUDED_\n#error "do not include '
                          'netinet6/in6.h directly, include netinet/in.h.  see RFC2553"\n'
                          "#endif\nstruct sockaddr_in6 {\n  int x;\n};\n",
        "netinet/in.h": "#ifndef __QNXNTO__\n#include <netinet6/in6.h>\n#else\n"
                        "#if defined(__EXT_POSIX1_200112)\n#include <netinet6/in6.h>\n"
                        "#endif\n#endif\n",
        "sys/queue.h": "#define\tLIST_ENTRY(type) struct { type *le_next; }\n",
        "devs/sys/queue.h": "#define\tLIST_ENTRY(type) struct { type *le_next; }\n"})
    (hdr, conds, _), = declaring_headers("sockaddr_in6", inc)
    assert hdr == "netinet/in.h"
    assert conds == ["defined(__QNXNTO__)", "defined(__EXT_POSIX1_200112)"]  # in the #else
    assert [h for h, _, _ in declaring_headers("LIST_ENTRY", inc)] == ["sys/queue.h"]


def test_strict_mode_when_the_public_header_is_already_included(
        kb: KnowledgeBase, tmp_path: Path) -> None:
    inc = _inc(tmp_path, {
        "netinet6/in6.h": '#error "do not include netinet6/in6.h directly, include '
                          'netinet/in.h."\nstruct sockaddr_in6 {\n  int x;\n};\n',
        "netinet/in.h": "#if defined(__EXT_POSIX1_200112)\n#include <netinet6/in6.h>\n"
                        "#endif\n"})
    (tmp_path / "a.h").write_text("#include <netinet/in.h>\nsockaddr_in6 s;\n")
    log = f"{tmp_path}/a.h:2:1: error: 'sockaddr_in6' does not name a type\n"
    fixes, unfixed = fx.from_diagnostics(parse(log).errors, kb, None, tmp_path, None, inc)
    assert unfixed == [] and [f.rule_id for f in fixes] == ["strict-mode-hides-posix"]


def test_no_cxx_header_for_a_c_file(kb: KnowledgeBase, tmp_path: Path) -> None:
    """open62541: 'pointers' (a LIST_* macro argument) once matched <CL/opencl.hpp>."""
    inc = _inc(tmp_path, {"CL/opencl.hpp": "  pointers,\n"})
    (tmp_path / "t.c").write_text("#include <stdio.h>\nint f(void) { return pointers; }\n")
    log = f"{tmp_path}/t.c:2:22: error: 'pointers' undeclared (first use in this function)\n"
    fixes, unfixed = fx.from_diagnostics(parse(log).errors, kb, None, tmp_path, None, inc)
    assert fixes == [] and len(unfixed) == 1


def test_qnx_header_in_every_caller_then_qnx_source(kb: KnowledgeBase, tmp_path: Path) -> None:
    """paho.mqtt.c: be32toh is called in SHA1.c and WebSocket.c; <net/netbyte.h> declares
    it only under __EXT_BSD."""
    inc = _inc(tmp_path, {"net/netbyte.h": "#ifdef __EXT_BSD\n"
                          "#define be32toh(__x) __NET_BE32((__x))\n#endif\n"})
    src = tmp_path / "src"
    src.mkdir()
    for f in ("SHA1.c", "WebSocket.c"):
        (src / f).write_text("#include <string.h>\nunsigned f(unsigned x) "
                             "{ return be32toh(x); }\n")
    log = (f"{src}/SHA1.c:2:35: warning: implicit declaration of function 'be32toh' "
           "[-Wimplicit-function-declaration]\n"
           "/usr/bin/ld: libpaho.so: undefined reference to `be32toh'\n")
    parsed = parse(log)
    implicit = {w.symbol: w for w in parsed.warnings if w.kind == "implicit-decl"}
    fixes, _ = fx.from_diagnostics(parsed.errors, kb, None, tmp_path, implicit, inc)
    assert sorted(f.path for f in fixes) == ["src/SHA1.c", "src/WebSocket.c"]
    for f in fixes:
        assert fx.apply(f, PortSpec("x"), tmp_path)
    # still undefined on the next attempt: the build hides __EXT_BSD
    again, _ = fx.from_diagnostics(parsed.errors, kb, None, tmp_path, implicit, inc)
    assert [f.rule_id for f in again] == ["strict-mode-hides-posix"]


def test_latest_release_tag(tmp_path: Path) -> None:
    import subprocess

    from portpilot.port import latest_release_tag
    repo = tmp_path / "r"
    repo.mkdir()

    def git(*a: str) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo,
                       check=True, capture_output=True)
    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "x")
    for t in ("v1.9.0", "v1.10.0", "v1.11.0-rc1", "nightly", "v2.0-beta"):
        git("tag", t)
    assert latest_release_tag(str(repo)) == "v1.10.0"
    git("tag", "1.10.2")  # zlib-ng: its own 2.x tags next to zlib's v1.2.11
    assert latest_release_tag(str(repo)) == "1.10.2"
    import pytest

    from portpilot.build import BuildError
    with pytest.raises(BuildError):  # never "no tags" (= silently port master)
        latest_release_tag(str(tmp_path / "missing"))


def test_dependency_port_cannot_damage_build_files(tmp_path: Path) -> None:
    """The official cunit port's hook defaults its source to ../../.. (the build-files root)
    and runs `rm -f */Makefile ...` there. PortPilot passes QNX_PROJECT_ROOT and restores
    any tracked build-files file a dependency build changes anyway."""
    import os
    import shutil
    import subprocess

    import pytest

    from portpilot.deps import ensure_port
    if not shutil.which("make") or not shutil.which("git"):
        pytest.skip("needs make and git")
    bf = tmp_path / "build-files"
    cpu = bf / "ports" / "evil" / "nto-x86_64-o"
    cpu.mkdir(parents=True)
    (bf / "ports" / "evil" / "README.md").write_text(
        "git clone https://github.com/x/evil.git\n")
    (bf / "ports" / "other").mkdir()
    (bf / "ports" / "other" / "Makefile").write_text("all:\n")
    (cpu / "Makefile").write_text(
        "R := $(if $(QNX_PROJECT_ROOT),$(QNX_PROJECT_ROOT),../../..)\n"
        "install:\n\t@echo root=$(R)\n\trm -f ../../other/Makefile\n")
    (tmp_path / "evil").mkdir()  # the port's source, already cloned next to build-files
    for a in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t",
                                               "commit", "-q", "-m", "x"]):
        subprocess.run(["git", *a], cwd=bf, check=True, capture_output=True)
    log = tmp_path / "dep.log"
    port, why = ensure_port("evil", tmp_path / "stage", dict(os.environ), log, bf)
    assert (port, why) == ("evil", "")
    text = log.read_text()
    assert f"root={tmp_path / 'evil'}" in text
    assert "restored them from git" in text
    assert (bf / "ports" / "other" / "Makefile").exists()


def test_header_goes_after_an_include_that_is_active_at_the_use(
        kb: KnowledgeBase, tmp_path: Path) -> None:
    """paho.mqtt.c SHA1.c: the file's last #include is inside `#if defined(SHA1_TEST)`."""
    inc = _inc(tmp_path, {"net/netbyte.h": "#define be32toh(__x) __NET_BE32((__x))\n"})
    (tmp_path / "SHA1.c").write_text(
        "#include \"SHA1.h\"\n#if defined(__linux__)\n#include <endian.h>\n#endif\n"
        "unsigned f(unsigned x) { return be32toh(x); }\n"
        "#if defined(SHA1_TEST)\n#include <stdio.h>\n#endif\n")
    fixes, _ = fx.from_diagnostics(
        parse("/usr/bin/ld: a.so: undefined reference to `be32toh'\n").errors, kb, None,
        tmp_path, {"be32toh": None}, inc)  # type: ignore[dict-item]
    assert len(fixes) == 1 and fx.apply(fixes[0], PortSpec("x"), tmp_path)
    assert (tmp_path / "SHA1.c").read_text().startswith(
        "#include \"SHA1.h\"\n#if defined(__QNX__)\n#include <net/netbyte.h>\n#endif\n")


def test_bundled_test_framework_build_failure() -> None:
    """civetweb downloads Check for its tests (ExternalProject); that copy fails on QNX."""
    from portpilot.port import _bundled_test_framework
    log = ("CMake Error at /b/third_party/src/check-unit-test-framework-stamp/"
           "check-unit-test-framework-build-Release.cmake:49 (message):\n"
           "  Command failed: 2\n\n")
    d = parse(log).errors[0]
    assert _bundled_test_framework(d) == "check-unit-test-framework"
    other = parse("CMake Error at /b/src/zlib-stamp/zlib-build-Release.cmake:49 (message):\n"
                  "  Command failed: 2\n\n").errors[0]
    assert _bundled_test_framework(other) == ""


def test_recompile_with_fpic(kb: KnowledgeBase, tmp_path: Path) -> None:
    """open62541 adds -fPIC inside if(CMAKE_COMPILER_IS_GNUCC ...), false for qcc."""
    log = ("/q/x86_64-pc-nto-qnx8.0.0-ld: CMakeFiles/o.dir/src/a.c.o: relocation "
           "R_X86_64_TPOFF32 against `notifyPayload.0' can not be used when making a shared "
           "object; recompile with -fPIC\n")
    fixes, unfixed = fx.from_diagnostics(parse(log).errors, kb, None, tmp_path)
    assert unfixed == [] and [f.rule_id for f in fixes] == ["qcc-not-gnucc"]
    spec = PortSpec("x")
    assert fx.apply(fixes[0], spec, tmp_path)
    assert [s.value for s in spec.cmake_args][-1] == "-DCMAKE_POSITION_INDEPENDENT_CODE=ON"


def test_libc_only_skips_branches_qnx_never_takes(kb: KnowledgeBase, tmp_path: Path) -> None:
    """paho.mqtt.c: only the generic else() branch is used on QNX, not Linux's or FreeBSD's."""
    (tmp_path / "CMakeLists.txt").write_text(
        'if(CMAKE_SYSTEM_NAME MATCHES "Linux")\n  set(LIBS_SYSTEM c dl pthread rt)\n'
        'elseif(CMAKE_SYSTEM_NAME MATCHES "FreeBSD")\n  set(LIBS_SYSTEM compat pthread)\n'
        "else()\n  set(LIBS_SYSTEM c pthread)\nendif()\n")
    fixes, _ = fx.from_diagnostics(parse("/usr/bin/ld: cannot find -lpthread\n").errors, kb,
                                   None, tmp_path)
    assert [f.line for f in fixes] == [6]


def test_test_framework_header_without_find_package() -> None:
    """libcoap v4.3.5: tests/testdriver.c includes <CUnit/CUnit.h>; CMake never asks."""
    from portpilot.port import _bundled_test_framework
    d = parse("/w/tests/testdriver.c:13:10: fatal error: CUnit/CUnit.h: No such file or "
              "directory\n").errors[0]
    assert _bundled_test_framework(d) == "CUnit"
    other = parse("/w/src/a.c:1:10: fatal error: sys/epoll.h: No such file or "
                  "directory\n").errors[0]
    assert _bundled_test_framework(other) == ""


def test_libc_only_keeps_branches_that_depend_on_project_variables(
        kb: KnowledgeBase, tmp_path: Path) -> None:
    """open62541: if("${UA_ARCHITECTURE}" STREQUAL "posix") - the project sets it."""
    (tmp_path / "CMakeLists.txt").write_text(
        'set(UA_ARCHITECTURE "posix")\n'
        'if("${UA_ARCHITECTURE}" STREQUAL "posix")\n'
        '  list(APPEND open62541_PUBLIC_LIBRARIES "pthread")\nendif()\n'
        'if(APPLE)\n  list(APPEND LIBS pthread)\nendif()\n')
    fixes, _ = fx.from_diagnostics(parse("/usr/bin/ld: cannot find -lpthread\n").errors, kb,
                                   None, tmp_path)
    assert [f.line for f in fixes] == [3]


def test_catch2_discovery_on_the_host(kb: KnowledgeBase, tmp_path: Path) -> None:
    """sockpp: catch_discover_tests runs the QNX unit_tests program on the Linux host."""
    log = ("CMake Error at /s/stage/x86_64/usr/local/lib/cmake/Catch2/CatchAddTests.cmake:70 "
           "(message):\n  Error running test executable '/b/tests/unit/unit_tests':\n\n")
    fixes, unfixed = fx.from_diagnostics(parse(log).errors, kb, None, tmp_path)
    assert unfixed == [] and [f.rule_id for f in fixes] == ["test-discovery-on-host"]
    assert fixes[0].setting is not None
    assert fixes[0].setting.value == "-DCMAKE_CATCH_DISCOVER_TESTS_DISCOVERY_MODE=PRE_TEST"


def test_pre_test_discovery_runs_the_whole_program(tmp_path: Path) -> None:
    from portpilot.qnxtests import read_ctest
    b = tmp_path / "build" / "tests" / "unit"
    b.mkdir(parents=True)
    inner = b / "unit_tests-b12d07c_include.cmake"
    inner.write_text("if(EXISTS \"x\")\n  include(\"CatchAddTests.cmake\")\n"
                     f"  catch_discover_tests_impl(\n      TEST_EXECUTABLE [==[{b}/unit_tests]==]\n"
                     "  )\nendif()\n")
    (b / "unit_tests_include.cmake").write_text(f'include("{inner}")')
    (b / "CTestTestfile.cmake").write_text(
        f'include("{b}/unit_tests_include.cmake")\n')
    (t,) = read_ctest(tmp_path / "build")
    assert t.exe == f"{b}/unit_tests" and t.name == "unit_tests (all cases)"


def test_optional_absent_library(kb: KnowledgeBase, tmp_path: Path) -> None:
    """open62541 tests: list(APPEND LIBS subunit)."""
    (tmp_path / "CMakeLists.txt").write_text(
        "set(LIBS ${CHECK_LIBRARIES})\nif(NOT WIN32 AND NOT APPLE)\n"
        "    list(APPEND LIBS subunit)\nendif()\n")
    fixes, unfixed = fx.from_diagnostics(parse("/q/ld: cannot find -lsubunit\n").errors, kb,
                                         None, tmp_path)
    assert unfixed == [] and [(f.rule_id, f.line) for f in fixes] == [
        ("link-optional-absent", 3)]
