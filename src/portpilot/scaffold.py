"""Generate a port folder in the qnx-ports/build-files layout.

    ports/<name>/
      Makefile                  recurse into nto-<cpu>-<variant>/ (identical in every port)
      common.mk                 the CMake build, with every QNX-specific setting commented
      nto-x86_64-o/Makefile     include ../common.mk
      nto-aarch64-le/Makefile   include ../common.mk
      qnx.nto.toolchain.cmake   the toolchain used by most ports, plus find-root isolation
      project_hooks.cmake       only when muslflt is needed (float formatting, F-002)
      qnxtests.sh               test runner for the target, generated from CTest
      patches/qnx.patch         source changes, if any
      README.md

Conventions: docs/conventions.md (studied from build-files @ 1964dba).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .scan_cmake import parse_commands

ARCH_DIRS = {"x86_64": "nto-x86_64-o", "aarch64": "nto-aarch64-le"}


@dataclass
class Setting:
    """One QNX-specific build setting and why it is there."""

    value: str  # "-DCMAKE_REQUIRED_LIBRARIES=socket", "-lregex", ...
    reason: str  # one line, shown as a comment in common.mk and in the README
    rule: str = ""  # knowledge-base rule id
    source: str = ""  # e.g. "docs/ground-truth.md#f-004"


@dataclass
class PortSpec:
    name: str
    upstream: str = ""  # URL
    commit: str = ""
    test_option: str = "BUILD_TESTING"  # "" if the project has no test switch
    options: list[Setting] = field(default_factory=list)  # project options, e.g. docs off
    cmake_args: list[Setting] = field(default_factory=list)  # QNX-specific -D settings
    ldflags: list[Setting] = field(default_factory=list)
    cflags: list[Setting] = field(default_factory=list)
    muslflt: bool = False
    has_patch: bool = False
    deps: list[str] = field(default_factory=list)  # official QNX ports this one needs

    def add_cflag(self, s: Setting) -> bool:
        if any(x.value == s.value for x in self.cflags):
            return False
        self.cflags.append(s)
        return True

    def add_ldflag(self, s: Setting) -> bool:
        if any(x.value == s.value for x in self.ldflags):
            return False
        self.ldflags.append(s)
        return True

    def add_cmake_arg(self, s: Setting) -> bool:
        key = s.value.split("=", 1)[0]
        if any(x.value.split("=", 1)[0] == key for x in self.cmake_args):
            return False
        self.cmake_args.append(s)
        return True


# ---- reading the project's options -----------------------------------------------------
_TEST_OPT = re.compile(r"^(?:[A-Z][A-Z0-9]*_)*(?:BUILD_|ENABLE_)?(?:TESTS?|TESTING|UNIT_TESTS?)$")
_DOC_OPT = re.compile(r"^(?:[A-Z][A-Z0-9]*_)*(?:BUILD_|ENABLE_|GENERATE_)?(?:DOCS?|DOCUMENTATION)$")
_NOT_TEST = re.compile(r"(?:CUDA|FUZZ|BENCH|INSTALL|COVERAGE|MODULE)", re.I)


def project_options(root: Path) -> dict[str, str]:
    """option() names -> default, from the top-level CMakeLists.txt and cmake/*.cmake."""
    files = [root / "CMakeLists.txt", *sorted((root / "cmake").glob("*.cmake"))]
    opts: dict[str, str] = {}
    for f in files:
        if not f.is_file():
            continue
        for c in parse_commands(f.read_text(encoding="utf-8", errors="replace")):
            if c.name == "option" and c.args and not c.in_body or c.name == "cmake_dependent_option" and c.args and not c.in_body:
                opts.setdefault(c.args[0], c.args[2] if len(c.args) > 2 else "OFF")
    return opts


def uses_ctest(root: Path) -> bool:
    text = (root / "CMakeLists.txt").read_text(encoding="utf-8", errors="replace") \
        if (root / "CMakeLists.txt").is_file() else ""
    return bool(re.search(r"include\s*\(\s*CTest\s*\)|enable_testing\s*\(", text, re.I))


def pick_test_option(opts: dict[str, str], name: str, ctest: bool) -> str:
    cands = [o for o in opts if _TEST_OPT.match(o) and not _NOT_TEST.search(o)]
    prefix = re.sub(r"\W", "_", name).upper()
    for o in cands:  # the project's own prefix first: FMT_TEST, NNG_TESTS, YAML_CPP_BUILD_TESTS
        if o.startswith(prefix + "_"):
            return o
    own = [o for o in cands if o != "BUILD_TESTING"]
    if own:  # a project switch gates the tests even when CTest is included
        return own[0]
    return "BUILD_TESTING" if "BUILD_TESTING" in opts or ctest else ""


def initial_spec(root: Path, name: str | None = None, upstream: str = "",
                 commit: str = "") -> PortSpec:
    name = name or root.name
    opts = project_options(root)
    spec = PortSpec(name=name, upstream=upstream, commit=commit,
                    test_option=pick_test_option(opts, name, uses_ctest(root)))
    for o in opts:
        if _DOC_OPT.match(o):
            spec.options.append(Setting(f"-D{o}=OFF", "docs are not built for the target"))
    return spec


# ---- rendering ----------------------------------------------------------------------------
TOP_MAKEFILE = """LIST=OS
ifndef QRECURSE
QRECURSE=recurse.mk
ifdef QCONFIG
QRDIR=$(dir $(QCONFIG))
endif
endif
include $(QRDIR)$(QRECURSE)
"""

ARCH_MAKEFILE = "include ../common.mk\n"

# The toolchain shared by 18 build-files ports (jansson, libuv, nghttp2, ...), plus the
# find-root modes as a safeguard: with this toolchain alone (no CMAKE_FIND_ROOT_PATH from
# common.mk), find_package(OpenSSL) picked the HOST's /usr/lib/x86_64-linux-gnu/libcrypto.so.
TOOLCHAIN = """set(QNX TRUE)
set(CMAKE_SYSTEM_NAME QNX)
set(CMAKE_C_COMPILER qcc)
set(CMAKE_CXX_COMPILER q++)

# Search only the SDP and the staging area for libraries, headers and packages.
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
"""

PROJECT_HOOKS = """# This file needs to be set as CMAKE_PROJECT_INCLUDE, which will load
# the following code at the end of every project() call.
if (QNX)
    # ---- muslflt linkage ----
    # Using find_library here allows libmuslflt to exist anywhere within CMake's search path
    # This includes SDP default paths and INSTALL_ROOT. This allows much more flexibility
    # than setting this option in common.mk
    find_library(MUSLFLT NAMES libmuslflt.a)
    if (MUSLFLT)
        message(STATUS "Using libmuslflt for correct floating point conversion behavior on QNX")
        add_link_options(-Wl,--whole-archive "${MUSLFLT}" -Wl,--no-whole-archive)
    else()
        message(WARNING "libmuslflt not found, tests involving floating point conversion will not pass on QNX")
    endif()
endif()
"""

_COMMON_HEAD = """ifndef QCONFIG
QCONFIG=qconfig.mk
endif
include $(QCONFIG)

include $(MKFILES_ROOT)/qmacros.mk

NAME = {name}

QNX_PROJECT_ROOT ?= $(PRODUCT_ROOT)/../../{name}/

#$(INSTALL_ROOT_$(OS)) is pointing to $QNX_TARGET
#by default, unless it was manually re-routed to
#a staging area by setting both INSTALL_ROOT_nto
#and USE_INSTALL_ROOT
INSTALL_ROOT ?= $(INSTALL_ROOT_$(OS))

#A prefix path to use **on the target**. This is
#different from INSTALL_ROOT, which refers to a
#installation destination **on the host machine**.
#This prefix path may be exposed to the source code,
#the linker, or package discovery config files (.pc,
#CMake config modules, etc.). Default is /usr/local
PREFIX ?= /usr/local

#choose Release or Debug
CMAKE_BUILD_TYPE ?= Release

BUILD_TESTING ?= OFF

#Where test binaries go when BUILD_TESTING=ON (copy this folder to the target)
TEST_DIR = $(INSTALL_ROOT)/$(CPUVARDIR)/$(PREFIX)/bin/$(NAME)_tests

#override 'all' target to bypass the default QNX build system
ALL_DEPENDENCIES = {name}_all
.PHONY: {name}_all install check clean

include $(MKFILES_ROOT)/qtargets.mk

#Search paths for all of CMake's find_* functions --
#headers, libraries, etc.
#
#$(QNX_TARGET): for architecture-agnostic files shipped with SDP (e.g. headers)
#$(QNX_TARGET)/$(CPUVARDIR): for architecture-specific files in SDP
#$(INSTALL_ROOT)/$(CPUVARDIR): any packages that may have been installed in the staging area
CMAKE_FIND_ROOT_PATH := $(QNX_TARGET);$(QNX_TARGET)/$(CPUVARDIR);$(INSTALL_ROOT)/$(CPUVARDIR)

#Path to CMake modules; These are CMake files installed by other packages
#for downstreams to discover them automatically. We support discovering
#CMake-based packages from inside SDP or in the staging area.
CMAKE_MODULE_PATH := $(QNX_TARGET)/$(CPUVARDIR)/$(PREFIX)/lib/cmake;$(INSTALL_ROOT)/$(CPUVARDIR)/$(PREFIX)/lib/cmake

#Headers from INSTALL_ROOT need to be made available by default
#because CMake and pkg-config do not necessary add it automatically
#if the include path is "default"
CFLAGS += $(FLAGS) \\
          -I$(QNX_TARGET)/$(CPUVARDIR)/$(PREFIX)/include \\
          -I$(INSTALL_ROOT)/$(CPUVARDIR)/$(PREFIX)/include
"""

_BASE_ARGS = [
    "-DCMAKE_TOOLCHAIN_FILE=$(PROJECT_ROOT)/qnx.nto.toolchain.cmake",
    "-DCMAKE_SYSTEM_PROCESSOR=$(CPUVARDIR)",
    '-DCMAKE_C_FLAGS="$(CFLAGS)"',
    '-DCMAKE_CXX_FLAGS="$(CFLAGS)"',
    '-DCMAKE_EXE_LINKER_FLAGS="$(LDFLAGS)"',
    '-DCMAKE_SHARED_LINKER_FLAGS="$(LDFLAGS)"',
    "-DCMAKE_CXX_COMPILER_TARGET=gcc_nto$(CPUVARDIR)",
    "-DCMAKE_C_COMPILER_TARGET=gcc_nto$(CPUVARDIR)",
    '-DCMAKE_INSTALL_PREFIX="$(PREFIX)"',
    '-DCMAKE_STAGING_PREFIX="$(INSTALL_ROOT)/$(CPUVARDIR)/$(PREFIX)"',
    '-DCMAKE_MODULE_PATH="$(CMAKE_MODULE_PATH)"',
    '-DCMAKE_FIND_ROOT_PATH="$(CMAKE_FIND_ROOT_PATH)"',
    "-DCMAKE_BUILD_TYPE=$(CMAKE_BUILD_TYPE)",
    "-DBUILD_SHARED_LIBS=ON",
]

_COMMON_TAIL = """MAKE_ARGS ?= -j $(firstword $(JLEVEL) 1)

ifndef NO_TARGET_OVERRIDE
{name}_all:
\t@mkdir -p build
\tcd build && cmake $(CMAKE_ARGS) $(QNX_PROJECT_ROOT)
\t@cd build && make VERBOSE=1 all $(MAKE_ARGS)

install check: {name}_all
\t@echo Installing...
\t@cd build && make VERBOSE=1 install $(MAKE_ARGS)
ifeq ($(BUILD_TESTING),ON)
\t@mkdir -p $(TEST_DIR)
\t@cd build && grep -rh '^add_test' --include=CTestTestfile.cmake . | sed -E 's/^add_test\\([^ ]+ "([^"]+)".*/\\1/' | grep -F "$$(pwd)/" | sort -u | xargs -r -I{{}} cp {{}} $(TEST_DIR)/
\t@if [ -f $(PROJECT_ROOT)/qnxtests.sh ]; then cp $(PROJECT_ROOT)/qnxtests.sh $(TEST_DIR)/; fi
\t@find build -maxdepth 2 -name 'lib*.so*' -exec cp -P {{}} $(TEST_DIR)/ \\;
\t@echo Tests, qnxtests.sh and shared libraries installed to $(TEST_DIR)
endif
\t@echo Done.

