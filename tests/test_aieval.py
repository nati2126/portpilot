from portpilot.aieval import Case, commands, judge, summary, suspect
from portpilot.diagnostics import Diagnostic

QCC = "/home/u/qnx800/host/linux/x86_64/usr/bin/qcc"


def _d(msg: str, file: str = "/s/a.c", kind: str = "undeclared", sym: str = "X") -> Diagnostic:
    return Diagnostic(kind=kind, severity="error", message=msg, tool="cc", file=file, line=3,
                      symbol=sym)


def _case(d: Diagnostic) -> Case:
    return Case("lib", "a.c", "/s/a.c", "/b", "qcc -c /s/a.c", d.to_dict())


def test_commands_from_a_verbose_cmake_log() -> None:
    log = (f"cd /b/src && {QCC} -Vgcc_ntox86_64 -DX=\\\"y\\\" -I/s/include -o "
           "CMakeFiles/l.dir/a.c.o -c /s/a.c\n"
           "[ 50%] Building C object ...\n"
           f"cd /b && {QCC} -Vgcc_ntox86_64_cxx -o t.o -c /s/t.cpp   \n")
    c = commands(log)
    assert set(c) == {"/s/a.c", "/s/t.cpp"}
    assert c["/s/a.c"][0] == "/b/src" and "-DX=" in c["/s/a.c"][1]


def test_judge_needs_the_error_gone_and_nothing_new_in_the_edited_file() -> None:
    target = _d("'X' undeclared")
    other = _d("'Y' undeclared", sym="Y")
    case = _case(target)
    assert judge(case, [target], [], {"a.c"})[0]
    assert judge(case, [target, other], [other], {"a.c"})[0]  # an old error may stay
    assert judge(case, [target], [target], {"a.c"}) == (False, "error still there")
    new = _d("'Z' undeclared", sym="Z")
    ok, why = judge(case, [target], [new], {"a.c"})
    assert not ok and why.startswith("new errors")
    assert judge(case, [target], [_d("'Z' undeclared", file="/s/b.c", sym="Z")], {"a.c"})[0]


def test_suspect_edits() -> None:
    assert suspect([{"search": "f();\ng();", "replace": "f();"}]) == "only deletes lines"
    assert suspect([{"search": "g();", "replace": "#if 0\ng();\n#endif"}]) == \
        "disables code with #if 0"
    assert suspect([{"search": "g();", "replace": "// g();"}]) == "comments code out"
    assert suspect([{"search": "#include <a.h>", "replace": "#include <a.h>\n#include <b.h>"}]) \
        == ""


def test_summary_counts() -> None:
    a, b = _case(_d("'X' undeclared")), _case(_d("'Y' undeclared", sym="Y"))
    a.results = {"rules": {"ok": True}, "bare": {"ok": False}, "grounded": {"ok": False}}
    b.results = {"rules": {"ok": False}, "bare": {"ok": False},
                 "grounded": {"ok": True, "suspect": ""}}
    s = summary([a, b], "m")
    assert "| Rules only | 1/2 (50%) |" in s
    assert "| Rules, then AI with QNX facts | 2/2 (100%) |" in s
    assert "no rule fixes: AI without facts fixes 0/1 (0%), with facts 1/1 (100%)" in s


def test_keep_build_edits_only_copies_cmake_files(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from portpilot.aieval import keep_build_edits

    ported, src = tmp_path / "ported", tmp_path / "src"
    for root, cm, c in ((ported, "qnx", "fixed();"), (src, "linux", "orig();")):
        (root / "cmake").mkdir(parents=True)
        (root / "CMakeLists.txt").write_text(cm)
        (root / "cmake" / "Arch.cmake").write_text(cm)
        (root / "a.c").write_text(c)
    assert keep_build_edits(ported, src) == ["CMakeLists.txt", "cmake/Arch.cmake"]
    assert (src / "cmake" / "Arch.cmake").read_text() == "qnx"
    assert (src / "a.c").read_text() == "orig();"
