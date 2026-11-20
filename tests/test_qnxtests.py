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
    assert [t.status for t in results] == ["TIMEOUT", "TIMEOUT"], r.stdout + r.stderr
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
    # Catch2 colors its summary even into a file (spdlog on QNX)
    colored = ("\x1b[1;32m====\x1b[0m\n"
               "\x1b[1;32mAll tests passed\x1b[0m (588 assertions in 180 test cases)\n")
    assert count_cases(colored) == (180, 180)


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


def test_boot_problem_bridge_without_dhcp(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from portpilot import target
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "qemu.out").write_text("---> Starting sshd\nStartup complete\n")
    monkeypatch.setattr(target, "_bridge_without_dhcp", lambda: True)
    assert "net-start default" in target.boot_problem(tmp_path)
    monkeypatch.setattr(target, "_bridge_without_dhcp", lambda: False)
    assert target.boot_problem(tmp_path) == ""


def test_point_localhost_rewrites_only_test_arguments() -> None:
    from portpilot.qnxtests import point_localhost

    ts = [CTest("t1", "/b/test1", ["--connection", "tcp://localhost:1883"]),
          CTest("t2", "/b/test2", ["ws://127.0.0.1:1883", "--name", "localhost.example"]),
          CTest("t3", "/b/test3", ["--proxy", "localhost"], will_fail=True)]
    out = point_localhost(render(ts, "demo"), "192.168.122.1")
    assert "./test1 --connection tcp://192.168.122.1:1883" in out
    assert "ws://192.168.122.1:1883 --name localhost.example" in out  # a longer name stays
    assert "INVERT=1 run t3 60 ./test3 --proxy 192.168.122.1" in out
    assert "cd \"$(dirname" in out and out.count("192.168.122.1") == 3  # runner body intact


def test_host_address_is_the_route_source() -> None:
    from portpilot.target import host_address

    assert host_address("127.0.0.1") == "127.0.0.1"


class _FakeTarget:
    """Records ssh/scp calls; answers like a target where the service keeps running."""

    host = "10.0.0.2"

    def __init__(self, alive: bool = True) -> None:
        self.cmds: list[str] = []
        self.alive = alive
        self.proc: subprocess.Popen[bytes] | None = None

    def ssh(self, command: str, **_: object) -> subprocess.CompletedProcess[str]:
        self.cmds.append(command)
        rc = 0
        if command.startswith("kill -0"):
            rc = 0 if self.alive else 1
        elif command.startswith("kill ") and self.proc is not None:
            self.proc.terminate()
        return subprocess.CompletedProcess(command, rc, "", "")

    def scp_to(self, files: list[Path], dest: str) -> None:
        self.cmds.append(f"scp {' '.join(f.name for f in files)} {dest}")

    def ssh_popen(self, command: str, out: Path) -> subprocess.Popen[bytes]:
        """The service session: prints the pid line; a dead service exits at once."""
        self.cmds.append(command)
        out.write_text("QNXSVC-PID 4242\n" + ("" if self.alive else
                                             "Error: Unable to open config file.\n"))
        self.proc = subprocess.Popen(["sleep", "30"] if self.alive else ["true"])
        return self.proc

    def scp_from(self, src: str, dest: Path) -> bool:
        self.cmds.append(f"scp-from {src}")
        return True


def test_service_runs_in_its_own_session_and_stops(tmp_path: Path) -> None:
    from portpilot.target import parse_service, start_service, stop_service

    (tmp_path / "mosquitto").mkdir()
    svc = parse_service(f"{tmp_path / 'mosquitto'}=sbin/mosquitto -c etc/test.conf")
    assert (svc.name, svc.command) == ("mosquitto", "sbin/mosquitto -c etc/test.conf")
    t = _FakeTarget()
    start_service(t, svc, tmp_path / "logs", settle=0)  # type: ignore[arg-type]
    start = next(c for c in t.cmds if "QNXSVC-PID" in c)
    assert start.startswith("cd /data/services/mosquitto && echo QNXSVC-PID $$ && export "
                            "LD_LIBRARY_PATH=/data/services/mosquitto/lib:")
    assert start.endswith("exec sbin/mosquitto -c etc/test.conf")  # pid = the shell's $$
    assert svc.pid == 4242 and svc.proc.poll() is None
    t.cmds.clear()
    stop_service(t, svc)  # type: ignore[arg-type]
    assert t.cmds[0].startswith("kill 4242") and svc.proc.poll() is not None


def test_service_that_exits_is_reported_with_its_log(tmp_path: Path) -> None:
    from portpilot.target import TargetError, parse_service, start_service

    (tmp_path / "broker").mkdir()
    with pytest.raises(TargetError, match="Unable to open config file"):
        start_service(_FakeTarget(alive=False),  # type: ignore[arg-type]
                      parse_service(f"{tmp_path / 'broker'}=./broker"), tmp_path, settle=0)
    with pytest.raises(TargetError, match="DIR=COMMAND"):
        parse_service(str(tmp_path / "broker"))


def test_unregistered_test_program(tmp_path: Path) -> None:
    # libcoap builds its CUnit testdriver but never calls add_test
    b = tmp_path / "build"
    (b / "CMakeFiles" / "testdriver.dir" / "tests").mkdir(parents=True)
    (b / "CMakeFiles" / "testdriver.dir" / "tests" / "testdriver.c.o").write_text("")
    (b / "CMakeFiles" / "coap-3.dir" / "src").mkdir(parents=True)
    (b / "CMakeFiles" / "coap-3.dir" / "src" / "net.c.o").write_text("")
    (b / "CMakeFiles" / "coap-3.dir" / "tests").mkdir()
    for exe in ("testdriver", "coap-3"):
        (b / exe).write_text("")
        (b / exe).chmod(0o755)
    text, tests = generate(b, "libcoap")
    assert [t.name for t in tests] == ["testdriver"]
    assert "run testdriver 60 ./testdriver" in text


def test_count_cunit_cases() -> None:
    from portpilot.qnxtests import count_cases
    out = ("Run Summary:    Type  Total    Ran Passed Failed Inactive\n"
           "              suites     12     12    n/a      0        0\n"
           "               tests    150    148    146      2        0\n"
           "             asserts   1009   1009   1007      2      n/a\n")
    assert count_cases(out) == (146, 148)