clean iclean spotless:
\trm -rf build

uninstall:
endif
"""


def _comment(s: Setting) -> list[str]:
    src = f" ({s.source})" if s.source else ""
    return [f"#{s.value}: {s.reason}{src}"]


def render_common_mk(spec: PortSpec) -> str:
    out = [_COMMON_HEAD.format(name=spec.name)]
    if spec.cflags:
        out.append("#QNX-specific compiler flags (PortPilot):")
        for s in spec.cflags:
            out += _comment(s)
        out.append("CFLAGS += " + " ".join(s.value for s in spec.cflags))
    out.append("")
    for s in spec.ldflags:
        out += _comment(s)
    out.append(" ".join(["LDFLAGS += -Wl,--build-id=md5", *(s.value for s in spec.ldflags)]))
    out.append("")
    if spec.cmake_args:
        out.append("#QNX-specific CMake settings (PortPilot):")
        for s in spec.cmake_args:
            out += _comment(s)
    args = list(_BASE_ARGS)
    if spec.muslflt:
        args.insert(1, "-DCMAKE_PROJECT_INCLUDE=$(PROJECT_ROOT)/project_hooks.cmake")
    args += [s.value for s in spec.cmake_args] + [s.value for s in spec.options]
    if spec.test_option:
        args.append(f"-D{spec.test_option}=$(BUILD_TESTING)")
    pad = " " * len("CMAKE_ARGS = ")
    lines = [f"CMAKE_ARGS = {args[0]} \\"]
    lines += [f"{pad}{a} \\" for a in args[1:-1]]
    lines.append(f"{pad}{args[-1]}")
    out += lines
    out.append("")
    out.append(_COMMON_TAIL.format(name=spec.name))
    return "\n".join(out)


def render_readme(spec: PortSpec, results: dict[str, str] | None = None,
                  changes: list[tuple[str, str, str]] | None = None) -> str:
    """Short port README. results: Tested/Result/Not built rows; changes: (file, change, why)."""
    r = results or {}
    up = spec.upstream or f"<{spec.name} upstream>"
    url = up.removesuffix(".git") if up.startswith("http") else ""
    title_link = f"[{spec.name}]({url})" if url else spec.name
    lines = [f"# {spec.name} for QNX", "",
             f"{title_link} built for QNX 8.0. Port generated and verified by PortPilot.", "",
             "| | |", "|---|---|",
             f"| Tested | {r.get('Tested', 'QNX SDP 8.0, x86_64, QEMU target')} |",
             f"| Upstream | `{spec.commit or 'HEAD'}`"
             + (" + `patches/qnx.patch`" if spec.has_patch else "") + " |"]
    if "Result" in r:
        lines.append(f"| Result | **{r['Result']}** |")
    if r.get("Not built"):
        lines.append(f"| Not built | {r['Not built']} |")
    clone = url or "<upstream git url>"
    lines += ["", "QNX ports are built from a Linux host.", "", "## Build", "", "```bash",
              "source ~/qnx800/qnxsdp-env.sh",
              f"git clone {clone} {spec.name}"]
    if spec.commit:
        lines.append(f"git -C {spec.name} checkout {spec.commit}")
    if spec.has_patch:
        lines.append(f"git -C {spec.name} apply $(pwd)/build-files/ports/{spec.name}"
                     "/patches/qnx.patch")
    lines += ["STAGE=$HOME/qnx-staging     # install here instead of into the SDP", ""]
    if spec.muslflt:
        lines.append("# Build the muslflt port into the same STAGE first (float formatting).")
    lines += [f"BUILD_TESTING=ON QNX_PROJECT_ROOT=$(pwd)/{spec.name} \\",
              f"  make -C build-files/ports/{spec.name} install -j8 "
              "INSTALL_ROOT_nto=$STAGE USE_INSTALL_ROOT=1",
              "```", "",
              "Output goes to `$STAGE/<arch>/usr/local/`: the library is in `lib/`, and the "
              f"tests are in `bin/{spec.name}_tests/`.", "",
              "## Run the tests on the target", "", "```bash",
              "IP=<target-ip>        # QEMU: mkqnximage --getip",
              f'ssh root@$IP "mkdir -p /data/{spec.name}"',
              f"scp -r $STAGE/x86_64/usr/local/bin/{spec.name}_tests/* "
              f"root@$IP:/data/{spec.name}/",
              f'ssh root@$IP "TIMEOUT_SCALE=3 sh /data/{spec.name}/qnxtests.sh"',
              "```", "",
              "Each test prints a `PASS`/`FAIL`/`TIMEOUT` line, then a summary line. Logs are "
              f"written to `/data/{spec.name}/logs/`.", ""]
    settings = [*spec.cmake_args, *spec.ldflags, *spec.cflags]
    if settings or spec.muslflt or changes:
        lines += ["## What is QNX-specific", ""]
        for s in settings:
            lines.append(f"- **`{s.value}`** (in `common.mk`): {s.reason}")
        if spec.muslflt:
            lines.append("- **muslflt** (in `project_hooks.cmake`): tests expect glibc-style "
                         "float output; QNX libc prints valid but different digits.")
        if changes:
            lines += ["", "| File | Change | Why (QNX behavior) |", "|---|---|---|"]
            lines += [f"| `{f}` | {c} | {w} |" for f, c, w in changes]
        lines.append("")
    return "\n".join(lines)


def render(spec: PortSpec, qnxtests: str | None = None, readme: str | None = None,
           patch: str | None = None) -> dict[str, str]:
    """All files of the port folder, as relative path -> text."""
    files = {
        "Makefile": TOP_MAKEFILE,
        "common.mk": render_common_mk(spec),
        "qnx.nto.toolchain.cmake": TOOLCHAIN,
        "README.md": readme if readme is not None else render_readme(spec),
    }
    for d in ARCH_DIRS.values():
        files[f"{d}/Makefile"] = ARCH_MAKEFILE
    if spec.muslflt:
        files["project_hooks.cmake"] = PROJECT_HOOKS
    if qnxtests:
        files["qnxtests.sh"] = qnxtests
    if patch:
        files["patches/qnx.patch"] = patch
    return files


def write(port_dir: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = port_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    stale = port_dir / "project_hooks.cmake"
    if "project_hooks.cmake" not in files and stale.exists():
        stale.unlink()
