"""The generated port folder follows build-files conventions and reproduces our verified ports.

tests/data/ports/{fmt,nng}.common.mk are the hand-made ports that passed 602/602 (fmt) and
64/64 (nng) on QNX 8.0 on Nov 4, 2026.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from portpilot.scaffold import (
    ARCH_MAKEFILE,
    TOP_MAKEFILE,
    PortSpec,
    Setting,
    initial_spec,
    pick_test_option,
    render,
    render_common_mk,
    render_readme,
    write,
)

DATA = Path(__file__).parent / "data" / "ports"


def dargs(mk: str) -> set[str]:
    """The -D settings in CMAKE_ARGS."""
    block = mk.split("CMAKE_ARGS = ", 1)[1].split("\n\n", 1)[0]
    return {a.rstrip("\\").strip() for a in block.split("\n") if a.strip().startswith("-D")} | {
        block.split()[0]}


def recipes(mk: str) -> list[str]:
    return [ln for ln in mk.splitlines() if ln.startswith("\t")]


def fmt_spec() -> PortSpec:
    return PortSpec(name="fmt", test_option="FMT_TEST", muslflt=True,
                    options=[Setting("-DFMT_DOC=OFF", "docs")],
                    ldflags=[Setting("-lregex", "regcomp is in libregex", "link-regex")])


def nng_spec() -> PortSpec:
    return PortSpec(name="nng", test_option="NNG_TESTS", muslflt=True,
                    cmake_args=[Setting("-DCMAKE_REQUIRED_LIBRARIES=socket", "libsocket"),
                                Setting("-DNNG_ENABLE_TLS=OFF", "no TLS")])


def test_cmake_args_match_the_verified_ports() -> None:
    for spec, ref in ((fmt_spec(), "fmt"), (nng_spec(), "nng")):
        want = (DATA / f"{ref}.common.mk").read_text()
        got = render_common_mk(spec)
        assert dargs(got) == dargs(want), ref
        assert "LDFLAGS += -Wl,--build-id=md5" + (" -lregex" if ref == "fmt" else "") in got


def test_recipes_are_the_verified_ones_plus_robustness_fixes() -> None:
    want = recipes((DATA / "fmt.common.mk").read_text())
    got = recipes(render_common_mk(fmt_spec()))
    # added: copy the programs qnxtests.sh runs that CTest only discovers at test time
    # (gtest/Catch2 PRE_TEST: no add_test line names them; sockpp, Nov 5)
    added = [g for g in got if "qnxtests.sh | sort -u" in g or g.startswith("\t  while read b")]
    assert len(added) == 2
    got = [g for g in got if g not in added]
    assert len(got) == len(want)
    diff = [(w, g) for w, g in zip(want, got, strict=True) if w != g]
    # 1. only copy test programs that are built in the tree (not /usr/bin/python3 etc.)
    # 2. qnxtests.sh is optional (it is generated after the first build)
    # 3. shared libraries from any depth: FetchContent builds Catch2 in _deps/ (spdlog, Nov 5)
    assert len(diff) == 3
    assert 'grep -F "$$(pwd)/"' in diff[0][1]
    assert diff[1][1].startswith("\t@if [ -f $(PROJECT_ROOT)/qnxtests.sh ]")
    assert "-maxdepth" not in diff[2][1] and "CMakeFiles" in diff[2][1]


def test_every_qnx_setting_is_commented_with_its_reason() -> None:
    mk = render_common_mk(nng_spec())
    assert "#-DCMAKE_REQUIRED_LIBRARIES=socket: libsocket" in mk
    mk = render_common_mk(fmt_spec())
    assert "#-lregex: regcomp is in libregex" in mk


def test_project_hooks_only_with_muslflt() -> None:
    spec = nng_spec()
    spec.muslflt = False
    files = render(spec)
    assert "project_hooks.cmake" not in files
    assert "CMAKE_PROJECT_INCLUDE" not in files["common.mk"]
    assert "project_hooks.cmake" in render(fmt_spec())


def test_layout_and_boilerplate(tmp_path: Path) -> None:
    files = render(fmt_spec(), qnxtests="#!/bin/sh\n", patch="diff --git a/x b/x\n")
    assert set(files) == {"Makefile", "common.mk", "qnx.nto.toolchain.cmake", "README.md",
                          "nto-x86_64-o/Makefile", "nto-aarch64-le/Makefile",
                          "project_hooks.cmake", "qnxtests.sh", "patches/qnx.patch"}
    assert files["Makefile"] == TOP_MAKEFILE
    assert files["nto-x86_64-o/Makefile"] == ARCH_MAKEFILE == "include ../common.mk\n"
    tc = files["qnx.nto.toolchain.cmake"]
    assert tc.startswith("set(QNX TRUE)\nset(CMAKE_SYSTEM_NAME QNX)\n")
    assert "CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY" in tc
    write(tmp_path / "fmt", files)
    assert (tmp_path / "fmt" / "patches" / "qnx.patch").read_text() == "diff --git a/x b/x\n"
    # recipes must be tab-indented for make
    assert re.search(r"^\tcd build && cmake \$\(CMAKE_ARGS\)",
                     (tmp_path / "fmt" / "common.mk").read_text(), re.M)


def test_pick_test_option() -> None:
    assert pick_test_option({"FMT_TEST": "ON", "FMT_DOC": "ON", "FMT_CUDA_TEST": "OFF"},
                            "fmt", False) == "FMT_TEST"
    assert pick_test_option({"NNG_TESTS": "ON", "NNG_TOOLS": "ON"}, "nng", True) == "NNG_TESTS"
    assert pick_test_option({"YAML_CPP_BUILD_TESTS": "ON"}, "yaml-cpp", True) == \
        "YAML_CPP_BUILD_TESTS"
    assert pick_test_option({"FOO": "ON"}, "x", True) == "BUILD_TESTING"
    assert pick_test_option({}, "x", False) == ""


def test_initial_spec_from_fixture(minilib: Path, tmp_path: Path) -> None:
    src = tmp_path / "minilib"
    shutil.copytree(minilib, src)
    spec = initial_spec(src)
    assert spec.name == "minilib" and spec.test_option == "MINI_TESTS"


def test_readme_is_short_and_has_the_commands() -> None:
    spec = nng_spec()
    spec.upstream, spec.commit, spec.has_patch = "https://github.com/nanomsg/nng", "caf6f9f", True
    text = render_readme(spec, {"Result": "64/64 test programs pass on QNX"},
                         [("src/x.c", "include <errno.h>", "QNX has no <sys/errno.h>")])
    assert "| Result | **64/64 test programs pass on QNX** |" in text
    assert "git -C nng apply $(pwd)/build-files/ports/nng/patches/qnx.patch" in text
    assert "make -C build-files/ports/nng install" in text
    assert "| `src/x.c` | include <errno.h> | QNX has no <sys/errno.h> |" in text
    assert len(text.splitlines()) < 60


def test_readme_builds_dependencies_first_in_the_official_workspace(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from portpilot.scaffold import PortSpec, render_readme

    monkeypatch.setenv("PORTPILOT_BUILD_FILES", "/nonexistent")
    monkeypatch.setenv("HOME", "/nonexistent")
    spec = PortSpec("sockpp", "https://github.com/fpagliughi/sockpp.git", "v1.0.0",
                    has_patch=True, deps=["Catch2"])
    md = render_readme(spec)
    i = md.index
    assert i("git clone https://github.com/qnx-ports/build-files.git") \
        < i("git -C sockpp apply $(pwd)/build-files/ports/sockpp/patches/qnx.patch") \
        < i("git clone https://github.com/qnx-ports/Catch2.git Catch2") \
        < i("make -C build-files/ports/Catch2 install JLEVEL=$(nproc)") \
        < i("BUILD_TESTING=ON make -C build-files/ports/sockpp install JLEVEL=$(nproc)")
    assert "USE_INSTALL_ROOT=true` to every `make` line" in md
    assert "QNX_PROJECT_ROOT" not in md  # the default ../../sockpp fits the workspace
