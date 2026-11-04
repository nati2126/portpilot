"""cpp_text.py: comment/string stripping, preprocessor frames, guard classification."""

from __future__ import annotations

from portpilot.cpp_text import Frame, classify_guard, guard_frames, path_guard, strip_code


def test_strip_code_keeps_lines_and_blanks_literals() -> None:
    src = 'int a; // epoll_wait()\n/* fork()\n */ char *s = "eventfd()";\nchar c = \'"\';\n'
    code, strings = strip_code(src)
    assert code.count("\n") == src.count("\n")
    assert "epoll_wait" not in code and "fork" not in code and "eventfd" not in code
    assert strings == [(3, "eventfd()")]
    assert "char c = ''" in code


def test_strip_code_raw_strings_and_digit_separators() -> None:
    src = 'auto r = R"x(fork() "quoted")x";\nint n = 1\'000\'000; int m = fork();\n'
    code, strings = strip_code(src)
    assert strings[0] == (1, 'fork() "quoted"')
    assert "fork();" in code.split("\n")[1]
    assert "1'000'000" in code


def test_guard_frames_chain_negation() -> None:
    code = "#ifdef A\n1\n#elif B\n2\n#else\n3\n#endif\n4\n"
    fr = guard_frames(code)
    assert fr[1] == (Frame("defined(A)", False),)
    assert fr[3] == (Frame("defined(A)", True), Frame("B", False))
    assert fr[5] == (Frame("defined(A)", True), Frame("B", True))
    assert fr[7] == ()


def test_guard_frames_continuation_and_raw_strings() -> None:
    raw = '#if FMT_HAS_INCLUDE("winapifamily.h") && \\\n    X\nbody\n#endif\n'
    code, _ = strip_code(raw)
    fr = guard_frames(code, raw)
    assert '"winapifamily.h"' in fr[2][0].cond
    assert "X" in fr[2][0].cond


def test_classify_guard_tokens() -> None:
    assert classify_guard((Frame("defined(NNG_PLATFORM_WINDOWS)", False),)) == "other-os"
    assert classify_guard((Frame("defined(__linux__)", False),)) == "linux"
    assert classify_guard((Frame("defined(__QNX__)", False),)) == "qnx"
    # the #else of a Windows check is compiled on QNX
    assert classify_guard((Frame("defined(_WIN32)", True),)) == "none"
    # a feature check about the same API
    assert classify_guard((Frame("defined(HAVE_EPOLL)", False),),
                          ("epoll_wait", "sys/epoll.h", "epoll")) == "feature"
    assert classify_guard((Frame("defined(HAVE_OTHER)", False),), ("epoll_wait",)) == "none"


def test_path_guard() -> None:
    assert path_guard("src/platform/windows/win_io.c") == "other-os"
    assert path_guard("src/platform/posix/posix_io.c") == "none"
    assert path_guard("src/linux/x.c") == "linux"
