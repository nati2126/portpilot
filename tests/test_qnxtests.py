"""qnxtests.sh generation from real CTest files (fmt and nng builds for QNX, tests/data/ctest)."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from portpilot.qnxtests import CTest, generate, parse_results, read_ctest, render, runnable

CT = Path(__file__).parent / "data" / "ctest"
BUILD = {"fmt": Path("/work/fmt/build"), "nng": Path("/work/nng/build")}


def load_tests(port: str) -> list[CTest]:
    ts = read_ctest(CT / port)
    for t in ts:  # fixtures were captured from /work/<port>/build
        t.exe = t.exe.replace(str(BUILD[port]), str(CT / port))
    return ts


def test_fmt_tests_read_from_bracket_names() -> None:
    ts = load_tests("fmt")
    assert len(ts) == 22
    assert ts[0].name == "args-test" and ts[0].binary == "args-test" and ts[0].args == []
    assert all(t.timeout == 60 for t in ts)


def test_nng_tests_args_and_timeouts() -> None:
    ts = {t.name: t for t in load_tests("nng")}
    assert len(ts) == 64
    assert ts["nng.core.aio_test"].args == ["-t", "-v"]
    assert ts["nng.core.aio_test"].timeout == 180
    assert ts["nng.cplusplus_pair"].timeout == 15
    assert ts["nng.pubdrop"].args == ["inproc://junk", "64", "1000", "2", "1"]
    assert ts["nng.pubdrop"].timeout == 60  # no TIMEOUT property: the default


def test_runner_lines_match_the_verified_manual_runner() -> None:
    """The nng runner that passed 64/64 on QNX (Nov 4) had exactly these run lines."""
    ts = load_tests("nng")
    ok, skipped = runnable(ts, CT / "nng")
    assert skipped == []
    text = render(ok, "nng")
    lines = [ln for ln in text.splitlines() if ln.startswith("run ")]
    assert len(lines) == 64
    assert lines[0] == "run nng.core.aio_test 180 ./aio_test -t -v"
    assert lines[-1] == "run nng.cplusplus_pair 15 ./cplusplus_pair 13000"
    assert "run nng.pubdrop 60 ./pubdrop inproc://junk 64 1000 2 1" in lines


def test_skips_non_binaries_disabled_and_inverts_will_fail(tmp_path: Path) -> None:
    (tmp_path / "CTestTestfile.cmake").write_text(
        f'add_test(a "{tmp_path}/a")\n'
        f'add_test(b "/usr/bin/python3" "x.py")\n'
        f'add_test(c "{tmp_path}/c")\n'
        'set_tests_properties(c PROPERTIES  DISABLED "ON")\n'
        f'add_test(d "{tmp_path}/d" "--arg with space")\n'
        'set_tests_properties(d PROPERTIES  WILL_FAIL "TRUE" TIMEOUT "2.5")\n'
        "add_test(e NOT_AVAILABLE)\n")
    text, ok = generate(tmp_path, "demo")
    assert [t.name for t in ok] == ["a", "d"]
    assert "# skipped b: runs /usr/bin/python3" in text
    assert "# skipped c: DISABLED in CTest" in text
    assert "INVERT=1 run d 2 ./d '--arg with space'; INVERT=" in text


@pytest.mark.skipif(shutil.which("sh") is None or shutil.which("sleep") is None,
                    reason="needs a POSIX shell")
def test_runner_executes(tmp_path: Path) -> None:
    for name, body in {"ok": "exit 0", "bad": "exit 3", "slow": "sleep 5",
                       "neg": "exit 1"}.items():
        p = tmp_path / name
        p.write_text(f"#!/bin/sh\n{body}\n")
        p.chmod(0o755)
    ts = [CTest("t.ok", str(tmp_path / "ok"), []), CTest("t.bad", str(tmp_path / "bad"), []),
          CTest("t.slow", str(tmp_path / "slow"), [], timeout=1),
          CTest("t.neg", str(tmp_path / "neg"), [], will_fail=True)]
    (tmp_path / "qnxtests.sh").write_text(render(ts, "demo"))
    r = subprocess.run(["sh", str(tmp_path / "qnxtests.sh")], capture_output=True, text=True,
                       timeout=30)
    results, summary = parse_results(r.stdout)
    assert {t.name: t.status for t in results} == {"t.ok": "PASS", "t.bad": "FAIL",
                                                   "t.slow": "TIMEOUT", "t.neg": "PASS"}
    assert summary == (2, 2, 1, 4)
    assert r.returncode != 0
    assert (tmp_path / "logs" / "t.ok.out").exists()


@pytest.mark.skipif(shutil.which("sh") is None or shutil.which("pgrep") is None,
                    reason="needs a POSIX shell and pgrep")
def test_runner_leaves_no_watchdog_behind(tmp_path: Path) -> None:
    """A leftover watchdog kept the QNX ssh session open for the whole timeout (180 s for a
    0 s test, Nov 4). The watchdog must be gone shortly after the test ends."""
    ok = tmp_path / "ok"
    ok.write_text("#!/bin/sh\nexit 0\n")
    ok.chmod(0o755)
    (tmp_path / "qnxtests.sh").write_text(render([CTest("t.ok", str(ok), [], timeout=97)],
                                                 "demo"))
    # own session: whatever the runner leaves behind keeps that session id
    p = subprocess.Popen(["sh", str(tmp_path / "qnxtests.sh")], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    p.wait(timeout=30)

    def left() -> str:
        return subprocess.run(["pgrep", "-a", "-s", str(p.pid)], capture_output=True,
                              text=True).stdout.strip()
    for _ in range(30):  # the watchdog polls once a second
        if not left():
            break
        time.sleep(0.2)
    assert not left(), f"left behind: {left()}"


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_runner_stops_when_every_program_hangs(tmp_path: Path) -> None:
    hang = tmp_path / "hang"
    hang.write_text("#!/bin/sh\nsleep 30\n")
    hang.chmod(0o755)
    ts = [CTest(f"t.{i}", str(hang), [], timeout=1) for i in range(10)]
    (tmp_path / "qnxtests.sh").write_text(render(ts, "demo"))
    r = subprocess.run(["sh", str(tmp_path / "qnxtests.sh")], capture_output=True, text=True,
                       timeout=60, env={"ABORT_AFTER_TIMEOUTS": "2", "PATH": "/usr/bin:/bin"})
    results, summary = parse_results(r.stdout)
    assert [t.status for t in results] == ["TIMEOUT", "TIMEOUT"]
    assert "QNXTEST-ABORT" in r.stdout and summary == (0, 2, 2, 2)


def test_parse_results_from_a_real_run() -> None:
    out = ("QNXTEST nng.core.aio_test PASS rc=0 secs=12\n"
           "QNXTEST nng.sp.x FAIL rc=1 secs=3 (see logs/nng.sp.x.out)\n"
           "QNXTEST nng.sp.y TIMEOUT rc=137 secs=540 limit=540\n"
           "QNXTEST-SUMMARY pass=1 fail=2 timeout=1 total=3\n")
    results, summary = parse_results(out)
    assert [(r.name, r.status, r.seconds) for r in results] == [
        ("nng.core.aio_test", "PASS", 12), ("nng.sp.x", "FAIL", 3), ("nng.sp.y", "TIMEOUT", 540)]
    assert summary == (1, 2, 1, 3)


def test_count_cases_from_framework_summaries() -> None:
    from portpilot.qnxtests import count_cases
    gtest = ("[==========] 1008 tests from 16 test suites ran. (52 ms total)\n"
             "[  PASSED  ] 1007 tests.\n[  FAILED  ] 1 test, listed below:\n")
    assert count_cases(gtest) == (1007, 1008)
    assert count_cases("All tests passed (311 assertions in 42 test cases)\n") == (42, 42)
    assert count_cases("test cases:  42 |  40 passed | 2 failed\n") == (40, 42)
    assert count_cases("80%: Checks: 10, Failures: 1, Errors: 1\n"
                       "100%: Checks: 5, Failures: 0, Errors: 0\n") == (13, 15)
    assert count_cases("12 Tests 1 Failures 2 Ignored\n") == (9, 10)
    assert count_cases("ldd:FATAL: Could not load library libCatch2Main.so.3.5.0\n") is None


def test_run_cases_mix_counted_and_plain_programs() -> None:
    from portpilot.qnxtests import TestResult
    from portpilot.target import TestRun
    rs = [TestResult("yaml-cpp::test", "FAIL", 1, 0, [1007, 1008]),
          TestResult("plain", "PASS", 0, 0)]
    tr = TestRun("h", False, 1, 1, 0, 2, 1.0, rs)
    assert tr.cases() == (1008, 1009)
    assert TestRun("h", True, 1, 0, 0, 1, 1.0, [TestResult("p", "PASS", 0, 0)]).cases() is None


def test_stage_libs_includes_dependency_libraries(tmp_path: Path) -> None:
    """spdlog/sockpp tests need libCatch2Main.so from the Catch2 port in the stage."""
    from portpilot.target import stage_libs
    tests = tmp_path / "stage" / "x86_64" / "usr" / "local" / "bin" / "sockpp_tests"
    tests.mkdir(parents=True)
    (tests / "libsockpp.so.1").write_text("x")
    lib = tmp_path / "stage" / "x86_64" / "usr" / "local" / "lib"
    lib.mkdir()
    for n in ("libCatch2Main.so.3.5.0", "libsockpp.so.1", "libCatch2Main.a"):
        (lib / n).write_text("x")
    got = stage_libs(tests, {"libsockpp.so.1"})
    assert [p.name for p in got] == ["libCatch2Main.so.3.5.0"]
