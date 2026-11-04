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
from dataclasses import dataclass
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
    '  "$@" > "logs/$n.out" 2>&1 & p=$!; ( sleep $to; kill -9 $p ) >/dev/null 2>&1 & w=$!',
    "  wait $p; rc=$?; kill $w 2>/dev/null; e=$(( $(date +%s) - s ))",
    "  if [ $rc -eq 137 ] && [ $e -ge $to ]; then tmo=$((tmo+1)); fail=$((fail+1))",
    '    echo "QNXTEST $n TIMEOUT rc=$rc secs=$e limit=$to"; return; fi',
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


# ---- results ------------------------------------------------------------------------------
_RESULT = re.compile(r"^QNXTEST (?P<name>\S+) (?P<status>PASS|FAIL|TIMEOUT) rc=(?P<rc>-?\d+) "
                     r"secs=(?P<secs>\d+)")
_SUMMARY = re.compile(r"^QNXTEST-SUMMARY pass=(\d+) fail=(\d+) timeout=(\d+) total=(\d+)")


@dataclass
class TestResult:
    name: str
    status: str  # PASS | FAIL | TIMEOUT
    rc: int
    seconds: int


def parse_results(text: str) -> tuple[list[TestResult], tuple[int, int, int, int] | None]:
    """Parse runner output: per-test results and (pass, fail, timeout, total) if finished."""
    results: list[TestResult] = []
    summary: tuple[int, int, int, int] | None = None
    for line in text.splitlines():
        if m := _RESULT.match(line.strip()):
            results.append(TestResult(m.group("name"), m.group("status"), int(m.group("rc")),
                                      int(m.group("secs"))))
        elif s := _SUMMARY.match(line.strip()):
            p, f, t, n = (int(x) for x in s.groups())
            summary = (p, f, t, n)
    return results, summary
