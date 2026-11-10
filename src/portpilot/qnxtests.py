"""Generate qnxtests.sh, a self-contained test runner for the QNX target, from CTest files.

The runner needs only /bin/sh on the target. It runs from the directory that holds the test
binaries and the port's shared libraries:

    sh qnxtests.sh                     # CTest timeouts as-is
    TIMEOUT_SCALE=3 sh qnxtests.sh     # slower targets such as QEMU

It prints `QNXTEST <name> PASS|FAIL|TIMEOUT rc=N secs=S`, keeps each log in ./logs/<name>.out,
ends with `QNXTEST-SUMMARY pass=P fail=F timeout=T total=N` and exits non-zero on any failure.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TIMEOUT = 60  # seconds, for tests without a CTest TIMEOUT

_ADD = re.compile(r"^add_test\((\S+)\s+(.*)\)\s*$")
_PROPS = re.compile(r"^set_tests_properties\((\S+)\s+PROPERTIES\s+(.*)\)\s*$")
_BRACKET = re.compile(r"^\[=*\[(.*)\]=*\]$")


@dataclass
class CTest:
    name: str
    exe: str  # absolute path in the build tree, as CTest has it
    args: list[str]
    timeout: int = DEFAULT_TIMEOUT
    will_fail: bool = False
    disabled: bool = False

    @property
    def binary(self) -> str:
        return os.path.basename(self.exe)


def _name(token: str) -> str:
    m = _BRACKET.match(token)
    return m.group(1) if m else token


_INCLUDE = re.compile(r'^\s*include\("([^"]+)"\)\s*$', re.M)
_TEST_EXE = re.compile(r'TEST_EXECUTABLE\s*(?:\[=*\[(?P<b>[^\]]+)\]=*\]|"(?P<q>[^"]+)")')


def _discovered_exe(include: Path, depth: int = 0) -> str:
    """The test program a gtest_discover_tests/catch_discover_tests include file runs."""
    try:
        text = include.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if m := _TEST_EXE.search(text):
        return m.group("b") or m.group("q")
    for inner in _INCLUDE.finditer(text) if depth < 2 else ():
        if "${" not in inner.group(1) and (exe := _discovered_exe(Path(inner.group(1)),
                                                                  depth + 1)):
            return exe
    return ""


def read_ctest(build_dir: Path) -> list[CTest]:
    """All tests in a configured CMake build tree, in CTestTestfile.cmake order."""
    tests: list[CTest] = []
    by_name: dict[str, CTest] = {}
    for d, _, files in sorted(os.walk(build_dir)):
        if "CTestTestfile.cmake" not in files:
            continue
        text = Path(d, "CTestTestfile.cmake").read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if m := _ADD.match(line):
                argv = shlex.split(m.group(2))
                if not argv or argv[0] == "NOT_AVAILABLE":
                    continue
                t = CTest(_name(m.group(1)), argv[0], argv[1:])
                tests.append(t)
                by_name[t.name] = t
            elif m := _INCLUDE.match(line):
                # gtest/Catch2 discovery at test time (DISCOVERY_MODE PRE_TEST): the cases
                # are listed by running the program, so run the whole program as one test
                exe = _discovered_exe(Path(m.group(1)))
                if exe and exe not in {t.exe for t in tests}:
                    # no spaces in the name: results are parsed as `QNXTEST <name> ...`
                    t = CTest(os.path.basename(exe) + ".all-cases", exe, [])
                    tests.append(t)
            elif (m := _PROPS.match(line)) and (t2 := by_name.get(_name(m.group(1)))):
                props = m.group(2)
                if to := re.search(r'\bTIMEOUT\s+"(\d+(?:\.\d+)?)"', props):
                    t2.timeout = max(1, round(float(to.group(1))))
                t2.will_fail = bool(re.search(r'\bWILL_FAIL\s+"(?:ON|TRUE|1|YES)"', props, re.I))
                t2.disabled = bool(re.search(r'\bDISABLED\s+"(?:ON|TRUE|1|YES)"', props, re.I))
    return tests


def runnable(tests: list[CTest], build_dir: Path) -> tuple[list[CTest], list[tuple[CTest, str]]]:
    """Split into tests whose program is a binary built in the tree, and skipped ones."""
    root = str(build_dir).rstrip("/") + "/"
    ok: list[CTest] = []
    skipped: list[tuple[CTest, str]] = []
    for t in tests:
        if t.disabled:
            skipped.append((t, "DISABLED in CTest"))
        elif not t.exe.startswith(root):
            skipped.append((t, f"runs {t.exe}, not a test binary from the build"))
        else:
            ok.append(t)
    return ok, skipped


_HEAD = [
    'here=$(cd "$(dirname "$0")" && pwd); cd "$here" || exit 1',
    'export LD_LIBRARY_PATH="$here${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"',
    "S=${TIMEOUT_SCALE:-1}; mkdir -p logs; pass=0; fail=0; tmo=0",
    "",
    "run() {  # run <name> <timeout> <cmd...>",
    "  n=$1; to=$(( $2 * S )); shift 2; s=$(date +%s)",
    '  "$@" > "logs/$n.out" 2>&1 </dev/null & p=$!',
    "  # watchdog: polls each second, so no stray sleep outlives the test (a leftover",
    "  # 'sleep $to' kept the ssh session open for the full timeout)",
    "  # it leaves a marker when it kills: exit codes and whole-second clocks are not",
    "  # reliable timeout evidence under load or across shells",
    "  rm -f \"logs/$n.killed\"",
    "  ( i=0; while [ $i -lt $to ]; do sleep 1; kill -0 $p 2>/dev/null || exit 0;",
    "    i=$((i+1)); done; : > \"logs/$n.killed\"; kill -9 $p ) >/dev/null 2>&1 </dev/null & w=$!",
    "  wait $p; rc=$?; kill $w 2>/dev/null; wait $w 2>/dev/null; e=$(( $(date +%s) - s ))",
    "  [ $e -ge 0 ] || e=0  # the clock can step back (WSL time sync under load)",
    "  if [ -e \"logs/$n.killed\" ]; then rm -f \"logs/$n.killed\"",
    "    tmo=$((tmo+1)); fail=$((fail+1))",
    '    echo "QNXTEST $n TIMEOUT rc=$rc secs=$e limit=$to"',
    "    if [ $pass -eq 0 ] && [ $tmo -ge ${ABORT_AFTER_TIMEOUTS:-3} ]; then  # all hang: stop",
    '      echo "QNXTEST-ABORT the first $tmo tests timed out: the programs probably hang"',
    '      echo "QNXTEST-SUMMARY pass=$pass fail=$fail timeout=$tmo total=$((pass+fail))"',
    "      exit 2; fi; return; fi",
    '  [ -n "$INVERT" ] && { [ $rc -eq 0 ] && rc=1 || rc=0; }  # CTest WILL_FAIL',
    '  if [ $rc -eq 0 ]; then pass=$((pass+1)); echo "QNXTEST $n PASS rc=0 secs=$e"',
    '  else fail=$((fail+1)); echo "QNXTEST $n FAIL rc=$rc secs=$e (see logs/$n.out)"; fi',
    "}",
    "",
]


def render(tests: list[CTest], port: str, skipped: list[tuple[CTest, str]] | None = None) -> str:
    out = [
        "#!/bin/sh",
        f"# QNX test runner for {port}: {len(tests)} tests, generated from CTest by PortPilot.",
        "# Run from anywhere: sh qnxtests.sh   (set TIMEOUT_SCALE=3 on QEMU)",
        *_HEAD,
    ]
    for t, why in skipped or []:
        out.append(f"# skipped {t.name}: {why}")
    for t in tests:
        cmd = ["run", shlex.quote(t.name), str(t.timeout), "./" + t.binary,
               *[shlex.quote(a) for a in t.args]]
        line = " ".join(cmd)
        out.append(f"INVERT=1 {line}; INVERT=" if t.will_fail else line)
    out += [
        "",
        'echo "QNXTEST-SUMMARY pass=$pass fail=$fail timeout=$tmo total=$((pass+fail))"',
        "[ $fail -eq 0 ]",
    ]
    return "\n".join(out) + "\n"


def generate(build_dir: Path, port: str) -> tuple[str, list[CTest]]:
    ok, skipped = runnable(read_ctest(build_dir), build_dir)
    return render(ok, port, skipped), ok


_LOCAL = re.compile(r"(?<![\w.-])(?:localhost|127\.0\.0\.1)(?![\w-]|\.\w)")


def point_localhost(script: str, host: str) -> str:
    """Make the test programs' arguments name `host` instead of localhost/127.0.0.1, for
    tests that talk to a service (an MQTT broker, a database) that runs on the host, not
    on the QNX target. Only the `run` lines change."""
    out = []
    for line in script.splitlines(keepends=True):
        if line.startswith(("run ", "INVERT=1 run ")):
            line = _LOCAL.sub(host, line)
        out.append(line)
    return "".join(out)


# ---- results ------------------------------------------------------------------------------
_RESULT = re.compile(r"^QNXTEST (?P<name>\S+) (?P<status>PASS|FAIL|TIMEOUT) rc=(?P<rc>-?\d+) "
                     r"secs=(?P<secs>-?\d+)")
_SUMMARY = re.compile(r"^QNXTEST-SUMMARY pass=(\d+) fail=(\d+) timeout=(\d+) total=(\d+)")


@dataclass
class TestResult:
    name: str
    status: str  # PASS | FAIL | TIMEOUT
    rc: int
    seconds: int
    cases: list[int] = field(default_factory=list)  # [passed, total] from the program's log


# Test case summaries the common frameworks print: (passed, total)
_GTEST_RAN = re.compile(r"^\[=+\] (\d+) tests? from .* ran\.", re.M)
_GTEST_PASSED = re.compile(r"^\[  PASSED  \] (\d+) tests?\.", re.M)
_CATCH_ALL = re.compile(r"^All tests passed \(\d+ assertions? in (\d+) test cases?\)", re.M)
_CATCH_SOME = re.compile(r"^test cases:\s*(\d+)\s*\|\s*(\d+) passed", re.M)
_CHECK = re.compile(r"^\d+%: Checks: (\d+), Failures: (\d+), Errors: (\d+)", re.M)
_UNITY = re.compile(r"^(\d+) Tests (\d+) Failures (\d+) Ignored", re.M)
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def count_cases(text: str) -> tuple[int, int] | None:
    """(passed, total) test cases from one program's output, for gtest, Catch2, Check and
    Unity; None if the program printed no summary (other frameworks, or it crashed)."""
    text = _ANSI.sub("", text)  # Catch2 colors its output even into a file (spdlog)
    if (ran := _GTEST_RAN.findall(text)):
        total = int(ran[-1])
        passed = _GTEST_PASSED.findall(text)
        return (int(passed[-1]) if passed else 0), total
    if m := _CATCH_ALL.search(text):
        return int(m.group(1)), int(m.group(1))
    if m := _CATCH_SOME.search(text):
        return int(m.group(2)), int(m.group(1))
    if found := _CHECK.findall(text):
        total = sum(int(c) for c, _, _ in found)
        bad = sum(int(f) + int(e) for _, f, e in found)
        return total - bad, total
    if m := _UNITY.search(text):
        total, fails, ign = (int(x) for x in m.groups())
        return total - fails - ign, total - ign
    return None


def parse_results(text: str) -> tuple[list[TestResult], tuple[int, int, int, int] | None]:
    """Parse runner output: per-test results and (pass, fail, timeout, total) if finished."""
    results: list[TestResult] = []
    summary: tuple[int, int, int, int] | None = None
    for line in text.splitlines():
        if m := _RESULT.match(line.strip()):
            results.append(TestResult(m.group("name"), m.group("status"), int(m.group("rc")),
                                      max(0, int(m.group("secs")))))
        elif s := _SUMMARY.match(line.strip()):
            p, f, t, n = (int(x) for x in s.groups())
            summary = (p, f, t, n)
    return results, summary
